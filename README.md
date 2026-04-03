# Tufin Agent

A **LangGraph-based multi-tool agent** fully customizable — select your LLM provider and model per tool, submit natural language tasks, and get structured answers with a full execution trace. The agent understands conversation context across turns and caches answers to preserve computational resources.

---

## Install Docker

1. Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Open Docker Desktop and wait until it is running.

If `docker` is not found in the terminal (Windows), add this folder to your **PATH**, then open a new terminal:

`C:\Program Files\Docker\Docker\resources\bin`

---

## Clone and `.env`

```bash
git clone <repo-url>
cd tufin_agent
cp .env.example .env
```

Edit **`.env`**. Use the next section so your values match the command you run.

---

## Two ways to run

Pick **one**. The command and `.env` must match.

**1 — OpenAI**

In `.env`: `LLM_PROVIDER=openai` and a valid `OPENAI_API_KEY`.

```bash
docker compose up --build
```

**2 — Ollama (model inside Docker)**

> **System Requirements**
>
> | Resource | Minimum | Recommended |
> |----------|---------|-------------|
> | RAM | 8 GB | 16 GB |
> | Free disk space | 6 GB | 10 GB |
> | CPU cores | 4 | 8+ |
> | GPU (optional) | — | NVIDIA with 6 GB+ VRAM |
>
> **First-run time estimates:**
> - Model download: **5 – 15 min** depending on internet speed (~4 GB file)
> - Model warmup (first inference): **1 – 3 min** on CPU, under 30 sec with a GPU
> - Subsequent runs start in seconds (model is cached on disk)

> ## ⚠️ REQUIRED — Edit your `.env` before running
> ### Set `LLM_PROVIDER=ollama` in your `.env` file or the agent will not use Ollama.

In `.env`: `LLM_PROVIDER=ollama`. Compose sets `OLLAMA_BASE_URL=http://ollama:11434/v1` for the **api** container automatically (your `.env` can keep `localhost` for local runs outside Docker).

```bash
docker compose --profile ollama up --build
```

---

## Open the app

- Chat: [http://127.0.0.1:8080](http://127.0.0.1:8080)
- Health: [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)

> **Want to test the agent?** See [AGENT_TESTS.md](AGENT_TESTS.md) for a full set of ready-to-run test prompts and expected outputs.

Stop: `Ctrl+C`, or `docker compose down` (if you used Ollama, `docker compose --profile ollama down`).

---

## Documentation

| # | Topic | Description |
|---|-------|-------------|
| — | [Full Docs Index](docs/README.md) | System overview, architecture diagram, and repository layout |
| 1 | [LangGraph Agent](docs/01-langgraph-agent/README.md) | Plan-and-execute graph, parallel tool waves, plugin tool system |
| 2 | [API + Persistence + Cache](docs/02-api-app/README.md) | FastAPI endpoints, SQLite task storage, Redis response cache |
| 3 | [Ollama Local LLM](docs/03-ollama-local-llm/README.md) | Running the agent locally with no external API key |
| 4 | [Memory, Token Usage & Caching](docs/04-memory-and-caching/README.md) | Conversation memory, token tracking, and five-layer cache system |

