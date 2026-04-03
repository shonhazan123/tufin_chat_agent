"""HTTP routes for service health and model warmup status (no API key)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas.health_check_schemas import HealthResponse, ModelStatusResponse
from app.services.health_check_service import HealthCheckService

router = APIRouter(tags=["health"])

_health_check_service = HealthCheckService()


@router.get("/health", response_model=HealthResponse)
async def get_service_health(http_request: Request) -> HealthResponse:
    """SQLite, Redis, LangGraph, and merged agent config snapshot."""
    return await _health_check_service.build_health_response(http_request)


@router.get("/health/model", response_model=ModelStatusResponse)
async def get_model_warmup_status() -> ModelStatusResponse:
    """Model lifecycle status for the chat UI to poll (download / warm / ready / error / skipped)."""
    return _health_check_service.build_model_warmup_status_response()
