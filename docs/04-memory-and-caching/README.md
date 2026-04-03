# 04 · Memory, Token Usage & Caching

[← Back to DOCS](../README.md)

---

This component covers three closely related concerns:

- **Conversation memory** — how the agent remembers what was said across multiple turns without bloating every prompt
- **Token usage tracking** — how every LLM call is measured as a 3-way split (cached / input / output) and surfaced through the observability system
- **Caching layers** — five independent cache layers from in-memory process caches to Redis, each serving a different purpose and scope

---

## Pages

| Page | What it covers |
|------|---------------|
| [Conversation Memory](01-conversation-memory.md) | Rolling message window, rolling summary, durable user facts, background summarizer, per-node memory injection |
| [Token Usage Tracking](02-token-usage.md) | 3-way token split, tiktoken estimation, provider metadata, per-request accumulator, observability chain |
| [Caching Layers](03-caching-layers.md) | All 5 cache layers: system prompt, LLM instance, LangChain SQLiteCache, tool TTL, Redis response cache |
