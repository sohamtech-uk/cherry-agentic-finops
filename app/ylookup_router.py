from __future__ import annotations

import hashlib
import hmac
import os
from typing import Annotated, Any

from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from app.config import get_settings
from app.ylookup_datasets import analyse_ylookup_dataset_batch

settings = get_settings()
router = APIRouter(prefix="/api/ylookup", tags=["ylookup"])

MAX_PDF_FILES = 25
MAX_EXCEL_FILES = 20


def _require_upload_access(token: str | None) -> None:
    expected = os.getenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "").strip()
    if settings.environment != "production" and not expected:
        return
    if not expected:
        raise HTTPException(status_code=503, detail="Ylookup uploads are not configured.")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Valid private-markets demo token required.")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@router.get("/health")
async def ylookup_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "supported_workflows": [
            "bank_statements_to_journal_entries",
            "investor_gl_to_loader",
        ],
        "input_contract": {
            "pdf": "zero_or_many",
            "excel": "one_or_many",
            "json": "not_required",
        },
    }


@router.post("/analyse")
async def analyse_ylookup_dataset(
    documents: Annotated[
        list[UploadFile] | None,
        File(description="Optional Ylookup PDF documents, including bank statements"),
    ] = None,
    workbooks: Annotated[
        list[UploadFile] | None,
        File(description="One or more Ylookup XLSX workbooks"),
    ] = None,
    x_cherry_demo_token: Annotated[
        str | None,
        Header(alias="X-Cherry-Demo-Token"),
    ] = None,
) -> dict[str, Any]:
    _require_upload_access(x_cherry_demo_token)

    pdf_uploads = documents or []
    workbook_uploads = workbooks or []
    if not workbook_uploads:
        raise HTTPException(status_code=422, detail="At least one Excel workbook is required.")
    if len(pdf_uploads) > MAX_PDF_FILES:
        raise HTTPException(status_code=413, detail=f"Maximum {MAX_PDF_FILES} PDFs per batch.")
    if len(workbook_uploads) > MAX_EXCEL_FILES:
        raise HTTPException(status_code=413, detail=f"Maximum {MAX_EXCEL_FILES} Excel files per batch.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    pdf_items: list[tuple[str, bytes]] = []
    workbook_items: list[tuple[str, bytes]] = []

    for upload in pdf_uploads:
        file_name = upload.filename or "document.pdf"
        content = await upload.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"PDF {file_name!r} exceeds {settings.max_upload_mb} MB.",
            )
        if not file_name.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail=f"{file_name!r} must be a PDF.")
        pdf_items.append((file_name, content))

    for upload in workbook_uploads:
        file_name = upload.filename or "workbook.xlsx"
        content = await upload.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Excel file {file_name!r} exceeds {settings.max_upload_mb} MB.",
            )
        if not file_name.lower().endswith(".xlsx"):
            raise HTTPException(status_code=415, detail=f"{file_name!r} must be .xlsx.")
        workbook_items.append((file_name, content))

    try:
        result = analyse_ylookup_dataset_batch(
            workbook_items,
            [file_name for file_name, _ in pdf_items],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "not_ylookup_dataset",
                "message": "No recognised Ylookup sponsor workbook contract was detected.",
            },
        )

    result["evidence"] = {
        "pdf_sha256": [
            {"file_name": file_name, "sha256": _sha256(content)}
            for file_name, content in pdf_items
        ],
        "excel_sha256": [
            {"file_name": file_name, "sha256": _sha256(content)}
            for file_name, content in workbook_items
        ],
    }
    return result
