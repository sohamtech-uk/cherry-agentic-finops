"""The "Analyse" orchestrator: given a classified batch of fund evidence, decide what control
each source needs (the "agent determines required controls" stage) and actually run whichever of
those this codebase can run end-to-end today, producing an issue register in the same shape as
the target QC report (status, issues found, critical/material counts, evidence-backed issues).

This is deliberately honest about what it can and cannot do yet, matching the control boundary
used throughout this codebase: never claim a control ran if the necessary evidence was not
present, and never fabricate a finding. Recognised source types that don't yet have an execution
path wired up here are reported as "not_yet_available" in the control plan, not silently skipped
and not faked.

Today, the only control that can run end-to-end from a batch of uploaded files alone (no separate
structured extraction step) is period-over-period statement comparison: two files classified
financial_statement are enough to run app.statement_tools.compare_periods/compare_dates directly.
Every other recognised type (nav_workbook, investor_gl, positions, trades, cash_transactions,
lpa, side_letter, ...) is planned but reported as not yet runnable from this endpoint, since each
needs its own structured extraction or a second comparison side that classification alone does not
provide (see app.nav_quality, app.fund_reconciliation, app.contracts for the engines that do run
these once that wiring exists).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.fund_manager_classification import ClassifiedSource, classify_sources
from app.statement_tools import compare_dates, compare_periods

ControlStatus = Literal["executed", "not_yet_available", "needs_pairing"]

# Which control a recognised source type maps to, and a short reason when it can't run yet.
_CONTROL_FOR_TYPE: dict[str, str] = {
    "nav_workbook": "NAV footing / bridge reconciliation",
    "investor_gl": "Investor capital reconciliation",
    "lp_commitments": "Commitment / capital-call arithmetic",
    "bank_statement_working_file": "Bank statement to journal-entry reconciliation",
    "loader_template": "Loader contract validation",
    "capital_call_notice": "Capital-call / commitment cross-check",
    "lpa": "Governing-document rule extraction",
    "side_letter": "Side-letter rule validation",
    "bank_statement": "Cash reconciliation",
    "investor_report": "Investor reporting cross-check",
    "positions": "Position reconciliation",
    "trades": "Trade reconciliation",
    "bank_transactions": "Cash reconciliation",
    "cash_transactions": "Cash reconciliation",
    "financial_statement": "Period-over-period statement comparison",
}

_NOT_YET_AVAILABLE_NOTE = (
    "Recognised, but running this control needs a dedicated extraction/execution step this "
    "endpoint doesn't wire up yet -- it never ran, so no result is reported for it."
)


@dataclass
class ControlPlanEntry:
    source_id: str
    filename: str
    detected_type: str
    control: str
    status: ControlStatus
    note: str


def _build_control_plan(sources: list[ClassifiedSource]) -> list[ControlPlanEntry]:
    financial_statement_sources = [
        s for s in sources if s["detected_type"] == "financial_statement"
    ]
    plan: list[ControlPlanEntry] = []

    for source in sources:
        detected_type = source["detected_type"]
        control = _CONTROL_FOR_TYPE.get(detected_type)
        if control is None:
            continue  # unknown_* sources have no control to plan -- they need review, not a run.

        if detected_type == "financial_statement":
            if len(financial_statement_sources) >= 2:
                plan.append(
                    ControlPlanEntry(
                        source_id=source["id"],
                        filename=source["filename"],
                        detected_type=detected_type,
                        control=control,
                        status="executed",
                        note="Compared against another uploaded financial statement.",
                    )
                )
            else:
                plan.append(
                    ControlPlanEntry(
                        source_id=source["id"],
                        filename=source["filename"],
                        detected_type=detected_type,
                        control=control,
                        status="needs_pairing",
                        note=(
                            "Needs a second (prior-period) financial statement to compare against."
                        ),
                    )
                )
            continue

        plan.append(
            ControlPlanEntry(
                source_id=source["id"],
                filename=source["filename"],
                detected_type=detected_type,
                control=control,
                status="not_yet_available",
                note=_NOT_YET_AVAILABLE_NOTE,
            )
        )

    return plan


def _statement_pair_issues(
    financial_statement_items: list[tuple[str, bytes, str | None]],
) -> list[dict[str, Any]]:
    """Run the one control this endpoint can execute end-to-end today: comparing the earliest and
    latest uploaded financial statements for stale/rolled-forward disclosures."""

    if len(financial_statement_items) < 2:
        return []

    prior_name, prior_content, _ = financial_statement_items[0]
    current_name, current_content, _ = financial_statement_items[-1]

    period_diff = compare_periods(current_content, current_name, prior_content, prior_name)
    date_diff = compare_dates(current_content, current_name, prior_content, prior_name)

    issues: list[dict[str, Any]] = []
    if not period_diff["identical"]:
        issues.append(
            {
                "id": "ISS-STMT-DIFF",
                "title": "Financial statement text changed between periods",
                "severity": "medium",
                "summary": (
                    f"{len(period_diff['lines_added'])} line(s) added and "
                    f"{len(period_diff['lines_removed'])} line(s) removed between "
                    f"{prior_name!r} and {current_name!r}."
                ),
                "evidence": [
                    {"source": prior_name, "detail": "Prior-period statement"},
                    {"source": current_name, "detail": "Current-period statement"},
                ],
                "recommended_action": (
                    "Review the diff for subsequent events that should have moved section, or "
                    "text that was rolled forward without an update."
                ),
            }
        )
    if date_diff["dates_in_both"]:
        issues.append(
            {
                "id": "ISS-STMT-STALE-DATE",
                "title": "Dates unchanged between periods",
                "severity": "medium",
                "summary": (
                    f"{len(date_diff['dates_in_both'])} date(s) appear unchanged in both "
                    f"{prior_name!r} and {current_name!r}: {', '.join(date_diff['dates_in_both'])}."
                ),
                "evidence": [
                    {"source": prior_name, "detail": "Prior-period statement"},
                    {"source": current_name, "detail": "Current-period statement"},
                ],
                "recommended_action": (
                    "Confirm each date is still accurate for this period rather than carried "
                    "forward from the prior disclosure."
                ),
            }
        )
    return issues


def run_analysis(files: list[tuple[str, bytes, str | None]]) -> dict[str, Any]:
    """Classify a batch of uploaded files, build a control plan, and run whichever control this
    endpoint can execute end-to-end today (see module docstring). Returns a QC-report-shaped
    result: overall status, issue counts, the control plan and any issues actually found.

    Args:
        files: (file_name, content, content_type) tuples in upload order.
    """

    sources = classify_sources(files)
    plan = _build_control_plan(sources)

    financial_statement_items = [
        (name, content, content_type)
        for (name, content, content_type), source in zip(files, sources, strict=True)
        if source["detected_type"] == "financial_statement"
    ]
    issues = _statement_pair_issues(financial_statement_items)

    critical = sum(1 for issue in issues if issue["severity"] == "high")
    material = sum(1 for issue in issues if issue["severity"] in {"high", "medium"})

    return {
        "status": "review_required" if issues else "clean",
        "sources": sources,
        "control_plan": [entry.__dict__ for entry in plan],
        "issues_found": len(issues),
        "critical": critical,
        "material": material,
        "issues": issues,
        "control_boundary": (
            "Deterministic tools produced every figure and comparison above; no LLM decided a "
            "pass/fail. Controls marked not_yet_available never ran -- they are not silent passes."
        ),
    }
