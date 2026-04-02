# Architecture Overview

## Two-Tier Plan-and-Execute Agent

This project implements a multi-tool agent using a **two-tier plan-and-execute** architecture (not ReAct). The system accepts natural language tasks, plans which tools to call and in what order, executes them with maximum parallelism via a DAG scheduler, and returns a structured answer with a full execution trace.

## Tiers

### Tier 1 — Planner LLM (Routing Intelligence)

The planner receives the current user task plus a conversation context summary. It outputs a JSON execution plan declaring (or an empty `tasks` array when a reply needs no tools, or when **required user details are missing** and the assistant should ask a follow-up):
- Which tools to call
- For every tool: structured `params` whose keys match that tool’s input schema in the registry
- For LLM-typed tools: a short natural language `sub_task` in addition to `params`
- Dependency ordering via `depends_on` arrays

The responder (see `RESPONDER_SYSTEM` in `agent/prompts.py`) acts as a personal assistant: it answers naturally when no tools ran, and synthesizes tool outputs into a friendly reply when they did. When the planner returned an empty plan due to missing details, the responder should ask a targeted clarifying question rather than guessing. It must not repeat the same computation or long arithmetic walkthrough when a tool already produced the final answer (unless the user asked for steps).

The planner knows: tool names, purposes, output field names, tool types (`llm` vs `function`), and each tool’s input fields (see registry / planner prompt). Each LLM-typed tool calls its own `self.llm.ainvoke` **only when planner params are missing** what it needs — one shot, no retry loops in `BaseToolAgent`.

### Tier 2 — Tool Agents (Domain Specialists)

Two subtypes:

**LLM Tools** (`type: "llm"`) — weather, web_search, calculator, unit_converter:
- Have their own LLM instance (`build_llm` per tool name in `BaseToolAgent.__init__`)
- `BaseToolAgent.run(state, plan_task)` builds **`ToolInvocation`** and calls **`_tool_executor(inv)`** once. Each tool calls **`self.llm.ainvoke`** only when params from the planner are **missing** (single call; no parse-retry loops in the base class)
- Use `get_llm_semaphore()` around tool LLM calls; release before HTTP/eval/conversion work

**Function Tools** (`type: "function"`) — optional pattern for tools with no extraction step:
- Planner writes structured `params` directly into the plan
- Executor calls `agent.call(params)` directly (see `BaseFunctionTool` in `agent/tools/base.py`)

## LangGraph Execution Graph

```
START → planner_node → executor_node ←──────────────────┐
                             │                           │
                             ▼                           │
                       route_after_executor              │
                        ├── tasks_remain ───────────────►│ (loop)
                        ├── error → mark_failure_node → response_node (failure; no re-plan)
                        └── all_done → response_node → END
```

An **empty plan** (`tasks: []`) skips tool execution: `executor_node` returns immediately and `route_after_executor` routes to `response_node` (same as when every task has finished).

## LLM Provider Abstraction

Both Ollama and OpenAI use `ChatOpenAI` from `langchain-openai`. At **process startup**, set `LLM_PROVIDER` in `.env` to `openai` (default) or `ollama`. The loader deep-merges `config/shared.yaml` with `config/openai.yaml` or `config/ollama.yaml` (connection + per-agent models). The `build_llm()` function is the sole instantiation point.

## Key Modules

| Module | Purpose |
|--------|---------|
| `agent/yaml_config.py` | Merges `config/shared.yaml` + provider YAML; env resolution (`load_config`) |
| `agent/llm.py` | LLM factory + semaphore management |
| `agent/tool_cache.py` | Tool TTL cache + LangChain SQLiteCache |
| `agent/state.py` | AgentState TypedDict with merge/append/add reducers |
| `agent/prompts.py` | Planner, responder, summarizer system prompts |
| `agent/context.py` | Conversation singleton: tagged window, `summary`, `user_key_facts`; background JSON summarizer after each reply |
| `agent/memory_format.py` | `build_planner_context_block` (recent + summary); `build_responder_memory_block` (key facts + summary); separate token caps; `estimate_tokens` uses tiktoken via `tokens.count_tokens` |
| `agent/tokens.py` | Token counting + per-invocation usage tracking (merged). `count_tokens(text)` for budgeting; `record_llm_call(role, response, messages, model)` — single call that splits SystemMessage tokens (`cached_tokens`) from HumanMessage tokens (`input_tokens`), extracts `output_tokens` from provider, with tiktoken fallback. Every LLM call and aggregate total always shows the 3-way split: cached / input / output. |
| `agent/graph_nodes.py` | planner_node, executor_node, response_node, routing |
| `agent/graph.py` | LangGraph StateGraph compilation with conditional edges |
| `agent/startup.py` | Ordered initialization sequence + validation |
| `agent/tools/base.py` | ToolSpec, BaseToolAgent, BaseFunctionTool, AgentRegistry |
| `agent/tools/*.py` | Individual tool implementations (auto-discovered) |
| `app/settings.py` | Pydantic `Settings` for API, database, Redis, CORS (env-driven) |
| `app/main.py` | FastAPI factory: `/api/v1` routes, CORS, lifespan (Alembic upgrade on file SQLite, `init_db`, Redis, `agent.startup`) |
| `app/services/task_service.py` | Orchestrates task rows, Redis response cache, and `app/integrations/agent_runner` |
| `app/db/` | Async SQLAlchemy + SQLite: tasks store executor `trace_json`, full `observability_json`, `latency_ms`, token totals (`task_repository.py`, models). `migrate.py` runs Alembic to *head* on startup for on-disk DBs (Docker volume-safe); `session.py` parses `DATABASE_URL` with `make_url` |
| `app/cache/redis_cache.py` | Redis GET/SET for cached final answers (TTL) |
| `app/integrations/agent_runner.py` | Wraps timed `graph.ainvoke`, builds `observability_json`, resets usage accumulator; conversation context |
| `main.py` | Re-exports `app` for `uvicorn main:app` |

For a detailed walkthrough of the reasoning flow, see [agent-reasoning-flow.md](agent-reasoning-flow.md).

## Chat UI Shell

The [`chat-ui/`](../../chat-ui/) SPA calls **`POST /api/v1/task`** (slim metrics + answer) and can load full traces via **`GET /api/v1/tasks/{task_id}`**. A dedicated debug endpoint **`GET /api/v1/tasks/{task_id}/debug`** returns `TaskDebugResponse` with full task metadata and a `reasoning_tree` of structured steps. The UI renders this in a **debug sidebar** that slides in from the right, showing the planner, executor waves (with per-tool timing), and responder as an interactive, expandable tree. Base URL: `VITE_API_BASE_URL`. See [frontend-shell.md](frontend-shell.md).

## Docker

Redis, the FastAPI app, and the static chat UI are orchestrated with **Docker Compose**; SQLite task data is stored in a volume. The **`ollama`** Compose profile (`docker compose --profile ollama up`) starts an Ollama sidecar, a persistent model volume, and **`ollama-pull`** (background model download; it does not block the API). See [docker.md](docker.md) for run commands, pre-built images, and Ollama on the host.

## Local debugging

Use **`.vscode/launch.json`** to run **uvicorn** under the debugger (breakpoints in `app/` and `agent/`). Run **`npm run dev`** in `chat-ui/` separately. See [local-debug.md](local-debug.md).
