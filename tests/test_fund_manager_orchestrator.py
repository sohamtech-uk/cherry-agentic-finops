from __future__ import annotations

import json

from app.fund_manager_orchestrator import run_analysis

_CURRENT_STATEMENT = b"""Subsequent Events
No subsequent events occurred after 2026-06-30.
"""

_PRIOR_STATEMENT = b"""Subsequent Events
Portfolio Company X completed a transaction on 2026-05-17.
"""


def test_single_financial_statement_needs_pairing() -> None:
    result = run_analysis([("statement.txt", _CURRENT_STATEMENT, "text/plain")])

    assert result["status"] == "clean"
    assert result["issues"] == []
    plan = result["control_plan"][0]
    assert plan["status"] == "needs_pairing"
    assert plan["detected_type"] == "financial_statement"


def test_two_financial_statements_are_compared_and_flagged() -> None:
    result = run_analysis(
        [
            ("prior.txt", _PRIOR_STATEMENT, "text/plain"),
            ("current.txt", _CURRENT_STATEMENT, "text/plain"),
        ]
    )

    assert result["status"] == "review_required"
    assert result["issues_found"] == 1
    assert result["material"] == 1
    assert result["critical"] == 0
    issue_ids = {issue["id"] for issue in result["issues"]}
    assert "ISS-STMT-DIFF" in issue_ids
    for plan_entry in result["control_plan"]:
        assert plan_entry["status"] == "executed"


def test_unrecognised_source_type_is_not_yet_available() -> None:
    positions = json.dumps([{"security_id": "ABC", "quantity": 100}]).encode()

    result = run_analysis([("positions.json", positions, "application/json")])

    assert result["status"] == "clean"
    assert result["control_plan"][0]["detected_type"] == "positions"
    assert result["control_plan"][0]["status"] == "not_yet_available"


def test_unknown_file_has_no_control_plan_entry() -> None:
    result = run_analysis([("mystery.txt", b"hello", "text/plain")])

    assert result["control_plan"] == []
    assert result["issues"] == []
    assert result["status"] == "clean"


def test_control_boundary_note_is_present() -> None:
    result = run_analysis([("mystery.txt", b"hello", "text/plain")])

    assert "control_boundary" in result
    assert "never" in result["control_boundary"].casefold()
