from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.agent_tools import (
    identify_ylookup_workbook,
    inspect_workflow,
    query_database,
    reconcile_investor_gl_workbook,
    reconcile_loader_sample_workbook,
    run_finance_scenario,
    run_nav_quality_review,
)


def _save_workbook(workbook: Workbook, path: Path) -> str:
    workbook.save(path)
    return str(path)


def test_identify_ylookup_workbook_recognises_investor_gl(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Investor-Level GL"
    sheet.append(["Legal Entity", "GL Account", "Trans Type", "Investor", "Deal Name"])
    sheet.append(["Fund A", "1000", "Capital", "LP 1", "Deal 1"])
    path = _save_workbook(workbook, tmp_path / "Investor-Level GL.xlsx")

    profile = identify_ylookup_workbook(path)

    assert profile["kind"] == "investor_gl"


def test_identify_ylookup_workbook_missing_path_raises() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        identify_ylookup_workbook("/nonexistent/workbook.xlsx")


def test_reconcile_investor_gl_workbook_profiles_source(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Investor-Level GL"
    sheet.append(["Legal Entity", "GL Account", "Trans Type", "Investor", "Deal Name"])
    sheet.append(["Fund A", "1000", "Capital", "LP 1", "Deal 1"])
    path = _save_workbook(workbook, tmp_path / "Investor-Level GL.xlsx")

    result = reconcile_investor_gl_workbook(path)

    assert result["workflow"] == "investor_gl_to_loader"
    assert result["row_count"] == 1


def test_reconcile_loader_sample_workbook_reports_missing_fields(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Some Other Column"])
    path = _save_workbook(workbook, tmp_path / "loader_sample.xlsx")

    result = reconcile_loader_sample_workbook(path)

    assert result["status"] == "review_required"
    assert result["required_target_fields_present"] is False


def test_query_database_matches_inspect_workflow() -> None:
    workflow = run_finance_scenario("autonomous")
    workflow_id = workflow["workflow_id"]

    assert query_database(workflow_id) == inspect_workflow(workflow_id)


def _write_nav_summary(path: Path, **overrides: object) -> str:
    payload = {
        "legal_entity": "Fund X",
        "period_end": "2026-06-30",
        "currency": "USD",
        "total_assets": 5_000_000,
        "total_liabilities": 150_000,
        "reported_equity": 4_850_000,
        "opening_nav": 4_700_000,
        "contributions": 250_000,
        "distributions": 100_000,
        "investment_movement": 0,
        "income": 10_000,
        "expenses": 10_000,
        "fx_movement": 0,
        "closing_nav": 4_850_000,
        "investor_capital": [
            {"investor": "Investor A", "reported_capital": 3_000_000},
            {"investor": "Investor B", "reported_capital": 1_850_000},
        ],
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload))
    return str(path)


def test_run_nav_quality_review_clean_summary_is_ready_to_submit(tmp_path: Path) -> None:
    summary_path = _write_nav_summary(tmp_path / "nav-summary.json")

    report = run_nav_quality_review(summary_path)

    assert report["action"] == "ready_to_submit"
    assert report["exceptions_open"] == 0


def test_run_nav_quality_review_flags_balance_sheet_mismatch(tmp_path: Path) -> None:
    summary_path = _write_nav_summary(tmp_path / "nav-summary.json", reported_equity=4_000_000)

    report = run_nav_quality_review(summary_path)

    assert report["action"] == "return_to_administrator"
    assert any(
        finding["code"] == "balance_sheet.footing_mismatch" for finding in report["findings"]
    )


def test_run_nav_quality_review_missing_path_raises() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        run_nav_quality_review("/nonexistent/nav-summary.json")
