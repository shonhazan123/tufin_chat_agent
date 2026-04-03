# Tufin Agent

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

In `.env`: `LLM_PROVIDER=ollama`. Compose sets `OLLAMA_BASE_URL=http://ollama:11434/v1` for the **api** container automatically (your `.env` can keep `localhost` for local runs outside Docker).

```bash
docker compose --profile ollama up --build
```

The first Ollama run downloads a large model and can take a long time. Have enough free disk space.

---

## Open the app

- Chat: [http://127.0.0.1:8080](http://127.0.0.1:8080)
- Health: [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)

Stop: `Ctrl+C`, or `docker compose down` (if you used Ollama, `docker compose --profile ollama down`).

---

More: [docs/project-instruction/docker.md](docs/project-instruction/docker.md)
