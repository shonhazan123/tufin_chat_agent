# 03 · Ollama Local LLM

[← Back to DOCS](../README.md)

---

Ollama is the **local runtime option** — the same LangGraph agent runs without any external API key, using a quantized model inside a Docker container.

The agent code does not change between providers. The only difference is configuration: `LLM_PROVIDER=ollama` in `.env` causes the config loader to merge `config/ollama.yaml` instead of `config/openai.yaml`.

---

## Pages

| Page | What it covers |
|------|---------------|
| [System Design](01-system-design.md) | How Ollama plugs into the stack, Docker service topology, concurrency control |
| [Docker Setup](02-docker-setup.md) | Step-by-step run instructions, model selection, warmup |
| [Performance & Limits](03-performance-and-limits.md) | Quantization, KV cache, VRAM tuning knobs, troubleshooting |
