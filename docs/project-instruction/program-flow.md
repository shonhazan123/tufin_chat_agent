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
9. app/main.py             → FastAPI lifespan: init SQLite tables, Redis client, then `agent.startup.startup()`; uvicorn starts (see [docker.md](docker.md) for containerized Redis + API + static UI)
```

## Request Lifecycle

```
API receives POST /api/v1/task with { "task": "..." }
  │
  ├── Insert Task row (pending) in SQLite; optional Redis cache lookup by normalized task hash
  ├── On cache hit: update row from cached final_answer + trace; return (no graph run)
  ├── On miss: conversation_context.add_user(task)
  │
  ▼
graph.ainvoke({
    "task":            task,
    "context_summary": conversation_context.summary,
    "plan":            None,
    "results":         {},
    "trace":           [],
    "response":        None,
    "retry_count":     0,
    "error_context":   "",
    "failure_flag":    False,
})
  │
  ▼
┌─ planner_node ─────────────────────────────────────────┐
│  Builds HumanMessage with task + context_summary       │
│  Invokes planner LLM → parses JSON plan                │
│  Returns {"plan": [...tasks...]}                       │
└────────────────────────────────────────────────────────-┘
  │
  ▼
┌─ executor_node (wave loop) ────────────────────────────┐
│  Finds ready tasks (all deps satisfied)                │
│  For LLM tools: agent.run(..., planner_params, context_summary) │
│  For function tools (if any): agent.call(params)       │
│  Runs all ready tasks via asyncio.gather()             │
│  Returns {"results": {...}, "trace": [...]}            │
└────────────────────────────────────────────────────────-┘
  │
  ▼
route_after_executor:
  - tasks_remain → back to executor_node
  - error → retry_router (re-plan if under max_retries)
  - all_done → response_node
  │
  ▼
┌─ response_node ────────────────────────────────────────┐
│  Invokes responder LLM with all results + trace        │
│  If failure_flag: returns polite error message          │
│  Returns {"response": "natural language answer"}       │
└────────────────────────────────────────────────────────-┘
  │
  ▼
Graph returns to API layer
  │
  ├── Update Task row in SQLite (completed / failed); SET Redis cache payload on success
  ├── Send response to user (zero added latency)
  ├── conversation_context.add_assistant(answer)
  └── asyncio.create_task(context.summarize_async(llm))  ← fire-and-forget
```

## State Flow Through Reducers

| Field | Reducer | Behavior |
|-------|---------|----------|
| `task` | last-write-wins | Set once at graph entry, never overwritten |
| `context_summary` | last-write-wins | Snapshot from conversation context |
| `plan` | last-write-wins | Set by planner; **replaced** on retry with new plan |
| `results` | `_merge` | Dict grows each executor wave (shallow merge) |
| `trace` | `_append` | List grows each executor wave (concatenate) |
| `response` | last-write-wins | Set once by response_node |
| `retry_count` | `operator.add` | Incremented by 1 on each error |
| `error_context` | last-write-wins | Latest error; cleared on success or re-plan |
| `failure_flag` | last-write-wins | True when retries exhausted |

## LLM Semaphore Behavior

For Ollama (single GPU): Semaphore(1) serializes LLM calls.
For OpenAI: Semaphore(5) allows parallel calls.

The semaphore is held only during LLM param extraction, released before API calls. This allows API calls from multiple tools to overlap even when LLM calls are serialized.

## Cursor: code-quality review skill

The project skill `.cursor/skills/codecraft-reviewer/` defines **CodeCraft Reviewer**: PR-style feedback on naming, duplication, readability, and maintainability at the code level, **without** architecture or scalability discussion. Invoke when asking for a clean-code or readability-focused review.
