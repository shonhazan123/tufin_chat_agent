"""Tests for the database query tool — SQL validation, limit enforcement, and _tool_executor."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.tools.base import ToolInvocation, UserFacingToolError
from agent.tools.database_query import (
    DatabaseQueryAgent,
    ensure_limit,
    validate_sql,
)
from scripts.seed_catalog import PRODUCTS_DDL, ORDERS_DDL


# ---------------------------------------------------------------------------
# validate_sql
# ---------------------------------------------------------------------------

class TestValidateSql:
    def test_simple_select_allowed(self):
        sql = "SELECT name, price FROM products"
        assert validate_sql(sql) == "SELECT name, price FROM products"

    def test_select_with_join_allowed(self):
        sql = (
            "SELECT p.name, o.quantity FROM orders o "
            "JOIN products p ON o.product_id = p.id"
        )
        assert validate_sql(sql) == sql

    def test_select_with_aggregation_allowed(self):
        sql = "SELECT category, COUNT(*) AS cnt FROM products GROUP BY category"
        assert validate_sql(sql) == sql

    def test_trailing_semicolon_stripped(self):
        assert validate_sql("SELECT 1;") == "SELECT 1"

    def test_insert_blocked(self):
        with pytest.raises(UserFacingToolError, match="Only SELECT"):
            validate_sql("INSERT INTO products (name) VALUES ('x')")

    def test_update_blocked(self):
        with pytest.raises(UserFacingToolError, match="Only SELECT"):
            validate_sql("UPDATE products SET price = 0")

    def test_delete_blocked(self):
        with pytest.raises(UserFacingToolError, match="Only SELECT"):
            validate_sql("DELETE FROM products")

    def test_drop_blocked(self):
        with pytest.raises(UserFacingToolError, match="Only SELECT"):
            validate_sql("DROP TABLE products")

    def test_multi_statement_with_mutation_blocked(self):
        sql = "SELECT * FROM products WHERE id IN (SELECT id FROM products); DELETE FROM products"
        with pytest.raises(UserFacingToolError, match="disallowed"):
            validate_sql(sql)

    def test_select_with_hidden_delete_keyword_blocked(self):
        sql = "SELECT 1 UNION ALL DELETE FROM products"
        with pytest.raises(UserFacingToolError, match="disallowed"):
            validate_sql(sql)

    def test_empty_query_raises(self):
        with pytest.raises(UserFacingToolError, match="empty"):
            validate_sql("")

    def test_non_select_raises(self):
        with pytest.raises(UserFacingToolError, match="Only SELECT"):
            validate_sql("EXPLAIN SELECT 1")

    def test_comment_stripped_before_validation(self):
        sql = "SELECT 1 /* this is a comment with DELETE in it */"
        assert validate_sql(sql) == "SELECT 1"

    def test_line_comment_stripped(self):
        sql = "SELECT 1 -- DROP TABLE products"
        assert validate_sql(sql) == "SELECT 1"


# ---------------------------------------------------------------------------
# ensure_limit
# ---------------------------------------------------------------------------

class TestEnsureLimit:
    def test_appends_limit_when_missing(self):
        result = ensure_limit("SELECT * FROM products", 50)
        assert result == "SELECT * FROM products LIMIT 50"

    def test_preserves_existing_limit(self):
        sql = "SELECT * FROM products LIMIT 10"
        assert ensure_limit(sql, 50) == sql

    def test_preserves_existing_limit_case_insensitive(self):
        sql = "SELECT * FROM products limit 5"
        assert ensure_limit(sql, 50) == sql

    def test_custom_max_rows(self):
        result = ensure_limit("SELECT * FROM products", 25)
        assert result == "SELECT * FROM products LIMIT 25"

    def test_subquery_limit_does_not_suppress_outer_limit(self):
        sql = "SELECT * FROM products WHERE id IN (SELECT id FROM products LIMIT 5)"
        result = ensure_limit(sql, 50)
        assert result == f"{sql} LIMIT 50"

    def test_outer_limit_after_subquery_preserved(self):
        sql = "SELECT * FROM (SELECT * FROM products) sub LIMIT 10"
        assert ensure_limit(sql, 50) == sql


# ---------------------------------------------------------------------------
# _tool_executor integration (mocked LLM + real SQLite on disk)
# ---------------------------------------------------------------------------

def _seed_test_db(db_path: str) -> None:
    """Create a minimal catalog using the canonical DDL from seed_catalog.py."""
    conn = sqlite3.connect(db_path)
    conn.execute(PRODUCTS_DDL)
    conn.execute(ORDERS_DDL)
    conn.executemany(
        "INSERT INTO products (id, name, category, price, stock_quantity, description, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "Widget", "Electronics", 9.99, 100, "A small widget", "2026-01-01"),
            (2, "Gadget", "Electronics", 19.99, 50, "A cool gadget", "2026-01-02"),
            (3, "Book",   "Books",       14.99, 200, "A good book",   "2026-01-03"),
        ],
    )
    conn.executemany(
        "INSERT INTO orders (id, product_id, customer_name, quantity, total_price, status, order_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 1, "Alice", 2, 19.98, "delivered", "2026-02-01"),
            (2, 2, "Bob",   1, 19.99, "pending",   "2026-02-05"),
            (3, 3, "Alice", 3, 44.97, "shipped",   "2026-02-10"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def db_agent(tmp_path: Path):
    """DatabaseQueryAgent wired to a temp seeded catalog."""
    db_file = tmp_path / "catalog.db"
    _seed_test_db(str(db_file))

    with patch("agent.tools.base.build_llm") as mock_build:
        mock_llm = AsyncMock()
        mock_build.return_value = mock_llm
        agent = DatabaseQueryAgent()
        agent.llm = mock_llm
        agent._db_path = db_file
        agent._catalog_available = True
        yield agent


@pytest.mark.asyncio
async def test_tool_executor_returns_schema(db_agent):
    """_tool_executor returns all output fields when LLM produces valid SQL."""
    db_agent.llm.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"sql_query": "SELECT name, price FROM products ORDER BY price DESC"}'
        )
    )
    result = await db_agent._tool_executor(
        ToolInvocation.from_parts(
            task="What products do you have?",
            sub_task="list products",
            planner_params={"question": "list all products by price"},
        )
    )
    assert "columns" in result
    assert "rows" in result
    assert "row_count" in result
    assert "sql_query" in result
    assert result["row_count"] == 3
    assert result["columns"] == ["name", "price"]


@pytest.mark.asyncio
async def test_tool_executor_rejects_mutation(db_agent):
    """Tool must raise UserFacingToolError when LLM produces a mutation query."""
    db_agent.llm.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"sql_query": "DELETE FROM products WHERE id = 1"}'
        )
    )
    with pytest.raises(UserFacingToolError, match="Only SELECT"):
        await db_agent._tool_executor(
            ToolInvocation.from_parts(
                task="delete product 1",
                sub_task="delete",
                planner_params={"question": "delete product 1"},
            )
        )


@pytest.mark.asyncio
async def test_tool_executor_join_query(db_agent):
    """Queries spanning both tables via JOIN work correctly."""
    db_agent.llm.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"sql_query": "SELECT p.name, o.customer_name, o.total_price FROM orders o JOIN products p ON o.product_id = p.id"}'
        )
    )
    result = await db_agent._tool_executor(
        ToolInvocation.from_parts(
            task="show orders with product names",
            sub_task="join query",
            planner_params={"question": "orders with product names"},
        )
    )
    assert result["row_count"] == 3
    assert "name" in result["columns"]
    assert "customer_name" in result["columns"]


@pytest.mark.asyncio
async def test_tool_executor_empty_question_raises(db_agent):
    """Empty question with no sub_task raises UserFacingToolError."""
    with pytest.raises(UserFacingToolError, match="No question"):
        await db_agent._tool_executor(
            ToolInvocation.from_parts(
                task="",
                sub_task="",
                planner_params={"question": ""},
            )
        )


@pytest.mark.asyncio
async def test_tool_executor_aggregation(db_agent):
    """Aggregation queries (COUNT, SUM) produce correct results."""
    db_agent.llm.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"sql_query": "SELECT COUNT(*) AS order_count FROM orders"}'
        )
    )
    result = await db_agent._tool_executor(
        ToolInvocation.from_parts(
            task="how many orders",
            sub_task="count orders",
            planner_params={"question": "how many orders are there"},
        )
    )
    assert result["row_count"] == 1
    assert result["rows"][0][0] == 3


@pytest.mark.asyncio
async def test_tool_executor_empty_result_set(db_agent):
    """Query returning zero rows produces row_count 0 and empty rows list."""
    db_agent.llm.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"sql_query": "SELECT * FROM products WHERE category = \'NonExistent\'"}'
        )
    )
    result = await db_agent._tool_executor(
        ToolInvocation.from_parts(
            task="find nonexistent products",
            sub_task="empty result",
            planner_params={"question": "products in NonExistent category"},
        )
    )
    assert result["row_count"] == 0
    assert result["rows"] == []


@pytest.mark.asyncio
async def test_tool_executor_bad_json_from_llm(db_agent):
    """Unparseable JSON from LLM raises a user-facing error."""
    db_agent.llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="This is not JSON at all")
    )
    with pytest.raises(UserFacingToolError, match="Could not generate"):
        await db_agent._tool_executor(
            ToolInvocation.from_parts(
                task="some query",
                sub_task="bad json",
                planner_params={"question": "show products"},
            )
        )


@pytest.mark.asyncio
async def test_tool_executor_missing_sql_query_key(db_agent):
    """JSON without sql_query key raises a user-facing error."""
    db_agent.llm.ainvoke = AsyncMock(
        return_value=MagicMock(content='{"query": "SELECT 1"}')
    )
    with pytest.raises(UserFacingToolError, match="did not produce"):
        await db_agent._tool_executor(
            ToolInvocation.from_parts(
                task="some query",
                sub_task="missing key",
                planner_params={"question": "show products"},
            )
        )


@pytest.mark.asyncio
async def test_tool_executor_catalog_unavailable(db_agent):
    """When catalog is flagged unavailable, tool raises immediately."""
    db_agent._catalog_available = False
    with pytest.raises(UserFacingToolError, match="not available"):
        await db_agent._tool_executor(
            ToolInvocation.from_parts(
                task="query",
                sub_task="test",
                planner_params={"question": "show products"},
            )
        )
