# Code Design — API + Persistence + Cache

[← Component README](README.md) · [← System Design](01-system-design.md) · [Folder Structure →](03-folder-structure.md)

---

## Startup (`app/main.py` lifespan)

On process start, the FastAPI `lifespan` context runs in this order:

```mermaid
flowchart TD
    A["Alembic — upgrade head, schema migrations"]
    B["init_db() — create engine and session factory"]
    C["Redis connect — ping, degrade gracefully if unreachable"]
    D["startup_initialization.startup() — config, tools, prompts, graph"]
    E["asyncio.create_task warmup_model() — runs in background"]

    A --> B --> C --> D --> E
```

---

## Request Flow Through the Code

```mermaid
flowchart TD
    Route["task_management_routes.py — POST /task"]
    Service["task_orchestration_service.py — create_and_run_task()"]
    Cache["redis_cache.py — get_cached_response()"]
    Runner["agent_runner.py — run_agent_task()"]
    Graph["graph.ainvoke(initial_state)"]
    Repo["task_repository.py — complete()"]
    SetCache["redis_cache.py — set_cached_response()"]

    Route --> Service
    Service --> Cache
    Cache -->|"hit"| Repo
    Cache -->|"miss"| Runner
    Runner --> Graph
    Graph --> Runner
    Runner --> Service
    Service --> Repo
    Service --> SetCache
```

---

## Task Repository States

```mermaid
stateDiagram-v2
    [*] --> pending : create_pending()
    pending --> running : mark_running()
    running --> completed : complete()
    running --> failed : fail()
    pending --> cached : complete(status=cached)
```

---

## Agent Runner (`app/integrations/agent_runner.py`)

This module is the boundary between the API layer and LangGraph. It:

1. Resets the per-request token accumulator (`reset_usage()`)
2. Attaches conversation memory to the initial state
3. Calls `graph.ainvoke(initial_state)` with a recursion limit derived from `executor.max_waves`
4. Builds `observability_json` from the result state + token usage
5. Schedules background conversation summarization (non-blocking — runs after the HTTP response returns)

---

## Warmup Manager (`app/warmup/`)

Only active when `LLM_PROVIDER=ollama`. Runs in background after startup completes.

```mermaid
flowchart TD
    Start["warmup_model() — background asyncio task"]
    Check{provider == ollama?}
    Skip["Set status: SKIPPED"]
    Poll["Poll GET /api/tags every 10s — timeout 600s"]
    Warm["Send warmup prompt — 3 attempts"]
    Ready["Set status: READY"]
    Error["Set status: ERROR — API stays up in degraded mode"]

    Start --> Check
    Check -->|no| Skip
    Check -->|yes| Poll
    Poll -->|model found| Warm
    Poll -->|timeout| Error
    Warm -->|success| Ready
    Warm -->|all attempts fail| Error
```

Status is exposed at `GET /api/v1/health/model` for the UI to poll.
