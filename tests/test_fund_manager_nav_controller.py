from __future__ import annotations

import json
from typing import Any

import pytest

import app.fund_manager_nav_controller as fund_manager_nav_controller
from app.fund_manager_cases import case_store
from app.fund_manager_classification import classify_and_validate_sources
from app.fund_manager_nav_controller import (
    ROUND_REDUCTION_TARGET,
    build_nav_readiness,
    get_case_nav_history,
    run_case_nav_reconciliation,
    run_case_nav_review,
)
from app.nav_review_history import get_nav_review_history_store


def setup_function() -> None:
    get_nav_review_history_store().clear()


def teardown_function() -> None:
    get_nav_review_history_store().clear()


def _nav_summary(**overrides: object) -> bytes:
    payload: dict[str, object] = {
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
    payload.update(overrides)
    return json.dumps(payload).encode()


def _case(**overrides: object) -> Any:
    """Build a case through the real classifier so readiness sees genuinely accepted evidence,
    the same way the fund manager router does."""

    files = [("nav-summary.json", _nav_summary(**overrides), "application/json")]
    classification = {"sources": classify_and_validate_sources(files)}
    return case_store.create(files, classification=classification, fund_name="Northstar Fund III")


def test_run_case_nav_reconciliation_requires_ready_readiness() -> None:
    files = [("mystery.json", b'{"foo": "bar"}', "application/json")]
    classification = {"sources": classify_and_validate_sources(files)}
    case = case_store.create(files, classification=classification, fund_name="Mystery Fund")

    with pytest.raises(ValueError, match="not ready"):
        run_case_nav_reconciliation(case)


def test_run_case_nav_reconciliation_runs_the_real_engine() -> None:
    case = _case()
    case.nav_readiness = build_nav_readiness(case)

    result = run_case_nav_reconciliation(case)

    assert result["workflow"] == "nav_quality_controller"
    assert result["fund_manager_case_id"] == case.case_id
    assert result["period_end"] == "2026-06-30"
    assert result["stage"] == "reconciled"
    assert result["review"]["action"] == "ready_to_submit"
    assert result["round_reduction_target"] == ROUND_REDUCTION_TARGET


def test_run_case_nav_reconciliation_flags_a_real_break() -> None:
    case = _case(reported_equity="108000000.00")
    case.nav_readiness = build_nav_readiness(case)

    result = run_case_nav_reconciliation(case)

    assert result["review"]["action"] == "return_to_administrator"
    assert len(result["root_causes"]) == 1
    assert result["root_causes"][0]["category"] == "balance_sheet"


def test_get_case_nav_history_before_reconciliation() -> None:
    case = _case()

    history = get_case_nav_history(case)

    assert history["available"] is False


def test_get_case_nav_history_after_reconciliation() -> None:
    case = _case()
    case.nav_readiness = build_nav_readiness(case)
    case.nav_reconciliation = run_case_nav_reconciliation(case)

    history = get_case_nav_history(case)

    assert history["available"] is True
    assert history["history"]["legal_entity"] == "Northstar Fund III"
    assert history["history"]["rounds_submitted"] == 1


@pytest.mark.asyncio
async def test_run_case_nav_review_requires_reconciliation() -> None:
    case = _case()

    with pytest.raises(ValueError, match="must complete"):
        await run_case_nav_review(case)


@pytest.mark.asyncio
async def test_run_case_nav_review_attaches_remediation_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case(reported_equity="108000000.00")
    case.nav_readiness = build_nav_readiness(case)
    case.nav_reconciliation = run_case_nav_reconciliation(case)

    async def fake_investigate(execution: dict[str, Any]) -> dict[str, Any]:
        assert execution["nav_quality_result"] is case.nav_reconciliation
        return {
            "investigations": [],
            "agent_summary": "stub agent summary",
            "recommended_human_action": "escalate",
        }

    monkeypatch.setattr(fund_manager_nav_controller, "investigate_case_execution", fake_investigate)

    review = await run_case_nav_review(case)

    assert review["workflow"] == "nav_quality_controller"
    assert review["stage"] == "reviewed"
    assert review["deterministic_action"] == "return_to_administrator"
    assert len(review["root_causes"]) == 1
    assert review["remediation_package"]["mode"] == "consolidated_first_pass"
    assert review["remediation_package"]["finding_count"] >= 1
    assert review["remediation_package"]["root_cause_count"] == 1
    assert review["round_reduction_target"] == ROUND_REDUCTION_TARGET
    assert "official NAV" in review["control_boundary"]
