"""SQLModel table and Pydantic schemas for TaskFlow."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, field_validator
from sqlmodel import Field, SQLModel

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


class Task(SQLModel, table=True):
    """Database table for tasks. Uses plain `str` columns so SQLModel can map them."""

    __tablename__ = "tasks"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    desc: str = ""
    status: str = "todo"
    priority: str = "medium"
    tag: str = "dev"
    assignee: str = "YO"
    due: date | None = None
    due_time: str | None = None
    proj: str = "Website Redesign"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


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
    id: int
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
