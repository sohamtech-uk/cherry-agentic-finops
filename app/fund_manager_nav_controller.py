from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import ValidationError

import app.nav_quality as nav_quality
from app.agent_tools import reconcile_investor_gl_workbook, run_nav_quality_review
from app.fund_manager_cases import FundManagerCase
from app.fund_manager_stages import investigate_case_execution
from app.nav_review_history import get_nav_review_history_store

ROUND_REDUCTION_TARGET = {
    "transcript_baseline": "3-7 review iterations",
    "target": "1-2 review iterations",
    "measurement": "actual rounds_to_close from NAV review history",
    "claim_boundary": (
        "This is a product target, not a guaranteed outcome. Actual reduction is measured from "
        "recorded NAV submissions."
    ),
}


def _accepted_sources(case: FundManagerCase) -> list[dict[str, Any]]:
    return [
        source
        for source in case.classification.get("sources", [])
        if source.get("validation_status") == "accepted"
    ]


def _file_by_source_id(
    case: FundManagerCase, source_id: str
) -> tuple[str, bytes, str | None] | None:
    for index, item in enumerate(case.files, start=1):
        if source_id == f"SRC-{index:02d}":
            return item
    return None


def _probe_nav_inputs(case: FundManagerCase) -> dict[str, Any]:
    nav_summary: dict[str, Any] | None = None
    ledger: dict[str, Any] | None = None
    rules: dict[str, Any] | None = None
    raw_nav_workbooks: list[dict[str, Any]] = []

    accepted = {source.get("id"): source for source in _accepted_sources(case)}
    for index, (filename, content, _) in enumerate(case.files, start=1):
        source_id = f"SRC-{index:02d}"
        source = accepted.get(source_id)
        if source and source.get("detected_type") == "nav_workbook":
            raw_nav_workbooks.append({"source_id": source_id, "filename": filename})

        lowered = filename.casefold()
        if lowered.endswith(".json"):
            if nav_summary is None and source and source.get("detected_type") == "nav_summary":
                try:
                    parsed = nav_quality.parse_administrator_nav_summary(content)
                    nav_summary = {
                        "source_id": source_id,
                        "filename": filename,
                        "legal_entity": parsed.legal_entity,
                        "period_end": parsed.period_end.isoformat(),
                        "currency": parsed.currency,
                    }
                    continue
                except (ValueError, ValidationError, json.JSONDecodeError):
                    pass
            if rules is None and source and source.get("detected_type") == "side_letter_rules":
                try:
                    parsed_rules = nav_quality.parse_side_letter_rules(content)
                    if parsed_rules:
                        rules = {
                            "source_id": source_id,
                            "filename": filename,
                            "rule_count": len(parsed_rules),
                        }
                except (ValueError, ValidationError, json.JSONDecodeError):
                    pass

        if (
            lowered.endswith(".xlsx")
            and ledger is None
            and source
            and source.get("detected_type") == "investor_gl"
        ):
            try:
                parsed_ledger = nav_quality.parse_investor_level_gl_workbook(content)
                ledger = {
                    "source_id": source_id,
                    "filename": filename,
                    "period_start": parsed_ledger.period_start.isoformat(),
                    "period_end": parsed_ledger.period_end.isoformat(),
                    "warning_count": len(parsed_ledger.warnings),
                }
            except (ValueError, ValidationError):
                pass

    return {
        "nav_summary": nav_summary,
        "source_ledger": ledger,
        "side_letter_rules": rules,
        "raw_nav_workbooks": raw_nav_workbooks,
    }


def build_nav_readiness(case: FundManagerCase) -> dict[str, Any]:
    inputs = _probe_nav_inputs(case)
    summary = inputs["nav_summary"]
    ledger = inputs["source_ledger"]
    rules = inputs["side_letter_rules"]
    raw_workbooks = inputs["raw_nav_workbooks"]

    controls = [
        {
            "control": "Balance sheet footing",
            "status": "ready" if summary else "optional_evidence",
            "requires": ["administrator NAV summary"],
        },
        {
            "control": "NAV bridge footing",
            "status": "ready" if summary else "optional_evidence",
            "requires": ["administrator NAV summary"],
        },
        {
            "control": "Independent NAV recalculation",
            "status": "ready" if summary else "optional_evidence",
            "requires": ["administrator NAV summary"],
        },
        {
            "control": "Investor GL source validation",
            "status": "ready" if ledger else "optional_evidence",
            "requires": ["investor-level GL"],
        },
        {
            "control": "Balance sheet vs source ledger",
            "status": "ready" if summary and ledger else "optional_evidence",
            "requires": ["administrator NAV summary", "investor-level GL"],
        },
        {
            "control": "Investor capital reconciliation",
            "status": "ready" if summary and ledger else "optional_evidence",
            "requires": ["administrator NAV summary", "investor-level GL"],
        },
        {
            "control": "Side-letter rule validation",
            "status": "ready" if summary and rules else "optional_evidence",
            "requires": ["administrator NAV summary", "structured side-letter rules"],
        },
    ]

    blockers: list[str] = []
    if summary is None and ledger is None:
        blockers.append(
            "Add at least one supported NAV evidence source before reconciliation: an "
            "administrator NAV summary or an investor-level GL."
        )
        if raw_workbooks:
            blockers.append(
                "A raw NAV workbook was recognised, but the workbook-to-NAV-summary "
                "normalisation adapter is not implemented yet."
            )

    return {
        "workflow": "nav_quality_controller",
        "status": "ready" if summary or ledger else "needs_input",
        "mode": "full_nav_review" if summary else "partial_source_review" if ledger else "waiting",
        "inputs": inputs,
        "controls": controls,
        "blockers": blockers,
        "optional_gaps": [
            label
            for label, present in (
                ("administrator NAV summary", bool(summary)),
                ("investor-level GL", bool(ledger)),
                ("structured side-letter rules", bool(rules)),
            )
            if not present
        ],
        "round_reduction_target": ROUND_REDUCTION_TARGET,
        "control_boundary": (
            "Readiness determines which supported NAV checks can run from the evidence supplied. "
            "Missing optional evidence skips dependent checks rather than blocking all "
            "reconciliation."
        ),
    }


def _materialise_nav_inputs(
    case: FundManagerCase,
    readiness: dict[str, Any],
    directory: str,
) -> tuple[str | None, str | None, str | None]:
    paths: dict[str, str | None] = {
        "nav_summary": None,
        "source_ledger": None,
        "side_letter_rules": None,
    }
    for key in paths:
        meta = readiness.get("inputs", {}).get(key)
        if not meta:
            continue
        source = _file_by_source_id(case, str(meta["source_id"]))
        if source is None:
            continue
        filename, content, _ = source
        path = Path(directory) / Path(filename).name
        path.write_bytes(content)
        paths[key] = str(path)

    return paths["nav_summary"], paths["source_ledger"], paths["side_letter_rules"]


def _partial_ledger_result(
    case: FundManagerCase,
    readiness: dict[str, Any],
    source_ledger: str,
) -> dict[str, Any]:
    profile = reconcile_investor_gl_workbook(source_ledger)
    ledger_meta = readiness["inputs"]["source_ledger"]
    missing_summary_finding = {
        "code": "nav_summary.optional_missing",
        "title": "Administrator NAV summary not supplied",
        "detail": (
            "Investor-level GL validation completed, but balance-sheet footing, NAV bridge, "
            "independent NAV recalculation and summary-to-ledger comparisons were skipped."
        ),
        "severity": "warning",
    }
    return {
        "case_id": case.case_id,
        "legal_entity": case.fund_name or "Investor GL case",
        "ledger_supplied": True,
        "side_letter_rules_supplied": bool(readiness["inputs"].get("side_letter_rules")),
        "partial": True,
        "source_profile": profile,
        "review": {
            "action": "needs_review",
            "controls_passed": 1,
            "exceptions_open": 1,
            "findings": [missing_summary_finding],
            "work_items": [
                {
                    "title": "Review partial NAV evidence coverage",
                    "detail": (
                        "Continue with the investor GL result or add an administrator NAV summary "
                        "later to enable the full NAV control set."
                    ),
                }
            ],
        },
        "root_causes": [],
        "iteration": {"round_number": 1, "prior_rounds": 0},
        "evidence": {"input_sha256": {}, "review_sha256": None},
        "period_end": ledger_meta.get("period_end"),
        "financial_boundary": (
            "This partial review validates the supplied investor GL and records evidence gaps; "
            "it does not infer missing administrator NAV figures or amend the official NAV."
        ),
    }


def run_case_nav_reconciliation(case: FundManagerCase) -> dict[str, Any]:
    readiness = case.nav_readiness or build_nav_readiness(case)
    if readiness.get("status") != "ready":
        raise ValueError(
            "NAV Quality Controller is not ready. Add at least one supported NAV evidence source."
        )

    with TemporaryDirectory(prefix="cherry-nav-quality-") as directory:
        nav_summary, source_ledger, rules = _materialise_nav_inputs(case, readiness, directory)
        if nav_summary is not None:
            result = run_nav_quality_review(nav_summary, source_ledger, rules)
            summary_meta = readiness["inputs"]["nav_summary"]
            result["period_end"] = summary_meta["period_end"]
        elif source_ledger is not None:
            result = _partial_ledger_result(case, readiness, source_ledger)
        else:
            raise ValueError("No supported NAV evidence is available for reconciliation.")

    result["workflow"] = "nav_quality_controller"
    result["fund_manager_case_id"] = case.case_id
    result["stage"] = "reconciled"
    result["round_reduction_target"] = ROUND_REDUCTION_TARGET
    return result


def _nav_execution_for_agent(result: dict[str, Any]) -> dict[str, Any]:
    review = result.get("review", {})
    findings = review.get("findings", [])
    exception_findings = [finding for finding in findings if finding.get("severity") != "pass"]
    issues = []
    for index, finding in enumerate(exception_findings, start=1):
        issues.append(
            {
                "id": f"NAV-{index:03d}",
                "category": "nav_quality",
                "code": finding.get("code", "nav.exception"),
                "title": finding.get("title", "NAV quality exception"),
                "summary": finding.get("detail", ""),
                "severity": finding.get("severity", "warning"),
                "recommended_action": review.get("action", "needs_review"),
                "evidence": [],
            }
        )
    return {
        "status": review.get("action", "needs_review"),
        "issues": issues,
        "nav_quality_result": result,
        "review_objective": (
            "Investigate every open NAV issue and every deterministic root-cause group in this "
            "single review. Produce a complete remediation view so the administrator can correct "
            "all detectable breaks together instead of discovering one new issue per round."
        ),
    }


def _build_remediation_package(
    reconciliation: dict[str, Any], investigation: dict[str, Any]
) -> dict[str, Any]:
    review = reconciliation.get("review", {})
    findings = review.get("findings", [])
    exception_findings = [finding for finding in findings if finding.get("severity") != "pass"]
    work_items = review.get("work_items", [])
    root_causes = reconciliation.get("root_causes", [])
    investigations = investigation.get("investigations", [])

    return {
        "mode": "consolidated_first_pass",
        "purpose": (
            "Return every detectable NAV break, grouped root cause, evidence gap and required "
            "administrator action together in one package."
        ),
        "finding_count": len(exception_findings),
        "root_cause_count": len(root_causes),
        "work_item_count": len(work_items),
        "findings": exception_findings,
        "root_causes": root_causes,
        "work_items": work_items,
        "agent_investigations": investigations,
        "recommended_action": review.get("action"),
        "round_reduction_target": ROUND_REDUCTION_TARGET,
    }


async def run_case_nav_review(case: FundManagerCase) -> dict[str, Any]:
    if case.nav_reconciliation is None:
        raise ValueError("NAV reconciliation must complete before agentic NAV review.")

    investigation = await investigate_case_execution(
        _nav_execution_for_agent(case.nav_reconciliation)
    )
    investigation["workflow"] = "nav_quality_controller"
    investigation["stage"] = "reviewed"
    investigation["deterministic_action"] = case.nav_reconciliation.get("review", {}).get("action")
    investigation["root_causes"] = case.nav_reconciliation.get("root_causes", [])
    investigation["remediation_package"] = _build_remediation_package(
        case.nav_reconciliation, investigation
    )
    investigation["round_reduction_target"] = ROUND_REDUCTION_TARGET
    investigation["control_boundary"] = (
        "The agent explains and consolidates deterministic NAV findings. It cannot change the "
        "NAV calculation, control result or official NAV."
    )
    return investigation


def get_case_nav_history(case: FundManagerCase) -> dict[str, Any]:
    reconciliation = case.nav_reconciliation
    if reconciliation is None:
        return {
            "available": False,
            "reason": "Run NAV reconciliation before requesting history.",
            "round_reduction_target": ROUND_REDUCTION_TARGET,
        }
    legal_entity = str(reconciliation.get("legal_entity") or "")
    period_end = str(reconciliation.get("period_end") or "")
    if not legal_entity or not period_end:
        return {
            "available": False,
            "reason": "NAV reconciliation did not return legal entity and period end.",
            "round_reduction_target": ROUND_REDUCTION_TARGET,
        }
    summary = get_nav_review_history_store().case_history(legal_entity, period_end)
    if summary is None:
        return {
            "available": False,
            "reason": "No NAV review history has been recorded for this fund and period.",
            "round_reduction_target": ROUND_REDUCTION_TARGET,
        }
    return {
        "available": True,
        "history": summary.model_dump(mode="json"),
        "round_reduction_target": ROUND_REDUCTION_TARGET,
    }
