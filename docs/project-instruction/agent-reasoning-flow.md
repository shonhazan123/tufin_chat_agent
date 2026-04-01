# Agent Reasoning Flow

This document explains the end-to-end reasoning flow of the multi-tool agent and the responsibility of each component.

## High-Level Flow

```
User Request
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  main.py (FastAPI)                                       │
│  Receives POST /task, adds to conversation context,      │
│  invokes the LangGraph execution graph                   │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Planner Node                                            │
│  LLM analyzes the task + conversation context            │
│  Outputs a JSON plan: which tools, what params, ordering │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│  Executor Node (wave loop)                               │
│  Picks tasks whose dependencies are satisfied            │
│  Runs them in parallel via asyncio.gather                │
│  Loops until all tasks complete or an error occurs       │
└───────────────────────────┬──────────────────────────────┘
                            │
                 ┌──────────┼──────────┐
                 │          │          │
            tasks_remain   error    all_done
                 │          │          │
                 ▼          ▼          ▼
            (loop back)  Retry?   Response Node
                        ┌──┴──┐       │
                      yes     no      ▼
                        │      │   Synthesize answer
                        ▼      ▼   from tool results
                    Re-plan  Failure
                    (back to  response
                     planner)
```

## Component Responsibilities

### `main.py` — API Entry Point

**What it does:** Receives user requests, manages the conversation lifecycle, invokes the graph.

- Accepts `POST /task` with a natural language task
- Records the message in `ConversationContext`
- Initializes `AgentState` with the task, context summary, and empty fields
- Invokes `graph.ainvoke()` with a recursion limit
- Returns the response and execution trace to the caller
- Fires off a background summarization of the conversation

### `agent/startup.py` — Initialization Orchestrator

**What it does:** Runs the startup sequence in strict dependency order.

1. Validates configuration (provider, env vars, agent configs)
2. Discovers and registers all tools (populates the registry)
3. Builds and caches the planner prompt (reads from populated registry)
4. Initializes the LLM semaphore (concurrency control)
5. Sets up LLM response caching (SQLite)
6. Compiles the LangGraph execution graph

### `agent/yaml_config.py` — Configuration Loader

**What it does:** Loads `config.yaml` once, resolves `${ENV_VAR:-default}` patterns from `.env`, caches the result for the process lifetime via `@lru_cache`.

### `agent/llm.py` — LLM Factory

**What it does:** The sole `ChatOpenAI` instantiation point. Builds one LLM instance per agent name (planner, responder, weather, web_search) with per-agent model/temperature/token settings. Manages the LLM concurrency semaphore (1 for Ollama, 5 for OpenAI).

### `agent/state.py` — Graph State Definition

**What it does:** Defines `AgentState` (TypedDict) with explicit reducer semantics:

| Field | Type | Behavior |
|-------|------|----------|
| `task` | `str` | Set once at graph entry |
| `context_summary` | `str` | Conversation context snapshot |
| `plan` | `list[dict]` | Set by planner; replaced on retry |
| `results` | `dict` | **Merge reducer** — grows each executor wave |
| `trace` | `list[dict]` | **Append reducer** — grows each executor wave |
| `response` | `str` | Set once by response node |
| `retry_count` | `int` | **Additive reducer** — incremented on each error |
| `error_context` | `str` | Latest error message; cleared on success |
| `failure_flag` | `bool` | True when max retries exhausted |

### `agent/prompts.py` — System Prompts

**What it does:** Defines the fixed system prompts used as `SystemMessage` content:

- **Planner prompt** — Built lazily from the tool registry. Tells the LLM what tools exist, their types (llm/function), input/output schemas, and the JSON output format.
- **Responder prompt** — Instructions for synthesizing tool results into a natural language answer.
- **Summarizer prompt** — Instructions for compressing conversation history into 2-3 sentences.

### `agent/context.py` — Conversation Memory

**What it does:** Maintains a process-lifetime rolling window of the last 5 user and 5 assistant messages. Provides a `summary` string (refreshed after each response via fire-and-forget LLM call) that the planner uses for context awareness across turns.

### `agent/graph_nodes.py` — Graph Node Functions

The three core node functions plus routing logic:

**`planner_node`** — The "brain" of the agent.
- Receives the task + conversation context + error context (if retrying)
- Calls the planner LLM with the system prompt containing all available tools
- Parses the JSON plan (with markdown fence stripping and error recovery)
- Returns the task list for the executor

**`executor_node`** — The "hands" of the agent.
- Identifies ready tasks (all dependencies satisfied)
- Runs them in parallel via `asyncio.gather` with a concurrency cap
- For **LLM tools**: calls `agent.run(user_msg, sub_task, prior_results)`
- For **function tools**: calls `agent.call(params)`
- Collects results, trace entries, and any errors
- Wraps every call in `asyncio.wait_for(timeout=...)` for safety

**`route_after_executor`** — The "decision maker" after each execution wave.
- Checks for errors → routes to retry (re-plan) or failure
- Checks for remaining tasks → loops back to executor
- All tasks done → routes to response node

**`mark_failure_node`** — Sets `failure_flag = True` before routing to response.

**`response_node`** — The "voice" of the agent.
- Takes all accumulated results and the execution trace
- Calls the responder LLM to synthesize a clear answer
- On failure: generates a polite apology with the error details

### `agent/graph.py` — LangGraph Compilation

**What it does:** Wires the nodes into a `StateGraph` with conditional edges:

```
START → planner → executor → [route_after_executor]
                                  ├── "continue" → executor (next wave)
                                  ├── "retry"    → planner (re-plan)
                                  ├── "fail"     → mark_failure → responder
                                  └── "done"     → responder → END
```

### `agent/tools/base.py` — Tool Framework

**What it does:** Provides the base classes and registry for all tools:

- **`ToolSpec`** — Declarative metadata (name, type, purpose, schemas, TTL)
- **`BaseToolAgent`** — LLM tools: semaphore → LLM param extraction → release → API call, with retry
- **`BaseFunctionTool`** — Pure functions: planner provides structured params directly
- **`AgentRegistry`** — Singleton registry populated by `@register` decorators at import time

### `agent/tools/__init__.py` — Autodiscovery

**What it does:** Imports every `.py` file in the tools directory (excluding `__init__.py` and `base.py`). The `@registry.register(SPEC)` decorators fire on import, populating the registry before anything else runs.

### `agent/tool_cache.py` — Caching Layer

**What it does:** Provides two caching mechanisms:
- **Tool TTL cache** (`cached_call`) — MD5-keyed in-memory cache with configurable TTL per tool
- **LLM response cache** — LangChain `SQLiteCache` for caching LLM responses to disk

## Tool Types: Two Execution Paths

### LLM Tools (weather, web_search)

```
planner sets sub_task (natural language)
    │
    ▼
executor calls agent.run(user_msg, sub_task, prior_results)
    │
    ├── Acquire LLM semaphore
    ├── LLM extracts structured API params from sub_task
    ├── Release LLM semaphore
    └── Call external API with extracted params
```

### Function Tools (calculator, unit_converter)

```
planner sets params (structured JSON)
    │
    ▼
executor calls agent.call(params)
    │
    └── Execute pure computation (no LLM, no semaphore)
```

## Error Recovery Flow

1. A tool fails during execution
2. `executor_node` sets `error_context` with the error details and increments `retry_count`
3. `route_after_executor` checks if retries remain:
   - **Yes** → routes back to `planner_node` with the error context
   - **No** → routes to `mark_failure_node` → `response_node` (failure message)
4. On retry, the planner sees the error and generates a revised plan
5. The new plan replaces the old one; the executor runs the new tasks
