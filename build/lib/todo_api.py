"""Small in-memory FastAPI todo service."""
from __future__ import annotations

from itertools import count
from threading import Lock
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Response, status
from pydantic import BaseModel, Field, field_validator


app = FastAPI(title="Todo API")

_todos: dict[int, dict[str, int | str | bool]] = {}
_ids = count(1)
_lock = Lock()


class TodoCreate(BaseModel):
    title: Annotated[str, Field(min_length=1)]
    completed: bool = False

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank")
        return normalized


class Todo(TodoCreate):
    id: int


def reset_state() -> None:
    """Clear in-memory state for tests."""
    global _ids
    with _lock:
        _todos.clear()
        _ids = count(1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/todos", response_model=list[Todo])
def list_todos() -> list[dict[str, int | str | bool]]:
    with _lock:
        return [_todos[todo_id].copy() for todo_id in sorted(_todos)]


@app.post("/todos", response_model=Todo, status_code=status.HTTP_201_CREATED)
def create_todo(todo: TodoCreate, response: Response) -> dict[str, int | str | bool]:
    with _lock:
        todo_id = next(_ids)
        record = {"id": todo_id, "title": todo.title, "completed": todo.completed}
        _todos[todo_id] = record
    response.headers["Location"] = f"/todos/{todo_id}"
    return record


@app.get("/todos/{todo_id}", response_model=Todo)
def get_todo(todo_id: Annotated[int, Path(gt=0)]) -> dict[str, int | str | bool]:
    with _lock:
        todo = _todos.get(todo_id)
        if todo is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="todo not found")
        return todo.copy()


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(todo_id: Annotated[int, Path(gt=0)]) -> None:
    with _lock:
        if todo_id not in _todos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="todo not found")
        del _todos[todo_id]
