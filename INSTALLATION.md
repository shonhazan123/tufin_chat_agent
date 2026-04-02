# Installation

## 1. Install Docker

1. Download **Docker Desktop**: [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
2. Run the installer and restart if it asks.
3. Open **Docker Desktop** and wait until it is **running** (no errors in the app window).

On Windows, if the terminal says `docker` is not recognized, add this folder to your user **PATH**, then open a **new** terminal:

`C:\Program Files\Docker\Docker\resources\bin`

---

## 2. Clone and configure

```bash
git clone <repo-url>
cd tufin_agent
Past .env KEYS your were given
```

Edit **`.env`**:

- **`OPENAI_API_KEY`** — required for OpenAI mode.
- **`LLM_PROVIDER`** — `openai` or `ollama`.
- For **Ollama in Docker** also set **`OLLAMA_BASE_URL=http://ollama:11434/v1`** (not `localhost`).

---

## 3. Run

**OpenAI**

```bash
docker compose up --build
```

**Ollama (local model in Docker)** — first run downloads a large model; be patient.

```bash
docker compose --profile ollama up --build
```

---

## 4. Use the app

- **Chat:** [http://127.0.0.1:8080](http://127.0.0.1:8080)
- **Health:** [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)

Stop: `Ctrl+C` or `docker compose down` (add `--profile ollama` if you used that profile).

---

## More help

Full Docker notes: [docs/project-instruction/docker.md](docs/project-instruction/docker.md)
