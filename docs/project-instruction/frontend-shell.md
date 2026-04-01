# Chat UI shell (`chat-ui/`)

The front-end in [`chat-ui/`](../../chat-ui/) (Vite + React + TypeScript + Tailwind) talks to the FastAPI service over HTTP.

## Configuration

| Variable | Purpose |
|----------|---------|
| `VITE_API_BASE_URL` | Base URL of the API (default in code: `http://127.0.0.1:8000` if unset). |
| `VITE_API_KEY` | Optional; sent as `X-API-Key` when the server has `API_KEY` set. |

See [`chat-ui/.env.example`](../../chat-ui/.env.example).

## API contract

- **`POST {base}/api/v1/task`** — JSON body `{ "task": "..." }`. Response: `task_id`, `final_answer`, `trace`.
- The UI maps `final_answer` to the assistant bubble and `trace` to the trace panel.

## CORS

The API enables CORS for origins from `CORS_ORIGINS` (e.g. `http://localhost:5173` in development).

## Static / Docker

The SPA can still be built and served as static files (see [`chat-ui/README.md`](../../chat-ui/README.md)). Point `VITE_API_BASE_URL` at the deployed API host (in Docker it is passed as a **build arg**; see [docker.md](docker.md)).
