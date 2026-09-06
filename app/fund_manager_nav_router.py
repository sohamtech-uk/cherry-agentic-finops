from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from app.config import get_settings
from app.fund_manager_cases import (
    FundManagerCase,
    FundManagerCaseStorageError,
    case_store,
)
from app.fund_manager_classification import classify_and_validate_sources
from app.fund_manager_nav_controller import (
    build_nav_readiness,
    get_case_nav_history,
    run_case_nav_reconciliation,
    run_case_nav_review,
)
from app.rate_limit import limiter

settings = get_settings()
router = APIRouter(prefix="/api/fund-manager/cases", tags=["fund-manager-nav"])
logger = logging.getLogger(__name__)


class NAVDecision(BaseModel):
    action: Literal[
        "approve_nav",
        "approve_with_exception",
        "request_evidence",
        "return_to_administrator",
        "escalate",
    ]
    note: str | None = None


class NAVExceptionIgnore(BaseModel):
    reason: str
    note: str | None = None


def _require_upload_access() -> None:
    expected = os.getenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "").strip()
    if settings.environment != "production" and not expected:
        return
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Fund Manager uploads are disabled until "
                "CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN is configured."
            ),
        )


def _case_or_404(case_id: str) -> FundManagerCase:
    try:
        case = case_store.get(case_id)
    except FundManagerCaseStorageError as exc:
        logger.exception("Could not load Fund Manager case %s", case_id)
        raise HTTPException(
            status_code=503,
            detail="The Fund Manager case store is temporarily unavailable or failed integrity "
            "verification.",
        ) from exc
    if case is None:
        raise HTTPException(status_code=404, detail=f"Fund Manager case {case_id} was not found.")
    return case


def _save_case(case: FundManagerCase) -> None:
    try:
        case_store.save(case)
    except FundManagerCaseStorageError as exc:
        logger.exception("Could not save Fund Manager case %s", case.case_id)
        raise HTTPException(
            status_code=503,
            detail="The Fund Manager case could not be stored. Retry this step without closing "
            "the page.",
        ) from exc


def _safe_file_name(value: str | None) -> str:
    candidate = Path(value or "evidence").name.strip()
    return candidate if candidate not in {"", ".", ".."} else "evidence"


def _refresh_classification(case: FundManagerCase) -> None:
    sources = classify_and_validate_sources(case.files)
    rejected_count = sum(1 for source in sources if source["validation_status"] == "rejected")
    case.classification = {
        **case.classification,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_count": len(sources),
        "unknown_count": rejected_count,
        "accepted_count": len(sources) - rejected_count,
        "rejected_count": rejected_count,
        "sources": sources,
    }


@router.get("/{case_id}/nav")
async def get_nav_workflow(case_id: str) -> dict[str, Any]:
    case = _case_or_404(case_id)
    return {
        "case_id": case.case_id,
        "fund_name": case.fund_name,
        "reporting_period": case.reporting_period,
        "as_of_date": case.as_of_date,
        "readiness": case.nav_readiness,
        "reconciliation": case.nav_reconciliation,
        "review": case.nav_review,
        "decision": case.nav_decision,
        "exception_resolutions": case.nav_exception_resolutions,
    }


@router.post("/{case_id}/nav/readiness")
@limiter.limit("1 per 5 seconds")
async def assess_nav_readiness(
    request: Request,
    response: Response,
    case_id: str,
) -> dict[str, Any]:
    _require_upload_access()
    case = _case_or_404(case_id)
    case.nav_readiness = build_nav_readiness(case)
    case.touch()
    _save_case(case)
    return case.public_view()


@router.post("/{case_id}/nav/reconcile")
@limiter.limit("1 per 5 seconds")
async def reconcile_nav_case(
    request: Request,
    response: Response,
    case_id: str,
) -> dict[str, Any]:
    _require_upload_access()
    case = _case_or_404(case_id)
    if case.nav_readiness is None:
        case.nav_readiness = build_nav_readiness(case)
    try:
        case.nav_reconciliation = run_case_nav_reconciliation(case)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    case.nav_review = None
    case.nav_decision = None
    case.touch()
    _save_case(case)
    return case.public_view()


@router.post("/{case_id}/nav/exceptions/{exception_id}/evidence")
@limiter.limit("1 per 5 seconds")
async def upload_nav_exception_evidence(
    request: Request,
    response: Response,
    case_id: str,
    exception_id: str,
    file: Annotated[UploadFile, File(description="Supporting evidence for this NAV exception")],
) -> dict[str, Any]:
    """Attach evidence to one exception and return the case to NAV readiness for re-validation."""
    _require_upload_access()
    case = _case_or_404(case_id)
    file_name = _safe_file_name(file.filename)
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"{file_name} exceeds the upload limit.")
    case.files.append((file_name, content, file.content_type))
    _refresh_classification(case)
    case.nav_exception_resolutions[exception_id] = {
        "status": "evidence_uploaded",
        "filename": file_name,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    case.nav_readiness = build_nav_readiness(case)
    case.nav_reconciliation = None
    case.nav_review = None
    case.nav_decision = None
    case.touch()
    _save_case(case)
    return case.public_view()


@router.post("/{case_id}/nav/exceptions/{exception_id}/ignore")
@limiter.limit("1 per 5 seconds")
async def ignore_nav_exception(
    request: Request,
    response: Response,
    case_id: str,
    exception_id: str,
    ignore: NAVExceptionIgnore,
) -> dict[str, Any]:
    """Record an explicit, auditable human decision to ignore one NAV exception."""
    _require_upload_access()
    case = _case_or_404(case_id)
    reason = ignore.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A reason is required to ignore an exception.")
    case.nav_exception_resolutions[exception_id] = {
        "status": "ignored",
        "reason": reason,
        "note": ignore.note,
        "recorded_at": datetime.now(UTC).isoformat(),
        "actor": "fund-manager-ui-user",
    }
    case.touch()
    _save_case(case)
    return case.public_view()


@router.post("/{case_id}/nav/review")
@limiter.limit("1 per 5 seconds")
async def review_nav_case(
    request: Request,
    response: Response,
    case_id: str,
) -> dict[str, Any]:
    _require_upload_access()
    case = _case_or_404(case_id)
    if case.nav_reconciliation is None:
        raise HTTPException(status_code=409, detail="Run NAV reconciliation before NAV review.")
    try:
        case.nav_review = await run_case_nav_review(case)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"NAV review agent could not complete: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    case.touch()
    _save_case(case)
    return case.public_view()


@router.post("/{case_id}/nav/decision")
@limiter.limit("1 per 5 seconds")
async def decide_nav_case(
    request: Request,
    response: Response,
    case_id: str,
    decision: NAVDecision,
) -> dict[str, Any]:
    _require_upload_access()
    case = _case_or_404(case_id)
    if case.nav_reconciliation is None:
        raise HTTPException(
            status_code=409,
            detail="Run NAV reconciliation before recording a NAV decision.",
        )
    if case.nav_review is None:
        raise HTTPException(
            status_code=409,
            detail="Run the agentic NAV review before recording a NAV decision.",
        )
    case.nav_decision = {
        "action": decision.action,
        "note": decision.note,
        "recorded_at": datetime.now(UTC).isoformat(),
        "actor": "fund-manager-ui-user",
        "financial_boundary": "Decision recorded only; no journal or official NAV was amended.",
    }
    case.touch()
    _save_case(case)
    return case.public_view()


@router.get("/{case_id}/nav/history")
async def nav_case_history(case_id: str) -> dict[str, Any]:
    return get_case_nav_history(_case_or_404(case_id))
