# Chat UI shell (`chat-ui/`)

The front-end in [`chat-ui/`](../../chat-ui/) (Vite + React + TypeScript + Tailwind) talks to the FastAPI service over HTTP.

## Configuration

| Variable | Purpose |
|----------|---------|
| `VITE_API_BASE_URL` | Base URL of the API (default in code: `http://127.0.0.1:8000` if unset). |
| `VITE_API_KEY` | Optional; sent as `X-API-Key` when the server has `API_KEY` set. |

See [`chat-ui/.env.example`](../../chat-ui/.env.example).

## API contract

- **`POST {base}/api/v1/task`** — JSON body `{ "task": "..." }`. Response: `task_id`, `final_answer`, `latency_ms`, `total_input_tokens`, `total_output_tokens` (no full trace blob).
- The UI maps `final_answer` to the assistant bubble; the collapsible observability strip shows latency, token totals, and `task_id`. Full persisted trace: **`GET {base}/api/v1/tasks/{task_id}`** (`observability` field).
- **`GET {base}/api/v1/tasks/{task_id}/debug`** — `TaskDebugResponse`: task metadata (`task_text`, `status`, timestamps, `error_message`) plus `reasoning_tree` — a structured tree of `ReasoningStep` nodes (planner, executor waves with per-tool children, responder). Each step carries `duration_ms`, token counts, input/output summaries, and wave number.

## Debug sidebar

The **reasoning debug sidebar** slides in from the right and visualizes the full agent reasoning flow for any task. It can be opened two ways:

1. **From a message** — clicking the "Debug" button in the observability strip auto-fills the task ID and fetches the debug data.
2. **From the header** — clicking the magnifying-glass icon opens the sidebar with an empty input so the user can paste any task ID.

The sidebar displays:
- **Task summary card** — original task text, status badge, timestamps, total latency and tokens.
- **Reasoning tree** — a vertical tree of expandable `ReasoningStepCard` nodes:
  - **Planner** (purple) — shows the plan it produced and token usage.
  - **Executor Waves** (green) — one node per wave, with child nodes for each tool. Tool labels include wall-clock timing (e.g. `weather (342 ms)`). Expanding a tool shows input (sub_task + params) and output (result JSON).
  - **Responder** (blue) — shows the synthesized answer and token usage.
- **Token usage bar** — visual split of total input vs output tokens.

Components: `ReasoningSidebar.tsx`, `ReasoningStepCard.tsx`. No extra dependencies (pure React + Tailwind).

## CORS

The API enables CORS for origins from `CORS_ORIGINS` (e.g. `http://localhost:5173` in development).

## Static / Docker

The SPA can still be built and served as static files (see [`chat-ui/README.md`](../../chat-ui/README.md)). Point `VITE_API_BASE_URL` at the deployed API host (in Docker it is passed as a **build arg**; see [docker.md](docker.md)).
