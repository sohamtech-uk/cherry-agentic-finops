from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from app.config import get_settings
from app.fund_manager_classification import classify_sources

settings = get_settings()
router = APIRouter(prefix="/api/fund-manager", tags=["fund-manager"])

MAX_FILES = 25


def _require_upload_access(token: str | None) -> None:
    expected = os.getenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "").strip()
    if settings.environment != "production" and not expected:
        return
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Fund Manager uploads are disabled until CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN "
            "is configured.",
        )
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Valid private-markets demo token required.")


def _safe_file_name(value: str | None, fallback: str) -> str:
    candidate = Path(value or fallback).name.strip()
    return candidate if candidate not in {"", ".", ".."} else fallback


@router.get("/health")
async def fund_manager_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "stage": "classification",
        "pipeline": [
            "multiple_files",
            "file_classification",
            "canonical_data_room",
            "data_quality",
            "agent_determines_required_controls",
            "position_cash_trade_nav_recon",
            "deterministic_exception_engine",
            "agentic_investigation",
            "fund_manager_dashboard",
        ],
        "implemented_stages": ["multiple_files", "file_classification", "canonical_data_room"],
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
            "Classification only identifies what was uploaded; it never decides which controls "
            "should run or what a control result means. An unrecognised file is marked unknown "
            "and flagged for review, never guessed at."
        ),
    }


@router.post("/classify")
async def classify_fund_evidence(
    files: Annotated[list[UploadFile], File(description="One or more mixed evidence files")],
    fund_name: Annotated[str | None, Form(description="Optional fund/entity name")] = None,
    reporting_period: Annotated[str | None, Form(description="Optional reporting period")] = None,
    as_of_date: Annotated[str | None, Form(description="Optional as-of date, YYYY-MM-DD")] = None,
    x_cherry_demo_token: Annotated[str | None, Header(alias="X-Cherry-Demo-Token")] = None,
) -> dict[str, Any]:
    """Classify a batch of mixed evidence files into a canonical source inventory.

    This is the first stage of the Fund Manager pipeline only: identify what each file is
    (NAV workbook, investor GL, capital-call notice, LPA, side letter, bank statement, financial
    statement, positions/trades/cash JSON or CSV, ...), never what to do with it. Nothing here
    runs a control or decides a control plan. An unrecognised file is returned as unknown with a
    warning rather than guessed at.
    """

    _require_upload_access(x_cherry_demo_token)
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

    sources = classify_sources(items)
    unknown_count = sum(1 for source in sources if source["status"] != "processed")

    return {
        "fund_name": fund_name,
        "reporting_period": reporting_period,
        "as_of_date": as_of_date,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_count": len(sources),
        "unknown_count": unknown_count,
        "sources": sources,
        "control_boundary": (
            "This is a source inventory, not a review result. No control has run yet."
        ),
    }
