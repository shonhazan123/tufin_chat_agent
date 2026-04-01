# Architecture Overview

## Two-Tier Plan-and-Execute Agent

This project implements a multi-tool agent using a **two-tier plan-and-execute** architecture (not ReAct). The system accepts natural language tasks, plans which tools to call and in what order, executes them with maximum parallelism via a DAG scheduler, and returns a structured answer with a full execution trace.

## Tiers

### Tier 1 — Planner LLM (Routing Intelligence)

The planner receives the current user task plus a conversation context summary. It outputs a JSON execution plan declaring:
- Which tools to call
- For every tool: structured `params` whose keys match that tool’s input schema in the registry
- For LLM-typed tools: a short natural language `sub_task` in addition to `params`
- Dependency ordering via `depends_on` arrays

The planner knows: tool names, purposes, output field names, tool types (`llm` vs `function`), and each tool’s required `params` keys (see registry / planner prompt). Each tool’s system prompt defines how the tool LLM recovers when planner args are wrong or execution fails.

### Tier 2 — Tool Agents (Domain Specialists)

Two subtypes:

**LLM Tools** (`type: "llm"`) — weather, web_search, calculator, unit_converter:
- Have their own LLM instance (model chosen per-agent in config)
- Receive planner-supplied `params` first; call the backend without the tool LLM when possible
- On missing/empty `params` or backend failure, the tool LLM infers or fixes JSON using the user request, conversation summary, sub-task, prior results, and error text (see each tool’s `system_prompt`)
- Outer attempt limit: `executor.max_tool_attempts` (default 2); inner limit for malformed JSON from the tool LLM: per-agent `max_retries` in provider YAML
- Hold the LLM semaphore only around the tool LLM call; release before HTTP/eval/conversion work

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
                        ├── error → retry_router         │
                        │            ├── retry < max → planner_node
                        │            └── retry >= max → response_node (failure)
                        └── all_done → response_node → END
```

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
| `agent/context.py` | Conversation context singleton with summarization |
| `agent/graph_nodes.py` | planner_node, executor_node, response_node, routing |
| `agent/graph.py` | LangGraph StateGraph compilation with conditional edges |
| `agent/startup.py` | Ordered initialization sequence + validation |
| `agent/tools/base.py` | ToolSpec, BaseToolAgent, BaseFunctionTool, AgentRegistry |
| `agent/tools/*.py` | Individual tool implementations (auto-discovered) |
| `app/settings.py` | Pydantic `Settings` for API, database, Redis, CORS (env-driven) |
| `app/main.py` | FastAPI factory: `/api/v1` routes, CORS, lifespan (SQLite init, Redis, `agent.startup`) |
| `app/services/task_service.py` | Orchestrates task rows, Redis response cache, and `app/integrations/agent_runner` |
| `app/db/` | Async SQLAlchemy + SQLite persistence for tasks and traces (`task_repository.py`, models, session) |
| `app/cache/redis_cache.py` | Redis GET/SET for cached final answers (TTL) |
| `app/integrations/agent_runner.py` | Wraps `graph.ainvoke` + conversation context (same behavior as legacy `main.py`) |
| `main.py` | Re-exports `app` for `uvicorn main:app` |

For a detailed walkthrough of the reasoning flow, see [agent-reasoning-flow.md](agent-reasoning-flow.md).

## Chat UI Shell

The [`chat-ui/`](../../chat-ui/) SPA calls **`POST /api/v1/task`** on the API (configurable base URL via `VITE_API_BASE_URL`). See [frontend-shell.md](frontend-shell.md).

## Docker

Redis, the FastAPI app, and the static chat UI are orchestrated with **Docker Compose**; SQLite task data is stored in a volume. See [docker.md](docker.md) for run commands, pre-built image workflow, and Ollama-on-host notes.
