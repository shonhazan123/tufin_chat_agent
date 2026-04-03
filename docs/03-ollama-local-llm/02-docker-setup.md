# Docker Setup — Ollama Local LLM

[← Component README](README.md) · [← System Design](01-system-design.md) · [Performance & Limits →](03-performance-and-limits.md)

---

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2)
- NVIDIA GPU with the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed — **GPU is required**; the `docker-compose.yml` reserves the NVIDIA device by default

---

## Running the Stack

**1. Create `.env`**

```bash
cp .env.example .env
```

Set in `.env`:

```env
LLM_PROVIDER=ollama
# OPENAI_API_KEY not required for Ollama
WEATHER_API_KEY=...
TAVILY_API_KEY=...
```

**2. Start with the Ollama profile**

```bash
docker compose --profile ollama up --build
```

What happens on first run:
- `ollama` container starts and exposes port `11434`
- `ollama-pull` downloads the default model into the `ollama_data` volume *(this can take several minutes)*
- `api` starts, connects to Redis, runs agent startup, and begins the warmup background task
- `web` (nginx) starts once the API is healthy

**3. Check readiness**

```
GET http://127.0.0.1:8000/api/v1/health/model
```

Returns one of:

| Status | Meaning |
|--------|---------|
| `downloading` | `ollama-pull` still in progress |
| `warming_up` | Model loaded, running warmup prompt |
| `ready` | Model ready to serve requests |
| `error` | Warmup failed — check `docker compose logs api` |

**4. Open the app**

- Chat UI: `http://127.0.0.1:8080`
- API: `http://127.0.0.1:8000/api/v1/health`

---

## Model Selection

The default model is `qwen2.5:7b-instruct-q4_K_M`.

To use a different model:

1. Update `config/ollama.yaml` — change `model:` under every agent role
2. Set `OLLAMA_PULL_MODEL` in `.env` to match
3. Rebuild and recreate the API container:

```bash
docker compose --profile ollama up -d --build --force-recreate api
```

---

## Host Ollama (without the container)

Install Ollama on the host from [ollama.com/download](https://ollama.com/download), pull the model manually, and set in `.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
```

Do **not** pass `--profile ollama` when running `docker compose` in this case.
