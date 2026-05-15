"""FastAPI application exposing TaskFlow REST API."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from app.assistant import (
    AssistantError,
    AssistantRequest,
    AssistantResponse,
    interpret_command,
)
from app.conflicts import check_conflict
from app.db import engine, get_session, init_db
from app.graph import create_calendar_event
from app.models import (
    Project,
    Task,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    User,
)
from app.seed import PROJECTS, USERS, build_seed_tasks


def seed_if_empty() -> None:
    with Session(engine) as session:
        existing = session.exec(select(Task)).first()
        if existing is not None:
            return
        for task in build_seed_tasks():
            session.add(task)
        session.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_if_empty()
    yield


app = FastAPI(title="TaskFlow API", version="1.0.0", lifespan=lifespan)

# CORS_ALLOW_ORIGINS is a comma-separated list of origins. Defaults to "*"
# for local dev; production should set it to the Static Web App's URL.
_origins_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
_origins = [o.strip() for o in _origins_env.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/projects", response_model=list[Project])
def list_projects() -> list[Project]:
    return PROJECTS


@app.get("/api/users", response_model=list[User])
def list_users() -> list[User]:
    return USERS


@app.get("/api/tasks", response_model=list[TaskRead])
def list_tasks(session: Session = Depends(get_session)) -> list[Task]:
    return list(session.exec(select(Task).order_by(Task.id)).all())


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(maxsplit=1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


def _resolve_timezone(name: str | None) -> tuple[ZoneInfo, str]:
    """Return a ZoneInfo and its canonical IANA name for Graph requests.

    Microsoft Graph accepts IANA names like ``Europe/Moscow``. If the caller
    omits it or supplies something unparseable, we fall back to UTC so we
    never crash the create flow over a bad ``tz`` query string.
    """
    if name:
        try:
            return ZoneInfo(name), name
        except ZoneInfoNotFoundError:
            pass
    return ZoneInfo("UTC"), "UTC"


@app.post("/api/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    session: Session = Depends(get_session),
    add_to_outlook: bool = False,
    tz: str | None = None,
    authorization: str | None = Header(default=None),
) -> TaskRead:
    """Create a task; optionally mirror it as an Outlook event if a token is supplied.

    `add_to_outlook=true` query parameter combined with a `Authorization:
    Bearer <graph-token>` header makes the backend create a 1-hour event on
    the caller's Outlook calendar (subject = task title, body = task desc).
    The optional `tz` query parameter is an IANA timezone (e.g.
    ``Europe/Moscow``) so the time the user typed is interpreted in their
    local zone rather than as UTC — without this the event would show up
    several hours off in Outlook. Calendar creation is best-effort:
    failures are swallowed so the task itself is still saved. On success the
    response's `outlook_event_id` field carries Graph's event ID so the UI
    can confirm the sync happened.
    """
    task = Task(**payload.model_dump())
    session.add(task)
    session.commit()
    session.refresh(task)

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
def get_task(task_id: int, session: Session = Depends(get_session)) -> Task:
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.patch("/api/tasks/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int, payload: TaskUpdate, session: Session = Depends(get_session)
) -> Task:
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(task, key, value)
    task.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


@app.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, session: Session = Depends(get_session)) -> None:
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    session.delete(task)
    session.commit()


@app.post("/api/assistant", response_model=AssistantResponse)
async def assistant(
    request: AssistantRequest,
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> AssistantResponse:
    """Parse a free-form voice/text command into a structured task suggestion.

    After Gemini returns a candidate task, we look in TaskFlow's DB *and* (if
    a Microsoft Graph access token is forwarded via the Authorization header)
    in the caller's Outlook calendar for tasks/events occupying the same slot.
    The conflict block returned to the frontend lists every offender and a
    few free alternatives.
    """
    zone, _zone_name = _resolve_timezone(request.tz)
    today = datetime.now(zone).date()
    try:
        response = await interpret_command(request, today=today)
    except AssistantError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    response.conflict = await check_conflict(
        session,
        response.task.due,
        response.task.due_time,
        access_token=_extract_bearer(authorization),
    )
    return response
