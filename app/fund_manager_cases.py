from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Literal, cast
from uuid import uuid4

from app.config import Settings, get_settings

CaseStage = Literal[
    "classified",
    "planned",
    "executed",
    "investigated",
    "decided",
]

# Firestore documents have a 1 MiB limit. Keep evidence well below that limit after protobuf
# overhead while allowing the existing 50 MiB per-file upload boundary.
FIRESTORE_FILE_CHUNK_BYTES = 512 * 1024


class FundManagerCaseStorageError(RuntimeError):
    """Raised when a stored Fund Manager case cannot be written or reconstructed safely."""


@dataclass
class FundManagerCase:
    case_id: str
    files: list[tuple[str, bytes, str | None]]
    fund_name: str | None
    reporting_period: str | None
    as_of_date: str | None
    created_at: str
    updated_at: str
    revision: int = 1
    stage: CaseStage = "classified"
    classification: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    investigation: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    nav_readiness: dict[str, Any] | None = None
    nav_reconciliation: dict[str, Any] | None = None
    nav_review: dict[str, Any] | None = None
    nav_decision: dict[str, Any] | None = None
    nav_exception_resolutions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat()
        self.revision += 1

    def persistence_view(self) -> dict[str, Any]:
        """Return durable case state without embedding uploaded evidence bytes."""

        return {
            "case_id": self.case_id,
            "fund_name": self.fund_name,
            "reporting_period": self.reporting_period,
            "as_of_date": self.as_of_date,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "stage": self.stage,
            "classification": self.classification,
            "plan": self.plan,
            "execution": self.execution,
            "investigation": self.investigation,
            "decision": self.decision,
            "nav_readiness": self.nav_readiness,
            "nav_reconciliation": self.nav_reconciliation,
            "nav_review": self.nav_review,
            "nav_decision": self.nav_decision,
            "nav_exception_resolutions": self.nav_exception_resolutions,
        }

    @classmethod
    def from_persistence(
        cls,
        record: dict[str, Any],
        files: list[tuple[str, bytes, str | None]],
    ) -> FundManagerCase:
        stage = cast(CaseStage, record.get("stage", "classified"))
        return cls(
            case_id=str(record["case_id"]),
            files=files,
            fund_name=record.get("fund_name"),
            reporting_period=record.get("reporting_period"),
            as_of_date=record.get("as_of_date"),
            created_at=str(record["created_at"]),
            updated_at=str(record["updated_at"]),
            revision=int(record.get("revision", 1)),
            stage=stage,
            classification=dict(record.get("classification") or {}),
            plan=record.get("plan"),
            execution=record.get("execution"),
            investigation=record.get("investigation"),
            decision=record.get("decision"),
            nav_readiness=record.get("nav_readiness"),
            nav_reconciliation=record.get("nav_reconciliation"),
            nav_review=record.get("nav_review"),
            nav_decision=record.get("nav_decision"),
            nav_exception_resolutions=dict(record.get("nav_exception_resolutions") or {}),
        )

    def public_view(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "fund_name": self.fund_name,
            "reporting_period": self.reporting_period,
            "as_of_date": self.as_of_date,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "stage": self.stage,
            "classification": self.classification,
            "plan": self.plan,
            "execution": self.execution,
            "investigation": self.investigation,
            "decision": self.decision,
            "workflows": {
                "general_control_review": {
                    "stage": self.stage,
                    "plan": self.plan,
                    "execution": self.execution,
                    "investigation": self.investigation,
                    "decision": self.decision,
                },
                "nav_quality_controller": {
                    "readiness": self.nav_readiness,
                    "reconciliation": self.nav_reconciliation,
                    "review": self.nav_review,
                    "decision": self.nav_decision,
                    "exception_resolutions": self.nav_exception_resolutions,
                },
            },
        }


def _new_case(
    files: list[tuple[str, bytes, str | None]],
    *,
    classification: dict[str, Any],
    fund_name: str | None,
    reporting_period: str | None,
    as_of_date: str | None,
) -> FundManagerCase:
    now = datetime.now(UTC).isoformat()
    return FundManagerCase(
        case_id=f"FM-{uuid4().hex[:12].upper()}",
        files=files,
        fund_name=fund_name,
        reporting_period=reporting_period,
        as_of_date=as_of_date,
        created_at=now,
        updated_at=now,
        classification=classification,
    )


def _file_manifest(files: list[tuple[str, bytes, str | None]]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for index, (name, content, content_type) in enumerate(files):
        manifest.append(
            {
                "index": index,
                "filename": name,
                "content_type": content_type,
                "sha256": hashlib.sha256(content).hexdigest(),
                "byte_size": len(content),
                "chunk_count": max(
                    1, (len(content) + FIRESTORE_FILE_CHUNK_BYTES - 1) // FIRESTORE_FILE_CHUNK_BYTES
                ),
            }
        )
    return manifest


class FundManagerCaseStore(ABC):
    """Persistence contract for staged Fund Manager cases and their uploaded evidence."""

    backend_name: str

    def create(
        self,
        files: list[tuple[str, bytes, str | None]],
        *,
        classification: dict[str, Any],
        fund_name: str | None = None,
        reporting_period: str | None = None,
        as_of_date: str | None = None,
    ) -> FundManagerCase:
        case = _new_case(
            files,
            classification=classification,
            fund_name=fund_name,
            reporting_period=reporting_period,
            as_of_date=as_of_date,
        )
        self.save(case)
        return case

    @abstractmethod
    def save(self, case: FundManagerCase) -> None:
        """Persist the complete logical case."""

    @abstractmethod
    def get(self, case_id: str) -> FundManagerCase | None:
        """Load a case, including the evidence bytes needed by later workflow stages."""

    @abstractmethod
    def clear(self) -> None:
        """Clear cases in test/local environments."""


class InMemoryFundManagerCaseStore(FundManagerCaseStore):
    """Thread-safe local store that mirrors durable-store copy-in/copy-out semantics."""

    backend_name = "memory"

    def __init__(self) -> None:
        self._cases: dict[str, FundManagerCase] = {}
        self._lock = RLock()

    def save(self, case: FundManagerCase) -> None:
        with self._lock:
            self._cases[case.case_id] = deepcopy(case)

    def get(self, case_id: str) -> FundManagerCase | None:
        with self._lock:
            case = self._cases.get(case_id)
            return deepcopy(case) if case is not None else None

    def clear(self) -> None:
        with self._lock:
            self._cases.clear()


class FirestoreFundManagerCaseStore(FundManagerCaseStore):
    """Durable case store using Firestore documents and chunked evidence subcollections."""

    backend_name = "firestore"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if client is None:
            from google.cloud import firestore

            client = firestore.Client(project=settings.google_cloud_project)
        self._client = client
        self._collection = client.collection(settings.fund_manager_firestore_collection)

    @staticmethod
    def _delete_file_chunks(file_ref: Any) -> None:
        for chunk_snapshot in file_ref.collection("chunks").stream():
            chunk_snapshot.reference.delete()
        file_ref.delete()

    def _write_file(self, case_ref: Any, entry: dict[str, Any], content: bytes) -> None:
        file_ref = case_ref.collection("files").document(str(entry["index"]))
        self._delete_file_chunks(file_ref)
        file_ref.set({key: value for key, value in entry.items() if key != "index"})
        chunks = file_ref.collection("chunks")
        for chunk_index in range(int(entry["chunk_count"])):
            start = chunk_index * FIRESTORE_FILE_CHUNK_BYTES
            chunks.document(f"{chunk_index:06d}").set(
                {
                    "index": chunk_index,
                    "data": content[start : start + FIRESTORE_FILE_CHUNK_BYTES],
                }
            )

    def save(self, case: FundManagerCase) -> None:
        case_ref = self._collection.document(case.case_id)
        try:
            snapshot = case_ref.get()
            existing_record = dict(snapshot.to_dict() or {}) if snapshot.exists else {}
            existing_manifest = existing_record.get("file_manifest") or []
            manifest = _file_manifest(case.files)

            for index, entry in enumerate(manifest):
                if index >= len(existing_manifest) or existing_manifest[index] != entry:
                    self._write_file(case_ref, entry, case.files[index][1])

            for stale_index in range(len(manifest), len(existing_manifest)):
                self._delete_file_chunks(case_ref.collection("files").document(str(stale_index)))

            case_ref.set({**case.persistence_view(), "file_manifest": manifest})
        except FundManagerCaseStorageError:
            raise
        except Exception as exc:
            raise FundManagerCaseStorageError(
                f"Could not persist Fund Manager case {case.case_id}."
            ) from exc

    @staticmethod
    def _read_file(case_ref: Any, entry: dict[str, Any]) -> tuple[str, bytes, str | None]:
        file_ref = case_ref.collection("files").document(str(entry["index"]))
        file_snapshot = file_ref.get()
        if not file_snapshot.exists:
            raise FundManagerCaseStorageError(
                f"Evidence {entry['index']} is missing for the stored Fund Manager case."
            )

        chunk_snapshots = list(file_ref.collection("chunks").stream())
        chunks_by_index = {
            int((snapshot.to_dict() or {}).get("index", -1)): bytes(
                (snapshot.to_dict() or {}).get("data", b"")
            )
            for snapshot in chunk_snapshots
        }
        expected_chunks = int(entry["chunk_count"])
        if set(chunks_by_index) != set(range(expected_chunks)):
            raise FundManagerCaseStorageError(
                f"Evidence {entry['index']} is incomplete for the stored Fund Manager case."
            )

        content = b"".join(chunks_by_index[index] for index in range(expected_chunks))
        if len(content) != int(entry["byte_size"]):
            raise FundManagerCaseStorageError(
                f"Evidence {entry['index']} has an invalid size in the stored Fund Manager case."
            )
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise FundManagerCaseStorageError(
                f"Evidence {entry['index']} failed integrity verification."
            )
        return str(entry["filename"]), content, entry.get("content_type")

    def get(self, case_id: str) -> FundManagerCase | None:
        case_ref = self._collection.document(case_id)
        try:
            snapshot = case_ref.get()
            if not snapshot.exists:
                return None
            record = dict(snapshot.to_dict() or {})
            manifest = list(record.pop("file_manifest", []) or [])
            files = [self._read_file(case_ref, entry) for entry in manifest]
            return FundManagerCase.from_persistence(record, files)
        except FundManagerCaseStorageError:
            raise
        except Exception as exc:
            raise FundManagerCaseStorageError(
                f"Could not load Fund Manager case {case_id}."
            ) from exc

    def clear(self) -> None:
        for case_snapshot in self._collection.stream():
            case_ref = case_snapshot.reference
            record = dict(case_snapshot.to_dict() or {})
            for entry in record.get("file_manifest") or []:
                self._delete_file_chunks(case_ref.collection("files").document(str(entry["index"])))
            case_ref.delete()


def build_fund_manager_case_store(
    settings: Settings, firestore_client: Any | None = None
) -> FundManagerCaseStore:
    if settings.persistence_backend == "firestore":
        return FirestoreFundManagerCaseStore(settings, firestore_client)
    return InMemoryFundManagerCaseStore()


case_store = build_fund_manager_case_store(get_settings())
