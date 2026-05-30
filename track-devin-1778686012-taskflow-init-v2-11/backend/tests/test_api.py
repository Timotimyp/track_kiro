"""Smoke tests for the TaskFlow REST API."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch) -> Iterator[TestClient]:
    """Spin up the API against a fresh in-memory task repository.

    Cosmos DB env vars are explicitly cleared so `get_repository()` falls
    back to `InMemoryTaskRepository`. The previous singleton is reset so
    each test starts with an empty store before the seed runs.
    """
    for var in ("COSMOS_ENDPOINT", "COSMOS_KEY", "COSMOS_USE_AAD"):
        monkeypatch.delenv(var, raising=False)

    from app import main as main_module
    from app import repository as repository_module

    repository_module.reset_repository(repository_module.InMemoryTaskRepository())

    with TestClient(main_module.app) as test_client:
        yield test_client

    repository_module.reset_repository(None)


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_projects_and_users(client: TestClient) -> None:
    projects = client.get("/api/projects").json()
    users = client.get("/api/users").json()
    assert len(projects) == 4
    assert {p["name"] for p in projects} == {
        "Website Redesign",
        "Backend API",
        "Mobile App",
        "Operations",
    }
    assert {u["code"] for u in users} >= {"AK", "BL", "CJ", "DM", "YO"}


def test_tasks_seeded(client: TestClient) -> None:
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 8
    # IDs are now strings (Cosmos requirement); verify shape.
    assert all(isinstance(t["id"], str) and t["id"] for t in tasks)


def test_create_update_delete_task(client: TestClient) -> None:
    payload = {
        "title": "Test task",
        "desc": "Some description",
        "status": "todo",
        "priority": "medium",
        "tag": "dev",
        "assignee": "YO",
        "due": "2026-06-01",
        "due_time": "15:30",
        "proj": "Website Redesign",
    }
    created = client.post("/api/tasks", json=payload).json()
    assert created["title"] == "Test task"
    assert created["due_time"] == "15:30"
    task_id = created["id"]
    assert isinstance(task_id, str) and task_id

    updated = client.patch(
        f"/api/tasks/{task_id}", json={"status": "done", "due_time": "09:00"}
    ).json()
    assert updated["status"] == "done"
    assert updated["due_time"] == "09:00"

    bad = client.post(
        "/api/tasks", json={**payload, "due_time": "25:99"}
    )
    assert bad.status_code == 422

    response = client.delete(f"/api/tasks/{task_id}")
    assert response.status_code == 204

    response = client.get(f"/api/tasks/{task_id}")
    assert response.status_code == 404


def test_assistant_endpoint_returns_structured_task(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The /api/assistant endpoint should return what the LLM returned, validated."""
    import app.main as main_module
    from app.assistant import AssistantResponse, AssistantTask

    async def fake_interpret(request, *, today, **kwargs):  # noqa: ANN001
        assert request.text.strip() != ""
        assert isinstance(today, date)
        return AssistantResponse(
            recommendation="Looks like a backend bug \u2014 assigning to BL with high priority.",
            task=AssistantTask(
                title="Fix payment timeout bug",
                desc="Investigate 504s on checkout",
                status="todo",
                priority="high",
                tag="dev",
                assignee="BL",
                due=None,
                due_time="15:00",
                proj="Backend API",
            ),
        )

    monkeypatch.setattr(main_module, "interpret_command", fake_interpret)

    response = client.post(
        "/api/assistant",
        json={"text": "\u041f\u043e\u0447\u0438\u043d\u0438 \u043b\u0430\u0433 \u043d\u0430 \u0447\u0435\u043a\u0430\u0443\u0442\u0435, \u0441\u0440\u043e\u0447\u043d\u043e", "language": "ru-RU"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task"]["assignee"] == "BL"
    assert body["task"]["priority"] == "high"
    assert body["task"]["proj"] == "Backend API"
    assert body["task"]["due_time"] == "15:00"
    assert "recommendation" in body and len(body["recommendation"]) > 0


def test_assistant_endpoint_propagates_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.main as main_module
    from app.assistant import AssistantError

    async def boom(request, *, today, **kwargs):  # noqa: ANN001
        raise AssistantError("GEMINI_API_KEY is not configured on the server.")

    monkeypatch.setattr(main_module, "interpret_command", boom)

    response = client.post("/api/assistant", json={"text": "hello", "language": "en-US"})
    assert response.status_code == 502
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_assistant_detects_conflict_and_proposes_alternatives(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When Gemini's suggested slot is occupied, the response includes a conflict block."""
    import app.main as main_module
    from app.assistant import AssistantResponse, AssistantTask

    occupying = client.post(
        "/api/tasks",
        json={
            "title": "Sprint planning",
            "due": "2026-06-01",
            "due_time": "15:00",
            "proj": "Operations",
        },
    ).json()
    assert occupying["due_time"] == "15:00"

    async def fake_interpret(request, *, today, **kwargs):  # noqa: ANN001
        return AssistantResponse(
            recommendation="Suggest scheduling at the requested time.",
            task=AssistantTask(
                title="1:1 with Beth",
                priority="medium",
                tag="pm",
                assignee="BL",
                due=date(2026, 6, 1),
                due_time="15:00",
                proj="Backend API",
            ),
        )

    monkeypatch.setattr(main_module, "interpret_command", fake_interpret)
    body = client.post(
        "/api/assistant",
        json={"text": "Set up 1:1 with Beth on June 1 at 3pm", "language": "en-US"},
    ).json()

    conflict = body["conflict"]
    assert conflict is not None
    assert len(conflict["conflicts"]) == 1
    assert conflict["conflicts"][0]["title"] == "Sprint planning"
    assert conflict["conflicts"][0]["due_time"] == "15:00"
    assert conflict["conflicts"][0]["source"] == "taskflow"
    assert conflict["conflicts"][0]["id"].startswith("taskflow:")
    assert len(conflict["alternatives"]) == 3
    # Same-day shifts come first when free
    alt_keys = [(a["due"], a["due_time"]) for a in conflict["alternatives"]]
    assert ("2026-06-01", "16:00") in alt_keys
    assert ("2026-06-01", "14:00") in alt_keys


def test_assistant_merges_outlook_calendar_conflicts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When an Authorization header is passed, Outlook events also count as conflicts."""
    import app.conflicts as conflicts_module
    import app.main as main_module
    from app.assistant import AssistantResponse, AssistantTask
    from app.graph import GraphEvent

    async def fake_interpret(request, *, today, **kwargs):  # noqa: ANN001
        return AssistantResponse(
            recommendation="Slot looks available.",
            task=AssistantTask(
                title="Pair on auth",
                priority="medium",
                tag="dev",
                assignee="YO",
                due=date(2026, 7, 10),
                due_time="14:00",
                proj="Backend API",
            ),
        )

    async def fake_calendar_view(token, start, end):  # noqa: ANN001
        assert token == "graph-token-xyz"
        return [
            GraphEvent(
                id="AAMkAGI2T...",
                subject="Stakeholder review",
                start=datetime(2026, 7, 10, 13, 30, tzinfo=UTC),
                end=datetime(2026, 7, 10, 14, 30, tzinfo=UTC),
            ),
            GraphEvent(
                id="AAMkAGI3T...",
                subject="Lunch",
                start=datetime(2026, 7, 10, 16, 0, tzinfo=UTC),
                end=datetime(2026, 7, 10, 17, 0, tzinfo=UTC),
            ),
        ]

    monkeypatch.setattr(main_module, "interpret_command", fake_interpret)
    monkeypatch.setattr(conflicts_module, "fetch_calendar_view", fake_calendar_view)

    body = client.post(
        "/api/assistant",
        json={"text": "schedule pair programming", "language": "en-US"},
        headers={"Authorization": "Bearer graph-token-xyz"},
    ).json()

    conflict = body["conflict"]
    assert conflict is not None
    # The overlapping Outlook event ("Stakeholder review" 13:30-14:30) clashes.
    titles = [c["title"] for c in conflict["conflicts"]]
    assert "Stakeholder review" in titles
    sources = {c["source"] for c in conflict["conflicts"]}
    assert "outlook" in sources
    # 16:00 is occupied by Lunch — must NOT be returned as alternative.
    alt_keys = [(a["due"], a["due_time"]) for a in conflict["alternatives"]]
    assert ("2026-07-10", "16:00") not in alt_keys
    # 15:00 should be free though.
    assert ("2026-07-10", "15:00") in alt_keys


def test_assistant_no_conflict_when_slot_is_free(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty slot should produce conflict=None."""
    import app.main as main_module
    from app.assistant import AssistantResponse, AssistantTask

    async def fake_interpret(request, *, today, **kwargs):  # noqa: ANN001
        return AssistantResponse(
            recommendation="No conflicts expected.",
            task=AssistantTask(
                title="Solo task",
                priority="low",
                tag="dev",
                assignee="YO",
                due=date(2030, 1, 1),
                due_time="10:00",
                proj="Backend API",
            ),
        )

    monkeypatch.setattr(main_module, "interpret_command", fake_interpret)
    body = client.post(
        "/api/assistant",
        json={"text": "schedule something in the far future", "language": "en-US"},
    ).json()
    assert body["conflict"] is None
