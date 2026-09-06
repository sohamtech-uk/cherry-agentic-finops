from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.fund_manager_cases import FundManagerCase, case_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_cases() -> None:
    case_store.clear()


def _case(*, decided: bool) -> FundManagerCase:
    case = case_store.create(
        [("positions.json", b"[]", "application/json")],
        classification={
            "accepted_count": 1,
            "rejected_count": 0,
            "sources": [
                {
                    "id": "SRC-01",
                    "filename": "positions.json",
                    "detected_type": "positions",
                    "validation_status": "accepted",
                }
            ],
        },
        fund_name="Northstar Growth Fund III",
        reporting_period="Q2 2026",
        as_of_date="2026-06-30",
    )
    case.plan = {
        "control_plan": [
            {
                "control": "Position reconciliation",
                "status": "ready",
                "source_ids": ["SRC-01"],
                "reasoning": "Position evidence is available.",
            }
        ]
    }
    case.execution = {
        "status": "review_required",
        "issues_found": 1,
        "material": 1,
        "critical": 0,
        "issues": [
            {
                "id": "EXC-001",
                "title": "Position mismatch",
                "severity": "warning",
                "summary": "Position quantities differ.",
                "recommended_action": "Review the break.",
            }
        ],
    }
    case.investigation = {
        "investigations": [
            {
                "issue_id": "EXC-001",
                "priority": "medium",
                "finding": "A position break requires review.",
                "likely_cause": "Different source quantities.",
                "evidence_gap": "Confirm the authoritative source.",
                "recommended_action": "Assign for review.",
            }
        ]
    }
    if decided:
        case.decision = {
            "action": "assign_and_monitor",
            "note": "Operations team to resolve the break.",
            "recorded_at": "2026-09-06T09:30:00+00:00",
            "actor": "fund-manager-ui-user",
        }
        case.stage = "decided"
    else:
        case.stage = "investigated"
    case.touch()
    case_store.save(case)
    return case


def test_final_pdf_report_downloads_after_human_decision() -> None:
    case = _case(decided=True)

    response = client.get(f"/api/fund-manager/cases/{case.case_id}/report.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert f"{case.case_id}-review.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


def test_final_excel_report_downloads_after_human_decision() -> None:
    case = _case(decided=True)

    response = client.get(f"/api/fund-manager/cases/{case.case_id}/report.xlsx")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert f"{case.case_id}-review.xlsx" in response.headers["content-disposition"]
    assert response.content.startswith(b"PK")


def test_reports_are_not_available_before_decision_is_recorded() -> None:
    case = _case(decided=False)

    pdf_response = client.get(f"/api/fund-manager/cases/{case.case_id}/report.pdf")
    xlsx_response = client.get(f"/api/fund-manager/cases/{case.case_id}/report.xlsx")

    assert pdf_response.status_code == 409
    assert xlsx_response.status_code == 409


def test_completed_decision_ui_removes_back_and_adds_report_actions() -> None:
    script = Path("app/static/fund_manager_completion.js").read_text(encoding="utf-8")

    assert 'stage.querySelector("#fm-back")?.remove()' in script
    assert '"Download PDF report ↓"' in script
    assert '"Download Excel report ↓"' in script
    assert "/api/fund-manager/cases/" in script
