"""In-memory task storage. No database, no files: state lives in this module."""

from itertools import count
from threading import Lock
from typing import Any

tasks: list[dict[str, Any]] = []

# Monotonic id generator: a deleted id is never reused.
_id_counter = count(start=1)
_lock = Lock()


class TaskNotFoundError(Exception):
    def __init__(self, task_id: int) -> None:
        super().__init__(f"Task {task_id} not found")
        self.task_id = task_id


def _find(task_id: int) -> dict[str, Any]:
    for task in tasks:
        if task["id"] == task_id:
            return task
    raise TaskNotFoundError(task_id)


def list_tasks() -> list[dict[str, Any]]:
    with _lock:
        return [dict(task) for task in tasks]


def create_task(title: str, done: bool = False) -> dict[str, Any]:
    with _lock:
        task = {"id": next(_id_counter), "title": title, "done": done}
        tasks.append(task)
        return dict(task)


def replace_task(task_id: int, title: str, done: bool) -> dict[str, Any]:
    with _lock:
        task = _find(task_id)
        task["title"] = title
        task["done"] = done
        return dict(task)


def update_task(
    task_id: int, title: str | None = None, done: bool | None = None
) -> dict[str, Any]:
    with _lock:
        task = _find(task_id)
        if title is not None:
            task["title"] = title
        if done is not None:
            task["done"] = done
        return dict(task)


def delete_task(task_id: int) -> None:
    with _lock:
        tasks.remove(_find(task_id))
