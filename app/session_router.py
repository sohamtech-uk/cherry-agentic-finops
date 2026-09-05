from __future__ import annotations

import hmac
import os
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.container import get_engine
from app.contracts import get_contract_repository

settings = get_settings()
router = APIRouter(prefix="/api/session", tags=["session"])


def _require_clear_access(token: str | None) -> None:
    expected = os.getenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "").strip()
    if settings.environment != "production" and not expected:
        return
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Memory clearing is disabled until the private-markets demo token is configured."
            ),
        )
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Valid private-markets demo token required.")


@router.post("/clear-memory")
async def clear_memory(
    x_cherry_demo_token: Annotated[
        str | None,
        Header(alias="X-Cherry-Demo-Token"),
    ] = None,
) -> dict[str, Any]:
    """Clear ephemeral server workflow state for the hackathon memory deployment.

    Private-markets and Ylookup upload endpoints process uploaded bytes request-by-request.
    They do not persist the raw PDF/XLSX payloads in the in-memory workflow repository. This
    endpoint clears any workflow records that are present in that repository. Persistent backends
    such as Firestore are deliberately excluded so this button can never become a remote
    database-delete operation.
    """

    _require_clear_access(x_cherry_demo_token)
    if settings.persistence_backend != "memory":
        raise HTTPException(
            status_code=409,
            detail=(
                "Server persistence is not memory-backed. The Clear memory action is intentionally "
                "restricted to ephemeral memory deployments and will not delete Firestore data."
            ),
        )

    engine = get_engine()
    cleared_workflow_records = len(engine.list())
    engine.repository.clear()
    cleared_contract_documents = get_contract_repository().clear()
    return {
        "status": "cleared",
        "persistence_backend": settings.persistence_backend,
        "cleared_workflow_records": cleared_workflow_records,
        "cleared_contract_documents": cleared_contract_documents,
        "raw_uploads_retained": False,
        "message": (
            "Ephemeral workflow and parsed contract memory were cleared. Raw private-markets "
            "uploads are not retained by the evidence-analysis endpoints."
        ),
    }
