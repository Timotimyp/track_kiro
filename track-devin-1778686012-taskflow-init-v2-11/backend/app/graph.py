"""Microsoft Graph API helpers for Outlook Calendar integration.

We use the Graph token forwarded by the frontend (delegated, on-behalf-of-user
flow) and call Graph endpoints directly. The backend itself does not validate
the token — it simply forwards it to Graph, which is the ultimate authority on
whether the token is valid and what scopes it has.

This keeps the backend stateless: it stores no user identity, no sessions, no
refresh tokens. The Microsoft access token is short-lived (~1h) and the
frontend (MSAL.js) is responsible for renewing it.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import BaseModel

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_TIMEOUT = 10.0


class GraphEvent(BaseModel):
    """A normalized Outlook calendar event."""

    id: str
    subject: str
    start: datetime
    end: datetime


def _parse_graph_dt(slot: dict[str, str]) -> datetime:
    """Parse a Graph dateTime slot into a UTC-aware datetime."""
    raw = slot.get("dateTime", "")
    # We send `Prefer: outlook.timezone="UTC"`, so values come back in UTC.
    cleaned = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"unparseable Graph dateTime: {raw!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


async def fetch_calendar_view(
    access_token: str,
    start: datetime,
    end: datetime,
) -> list[GraphEvent]:
    """Fetch the user's Outlook events between `start` and `end` (both UTC).

    Returns an empty list if the token is missing/invalid or Graph fails — we
    never want a Graph outage to bring the assistant down.
    """
    if not access_token:
        return []
    params = {
        "startDateTime": start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "endDateTime": end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "$top": "100",
        "$select": "id,subject,start,end",
        "$orderby": "start/dateTime",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Prefer": 'outlook.timezone="UTC"',
    }
    try:
        async with httpx.AsyncClient(timeout=GRAPH_TIMEOUT) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/me/calendarView", params=params, headers=headers
            )
    except httpx.HTTPError as exc:
        log.warning("Graph calendarView request failed: %s", exc)
        return []
    if resp.status_code != 200:
        log.warning(
            "Graph calendarView returned %s: %s", resp.status_code, resp.text[:500]
        )
        return []
    payload = resp.json()
    out: list[GraphEvent] = []
    for item in payload.get("value", []):
        try:
            out.append(
                GraphEvent(
                    id=item["id"],
                    subject=item.get("subject") or "(без названия)",
                    start=_parse_graph_dt(item["start"]),
                    end=_parse_graph_dt(item["end"]),
                )
            )
        except (KeyError, ValueError):
            continue
    return out


async def create_calendar_event(
    access_token: str,
    *,
    subject: str,
    body: str,
    start: datetime,
    end: datetime,
    time_zone: str = "UTC",
) -> dict | None:
    """Create an Outlook event. Returns the Graph JSON or None on failure.

    ``start`` and ``end`` must be timezone-aware. ``time_zone`` is the IANA
    name (e.g. "Europe/Moscow") under which Graph should store the event.
    We send the local wall-clock time alongside that zone so the event
    appears in Outlook at the time the user actually typed, not shifted by
    whatever offset their local zone has from UTC.
    """
    if not access_token:
        return None
    # The caller is expected to have constructed `start` and `end` already in
    # the desired wall-clock zone (matching `time_zone`). We just format the
    # local components and tell Graph what zone they're in.
    payload = {
        "subject": subject,
        "body": {"contentType": "text", "content": body},
        "start": {
            "dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": time_zone,
        },
        "end": {
            "dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": time_zone,
        },
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=GRAPH_TIMEOUT) as client:
            resp = await client.post(
                f"{GRAPH_BASE}/me/events", json=payload, headers=headers
            )
    except httpx.HTTPError as exc:
        log.warning("Graph POST /me/events request failed: %s", exc)
        return None
    if resp.status_code in (200, 201):
        return resp.json()
    log.warning(
        "Graph POST /me/events returned %s: %s", resp.status_code, resp.text[:500]
    )
    return None


def events_overlapping(
    events: list[GraphEvent], slot_start: datetime, slot_end: datetime
) -> list[GraphEvent]:
    """Return events whose [start, end) interval overlaps the given slot."""
    return [e for e in events if e.start < slot_end and e.end > slot_start]


def slot_window_for_day(
    due_date: datetime, hours_around: int = 4
) -> tuple[datetime, datetime]:
    """Return a window centered on `due_date` for calendarView fetches."""
    return (
        due_date - timedelta(hours=hours_around),
        due_date + timedelta(hours=hours_around),
    )
