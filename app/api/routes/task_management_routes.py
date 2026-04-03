"""HTTP routes for submitting tasks and reading persisted traces (API key when configured)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_task_orchestration_service
from app.middleware.auth import verify_api_key
from app.schemas.task_schemas import (
    TaskDebugResponse,
    TaskDetailResponse,
    TaskRequest,
    TaskSubmitResponse,
)
from app.services.task_orchestration_service import TaskOrchestrationService

router = APIRouter(tags=["tasks"])


@router.post(
    "/task",
    response_model=TaskSubmitResponse,
    dependencies=[Depends(verify_api_key)],
)
async def submit_task_and_run_agent(
    request_body: TaskRequest,
    task_orchestration_service: TaskOrchestrationService = Depends(
        get_task_orchestration_service,
    ),
) -> TaskSubmitResponse:
    """Enqueue a user task, run the agent (or Redis cache hit), return the final answer."""
    return await task_orchestration_service.create_and_run_task(request_body.task)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskDetailResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_task_detail_by_id(
    task_id: UUID,
    task_orchestration_service: TaskOrchestrationService = Depends(
        get_task_orchestration_service,
    ),
) -> TaskDetailResponse:
    """Load one task row including observability_json for the Chat UI trace view."""
    task_row = await task_orchestration_service.get_task(task_id)
    if task_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    return task_orchestration_service.to_detail_response(task_row)


@router.get(
    "/tasks/{task_id}/debug",
    response_model=TaskDebugResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_task_debug_by_id(
    task_id: UUID,
    task_orchestration_service: TaskOrchestrationService = Depends(
        get_task_orchestration_service,
    ),
) -> TaskDebugResponse:
    """Full metadata plus reasoning_tree for the expandable debug sidebar."""
    task_row = await task_orchestration_service.get_task(task_id)
    if task_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    return task_orchestration_service.to_debug_response(task_row)
