from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.fund_manager_cases import FundManagerCase, FundManagerCaseStorageError, case_store
from app.fund_manager_reports import build_fund_manager_excel_report, build_fund_manager_pdf_report

router = APIRouter(prefix="/api/fund-manager", tags=["fund-manager"])


def _decided_case_or_404(case_id: str) -> FundManagerCase:
    try:
        case = case_store.get(case_id)
    except FundManagerCaseStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="The Fund Manager case could not be loaded. Retry the report download.",
        ) from exc
    if case is None:
        raise HTTPException(status_code=404, detail=f"Fund Manager case {case_id} was not found.")
    if case.stage != "decided":
        message = f"Reports are unavailable until case {case.case_id} has a recorded decision."
        raise HTTPException(status_code=409, detail=message)
    return case


@router.get("/cases/{case_id}/report.pdf")
async def download_fund_manager_pdf_report(case_id: str) -> Response:
    """Download the final review PDF only after the explicit human decision is recorded."""

    case = _decided_case_or_404(case_id)
    content = build_fund_manager_pdf_report(case)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{case.case_id}-review.pdf"',
        },
    )


@router.get("/cases/{case_id}/report.xlsx")
async def download_fund_manager_excel_report(case_id: str) -> Response:
    """Download the final review workbook only after the explicit human decision is recorded."""

    case = _decided_case_or_404(case_id)
    content = build_fund_manager_excel_report(case)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{case.case_id}-review.xlsx"',
        },
    )
