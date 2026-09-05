"""Integration gate for the eventual cash-application implementation.

This remains an explicit xfail on the planning-only base branch. It must not be converted to a
pass, skip, or relaxed assertion: integration should supply the documented adapter and meet all
18 observed safety-critical trials.
"""

from __future__ import annotations

import importlib

import pytest

from evals.cash_application.runner import REPEATABILITY_CASES, run_cases
from evals.cash_application.schema import load_cases


def test_product_adapter_runs_all_safety_critical_trials() -> None:
    try:
        module = importlib.import_module("app.cash_application.eval_adapter")
    except ModuleNotFoundError:
        pytest.xfail(
            "integration blocker: app.cash_application.eval_adapter:run_case is not on the "
            "configured hackathon base"
        )
    adapter = module.run_case
    cases = [case for case in load_cases("core") if case.case_id in REPEATABILITY_CASES]
    report = run_cases(cases, adapter, recommended_trials=True)
    summary = report["summary"]
    assert summary["attempted_trials"] == 18
    assert summary["graded_trials"] == 18
    assert summary["passed_trials"] == 18
    assert summary["failed_trials"] == 0
    assert summary["error_trials"] == 0
    assert summary["unsupported_trials"] == 0
    assert summary["false_auto_application_trials"] == 0
