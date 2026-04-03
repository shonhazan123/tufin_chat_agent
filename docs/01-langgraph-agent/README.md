# 01 · LangGraph Agent

[← Back to DOCS](../README.md)

---

This component is the **brain** of the system. It receives a natural language task, decides which tools to run and in what order, executes them in parallel waves, and synthesizes a final human-readable answer.

The design is a **plan-and-execute** architecture (not ReAct) built on top of LangGraph's `StateGraph`.

**Tool calls in the graph** are structured so execution starts with **deterministic, pure-function** work whenever the planner (or prior tool outputs) already supplies usable parameters. When something is missing, ambiguous, or must be inferred from context, the tool layer **falls back to an LLM** (the parameter specialist) to extract or shape inputs. That pattern speeds up the happy path, cuts token cost on straightforward steps, and reserves model calls for cases that actually need them.

---

## Pages

| Page | What it covers |
|------|---------------|
| [System Design](01-system-design.md) | Execution graph topology, fan-out/fan-in waves, plugin tool system, provider configuration |
| [Code Design](02-code-design.md) | Startup sequence, node internals, tool base classes, observability chain |
| [Folder Structure](03-folder-structure.md) | File tree with annotations for every module in `agent/` |
