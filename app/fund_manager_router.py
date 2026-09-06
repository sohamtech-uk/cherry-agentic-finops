from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from app.config import get_settings
from app.fund_manager_agentic import run_agentic_analysis
from app.fund_manager_cases import FundManagerCase, case_store
from app.fund_manager_classification import classify_and_validate_sources
from app.fund_manager_stages import (
    execute_case_controls,
    investigate_case_execution,
    plan_case_controls,
)
from app.rate_limit import limiter

settings = get_settings()
router = APIRouter(prefix="/api/fund-manager", tags=["fund-manager"])

MAX_FILES = 25


class FundManagerDecision(BaseModel):
    action: Literal[
        "accept_and_close",
        "request_evidence",
        "assign_and_monitor",
        "escalate_immediately",
    ]
    note: str | None = None


def _require_upload_access() -> None:
    """Require the deployment secret server-side without exposing it to the browser."""
    expected = os.getenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "").strip()
    if settings.environment != "production" and not expected:
        return
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Fund Manager uploads are disabled until CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN "
            "is configured.",
        )


def _safe_file_name(value: str | None, fallback: str) -> str:
    candidate = Path(value or fallback).name.strip()
    return candidate if candidate not in {"", ".", ".."} else fallback


async def _read_upload_batch(files: list[UploadFile]) -> list[tuple[str, bytes, str | None]]:
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required.")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"Maximum {MAX_FILES} files per batch.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    items: list[tuple[str, bytes, str | None]] = []
    for upload in files:
        file_name = _safe_file_name(upload.filename, "evidence")
        content = await upload.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{file_name} exceeds the {settings.max_upload_mb} MB upload limit.",
            )
        items.append((file_name, content, upload.content_type))
    return items


def _case_or_404(case_id: str) -> FundManagerCase:
    case = case_store.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Fund Manager case {case_id} was not found.")
    return case


def _require_stage(case: FundManagerCase, allowed: set[str]) -> None:
    if case.stage not in allowed:
        expected = ", ".join(sorted(allowed))
        raise HTTPException(
            status_code=409,
            detail=(
                f"Case {case.case_id} is at stage {case.stage}; this action requires "
                f"stage {expected}."
            ),
        )


def _classification_report(
    items: list[tuple[str, bytes, str | None]],
    *,
    fund_name: str | None = None,
    reporting_period: str | None = None,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    sources = classify_and_validate_sources(items)
    rejected_count = sum(1 for source in sources if source["validation_status"] == "rejected")
    return {
        "fund_name": fund_name,
        "reporting_period": reporting_period,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_count": len(sources),
        "unknown_count": rejected_count,
        "accepted_count": len(sources) - rejected_count,
        "rejected_count": rejected_count,
        "sources": sources,
        "control_boundary": (
            "This is a source inventory, not a review result. No financial control has run yet."
        ),
    }


def _reset_case_after_new_evidence(case: FundManagerCase) -> None:
    """Invalidate results that may have depended on the previous evidence set."""
    case.stage = "classified"
    case.plan = None
    case.execution = None
    case.investigation = None
    case.decision = None
    case.nav_readiness = None
    case.nav_reconciliation = None
    case.nav_review = None
    case.nav_decision = None


@router.get("/health")
async def fund_manager_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "stage": "staged_agentic_control_pipeline",
        "orchestration_mode": "agentic",
        "pipeline": [
            "upload_and_classify",
            "human_continue_to_control_planning",
            "agent_determines_required_controls",
            "human_approves_control_execution",
            "agent_invokes_deterministic_tools",
            "human_continue_to_investigation",
            "agentic_investigation",
            "human_decision",
        ],
        "implemented_stages": [
            "case_creation",
            "file_classification",
            "incremental_case_evidence",
            "agent_control_planning",
            "deterministic_control_execution",
            "agentic_investigation",
            "human_decision_recording",
        ],
        "case_storage": "process_local",
        "control_boundary": (
            "The Fund Manager agent plans controls and investigates results. Deterministic tools "
            "remain authoritative for calculations and reconciliations. The UI requires explicit "
            "human confirmation before execution and before recording the final decision."
        ),
    }


@router.post("/cases")
@limiter.limit("1 per 5 seconds")
async def create_fund_manager_case(
    request: Request,
    response: Response,
    files: Annotated[list[UploadFile], File(description="One or more mixed evidence files")],
    fund_name: Annotated[str | None, Form(description="Optional fund/entity name")] = None,
    reporting_period: Annotated[str | None, Form(description="Optional reporting period")] = None,
    as_of_date: Annotated[str | None, Form(description="Optional as-of date, YYYY-MM-DD")] = None,
) -> dict[str, Any]:
    """Create a case and perform classification only. No control or LLM analysis runs here."""

    _require_upload_access()
    items = await _read_upload_batch(files)
    classification = _classification_report(
        items,
        fund_name=fund_name,
        reporting_period=reporting_period,
        as_of_date=as_of_date,
    )
    case = case_store.create(
        items,
        classification=classification,
        fund_name=fund_name,
        reporting_period=reporting_period,
        as_of_date=as_of_date,
    )
    return case.public_view()


@router.post("/cases/{case_id}/evidence")
@limiter.limit("1 per 5 seconds")
async def append_fund_manager_evidence(
    request: Request,
    response: Response,
    case_id: str,
    files: Annotated[list[UploadFile], File(description="Only newly added evidence files")],
) -> dict[str, Any]:
    """Append only newly selected evidence to an existing case and reclassify the case.

    Existing browser-held files must not be resubmitted. New evidence invalidates downstream
    general and NAV results because those results were produced from the previous evidence set.
    """

    _require_upload_access()
    case = _case_or_404(case_id)
    new_items = await _read_upload_batch(files)
    if len(case.files) + len(new_items) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"Maximum {MAX_FILES} files per case.")

    existing_names = {name for name, _, _ in case.files}
    duplicate_names = sorted(name for name, _, _ in new_items if name in existing_names)
    if duplicate_names:
        raise HTTPException(
            status_code=409,
            detail=(
                "These filenames already exist in the case: " + ", ".join(duplicate_names) +
                ". Upload only new evidence; use the exception-specific upload when replacing or "
                "supporting an exception."
            ),
        )

    case.files.extend(new_items)
    case.classification = _classification_report(
        case.files,
        fund_name=case.fund_name,
        reporting_period=case.reporting_period,
        as_of_date=case.as_of_date,
    )
    _reset_case_after_new_evidence(case)
    case.touch()
    return case.public_view()


@router.get("/cases/{case_id}")
async def get_fund_manager_case(case_id: str) -> dict[str, Any]:
    """Return the staged review state without returning uploaded file bytes."""

    return _case_or_404(case_id).public_view()


@router.post("/cases/{case_id}/plan")
@limiter.limit("1 per 5 seconds")
async def plan_fund_manager_case(
    request: Request,
    response: Response,
    case_id: str,
) -> dict[str, Any]:
    """Ask the ADK planning agent which registered controls should run; execute nothing."""

    _require_upload_access()
    case = _case_or_404(case_id)
    _require_stage(case, {"classified"})
    try:
        case.plan = await plan_case_controls(
            case.classification,
            fund_name=case.fund_name,
            reporting_period=case.reporting_period,
            as_of_date=case.as_of_date,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Fund Manager planning agent could not complete: {exc}",
        ) from exc
    case.stage = "planned"
    case.touch()
    return case.public_view()


@router.post("/cases/{case_id}/execute")
@limiter.limit("1 per 5 seconds")
async def execute_fund_manager_case(
    request: Request,
    response: Response,
    case_id: str,
) -> dict[str, Any]:
    """Execute only controls approved by advancing a planned case to this endpoint."""

    _require_upload_access()
    case = _case_or_404(case_id)
    _require_stage(case, {"planned"})
    if case.plan is None:
        raise HTTPException(status_code=409, detail="The case does not contain a control plan.")
    try:
        case.execution = await execute_case_controls(
            case.files,
            case.classification,
            case.plan,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Fund Manager execution agent could not complete: {exc}",
        ) from exc
    case.stage = "executed"
    case.touch()
    return case.public_view()


@router.post("/cases/{case_id}/investigate")
@limiter.limit("1 per 5 seconds")
async def investigate_fund_manager_case(
    request: Request,
    response: Response,
    case_id: str,
) -> dict[str, Any]:
    """Ask the agent to explain completed deterministic control results without changing them."""

    _require_upload_access()
    case = _case_or_404(case_id)
    _require_stage(case, {"executed"})
    if case.execution is None:
        raise HTTPException(status_code=409, detail="The case does not contain execution results.")
    try:
        case.investigation = await investigate_case_execution(case.execution)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Fund Manager investigation agent could not complete: {exc}",
        ) from exc
    case.stage = "investigated"
    case.touch()
    return case.public_view()


@router.post("/cases/{case_id}/decision")
@limiter.limit("1 per 5 seconds")
async def decide_fund_manager_case(
    request: Request,
    response: Response,
    case_id: str,
    decision: FundManagerDecision,
) -> dict[str, Any]:
    """Record the explicit human decision that closes or routes the staged review."""

    _require_upload_access()
    case = _case_or_404(case_id)
    _require_stage(case, {"executed", "investigated"})
    case.decision = {
        "action": decision.action,
        "note": decision.note,
        "recorded_at": datetime.now(UTC).isoformat(),
        "actor": "fund-manager-ui-user",
    }
    case.stage = "decided"
    case.touch()
    return case.public_view()


@router.post("/classify")
@limiter.limit("1 per 5 seconds")
async def classify_fund_evidence(
    request: Request,
    response: Response,
    files: Annotated[list[UploadFile], File(description="One or more mixed evidence files")],
    fund_name: Annotated[str | None, Form(description="Optional fund/entity name")] = None,
    reporting_period: Annotated[str | None, Form(description="Optional reporting period")] = None,
    as_of_date: Annotated[str | None, Form(description="Optional as-of date, YYYY-MM-DD")] = None,
) -> dict[str, Any]:
    """Compatibility/diagnostic classification endpoint without case creation."""

    _require_upload_access()
    items = await _read_upload_batch(files)
    return _classification_report(
        items,
        fund_name=fund_name,
        reporting_period=reporting_period,
        as_of_date=as_of_date,
    )


@router.post("/analyse")
@limiter.limit("1 per 5 seconds")
async def analyse_fund_evidence(
    request: Request,
    response: Response,
    files: Annotated[list[UploadFile], File(description="One or more mixed evidence files")],
    fund_name: Annotated[str | None, Form(description="Optional fund/entity name")] = None,
    reporting_period: Annotated[str | None, Form(description="Optional reporting period")] = None,
    as_of_date: Annotated[str | None, Form(description="Optional as-of date, YYYY-MM-DD")] = None,
) -> dict[str, Any]:
    """Backward-compatible one-shot agentic analysis endpoint.

    The Fund Manager browser UI uses the staged case endpoints instead.
    """

    _require_upload_access()
    items = await _read_upload_batch(files)
    try:
        result = await run_agentic_analysis(
            items,
            fund_name=fund_name,
            reporting_period=reporting_period,
            as_of_date=as_of_date,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Fund Manager agent could not complete the control review: {exc}",
        ) from exc

    return {
        "fund_name": fund_name,
        "reporting_period": reporting_period,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(UTC).isoformat(),
        **result,
    }
