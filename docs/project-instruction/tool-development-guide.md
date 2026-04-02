# Tool Development Guide

## Adding a New Tool

Adding a tool requires exactly **one new file** + **one config block**. Other project files usually stay unchanged unless you add cross-cutting behavior (e.g. shared error types in `agent/tools/base.py`).

### Step 1: Create The Tool File

Create `agent/tools/your_tool.py`. The autodiscovery loop in `agent/tools/__init__.py` imports all `.py` files in the directory (excluding `__init__.py` and `base.py`).

### Step 2: Choose Tool Type

**LLM Tool** (`type: "llm"`) — tools that may call `self.llm.ainvoke` **once** when planner params are missing what they need (no retry loops in `BaseToolAgent`):

```python
from agent.tools.base import BaseToolAgent, ToolInvocation, ToolSpec, registry

SPEC = ToolSpec(
    name="your_tool",
    type="llm",
    purpose="One sentence describing what this tool does.",
    output_schema={"field_a": float, "field_b": str},
    system_prompt="Domain expert prompt with rules and examples.",
    default_ttl_seconds=60,
)

YOUR_TOOL_SYSTEM = SPEC.system_prompt  # static constant

@registry.register(SPEC)
class YourToolAgent(BaseToolAgent):
    SYSTEM = YOUR_TOOL_SYSTEM

    async def _tool_executor(self, inv: ToolInvocation) -> dict:
        # inv.user_msg, inv.sub_task, inv.prior_results, inv.context_summary, inv.planner_params
        # If planner params lack required fields: get_llm_semaphore(); asyncio.wait_for(self.llm.ainvoke(...)); json.loads once.
        # Then call your API and return a dict matching output_schema.
        ...
```

`BaseToolAgent.run(state, plan_task)` wraps the graph state and current plan row in `ToolInvocation` and calls `_tool_executor` once. Do **not** add parse-retry loops in `base.py`; keep tool LLM usage to filling missing params only. Tests can use `ToolInvocation.from_parts(...)`.

**Function Tool** (`type: "function"`) — for pure computation with no LLM needed:

```python
from agent.tools.base import ToolSpec, BaseFunctionTool, registry

SPEC = ToolSpec(
    name="your_tool",
    type="function",
    purpose="One sentence for the planner.",
    output_schema={"result": float},
    input_schema={"param_a": "float — description", "param_b": "str — description"},
    default_ttl_seconds=0,
)

@registry.register(SPEC)
class YourFunctionTool(BaseFunctionTool):
    async def call(self, params: dict) -> dict:
        # params come directly from the planner's JSON plan
        return {"result": compute(params["param_a"])}
```

### Step 3: Add Config Block

Add an **agent** entry in both `config/openai.yaml` and `config/ollama.yaml` (if LLM tool), with models appropriate to each provider. Add **tool** settings and TTLs in `config/shared.yaml`:

```yaml
# config/openai.yaml or config/ollama.yaml — agents.your_tool (LLM tools only)
agents:
  your_tool:
    model: gpt-4o-mini   # or a local model id under Ollama
    max_tokens: 256
    temperature: 0
    num_ctx: 2048        # Ollama only; omit for OpenAI

# config/shared.yaml
tools:
  your_tool:
    enabled: true
    api_key: ${YOUR_TOOL_API_KEY}   # if needed

cache:
  tool_ttls:
    your_tool: 60
```

### Files that usually stay unchanged when adding a tool

- `graph.py` — graph structure is tool-agnostic
- `graph_nodes.py` — executor uses registry lookup (shared behavior such as `UserFacingToolError` lives here)
- `main.py` — API layer is tool-agnostic
- `base.py` — base classes and registry (unless you extend shared helpers)
- `__init__.py` — autodiscovery is automatic
- Any existing tool file

### Contracts

- `run()` (LLM tools) must return a `dict` with all fields declared in `output_schema`
- `call()` (function tools) must return a `dict` with all fields declared in `output_schema`
- The tool's `name` must match the key used under `tools:` in `config/shared.yaml` and `agents:` in each provider YAML
- All HTTP calls must use `aiohttp`, never `requests`
- CPU-bound work should use `ThreadPoolExecutor`

### Calculator tool (`agent/tools/calculator.py`)

- Expressions are evaluated via a whitelisted Python AST (not arbitrary `eval`).
- **Powers:** `**` is the native form; a caret `^` is normalized to `**` before parsing (school-style notation). Bitwise XOR is not supported.
- **Functions:** include `sqrt`, `cbrt` (real cube root, including negative inputs), `abs`, `round`, `sin`, `cos`, `tan`, `log`, `log10`, `ceil`, `floor`, plus constants `pi` and `e`.
- The tool `ToolSpec.system_prompt` and `input_schema` describe this dialect to the planner and to the tool’s own param-fill LLM.

### Database query tool (`agent/tools/database_query.py`)

- **LLM-to-SQL pattern:** Unlike other tools where the LLM is a fallback for missing params, the database query tool's LLM always runs because SQL generation IS its core function. The planner provides a natural-language `question`; the tool LLM converts it into a SQL SELECT statement.
- **Separate catalog database:** The tool queries `data/catalog.db` (fictional product catalog), completely separate from the app's `data/app.db`. Tables: `products` (id, name, category, price, stock_quantity, description, created_at) and `orders` (id, product_id, customer_name, quantity, total_price, status, order_date).
- **SQL validation:** Generated SQL is validated before execution — must be a SELECT statement, no mutating keywords (INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, etc.), no multiple statements (semicolons).
- **Row limit enforcement:** A LIMIT clause is appended if the query does not include one (default 50 rows, configurable via `tools.database_query.max_rows`).
- **Auto-seeding:** If `data/catalog.db` does not exist at tool registration time, the tool auto-seeds it using `scripts/seed_catalog.py`. The seeder can also be run standalone: `python scripts/seed_catalog.py`.
- The tool uses `aiosqlite` for async database access.

### User-facing tool errors (`UserFacingToolError`)

- Tools may raise `UserFacingToolError` from `agent.tools.base` with a short, user-safe message (no stack traces).
- The executor tags trace entries with `user_facing: true` and aggregates `user_facing_error` on graph state so the responder can explain the failure in plain language instead of a generic apology.
- Prefer this for failures the user can act on (e.g. unsupported function in an expression).
