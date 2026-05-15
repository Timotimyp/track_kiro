"""Voice/text assistant that turns a free-form command into a structured task.

Calls Google Gemini's `generateContent` REST endpoint with a strict JSON schema so
the response is deterministic and easy to consume. The API key is read from the
``GEMINI_API_KEY`` environment variable.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.conflicts import AssistantConflict
from app.models import Priority, Status, Tag
from app.seed import PROJECTS, USERS

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_TIMEOUT = 20.0


def _gemini_url() -> str:
    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    return f"{GEMINI_API_BASE}/{model}:generateContent"


class AssistantRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: str = "ru-RU"
    # Optional IANA timezone (e.g. "Europe/Moscow") so the assistant
    # interprets "today" / "tomorrow" relative to the user's local day, not
    # the server's UTC day.
    tz: str | None = None


class AssistantTask(BaseModel):
    title: str
    desc: str = ""
    status: Status = "todo"
    priority: Priority = "medium"
    tag: Tag = "dev"
    assignee: str = "YO"
    due: date | None = None
    due_time: str | None = None
    proj: str = "Website Redesign"


class AssistantResponse(BaseModel):
    recommendation: str
    task: AssistantTask
    conflict: AssistantConflict | None = None


def _project_names() -> list[str]:
    return [p.name for p in PROJECTS]


def _assignee_codes() -> list[str]:
    return [u.code for u in USERS]


def _build_prompt(text: str, language: str, today: date) -> str:
    project_lines = "\n".join(f"- {p.name}" for p in PROJECTS)
    user_lines = "\n".join(f"- {u.code}: {u.name}" for u in USERS)
    is_russian = language.lower().startswith("ru")
    reply_lang = "Russian" if is_russian else "English"
    return f"""You are TaskFlow's task-creation assistant.

The user spoke (language: {language}, today is {today.isoformat()}):
"\"\"\"{text}\"\"\""

Extract a single actionable task from this command. Pick the most appropriate
values from the lists below — do NOT invent new projects, assignees, tags, or
statuses.

Available projects:
{project_lines}

Available assignees (use the 2-letter code only):
{user_lines}
- "YO" means the speaker themself; use it when the user says "me/myself/я/мне".

Available categories (tag): dev, design, qa, pm.
Available priorities: high, medium, low.
Available statuses: todo (default), inprog, done.

Date handling:
- If the user mentions a relative date ("tomorrow", "next week", "Friday",
  "завтра", "в пятницу", "через 3 дня"), compute the actual YYYY-MM-DD using
  today = {today.isoformat()}.
- If no date is mentioned, omit `due` (set it to null).
- Never set a due date in the past.

Time handling:
- If the user mentions a specific time of day ("at 3pm", "в 15:00", "в 3 дня",
  "к 17:30", "вечером", "in the morning"), set `due_time` to the 24-hour
  "HH:MM" string (e.g. "15:00", "09:30"). Map vague phrases sensibly:
  morning=09:00, noon=12:00, afternoon=15:00, evening=18:00, night=21:00,
  "в X дня"=15:00 + X hours when ambiguous, but prefer explicit numbers.
- If no time is mentioned, omit `due_time` (set it to null).
- `due_time` only makes sense together with `due`; if `due` is null, leave
  `due_time` null too.

Recommendation field:
- Write 1-2 short sentences in {reply_lang} explaining why you picked this
  project / assignee / priority / due date. Be concise and concrete.

Title field:
- Short, imperative, max ~80 chars. Strip filler words.

Respond ONLY with JSON that conforms to the response schema. No prose, no
markdown fences."""


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "recommendation": {"type": "string"},
            "task": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "desc": {"type": "string"},
                    "status": {"type": "string", "enum": ["todo", "inprog", "done"]},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "tag": {"type": "string", "enum": ["dev", "design", "qa", "pm"]},
                    "assignee": {"type": "string", "enum": _assignee_codes()},
                    "due": {"type": "string"},
                    "due_time": {"type": "string"},
                    "proj": {"type": "string", "enum": _project_names()},
                },
                "required": [
                    "title",
                    "priority",
                    "tag",
                    "assignee",
                    "proj",
                    "status",
                ],
            },
        },
        "required": ["recommendation", "task"],
    }


def _extract_json_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise AssistantError("Gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts") or []
    if not parts:
        raise AssistantError("Gemini returned an empty content")
    return parts[0].get("text", "")


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _normalize_task(raw: dict[str, Any]) -> dict[str, Any]:
    """Patch loose model output so it matches AssistantTask validation."""
    task = dict(raw)
    if task.get("due") in ("", None):
        task.pop("due", None)
    raw_time = task.get("due_time")
    if raw_time in ("", None) or not _TIME_RE.match(str(raw_time)):
        task.pop("due_time", None)
    if task.get("assignee") not in _assignee_codes():
        task["assignee"] = "YO"
    if task.get("proj") not in _project_names():
        task["proj"] = _project_names()[0]
    return task


class AssistantError(RuntimeError):
    """Raised when the assistant cannot fulfil the request."""


async def interpret_command(
    request: AssistantRequest,
    *,
    today: date,
    api_key: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> AssistantResponse:
    """Call Gemini and return a structured AssistantResponse."""
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise AssistantError(
            "GEMINI_API_KEY is not configured on the server."
        )

    body = {
        "contents": [
            {"role": "user", "parts": [{"text": _build_prompt(request.text, request.language, today)}]},
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _response_schema(),
            "temperature": 0.2,
        },
    }
    url = f"{_gemini_url()}?key={key}"

    if http_client is None:
        async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
            response = await client.post(url, json=body)
    else:
        response = await http_client.post(url, json=body, timeout=GEMINI_TIMEOUT)

    if response.status_code >= 400:
        detail = response.text[:500]
        raise AssistantError(f"Gemini API error {response.status_code}: {detail}")

    payload = response.json()
    text = _extract_json_text(payload)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AssistantError(f"Gemini returned non-JSON content: {text[:200]}") from exc

    parsed["task"] = _normalize_task(parsed.get("task") or {})
    return AssistantResponse.model_validate(parsed)
