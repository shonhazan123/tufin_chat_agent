# System Design — Ollama Local LLM

[← Component README](README.md) · [Docker Setup →](02-docker-setup.md)

---

## How Ollama Plugs into the Stack

The agent uses LangChain's `ChatOpenAI` for all LLM calls. Ollama exposes an OpenAI-compatible API at `/v1`, so **zero agent code changes** are needed to switch providers.

```mermaid
flowchart LR
    subgraph agent ["agent/llm_provider_factory.py"]
        LLM["ChatOpenAI — base_url=OLLAMA_BASE_URL, model=qwen2.5:7b-instruct-q4_K_M"]
    end

    subgraph docker ["Docker — profile ollama"]
        Ollama["ollama container — :11434/v1 — OpenAI-compatible"]
        Volume[("ollama_data — model weights")]
    end

    LLM -->|"HTTP POST /v1/chat/completions"| Ollama
    Ollama --> Volume
```

The `base_url` resolves to `http://ollama:11434/v1` inside Docker (Compose service DNS) and `http://localhost:11434/v1` for local host development. Both are set via `OLLAMA_BASE_URL` in `.env`.

---

## Docker Service Topology

```mermaid
flowchart TB
    subgraph compose ["docker-compose.yml — profile ollama"]
        Web["web — nginx :8080"]
        API["api — uvicorn :8000"]
        Redis["redis — :6379"]
        Ollama["ollama — :11434"]
        Pull["ollama-pull — one-shot download"]
        SQLiteVol[("sqlite_data")]
        OllamaVol[("ollama_data")]
    end

    Web -->|"API calls"| API
    API -->|"cache"| Redis
    API -->|"LLM calls"| Ollama
    API -->|"task rows"| SQLiteVol
    Pull -->|"ollama pull"| Ollama
    Ollama --> OllamaVol
```

`ollama-pull` is a **one-shot** container — it runs once, downloads the model into the volume, and exits. It does not block the API from starting.

---

## Concurrency Control

Local inference is single-threaded by nature — concurrent LLM calls on a single GPU do not parallelize; they queue and create memory pressure.

This is handled by a semaphore in `agent/llm_provider_factory.py`:

| Provider | Semaphore limit | Reason |
|----------|----------------|--------|
| `openai` | 5 | External API can handle parallel requests |
| `ollama` | **1** | Single GPU — serialize LLM calls to avoid OOM |

The semaphore is held **only during LLM inference** and released before HTTP/computation work. This means API calls from multiple tools can still overlap even when LLM calls are serialized.

---

## Config Path for Ollama

```mermaid
flowchart LR
    env[".env — LLM_PROVIDER=ollama"]
    shared["config/shared.yaml — tools, executor, cache"]
    ollama["config/ollama.yaml — models, num_ctx per agent"]
    merged["config_loader.py — deep-merge result"]
    factory["llm_provider_factory.py — build_llm() — forwards num_ctx via extra_body"]

    env --> ollama
    shared --> merged
    ollama --> merged
    merged --> factory
```

The `num_ctx` value is forwarded to Ollama as `options.num_ctx` in the API request body — it is not a standard `ChatOpenAI` parameter. This is handled in `build_llm()` via `extra_body`.
