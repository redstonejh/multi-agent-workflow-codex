import pytest
from fastapi.testclient import TestClient

from todo_api import app, reset_state


@pytest.fixture()
def client():
    reset_state()
    with TestClient(app) as test_client:
        yield test_client
    reset_state()


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_todos_start_empty(client):
    response = client.get("/todos")

    assert response.status_code == 200
    assert response.json() == []


def test_create_todo_defaults_completed_false(client):
    response = client.post("/todos", json={"title": "write tests"})

    assert response.status_code == 201
    assert response.headers["location"] == "/todos/1"
    assert response.json() == {"id": 1, "title": "write tests", "completed": False}


def test_create_todo_accepts_completed(client):
    response = client.post("/todos", json={"title": "ship api", "completed": True})

    assert response.status_code == 201
    assert response.headers["location"] == "/todos/1"
    assert response.json() == {"id": 1, "title": "ship api", "completed": True}


def test_create_todo_strips_title(client):
    response = client.post("/todos", json={"title": "  trim me  "})

    assert response.status_code == 201
    assert response.json() == {"id": 1, "title": "trim me", "completed": False}


def test_list_todos_returns_created_items(client):
    client.post("/todos", json={"title": "first"})
    client.post("/todos", json={"title": "second", "completed": True})

    response = client.get("/todos")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "title": "first", "completed": False},
        {"id": 2, "title": "second", "completed": True},
    ]


def test_get_todo_returns_existing_item(client):
    created = client.post("/todos", json={"title": "find me"}).json()

    response = client.get(f"/todos/{created['id']}")

    assert response.status_code == 200
    assert response.json() == {"id": 1, "title": "find me", "completed": False}


def test_get_missing_todo_returns_404(client):
    response = client.get("/todos/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "todo not found"}


def test_delete_todo_removes_existing_item(client):
    created = client.post("/todos", json={"title": "temporary"}).json()

    response = client.delete(f"/todos/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/todos").json() == []


def test_delete_missing_todo_returns_404(client):
    response = client.delete("/todos/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "todo not found"}


def test_create_todo_rejects_empty_title(client):
    response = client.post("/todos", json={"title": ""})

    assert response.status_code == 422


def test_create_todo_rejects_whitespace_title(client):
    response = client.post("/todos", json={"title": "   "})

    assert response.status_code == 422
