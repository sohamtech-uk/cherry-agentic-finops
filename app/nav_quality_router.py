from __future__ import annotations

import hmac
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import ValidationError

from app.config import get_settings
from app.contract_nav import resolve_contract_rules_for_nav
from app.nav_exceptions import group_exceptions_by_root_cause
from app.nav_quality import (
    SideLetterRule,
    build_case_id,
    parse_administrator_nav_summary,
    parse_investor_level_gl_workbook,
    parse_side_letter_rules,
    report_hash,
    review_nav_quality,
    sha256_hex,
)

settings = get_settings()
router = APIRouter(prefix="/api/nav-quality", tags=["nav-quality"])


def _require_real_data_access(token: str | None) -> None:
    expected = os.getenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "").strip()
    if settings.environment != "production" and not expected:
        return
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "NAV uploads are disabled until CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN is configured."
            ),
        )
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Valid private-markets demo token required.")


def _safe_file_name(value: str | None, fallback: str) -> str:
    candidate = Path(value or fallback).name.strip()
    return candidate if candidate not in {"", ".", ".."} else fallback


@router.get("/health")
async def nav_quality_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "input_contract": [
            "nav_summary",
            "source_ledger",
            "side_letter_rules",
            "use_contract_documents",
        ],
        "input_required": {
            "nav_summary": True,
            "source_ledger": False,
            "side_letter_rules": False,
            "use_contract_documents": False,
        },
        "checks": [
            "balance_sheet_footing",
            "balance_sheet_vs_ledger",
            "nav_bridge_footing",
            "nav_independent_recalculation",
            "investor_capital_reconciliation",
            "side_letter_rule_validation",
        ],
        "exception_grouping": "root_causes ranked by impact_amount (materiality), highest first",
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
    use_contract_documents: Annotated[
        bool,
        Form(
            description=(
                "Resolve investor rules from documents already ingested through /api/contracts"
            )
        ),
    ] = False,
    x_cherry_demo_token: Annotated[
        str | None,
        Header(alias="X-Cherry-Demo-Token"),
    ] = None,
) -> dict[str, object]:
    """Run the deterministic NAV quality checks against an administrator's reported NAV summary.

    ``nav_summary`` is always required and is checked for internal footing on its own (the balance
    sheet and NAV bridge must add up). ``source_ledger`` and ``side_letter_rules`` are optional
    independent evidence. ``use_contract_documents`` instead resolves side-letter terms from the
    source-backed contract repository. When supplied, those inputs add an independent balance-sheet,
    NAV and per-investor capital check. This never posts a correction; it only reports findings, a
    recommended action and evidence for a human reviewer.
    """

    _require_real_data_access(x_cherry_demo_token)
    if use_contract_documents and side_letter_rules is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Choose either source-backed contract documents or a side_letter_rules JSON file, "
                "not both."
            ),
        )
    max_bytes = settings.max_upload_mb * 1024 * 1024

    summary_name = _safe_file_name(nav_summary.filename, "nav-summary.json")
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
        ledger_name = _safe_file_name(source_ledger.filename, "source-ledger.xlsx")
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
        rules_name = _safe_file_name(side_letter_rules.filename, "side-letter-rules.json")
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
    if use_contract_documents:
        rules = resolve_contract_rules_for_nav(summary)

    report = review_nav_quality(summary, ledger=ledger, side_letter_rules=rules)
    root_causes = group_exceptions_by_root_cause(report)
    contract_sources = [
        {
            "investor": rule.investor,
            "document_id": rule.document_id,
            "document_name": rule.document_name,
            "section_reference": rule.section_reference,
            "page_number": rule.page_number,
            "source_sha256": rule.source_sha256,
            "effective_date": rule.effective_date.isoformat() if rule.effective_date else None,
            "resolution_status": rule.resolution_status,
        }
        for rule in rules
        if rule.document_id or rule.resolution_status != "found"
    ]

    summary_hash = sha256_hex(summary_content)
    ledger_hash = sha256_hex(ledger_content) if ledger_content is not None else None
    rules_hash = sha256_hex(rules_content) if rules_content is not None else None
    resolved_rules_hash = (
        sha256_hex(
            json.dumps(
                [rule.model_dump(mode="json") for rule in rules],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if use_contract_documents
        else None
    )
    case_id = build_case_id(
        summary_hash,
        ledger_hash or "NO_LEDGER",
        rules_hash or resolved_rules_hash or "NO_RULES",
    )
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
        "contract_rule_source": (
            "source_backed_contract_documents"
            if use_contract_documents
            else "uploaded_structured_rules"
            if rules_content is not None
            else "none"
        ),
        "review": report.model_dump(mode="json"),
        "root_causes": [group.model_dump(mode="json") for group in root_causes],
        "evidence": {
            "input_sha256": {
                "nav_summary": summary_hash,
                "source_ledger": ledger_hash,
                "side_letter_rules": rules_hash,
                "resolved_contract_rules": resolved_rules_hash,
            },
            "sources": sources,
            "contract_sources": contract_sources,
            "review_sha256": report_hash(report),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "financial_boundary": (
            "This service reviews the NAV pack and recommends an action; it never posts a "
            "correcting journal entry or amends the official NAV."
        ),
    }
