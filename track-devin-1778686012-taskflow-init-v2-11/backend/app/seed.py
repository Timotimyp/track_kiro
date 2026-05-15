"""Reference data for projects/users and seed tasks for first launch."""
from __future__ import annotations

from datetime import date

from app.models import Project, Task, User

PROJECTS: list[Project] = [
    Project(name="Website Redesign", slug="proj-website", color="#7c6af7"),
    Project(name="Backend API", slug="proj-backend", color="#4d9ef7"),
    Project(name="Mobile App", slug="proj-mobile", color="#3ecf8e"),
    Project(name="Operations", slug="proj-ops", color="#f5a623"),
]

USERS: list[User] = [
    User(code="AK", name="Alex Kim", color="#7c6af7"),
    User(code="BL", name="Beth Lin", color="#3ecf8e"),
    User(code="CJ", name="Chris Jo", color="#f5a623"),
    User(code="DM", name="Dana Mo", color="#4d9ef7"),
    User(code="YO", name="You", color="#f56060"),
]


_SEED_TASKS_DATA: list[dict] = [
    {
        "title": "Redesign landing page hero section",
        "desc": "Update hero with new brand guidelines",
        "status": "inprog",
        "priority": "high",
        "tag": "design",
        "assignee": "AK",
        "due": date(2026, 5, 10),
        "proj": "Website Redesign",
    },
    {
        "title": "Set up CI/CD pipeline for staging",
        "desc": "Use GitHub Actions",
        "status": "done",
        "priority": "medium",
        "tag": "dev",
        "assignee": "BL",
        "due": date(2026, 5, 8),
        "proj": "Backend API",
    },
    {
        "title": "Write unit tests for auth module",
        "desc": "Target 80% code coverage",
        "status": "todo",
        "priority": "high",
        "tag": "qa",
        "assignee": "CJ",
        "due": date(2026, 5, 15),
        "proj": "Backend API",
    },
    {
        "title": "Create sprint retrospective deck",
        "desc": "Q2 retrospective",
        "status": "done",
        "priority": "low",
        "tag": "pm",
        "assignee": "DM",
        "due": date(2026, 5, 9),
        "proj": "Operations",
    },
    {
        "title": "Fix payment gateway timeout bug",
        "desc": "Intermittent 504 errors on checkout",
        "status": "inprog",
        "priority": "high",
        "tag": "dev",
        "assignee": "BL",
        "due": date(2026, 5, 14),
        "proj": "Backend API",
    },
    {
        "title": "User interview — mobile onboarding",
        "desc": "5 interviews scheduled",
        "status": "todo",
        "priority": "medium",
        "tag": "design",
        "assignee": "AK",
        "due": date(2026, 5, 16),
        "proj": "Mobile App",
    },
    {
        "title": "API documentation update",
        "desc": "Add new endpoints for v2",
        "status": "inprog",
        "priority": "low",
        "tag": "dev",
        "assignee": "CJ",
        "due": date(2026, 5, 18),
        "proj": "Backend API",
    },
    {
        "title": "QA regression test — v2.3 release",
        "desc": "Full regression before release",
        "status": "todo",
        "priority": "medium",
        "tag": "qa",
        "assignee": "DM",
        "due": date(2026, 5, 20),
        "proj": "Mobile App",
    },
]


def build_seed_tasks() -> list[Task]:
    """Return a fresh list of Task instances for seeding."""
    return [Task(**row) for row in _SEED_TASKS_DATA]
