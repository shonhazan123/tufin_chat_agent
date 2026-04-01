# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A **Multi-Tool Agent REST API** that accepts natural language tasks, plans and executes them step-by-step via LLM + tools, and returns a final answer with a full structured trace. All activity is persisted to a queryable database.

## Stack
- Python 3.11, FastAPI, LangGraph
- SQLite + SQLAlchemy
- Docker + docker-compose

## Commands
- `uvicorn app.main:app --reload` — start dev server
- **Debug:** Run and Debug → `API + agent (uvicorn, debug)` (starts Redis via `preLaunchTask`, then uvicorn; see `docs/project-instruction/local-debug.md`); UI separately: `npm run dev` in `chat-ui/`
- `pytest tests/` — run test suite
- `docker compose up` — full service

## API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/task` | Submit a task → returns `task_id`, final answer, and trace |
| GET | `/tasks/{task_id}` | Retrieve past task result and trace |
| GET | `/health` | Health check |

## Agent Tools
Implement at least 3 as real functions (not mocks):
- `calculator` — planner supplies `params.expression`; tool LLM only on missing/wrong args or eval failure (`executor.max_tool_attempts`)
- `weather` — fetch current weather for a city
- `web_search` — search the web and return a summary
- `unit_converter` — convert between length, weight, temperature, currency
- `database_query` *(bonus)* — query a pre-seeded SQLite DB (products + orders tables)

## Observability Requirements
- Persist all task results and traces to the database
- Log latency and token usage per task
- Every reasoning step, tool call, and result must be structured and stored

## Architecture
- `app/agent/` — LangGraph graph, nodes, tools
- `app/api/` — FastAPI routes
- `app/db/` — SQLAlchemy models + persistence

## LLM provider (env, not YAML keys)

- Set **`LLM_PROVIDER`** in `.env` to `openai` (default) or `ollama`. The loader merges `config/shared.yaml` with `config/openai.yaml` or `config/ollama.yaml` (see `agent/yaml_config.py`). There is no `LLM_PROVIDER` key inside the YAML files.

## Conventions
- Type hints on all functions
- Async throughout (FastAPI + LangGraph)
- Tests in `tests/` mirroring `app/` structure
- LLM config and API keys via `.env` file only — service must run with no modifications beyond setting keys there

## Bonus Features (optional)
- Local model support via Ollama / vLLM / HuggingFace (no external API key needed)
- Multi-turn support: pass conversation context for follow-up questions referencing a prior task
- Evaluation: ≥5 automated test assertions on known tasks
- Simple frontend (any framework or plain HTML) to submit tasks and view traces

## Constraints
- Do not expose raw tool output as the final answer — always include an LLM reasoning step
- Service must be fully runnable via Docker
- README.md must include: architecture overview, setup/run instructions, reasoning loop design, and ≥5 example tasks with expected outputs and traces
