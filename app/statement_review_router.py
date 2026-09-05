from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from app.config import get_settings
from app.statement_tools import (
    compare_dates,
    compare_periods,
    find_entity,
    find_section,
    read_document,
)

settings = get_settings()
router = APIRouter(prefix="/api/statement-review", tags=["statement-review"])

_ALLOWED_SUFFIXES = (".pdf", ".txt", ".md")


def _require_upload_access(token: str | None) -> None:
    expected = os.getenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "").strip()
    if settings.environment != "production" and not expected:
        return
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Statement-review uploads are disabled until CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN "
                "is configured."
            ),
        )
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Valid private-markets demo token required.")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_file_name(value: str | None, fallback: str) -> str:
    candidate = Path(value or fallback).name.strip()
    return candidate if candidate not in {"", ".", ".."} else fallback


async def _read_upload(
    upload: UploadFile, field: str, fallback_name: str, max_bytes: int
) -> tuple[str, bytes]:
    file_name = _safe_file_name(upload.filename, fallback_name)
    content = await upload.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{field} exceeds the {settings.max_upload_mb} MB upload limit.",
        )
    if not file_name.lower().endswith(_ALLOWED_SUFFIXES):
        raise HTTPException(status_code=415, detail=f"{field} must be a PDF, TXT or Markdown file.")
    return file_name, content


@router.get("/health")
async def statement_review_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "input_contract": ["current_document", "prior_document", "section_heading", "entity_name"],
        "input_required": {
            "current_document": True,
            "prior_document": False,
            "section_heading": False,
            "entity_name": False,
        },
        "accepted_file_formats": ["pdf", "txt", "md"],
        "checks": [
            "read_document",
            "find_section",
            "find_entity",
            "compare_periods",
            "compare_dates",
        ],
        "control_boundary": (
            "Section/entity location and period/date diffing are deterministic text operations; "
            "whether a result is a real defect (a stale disclosure, a misclassified subsequent "
            "event) requires human or agent judgement. This service never amends a statement."
        ),
    }


@router.post("/compare")
async def compare_statement(
    current_document: Annotated[
        UploadFile,
        File(description="Current-period financial statement (PDF, TXT or Markdown)"),
    ],
    prior_document: Annotated[
        UploadFile | None,
        File(description="Optional prior-period financial statement, for period/date diffing"),
    ] = None,
    section_heading: Annotated[
        str | None,
        Form(description='Optional section heading to locate, e.g. "Subsequent Events"'),
    ] = None,
    entity_name: Annotated[
        str | None,
        Form(description="Optional entity to search for, e.g. a portfolio company name"),
    ] = None,
    x_cherry_demo_token: Annotated[
        str | None,
        Header(alias="X-Cherry-Demo-Token"),
    ] = None,
) -> dict[str, Any]:
    """Run the deterministic statement-review primitives against one or two uploaded documents.

    ``current_document`` is always required. Supplying ``section_heading`` or ``entity_name`` adds
    a targeted lookup within it. Supplying ``prior_document`` additionally runs a line-level diff
    and a date-comparison against the current document. This never amends a statement; it only
    returns the located text, the diff and evidence for a human or agent to interpret.
    """

    _require_upload_access(x_cherry_demo_token)
    max_bytes = settings.max_upload_mb * 1024 * 1024

    current_name, current_content = await _read_upload(
        current_document, "current_document", "current-statement.txt", max_bytes
    )

    try:
        result: dict[str, Any] = {"current_document": read_document(current_content, current_name)}
        if section_heading:
            result["section"] = find_section(current_content, current_name, section_heading)
        if entity_name:
            result["entity"] = find_entity(current_content, current_name, entity_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"Could not read {current_name!r}: {exc}"
        ) from exc

    prior_name: str | None = None
    prior_content: bytes | None = None
    if prior_document is not None and (prior_document.filename or "").strip():
        prior_name, prior_content = await _read_upload(
            prior_document, "prior_document", "prior-statement.txt", max_bytes
        )
        try:
            result["period_diff"] = compare_periods(
                current_content, current_name, prior_content, prior_name
            )
            result["date_diff"] = compare_dates(
                current_content, current_name, prior_content, prior_name
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Could not read {prior_name!r}: {exc}"
            ) from exc

    sources: list[dict[str, str]] = [
        {
            "kind": "current_document",
            "file_name": current_name,
            "sha256": _sha256(current_content),
        }
    ]
    if prior_content is not None and prior_name is not None:
        sources.append(
            {
                "kind": "prior_document",
                "file_name": prior_name,
                "sha256": _sha256(prior_content),
            }
        )

    result["evidence"] = {"sources": sources, "generated_at": datetime.now(UTC).isoformat()}
    result["control_boundary"] = (
        "Findings are deterministic text matches and diffs; a human or agent must judge whether "
        "any result is a genuine defect before a statement is returned to the administrator."
    )
    return result
