"""API integration tests — in-memory SQLite, mocked agent startup and runner."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from app.settings import get_settings
from app.db.session import dispose_engine
from app.integrations.agent_runner import AgentRunResult


@pytest.fixture(autouse=True)
def _api_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.delenv("API_KEY", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr("agent.startup_initialization.startup", AsyncMock())


@pytest.fixture
def client() -> TestClient:
    asyncio.run(dispose_engine())
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    asyncio.run(dispose_engine())
    get_settings.cache_clear()


def test_health_ok(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["sqlite"] == "ok"
    assert data["redis"] == "skipped"


def test_post_task_returns_task_id_and_metrics(client: TestClient) -> None:
    async def fake_run(_task: str) -> AgentRunResult:
        return AgentRunResult(
            final_answer="hello",
            trace=[],
            observability={"version": 1, "executor_trace": []},
            latency_ms=12,
            total_input_tokens=3,
            total_output_tokens=4,
        )

    with patch("app.services.task_orchestration_service.run_agent_task", fake_run):
        r = client.post("/api/v1/task", json={"task": "ping"})
    assert r.status_code == 200
    data = r.json()
    assert "task_id" in data
    assert data["final_answer"] == "hello"
    assert "trace" not in data
    assert data["latency_ms"] == 12
    assert data["total_input_tokens"] == 3
    assert data["total_output_tokens"] == 4


def test_get_task_roundtrip(client: TestClient) -> None:
    obs = {"version": 1, "executor_trace": [{"task_id": "x"}]}

    async def fake_run(_task: str) -> AgentRunResult:
        return AgentRunResult(
            final_answer="round",
            trace=[{"task_id": "x"}],
            observability=obs,
            latency_ms=99,
            total_input_tokens=1,
            total_output_tokens=2,
        )

    with patch("app.services.task_orchestration_service.run_agent_task", fake_run):
        post = client.post("/api/v1/task", json={"task": "x"})
    assert post.status_code == 200
    tid = post.json()["task_id"]
    get = client.get(f"/api/v1/tasks/{tid}")
    assert get.status_code == 200
    body = get.json()
    assert body["final_answer"] == "round"
    assert body["observability"] == obs
    assert body["latency_ms"] == 99


def test_get_task_404(client: TestClient) -> None:
    r = client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000001")
    assert r.status_code == 404
