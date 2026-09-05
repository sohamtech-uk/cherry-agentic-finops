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

    assert result["status"] == "insufficient_evidence"
    assert result["issues"][0]["category"] == "data_quality"
    plan = result["control_plan"][0]
    assert plan["status"] == "needs_evidence"
    assert plan["control_id"] == "CTRL-STMT-001"


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
    issue_codes = {issue["code"] for issue in result["issues"]}
    assert "statement.period_text_changed" in issue_codes
    for plan_entry in result["control_plan"]:
        assert plan_entry["status"] == "executed"
    assert result["investigations"][0]["lineage"]["evidence_source_ids"] == [
        "SRC-01",
        "SRC-02",
    ]


def test_unrecognised_source_type_is_not_yet_available() -> None:
    positions = json.dumps([{"security_id": "ABC", "quantity": 100}]).encode()

    result = run_analysis([("positions.json", positions, "application/json")])

    assert result["status"] == "insufficient_evidence"
    assert result["control_plan"][0]["control_id"] == "CTRL-POS-001"
    assert result["control_plan"][0]["status"] == "needs_evidence"
    assert result["issues"][0]["code"].endswith("evidence_missing")


def test_unknown_file_has_no_control_plan_entry() -> None:
    result = run_analysis([("mystery.txt", b"hello", "text/plain")])

    assert result["control_plan"] == []
    assert result["issues"][0]["code"] == "evidence.unclassified"
    assert result["status"] == "insufficient_evidence"


def test_control_boundary_note_is_present() -> None:
    result = run_analysis([("mystery.txt", b"hello", "text/plain")])

    assert "control_boundary" in result
    assert "never" in result["control_boundary"].casefold()


def test_position_pair_runs_control_generates_exception_and_investigation() -> None:
    internal = json.dumps(
        [{"fund": "F1", "security_id": "ABC", "quantity": 100, "price": 10}]
    ).encode()
    external = json.dumps(
        [{"fund": "F1", "security_id": "ABC", "quantity": 90, "price": 10}]
    ).encode()

    result = run_analysis(
        [
            ("internal_positions.json", internal, "application/json"),
            ("custodian_positions.json", external, "application/json"),
        ]
    )

    assert result["status"] == "review_required"
    assert result["controls_executed"] == 1
    assert result["control_runs"][0]["tool_name"] == "reconcile_positions"
    assert result["issues"][0]["code"] == "position.quantity_mismatch"
    assert len(result["issues"][0]["evidence"]) == 2
    assert result["investigations"][0]["human_decision_required"] is True
    assert result["recommended_human_action"] == "assign_and_monitor"
