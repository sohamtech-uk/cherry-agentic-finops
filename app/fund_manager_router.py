from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile

from app.config import get_settings
from app.fund_manager_agentic import run_agentic_analysis
from app.fund_manager_classification import classify_and_validate_sources
from app.rate_limit import limiter

settings = get_settings()
router = APIRouter(prefix="/api/fund-manager", tags=["fund-manager"])

MAX_FILES = 25


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


@router.get("/health")
async def fund_manager_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "stage": "end_to_end_agentic_control_pipeline",
        "orchestration_mode": "agentic",
        "pipeline": [
            "multiple_files",
            "agent_calls_file_classification",
            "agent_reads_control_catalogue",
            "agent_determines_required_controls",
            "agent_invokes_deterministic_tools",
            "agentic_investigation",
            "human_decision",
            "fund_manager_dashboard",
        ],
        "implemented_stages": [
            "multiple_files",
            "agent_calls_file_classification",
            "agent_reads_control_catalogue",
            "agent_determines_required_controls",
            "agent_invokes_deterministic_tools",
            "agentic_investigation",
            "lineage",
        ],
        "partially_implemented_stages": {
            "control_adapters": (
                "The agent can select every recognised control, including bank-statement-to-cash "
                "and bank-statement working-file pairs. Existing deterministic adapters execute "
                "when available; unsupported controls remain adapter_pending rather than being "
                "treated as passed."
            ),
            "human_decision": (
                "The agent recommends a human action and exposes whether a decision is required; "
                "durable decision recording remains a separate workflow capability."
            ),
        },
        "recognised_source_types": [
            "nav_workbook",
            "investor_gl",
            "lp_commitments",
            "bank_statement_working_file",
            "loader_template",
            "capital_call_notice",
            "lpa",
            "side_letter",
            "bank_statement",
            "financial_statement",
            "investor_report",
            "positions",
            "trades",
            "bank_transactions",
            "cash_transactions",
        ],
        "control_boundary": (
            "The ADK Fund Manager agent classifies evidence and chooses which registered controls "
            "to invoke. Deterministic tools remain authoritative for financial calculations and "
            "reconciliations; material decisions remain human-governed."
        ),
    }


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
    """Agent-facing classification tool for a mixed evidence batch.

    The browser UI does not call this endpoint. The Fund Manager ADK flow performs classification
    internally as its first tool call before it selects any control. This endpoint remains useful
    for agent/tool integration and diagnostics.
    """

    _require_upload_access()
    items = await _read_upload_batch(files)
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
            "This is a source inventory, not a review result. No control has run yet."
        ),
    }


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
    """Run the uploaded batch through the ADK Fund Manager control-orchestration agent.

    The agent must classify the evidence first, read the closed control catalogue, choose the
    applicable controls, and invoke deterministic tools for calculations/reconciliations. The agent
    may investigate and explain tool outputs but cannot override deterministic financial results or
    silently pass a control that lacks evidence or an implementation.
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
