# Tufin Agent — System Documentation

---

## System Overview

```mermaid
flowchart TB
    Client(["User / Chat UI"])

    subgraph appLayer ["app/ — API + Persistence + Cache"]
        Route["Routes: task_management · health_check"]
        Service["TaskOrchestrationService · HealthCheckService"]
        Redis[("Redis — Response Cache")]
        DB[("SQLite — Tasks Table")]
    end

    subgraph agentLayer ["agent/ — LangGraph StateGraph nodes"]
        planner["planner"]
        executor["executor"]
        routeAfterExec{route_after_executor}
        markFailure["mark_failure"]
        prepareContext["prepare_context"]
        responder["responder"]
    end

    Client -->|"POST /api/v1/task"| Route
    Route --> Service
    Service <-->|"cache hit / miss"| Redis
    Service <-->|"persist"| DB
    Service -->|"graph.ainvoke START→planner"| planner
    planner --> executor
    executor --> routeAfterExec
    routeAfterExec -->|"continue next wave"| executor
    routeAfterExec -->|"fail"| markFailure
    routeAfterExec -->|"done"| prepareContext
    markFailure --> prepareContext
    prepareContext --> responder
    responder -->|"END · answer + trace"| Service
    Service -->|"response"| Client
```

Graph topology matches `agent/graph.py` (`build_graph`): **route_after_executor** chooses `continue` (another executor wave), `fail` (**mark_failure** then **prepare_context**), or `done` (**prepare_context** only). **prepare_context** tags tool outputs (FINAL vs INTERMEDIATE) for the responder; **responder** then runs before **END**. Implementation lives in `agent/graph_nodes.py`.

---

## Components

| # | Component | Role | Code |
|---|-----------|------|------|
| 1 | [LangGraph Agent](01-langgraph-agent/README.md) | The **brain** — compiled **StateGraph** (`planner` → `executor` ↔ `route_after_executor` → `mark_failure` / `prepare_context` → `responder`). Plugin tools and factory-driven config. | `agent/graph.py` · `agent/graph_nodes.py` |
| 2 | [API + Persistence + Cache](02-api-app/README.md) | The **product layer** — FastAPI endpoints, SQLite task persistence, Redis response cache, full observability trace. | `app/` |
| 3 | [Ollama Local LLM](03-ollama-local-llm/README.md) | The **local runtime** — runs the same agent with no external API key. Tuned for limited VRAM via quantization and context capping. | `config/ollama.yaml` + `docker-compose.yml` |
| 4 | [Memory, Token Usage & Caching](04-memory-and-caching/README.md) | The **context layer** — rolling conversation memory, 3-way token tracking, and five stacked cache layers from in-process to Redis. | `agent/conversation_memory.py` · `agent/token_usage_tracker.py` · `agent/tool_result_cache.py` |

---

## Repository Layout

```
tufin_agent/
│
├── agent/                   ← LangGraph brain (planner, executor, tools, memory)
├── app/                     ← FastAPI, SQLite, Redis, `app/types/` StrEnums, split routes/services
├── config/
│   ├── shared.yaml          ← shared executor / tool / cache settings
│   ├── openai.yaml          ← OpenAI models + API key
│   └── ollama.yaml          ← Ollama models + num_ctx per agent
│
├── docs/                    ← this documentation
│   ├── README.md
│   ├── 01-langgraph-agent/
│   ├── 02-api-app/
│   ├── 03-ollama-local-llm/
│   └── 04-memory-and-caching/
│
├── chat-ui/                 ← Vite + React frontend (served by nginx in Docker)
├── tests/                   ← pytest suite
├── docker-compose.yml       ← full stack (Redis · API · UI · Ollama profile)
├── Dockerfile               ← API container
└── .env.example             ← all required env vars
```
