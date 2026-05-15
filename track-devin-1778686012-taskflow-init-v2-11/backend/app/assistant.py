"""Voice/text assistant that turns a free-form command into a structured task.

Supports two LLM backends (selected via environment variables):

1. **Azure OpenAI** (preferred) — set ``AZURE_OPENAI_ENDPOINT``,
   ``AZURE_OPENAI_API_KEY``, and ``AZURE_OPENAI_DEPLOYMENT``.
2. **Google Gemini** (fallback) — set ``GEMINI_API_KEY``.

If both are configured, Azure OpenAI wins. If neither is set, the endpoint
returns 502 with a clear error message.
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

# ---------------------------------------------------------------------------
# Gemini config (legacy / fallback)
# ---------------------------------------------------------------------------
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_TIMEOUT = 20.0

# ---------------------------------------------------------------------------
# Azure OpenAI config
# ---------------------------------------------------------------------------
AZURE_OPENAI_API_VERSION = "2024-10-21"
AZURE_OPENAI_TIMEOUT = 60.0


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

Respond ONLY with valid JSON matching this schema:
{{
  "recommendation": "<string>",
  "task": {{
    "title": "<string>",
    "desc": "<string>",
    "status": "todo|inprog|done",
    "priority": "high|medium|low",
    "tag": "dev|design|qa|pm",
    "assignee": "<2-letter code>",
    "due": "YYYY-MM-DD" or null,
    "due_time": "HH:MM" or null,
    "proj": "<exact project name>"
  }}
}}
No markdown fences, no extra text."""


def _response_schema() -> dict[str, Any]:
    """JSON schema used for Gemini's structured output."""
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
    if task.get("due") in ("", None, "null"):
        task.pop("due", None)
    raw_time = task.get("due_time")
    if raw_time in ("", None, "null") or not _TIME_RE.match(str(raw_time)):
        task.pop("due_time", None)
    if task.get("assignee") not in _assignee_codes():
        task["assignee"] = "YO"
    if task.get("proj") not in _project_names():
        task["proj"] = _project_names()[0]
    return task


class AssistantError(RuntimeError):
    """Raised when the assistant cannot fulfil the request."""


# ---------------------------------------------------------------------------
# Azure OpenAI backend
# ---------------------------------------------------------------------------


def _azure_openai_config() -> tuple[str, str, str] | None:
    """Return (endpoint, api_key, deployment) or None if not configured."""
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
    if endpoint and api_key and deployment:
        return endpoint, api_key, deployment
    return None


async def _call_azure_openai(
    prompt: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Call Azure OpenAI Chat Completions and return parsed JSON."""
    config = _azure_openai_config()
    if config is None:
        raise AssistantError(
            "Azure OpenAI is not fully configured. "
            "Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT."
        )
    endpoint, api_key, deployment = config

    url = (
        f"{endpoint.rstrip('/')}/openai/deployments/{deployment}"
        f"/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"
    )
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }
    body = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a task-creation assistant. Always respond with valid JSON only, "
                    "no markdown, no explanation outside the JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 1000,
    }

    try:
        if http_client is None:
            async with httpx.AsyncClient(timeout=AZURE_OPENAI_TIMEOUT) as client:
                response = await client.post(url, headers=headers, json=body)
        else:
            response = await http_client.post(
                url, headers=headers, json=body, timeout=AZURE_OPENAI_TIMEOUT
            )
    except httpx.TimeoutException as exc:
        raise AssistantError(
            "Azure OpenAI request timed out (60s). The model may be overloaded — try again."
        ) from exc
    except httpx.HTTPError as exc:
        raise AssistantError(
            f"Network error calling Azure OpenAI: {exc}"
        ) from exc

    if response.status_code >= 400:
        detail = response.text[:500]
        raise AssistantError(
            f"Azure OpenAI API error {response.status_code}: {detail}"
        )

    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        raise AssistantError("Azure OpenAI returned no choices")
    content = choices[0].get("message", {}).get("content", "")
    if not content:
        raise AssistantError("Azure OpenAI returned empty content")

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise AssistantError(
            f"Azure OpenAI returned non-JSON content: {content[:200]}"
        ) from exc


# ---------------------------------------------------------------------------
# Gemini backend (fallback)
# ---------------------------------------------------------------------------


async def _call_gemini(
    prompt: str,
    *,
    api_key: str,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Call Google Gemini and return parsed JSON."""
    body = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]},
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _response_schema(),
            "temperature": 0.2,
        },
    }
    url = f"{_gemini_url()}?key={api_key}"

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
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AssistantError(
            f"Gemini returned non-JSON content: {text[:200]}"
        ) from exc


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def interpret_command(
    request: AssistantRequest,
    *,
    today: date,
    api_key: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> AssistantResponse:
    """Call the configured LLM and return a structured AssistantResponse.

    Resolution order:
      1. Azure OpenAI (if AZURE_OPENAI_ENDPOINT + KEY + DEPLOYMENT are set)
      2. Google Gemini (if GEMINI_API_KEY is set)
      3. Error
    """
    prompt = _build_prompt(request.text, request.language, today)

    azure_config = _azure_openai_config()
    gemini_key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()

    if azure_config:
        parsed = await _call_azure_openai(prompt, http_client=http_client)
    elif gemini_key:
        parsed = await _call_gemini(
            prompt, api_key=gemini_key, http_client=http_client
        )
    else:
        raise AssistantError(
            "No LLM backend configured. Set AZURE_OPENAI_ENDPOINT + "
            "AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT, or GEMINI_API_KEY."
        )

    parsed["task"] = _normalize_task(parsed.get("task") or {})
    return AssistantResponse.model_validate(parsed)
