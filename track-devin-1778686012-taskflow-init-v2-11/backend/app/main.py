"""FastAPI application exposing TaskFlow REST API with per-user isolation."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.assistant import (
    AssistantError,
    AssistantRequest,
    AssistantResponse,
    interpret_command,
)
from app.auth import CurrentUser, get_current_user
from app.conflicts import check_conflict
from app.models import (
    Project,
    Task,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    User,
)
from app.repository import TaskRepository, get_repository
from app.seed import PROJECTS, USERS


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # No global seed — each user starts with an empty task list.
    # Repository is initialized on first use via get_repository().
    get_repository()
    yield


app = FastAPI(title="TaskFlow API", version="2.0.0", lifespan=lifespan)

_origins_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
_origins = [o.strip() for o in _origins_env.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_repo() -> TaskRepository:
    """FastAPI dependency that returns the singleton task repository."""
    return get_repository()


# ---------------------------------------------------------------------------
# Public endpoints (no auth required)
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/projects", response_model=list[Project])
def list_projects() -> list[Project]:
    return PROJECTS


@app.get("/api/users", response_model=list[User])
def list_users() -> list[User]:
    return USERS


# ---------------------------------------------------------------------------
# User info endpoint (returns who the token belongs to)
# ---------------------------------------------------------------------------


@app.get("/api/me")
async def get_me(user: CurrentUser = Depends(get_current_user)) -> dict[str, str]:
    """Return the authenticated user's info. Useful for the frontend to
    confirm the login succeeded and display the user's name/email."""
    return {
        "user_id": user.user_id,
        "display_name": user.display_name,
        "email": user.email,
    }


# ---------------------------------------------------------------------------
# Protected endpoints (require valid MS token → user isolation)
# ---------------------------------------------------------------------------


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(maxsplit=1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


def _resolve_timezone(name: str | None) -> tuple[ZoneInfo, str]:
    if name:
        try:
            return ZoneInfo(name), name
        except ZoneInfoNotFoundError:
            pass
    return ZoneInfo("UTC"), "UTC"


@app.get("/api/tasks", response_model=list[TaskRead])
async def list_tasks(
    repo: TaskRepository = Depends(get_repo),
    user: CurrentUser = Depends(get_current_user),
) -> list[Task]:
    return repo.list_tasks(user.user_id)


@app.post("/api/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    repo: TaskRepository = Depends(get_repo),
    user: CurrentUser = Depends(get_current_user),
    add_to_outlook: bool = False,
    tz: str | None = None,
    authorization: str | None = Header(default=None),
) -> TaskRead:
    """Create a task owned by the authenticated user."""
    from app.graph import create_calendar_event

    task = Task(**payload.model_dump(), user_id=user.user_id)
    repo.add_task(task)

    outlook_event_id: str | None = None
    if add_to_outlook and task.due is not None and task.due_time:
        token = _extract_bearer(authorization)
        if token:
            zone, zone_name = _resolve_timezone(tz)
            start = datetime.combine(
                task.due,
                datetime.strptime(task.due_time, "%H:%M").time(),
                tzinfo=zone,
            )
            end = start + timedelta(minutes=60)
            event = await create_calendar_event(
                token,
                subject=task.title,
                body=task.desc or "",
                start=start,
                end=end,
                time_zone=zone_name,
            )
            if event is not None:
                outlook_event_id = event.get("id")

    return TaskRead(**task.model_dump(), outlook_event_id=outlook_event_id)


@app.get("/api/tasks/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: str,
    repo: TaskRepository = Depends(get_repo),
    user: CurrentUser = Depends(get_current_user),
) -> Task:
    task = repo.get_task(task_id, user.user_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.patch("/api/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    repo: TaskRepository = Depends(get_repo),
    user: CurrentUser = Depends(get_current_user),
) -> Task:
    task = repo.get_task(task_id, user.user_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    data = payload.model_dump(exclude_unset=True)
    updated = task.model_copy(
        update={**data, "updated_at": datetime.now(UTC).replace(tzinfo=None)}
    )
    repo.update_task(updated)
    return updated


@app.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    repo: TaskRepository = Depends(get_repo),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    deleted = repo.delete_task(task_id, user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")


@app.post("/api/assistant", response_model=AssistantResponse)
async def assistant(
    request: AssistantRequest,
    repo: TaskRepository = Depends(get_repo),
    user: CurrentUser = Depends(get_current_user),
    authorization: str | None = Header(default=None),
) -> AssistantResponse:
    """Parse a free-form voice/text command into a structured task suggestion."""
    zone, _zone_name = _resolve_timezone(request.tz)
    today = datetime.now(zone).date()
    try:
        response = await interpret_command(request, today=today)
    except AssistantError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    response.conflict = await check_conflict(
        repo,
        user.user_id,
        response.task.due,
        response.task.due_time,
        access_token=_extract_bearer(authorization),
    )
    return response
