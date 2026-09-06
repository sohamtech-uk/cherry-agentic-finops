from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import get_settings
from app.fund_manager_cases import FundManagerCase, case_store
from app.fund_manager_nav_controller import (
    build_nav_readiness,
    get_case_nav_history,
    run_case_nav_reconciliation,
    run_case_nav_review,
)
from app.rate_limit import limiter

settings = get_settings()
router = APIRouter(prefix="/api/fund-manager/cases", tags=["fund-manager-nav"])


class NAVDecision(BaseModel):
    action: Literal[
        "approve_nav",
        "approve_with_exception",
        "request_evidence",
        "return_to_administrator",
        "escalate",
    ]
    note: str | None = None


def _require_upload_access() -> None:
    expected = os.getenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "").strip()
    if settings.environment != "production" and not expected:
        return
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Fund Manager uploads are disabled until CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN is configured.",
        )


def _case_or_404(case_id: str) -> FundManagerCase:
    case = case_store.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Fund Manager case {case_id} was not found.")
    return case


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
    }


@router.post("/{case_id}/nav/readiness")
@limiter.limit("1 per 5 seconds")
async def assess_nav_readiness(
    request: Request,
    response: Response,
    case_id: str,
) -> dict[str, Any]:
    """Assess NAV workflow readiness using evidence already stored on the Fund Manager case."""

    _require_upload_access()
    case = _case_or_404(case_id)
    case.nav_readiness = build_nav_readiness(case)
    case.touch()
    return case.public_view()


@router.post("/{case_id}/nav/reconcile")
@limiter.limit("1 per 5 seconds")
async def reconcile_nav_case(
    request: Request,
    response: Response,
    case_id: str,
) -> dict[str, Any]:
    """Run the existing deterministic NAV Quality Controller after explicit user approval."""

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
    return case.public_view()


@router.post("/{case_id}/nav/review")
@limiter.limit("1 per 5 seconds")
async def review_nav_case(
    request: Request,
    response: Response,
    case_id: str,
) -> dict[str, Any]:
    """Ask the existing Fund Manager investigation agent to review deterministic NAV findings."""

    _require_upload_access()
    case = _case_or_404(case_id)
    if case.nav_reconciliation is None:
        raise HTTPException(status_code=409, detail="Run NAV reconciliation before NAV review.")
    try:
        case.nav_review = await run_case_nav_review(case)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"NAV review agent could not complete: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    case.touch()
    return case.public_view()


@router.post("/{case_id}/nav/decision")
@limiter.limit("1 per 5 seconds")
async def decide_nav_case(
    request: Request,
    response: Response,
    case_id: str,
    decision: NAVDecision,
) -> dict[str, Any]:
    """Record a NAV-specific human decision without amending the official NAV."""

    _require_upload_access()
    case = _case_or_404(case_id)
    if case.nav_reconciliation is None:
        raise HTTPException(status_code=409, detail="Run NAV reconciliation before recording a NAV decision.")
    case.nav_decision = {
        "action": decision.action,
        "note": decision.note,
        "recorded_at": datetime.now(UTC).isoformat(),
        "actor": "fund-manager-ui-user",
        "financial_boundary": "Decision recorded only; no journal or official NAV was amended.",
    }
    case.touch()
    return case.public_view()


@router.get("/{case_id}/nav/history")
async def nav_case_history(case_id: str) -> dict[str, Any]:
    """Return the existing NAV review iteration history for this case's fund and period."""

    return get_case_nav_history(_case_or_404(case_id))
