# 02 · API + Persistence + Cache

[← Back to DOCS](../README.md)

---

The `app/` layer wraps the LangGraph agent in a production-ready HTTP service.

It is responsible for:
- exposing stable REST endpoints
- persisting every task with its full execution trace and observability payload
- caching identical requests via Redis to avoid re-running the graph
- running DB schema migrations automatically on startup

---

## Pages

| Page | What it covers |
|------|---------------|
| [System Design](01-system-design.md) | Request lifecycle, endpoints, persistence model, Redis cache strategy |
| [Code Design](02-code-design.md) | Module walkthrough from HTTP route to DB commit |
| [Folder Structure](03-folder-structure.md) | File tree with annotations for every module in `app/` |
