"""Task storage abstraction with Azure Cosmos DB and in-memory backends.

The application talks to a `TaskRepository`. In production we wire the
`CosmosTaskRepository`, which stores each task as a JSON document in a
Cosmos DB container partitioned by `/proj` (project name). For local
development without a Cosmos account, and for the test suite, the
`InMemoryTaskRepository` is used instead — it has identical semantics
without any external dependency.

Selection happens in `get_repository()` based on environment variables:

  COSMOS_ENDPOINT   – e.g. "https://<account>.documents.azure.com:443/"
  COSMOS_KEY        – primary key (use either this OR Managed Identity)
  COSMOS_USE_AAD    – "1"/"true" to authenticate with DefaultAzureCredential
  COSMOS_DATABASE   – database name (default: "taskflow")
  COSMOS_CONTAINER  – container name (default: "tasks")

If neither key nor AAD is configured, we fall back to in-memory storage
and log a warning. This keeps `uv run pytest` and local `uvicorn` running
without a real Azure account.
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
    """Storage interface used by the API layer."""

    def list_tasks(self) -> list[Task]: ...

    def get_task(self, task_id: str) -> Task | None: ...

    def add_task(self, task: Task) -> Task: ...

    def update_task(self, task: Task) -> Task: ...

    def delete_task(self, task_id: str) -> bool: ...

    def find_at_slot(self, due: date, due_time: str) -> list[Task]: ...

    def is_empty(self) -> bool: ...


# ---------------------------------------------------------------------------
# In-memory implementation (used by tests and for local runs without Cosmos)
# ---------------------------------------------------------------------------


class InMemoryTaskRepository:
    """Thread-safe dict-backed implementation of `TaskRepository`."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.RLock()

    def list_tasks(self) -> list[Task]:
        with self._lock:
            # Stable ordering by created_at then id, mirroring "ORDER BY id"
            # from the previous SQLite-backed implementation.
            return sorted(
                self._tasks.values(),
                key=lambda t: (t.created_at, t.id),
            )

    def get_task(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def add_task(self, task: Task) -> Task:
        with self._lock:
            self._tasks[task.id] = task
            return task

    def update_task(self, task: Task) -> Task:
        with self._lock:
            self._tasks[task.id] = task
            return task

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            return self._tasks.pop(task_id, None) is not None

    def find_at_slot(self, due: date, due_time: str) -> list[Task]:
        with self._lock:
            return [
                t
                for t in self._tasks.values()
                if t.due == due and t.due_time == due_time
            ]

    def is_empty(self) -> bool:
        with self._lock:
            return not self._tasks


# ---------------------------------------------------------------------------
# Azure Cosmos DB implementation
# ---------------------------------------------------------------------------


def _task_to_doc(task: Task) -> dict[str, Any]:
    """Serialise a Task to a JSON-safe Cosmos document.

    Cosmos stores JSON, so dates/datetimes go in as ISO strings. The `id`
    must be a non-empty string. The partition key is `proj`.
    """
    return {
        "id": task.id,
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

    The container is created on first use if it doesn't exist. Partition key
    is `/proj` so reads filtered by project go to a single partition.
    """

    PARTITION_KEY_PATH = "/proj"

    def __init__(
        self,
        *,
        endpoint: str,
        credential: Any,
        database_name: str = "taskflow",
        container_name: str = "tasks",
    ) -> None:
        # Imported lazily so the test environment doesn't need the SDK loaded.
        from azure.cosmos import CosmosClient, PartitionKey  # type: ignore[import-not-found]

        self._client = CosmosClient(endpoint, credential=credential)
        self._database = self._client.create_database_if_not_exists(id=database_name)
        self._container = self._database.create_container_if_not_exists(
            id=container_name,
            partition_key=PartitionKey(path=self.PARTITION_KEY_PATH),
        )
        log.info(
            "Cosmos DB repository ready (database=%s, container=%s)",
            database_name,
            container_name,
        )

    # --- TaskRepository protocol --------------------------------------------------

    def list_tasks(self) -> list[Task]:
        items: Iterable[dict[str, Any]] = self._container.query_items(
            query="SELECT * FROM c ORDER BY c.created_at ASC",
            enable_cross_partition_query=True,
        )
        return [_doc_to_task(doc) for doc in items]

    def get_task(self, task_id: str) -> Task | None:
        # We don't know the partition for a given id without a lookup, so
        # use a cross-partition query keyed by id.
        items = list(
            self._container.query_items(
                query="SELECT * FROM c WHERE c.id = @id",
                parameters=[{"name": "@id", "value": task_id}],
                enable_cross_partition_query=True,
            )
        )
        return _doc_to_task(items[0]) if items else None

    def add_task(self, task: Task) -> Task:
        self._container.create_item(body=_task_to_doc(task))
        return task

    def update_task(self, task: Task) -> Task:
        # `upsert_item` makes the call idempotent and avoids needing to know
        # the document's current `_etag`. Partition key is derived from the
        # `proj` field in the body.
        self._container.upsert_item(body=_task_to_doc(task))
        return task

    def delete_task(self, task_id: str) -> bool:
        existing = self.get_task(task_id)
        if existing is None:
            return False
        self._container.delete_item(item=existing.id, partition_key=existing.proj)
        return True

    def find_at_slot(self, due: date, due_time: str) -> list[Task]:
        items = self._container.query_items(
            query=(
                "SELECT * FROM c WHERE c.due = @due AND c.due_time = @due_time"
            ),
            parameters=[
                {"name": "@due", "value": due.isoformat()},
                {"name": "@due_time", "value": due_time},
            ],
            enable_cross_partition_query=True,
        )
        return [_doc_to_task(doc) for doc in items]

    def is_empty(self) -> bool:
        items = list(
            self._container.query_items(
                query="SELECT VALUE COUNT(1) FROM c",
                enable_cross_partition_query=True,
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
    except Exception as exc:  # pragma: no cover - depends on Azure availability
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
