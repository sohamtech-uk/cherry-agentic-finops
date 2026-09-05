from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import ValidationError

from app.config import get_settings
from app.nav_quality import (
    NAVReviewReport,
    SideLetterRule,
    parse_administrator_nav_summary,
    parse_investor_level_gl_workbook,
    parse_side_letter_rules,
    review_nav_quality,
)

settings = get_settings()
router = APIRouter(prefix="/api/nav-quality", tags=["nav-quality"])


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _case_id(*hashes: str) -> str:
    material = "|".join(hashes).encode("utf-8")
    return f"NAV-{_sha256(material)[:12].upper()}"


def _report_hash(report: NAVReviewReport) -> str:
    payload = json.dumps(
        report.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256(payload)


@router.get("/health")
async def nav_quality_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "input_contract": ["nav_summary", "source_ledger", "side_letter_rules"],
        "input_required": {
            "nav_summary": True,
            "source_ledger": False,
            "side_letter_rules": False,
        },
        "checks": [
            "balance_sheet_footing",
            "balance_sheet_vs_ledger",
            "nav_bridge_footing",
            "nav_independent_recalculation",
            "investor_capital_reconciliation",
            "side_letter_rule_validation",
        ],
        "financial_boundary": (
            "Decision support only; this service never posts a journal entry or amends the "
            "official NAV."
        ),
    }


@router.post("/review")
async def review_nav_pack(
    nav_summary: Annotated[
        UploadFile,
        File(description="Administrator's reported NAV summary (.json)"),
    ],
    source_ledger: Annotated[
        UploadFile | None,
        File(
            description="Optional investor-level GL export (.xlsx) to independently verify against"
        ),
    ] = None,
    side_letter_rules: Annotated[
        UploadFile | None,
        File(description="Optional structured side-letter rules (.json)"),
    ] = None,
) -> dict[str, object]:
    """Run the deterministic NAV quality checks against an administrator's reported NAV summary.

    ``nav_summary`` is always required and is checked for internal footing on its own (the balance
    sheet and NAV bridge must add up). ``source_ledger`` and ``side_letter_rules`` are optional
    independent evidence: when supplied, the reported figures are additionally checked against an
    independently recomputed balance sheet, NAV and per-investor capital account. This never posts
    a correction; it only reports findings, a recommended action and evidence for a human reviewer.
    """

    max_bytes = settings.max_upload_mb * 1024 * 1024

    summary_name = nav_summary.filename or "nav-summary.json"
    summary_content = await nav_summary.read()
    if len(summary_content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"NAV summary exceeds the {settings.max_upload_mb} MB upload limit.",
        )
    if not summary_name.lower().endswith(".json"):
        raise HTTPException(status_code=415, detail="nav_summary must be a .json file.")

    ledger_name: str | None = None
    ledger_content: bytes | None = None
    if source_ledger is not None and (source_ledger.filename or "").strip():
        ledger_name = source_ledger.filename or "source-ledger.xlsx"
        ledger_content = await source_ledger.read()
        if len(ledger_content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Source ledger exceeds the {settings.max_upload_mb} MB upload limit.",
            )
        if not ledger_name.lower().endswith(".xlsx"):
            raise HTTPException(status_code=415, detail="source_ledger must be an .xlsx workbook.")

    rules_name: str | None = None
    rules_content: bytes | None = None
    if side_letter_rules is not None and (side_letter_rules.filename or "").strip():
        rules_name = side_letter_rules.filename or "side-letter-rules.json"
        rules_content = await side_letter_rules.read()
        if len(rules_content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Side-letter rules exceed the {settings.max_upload_mb} MB upload limit.",
            )
        if not rules_name.lower().endswith(".json"):
            raise HTTPException(status_code=415, detail="side_letter_rules must be a .json file.")

    try:
        summary = parse_administrator_nav_summary(summary_content)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid administrator NAV summary: {exc}"
        ) from exc

    ledger = None
    if ledger_content is not None:
        try:
            ledger = parse_investor_level_gl_workbook(ledger_content)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid source ledger {ledger_name!r}: {exc}"
            ) from exc

    rules: list[SideLetterRule] = []
    if rules_content is not None:
        try:
            rules = parse_side_letter_rules(rules_content)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid side-letter rules {rules_name!r}: {exc}"
            ) from exc

    report = review_nav_quality(summary, ledger=ledger, side_letter_rules=rules)

    summary_hash = _sha256(summary_content)
    ledger_hash = _sha256(ledger_content) if ledger_content is not None else None
    rules_hash = _sha256(rules_content) if rules_content is not None else None
    case_id = _case_id(summary_hash, ledger_hash or "NO_LEDGER", rules_hash or "NO_RULES")
    sources: list[dict[str, str | None]] = [
        {"kind": "nav_summary", "file_name": summary_name, "sha256": summary_hash}
    ]
    if ledger_content is not None:
        sources.append({"kind": "source_ledger", "file_name": ledger_name, "sha256": ledger_hash})
    if rules_content is not None:
        sources.append({"kind": "side_letter_rules", "file_name": rules_name, "sha256": rules_hash})

    return {
        "case_id": case_id,
        "legal_entity": summary.legal_entity,
        "ledger_supplied": ledger is not None,
        "side_letter_rules_supplied": bool(rules),
        "review": report.model_dump(mode="json"),
        "evidence": {
            "input_sha256": {
                "nav_summary": summary_hash,
                "source_ledger": ledger_hash,
                "side_letter_rules": rules_hash,
            },
            "sources": sources,
            "review_sha256": _report_hash(report),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "financial_boundary": (
            "This service reviews the NAV pack and recommends an action; it never posts a "
            "correcting journal entry or amends the official NAV."
        ),
    }
