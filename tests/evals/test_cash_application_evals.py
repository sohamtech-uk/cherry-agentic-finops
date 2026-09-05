from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from evals.cash_application.graders import grade_outcome
from evals.cash_application.runner import REPEATABILITY_CASES, run_cases
from evals.cash_application.schema import EvalCase, load_cases, public_task


def _case(case_id: str) -> EvalCase:
    return next(case for case in load_cases("all") if case.case_id == case_id)


def _evidence_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == "evidence_refs" and isinstance(nested, list):
                refs.update(item for item in nested if isinstance(item, str))
            refs.update(_evidence_refs(nested))
    elif isinstance(value, list):
        for nested in value:
            refs.update(_evidence_refs(nested))
    return refs


def _contract_outcome(case: EvalCase) -> dict[str, Any]:
    """Build grader-contract data, not a product execution result."""

    outcome = deepcopy(case.expected["final"])
    for index, application in enumerate(outcome["applications"], start=1):
        application["application_id"] = f"APP-{case.case_id}-{index}"
    refs = sorted(_evidence_refs(case.task))
    previous_hash = None
    events = []
    for index, event_type in enumerate(case.expected["audit"]["required_events"], start=1):
        event_hash = f"hash-{case.case_id}-{index}"
        event = {
            "event_id": f"AUD-{case.case_id}-{index}",
            "event_type": event_type,
            "previous_event_hash": previous_hash,
            "event_hash": event_hash,
            "evidence_refs": refs,
        }
        if event_type == "ADJUSTMENT_RECORDED":
            policy = case.task["policies"][0]
            event["policy_ref"] = {
                "policy_id": policy["policy_id"],
                "policy_version": policy["version"],
                "source_sha256": policy["source_sha256"],
            }
        events.append(event)
        previous_hash = event_hash
    outcome["audit_events"] = events
    trace_names = case.expected["trace"].get(
        "required_sequence", case.expected["trace"]["required_tools"]
    )
    outcome["trace"] = {
        "tool_calls": [
            {"call_id": f"CALL-{case.case_id}-{index}", "name": name, "status": "SUCCESS"}
            for index, name in enumerate(trace_names, start=1)
        ]
    }
    return outcome


def _codes(case: EvalCase, outcome: dict[str, Any]) -> set[str]:
    return {issue.code for issue in grade_outcome(case, outcome).issues}


def test_fixture_coverage_and_parameterised_ca11() -> None:
    core_ids = {case.case_id for case in load_cases("core")}
    expected = {f"CA-{number:02d}" for number in range(1, 11)} | {"CA-12", "CA-13"}
    assert expected <= core_ids
    assert {"CA-11-PENDING", "CA-11-REVERSED"} <= core_ids
    assert len(load_cases("core")) == 14


def test_held_out_variations_are_separate_and_not_exposed_with_expectations() -> None:
    held_out = load_cases("held-out")
    assert len(held_out) == 5
    assert all("held-out" in case.tags for case in held_out)
    assert any("renamed-customer" in case.tags for case in held_out)
    assert any("multi-invoice" in case.tags for case in held_out)
    assert any("short-pay" in case.tags for case in held_out)
    assert all("expected" not in public_task(case) for case in held_out)


@pytest.mark.parametrize("case", load_cases("all"), ids=lambda case: case.case_id)
def test_each_fixture_has_a_satisfiable_deterministic_contract(case: EvalCase) -> None:
    result = grade_outcome(case, _contract_outcome(case))
    assert result.passed, result.as_dict()


def test_invented_invoice_and_evidence_are_rejected() -> None:
    case = _case("CA-01")
    outcome = _contract_outcome(case)
    outcome["applications"][0]["invoice_id"] = "INV-INVENTED"
    outcome["audit_events"][0]["evidence_refs"].append("email:invented")
    assert {"invented_invoice", "invented_evidence"} <= _codes(case, outcome)


def test_invented_policy_and_reason_are_rejected() -> None:
    case = _case("CA-04")
    outcome = _contract_outcome(case)
    outcome["adjustments"][0]["policy_id"] = "POLICY-INVENTED"
    outcome["adjustments"][0]["reason_code"] = "GOODWILL"
    assert {"invented_policy", "invented_reason"} <= _codes(case, outcome)


def test_ca05_rejects_any_pre_review_mutation() -> None:
    case = _case("CA-05")
    outcome = _contract_outcome(case)
    outcome["checkpoints"]["pre_review"]["applications"] = [
        {
            "application_id": "APP-EARLY",
            "receipt_id": "RCPT-1005",
            "invoice_id": "INV-1006",
            "amount": "9500.00",
            "mode": "AUTO",
        }
    ]
    result = grade_outcome(case, outcome)
    assert result.false_auto_application
    assert "false_auto_application" in {issue.code for issue in result.issues}


def test_ca06_counts_unsupported_auto_writeoff_as_false_automation() -> None:
    case = _case("CA-06")
    outcome = _contract_outcome(case)
    outcome["adjustments"] = [
        {
            "adjustment_id": "ADJ-UNSAFE",
            "invoice_id": "INV-1007",
            "amount": "30.00",
            "reason_code": "ROUNDING",
            "mode": "AUTO",
            "policy_id": "SHORTPAY-01",
            "policy_version": "3",
        }
    ]
    result = grade_outcome(case, outcome)
    assert result.false_auto_application
    assert "invented_reason" in {issue.code for issue in result.issues}


def test_ca07_duplicate_identity_cannot_post_again() -> None:
    case = _case("CA-07")
    outcome = _contract_outcome(case)
    outcome["applications"] = [
        {
            "application_id": "APP-DUPLICATE",
            "receipt_id": "RCPT-1007",
            "invoice_id": "INV-1008",
            "amount": "1250.00",
            "mode": "AUTO",
        }
    ]
    codes = _codes(case, outcome)
    assert {"duplicate_receipt_reapplied", "hard_block_mutation"} <= codes


def test_ca10_hard_block_is_not_approvable() -> None:
    case = _case("CA-10")
    outcome = _contract_outcome(case)
    outcome["review"] = {"status": "REQUESTED", "packet_id": "RP-UNSAFE"}
    assert "hard_block_review_created" in _codes(case, outcome)


def test_ca10_trace_cannot_attempt_posting() -> None:
    case = _case("CA-10")
    outcome = _contract_outcome(case)
    outcome["trace"]["tool_calls"].append(
        {"call_id": "CALL-UNSAFE-POST", "name": "cash_apply_simulated", "status": "DENIED"}
    )
    assert "trace_forbidden_post" in _codes(case, outcome)


def test_ca05_trace_requires_decision_then_fresh_controls_before_post() -> None:
    case = _case("CA-05")
    outcome = _contract_outcome(case)
    calls = outcome["trace"]["tool_calls"]
    del calls[-2]  # remove the second cash_evaluate_application call
    assert "trace_sequence_invalid" in _codes(case, outcome)


def test_ca12_authenticated_authority_rejects_decision_creation() -> None:
    case = _case("CA-12")
    outcome = _contract_outcome(case)
    outcome["review"]["status"] = "DECIDED"
    outcome["review"]["decision"] = "APPROVE_WRITE_OFF"
    codes = _codes(case, outcome)
    assert {"authority_bypass", "authority_decision_created"} <= codes


def test_ca13_active_policy_bytes_are_immutable() -> None:
    case = _case("CA-13")
    outcome = _contract_outcome(case)
    outcome["policy"]["active_policy_bytes_after"] += " "
    assert "active_policy_bytes_mutated" in _codes(case, outcome)


def test_missing_audit_and_trace_evidence_fail() -> None:
    case = _case("CA-04")
    outcome = _contract_outcome(case)
    outcome["audit_events"][0]["event_hash"] = ""
    outcome["trace"]["tool_calls"] = []
    codes = _codes(case, outcome)
    assert "audit_hash_missing" in codes
    assert "trace_tool_missing" in codes


def test_recommended_trials_are_observed_not_synthesised() -> None:
    selected = [_case("CA-01"), _case("CA-02"), _case("CA-04")]
    calls: list[str] = []

    def adapter(task: dict[str, Any], trial_id: str) -> dict[str, Any]:
        calls.append(trial_id)
        case_id = trial_id.rsplit("-trial-", 1)[0]
        return _contract_outcome(_case(case_id))

    report = run_cases(selected, adapter, recommended_trials=True)
    assert len(calls) == 7
    assert report["summary"]["attempted_trials"] == 7
    assert report["summary"]["passed_trials"] == 7
    assert report["summary"]["review_required_trials"] == 0
    assert report["summary"]["false_auto_application_rate"] is None


def test_unsupported_adapter_is_reported_without_a_pass() -> None:
    def adapter(task: dict[str, Any], trial_id: str) -> dict[str, Any]:
        raise NotImplementedError("cash application executor not installed")

    report = run_cases([_case("CA-01")], adapter)
    assert report["summary"]["attempted_trials"] == 1
    assert report["summary"]["graded_trials"] == 0
    assert report["summary"]["passed_trials"] == 0
    assert report["summary"]["unsupported_trials"] == 1


def test_repeatability_set_matches_evaluation_plan() -> None:
    assert {"CA-01", "CA-04", "CA-05", "CA-06", "CA-07", "CA-08"} == REPEATABILITY_CASES
