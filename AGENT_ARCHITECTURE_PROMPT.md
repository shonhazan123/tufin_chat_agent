# Part 1 — Agent Architecture & Execution Engine
# Claude Code Brainstorm Prompt

This is Part 1 of a multi-part spec. Parts covering REST API, database, and
Docker come separately. Do not invent those layers. Focus only on what is here.

---

## What We Are Building

A multi-tool agent that:
- Accepts a natural language task
- Plans which agents to call and in what order
- Executes agents with maximum parallelism using a DAG scheduler
- Returns a structured answer + full execution trace

---

## Architecture: Two-Tier Plan-and-Execute

### Do NOT use ReAct
ReAct calls one tool per LLM decision, sequentially. It is the slowest possible
approach and cannot parallelize. Do not implement it.

### Tier 1 — Planner LLM (routing intelligence)
Receives the full user task. Outputs a JSON plan declaring:
- Which agents to call
- A natural language `sub_task` for each (not raw API params)
- Which agents depend on which others (`depends_on`)

The planner knows: agent names, one-line purposes, output field names, execution order.
The planner does NOT know: API schemas, parameter formats, extraction logic.

### Tier 2 — Tool Agents (domain specialists)
Each tool agent is a self-contained unit with:
- Its own LLM instance (model chosen per-agent in config)
- Its own static system prompt (domain rules, examples, extraction logic)
- Its own API call
- Its own output schema (guaranteed field names)

The tool agent receives: original user message + planner's `sub_task` + prior results.
It extracts the correct API parameters itself using its LLM, then calls the API.

### Why two tiers matter
Without this split, the planner must know every tool's API schema. Every new tool
means rewriting the planner prompt. With the split, the planner only needs a
one-line description per tool. Adding a tool never touches the planner.

---

## Plan JSON Contract

```json
{
  "tasks": [
    {
      "id": "t1",
      "agent": "weather",
      "sub_task": "Get current weather for the city the user mentioned",
      "depends_on": []
    },
    {
      "id": "t2",
      "agent": "calculator",
      "sub_task": "Convert the temperature from t1 result to Fahrenheit",
      "depends_on": ["t1"]
    },
    {
      "id": "t3",
      "agent": "web_search",
      "sub_task": "Find current news about the city the user mentioned",
      "depends_on": []
    }
  ]
}
```

- `depends_on: []` → fires in wave 1 (no dependencies)
- `depends_on: ["t1"]` → waits for t1 to complete before starting
- t1 and t3 fire in parallel. t2 waits for t1 only.
- Loop count = depth of deepest chain, not total task count

---

## LangGraph Graph

```
START → planner_node → executor_node ←──┐
                              │          │ loop if tasks remain
                              ▼          │
                           router ───────┘
                              │ all done
                              ▼
                        response_node → END
```

### State

```python
class AgentState(TypedDict):
    task:     str             # original user message — never modified
    plan:     list[dict]      # [{id, agent, sub_task, depends_on}] — frozen after planner
    results:  dict[str, Any]  # {task_id: result_dict} — grows each executor pass
    trace:    list[dict]      # [{task, agent, sub_task, result, llm_ms, api_ms, total_ms, wave}]
    response: str             # set by response_node only
```

### Executor node

```python
async def executor_node(state: AgentState) -> AgentState:
    plan, results, trace = state["plan"], dict(state["results"]), list(state["trace"])

    ready = [
        t for t in plan
        if t["id"] not in results
        and all(dep in results for dep in t["depends_on"])
    ]

    async def run_one(task):
        agent  = agent_registry.get(task["agent"])
        prior  = {dep: results[dep] for dep in task["depends_on"]}
        result = await agent.run(
            user_msg      = state["task"],
            sub_task      = task["sub_task"],
            prior_results = prior
        )
        return task["id"], result

    completed = await asyncio.gather(*[run_one(t) for t in ready])
    for task_id, result in completed:
        results[task_id] = result
        trace.append({"task": task_id, "agent": ..., "result": result, ...})

    return {**state, "results": results, "trace": trace}

def should_continue(state: AgentState) -> str:
    return "respond" if all(t["id"] in state["results"] for t in state["plan"]) else "execute"
```

---

## Tool Agent Structure

Every agent is a self-contained file. It declares a spec and implements `run()`.

```python
# agent/tools/weather.py

SPEC = AgentSpec(
    name="weather",
    purpose="Get current weather conditions for a location.",  # planner reads this
    system_prompt="""...""",   # domain expert prompt — static, frozen at startup
    output_schema={            # guarantees these fields exist in every response
        "temp_c": float, "temp_f": float, "condition": str, "city_name": str
    },
    default_ttl_seconds=300,
)

@agent_registry.register(SPEC)
class WeatherAgent:
    def __init__(self):
        self.llm = build_llm("weather")   # own model from config

    async def run(self, user_msg: str, sub_task: str, prior_results: dict) -> dict:
        # Step 1: LLM extracts params — holds semaphore only for this step
        async with get_llm_semaphore():
            params = await self.llm.ainvoke([
                SystemMessage(content=WEATHER_SYSTEM),   # static constant
                HumanMessage(content=f"User: {user_msg}\nTask: {sub_task}\nContext: {prior_results}")
            ])
        # semaphore released HERE — before the API call
        # other agents' LLM extractions can now proceed

        # Step 2: API call — runs in parallel with other agents' API calls
        parsed = json.loads(params.content)
        result = await call_weather_api(city=parsed["city"], units=parsed.get("units","metric"))
        return {"temp_c": result["main"]["temp"], "temp_f": ..., "condition": ..., "city_name": ...}
```

---

## LLM Concurrency Rule (Critical for Ollama)

### The problem
Ollama processes one LLM request at a time (single GPU). When two agents fire
simultaneously via `asyncio.gather()`, their LLM calls queue inside Ollama.
The queuing is invisible — no error, no warning, just hidden latency.

### The solution: semaphore on LLM step only, released before API call

```python
# agent/llm.py

_llm_sem: asyncio.Semaphore | None = None

def get_llm_semaphore() -> asyncio.Semaphore:
    global _llm_sem
    if _llm_sem is None:
        # Ollama = 1 (one GPU, serialize), OpenAI = 5 (parallel allowed)
        limit = 1 if load_config()["provider"] == "ollama" else 5
        _llm_sem = asyncio.Semaphore(limit)
    return _llm_sem
```

### Why this preserves parallelism

Each agent has two steps: LLM extraction (GPU bound) then API call (I/O bound).
The semaphore serializes LLM extractions. But it is released before the API call.
So API calls still run in parallel across agents.

Timeline with 2 agents:
```
Agent A: [LLM 200ms][─────────API 300ms─────────]
Agent B: [wait 200ms][LLM 200ms][────────API 400ms────────]
Total: 800ms   (vs 1100ms fully sequential, vs 800ms no semaphore but unpredictable)
```

Without semaphore, Ollama still queues internally — same result, but the wait
is hidden and untraced. With semaphore, the wait appears in your trace as
`"llm_wait_ms"` and you understand exactly what happened.

**GPU is safe either way. The semaphore makes behavior explicit and traceable.**

---

## LLM Provider Abstraction

Both Ollama and OpenAI use `ChatOpenAI` from `langchain-openai`. No other class.
Ollama exposes an OpenAI-compatible API — only `base_url` and `api_key` differ.

```python
# agent/llm.py

from langchain_openai import ChatOpenAI
from functools import lru_cache

@lru_cache(maxsize=None)
def build_llm(agent_name: str) -> ChatOpenAI:
    cfg      = load_config()
    provider = cfg["provider"]         # "ollama" or "openai" only
    conn     = cfg[provider]           # picks correct connection block
    agent    = cfg["agents"][agent_name]
    return ChatOpenAI(
        base_url    = conn["base_url"],
        api_key     = conn["api_key"],
        model       = agent["model"],
        temperature = agent.get("temperature", 0),
        max_tokens  = agent.get("max_tokens", 512),
    )
```

Switching providers = change `provider:` in config.yaml. Zero code changes.

---

## Static System Prompts (KV Cache)

All system prompts are module-level string constants. Built once at startup. Never
rebuilt per request.

**Why:** Both Ollama and OpenAI cache the system prompt's token representations (KV
cache). A single character change between requests invalidates the cache and adds
200–600ms prefill cost per call. Static prompts mean every request after the first
gets the cached version for free.

**Rule:** SystemMessage = fixed content only (role, rules, tool list, output format).
HumanMessage = all dynamic content (user task, tool results, retry feedback).
Never put timestamps, request IDs, or per-request data in SystemMessage.

```python
# agent/prompts.py — built at import time, never touched again

from agent.tools.base import agent_registry  # must be populated before this runs

def _build_planner_system() -> str:
    agent_block = agent_registry.planner_agent_block()  # called ONCE here
    return f"""You are a routing agent. Output a JSON execution plan.
Rules: ...
Agents:
{agent_block}
Output format: ..."""

PLANNER_SYSTEM = _build_planner_system()   # frozen constant
```

Tool agents also have static system prompts defined in their own files — with
domain-specific rules and few-shot examples baked in.

---

## Configuration

```yaml
# config.yaml

provider: ollama   # "ollama" or "openai" — the only line that changes between modes

ollama:
  base_url: ${OLLAMA_BASE_URL:-http://localhost:11434/v1}
  api_key: ollama

openai:
  base_url: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY}

# Each agent picks its own model independently
agents:
  planner:
    model: qwen2.5:7b-instruct-q4_K_M
    max_tokens: 512
    temperature: 0
  responder:
    model: qwen2.5:7b-instruct-q4_K_M
    max_tokens: 1024
    temperature: 0.3
  weather:
    model: llama3.2:3b-instruct-q4_K_M   # small — extraction is simple
    max_tokens: 256
    temperature: 0
  calculator:
    model: llama3.2:3b-instruct-q4_K_M
    max_tokens: 256
    temperature: 0
  web_search:
    model: qwen2.5:7b-instruct-q4_K_M
    max_tokens: 512
    temperature: 0
  database_query:
    model: qwen2.5:7b-instruct-q4_K_M
    max_tokens: 512
    temperature: 0

tools:
  calculator:    { enabled: true }
  weather:       { enabled: true, api_key: ${WEATHER_API_KEY}, base_url: ..., timeout_seconds: 5 }
  web_search:    { enabled: true, api_key: ${SERP_API_KEY}, base_url: ..., max_results: 5 }
  unit_converter:{ enabled: true, currency_api_key: ${EXCHANGE_API_KEY} }
  database_query:{ enabled: true, db_path: ./data/products.db, max_rows: 50 }

cache:
  enabled: true
  llm_cache_path: ./.cache/langchain.db
  tool_ttls: { calculator: 0, weather: 300, web_search: 600, unit_converter: 60, database_query: 30 }

executor:
  max_waves: 10
  max_parallel_tools: 8
  tool_timeout_seconds: 15

persistence:
  db_path: ./data/agent_tasks.db

api:
  host: 0.0.0.0
  port: 8000
```

---

## Plugin Architecture — Adding a Tool

One new file + one config block. No other files change.

```python
# agent/tools/my_tool.py

SPEC = AgentSpec(
    name="my_tool",
    purpose="One sentence — what the planner reads to decide routing.",
    system_prompt="""Domain expert prompt. Static. Include rules and examples.""",
    output_schema={"field_a": float, "field_b": str},
    default_ttl_seconds=60,
)

@agent_registry.register(SPEC)
class MyToolAgent:
    def __init__(self):
        self.llm = build_llm("my_tool")

    async def run(self, user_msg, sub_task, prior_results) -> dict:
        async with get_llm_semaphore():
            params = await self.llm.ainvoke([
                SystemMessage(content=MY_TOOL_SYSTEM),
                HumanMessage(content=f"User: {user_msg}\nTask: {sub_task}")
            ])
        # semaphore released — API call runs freely
        result = await call_my_api(**json.loads(params.content))
        return {"field_a": result["val"], "field_b": result["label"]}
```

Files that never change when adding a tool:
`graph.py`, `nodes.py`, `main.py`, `base.py`, `__init__.py`, any existing tool.

Autodiscovery: `agent/tools/__init__.py` imports every `.py` in the tools
directory at startup. The `@agent_registry.register(SPEC)` decorator fires on
import. Nothing else needs to know the tool exists.

---

## Performance Rules

**1. All HTTP calls must use aiohttp, not requests.**
`requests.get()` blocks the entire event loop. One blocking call collapses the
whole `asyncio.gather()` wave to sequential with no error or warning.

```python
# BANNED: import requests; requests.get(url)
# REQUIRED: async with aiohttp.ClientSession() as s: async with s.get(url) as r: ...
```

**2. CPU-bound tools use a thread pool executor.**
```python
_pool = ThreadPoolExecutor(max_workers=4)
async def calculator_tool(expr):
    return await asyncio.get_event_loop().run_in_executor(_pool, safe_eval, expr)
```

**3. Tool result caching with TTL.**
```python
_cache: dict[str, tuple[Any, float]] = {}
async def cached_call(fn, name, ttl, **kwargs):
    key = md5(f"{name}:{json.dumps(kwargs,sort_keys=True)}".encode()).hexdigest()
    if key in _cache:
        val, exp = _cache[key]
        if time() < exp: return val
    result = await fn(**kwargs)
    _cache[key] = (result, time() + ttl)
    return result
```

**4. LangChain LLM response cache.**
```python
from langchain.globals import set_llm_cache
from langchain_community.cache import SQLiteCache
set_llm_cache(SQLiteCache(database_path=".cache/langchain.db"))
```

**5. Context trimming — never dump raw results into LLM prompts.**
```python
def slim_results(results):
    KEEP = {"temp_c","temp_f","condition","price","rate","result","value","status","name"}
    return {tid: {k:v for k,v in r.items() if k in KEEP} if isinstance(r,dict) else r
            for tid, r in results.items()}
```

**6. Ollama model config — always Q4_K_M quantization.**
```
Q4_K_M: ~48 tok/s, 4.5GB RAM, 95% quality  ← use this
F16:     ~18 tok/s, 14GB RAM, 100% quality  ← do not use
```

Modelfile:
```
PARAMETER num_gpu 99     # offload ALL layers to GPU
PARAMETER num_ctx 2048   # set explicitly — never rely on defaults
PARAMETER temperature 0  # deterministic = better KV cache hit rate
```

---

## Startup Import Order

Must happen in this exact sequence to avoid empty prompt constants:

```
1. agent/config.py          → load_config() cached
2. agent/tools/__init__.py  → autodiscovery, all @register decorators fire
3. agent/prompts.py         → PLANNER_SYSTEM built from populated registry (frozen)
4. agent/llm.py             → build_llm() per agent, get_llm_semaphore() created
5. agent/graph.py           → LangGraph compiled
6. agent/startup.py         → validate_config(), fail fast on bad config
7. main.py                  → FastAPI + uvicorn
```

---

## File Structure

```
/
├── config.yaml
├── .env
├── main.py
├── agent/
│   ├── config.py        # load_config() — singleton, lru_cache
│   ├── llm.py           # build_llm(), get_llm_semaphore()
│   ├── prompts.py       # PLANNER_SYSTEM, RESPONDER_SYSTEM — frozen constants
│   ├── state.py         # AgentState TypedDict
│   ├── graph.py         # LangGraph graph + conditional edges
│   ├── nodes.py         # planner_node, executor_node, response_node
│   ├── cache.py         # tool TTL cache + LangChain LLM cache init
│   └── tools/
│       ├── __init__.py  # autodiscovery
│       ├── base.py      # AgentSpec, AgentRegistry, agent_registry singleton
│       ├── calculator.py
│       ├── weather.py
│       ├── web_search.py
│       ├── unit_converter.py
│       └── database_query.py
├── db/                  # defined in Part 2
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Hard Constraints

1. No `requests` library — `aiohttp` only for all HTTP calls.
2. No `time.sleep()` — `await asyncio.sleep()` only.
3. Planner output → `json.loads()` only, no regex extraction.
4. All agent `run()` methods return `dict` with schema-declared fields.
5. `num_ctx` always set explicitly in config — never rely on Ollama defaults.
6. SystemMessage content is always a module-level constant — never constructed per request.
7. Executor uses `asyncio.gather(*[run_one(t) for t in ready])` — never `for t in ready: await`.
8. LLM semaphore is released BEFORE the API call inside every agent's `run()`.
9. Every agent result appears in `trace[]` — nothing silently skipped.
10. `provider` in config is `"ollama"` or `"openai"` only — no other values.
11. `build_llm(agent_name)` is the only place `ChatOpenAI` is instantiated.
12. No Anthropic support — remove it if it appears.

---

## Brainstorm Questions — Resolve Before Writing Code

1. **Two-tier plan JSON** — the planner outputs `sub_task` (natural language), not
   raw API params. Confirm the executor correctly passes `user_msg`, `sub_task`, and
   `prior_results` into each agent's `run()`. How does the agent know which fields
   from `prior_results` are relevant when `depends_on` lists multiple task IDs?

2. **Semaphore placement** — the semaphore wraps only the LLM step inside `run()`,
   released before the API call. Confirm this is correctly placed so API calls of
   multiple agents can overlap even while LLM calls are serialized.

3. **Planner prompt scope** — the planner sees only: agent name, one-line purpose,
   and output field names. It does not see input schemas or API details. Confirm the
   planner system prompt is written to produce valid `depends_on` arrays without
   knowing parameter formats.

4. **Tool agent error handling** — if an agent's LLM extraction produces invalid
   JSON, does it retry once (like the planner) or fail immediately? Define the policy.

5. **Prior results passed to agents** — agents in `depends_on: ["t1"]` receive t1's
   output dict in `prior_results`. Agents with `depends_on: []` receive an empty dict.
   Confirm agents are written to handle both cases without crashing.

6. **Startup import order** — confirm the sequence above is enforceable without
   circular imports. Specifically: `prompts.py` imports from `tools/base.py`, and
   `tools/base.py` imports from `config.py`. Trace any risk of circular dependency.

7. **Semaphore with OpenAI** — when `provider: openai`, `Semaphore(5)` is used.
   Confirm this does not break any agent code that assumes serial LLM execution.

Do not write any code until these questions are resolved.
This is the brainstorm phase for Part 1 only.
