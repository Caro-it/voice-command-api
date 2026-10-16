from fastapi import APIRouter, HTTPException, status

from src.app.schemas.voice import Task, TaskCreate, TaskReplace, TaskUpdate
from src.app.services import task_store

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[Task])
def get_tasks() -> list[Task]:
    return [Task(**task) for task in task_store.list_tasks()]


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate) -> Task:
    return Task(**task_store.create_task(payload.title, payload.done))


@router.put("/{task_id}", response_model=Task)
def replace_task(
    task_id: int,
    payload: TaskReplace,
) -> Task:
    try:
        return Task(**task_store.replace_task(task_id, payload.title, payload.done))
    except task_store.TaskNotFoundError as exc:
        raise_not_found(exc)


@router.patch("/{task_id}", response_model=Task)
def update_task(
    task_id: int,
    payload: TaskUpdate,
) -> Task:
    try:
        return Task(**task_store.update_task(task_id, payload.title, payload.done))
    except task_store.TaskNotFoundError as exc:
        raise_not_found(exc)


@router.delete("/{task_id}")
def delete_task(task_id: int) -> dict[str, str]:
    try:
        task_store.delete_task(task_id)
    except task_store.TaskNotFoundError as exc:
        raise_not_found(exc)
    return {"message": f"Task {task_id} deleted"}


def raise_not_found(exc: task_store.TaskNotFoundError) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=str(exc),
    ) from exc
