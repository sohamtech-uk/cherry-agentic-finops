from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import get_settings
from app.container import get_engine
from app.contracts import get_contract_repository

settings = get_settings()
router = APIRouter(prefix="/api/session", tags=["session"])


@router.post("/clear-memory")
async def clear_memory() -> dict[str, Any]:
    """Clear only ephemeral server state; never require the upload token for a reset.

    Private-markets and Ylookup upload endpoints process uploaded bytes request-by-request and do
    not retain the raw PDF/XLSX/JSON payloads. The browser clears selected files and rendered
    results locally. On memory-backed deployments this endpoint also clears ephemeral workflow and
    parsed contract state. Persistent backends such as Firestore are deliberately left untouched so
    the reset action can never become an unauthenticated database-delete operation.
    """

    if settings.persistence_backend != "memory":
        return {
            "status": "browser_reset_only",
            "persistence_backend": settings.persistence_backend,
            "cleared_workflow_records": 0,
            "cleared_contract_documents": 0,
            "persistent_records_deleted": False,
            "raw_uploads_retained": False,
            "message": (
                "Browser-selected files and rendered analysis can be cleared without a token. "
                "Persistent server workflow records were not deleted."
            ),
        }

    engine = get_engine()
    cleared_workflow_records = len(engine.list())
    engine.repository.clear()
    cleared_contract_documents = get_contract_repository().clear()
    return {
        "status": "cleared",
        "persistence_backend": settings.persistence_backend,
        "cleared_workflow_records": cleared_workflow_records,
        "cleared_contract_documents": cleared_contract_documents,
        "persistent_records_deleted": False,
        "raw_uploads_retained": False,
        "message": (
            "Ephemeral workflow and parsed contract memory were cleared. Raw private-markets "
            "uploads are not retained by the evidence-analysis endpoints."
        ),
    }
