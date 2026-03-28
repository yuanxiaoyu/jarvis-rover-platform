from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.models.task import Task, TaskCreate, TaskStatusPatch
from app.state import TASK_STATE

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[Task])
def list_tasks() -> list[Task]:
    return TASK_STATE


@router.post("", response_model=Task)
def create_task(task_req: TaskCreate) -> Task:
    now = datetime.now(timezone.utc)
    task = Task(
        task_id=f"task-{uuid4().hex[:8]}",
        type=task_req.type,
        target=task_req.target,
        description=task_req.description,
        created_at=now,
        updated_at=now,
    )
    TASK_STATE.append(task)
    return task


@router.patch("/{task_id}", response_model=Task)
def patch_task(task_id: str, patch: TaskStatusPatch) -> Task:
    for task in TASK_STATE:
        if task.task_id == task_id:
            task.status = patch.status
            task.updated_at = datetime.now(timezone.utc)
            return task
    raise HTTPException(status_code=404, detail="task not found")

