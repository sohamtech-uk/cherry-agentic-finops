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
    GeminiCapitalCallExtractor,
    GeminiPrivateMarketsUnavailable,
    PrivateMarketsAnalysis,
    parse_commitment_workbook,
)
from app.private_markets_io import parse_cash_json
from app.private_markets_strict import analyse_private_markets_case_strict

settings = get_settings()
extractor = GeminiCapitalCallExtractor(settings)
studio = FundOpsStudioConnector(settings)
router = APIRouter(prefix="/api/private-markets", tags=["private-markets-integration"])


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


@router.get("/integration/health")
async def integration_health() -> dict[str, Any]:
    response: dict[str, Any] = {
        "status": "ok",
        "input_contract": ["pdf", "excel", "json"],
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
        UploadFile,
        File(description="Capital-call notice PDF"),
    ],
    commitments: Annotated[
        UploadFile,
        File(description="LP commitment/control workbook (.xlsx)"),
    ],
    fund_json: Annotated[
        UploadFile,
        File(description="Fund cash/bank transactions (.json)"),
    ],
    as_of_date: Annotated[
        str | None,
        Form(description="Optional YYYY-MM-DD control date."),
    ] = None,
    x_cherry_demo_token: Annotated[
        str | None,
        Header(alias="X-Cherry-Demo-Token"),
    ] = None,
) -> dict[str, object]:
    """Run the combined PDF + Excel + JSON private-markets workflow.

    Cherry extracts the PDF, parses the commitment workbook and cash JSON, applies strict
    deterministic controls, and then sends only structured case data and evidence hashes to the
    optional FundOps Agent Studio microservice for capital-call review, reconciliation and exception
    investigation. Cherry remains the authority for the financial control state.
    """

    _require_real_data_access(x_cherry_demo_token)
    max_bytes = settings.max_upload_mb * 1024 * 1024

    pdf_content = await capital_call.read()
    workbook_content = await commitments.read()
    json_content = await fund_json.read()
    for label, content in {
        "PDF": pdf_content,
        "Excel": workbook_content,
        "JSON": json_content,
    }.items():
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{label} input exceeds the {settings.max_upload_mb} MB upload limit.",
            )

    if (capital_call.content_type or "").lower() != "application/pdf":
        raise HTTPException(status_code=415, detail="capital_call must be a PDF document.")
    if not (commitments.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=415, detail="commitments must be an .xlsx workbook.")
    if not (fund_json.filename or "").lower().endswith(".json"):
        raise HTTPException(status_code=415, detail="fund_json must be a .json file.")

    try:
        dataset = parse_commitment_workbook(workbook_content)
        transactions = parse_cash_json(json_content)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid Excel/JSON supporting data: {exc}",
        ) from exc

    try:
        call = await extractor.extract(
            pdf_content,
            "application/pdf",
            capital_call.filename or "capital-call.pdf",
        )
    except GeminiPrivateMarketsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    parsed_as_of: date | None = None
    if as_of_date:
        try:
            parsed_as_of = date.fromisoformat(as_of_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="as_of_date must be YYYY-MM-DD.") from exc

    analysis = analyse_private_markets_case_strict(
        call,
        dataset,
        transactions,
        as_of_date=parsed_as_of,
    )
    input_hashes = {
        "pdf": _sha256(pdf_content),
        "excel": _sha256(workbook_content),
        "json": _sha256(json_content),
    }
    case_id = _case_id(*input_hashes.values())

    studio_payload: dict[str, Any] = {
        "case_id": case_id,
        "capital_call": call.model_dump(mode="json"),
        "commitments": [item.model_dump(mode="json") for item in dataset.commitments],
        "approved_bank_details": [
            item.model_dump(mode="json") for item in dataset.approved_bank_details
        ],
        "transactions": [item.model_dump(mode="json") for item in transactions],
        "cherry_analysis": analysis.model_dump(mode="json"),
        "sources": [
            {
                "kind": "pdf",
                "file_name": capital_call.filename or "capital-call.pdf",
                "sha256": input_hashes["pdf"],
            },
            {
                "kind": "excel",
                "file_name": commitments.filename or "commitments.xlsx",
                "sha256": input_hashes["excel"],
            },
            {
                "kind": "json",
                "file_name": fund_json.filename or "fund-cash.json",
                "sha256": input_hashes["json"],
            },
        ],
    }

    studio_result: dict[str, Any]
    if not studio.configured:
        studio_result = {
            "status": "not_configured",
            "message": "Cherry strict controls completed; Agent Studio enrichment was skipped.",
        }
    else:
        try:
            studio_result = await studio.analyse_capital_call_case(studio_payload)
            studio_result = {"status": "completed", **studio_result}
        except FundOpsStudioUnavailable:
            studio_result = {
                "status": "unavailable",
                "message": (
                    "Cherry strict controls completed; Agent Studio was temporarily unavailable."
                ),
            }

    return {
        "case_id": case_id,
        "synthetic": False,
        "input_contract": ["pdf", "excel", "json"],
        "controls_version": "strict-v1",
        "extraction": call.model_dump(mode="json"),
        "analysis": analysis.model_dump(mode="json"),
        "agent_studio": studio_result,
        "evidence": {
            "input_sha256": input_hashes,
            "analysis_sha256": _analysis_hash(analysis),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "financial_boundary": (
            "AI and Agent Studio enrich the case; Cherry deterministic controls decide whether it "
            "can reconcile, requires approval or needs evidence. No payment is initiated."
        ),
    }
