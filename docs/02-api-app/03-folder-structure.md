# Folder Structure — API + Persistence + Cache

[← Component README](README.md) · [← Code Design](02-code-design.md)

---

## `app/` Tree

```
app/
│
├── main.py                      ← FastAPI app factory + lifespan
│                                   (migrations · Redis · agent startup · warmup)
│
├── settings.py                  ← Pydantic Settings: DATABASE_URL · REDIS_URL · API_KEY
│                                   CORS_ORIGINS · CACHE_TTL_SECONDS · api_v1_prefix
│
├── dependencies.py              ← FastAPI DI: get_database_session() ·
│                                   get_task_orchestration_service() (alias get_task_service)
│
├── types/                       ← StrEnum “documentation types” for API string contracts
│   ├── __init__.py              ← Re-exports health + reasoning enums
│   ├── health_status_types.py   ← OverallHealthStatus · ComponentHealthStatus · ModelWarmupStatus
│   └── reasoning_step_types.py  ← ReasoningNodeType · ReasoningStepStatus
│
├── api/
│   ├── __init__.py              ← HTTP API package marker
│   └── routes/
│       ├── __init__.py          ← Re-exports health_router, tasks_router for app.main
│       ├── task_management_routes.py   ← POST /task · GET /tasks/{id} · GET /tasks/{id}/debug
│       └── health_check_routes.py      ← GET /health · GET /health/model
│
├── middleware/
│   ├── auth.py                  ← Optional X-API-Key verification
│   └── error_handler.py        ← Global exception handler → structured JSON errors
│
├── services/
│   ├── __init__.py              ← TaskOrchestrationService · HealthCheckService
│   ├── task_orchestration_service.py  ← DB row lifecycle + Redis + agent_runner
│   ├── health_check_service.py          ← SQLite / Redis / LangGraph health aggregation
│   └── reasoning_tree_builder.py       ← observability_json → ReasoningStep[] (debug UI)
│
├── integrations/
│   └── agent_runner.py          ← Graph entry point: builds state, invokes graph,
│                                   assembles observability_json, schedules summarization
│
├── cache/
│   └── redis_cache.py           ← GET/SET with TTL · SHA-256 key builder · safe degradation
│
├── db/
│   ├── models.py                ← Task ORM model + TaskStatus enum
│   ├── task_repository.py       ← create_pending · mark_running · complete · fail · get_by_id
│   ├── session.py               ← Async engine + session factory
│   ├── migrate.py               ← Alembic upgrade head on startup
│   └── base.py                  ← SQLAlchemy declarative Base
│
├── warmup/
│   ├── manager.py               ← Poll Ollama /api/tags → send warmup prompt
│   ├── status.py                ← ModelWarmupStatus (alias ModelStatus) + model_state singleton
│   └── __init__.py              ← Re-exports warmup_model · ModelStatus · model_state
│
├── schemas/
│   ├── __init__.py              ← Re-exports public DTOs for `from app.schemas import …`
│   ├── task_schemas.py          ← TaskRequest · TaskSubmitResponse · TaskDetailResponse
│   │                               TaskDebugResponse · ReasoningStep
│   └── health_check_schemas.py  ← HealthResponse · ModelStatusResponse
│
└── observability/
    ├── logging.py               ← Structured logging helpers
    └── tracing.py               ← Tracing hooks
```

---

## Key Data Flow Between Modules

```mermaid
flowchart LR
    Route["routes/task_management_routes.py"] --> Service["services/task_orchestration_service.py"]
    Service --> Cache["cache/redis_cache.py"]
    Service --> Repo["db/task_repository.py"]
    Service --> Runner["integrations/agent_runner.py"]
    Service --> Tree["services/reasoning_tree_builder.py"]
    Runner --> Graph["agent/ graph.ainvoke()"]
    Repo --> DB[("SQLite")]
    Cache --> Redis[("Redis")]
```
