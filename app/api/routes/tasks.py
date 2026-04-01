"""Task endpoints — delegate to TaskService only."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_task_service
from app.middleware.auth import verify_api_key
from app.schemas.task import TaskRequest, TaskResponse
from app.services.task_service import TaskService

router = APIRouter(tags=["tasks"])


@router.post(
    "/task",
    response_model=TaskResponse,
    dependencies=[Depends(verify_api_key)],
)
async def create_task(
    body: TaskRequest,
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    return await service.create_and_run_task(body.task)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_task(
    task_id: UUID,
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    task = await service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return service.to_response(task)
