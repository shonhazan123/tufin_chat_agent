# Local debugging (API + agent + UI)

Use the **Python debugger** for the FastAPI process (agent graph, tools, routes run in-process). Run the **chat UI** separately with Vite so you get hot reload without rebuilding Docker.

## Prerequisites

- Python env with `requirements.txt` installed (same interpreter selected in Cursor / VS Code).
- **`.env`** at the repo root (keys, `LLM_PROVIDER`, etc.). For Redis on the host port exposed by Compose, use e.g. **`REDIS_URL=redis://127.0.0.1:6379/0`**.
- **`DATABASE_URL`:** use a **local** SQLite URL for host debugging, e.g. **`sqlite+aiosqlite:///./data/app.db`** (see `.env.example`). Docker Compose overrides this to **`sqlite+aiosqlite:////data/app.db`** inside the container. `app/db/session.py` uses SQLAlchemy’s URL parser so both forms create the parent directory correctly.
- **Docker Desktop** installed and running — both debug configurations run **`preLaunchTask`** **`docker: Redis up`** (see `.vscode/tasks.json`) so **`docker compose up redis -d`** runs before uvicorn starts. On Windows, the task prepends Docker’s CLI path (`…\\Docker\\resources\\bin`) because Cursor/VS Code sometimes starts with a **PATH** that does not include `docker`.

**If the pre-launch task fails with “docker is not recognized”:** start Docker Desktop, then **fully quit and reopen Cursor** (or sign out/in so PATH updates). If it still fails, add Docker’s `bin` folder to your user or system **PATH** (Docker Desktop → Settings → Advanced → “Add CLI to PATH” or add `C:\Program Files\Docker\Docker\resources\bin` manually).

With Redis optional (`REDIS_OPTIONAL=true` in `.env`), the API can start without Redis (cache miss only), but the pre-launch task still starts Redis when Docker is available.

**Note:** You debug **Python** (API, agent, `app/cache/redis_cache.py`, etc.). The **Redis server** runs in Docker; use `docker compose logs redis -f` or `redis-cli` for the server process itself.

## Debug the API + agent

1. Open **Run and Debug** (Ctrl+Shift+D), choose **`API + agent (uvicorn, debug)`**, press F5 — Redis starts first, then the API.
2. Set breakpoints in `app/`, `agent/`, etc.
3. Prefer **`API + agent (uvicorn, debug)`** (no `--reload`) so breakpoints stay in one process. Use **`… debug + reload`** only if you need auto-restart on file changes; it uses `subProcess` so behavior can differ slightly.

`launch.json` sets `PYTHONPATH` to the repo root and loads **`.env`** via `envFile`.

## Run the UI (separate terminal)

From `chat-ui/`:

```bash
npm run dev
```

Point the UI at the local API (default in `chat-ui/.env.example`):

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Open the Vite URL (usually `http://localhost:5173`). Requests go to the debugged server.

## CORS

Local Vite origin is `http://localhost:5173`. Ensure **`CORS_ORIGINS`** in `.env` includes it (the example template does).
