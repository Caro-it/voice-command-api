"""Executes an already-routed instruction against the task store.

This does not detect intent: it only dispatches the method + endpoint the LLM
chose to the matching task_store operation.
"""

from typing import Any, TypeVar

from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError

from src.app.schemas.voice import InstructionPayload, TaskCreate, TaskReplace, TaskUpdate
from src.app.services import task_store

M = TypeVar("M", bound=BaseModel)


def _parse_params(model: type[M], params: dict[str, Any]) -> M:
    try:
        return model.model_validate(params)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid params for the routed instruction.", "errors": exc.errors(include_url=False, include_context=False)},
        ) from exc


def _task_id(endpoint: str) -> int | None:
    parts = endpoint.strip("/").split("/")
    return int(parts[1]) if len(parts) == 2 else None


def execute_instruction(instruction: InstructionPayload) -> Any:
    method = instruction.method.upper()
    task_id = _task_id(instruction.endpoint)
    params = instruction.params

    try:
        if method == "GET" and task_id is None:
            return task_store.list_tasks()
        if method == "POST" and task_id is None:
            body = _parse_params(TaskCreate, params)
            return task_store.create_task(body.title, body.done)
        if method == "PUT" and task_id is not None:
            body = _parse_params(TaskReplace, params)
            return task_store.replace_task(task_id, body.title, body.done)
        if method == "PATCH" and task_id is not None:
            body = _parse_params(TaskUpdate, params)
            if body.title is None and body.done is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="PATCH requires at least one of 'title' or 'done'.",
                )
            return task_store.update_task(task_id, body.title, body.done)
        if method == "DELETE" and task_id is not None:
            task_store.delete_task(task_id)
            return {"message": f"Task {task_id} deleted"}
    except task_store.TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unsupported instruction: {method} {instruction.endpoint}",
    )
