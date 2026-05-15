"""Task storage abstraction with Azure Cosmos DB and in-memory backends.

Partition key is now `/user_id` — each user's tasks live in their own
logical partition. All query methods require a `user_id` parameter so
one user can never see another user's data.

Selection happens in `get_repository()` based on environment variables:

  COSMOS_ENDPOINT   – e.g. "https://<account>.documents.azure.com:443/"
  COSMOS_KEY        – primary key (use either this OR Managed Identity)
  COSMOS_USE_AAD    – "1"/"true" to authenticate with DefaultAzureCredential
  COSMOS_DATABASE   – database name (default: "taskflow")
  COSMOS_CONTAINER  – container name (default: "tasks")

If neither key nor AAD is configured, we fall back to in-memory storage.
"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, Protocol

from app.models import Task

log = logging.getLogger(__name__)


class TaskRepository(Protocol):
    """Storage interface used by the API layer. All methods are user-scoped."""

    def list_tasks(self, user_id: str) -> list[Task]: ...

    def get_task(self, task_id: str, user_id: str) -> Task | None: ...

    def add_task(self, task: Task) -> Task: ...

    def update_task(self, task: Task) -> Task: ...

    def delete_task(self, task_id: str, user_id: str) -> bool: ...

    def find_at_slot(self, user_id: str, due: date, due_time: str) -> list[Task]: ...

    def is_empty_for_user(self, user_id: str) -> bool: ...


# ---------------------------------------------------------------------------
# In-memory implementation (used by tests and for local runs without Cosmos)
# ---------------------------------------------------------------------------


class InMemoryTaskRepository:
    """Thread-safe dict-backed implementation of `TaskRepository`."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.RLock()

    def list_tasks(self, user_id: str) -> list[Task]:
        with self._lock:
            return sorted(
                (t for t in self._tasks.values() if t.user_id == user_id),
                key=lambda t: (t.created_at, t.id),
            )

    def get_task(self, task_id: str, user_id: str) -> Task | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.user_id == user_id:
                return task
            return None

    def add_task(self, task: Task) -> Task:
        with self._lock:
            self._tasks[task.id] = task
            return task

    def update_task(self, task: Task) -> Task:
        with self._lock:
            self._tasks[task.id] = task
            return task

    def delete_task(self, task_id: str, user_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.user_id == user_id:
                del self._tasks[task_id]
                return True
            return False

    def find_at_slot(self, user_id: str, due: date, due_time: str) -> list[Task]:
        with self._lock:
            return [
                t
                for t in self._tasks.values()
                if t.user_id == user_id and t.due == due and t.due_time == due_time
            ]

    def is_empty_for_user(self, user_id: str) -> bool:
        with self._lock:
            return not any(t.user_id == user_id for t in self._tasks.values())


# ---------------------------------------------------------------------------
# Azure Cosmos DB implementation
# ---------------------------------------------------------------------------


def _task_to_doc(task: Task) -> dict[str, Any]:
    """Serialise a Task to a JSON-safe Cosmos document."""
    return {
        "id": task.id,
        "user_id": task.user_id,
        "title": task.title,
        "desc": task.desc,
        "status": task.status,
        "priority": task.priority,
        "tag": task.tag,
        "assignee": task.assignee,
        "due": task.due.isoformat() if task.due else None,
        "due_time": task.due_time,
        "proj": task.proj,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


def _doc_to_task(doc: dict[str, Any]) -> Task:
    """Deserialise a Cosmos document back into a Task."""
    raw_due = doc.get("due")
    raw_created = doc.get("created_at")
    raw_updated = doc.get("updated_at")
    return Task(
        id=str(doc["id"]),
        user_id=doc.get("user_id", ""),
        title=doc.get("title", ""),
        desc=doc.get("desc", "") or "",
        status=doc.get("status", "todo"),
        priority=doc.get("priority", "medium"),
        tag=doc.get("tag", "dev"),
        assignee=doc.get("assignee", "YO"),
        due=date.fromisoformat(raw_due) if raw_due else None,
        due_time=doc.get("due_time"),
        proj=doc.get("proj", "Website Redesign"),
        created_at=(
            datetime.fromisoformat(raw_created) if raw_created else datetime.utcnow()
        ),
        updated_at=(
            datetime.fromisoformat(raw_updated) if raw_updated else datetime.utcnow()
        ),
    )


class CosmosTaskRepository:
    """Cosmos DB NoSQL Core API implementation of `TaskRepository`.

    Partition key is `/user_id` — each user's tasks are isolated in their
    own logical partition for efficient reads and strong data isolation.
    """

    PARTITION_KEY_PATH = "/user_id"

    def __init__(
        self,
        *,
        endpoint: str,
        credential: Any,
        database_name: str = "taskflow",
        container_name: str = "tasks",
    ) -> None:
        from azure.cosmos import CosmosClient, PartitionKey  # type: ignore[import-not-found]

        self._client = CosmosClient(endpoint, credential=credential)
        self._database = self._client.create_database_if_not_exists(id=database_name)
        self._container = self._database.create_container_if_not_exists(
            id=container_name,
            partition_key=PartitionKey(path=self.PARTITION_KEY_PATH),
        )
        log.info(
            "Cosmos DB repository ready (database=%s, container=%s, partition_key=%s)",
            database_name,
            container_name,
            self.PARTITION_KEY_PATH,
        )

    # --- TaskRepository protocol --------------------------------------------------

    def list_tasks(self, user_id: str) -> list[Task]:
        items: Iterable[dict[str, Any]] = self._container.query_items(
            query="SELECT * FROM c WHERE c.user_id = @uid ORDER BY c.created_at ASC",
            parameters=[{"name": "@uid", "value": user_id}],
            partition_key=user_id,
        )
        return [_doc_to_task(doc) for doc in items]

    def get_task(self, task_id: str, user_id: str) -> Task | None:
        try:
            doc = self._container.read_item(item=task_id, partition_key=user_id)
            return _doc_to_task(doc)
        except Exception:  # noqa: BLE001
            return None

    def add_task(self, task: Task) -> Task:
        self._container.create_item(body=_task_to_doc(task))
        return task

    def update_task(self, task: Task) -> Task:
        self._container.upsert_item(body=_task_to_doc(task))
        return task

    def delete_task(self, task_id: str, user_id: str) -> bool:
        try:
            self._container.delete_item(item=task_id, partition_key=user_id)
            return True
        except Exception:  # noqa: BLE001
            return False

    def find_at_slot(self, user_id: str, due: date, due_time: str) -> list[Task]:
        items = self._container.query_items(
            query="SELECT * FROM c WHERE c.due = @due AND c.due_time = @due_time",
            parameters=[
                {"name": "@due", "value": due.isoformat()},
                {"name": "@due_time", "value": due_time},
            ],
            partition_key=user_id,
        )
        return [_doc_to_task(doc) for doc in items]

    def is_empty_for_user(self, user_id: str) -> bool:
        items = list(
            self._container.query_items(
                query="SELECT VALUE COUNT(1) FROM c",
                partition_key=user_id,
            )
        )
        count = items[0] if items else 0
        return int(count) == 0


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


_repo_singleton: TaskRepository | None = None
_repo_lock = threading.Lock()


def _build_cosmos_repository() -> TaskRepository | None:
    endpoint = os.environ.get("COSMOS_ENDPOINT", "").strip()
    if not endpoint:
        return None

    database_name = os.environ.get("COSMOS_DATABASE", "taskflow").strip() or "taskflow"
    container_name = os.environ.get("COSMOS_CONTAINER", "tasks").strip() or "tasks"

    use_aad = os.environ.get("COSMOS_USE_AAD", "").strip().lower() in {"1", "true", "yes"}
    if use_aad:
        try:
            from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
        except ImportError:
            log.error(
                "COSMOS_USE_AAD is set but azure-identity is not installed; "
                "falling back to in-memory repository."
            )
            return None
        credential: Any = DefaultAzureCredential()
    else:
        key = os.environ.get("COSMOS_KEY", "").strip()
        if not key:
            log.error(
                "COSMOS_ENDPOINT is set but neither COSMOS_KEY nor COSMOS_USE_AAD; "
                "falling back to in-memory repository."
            )
            return None
        credential = key

    try:
        return CosmosTaskRepository(
            endpoint=endpoint,
            credential=credential,
            database_name=database_name,
            container_name=container_name,
        )
    except Exception as exc:  # pragma: no cover
        log.exception("Failed to initialise Cosmos DB repository: %s", exc)
        return None


def get_repository() -> TaskRepository:
    """Return the process-wide repository singleton, building it on first use."""
    global _repo_singleton
    if _repo_singleton is not None:
        return _repo_singleton
    with _repo_lock:
        if _repo_singleton is not None:
            return _repo_singleton
        repo = _build_cosmos_repository()
        if repo is None:
            log.warning(
                "Using InMemoryTaskRepository — set COSMOS_ENDPOINT + "
                "COSMOS_KEY (or COSMOS_USE_AAD=1) to enable Azure Cosmos DB."
            )
            repo = InMemoryTaskRepository()
        _repo_singleton = repo
        return _repo_singleton


def reset_repository(new_repo: TaskRepository | None = None) -> None:
    """Replace the singleton. Tests use this to inject an in-memory repo."""
    global _repo_singleton
    with _repo_lock:
        _repo_singleton = new_repo
