from __future__ import annotations

import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.config import get_settings
from app.private_markets import (
    ApprovedBankDetails,
    CapitalCallExtraction,
    FundCashTransaction,
    GeminiCapitalCallExtractor,
    GeminiPrivateMarketsUnavailable,
    LPCommitment,
    PrivateMarketsDataset,
    analyse_private_markets_case,
    parse_cash_csv,
    parse_commitment_workbook,
)

settings = get_settings()
extractor = GeminiCapitalCallExtractor(settings)
router = APIRouter(prefix="/api/private-markets", tags=["private-markets"])


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
    return {
        "status": "ok",
        "google_ready": settings.google_ready,
        "accepted_commitment_format": "xlsx",
        "accepted_cash_format": "utf-8 csv",
        "financial_boundary": "Decision support only; no payment initiation.",
    }


@router.post("/demo/{scenario}")
async def private_markets_demo(scenario: str) -> dict[str, object]:
    try:
        call, dataset, transactions = _demo_case(scenario)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    analysis = analyse_private_markets_case(
        call,
        dataset,
        transactions,
        as_of_date=date(2026, 9, 5),
    )
    return {
        "case_id": "CPGF-2026-03-LP001",
        "scenario": scenario,
        "synthetic": True,
        "source_files": [
            "Capital call notice",
            "LP commitment workbook",
            "Fund bank cash feed",
        ],
        "extraction": call.model_dump(mode="json"),
        "analysis": analysis.model_dump(mode="json"),
        "transactions": [transaction.model_dump(mode="json") for transaction in transactions],
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
) -> dict[str, object]:
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

    if capital_call_json:
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
        content = await capital_call.read()
        if len(content) > max_bytes:
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
                content,
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

    analysis = analyse_private_markets_case(
        call,
        dataset,
        transactions,
        as_of_date=parsed_as_of,
    )
    return {
        "extraction": call.model_dump(mode="json"),
        "analysis": analysis.model_dump(mode="json"),
    }
