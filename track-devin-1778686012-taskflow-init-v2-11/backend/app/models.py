"""Pydantic schemas for TaskFlow.

Tasks are stored as JSON documents in Azure Cosmos DB (NoSQL Core API), so
there are no ORM table classes here. The `Task` model is the canonical
in-memory representation; the repository layer is responsible for
serialising it to/from Cosmos documents.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["todo", "inprog", "done"]
Priority = Literal["high", "medium", "low"]
Tag = Literal["dev", "design", "qa", "pm"]

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_due_time(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not _TIME_RE.match(value):
        raise ValueError("due_time must be in HH:MM 24-hour format")
    return value


def _utcnow_naive() -> datetime:
    """Return a naive UTC datetime to keep created_at/updated_at JSON-friendly."""
    return datetime.now(UTC).replace(tzinfo=None)


def _new_id() -> str:
    return uuid.uuid4().hex


class Task(BaseModel):
    """Canonical Task document stored in Cosmos DB.

    Cosmos requires a string `id`. We also keep `proj` as the partition key,
    so the repository layer can route reads/writes efficiently.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=_new_id)
    title: str
    desc: str = ""
    status: Status = "todo"
    priority: Priority = "medium"
    tag: Tag = "dev"
    assignee: str = "YO"
    due: date | None = None
    due_time: str | None = None
    proj: str = "Website Redesign"
    created_at: datetime = Field(default_factory=_utcnow_naive)
    updated_at: datetime = Field(default_factory=_utcnow_naive)

    @field_validator("due_time", mode="before")
    @classmethod
    def _check_task_time(cls, value: str | None) -> str | None:
        return _validate_due_time(value)


class TaskCreate(BaseModel):
    """Payload schema for creating a task with strict literal validation."""

    title: str
    desc: str = ""
    status: Status = "todo"
    priority: Priority = "medium"
    tag: Tag = "dev"
    assignee: str = "YO"
    due: date | None = None
    due_time: str | None = None
    proj: str = "Website Redesign"

    @field_validator("due_time", mode="before")
    @classmethod
    def _check_create_time(cls, value: str | None) -> str | None:
        return _validate_due_time(value)


class TaskUpdate(BaseModel):
    title: str | None = None
    desc: str | None = None
    status: Status | None = None
    priority: Priority | None = None
    tag: Tag | None = None
    assignee: str | None = None
    due: date | None = None
    due_time: str | None = None
    proj: str | None = None

    @field_validator("due_time", mode="before")
    @classmethod
    def _check_update_time(cls, value: str | None) -> str | None:
        return _validate_due_time(value)


class TaskRead(BaseModel):
    id: str
    title: str
    desc: str
    status: Status
    priority: Priority
    tag: Tag
    assignee: str
    due: date | None
    due_time: str | None = None
    proj: str
    created_at: datetime
    updated_at: datetime
    # Populated when POST /api/tasks?add_to_outlook=true was successful.
    # Not stored in DB; only returned on the response.
    outlook_event_id: str | None = None


class Project(BaseModel):
    name: str
    slug: str
    color: str


class User(BaseModel):
    code: str
    name: str
    color: str
