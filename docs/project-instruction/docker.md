# Docker deployment

Run the **API** (FastAPI + agent), **Redis** (response cache), and **chat UI** (nginx + static Vite build) with Docker Compose. Compose sets `DATABASE_URL` and `REDIS_URL` for in-container networking; SQLite data lives in a named volume.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose v2) on Windows, macOS, or Linux.
- API keys and provider settings in a **local** `.env` file (never commit real secrets).

## One-time setup

1. Clone the repository.
2. Copy the env template and edit values:

   ```bash
   copy .env.example .env
   ```

   On Linux/macOS: `cp .env.example .env`

3. In `.env`, set at least:

   - `LLM_PROVIDER` — `openai` or `ollama`
   - `OPENAI_API_KEY` if using OpenAI
   - Tool keys you need (`TAVILY_API_KEY`, `WEATHER_API_KEY`, etc.)

The `api` service uses **`env_file: .env`** (all keys such as `LLM_PROVIDER`, `OPENAI_API_KEY`, tool keys) and mounts **`./.env` → `/app/.env`** read-only so `load_dotenv()` and Pydantic’s `env_file` path match local runs. Compose **`environment`** still overrides `DATABASE_URL`, `REDIS_URL`, `REDIS_OPTIONAL`, and `CORS_ORIGINS` for container networking and the Docker chat UI. Create `.env` from `.env.example` before `docker compose up` (both mechanisms expect the file to exist).

## Run everything (build from source)

From the **repository root**:

```bash
docker compose up --build
```

- **API**: `http://127.0.0.1:8000` — e.g. `GET http://127.0.0.1:8000/api/v1/health`
- **Chat UI**: `http://127.0.0.1:8080`
- **Redis**: `localhost:6379` (optional to expose; the `api` container uses hostname `redis` internally)

Stop: `Ctrl+C`, or `docker compose down`. Data in the SQLite volume persists until you run `docker compose down -v`.

## What testers need

**Option A — from Git (build locally)**  

Dockerfile(s) are in the repo; testers clone, add `.env`, then `docker compose up --build`. No separate “download image” step unless you publish images (Option B).

**Option B — pre-built images (optional)**  

A maintainer builds and pushes two images (API and web) to a registry (GHCR, Docker Hub, etc.):

```bash
docker build -t YOUR_REGISTRY/tufin-agent-api:latest .
docker build -t YOUR_REGISTRY/tufin-agent-web:latest ./chat-ui
docker push YOUR_REGISTRY/tufin-agent-api:latest
docker push YOUR_REGISTRY/tufin-agent-web:latest
```

Testers copy `docker-compose.images.example.yml` to `docker-compose.images.yml`, replace `YOUR_REGISTRY/...` tags, then:

```bash
docker compose -f docker-compose.yml -f docker-compose.images.yml pull
docker compose -f docker-compose.yml -f docker-compose.images.yml up -d
```

They still need a `.env` with secrets (or equivalent env vars); images do not embed API keys.

## Chat UI → API URL

The SPA is built with `VITE_API_BASE_URL` (see `chat-ui/Dockerfile` and `docker-compose.yml`). The default `http://127.0.0.1:8000` is correct when the **browser** runs on the same machine that publishes port `8000`.

If testers open the UI from another machine, set the build arg to a reachable API URL (e.g. `http://192.168.1.10:8000`) and rebuild the `web` image, or add a reverse proxy so one host/port serves both.

## Ollama on the host (not in Docker)

Point the API at the host from inside the container, for example in `.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

On Linux, `host.docker.internal` may require `extra_hosts` on the `api` service (see Docker docs for your version).

## Troubleshooting

- **`docker` not found**: Install Docker Desktop and restart the terminal; ensure Docker is running.
- **CORS errors**: Add your UI origin to `CORS_ORIGINS` in compose or `.env` (comma-separated).
- **Redis / health degraded**: Ensure the `redis` service is healthy before `api` starts; `REDIS_OPTIONAL=false` in compose requires Redis.
