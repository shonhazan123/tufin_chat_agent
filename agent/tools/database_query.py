"""Database query tool — LLM generates SQL SELECT; validated and executed on catalog.db."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

import aiosqlite
from langchain_core.messages import HumanMessage, SystemMessage

from agent.config_loader import load_config
from agent.llm_provider_factory import get_llm_semaphore
from agent.token_usage_tracker import record_llm_call
from agent.tools.tool_base_classes import (
    BaseToolAgent,
    ToolInvocation,
    ToolSpec,
    UserFacingToolError,
    registry,
    strip_json_fence,
)
from scripts.seed_catalog import PRODUCTS_DDL, ORDERS_DDL

logger = logging.getLogger(__name__)

_SCHEMA_DDL = (
    PRODUCTS_DDL.replace("IF NOT EXISTS ", "")
    + "\n"
    + ORDERS_DDL.replace("IF NOT EXISTS ", "")
)

TOOL_SPEC = ToolSpec(
    name="database_query",
    type="llm",
    purpose=(
        "Query a product-catalog database (products and orders tables) to answer "
        "data questions such as product lookups, order summaries, revenue, stock levels, "
        "and customer order history."
    ),
    output_schema={
        "columns": list,
        "rows": list,
        "row_count": int,
        "sql_query": str,
    },
    input_schema={
        "question": (
            "str — natural language question about the product catalog "
            "(e.g. 'most expensive product', 'total revenue from shipped orders', "
            "'orders placed by Alice Johnson')"
        ),
    },
    system_prompt=(
        "## Role\n"
        "You are a **SQL specialist** for a product-catalog database. You convert a "
        "natural-language question into a single **SQLite SELECT** query.\n\n"
        "## Priority order (resolve conflicts using this)\n"
        "1. **Strict JSON** — output only the required JSON object.\n"
        "2. **SELECT only** — never produce INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, "
        "or any other mutating statement.\n"
        "3. **Schema compliance** — use only the tables and columns below.\n"
        "4. **User intent** — infer the intended query from the question and context.\n\n"
        "## Database schema\n"
        f"```sql\n{_SCHEMA_DDL}\n```\n\n"
        "## Column notes\n"
        "- `products.category`: one of Electronics, Clothing, Home, Sports, Books.\n"
        "- `orders.status`: one of pending, shipped, delivered, cancelled.\n"
        "- Date columns are ISO-8601 strings (e.g. '2026-01-15 09:30:00'); use SQLite "
        "date/time functions for date arithmetic.\n"
        "- `orders.total_price` = `products.price * orders.quantity` (pre-computed).\n\n"
        "## Output contract\n"
        "Return **only** this JSON shape (no markdown, no prose):\n"
        '  {"sql_query": "<single SELECT statement>"}\n\n'
        "## Query rules\n"
        "1. **SELECT only** — no semicolons, no multiple statements, no CTEs with "
        "INSERT/UPDATE.\n"
        "2. **JOINs** — use `JOIN products ON orders.product_id = products.id` when "
        "the question spans both tables.\n"
        "3. **Aggregations** — use COUNT, SUM, AVG, MIN, MAX with GROUP BY as needed.\n"
        "4. **Ordering** — add ORDER BY when the question implies ranking or sorting.\n"
        "5. **Limit** — add LIMIT when the question asks for top-N; otherwise omit "
        "(the system enforces a safety cap).\n\n"
        "## Format\n"
        "Raw JSON object only — no code fences, no explanation.\n"
    ),
    default_ttl_seconds=120,
)

_MUTATING_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|ATTACH|DETACH|REINDEX|VACUUM|PRAGMA)\b",
    re.IGNORECASE,
)

_SQL_COMMENT = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.DOTALL)


def _strip_sql_comments(sql: str) -> str:
    return _SQL_COMMENT.sub("", sql).strip()


def validate_sql(sql: str) -> str:
    """Validate that *sql* is a single SELECT and return it cleaned.

    Raises ``UserFacingToolError`` for any mutation or structurally invalid query.
    """
    cleaned = _strip_sql_comments(sql).rstrip(";").strip()
    if not cleaned:
        raise UserFacingToolError("The generated query was empty.")

    if not cleaned.upper().lstrip().startswith("SELECT"):
        raise UserFacingToolError(
            "Only SELECT queries are allowed on the product catalog."
        )

    if _MUTATING_PATTERN.search(cleaned):
        raise UserFacingToolError(
            "The query contains a disallowed statement. Only SELECT queries are permitted."
        )

    if ";" in cleaned:
        raise UserFacingToolError(
            "Multiple statements are not allowed; use a single SELECT query."
        )

    return cleaned


def ensure_limit(sql: str, max_rows: int = 50) -> str:
    """Append ``LIMIT max_rows`` if the outermost query does not already have one.

    Only inspects text after the last closing parenthesis (or the full query if
    there are none) so that a LIMIT inside a subquery does not suppress the cap.
    """
    outer_tail = sql.rsplit(")", 1)[-1] if ")" in sql else sql
    if re.search(r"\bLIMIT\b", outer_tail, re.IGNORECASE):
        return sql
    return f"{sql} LIMIT {max_rows}"


def _resolve_db_path() -> Path:
    config = load_config()
    tool_config = config.get("tools", {}).get("database_query", {})
    raw_path = tool_config.get("db_path", "./data/catalog.db")
    return Path(raw_path)


async def execute_query(sql: str, db_path: Path) -> dict[str, Any]:
    """Run a validated SELECT against the catalog in read-only mode."""
    uri = f"file:{db_path}?mode=ro"
    async with aiosqlite.connect(uri, uri=True) as db:
        cursor = await db.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = await cursor.fetchall()

    rows_as_lists = [list(row) for row in rows]
    return {
        "columns": columns,
        "rows": rows_as_lists,
        "row_count": len(rows_as_lists),
        "sql_query": sql,
    }


@registry.register(TOOL_SPEC)
class DatabaseQueryAgent(BaseToolAgent):
    def __init__(self) -> None:
        super().__init__()
        self._db_path = _resolve_db_path()
        config = load_config()
        self._max_rows: int = config.get("tools", {}).get("database_query", {}).get("max_rows", 50)
        self._catalog_available = True
        self._ensure_catalog()

    def _ensure_catalog(self) -> None:
        """Auto-seed the catalog DB on first use if it does not exist."""
        if str(self._db_path) == ":memory:" or self._db_path.exists():
            return
        try:
            from scripts.seed_catalog import seed_catalog_db

            logger.info("Catalog DB not found at %s — seeding now", self._db_path)
            seed_catalog_db(self._db_path)
        except Exception:
            logger.exception("Auto-seed of catalog DB failed")
            self._catalog_available = False

    async def _generate_sql(self, tool_invocation: ToolInvocation) -> str:
        """Call the tool LLM to produce a SQL SELECT from the user question."""
        question = (
            (tool_invocation.planner_params.get("question") or "").strip()
            or tool_invocation.sub_task
        )
        parts = [
            f"User request: {tool_invocation.user_msg}",
            f"Data question: {question}",
            f"Conversation context (summary): {tool_invocation.context_summary or '(none)'}",
            f"Prior tool results: {json.dumps(tool_invocation.prior_results, default=str)}",
            "Reply with a single JSON object only — no markdown, no fences, "
            "no explanation outside the JSON.",
        ]
        human_content = "\n".join(parts)
        sql_specialist_prompt = self.spec.system_prompt or ""
        messages = [
            SystemMessage(content=sql_specialist_prompt),
            HumanMessage(content=human_content),
        ]
        async with get_llm_semaphore():
            result = await asyncio.wait_for(
                self.llm.ainvoke(messages),
                timeout=self.timeout,
            )
        record_llm_call(
            f"tool:{self.spec.name}", result, messages=messages, model=self.llm.model_name
        )
        raw = strip_json_fence(result.content)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UserFacingToolError(
                "Could not generate a valid database query. Try rephrasing your question."
            ) from exc
        if not isinstance(parsed, dict):
            raise UserFacingToolError(
                "Could not generate a valid database query. Try rephrasing your question."
            )
        sql = parsed.get("sql_query", "")
        if not isinstance(sql, str) or not sql.strip():
            raise UserFacingToolError("The model did not produce a valid SQL query.")
        return sql.strip()

    async def _tool_executor(self, tool_invocation: ToolInvocation) -> dict[str, Any]:
        if not self._catalog_available:
            raise UserFacingToolError(
                "The product catalog database is not available. "
                "Please contact the administrator."
            )

        question = (tool_invocation.planner_params.get("question") or "").strip()
        if not question and not tool_invocation.sub_task:
            raise UserFacingToolError(
                "No question was provided for the database query tool."
            )

        sql_raw = await self._generate_sql(tool_invocation)
        sql_safe = validate_sql(sql_raw)
        sql_final = ensure_limit(sql_safe, self._max_rows)

        return await execute_query(sql_final, self._db_path)
