from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from app.fund_manager_cases import FundManagerCase, FundManagerCaseStorageError, case_store
from app.fund_manager_reports import build_fund_manager_excel_report, build_fund_manager_pdf_report

router = APIRouter(prefix="/api/fund-manager", tags=["fund-manager"])


def _case_or_404(case_id: str) -> FundManagerCase:
    try:
        case = case_store.get(case_id)
    except FundManagerCaseStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="The Fund Manager case could not be loaded. Retry the report download.",
        ) from exc
    if case is None:
        raise HTTPException(status_code=404, detail=f"Fund Manager case {case_id} was not found.")
    return case


def _decided_case_or_404(case_id: str) -> FundManagerCase:
    case = _case_or_404(case_id)
    if case.stage != "decided":
        message = f"Reports are unavailable until case {case.case_id} has a recorded decision."
        raise HTTPException(status_code=409, detail=message)
    return case


def _nav_report_case(case_id: str) -> FundManagerCase:
    case = _case_or_404(case_id)
    if case.nav_decision is None:
        detail = (
            f"NAV reports are unavailable until case {case.case_id} has a recorded NAV decision."
        )
        raise HTTPException(status_code=409, detail=detail)
    if case.nav_reconciliation is None:
        raise HTTPException(
            status_code=409,
            detail="NAV reconciliation must complete before a NAV report can be downloaded.",
        )

    reconciliation = case.nav_reconciliation
    review = reconciliation.get("review", {})
    findings = review.get("findings", [])
    issues: list[dict[str, Any]] = []
    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "review")
        if severity == "pass":
            continue
        issues.append(
            {
                "id": str(finding.get("code") or f"NAV-{index:03d}"),
                "title": str(finding.get("title") or "NAV finding"),
                "severity": severity,
                "summary": str(finding.get("detail") or ""),
                "recommended_action": str(review.get("action") or "needs_review"),
            }
        )

    critical = sum(1 for issue in issues if issue["severity"] in {"critical", "high"})
    material = sum(1 for issue in issues if issue["severity"] in {"critical", "high", "material"})
    execution = {
        "status": review.get("action", "needs_review"),
        "issues_found": len(issues),
        "material": material,
        "critical": critical,
        "issues": issues,
    }

    return replace(
        case,
        stage="decided",
        execution=execution,
        investigation=case.nav_review or {},
        decision=case.nav_decision,
    )


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


@router.get("/cases/{case_id}/nav/report.pdf")
async def download_nav_pdf_report(case_id: str) -> Response:
    """Download the NAV summary report after the explicit NAV decision is recorded."""

    case = _nav_report_case(case_id)
    content = build_fund_manager_pdf_report(case)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{case.case_id}-nav-summary.pdf"',
        },
    )


@router.get("/cases/{case_id}/nav/report.xlsx")
async def download_nav_excel_report(case_id: str) -> Response:
    """Download the NAV review workbook after the explicit NAV decision is recorded."""

    case = _nav_report_case(case_id)
    content = build_fund_manager_excel_report(case)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{case.case_id}-nav-summary.xlsx"',
        },
    )
