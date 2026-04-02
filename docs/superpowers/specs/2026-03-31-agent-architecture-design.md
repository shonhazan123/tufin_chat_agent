# Agent Architecture Design — Part 1
**Date:** 2026-03-31
**Scope:** Agent execution engine only. REST API, database persistence, and Docker are Part 2.

---

## 1. Overview

A multi-tool agent that accepts a natural language task, plans which tools to call and in what order, executes them with maximum parallelism via a DAG scheduler, maintains a rolling conversation context, and returns a structured answer with a full execution trace.

**Key decisions:**
- LLM provider: Ollama-first (semaphore limit = 1), OpenAI switchable via single config line
- Web search: Tavily (free tier, LangChain-native)
- Tools in scope: calculator, weather, web_search, unit_converter (4 core tools; database_query deferred to Part 2)
- Tests: written alongside implementation

---

## 2. Architecture — Two-Tier Plan-and-Execute

### Do NOT use ReAct
ReAct calls one tool per LLM decision, sequentially. It cannot parallelize. Not implemented here.

### Tier 1 — Planner LLM
Receives: current user task + context summary (from prior turns).
Outputs: a JSON execution plan declaring which tools to call, their params or sub_task, and dependencies.

The planner knows: tool names, one-line purposes, output field names, tool type (`llm` vs `function`), and input schemas for function tools.
The planner does NOT know: API schemas or parameter formats for LLM tools.

### Tier 2 — Tool Agents
Each tool agent is self-contained. Two subtypes:

**LLM tools** (`type: "llm"`) — weather, web_search:
- Have their own LLM instance (model chosen per-agent in config)
- Receive: `user_msg`, `sub_task` (natural language), `prior_results`
- Extract API params themselves using their LLM
- Hold the LLM semaphore during extraction only; release before API call

**Function tools** (`type: "function"`) — calculator, unit_converter:
- Pure functions, no LLM call, no semaphore
- Planner writes structured `params` directly into the plan
- Executor calls `agent.call(params)` directly

### Graph

```
START → planner_node → executor_node ◄─────────────────────┐
                             │                              │
                             ▼                              │
                       route_after_executor                 │
                        ├── tasks_remain  ─────────────────►│ (loop)
                        ├── error         → retry_router    │
                        │                      ├── retry_count < max_retries ──► planner_node
                        │                      └── retry_count >= max_retries ─► response_node(failure)
                        │                          (max_retries = cfg["graph"]["max_retries"], default 3)
                        └── all_done ──────────────────────► response_node → END
```

---

## 3. AgentState

All fields have explicit reducer functions. Nodes return only the fields they modify.

```python
# agent/state.py

import operator
from typing import Annotated, Any
from typing_extensions import TypedDict

def _merge(existing: dict, new: dict) -> dict:
    return {**existing, **new}

def _append(existing: list, new: list) -> list:
    return existing + new

def _write_once(existing: Any, new: Any) -> Any:
    return existing if existing is not None else new

class AgentState(TypedDict):
    task:            Annotated[str,            _write_once]   # current user message — frozen at entry
    context_summary: Annotated[str,            _write_once]   # snapshot from ConversationContext — frozen at entry
    plan:            Annotated[list[dict],     _write_once]   # set by planner_node — frozen
    results:         Annotated[dict[str, Any], _merge]        # grows each executor pass
    trace:           Annotated[list[dict],     _append]       # grows each executor pass
    response:        Annotated[str,            _write_once]   # set by response_node only
    retry_count:     Annotated[int,            operator.add]  # incremented by 1 on each error
    error_context:   str                                      # replaces — last error wins
    failure_flag:    bool                                     # True when retries exhausted
```

**Reducer rules:**
- `results` and `trace`: accumulate across executor passes — merge/append, never replace
- `task`, `plan`, `context_summary`, `response`: write-once — first value wins
- `retry_count`: additive — node returns `1` and reducer adds it
- `error_context`: replace — only the latest error matters
- `failure_flag`: replace — set True when retry_count reaches 3

---

## 4. Plan JSON Contract

```json
{
  "tasks": [
    {
      "id": "t1",
      "agent": "weather",
      "type": "llm",
      "sub_task": "Get current weather for the city the user mentioned",
      "depends_on": []
    },
    {
      "id": "t2",
      "agent": "calculator",
      "type": "function",
      "params": { "expression": "37 * 1.8 + 32" },
      "depends_on": ["t1"]
    },
    {
      "id": "t3",
      "agent": "web_search",
      "type": "llm",
      "sub_task": "Find current news about the city the user mentioned",
      "depends_on": []
    }
  ]
}
```

- `depends_on: []` → fires in wave 1
- `depends_on: ["t1"]` → waits for t1 only
- t1 and t3 fire in parallel; t2 waits for t1
- Function tools receive `params` (structured); LLM tools receive `sub_task` (natural language)

---

## 5. Tool Subtype Contract

```python
# agent/tools/base.py

from dataclasses import dataclass
from typing import Literal

@dataclass
class ToolSpec:
    name:                str
    type:                Literal["llm", "function"]
    purpose:             str                      # one line — planner reads this
    output_schema:       dict[str, type]          # guaranteed output fields
    input_schema:        dict[str, str] | None = None  # function tools only — planner writes params from this
    system_prompt:       str | None = None        # LLM tools only; static constant
    default_ttl_seconds: int = 0
```

### BaseToolAgent (LLM tools)

```python
class BaseToolAgent:
    MAX_RETRIES: int = 3   # overridden per-agent via config

    async def run(self, user_msg: str, sub_task: str, prior_results: dict) -> dict:
        feedback = ""
        for attempt in range(self.max_retries):
            async with get_llm_semaphore():
                human_content = f"User: {user_msg}\nTask: {sub_task}\nContext: {prior_results}"
                if feedback:
                    human_content += f"\n\nPrevious output was invalid: {feedback}. Try again."
                params_msg = await self.llm.ainvoke([
                    SystemMessage(content=self.SYSTEM),
                    HumanMessage(content=human_content)
                ])
            # semaphore released — API call runs freely
            try:
                params = json.loads(params_msg.content)
                return await self._tool_executor(params)
            except json.JSONDecodeError as e:
                feedback = str(e)
        raise ToolExtractionError(f"{self.spec.name}: LLM extraction failed after {self.max_retries} retries")
```

### BaseFunctionTool (function tools)

```python
class BaseFunctionTool:
    async def call(self, params: dict) -> dict:
        raise NotImplementedError
```

---

## 6. Executor Node

```python
# agent/nodes.py

async def executor_node(state: AgentState) -> dict:
    plan, results = state["plan"], state["results"]

    ready = [
        t for t in plan
        if t["id"] not in results
        and all(dep in results for dep in t["depends_on"])
    ]

    async def run_one(task: dict):
        agent = agent_registry.get(task["agent"])
        prior = {dep: results[dep] for dep in task["depends_on"]}
        t0 = time()
        if task["type"] == "llm":
            result = await agent.run(
                user_msg=state["task"],
                sub_task=task["sub_task"],
                prior_results=prior
            )
        else:
            result = await agent.call(task["params"])
        return task["id"], result, time() - t0

    # return_exceptions=True: partial failures don't cancel sibling tasks
    completed = await asyncio.gather(*[run_one(t) for t in ready], return_exceptions=True)

    errors = [r for r in completed if isinstance(r, BaseException)]
    if errors:
        return {"error_context": str(errors[0]), "retry_count": 1}

    new_results = {tid: res for tid, res, _ in completed}
    new_trace   = [
        {"task": tid, "agent": plan_task["agent"], "result": res,
         "total_ms": int(elapsed * 1000)}
        for (tid, res, elapsed), plan_task in zip(completed, ready)
    ]
    return {"results": new_results, "trace": new_trace}
```

---

## 7. Conversation Context Manager

A process-lifetime singleton. Not in `AgentState` — it is global, not per-request.

```python
# agent/context.py

from collections import deque
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

class ConversationContext:
    def __init__(self):
        self._human:  deque[HumanMessage] = deque(maxlen=5)
        self._ai:     deque[AIMessage]    = deque(maxlen=5)
        self.summary: str = ""

    def add_user(self, text: str) -> None:
        self._human.append(HumanMessage(content=text))

    def add_assistant(self, text: str) -> None:
        self._ai.append(AIMessage(content=text))

    def window(self) -> list[BaseMessage]:
        # interleave in chronological order
        msgs = []
        h, a = list(self._human), list(self._ai)
        for i in range(max(len(h), len(a))):
            if i < len(h): msgs.append(h[i])
            if i < len(a): msgs.append(a[i])
        return msgs

    async def summarize_async(self, llm) -> None:
        try:
            result = await llm.ainvoke([
                SystemMessage(content=SUMMARIZER_SYSTEM),
                *self.window()
            ])
            self.summary = result.content
        except Exception:
            pass  # keep old summary — never raise

conversation_context = ConversationContext()
```

### Full lifecycle

```
API receives task
  │
  ├── context.add_user(task)
  │
  ▼
graph.invoke({
    "task":            task,
    "context_summary": context.summary,   # snapshot — frozen for this request
    ...
})
  │
  ▼
planner_node:
    prompt = f"User: {state['task']}"
    if state['context_summary']:
        prompt += f"\n\n[Conversation context]: {state['context_summary']}"
  │
  ▼
  ... executor waves ...
  │
  ▼
response_node → state["response"] = answer
  │
  ▼
graph returns to API layer
  │
  ├── send response to user              ← zero added latency
  ├── context.add_assistant(answer)
  └── asyncio.create_task(
          context.summarize_async(build_llm("responder"))
      )                                  ← fire-and-forget
```

---

## 8. LLM Provider Abstraction

```python
# agent/llm.py

from langchain_openai import ChatOpenAI
from functools import lru_cache

@lru_cache(maxsize=None)
def build_llm(agent_name: str) -> ChatOpenAI:
    cfg      = load_config()
    provider = cfg["provider"]        # "ollama" or "openai" only
    conn     = cfg[provider]
    agent    = cfg["agents"][agent_name]
    return ChatOpenAI(
        base_url    = conn["base_url"],
        api_key     = conn["api_key"],
        model       = agent["model"],
        temperature = agent.get("temperature", 0),
        max_tokens  = agent.get("max_tokens", 512),
    )

_llm_sem: asyncio.Semaphore | None = None

def init_llm_semaphore() -> None:
    """Call once at startup (in startup.py) before the event loop accepts requests."""
    global _llm_sem
    limit = 1 if load_config()["provider"] == "ollama" else 5
    _llm_sem = asyncio.Semaphore(limit)

def get_llm_semaphore() -> asyncio.Semaphore:
    if _llm_sem is None:
        raise RuntimeError("LLM semaphore not initialized — call init_llm_semaphore() at startup")
    return _llm_sem
```

Switching providers = change one line in `config.yaml`. Zero code changes.

---

## 9. Static System Prompts (KV Cache)

All system prompts are module-level string constants. Never rebuilt per request.

```python
# agent/prompts.py — built once at import time

PLANNER_SYSTEM    = _build_planner_system()   # uses populated agent_registry
RESPONDER_SYSTEM  = """
You are a helpful assistant. You have received the results of one or more tool
calls executed on the user's behalf. Synthesize these results into a clear,
concise natural language answer. Do not expose raw JSON or internal field names.
If a failure_flag is present, apologize politely and ask the user to rephrase
or try again. Never invent facts not present in the tool results.
"""
SUMMARIZER_SYSTEM = """
You are a conversation summarizer. Given recent user and assistant messages,
write 2-3 sentences capturing: topics discussed, key facts established, and any
unresolved questions. Plain text only. No lists or headers.
"""
```

**Rule:** `SystemMessage` = fixed content only. `HumanMessage` = all dynamic content (user task, tool results, retry feedback, context summary). Never put per-request data in `SystemMessage`.

---

## 10. Tool Caching

```python
# agent/cache.py

_cache: dict[str, tuple[Any, float]] = {}

async def cached_call(fn, name: str, ttl: int, **kwargs) -> Any:
    if ttl == 0:
        return await fn(**kwargs)
    key = md5(f"{name}:{json.dumps(kwargs, sort_keys=True)}".encode()).hexdigest()
    if key in _cache:
        val, exp = _cache[key]
        if time() < exp:
            return val
    result = await fn(**kwargs)
    _cache[key] = (result, time() + ttl)
    return result
```

LangChain LLM response cache:
```python
from langchain.globals import set_llm_cache
from langchain_community.cache import SQLiteCache
set_llm_cache(SQLiteCache(database_path=".cache/langchain.db"))
```

---

## 11. Startup Sequence

`startup.py` owns all initialization. Called once at process start before the event loop accepts requests.

```
1. agent/config.py              → load_config() cached (no side effects)
2. agent/tools/__init__.py      → autodiscovery; all @register decorators fire; registry populated
3. agent/prompts.py             → PLANNER_SYSTEM built from populated registry (frozen)
4. agent/llm.py                 → build_llm() per agent (lru_cache warms up)
5. agent/llm.py                 → init_llm_semaphore() called explicitly — no race condition
6. agent/context.py             → conversation_context singleton created
7. agent/graph.py               → LangGraph compiled
8. agent/startup.py             → validate_config(); check required env vars; fail fast
9. main.py                      → FastAPI lifespan runs startup(); uvicorn starts (stub in Part 1)
```

**Rule:** `PLANNER_SYSTEM` is a module-level string constant but is only valid after step 2 completes.
`startup.py` must import tools before importing prompts — enforced by explicit import order in `startup.py`.

**LLM call timeouts:** All `llm.ainvoke()` and `_tool_executor()` calls are wrapped:
```python
await asyncio.wait_for(llm.ainvoke(messages), timeout=cfg["executor"]["tool_timeout_seconds"])
```
If timeout fires, it raises `asyncio.TimeoutError` which is caught by the executor's exception handler.

---

## 12. File Structure

```
/
├── config.yaml
├── .env
├── main.py                       # FastAPI stub (full impl in Part 2)
├── agent/
│   ├── config.py                 # load_config() — lru_cache singleton
│   ├── llm.py                    # build_llm(), get_llm_semaphore()
│   ├── prompts.py                # PLANNER_SYSTEM, RESPONDER_SYSTEM, SUMMARIZER_SYSTEM
│   ├── state.py                  # AgentState TypedDict + all reducers
│   ├── context.py                # ConversationContext singleton
│   ├── graph.py                  # LangGraph compile + conditional edges
│   ├── nodes.py                  # planner_node, executor_node, response_node
│   ├── cache.py                  # tool TTL cache + LangChain SQLiteCache init
│   └── tools/
│       ├── __init__.py           # autodiscovery loop
│       ├── base.py               # ToolSpec, BaseToolAgent, BaseFunctionTool, AgentRegistry
│       ├── calculator.py         # type: "function"
│       ├── weather.py            # type: "llm"
│       ├── web_search.py         # type: "llm" — Tavily
│       └── unit_converter.py     # type: "function"
├── tests/
│   ├── test_graph.py             # end-to-end integration tests (≥5 assertions)
│   ├── test_calculator.py
│   ├── test_weather.py
│   ├── test_web_search.py
│   └── test_unit_converter.py
└── docs/
    └── superpowers/specs/
        └── 2026-03-31-agent-architecture-design.md
```

---

## 13. Configuration

```yaml
# config.yaml

provider: ollama   # "ollama" or "openai" — only line that changes between modes

ollama:
  base_url: ${OLLAMA_BASE_URL:-http://localhost:11434/v1}
  api_key: ollama

openai:
  base_url: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY}

agents:
  planner:
    model: qwen2.5:7b-instruct-q4_K_M
    max_tokens: 512
    temperature: 0
    num_ctx: 4096        # required — never rely on Ollama defaults
  responder:
    model: qwen2.5:7b-instruct-q4_K_M
    max_tokens: 1024
    temperature: 0.3
    max_retries: 3
    num_ctx: 8192
  weather:
    model: llama3.2:3b-instruct-q4_K_M
    max_tokens: 256
    temperature: 0
    max_retries: 3
    num_ctx: 2048
  web_search:
    model: qwen2.5:7b-instruct-q4_K_M
    max_tokens: 512
    temperature: 0
    max_retries: 3
    num_ctx: 4096

tools:
  calculator:     { enabled: true }
  weather:        { enabled: true, api_key: ${WEATHER_API_KEY}, timeout_seconds: 5 }
  web_search:     { enabled: true, api_key: ${TAVILY_API_KEY}, max_results: 5 }
  unit_converter: { enabled: true, currency_api_key: ${EXCHANGE_API_KEY} }
  # currency_api_key: exchangerate-api.com free tier (1500 req/month)
  # set EXCHANGE_API_KEY in .env; if absent, currency conversion returns error, other conversions unaffected

cache:
  enabled: true
  llm_cache_path: ./.cache/langchain.db
  tool_ttls:
    calculator:     0
    weather:        300
    web_search:     600
    unit_converter: 60

executor:
  max_waves:          10
  max_parallel_tools: 8
  tool_timeout_seconds: 15

graph:
  max_retries: 3   # planner-level retry loop
```

---

## 14. Testing Strategy

Minimum 5 assertions on known tasks:

| Test | Input | Expected |
|---|---|---|
| Calculator — basic math | `"What is 42 * 18?"` | result contains `756` |
| Calculator — chained | `"Convert 100°C to F"` → unit_converter | result contains `212` |
| Planner — parallel routing | task requiring weather + web_search | plan has 2 tasks with `depends_on: []` |
| Planner — sequential routing | task requiring weather then calculator | t2 `depends_on: ["t1"]` |
| Error recovery | planner receives deliberately bad task | `retry_count > 0`, final response is polite |
| Context summary | 2nd request referencing 1st | planner HumanMessage contains `[Conversation context]` |

---

## 15. Hard Constraints (from spec)

1. No `requests` library — `aiohttp` only for all HTTP calls
2. No `time.sleep()` — `await asyncio.sleep()` only
3. Planner output → `json.loads()` only, no regex extraction
4. All agent `run()` methods return `dict` with schema-declared fields
5. `num_ctx` always set explicitly in config — never rely on Ollama defaults
6. `SystemMessage` content is always a module-level constant — never constructed per request
7. Executor uses `asyncio.gather(*[run_one(t) for t in ready])` — never `for t in ready: await`
8. LLM semaphore released BEFORE the API call inside every LLM tool's `run()`
9. Every agent result appears in `trace[]` — nothing silently skipped
10. `provider` in config is `"ollama"` or `"openai"` only
11. `build_llm(agent_name)` is the only place `ChatOpenAI` is instantiated
12. No Anthropic support
13. Errors never reach the user — all failures route through retry loop → polite response

---

## 16. Resolved Brainstorm Questions

| # | Question | Resolution |
|---|---|---|
| 1 | Prior results relevance | Agent receives `{dep_id: result_dict}` for all its `depends_on`. Static system prompt instructs extraction. |
| 2 | Semaphore placement | Acquired before `llm.ainvoke()`, released immediately after — before API call. API calls overlap freely. |
| 3 | Planner prompt scope | Sees: name, purpose, output fields, type, input schema (function tools only). No API details. |
| 4 | Tool agent error handling | Retry up to `max_retries` (per-agent config). Retry feedback injected into HumanMessage. |
| 5 | Empty prior_results | `prior_results = {}` for `depends_on: []`. All agents handle empty dict. |
| 6 | Circular import risk | `config.py` → no imports. `tools/base.py` → `config.py` only. `prompts.py` → `tools/base.py`. No cycles. |
| 7 | Semaphore(5) with OpenAI | Agent code makes no serial assumption — semaphore just controls concurrency. |
