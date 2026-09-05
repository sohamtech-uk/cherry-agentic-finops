from __future__ import annotations

import hashlib
import hmac
import os
from typing import Annotated, Any

from fastapi import APIRouter, Body, File, Header, HTTPException, UploadFile
from fastapi.responses import Response

from app.config import get_settings
from app.ylookup_datasets import analyse_ylookup_dataset_batch
from app.ylookup_reports import build_ylookup_excel_report, build_ylookup_pdf_report

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


def _hash_items(items: list[tuple[str, bytes]]) -> list[dict[str, str]]:
    hashes: list[dict[str, str]] = []
    for file_name, content in items:
        hashes.append({"file_name": file_name, "sha256": _sha256(content)})
    return hashes


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
        "report_formats": ["pdf", "xlsx"],
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
        raise HTTPException(
            status_code=413,
            detail=f"Maximum {MAX_EXCEL_FILES} Excel files per batch.",
        )

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
        "pdf_sha256": _hash_items(pdf_items),
        "excel_sha256": _hash_items(workbook_items),
    }
    return result


@router.post("/report/{report_format}")
async def download_ylookup_report(
    report_format: str,
    result: Annotated[
        dict[str, Any],
        Body(description="Previously returned /api/ylookup/analyse result"),
    ],
    x_cherry_demo_token: Annotated[
        str | None,
        Header(alias="X-Cherry-Demo-Token"),
    ] = None,
) -> Response:
    """Create a point-in-time report from the current structured review result.

    The report request is stateless: the browser sends the current structured analysis back to this
    endpoint, which renders a file and does not retain the report payload after the request.
    """

    _require_upload_access(x_cherry_demo_token)
    if result.get("workflow_type") != "ylookup_dataset_batch":
        raise HTTPException(
            status_code=422, detail="A Ylookup dataset analysis result is required."
        )

    if report_format == "xlsx":
        content = build_ylookup_excel_report(result)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "cherry-fundops-ylookup-review.xlsx"
    elif report_format == "pdf":
        try:
            content = build_ylookup_pdf_report(result)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        media_type = "application/pdf"
        filename = "cherry-fundops-ylookup-review.pdf"
    else:
        raise HTTPException(status_code=404, detail="Report format must be pdf or xlsx.")

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )