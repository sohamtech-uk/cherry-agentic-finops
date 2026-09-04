from __future__ import annotations

import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.config import get_settings
from app.private_markets import (
    CapitalCallExtraction,
    GeminiCapitalCallExtractor,
    GeminiPrivateMarketsUnavailable,
    analyse_private_markets_case,
    parse_cash_csv,
    parse_commitment_workbook,
)

settings = get_settings()
extractor = GeminiCapitalCallExtractor(settings)
router = APIRouter(prefix="/api/private-markets", tags=["private-markets"])


@router.get("/health")
async def private_markets_health() -> dict[str, object]:
    return {
        "status": "ok",
        "google_ready": settings.google_ready,
        "accepted_commitment_format": "xlsx",
        "accepted_cash_format": "utf-8 csv",
        "financial_boundary": "Decision support only; no payment initiation.",
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
