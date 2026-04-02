# Docker deployment

Quick install steps: **[README.md](../../README.md)**. This file is the full Docker reference.

Run the **API** (FastAPI + agent), **Redis** (response cache), and **chat UI** (nginx + static Vite build) with Docker Compose. Compose sets `DATABASE_URL` and `REDIS_URL` for in-container networking; SQLite data lives in a named volume. On each API start, **Alembic runs `upgrade head`** on that file (same URL as the app), so you do not need to run migrations manually after pulling schema changes. Old volumes created before observability columns existed are upgraded automatically (including a one-time stamp when `tasks` existed without `alembic_version`).

Ollama (local LLM in Docker) is optional and controlled by the Compose profile **`ollama`**.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose v2) on Windows, macOS, or Linux.
- A **local** `.env` file (never commit real secrets).

## One-time setup

1. Clone the repository.
2. Copy the env template and edit values:

   ```bash
   copy .env.example .env
   ```

   On Linux/macOS: `cp .env.example .env`

3. In `.env`, set at least:

   - `LLM_PROVIDER` — `openai` or `ollama`
   - `OPENAI_API_KEY` when using OpenAI
   - Tool keys you need (`TAVILY_API_KEY`, `WEATHER_API_KEY`, etc.)

The `api` service uses **`env_file: .env`** and mounts **`./.env` → `/app/.env`** read-only. The compose file also sets **`LLM_PROVIDER`** and **`OLLAMA_BASE_URL`** on the `api` service using **variable substitution from your project `.env`** (`${LLM_PROVIDER:-openai}`, `${OLLAMA_BASE_URL:-...}`), so those two keys match what Compose reads when you run `docker compose` (see `docker-compose.yml`). Other keys still come from `env_file` as usual. **The file `./.env` must exist** before `docker compose up`.

---

## Step-by-step: OpenAI only (default)

Use this when you want **ChatGPT / OpenAI** and **no** Ollama containers.

1. Copy `.env.example` → `.env` if you have not already.
2. In `.env` set:

   ```env
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-...
   ```

   Leave **`COMPOSE_PROFILES`** unset (or empty). Do not pass `--profile ollama`.
3. From the **repository root**:

   ```bash
   docker compose up --build
   ```

4. Open **API**: `http://127.0.0.1:8000` — e.g. `GET http://127.0.0.1:8000/api/v1/health`  
   **Chat UI**: `http://127.0.0.1:8080`  
   **Redis** (optional to use from host): `localhost:6379`

Stop: `Ctrl+C`, or `docker compose down`. SQLite data persists until `docker compose down -v`.

---

## Step-by-step: Ollama in Docker (`--profile ollama`)

Use this when the LLM should run **inside Docker** (Ollama service + automatic **`ollama-pull`**). The API **does not wait** for the model download: you can keep **`LLM_PROVIDER=openai`** until the pull finishes, then switch to Ollama and recreate the API container.

1. Copy `.env.example` → `.env` if needed.
2. **Start the stack with the Ollama profile** (from repo root):

   ```bash
   docker compose --profile ollama up --build
   ```

   **Alternative** — set in `.env`:

   ```env
   COMPOSE_PROFILES=ollama
   ```

   Then a plain `docker compose up --build` also starts the Ollama services.

3. **While the model downloads (first run)**  
   In `.env` you can keep:

   ```env
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-...
   OLLAMA_BASE_URL=http://ollama:11434/v1
   ```

   Recreate the API if you changed `.env`: `docker compose --profile ollama up -d --build --force-recreate api`  
   Use the app with **OpenAI**; watch logs for **`ollama-pull`** until the pull completes.

4. **Switch to Ollama**  
   In `.env` set:

   ```env
   LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=http://ollama:11434/v1
   ```

   Then recreate the API so it picks up the new provider:

   ```bash
   docker compose --profile ollama up -d --build --force-recreate api
   ```

   (Or stop and `docker compose --profile ollama up --build` again.)

5. **Optional checks**

   ```bash
   docker compose --profile ollama exec ollama ollama list
   ```

**Model name**: Default pull is **`mistral`** (see `config/ollama.yaml`). Override with **`OLLAMA_PULL_MODEL`** in `.env` (must match YAML).

**Ollama container env (VRAM / stability)** — set on the **`ollama`** service in `docker-compose.yml`:

- `OLLAMA_NUM_PARALLEL=1` — limits concurrent inference (fewer VRAM spikes).
- `OLLAMA_GPU_OVERHEAD=1073741824` — reserves ~1 GB VRAM headroom.

**Persistence**: Models live in the **`ollama_data`** volume. `docker compose down -v` removes volumes, including downloaded models.

**GPU in Docker**

- **Linux / Windows (WSL2)**: Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). The **`ollama`** service includes a **`deploy`** GPU reservation; **comment out the entire `deploy:` block** if you run CPU-only (Compose may error without a GPU/driver).
- After the stack is up and you send a chat, on the host run **`nvidia-smi`**: you should see Ollama using VRAM and non-zero GPU utilization when a request is in flight.
- **Avoid conflicts**: do not run **host** Ollama on `11434` at the same time as this container (one listener per port).
- **macOS (Docker Desktop)**: GPU passthrough into Ollama containers is not supported; prefer **host Ollama** (below) or CPU inside Docker (slow).

---

## Quick reference (commands)

| Goal | Command |
|------|---------|
| OpenAI stack only | `docker compose up --build` |
| Include Ollama + pull | `docker compose --profile ollama up --build` |
| Recreate API after editing `.env` | `docker compose --profile ollama up -d --build --force-recreate api` (use `--profile ollama` whenever that profile is part of your project) |

---

## Run everything (short version)

From the **repository root**:

```bash
docker compose up --build
```

With Ollama profile:

```bash
docker compose --profile ollama up --build
```

---

## What testers need

**Option A — from Git (build locally)**  

Dockerfile(s) are in the repo; testers clone, add `.env`, then `docker compose up --build` (or `--profile ollama` for local LLM). No separate image download unless you publish images (Option B).

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

Add **`--profile ollama`** to those commands if you also use the Ollama sidecar from the main compose file.

They still need a `.env` with secrets (or equivalent env vars); images do not embed API keys.

---

## Chat UI → API URL

The SPA is built with `VITE_API_BASE_URL` (see `chat-ui/Dockerfile` and `docker-compose.yml`). The default `http://127.0.0.1:8000` is correct when the **browser** runs on the same machine that publishes port `8000`.

If testers open the UI from another machine, set the build arg to a reachable API URL (e.g. `http://192.168.1.10:8000`) and rebuild the `web` image, or add a reverse proxy so one host/port serves both.

---

## Local LLM (Ollama) — how this app wires it

The agent uses **OpenAI-compatible** endpoints via LangChain’s `ChatOpenAI` (`agent/llm.py`). Ollama exposes that at **`{base}/v1`**. Configuration comes from `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL`, and merged YAML in `config/ollama.yaml`. Concurrency is limited to **one** in-flight LLM call when `provider == ollama` (single-GPU friendly).

**Default model** (all agents in `config/ollama.yaml`): **`mistral`**, with **`num_ctx` ≤ 4096** for planner/responder and smaller for tools (limits KV-cache VRAM; see `agent/llm.py`).

With **`--profile ollama`**, **`ollama-pull`** downloads that model into the volume in the background; remain on **OpenAI** until the pull completes if you want the API usable immediately.

---

## Option A — Install Ollama on the **host** (not containerized)

Docker **does not** pull models on the host. Install from [https://ollama.com/download](https://ollama.com/download), then:

```bash
ollama pull mistral
```

**`.env` — API on host**: `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://localhost:11434/v1`

**API in Docker, Ollama on host**: `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` (Linux may need `extra_hosts: host.docker.internal:host-gateway` on `api`).

Do **not** pass `--profile ollama` if you are not using the Ollama container.

---

## Single-container Ollama (upstream)

```bash
docker run -d --gpus=all -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
```

Use `--gpus=all` only when the NVIDIA toolkit is available; omit for CPU.

---

## What can still fail (checklist)

| Issue | Symptom | Mitigation |
|--------|---------|------------|
| **No `.env` file** | Compose error about missing `env_file` | `cp .env.example .env` first |
| **`LLM_PROVIDER=openai` but no key** | Errors when calling OpenAI | Set `OPENAI_API_KEY` |
| **`LLM_PROVIDER=ollama` before pull finishes** | Model errors from Ollama | Wait for `ollama-pull` or check `ollama list` |
| **`OLLAMA_BASE_URL` wrong** | Connection errors | In Docker → Ollama service use `http://ollama:11434/v1` |
| **Host Ollama without pull** | Model not found | `ollama pull` on host |
| **Tool APIs** | Tool-specific errors | Set real keys in `.env` for tools you use |

---

## Troubleshooting (Ollama)

- **Connection refused**: Confirm `OLLAMA_BASE_URL` and that the `ollama` service is up (`docker compose --profile ollama ps`).
- **Model not found**: Align `OLLAMA_PULL_MODEL` and `config/ollama.yaml`; run `docker compose --profile ollama exec ollama ollama pull <model>`.
- **Slow or OOM**: Smaller models / lower `num_ctx` in `config/ollama.yaml` (see [tool-development-guide.md](tool-development-guide.md)).

---

## Troubleshooting

- **`docker` not found**: Install Docker Desktop and restart the terminal; ensure Docker is running.
- **CORS errors**: Add your UI origin to `CORS_ORIGINS` in compose or `.env` (comma-separated).
- **Redis / health degraded**: Ensure the `redis` service is healthy before `api` starts; `REDIS_OPTIONAL=false` in compose requires Redis.
