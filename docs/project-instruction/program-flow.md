# Program Flow

## Startup Sequence

Initialization happens in strict order to avoid empty prompt constants and circular imports:

```
1. agent/yaml_config.py    → load_config() merges shared + openai/ollama YAML per LLM_PROVIDER; cached
2. agent/tools/__init__.py → autodiscovery; all @register decorators fire; registry populated
3. agent/prompts.py        → PLANNER_SYSTEM built from populated registry (frozen)
4. agent/llm.py            → build_llm() per agent (lru_cache warms up)
5. agent/llm.py            → init_llm_semaphore() called explicitly
6. agent/tool_cache.py    → init_llm_cache() sets up SQLiteCache
7. agent/context.py        → conversation_context singleton created
8. agent/graph.py          → LangGraph compiled
9. app/main.py             → FastAPI lifespan: init SQLite tables, Redis client, then `agent.startup.startup()`; uvicorn starts (see [docker.md](docker.md) for containers; [local-debug.md](local-debug.md) for debugging API + agent with the UI on Vite)
```

## Request Lifecycle

```
API receives POST /api/v1/task with { "task": "..." }
  │
  ├── Insert Task row (pending) in SQLite; optional Redis cache lookup by normalized task hash
  ├── On cache hit: update row from cached final_answer + trace + observability_json + latency/tokens; add_user + record_assistant_and_schedule_conversation_summary (background dialogue summarization); return slim JSON (no graph run)
  ├── On miss: conversation_context.add_user(task)
  │
  ▼
reset_invocation_usage() — per-request LLM token accumulator (contextvar); timed graph run
  │
  ▼
graph.ainvoke({
    "task":                   task,
    "context_summary":        conversation_context.summary,
    "user_key_facts":         conversation_context.user_key_facts,
    "recent_messages_text":   <last up to 5 turns, plain text>,
    "plan":                   [],
    "results":                {},
    "trace":                  [],
    "response":               "",
    "error_context":          "",
    "failure_flag":           False,
})
  │
  ▼
┌─ planner_node ─────────────────────────────────────────┐
│  HumanMessage: task + build_planner_context_block       │
│  (recent ≤5 turns + rolling summary only; token cap)    │
│  Invokes planner LLM → parses JSON plan                │
│  Returns {"plan": [...tasks...]}                       │
└────────────────────────────────────────────────────────-┘
  │
  ▼
┌─ executor_node (wave loop) ────────────────────────────┐
│  Empty plan → return {} immediately (no tools)          │
│  Else: find ready tasks (all deps satisfied)           │
│  For LLM tools: agent.run(state=state, plan_task=task)   │
│  For function tools (if any): agent.call(params)       │
│  Runs all ready tasks via asyncio.gather()             │
│  Returns {"results": {...}, "trace": [...]}             │
└────────────────────────────────────────────────────────-┘
  │
  ▼
route_after_executor:
  - empty plan → response_node (same as all_done for tools)
  - tasks_remain → back to executor_node
  - error → mark_failure_node → response_node (no planner re-run; tools already retried internally)
  - all_done → response_node
  │
  ▼
┌─ response_node ────────────────────────────────────────┐
│  Invokes responder LLM with user message, optional     │
│  user task + key facts + summary + tool results + trace  │
│  Empty plan → no tools; responder answers conversationally│
│  If failure_flag: returns polite error message          │
│  Returns {"response": "natural language answer"}       │
└────────────────────────────────────────────────────────-┘
  │
  ▼
Graph returns to API layer
  │
  ├── run_agent_task: build observability_json (context, plan, results, executor trace, llm_calls, totals); record_assistant_and_schedule_conversation_summary(answer) — tagged [assistant msg]; `summarize_async` scheduled on event loop (does not await; does not add LLM latency or tokens to the graph metrics)
  ├── Update Task row in SQLite: final_answer, trace_json (executor list), latency_ms, total_input_tokens, total_output_tokens, observability_json; SET Redis cache payload (same fields) on success
  └── Return TaskSubmitResponse to client (task_id, final_answer, latency_ms, token totals only). Full observability: GET /api/v1/tasks/{task_id} → TaskDetailResponse
```

Planner, responder, and tool LLM calls call `agent.usage.record_llm_message` so totals aggregate for the invocation.

## Observability (metrics vs persisted trace)

| Concern | Behavior |
|---------|----------|
| **POST /api/v1/task** | Slim JSON: `task_id`, `final_answer`, `latency_ms`, `total_input_tokens`, `total_output_tokens`. No full graph blob. |
| **GET /api/v1/tasks/{task_id}** | `TaskDetailResponse` includes `observability` (from `observability_json`): context snapshot, plan, results, executor trace, errors, per-LLM usage entries. |
| **Chat UI** | Collapsible strip shows latency, token totals, and `task_id` (debug/monitoring; not the primary answer). |
| **Scope** | Wall-clock and tokens cover `graph.ainvoke` only, not post-response `summarize_async`. |

## State Flow Through Reducers

| Field | Reducer | Behavior |
|-------|---------|----------|
| `task` | last-write-wins | Set once at graph entry, never overwritten |
| `context_summary` | last-write-wins | Snapshot of rolling dialogue summary at graph entry |
| `user_key_facts` | last-write-wins | Snapshot of durable user facts at graph entry (responder only; capped when injected) |
| `recent_messages_text` | last-write-wins | Last up to five turns at graph entry (planner only; capped when injected) |
| `plan` | last-write-wins | Set once by planner |
| `results` | `_merge` | Dict grows each executor wave (shallow merge) |
| `trace` | `_append` | List grows each executor wave (concatenate) |
| `response` | last-write-wins | Set once by response_node |
| `error_context` | last-write-wins | Latest error summary for logging; cleared on success |
| `failure_flag` | last-write-wins | True when routing through `mark_failure_node` |

## LLM Semaphore Behavior

For Ollama (single GPU): Semaphore(1) serializes LLM calls.
For OpenAI: Semaphore(5) allows parallel calls.

The semaphore is held only during LLM param extraction, released before API calls. This allows API calls from multiple tools to overlap even when LLM calls are serialized.

## Cursor: code-quality review skill

The project skill `.cursor/skills/codecraft-reviewer/` defines **CodeCraft Reviewer**: PR-style feedback on naming, duplication, readability, and maintainability at the code level, **without** architecture or scalability discussion. Invoke when asking for a clean-code or readability-focused review.
