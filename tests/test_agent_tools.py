from __future__ import annotations

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
