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
            (loop back)  Failure   Response Node
                        response    (synthesize from
                        (polite     tool results)
                         apology;
                         errors
                         logged)
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

**What it does:** After `load_dotenv()`, reads `LLM_PROVIDER` (`openai` or `ollama`, default `openai`), loads `config/shared.yaml` and the matching provider file (`config/openai.yaml` or `config/ollama.yaml`), deep-merges them (provider overlay wins), resolves `${ENV_VAR:-default}` patterns, and caches the result for the process lifetime via `@lru_cache`.

### `agent/llm.py` — LLM Factory

**What it does:** The sole `ChatOpenAI` instantiation point. Builds one LLM instance per agent name (planner, responder, and each LLM-backed tool such as weather, web_search, calculator, unit_converter, database_query) with per-agent model/temperature/token settings. Manages the LLM concurrency semaphore (1 for Ollama, 5 for OpenAI).

### `agent/state.py` — Graph State Definition

**What it does:** Defines `AgentState` (TypedDict) with explicit reducer semantics:

| Field | Type | Behavior |
|-------|------|----------|
| `task` | `str` | Set once at graph entry |
| `context_summary` | `str` | Conversation context snapshot |
| `plan` | `list[dict]` | Set by planner |
| `results` | `dict` | **Merge reducer** — grows each executor wave |
| `trace` | `list[dict]` | **Append reducer** — grows each executor wave |
| `response` | `str` | Set once by response node |
| `error_context` | `str` | Latest error summary (for logs); cleared on success |
| `failure_flag` | `bool` | True when execution failed and the graph uses the failure response path |
| `planner_duration_ms` | `int` (NotRequired) | Wall-clock ms for the planner LLM call |
| `responder_duration_ms` | `int` (NotRequired) | Wall-clock ms for the responder LLM call |

### `agent/prompts.py` — System Prompts

**What it does:** Defines the fixed system prompts used as `SystemMessage` content. Each prompt uses Markdown-style **section headings** (Role, Objective or output contract, rules, format) so model behavior and human review stay aligned.

- **Planner prompt** — Built lazily from the tool registry. Tells the planner LLM what tools exist, each tool’s input/output field names, and that every task must include structured `params` matching those schemas (plus `sub_task` for LLM-typed tools). The executor tries planner `params` before invoking each tool’s specialist LLM.
  - Includes a **"Conversational context awareness"** section that instructs the planner to: (a) resolve follow-up pronouns/references (e.g. "it", "from it") using conversation memory, (b) prefer the same tool(s) used in the previous turn when the follow-up continues the same topic, (c) embed the resolved entity directly in `params`/`sub_task` instead of relying on pronouns.
- **Responder prompt** — Instructions for synthesizing tool results into a natural language answer (grounding, no double computation when tools already returned a final value, failure tone).
- **Summarizer prompt** — Strict JSON output: rolling `summary` plus merged `user_key_facts` (stable user attributes). Background refresh after each assistant reply.

LLM-backed tools use the same section pattern inside each `ToolSpec.system_prompt` (parameter specialist → JSON shape → rules).

### `agent/context.py` — Conversation Memory

**What it does:** Rolling window of the last 5 user and 5 assistant messages (tagged). Persists `summary`, `user_key_facts`, and `last_tools_used` (list of tool names invoked in the most recent turn). Snapshots are passed in graph state; **injection differs by node**: planner gets recent + summary (capped); tools get only rolling summary with `user_msg`; responder gets key facts + summary + current user message (capped).

### `agent/memory_format.py` — Memory bundle

**What it does:** `build_planner_context_block` (recent + summary) and `build_responder_memory_block` (key facts + summary), each with its own token budget.

### `agent/graph_nodes.py` — Graph Node Functions

The three core node functions plus routing logic:

**`planner_node`** — The "brain" of the agent.
- Receives the task + planner memory (recent messages + `context_summary` only; capped) + `[Tools used in previous turn]` hint from `ConversationContext.last_tools_used`
- Calls the planner LLM with the system prompt containing all available tools
- Parses the JSON plan (with markdown fence stripping and error recovery)
- Times the LLM call and returns `planner_duration_ms` alongside the task list

**`executor_node`** — The "hands" of the agent.
- Identifies ready tasks (all dependencies satisfied)
- Computes the current wave number from existing trace entries
- Runs ready tasks in parallel via `asyncio.gather` with a concurrency cap
- Each tool call is individually timed (`duration_ms`) and tagged with the `wave` number in its trace entry
- For **LLM tools**: calls `agent.run(state=state, plan_task=task)` (tools receive a **`ToolInvocation`** with `user_msg`, `sub_task`, `prior_results`, `planner_params`, `context_summary` derived from state + task)
- For **function tools**: calls `agent.call(task["params"])`
- Collects results, trace entries, and any errors
- Wraps every call in `asyncio.wait_for(timeout=...)` for safety

**`route_after_executor`** — The "decision maker" after each execution wave.
- Checks for errors → routes to failure (no planner re-run; tools already performed their own retries)
- Checks for remaining tasks → loops back to executor
- All tasks done → routes to response node

**`mark_failure_node`** — Sets `failure_flag = True` before routing to response.

**`response_node`** — The "voice" of the agent.
- Takes all accumulated results and the execution trace
- Calls the responder LLM to synthesize a clear answer (see `RESPONDER_SYSTEM` in `agent/prompts.py`). When tools already returned a final value (e.g. calculator `result`), the responder must state it in the user's language without redoing step-by-step work unless the user asked for a derivation.
- On failure: logs internal error details, then asks the responder for a user-safe apology (no technical leakage), or a plain-language explanation when `user_facing_error` is set

### `agent/graph.py` — LangGraph Compilation

**What it does:** Wires the nodes into a `StateGraph` with conditional edges:

```
START → planner → executor → [route_after_executor]
                                  ├── "continue" → executor (next wave)
                                  ├── "fail"     → mark_failure → responder
                                  └── "done"     → responder → END
```

### `agent/tools/base.py` — Tool Framework

**What it does:** Provides the base classes and registry for all tools:

- **`ToolSpec`** — Declarative metadata (name, type, purpose, schemas, TTL)
- **`ToolInvocation`** — frozen bundle: graph `state` + plan task row; properties for `user_msg`, `sub_task`, `prior_results`, `planner_params`, `context_summary`
- **`BaseToolAgent`** — `run(state, plan_task)` builds **`ToolInvocation`** and delegates to **`_tool_executor(inv)`**; each tool invokes **`self.llm`** only when planner params are **missing** (no retry loops in `base.py`)
- **`BaseFunctionTool`** — Pure functions: planner provides structured params directly
- **`AgentRegistry`** — Singleton registry populated by `@register` decorators at import time

### `agent/tools/__init__.py` — Autodiscovery

**What it does:** Imports every `.py` file in the tools directory (excluding `__init__.py` and `base.py`). The `@registry.register(SPEC)` decorators fire on import, populating the registry before anything else runs.

### `agent/tool_cache.py` — Caching Layer

**What it does:** Provides two caching mechanisms:
- **Tool TTL cache** (`cached_call`) — MD5-keyed in-memory cache with configurable TTL per tool
- **LLM response cache** — LangChain `SQLiteCache` for caching LLM responses to disk

## Tool Types: Two Execution Paths

### LLM Tools (weather, web_search, calculator, unit_converter, database_query)

```
planner sets sub_task + params (structured JSON per tool input_schema)
    │
    ▼
executor calls agent.run(state, plan_task)
    │
    ▼
subclass _tool_executor(inv) — tool-specific: optional single self.llm.ainvoke if params missing,
    then backend
    │
    ├── Acquire LLM semaphore around that tool LLM call
    └── Backend: HTTP API, safe eval, conversion, or SQL execution
```

**database_query variant:** Unlike other LLM tools where the LLM is a fallback for missing params, the database_query tool's LLM **always** runs because SQL generation is its core function. The planner provides a natural-language `question` param; the tool LLM converts it into a validated SQL SELECT query that runs against `data/catalog.db` (products and orders tables).

### Function Tools (optional — `BaseFunctionTool`)

```
planner sets params (structured JSON)
    │
    ▼
executor calls agent.call(params)
    │
    └── Execute pure computation with no extraction LLM (no semaphore for that step)
```

## Error Recovery Flow

1. An LLM-backed tool raises: `executor_node` records the error; no automatic replan. Tools do not run parse-retry loops in `base.py`.
2. If the tool still raises, `executor_node` records the failure in `trace`, sets `error_context` for **logging**, and does not merge a result for that task id. If the exception is `UserFacingToolError`, the trace entry includes `user_facing: true` and the message is aggregated into `user_facing_error` on state.
3. `route_after_executor` sees `error_context` → routes to `mark_failure_node` → `response_node` (no return to the planner).
4. `response_node` logs the internal error text. If `user_facing_error` is set, the responder is instructed to explain that plain-language reason to the user; otherwise it asks for a generic polite apology without technical details.
