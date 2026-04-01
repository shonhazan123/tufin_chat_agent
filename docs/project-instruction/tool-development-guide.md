# Tool Development Guide

## Adding a New Tool

Adding a tool requires exactly **one new file** + **one config block**. No other files change.

### Step 1: Create the Tool File

Create `agent/tools/your_tool.py`. The autodiscovery loop in `agent/tools/__init__.py` imports all `.py` files in the directory (excluding `__init__.py` and `base.py`).

### Step 2: Choose Tool Type

**LLM Tool** (`type: "llm"`) — for tools that need natural language understanding to extract API parameters:

```python
from agent.tools.base import ToolSpec, BaseToolAgent, registry

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
    async def _tool_executer(self, params: dict) -> dict:
        # params extracted by the LLM from the user's sub_task
        result = await call_your_api(**params)
        return {"field_a": result["val"], "field_b": result["label"]}
```

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

### Files That Never Change When Adding a Tool

- `graph.py` — graph structure is tool-agnostic
- `graph_nodes.py` — executor uses registry lookup
- `main.py` — API layer is tool-agnostic
- `base.py` — base classes and registry
- `__init__.py` — autodiscovery is automatic
- Any existing tool file

### Contracts

- `run()` (LLM tools) must return a `dict` with all fields declared in `output_schema`
- `call()` (function tools) must return a `dict` with all fields declared in `output_schema`
- The tool's `name` must match the key used under `tools:` in `config/shared.yaml` and `agents:` in each provider YAML
- All HTTP calls must use `aiohttp`, never `requests`
- CPU-bound work should use `ThreadPoolExecutor`
