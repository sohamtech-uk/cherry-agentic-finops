from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import fund_manager_nav_router
from app.api import app
from app.fund_manager_cases import case_store
from app.fund_manager_nav_controller import build_nav_readiness

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_cases() -> None:
    case_store.clear()


def _nav_summary() -> bytes:
    return json.dumps(
        {
            "legal_entity": "Northstar Fund III",
            "period_end": "2026-06-30",
            "currency": "GBP",
            "total_assets": "108500000.00",
            "total_liabilities": "95000.00",
            "reported_equity": "108405000.00",
            "opening_nav": "107000000.00",
            "closing_nav": "108405000.00",
            "contributions": "750000.00",
            "distributions": "250000.00",
            "investment_movement": "1020000.00",
            "income": "100000.00",
            "expenses": "215000.00",
            "fx_movement": "0.00",
            "investor_capital": [],
        }
    ).encode()


def _case() -> Any:
    files = [("nav-summary.json", _nav_summary(), "application/json")]
    classification = {
        "sources": [
            {
                "id": "SRC-01",
                "filename": "nav-summary.json",
                "detected_type": "unknown_json",
                "validation_status": "rejected",
            }
        ]
    }
    return case_store.create(files, classification=classification, fund_name="Northstar Fund III")


def test_nav_readiness_identifies_structured_nav_summary() -> None:
    readiness = build_nav_readiness(_case())
    assert readiness["status"] == "ready"
    assert readiness["inputs"]["nav_summary"]["legal_entity"] == "Northstar Fund III"
    assert readiness["controls"][0]["status"] == "ready"
    assert "investor-level GL" in readiness["optional_gaps"]


def test_nav_readiness_endpoint_reuses_existing_case() -> None:
    case = _case()
    response = client.post(f"/api/fund-manager/cases/{case.case_id}/nav/readiness")
    assert response.status_code == 200
    payload = response.json()
    nav = payload["workflows"]["nav_quality_controller"]
    assert nav["readiness"]["status"] == "ready"
    assert nav["reconciliation"] is None


def test_nav_reconcile_review_and_decision_are_staged(monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case()
    case.nav_readiness = build_nav_readiness(case)

    def fake_reconcile(_: Any) -> dict[str, Any]:
        return {
            "workflow": "nav_quality_controller",
            "legal_entity": "Northstar Fund III",
            "period_end": "2026-06-30",
            "review": {
                "action": "needs_review",
                "controls_passed": 4,
                "exceptions_open": 1,
                "findings": [{"code": "nav.bridge", "title": "NAV bridge difference"}],
            },
            "root_causes": [],
        }

    async def fake_review(_: Any) -> dict[str, Any]:
        return {
            "workflow": "nav_quality_controller",
            "stage": "reviewed",
            "recommended_human_action": "return_to_administrator",
            "investigations": [],
        }

    monkeypatch.setattr(fund_manager_nav_router, "run_case_nav_reconciliation", fake_reconcile)
    monkeypatch.setattr(fund_manager_nav_router, "run_case_nav_review", fake_review)

    reconcile = client.post(f"/api/fund-manager/cases/{case.case_id}/nav/reconcile")
    assert reconcile.status_code == 200
    assert reconcile.json()["workflows"]["nav_quality_controller"]["reconciliation"] is not None

    review = client.post(f"/api/fund-manager/cases/{case.case_id}/nav/review")
    assert review.status_code == 200
    assert review.json()["workflows"]["nav_quality_controller"]["review"]["stage"] == "reviewed"

    decision = client.post(
        f"/api/fund-manager/cases/{case.case_id}/nav/decision",
        json={"action": "return_to_administrator", "note": "Confirm the NAV bridge break."},
    )
    assert decision.status_code == 200
    stored = decision.json()["workflows"]["nav_quality_controller"]["decision"]
    assert stored["action"] == "return_to_administrator"
    assert "official NAV" in stored["financial_boundary"]


def test_nav_review_requires_reconciliation() -> None:
    case = _case()
    response = client.post(f"/api/fund-manager/cases/{case.case_id}/nav/review")
    assert response.status_code == 409
