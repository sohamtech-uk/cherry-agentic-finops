"""CLI runner for deterministic cash-application evaluations.

An adapter is deliberately required for trial execution. The eval package contains no product
implementation and never treats fixture validation as a CA scenario pass.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, cast

from evals.cash_application.graders import EvaluationResult, grade_outcome
from evals.cash_application.schema import EvalCase, load_cases, public_task

REPEATABILITY_CASES = {"CA-01", "CA-04", "CA-05", "CA-06", "CA-07", "CA-08"}
AdapterResult = dict[str, Any] | Awaitable[dict[str, Any]]
Adapter = Callable[[dict[str, Any], str], AdapterResult]


def _load_adapter(reference: str) -> Adapter:
    try:
        module_name, function_name = reference.split(":", 1)
    except ValueError as exc:
        raise ValueError("Adapter must use module:function syntax") from exc
    function = getattr(importlib.import_module(module_name), function_name)
    if not callable(function):
        raise TypeError(f"{reference} is not callable")
    return cast(Adapter, function)


async def _await_adapter(result: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    return await result


def _invoke(adapter: Adapter, task: dict[str, Any], trial_id: str) -> dict[str, Any]:
    result = adapter(task, trial_id)
    if inspect.isawaitable(result):
        result = asyncio.run(_await_adapter(result))
    if not isinstance(result, dict):
        raise TypeError("Adapter must return a mapping")
    return result


def _select_cases(suite: str, selected_ids: Sequence[str]) -> list[EvalCase]:
    cases = load_cases(suite)
    if not selected_ids:
        return cases
    selected = [case for case in cases if case.case_id in selected_ids]
    missing = sorted(set(selected_ids) - {case.case_id for case in selected})
    if missing:
        raise ValueError(f"Unknown case ids in {suite} suite: {missing}")
    return selected


def _trial_count(case: EvalCase, default: int, recommended: bool) -> int:
    if recommended and case.case_id in REPEATABILITY_CASES:
        return 3
    return default


def _summary(trials: list[dict[str, Any]]) -> dict[str, Any]:
    graded = [trial for trial in trials if trial["status"] == "GRADED"]
    passed = [trial for trial in graded if trial["result"]["passed"]]
    review_required = [trial for trial in graded if trial["result"]["review_required"]]
    false_auto = [trial for trial in review_required if trial["result"]["false_auto_application"]]
    return {
        "attempted_trials": len(trials),
        "graded_trials": len(graded),
        "unsupported_trials": sum(trial["status"] == "UNSUPPORTED" for trial in trials),
        "error_trials": sum(trial["status"] == "ERROR" for trial in trials),
        "passed_trials": len(passed),
        "failed_trials": len(graded) - len(passed),
        "review_required_trials": len(review_required),
        "false_auto_application_trials": len(false_auto),
        "false_auto_application_rate": (
            f"{len(false_auto)}/{len(review_required)}" if review_required else None
        ),
    }


def run_cases(
    cases: Sequence[EvalCase],
    adapter: Adapter,
    *,
    default_trials: int = 1,
    recommended_trials: bool = False,
) -> dict[str, Any]:
    """Execute real adapter trials and return only actually observed results."""

    trial_rows: list[dict[str, Any]] = []
    for case in cases:
        for number in range(1, _trial_count(case, default_trials, recommended_trials) + 1):
            trial_id = f"{case.case_id}-trial-{number}"
            started = time.perf_counter()
            try:
                outcome = _invoke(adapter, public_task(case), trial_id)
                result: EvaluationResult = grade_outcome(case, outcome)
                row: dict[str, Any] = {
                    "trial_id": trial_id,
                    "status": "GRADED",
                    "result": result.as_dict(),
                }
            except NotImplementedError as exc:
                row = {"trial_id": trial_id, "status": "UNSUPPORTED", "reason": str(exc)}
            except Exception as exc:  # adapters are an explicit external boundary
                row = {
                    "trial_id": trial_id,
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                }
            row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            trial_rows.append(row)
    return {"summary": _summary(trial_rows), "trials": trial_rows}


def _write_report(report: dict[str, Any], path: Path | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if path is not None:
        path.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate fixtures; does not run CA trials")
    validate.add_argument("--suite", choices=("core", "held-out", "all"), default="all")

    run = subparsers.add_parser("run", help="Execute cases through an implementation adapter")
    run.add_argument("--adapter", required=True, help="Python callable as module:function")
    run.add_argument("--suite", choices=("core", "held-out", "all"), default="core")
    run.add_argument("--case", action="append", default=[], dest="case_ids")
    run.add_argument("--trials", type=int, default=1)
    run.add_argument(
        "--recommended-trials",
        action="store_true",
        help="Run CA-01/04/05/06/07/08 three times; other cases use --trials",
    )
    run.add_argument("--report", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        cases = load_cases(args.suite)
        print(
            json.dumps(
                {
                    "fixture_validation": "PASS",
                    "suite": args.suite,
                    "case_count": len(cases),
                    "case_ids": [case.case_id for case in cases],
                    "scenario_trials_run": 0,
                },
                indent=2,
            )
        )
        return 0

    if args.trials < 1:
        raise ValueError("--trials must be at least 1")
    cases = _select_cases(args.suite, args.case_ids)
    report = run_cases(
        cases,
        _load_adapter(args.adapter),
        default_trials=args.trials,
        recommended_trials=args.recommended_trials,
    )
    _write_report(report, args.report)
    summary = report["summary"]
    failures = summary["failed_trials"] + summary["error_trials"] + summary["unsupported_trials"]
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
