# System Design — LangGraph Agent

[← Component README](README.md) · [Code Design →](02-code-design.md)

---

## What Kind of Agent

This is a **plan-and-execute** agent, not a ReAct loop.

The three roles never overlap:

| Role | Job | Output |
|------|-----|--------|
| **Planner** | Decides which tools to run, in what order, with what parameters | JSON task plan |
| **Executor** | Runs tools in parallel waves, respects dependencies | Structured results + trace |
| **Responder** | Synthesizes a human-readable answer from tool outputs | Final text answer |

The planner never speaks to the user. The responder never calls tools. The executor never reasons.

---

## Execution Graph

```mermaid
flowchart TD
    START([START]) --> planner_node

    planner_node["planner_node — LLM produces JSON task plan"]

    planner_node --> executor_node

    executor_node["executor_node — runs ready tasks in parallel"]

    executor_node --> router{route_after_executor}

    router -->|"tasks remain"| executor_node
    router -->|"error"| mark_failure["mark_failure_node"]
    router -->|"done"| prepare["prepare_responder_context_node — label FINAL vs INTERMEDIATE"]

    mark_failure --> prepare
    prepare --> response_node["response_node — LLM synthesizes final answer"]
    response_node --> END([END])
```

> The `prepare_responder_context_node` labels each tool result as **FINAL ANSWER** (no downstream task depends on it) or **INTERMEDIATE** (fed data into another tool). The responder uses these labels to know which numbers to present vs. which to treat as background context.

---

## Fan-Out / Fan-In Wave Architecture

The planner emits a dependency-aware task list using `depends_on` arrays, forming a DAG.

```mermaid
flowchart TD
    Plan["Planner Output — tasks: t1, t2, t3, t4"]

    subgraph Wave1 ["Wave 1 — parallel"]
        t1["t1: weather"]
        t2["t2: web_search"]
    end

    subgraph Wave2 ["Wave 2 — parallel"]
        t3["t3: unit_converter — depends on t1"]
    end

    subgraph Wave3 ["Wave 3"]
        t4["t4: calculator — depends on t2 and t3"]
    end

    Plan --> t1
    Plan --> t2
    t1 --> t3
    t2 --> t4
    t3 --> t4
```

**Fan-out** — every task whose `depends_on` list is fully satisfied runs concurrently via `asyncio.gather`.  
**Fan-in** — results merge back into shared graph state, unlocking the next wave.

Independent tools never wait for each other. Dependent tools always receive their upstream data before running.

---

## Plugin / Factory Tool System

Tools are registered automatically at startup — the planner prompt is generated from whatever is in the registry.

```mermaid
flowchart LR
    subgraph tools ["agent/tools/"]
        W["weather.py"]
        S["web_search.py"]
        C["calculator.py"]
        D["database_query.py"]
    end

    decorator["@registry.register(ToolSpec)"]

    W & S & C & D --> decorator
    decorator --> Registry["AgentRegistry singleton"]
    Registry --> Prompt["build_planner_prompt()"]
    Prompt --> LLM["Planner LLM — knows all tools"]
```

Adding a new tool requires only creating a `.py` file in `agent/tools/` with the decorator — nothing else changes.

Tools can be enabled or disabled via `config/shared.yaml`:

```yaml
tools:
  weather:
    enabled: true
  my_new_tool:
    enabled: false   # skipped during discovery
```

---

## Externalized Provider Configuration

The provider is selected at process start from `.env` and never changes at runtime.

```mermaid
flowchart TD
    env[".env — LLM_PROVIDER=openai or ollama"]

    subgraph yaml ["config/"]
        shared["shared.yaml — tools, executor, cache"]
        openai["openai.yaml — models, api_key"]
        ollama["ollama.yaml — models, num_ctx per agent"]
    end

    env -->|selects| openai
    env -->|or selects| ollama
    shared --> merge["config_loader.py — deep-merge"]
    openai --> merge
    ollama --> merge

    merge --> factory["llm_provider_factory.py — build_llm() — one instance per role, cached"]
```

Each agent role (planner, responder, every tool) can use a **different model**, configured entirely in YAML.
