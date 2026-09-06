from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import ValidationError

import app.nav_quality as nav_quality
from app.agent_tools import run_nav_quality_review
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
            if nav_summary is None:
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
            if rules is None:
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
            "status": "ready" if summary else "awaiting_evidence",
            "requires": ["administrator NAV summary"],
        },
        {
            "control": "NAV bridge footing",
            "status": "ready" if summary else "awaiting_evidence",
            "requires": ["administrator NAV summary"],
        },
        {
            "control": "Independent NAV recalculation",
            "status": "ready" if summary else "awaiting_evidence",
            "requires": ["administrator NAV summary"],
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
    if summary is None:
        blockers.append(
            "A structured administrator NAV summary JSON is required to run the existing "
            "NAV quality engine."
        )
        if raw_workbooks:
            blockers.append(
                "A raw NAV workbook was recognised, but the workbook-to-NAV-summary "
                "normalisation adapter is not implemented yet."
            )

    return {
        "workflow": "nav_quality_controller",
        "status": "ready" if summary else "needs_input",
        "inputs": inputs,
        "controls": controls,
        "blockers": blockers,
        "optional_gaps": [
            label
            for label, present in (
                ("investor-level GL", bool(ledger)),
                ("structured side-letter rules", bool(rules)),
            )
            if not present
        ],
        "round_reduction_target": ROUND_REDUCTION_TARGET,
        "control_boundary": (
            "Readiness only determines which existing NAV checks can run. No NAV calculation "
            "or pass/fail decision is made at this stage."
        ),
    }


def _materialise_nav_inputs(
    case: FundManagerCase,
    readiness: dict[str, Any],
    directory: str,
) -> tuple[str, str | None, str | None]:
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

    if paths["nav_summary"] is None:
        raise ValueError(
            "NAV Quality Controller requires a structured administrator NAV summary JSON."
        )
    return paths["nav_summary"], paths["source_ledger"], paths["side_letter_rules"]


def run_case_nav_reconciliation(case: FundManagerCase) -> dict[str, Any]:
    readiness = case.nav_readiness or build_nav_readiness(case)
    if readiness.get("status") != "ready":
        raise ValueError(
            "NAV Quality Controller is not ready. Review the readiness blockers first."
        )

    with TemporaryDirectory(prefix="cherry-nav-quality-") as directory:
        nav_summary, source_ledger, rules = _materialise_nav_inputs(case, readiness, directory)
        result = run_nav_quality_review(nav_summary, source_ledger, rules)

    summary_meta = readiness["inputs"]["nav_summary"]
    result["workflow"] = "nav_quality_controller"
    result["fund_manager_case_id"] = case.case_id
    result["period_end"] = summary_meta["period_end"]
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
