"""Schedule-conflict detection for AI-suggested tasks.

Two sources of "occupied" slots:

1. The TaskFlow task store (Azure Cosmos DB in production, in-memory in
   tests/dev) — exact `due` + `due_time` match. Tasks have no duration
   field, so we treat them as point-in-time slots.
2. The user's Outlook Calendar (optional) — fetched via Microsoft Graph
   using the access token forwarded by the frontend. Outlook events have
   real `start` and `end`, so they're treated as intervals.

When the AI proposes a slot, we look in both sources. If anything overlaps,
we return a conflict block with the conflicting items and up to 3 free
alternatives. Alternatives are checked against both sources too.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from app.graph import (
    GraphEvent,
    events_overlapping,
    fetch_calendar_view,
)
from app.models import Task
from app.repository import TaskRepository

SLOT_DURATION_MINUTES = 60
"""Assumed length of an AI-suggested slot when comparing against Outlook events."""


class AssistantConflictTask(BaseModel):
    """An item that occupies the slot the user is trying to schedule.

    `source` distinguishes a local TaskFlow task from an external Outlook
    meeting so the UI can label them appropriately.
    """

    id: str
    title: str
    due: date
    due_time: str
    source: Literal["taskflow", "outlook"] = "taskflow"


class AssistantAlternative(BaseModel):
    due: date
    due_time: str


class AssistantConflict(BaseModel):
    conflicts: list[AssistantConflictTask]
    alternatives: list[AssistantAlternative]


def _shift_same_day(due: date, due_time: str, hours: int) -> tuple[date, str] | None:
    base = datetime.combine(due, datetime.strptime(due_time, "%H:%M").time())
    shifted = base + timedelta(hours=hours)
    if shifted.date() != due:
        return None
    return shifted.date(), shifted.strftime("%H:%M")


def _candidate_slots(due: date, due_time: str) -> list[tuple[date, str]]:
    out: list[tuple[date, str]] = []
    for hours in (1, -1, 2, -2, 3, -3):
        shifted = _shift_same_day(due, due_time, hours)
        if shifted is not None:
            out.append(shifted)
    next_day = due + timedelta(days=1)
    out.append((next_day, due_time))
    nd_plus_one = _shift_same_day(next_day, due_time, 1)
    if nd_plus_one is not None:
        out.append(nd_plus_one)
    return out


def _slot_to_utc_range(due: date, due_time: str) -> tuple[datetime, datetime]:
    """Map a (date, HH:MM) to a UTC start/end interval of `SLOT_DURATION_MINUTES`.

    We don't know the user's local timezone; treating the slot as UTC is good
    enough for collision arithmetic since Outlook events come back in UTC too.
    """
    start = datetime.combine(due, datetime.strptime(due_time, "%H:%M").time()).replace(
        tzinfo=UTC
    )
    return start, start + timedelta(minutes=SLOT_DURATION_MINUTES)


def _is_slot_free(
    repo: TaskRepository,
    user_id: str,
    due: date,
    due_time: str,
    calendar_events: list[GraphEvent],
) -> bool:
    if repo.find_at_slot(user_id, due, due_time):
        return False
    slot_start, slot_end = _slot_to_utc_range(due, due_time)
    if events_overlapping(calendar_events, slot_start, slot_end):
        return False
    return True


def compute_alternatives(
    repo: TaskRepository,
    user_id: str,
    due: date,
    due_time: str,
    *,
    calendar_events: list[GraphEvent] | None = None,
    max_alternatives: int = 3,
) -> list[AssistantAlternative]:
    """Return up to `max_alternatives` slots that are free in both sources."""
    events = calendar_events or []
    seen: set[tuple[str, str]] = set()
    free: list[AssistantAlternative] = []
    for cand_date, cand_time in _candidate_slots(due, due_time):
        key = (cand_date.isoformat(), cand_time)
        if key in seen:
            continue
        seen.add(key)
        if not _is_slot_free(repo, user_id, cand_date, cand_time, events):
            continue
        free.append(AssistantAlternative(due=cand_date, due_time=cand_time))
        if len(free) >= max_alternatives:
            break
    return free


def _local_tasks_to_conflict(tasks: list[Task]) -> list[AssistantConflictTask]:
    out: list[AssistantConflictTask] = []
    for t in tasks:
        if t.due is None or not t.due_time:
            continue
        out.append(
            AssistantConflictTask(
                id=f"taskflow:{t.id}",
                title=t.title,
                due=t.due,
                due_time=t.due_time,
                source="taskflow",
            )
        )
    return out


def _outlook_events_to_conflict(
    events: list[GraphEvent],
) -> list[AssistantConflictTask]:
    out: list[AssistantConflictTask] = []
    for e in events:
        start_local = e.start.astimezone(UTC)
        out.append(
            AssistantConflictTask(
                id=f"outlook:{e.id}",
                title=e.subject,
                due=start_local.date(),
                due_time=start_local.strftime("%H:%M"),
                source="outlook",
            )
        )
    return out


async def check_conflict(
    repo: TaskRepository,
    user_id: str,
    due: date | None,
    due_time: str | None,
    *,
    access_token: str | None = None,
) -> AssistantConflict | None:
    """Detect conflicts in TaskFlow and (if a token is provided) Outlook.

    Returns None when both sources are clear.
    """
    if due is None or not due_time:
        return None

    local_conflicts = repo.find_at_slot(user_id, due, due_time)

    calendar_events: list[GraphEvent] = []
    overlapping: list[GraphEvent] = []
    if access_token:
        slot_start, slot_end = _slot_to_utc_range(due, due_time)
        calendar_events = await fetch_calendar_view(
            access_token,
            slot_start - timedelta(hours=4),
            slot_end + timedelta(hours=4),
        )
        overlapping = events_overlapping(calendar_events, slot_start, slot_end)

    if not local_conflicts and not overlapping:
        return None

    conflicts = _local_tasks_to_conflict(local_conflicts) + _outlook_events_to_conflict(
        overlapping
    )
    alternatives = compute_alternatives(
        repo, user_id, due, due_time, calendar_events=calendar_events
    )
    return AssistantConflict(conflicts=conflicts, alternatives=alternatives)
