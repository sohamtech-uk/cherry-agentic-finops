from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.config import Settings
from app.fund_manager_cases import (
    FIRESTORE_FILE_CHUNK_BYTES,
    FirestoreFundManagerCaseStore,
    FundManagerCaseStorageError,
    InMemoryFundManagerCaseStore,
)


class FakeDocumentSnapshot:
    def __init__(self, reference: FakeDocumentReference, value: dict[str, Any] | None) -> None:
        self.reference = reference
        self.id = reference.id
        self.exists = value is not None
        self._value = value

    def to_dict(self) -> dict[str, Any] | None:
        return deepcopy(self._value)


class FakeCollectionReference:
    def __init__(self, client: FakeFirestoreClient, path: tuple[str, ...]) -> None:
        self._client = client
        self._path = path

    def document(self, document_id: str) -> FakeDocumentReference:
        return FakeDocumentReference(self._client, (*self._path, document_id))

    def stream(self) -> list[FakeDocumentSnapshot]:
        document_length = len(self._path) + 1
        paths = sorted(
            path
            for path in self._client.documents
            if len(path) == document_length and path[: len(self._path)] == self._path
        )
        return [self.document(path[-1]).get() for path in paths]


class FakeDocumentReference:
    def __init__(self, client: FakeFirestoreClient, path: tuple[str, ...]) -> None:
        self._client = client
        self._path = path
        self.id = path[-1]

    def collection(self, name: str) -> FakeCollectionReference:
        return FakeCollectionReference(self._client, (*self._path, name))

    def set(self, value: dict[str, Any]) -> None:
        self._client.documents[self._path] = deepcopy(value)

    def get(self) -> FakeDocumentSnapshot:
        return FakeDocumentSnapshot(self, self._client.documents.get(self._path))

    def delete(self) -> None:
        self._client.documents.pop(self._path, None)


class FakeFirestoreClient:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, ...], dict[str, Any]] = {}

    def collection(self, name: str) -> FakeCollectionReference:
        return FakeCollectionReference(self, (name,))


def test_memory_store_requires_explicit_save_for_mutations() -> None:
    store = InMemoryFundManagerCaseStore()
    case = store.create(
        [("positions.json", b"[]", "application/json")],
        classification={"accepted_count": 1},
    )

    case.stage = "planned"
    initially_stored = store.get(case.case_id)
    assert initially_stored is not None
    assert initially_stored.stage == "classified"

    case.touch()
    store.save(case)
    reloaded = store.get(case.case_id)
    assert reloaded is not None
    assert reloaded.stage == "planned"
    assert reloaded.revision == 2


def test_firestore_store_round_trips_case_state_and_chunked_evidence() -> None:
    client = FakeFirestoreClient()
    settings = Settings(
        CHERRY_PERSISTENCE_BACKEND="firestore",
        GOOGLE_CLOUD_PROJECT="test-project",
        CHERRY_FUND_MANAGER_FIRESTORE_COLLECTION="fund-manager-test-cases",
    )
    store = FirestoreFundManagerCaseStore(settings, client)
    content = b"e" * (FIRESTORE_FILE_CHUNK_BYTES + 37)

    case = store.create(
        [("large-evidence.pdf", content, "application/pdf")],
        classification={"accepted_count": 1, "sources": []},
        fund_name="Northstar Fund III",
    )
    case.stage = "planned"
    case.plan = {"status": "ready"}
    case.touch()
    store.save(case)

    stored_document = client.documents[("fund-manager-test-cases", case.case_id)]
    assert "files" not in stored_document
    assert stored_document["file_manifest"][0]["chunk_count"] == 2

    # A second store represents a different Cloud Run instance reading the shared database.
    reloaded = FirestoreFundManagerCaseStore(settings, client).get(case.case_id)
    assert reloaded is not None
    assert reloaded.stage == "planned"
    assert reloaded.plan == {"status": "ready"}
    assert reloaded.files == [("large-evidence.pdf", content, "application/pdf")]


def test_firestore_store_rejects_corrupt_evidence() -> None:
    client = FakeFirestoreClient()
    settings = Settings(
        CHERRY_PERSISTENCE_BACKEND="firestore",
        GOOGLE_CLOUD_PROJECT="test-project",
        CHERRY_FUND_MANAGER_FIRESTORE_COLLECTION="fund-manager-test-cases",
    )
    store = FirestoreFundManagerCaseStore(settings, client)
    case = store.create(
        [("positions.json", b"original", "application/json")],
        classification={"accepted_count": 1},
    )
    chunk_path = (
        "fund-manager-test-cases",
        case.case_id,
        "files",
        "0",
        "chunks",
        "000000",
    )
    client.documents[chunk_path]["data"] = b"tampered"

    with pytest.raises(FundManagerCaseStorageError, match="integrity verification"):
        store.get(case.case_id)
