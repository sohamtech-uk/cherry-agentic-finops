from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import ValidationError

from app.config import get_settings
from app.fundops_studio import FundOpsStudioConnector, FundOpsStudioUnavailable
from app.private_markets import (
    FindingSeverity,
    FundCashTransaction,
    GeminiCapitalCallExtractor,
    GeminiPrivateMarketsUnavailable,
    PrivateMarketsAction,
    PrivateMarketsAnalysis,
    PrivateMarketsDataset,
    WorkItemPriority,
    parse_commitment_workbook,
)
from app.private_markets_io import parse_cash_json
from app.private_markets_strict import analyse_private_markets_case_strict

settings = get_settings()
extractor = GeminiCapitalCallExtractor(settings)
studio = FundOpsStudioConnector(settings)
router = APIRouter(prefix="/api/private-markets", tags=["private-markets-integration"])

MAX_PDF_FILES = 25
MAX_EXCEL_FILES = 20
NO_JSON_HASH = "NO_CASH_JSON"


def _require_real_data_access(token: str | None) -> None:
    expected = os.getenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "").strip()
    if settings.environment != "production" and not expected:
        return
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Real private-markets uploads are disabled until "
                "CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN is configured."
            ),
        )
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Valid private-markets demo token required.")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _analysis_hash(analysis: PrivateMarketsAnalysis) -> str:
    payload = json.dumps(
        analysis.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(payload)


def _case_id(*hashes: str) -> str:
    material = "|".join(hashes).encode("utf-8")
    return f"PM-{_sha256(material)[:12].upper()}"


def _bundle_hash(items: list[tuple[str, bytes]]) -> str:
    manifest = [
        {"file_name": file_name, "sha256": _sha256(content)} for file_name, content in items
    ]
    material = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256(material)


def _merge_datasets(datasets: list[PrivateMarketsDataset]) -> PrivateMarketsDataset:
    return PrivateMarketsDataset(
        commitments=[item for dataset in datasets for item in dataset.commitments],
        approved_bank_details=[
            item for dataset in datasets for item in dataset.approved_bank_details
        ],
    )


def _mark_cash_evidence_pending(analysis: PrivateMarketsAnalysis) -> None:
    """Distinguish an omitted cash feed from a verified missing receipt."""

    for finding in analysis.findings:
        if finding.code != "cash.missing":
            continue
        finding.code = "cash.evidence_not_supplied"
        finding.severity = FindingSeverity.WARNING
        finding.title = "Cash evidence not supplied"
        finding.detail = (
            "PDF and Excel controls were completed without a cash/bank export. "
            "Attach cash evidence later to complete receipt reconciliation."
        )
        finding.expected = None
        finding.observed = None

    for work_item in analysis.work_items:
        if work_item.code != "resolve_cash_shortfall":
            continue
        work_item.code = "attach_cash_evidence"
        work_item.priority = WorkItemPriority.NORMAL
        work_item.title = "Attach fund cash evidence"
        work_item.instruction = (
            "Add a JSON cash/bank export when available. Document and ledger analysis is complete; "
            "cash reconciliation remains pending."
        )

    analysis.action = PrivateMarketsAction.REQUEST_EVIDENCE
    analysis.controls_summary = (
        f"{analysis.controls_passed} controls passed; cash reconciliation is pending evidence."
    )


async def _agent_studio_result(payload: dict[str, Any]) -> dict[str, Any]:
    if not studio.configured:
        return {
            "status": "not_configured",
            "message": "Cherry strict controls completed; Agent Studio enrichment was skipped.",
        }
    try:
        result = await studio.analyse_capital_call_case(payload)
        return {"status": "completed", **result}
    except FundOpsStudioUnavailable:
        return {
            "status": "unavailable",
            "message": (
                "Cherry strict controls completed; Agent Studio was temporarily unavailable."
            ),
        }


@router.get("/integration/health")
async def integration_health() -> dict[str, Any]:
    response: dict[str, Any] = {
        "status": "ok",
        "input_contract": ["pdf", "excel", "json"],
        "input_required": {"pdf": True, "excel": True, "json": False},
        "input_multiplicity": {"pdf": "many", "excel": "many", "json": "zero_or_one"},
        "max_pdf_files": MAX_PDF_FILES,
        "max_excel_files": MAX_EXCEL_FILES,
        "fundops_studio_configured": studio.configured,
        "financial_boundary": (
            "Cherry retains deterministic control authority; no payment initiation."
        ),
    }
    if not studio.configured:
        response["fundops_studio"] = {"status": "not_configured"}
        return response
    try:
        response["fundops_studio"] = await studio.health()
    except FundOpsStudioUnavailable:
        response["fundops_studio"] = {"status": "unavailable"}
    return response


@router.post("/analyse-integrated")
async def analyse_integrated_private_markets_case(
    capital_call: Annotated[
        list[UploadFile],
        File(description="One or more capital-call notice PDFs"),
    ],
    commitments: Annotated[
        list[UploadFile],
        File(description="One or more LP commitment/control workbooks (.xlsx)"),
    ],
    fund_json: Annotated[
        UploadFile | None,
        File(description="Optional fund cash/bank transactions (.json)"),
    ] = None,
    as_of_date: Annotated[
        str | None,
        Form(description="Optional YYYY-MM-DD control date."),
    ] = None,
    x_cherry_demo_token: Annotated[
        str | None,
        Header(alias="X-Cherry-Demo-Token"),
    ] = None,
) -> dict[str, object]:
    """Run a batch private-markets workflow with optional cash evidence.

    Every PDF becomes an independently governed case. All supplied commitment/control workbooks are
    parsed and merged into one supporting dataset. When a JSON cash feed is supplied it is shared
    across the batch; when it is omitted Cherry still extracts and validates the notices and ledger
    evidence, while cash-dependent controls remain unresolved and request supporting evidence rather
    than blocking the upload itself. Cherry remains the financial control authority.
    """

    _require_real_data_access(x_cherry_demo_token)

    if not capital_call:
        raise HTTPException(status_code=422, detail="At least one capital-call PDF is required.")
    if not commitments:
        raise HTTPException(status_code=422, detail="At least one .xlsx workbook is required.")
    if len(capital_call) > MAX_PDF_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"A maximum of {MAX_PDF_FILES} PDF files can be processed in one batch.",
        )
    if len(commitments) > MAX_EXCEL_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"A maximum of {MAX_EXCEL_FILES} Excel files can be processed in one batch.",
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    pdf_items: list[tuple[str, bytes]] = []
    workbook_items: list[tuple[str, bytes]] = []

    for upload in capital_call:
        file_name = upload.filename or "capital-call.pdf"
        content = await upload.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"PDF {file_name!r} exceeds the {settings.max_upload_mb} MB per-file limit."
                ),
            )
        is_pdf_content_type = (upload.content_type or "").lower() == "application/pdf"
        if not is_pdf_content_type and not file_name.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail=f"{file_name!r} must be a PDF document.")
        pdf_items.append((file_name, content))

    for upload in commitments:
        file_name = upload.filename or "commitments.xlsx"
        content = await upload.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Excel file {file_name!r} exceeds the {settings.max_upload_mb} MB "
                    "per-file limit."
                ),
            )
        if not file_name.lower().endswith(".xlsx"):
            raise HTTPException(status_code=415, detail=f"{file_name!r} must be an .xlsx workbook.")
        workbook_items.append((file_name, content))

    json_file_name: str | None = None
    json_content: bytes | None = None
    transactions: list[FundCashTransaction] = []
    if fund_json is not None:
        json_file_name = fund_json.filename or "fund-cash.json"
        json_content = await fund_json.read()
        if len(json_content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"JSON input exceeds the {settings.max_upload_mb} MB upload limit.",
            )
        if not json_file_name.lower().endswith(".json"):
            raise HTTPException(status_code=415, detail="fund_json must be a .json file.")
        try:
            transactions = parse_cash_json(json_content)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid JSON supporting data: {exc}",
            ) from exc

    parsed_as_of: date | None = None
    if as_of_date:
        try:
            parsed_as_of = date.fromisoformat(as_of_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="as_of_date must be YYYY-MM-DD.") from exc

    datasets: list[PrivateMarketsDataset] = []
    for file_name, content in workbook_items:
        try:
            datasets.append(parse_commitment_workbook(content))
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid commitment workbook {file_name!r}: {exc}",
            ) from exc

    dataset = _merge_datasets(datasets)
    excel_bundle_hash = _bundle_hash(workbook_items)
    json_hash = _sha256(json_content) if json_content is not None else NO_JSON_HASH
    sources_excel = [
        {"kind": "excel", "file_name": file_name, "sha256": _sha256(content)}
        for file_name, content in workbook_items
    ]
    json_source = (
        {"kind": "json", "file_name": json_file_name, "sha256": json_hash}
        if json_file_name is not None
        else None
    )

    cases: list[dict[str, object]] = []
    for pdf_file_name, pdf_content in pdf_items:
        try:
            call = await extractor.extract(pdf_content, "application/pdf", pdf_file_name)
        except GeminiPrivateMarketsUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Could not extract {pdf_file_name!r}: {exc}",
            ) from exc

        analysis = analyse_private_markets_case_strict(
            call,
            dataset,
            transactions,
            as_of_date=parsed_as_of,
        )
        if json_content is None:
            _mark_cash_evidence_pending(analysis)

        pdf_hash = _sha256(pdf_content)
        case_id = _case_id(pdf_hash, excel_bundle_hash, json_hash)
        sources: list[dict[str, str | None]] = [
            {"kind": "pdf", "file_name": pdf_file_name, "sha256": pdf_hash},
            *sources_excel,
        ]
        if json_source is not None:
            sources.append(json_source)
        studio_payload: dict[str, Any] = {
            "case_id": case_id,
            "capital_call": call.model_dump(mode="json"),
            "commitments": [item.model_dump(mode="json") for item in dataset.commitments],
            "approved_bank_details": [
                item.model_dump(mode="json") for item in dataset.approved_bank_details
            ],
            "transactions": [item.model_dump(mode="json") for item in transactions],
            "cherry_analysis": analysis.model_dump(mode="json"),
            "sources": sources,
        }
        studio_result = await _agent_studio_result(studio_payload)
        input_sha256: dict[str, str | None] = {
            "pdf": pdf_hash,
            "excel_bundle": excel_bundle_hash,
            "json": json_hash if json_content is not None else None,
        }
        cases.append(
            {
                "case_id": case_id,
                "source_pdf": pdf_file_name,
                "synthetic": False,
                "cash_feed_supplied": json_content is not None,
                "extraction": call.model_dump(mode="json"),
                "analysis": analysis.model_dump(mode="json"),
                "agent_studio": studio_result,
                "evidence": {
                    "input_sha256": input_sha256,
                    "sources": sources,
                    "analysis_sha256": _analysis_hash(analysis),
                    "generated_at": datetime.now(UTC).isoformat(),
                },
                "financial_boundary": (
                    "AI and Agent Studio enrich the case; Cherry deterministic controls decide "
                    "whether it can reconcile, requires approval or needs evidence. No payment is "
                    "initiated."
                ),
            }
        )

    if not cases:
        raise HTTPException(status_code=422, detail="No PDF cases were produced.")

    batch_id = _case_id(
        _bundle_hash(pdf_items),
        excel_bundle_hash,
        json_hash,
    ).replace("PM-", "BATCH-")
    first_case = cases[0]
    action_counts: dict[str, int] = {}
    for item in cases:
        analysis_payload = item["analysis"]
        if isinstance(analysis_payload, dict):
            action = str(analysis_payload.get("action", "unknown"))
            action_counts[action] = action_counts.get(action, 0) + 1

    return {
        **first_case,
        "batch_id": batch_id,
        "batch": {
            "pdf_count": len(pdf_items),
            "excel_count": len(workbook_items),
            "json_count": 1 if json_content is not None else 0,
            "case_count": len(cases),
            "action_counts": action_counts,
        },
        "cases": cases,
        "input_contract": ["pdf", "excel", "json"],
        "input_required": {"pdf": True, "excel": True, "json": False},
        "input_multiplicity": {"pdf": "many", "excel": "many", "json": "zero_or_one"},
    }
