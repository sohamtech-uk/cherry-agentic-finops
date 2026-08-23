from __future__ import annotations

from abc import ABC, abstractmethod
from threading import RLock

from app.config import Settings
from app.models import WorkflowRecord


class WorkflowRepository(ABC):
    @abstractmethod
    def save(self, workflow: WorkflowRecord) -> None: ...

    @abstractmethod
    def get(self, workflow_id: str) -> WorkflowRecord | None: ...

    @abstractmethod
    def list(self) -> list[WorkflowRecord]: ...

    @abstractmethod
    def clear(self) -> None: ...


class InMemoryWorkflowRepository(WorkflowRepository):
    def __init__(self) -> None:
        self._records: dict[str, WorkflowRecord] = {}
        self._lock = RLock()

    def save(self, workflow: WorkflowRecord) -> None:
        with self._lock:
            self._records[workflow.workflow_id] = workflow.model_copy(deep=True)

    def get(self, workflow_id: str) -> WorkflowRecord | None:
        with self._lock:
            record = self._records.get(workflow_id)
            return record.model_copy(deep=True) if record else None

    def list(self) -> list[WorkflowRecord]:
        with self._lock:
            return sorted(
                (record.model_copy(deep=True) for record in self._records.values()),
                key=lambda record: record.created_at,
                reverse=True,
            )

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


class FirestoreWorkflowRepository(WorkflowRepository):
    """Firestore adapter loaded lazily so local demo mode has no cloud dependency at import time."""

    def __init__(self, settings: Settings) -> None:
        try:
            from google.cloud import firestore
        except ImportError as exc:  # pragma: no cover - only possible in reduced local installs
            raise RuntimeError(
                "Install google-cloud-firestore to use Firestore persistence."
            ) from exc

        self._client = firestore.Client(project=settings.google_cloud_project)
        self._collection = self._client.collection(settings.firestore_collection)

    def save(self, workflow: WorkflowRecord) -> None:
        self._collection.document(workflow.workflow_id).set(workflow.model_dump(mode="json"))

    def get(self, workflow_id: str) -> WorkflowRecord | None:
        snapshot = self._collection.document(workflow_id).get()
        if not snapshot.exists:
            return None
        return WorkflowRecord.model_validate(snapshot.to_dict())

    def list(self) -> list[WorkflowRecord]:
        records = [
            WorkflowRecord.model_validate(snapshot.to_dict())
            for snapshot in self._collection.stream()
        ]
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def clear(self) -> None:
        for snapshot in self._collection.stream():
            snapshot.reference.delete()


def build_repository(settings: Settings) -> WorkflowRepository:
    if settings.persistence_backend == "firestore":
        return FirestoreWorkflowRepository(settings)
    return InMemoryWorkflowRepository()
