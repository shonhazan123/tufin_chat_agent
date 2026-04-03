"""Aggregates SQLite, Redis, and agent graph probes for GET /health and model warmup polling."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy import text

from app.cache.redis_cache import RedisCache
from app.db.session import get_session_factory
from app.schemas.health_check_schemas import HealthResponse, ModelStatusResponse
from app.settings import Settings, get_settings
from app.types.health_status_types import (
    ComponentHealthStatus,
    ModelWarmupStatus,
    OverallHealthStatus,
)
from app.warmup.status import model_state


class HealthCheckService:
    """Builds health DTOs; keeps route handlers as thin HTTP adapters."""

    async def build_health_response(self, http_request: Request) -> HealthResponse:
        """Run all probes and return a single summary for GET /health."""
        application_settings = get_settings()

        sqlite_health_status = await self._probe_sqlite(application_settings)
        redis_health_status = await self._probe_redis(http_request, application_settings)
        agent_health_status, llm_provider_name, model_name_by_agent_role = self._probe_agent_stack()

        overall_health_status = self._combine_overall_status(
            sqlite_health_status=sqlite_health_status,
            agent_health_status=agent_health_status,
            redis_health_status=redis_health_status,
            application_settings=application_settings,
        )

        return HealthResponse(
            status=overall_health_status,
            sqlite=sqlite_health_status,
            redis=redis_health_status,
            agent=agent_health_status,
            provider=llm_provider_name,
            models=model_name_by_agent_role,
        )

    def build_model_warmup_status_response(self) -> ModelStatusResponse:
        """Map the shared singleton model_state into the API response for GET /health/model."""
        warmup_status_snapshot = model_state.snapshot()
        return ModelStatusResponse(
            status=ModelWarmupStatus(warmup_status_snapshot["status"]),
            detail=warmup_status_snapshot["detail"],
        )

    async def _probe_sqlite(self, application_settings: Settings) -> ComponentHealthStatus:
        try:
            database_session_factory = get_session_factory(application_settings.database_url)
            async with database_session_factory() as database_session:
                await database_session.execute(text("SELECT 1"))
            return ComponentHealthStatus.OK
        except Exception:
            return ComponentHealthStatus.ERROR

    async def _probe_redis(
        self,
        http_request: Request,
        application_settings: Settings,
    ) -> ComponentHealthStatus:
        if not application_settings.redis_url:
            return ComponentHealthStatus.SKIPPED
        redis_cache: RedisCache = http_request.app.state.redis_cache
        if await redis_cache.ping():
            return ComponentHealthStatus.OK
        return ComponentHealthStatus.ERROR

    def _probe_agent_stack(
        self,
    ) -> tuple[ComponentHealthStatus, str | None, dict[str, str] | None]:
        """Verify LangGraph compiles and load merged YAML for provider + model map."""
        try:
            from agent.config_loader import load_config
            from agent.graph import get_graph

            get_graph()
            agent_configuration = load_config()
            raw_provider = agent_configuration.get("provider")
            llm_provider_name = str(raw_provider) if raw_provider is not None else None
            agents_configuration = agent_configuration.get("agents") or {}
            model_name_by_agent_role: dict[str, str] = {}
            for agent_role_name, agent_config_entry in agents_configuration.items():
                model_name = agent_config_entry.get("model")
                if model_name is not None:
                    model_name_by_agent_role[agent_role_name] = str(model_name)
            return ComponentHealthStatus.OK, llm_provider_name, model_name_by_agent_role
        except Exception:
            return ComponentHealthStatus.ERROR, None, None

    def _combine_overall_status(
        self,
        *,
        sqlite_health_status: ComponentHealthStatus,
        agent_health_status: ComponentHealthStatus,
        redis_health_status: ComponentHealthStatus,
        application_settings: Settings,
    ) -> OverallHealthStatus:
        if sqlite_health_status != ComponentHealthStatus.OK:
            return OverallHealthStatus.DEGRADED
        if agent_health_status != ComponentHealthStatus.OK:
            return OverallHealthStatus.DEGRADED
        if (
            redis_health_status == ComponentHealthStatus.ERROR
            and application_settings.redis_url
        ):
            return OverallHealthStatus.DEGRADED
        return OverallHealthStatus.OK
