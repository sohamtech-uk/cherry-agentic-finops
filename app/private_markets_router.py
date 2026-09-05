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
from app.connectors import CherryMoneyConnector
from app.private_markets import (
    ApprovedBankDetails,
    CapitalCallExtraction,
    FundCashTransaction,
    GeminiCapitalCallExtractor,
    GeminiPrivateMarketsUnavailable,
    LPCommitment,
    PrivateMarketsAnalysis,
    PrivateMarketsDataset,
    parse_cash_csv,
    parse_commitment_workbook,
)
from app.private_markets_strict import analyse_private_markets_case_strict

settings = get_settings()
extractor = GeminiCapitalCallExtractor(settings)
cherry_money = CherryMoneyConnector(settings)
router = APIRouter(prefix="/api/private-markets", tags=["private-markets"])


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


def _demo_case(
    scenario: str,
) -> tuple[CapitalCallExtraction, PrivateMarketsDataset, list[FundCashTransaction]]:
    if scenario not in {"exception", "clean", "awaiting-cash"}:
        raise ValueError("Scenario must be exception, clean, or awaiting-cash.")

    call = CapitalCallExtraction(
        fund_name="Cedar Peak Growth Fund III LP",
        investor_name="Oakfield Pension Trust",
        lp_reference="LP-001",
        notice_id="NCGFIII-CALL-2026-03",
        issue_date=date(2026, 8, 28),
        due_date=date(2026, 9, 6),
        currency="GBP",
        total_commitment=5_000_000,
        called_before_current=2_750_000,
        current_call=1_250_000,
        remaining_after_current=1_000_000,
        beneficiary="Cedar Peak Growth Fund III LP",
        bank_name="Cedar Demo Bank plc" if scenario != "exception" else "Harbour Demo Bank plc",
        sort_code="00-00-00" if scenario != "exception" else "99-99-99",
        account_last4="2381" if scenario != "exception" else "9437",
        payment_reference="NCGFIII-CALL-2026-03 / LP-001",
        purpose="Portfolio acquisition funding and fund expenses",
        confidence=98,
        source="fixture",
    )
    dataset = PrivateMarketsDataset(
        commitments=[
            LPCommitment(
                lp_id="LP-001",
                lp_name="Oakfield Pension Trust",
                total_commitment=5_000_000,
                called_before_current=2_750_000,
                current_call=1_250_000,
                remaining_after_current=1_000_000,
                due_date=date(2026, 9, 6),
                call_notice_id="NCGFIII-CALL-2026-03",
                call_status="RECEIVED" if scenario == "clean" else "OPEN",
            )
        ],
        approved_bank_details=[
            ApprovedBankDetails(
                fund_id="FUND-001",
                fund_name="Cedar Peak Growth Fund III LP",
                beneficiary="Cedar Peak Growth Fund III LP",
                bank_name="Cedar Demo Bank plc",
                sort_code="00-00-00",
                account_last4="2381",
                approval_status="APPROVED",
            )
        ],
    )
    transactions: list[FundCashTransaction] = []
    if scenario != "awaiting-cash":
        transactions.append(
            FundCashTransaction(
                transaction_id="TXN-2026-0905-003",
                booking_date=date(2026, 9, 5),
                direction="credit",
                amount=1_250_000 if scenario == "clean" else 1_249_500,
                currency="GBP",
                counterparty="Oakfield Pension Trust",
                reference="NCGFIII-CALL-2026-03 / LP-001",
                description="Capital contribution - Oakfield",
                status="BOOKED",
            )
        )
    return call, dataset, transactions


@router.get("/health")
async def private_markets_health() -> dict[str, object]:
    expected_token = bool(os.getenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "").strip())
    return {
        "status": "ok",
        "controls": "strict-v1",
        "google_ready": settings.google_ready,
        "cherry_money_read_only_configured": cherry_money.configured,
        "accepted_commitment_format": "xlsx",
        "accepted_cash_format": "utf-8 csv",
        "real_upload_protected": settings.environment == "production" or expected_token,
        "financial_boundary": "Decision support only; no payment initiation.",
    }


@router.post("/demo/{scenario}")
async def private_markets_demo(scenario: str) -> dict[str, object]:
    try:
        call, dataset, transactions = _demo_case(scenario)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    analysis = analyse_private_markets_case_strict(
        call,
        dataset,
        transactions,
        as_of_date=date(2026, 9, 5),
    )
    return {
        "case_id": "CPGF-2026-03-LP001",
        "scenario": scenario,
        "synthetic": True,
        "controls_version": "strict-v1",
        "source_files": [
            "Capital call notice",
            "LP commitment workbook",
            "Fund bank cash feed",
        ],
        "extraction": call.model_dump(mode="json"),
        "analysis": analysis.model_dump(mode="json"),
        "transactions": [transaction.model_dump(mode="json") for transaction in transactions],
        "evidence": {
            "analysis_sha256": _analysis_hash(analysis),
            "generated_at": datetime.now(UTC).isoformat(),
        },
    }


@router.get("/cherry-money/snapshot")
async def cherry_money_snapshot(
    x_cherry_demo_token: Annotated[
        str | None,
        Header(alias="X-Cherry-Demo-Token"),
    ] = None,
    limit: int = 50,
) -> dict[str, Any]:
    _require_real_data_access(x_cherry_demo_token)
    if not cherry_money.configured:
        raise HTTPException(
            status_code=503, detail="Cherry Money read-only bridge is not configured."
        )
    try:
        snapshot = await cherry_money.finance_snapshot(limit=limit)
    except Exception as exc:  # pragma: no cover - depends on external service
        raise HTTPException(
            status_code=502, detail="Cherry Money read-only bridge unavailable."
        ) from exc
    return {
        "read_only": True,
        "source": "Cherry Money /api/webmcp/bootstrap",
        "snapshot": snapshot,
    }


@router.post("/analyse")
async def analyse_private_markets(
    commitments: Annotated[
        UploadFile,
        File(description="LP commitment/control workbook (.xlsx)"),
    ],
    cash: Annotated[
        UploadFile,
        File(description="Fund cash/bank transactions (.csv)"),
    ],
    capital_call: Annotated[
        UploadFile | None,
        File(
            description="Capital-call/distribution PDF or image. Optional with capital_call_json."
        ),
    ] = None,
    capital_call_json: Annotated[
        str | None,
        Form(
            description=(
                "Optional schema-conformant capital-call JSON fallback. Useful when AI extraction "
                "is unavailable or for deterministic fixture testing."
            )
        ),
    ] = None,
    as_of_date: Annotated[
        str | None,
        Form(description="Optional YYYY-MM-DD date for due-date controls."),
    ] = None,
    x_cherry_demo_token: Annotated[
        str | None,
        Header(alias="X-Cherry-Demo-Token"),
    ] = None,
) -> dict[str, object]:
    _require_real_data_access(x_cherry_demo_token)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    workbook_content = await commitments.read()
    cash_content = await cash.read()
    if len(workbook_content) > max_bytes or len(cash_content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Supporting file exceeds the {settings.max_upload_mb} MB upload limit.",
        )

    try:
        dataset = parse_commitment_workbook(workbook_content)
        transactions = parse_cash_csv(cash_content)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid supporting data: {exc}") from exc

    notice_content: bytes
    if capital_call_json:
        notice_content = capital_call_json.encode("utf-8")
        try:
            payload = json.loads(capital_call_json)
            payload.setdefault("source", "manual")
            call = CapitalCallExtraction.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid capital_call_json: {exc}"
            ) from exc
    else:
        if capital_call is None:
            raise HTTPException(
                status_code=422,
                detail="Provide either capital_call or capital_call_json.",
            )
        notice_content = await capital_call.read()
        if len(notice_content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Capital-call document exceeds the {settings.max_upload_mb} MB upload limit.",
            )
        mime_type = capital_call.content_type or "application/octet-stream"
        if mime_type not in {
            "application/pdf",
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/heic",
        }:
            raise HTTPException(status_code=415, detail=f"Unsupported document type: {mime_type}")
        try:
            call = await extractor.extract(
                notice_content,
                mime_type,
                capital_call.filename or "capital-call",
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
        "capital_call": _sha256(notice_content),
        "commitments": _sha256(workbook_content),
        "cash": _sha256(cash_content),
    }
    return {
        "case_id": _case_id(*input_hashes.values()),
        "synthetic": False,
        "controls_version": "strict-v1",
        "extraction": call.model_dump(mode="json"),
        "analysis": analysis.model_dump(mode="json"),
        "evidence": {
            "input_sha256": input_hashes,
            "analysis_sha256": _analysis_hash(analysis),
            "generated_at": datetime.now(UTC).isoformat(),
        },
    }
