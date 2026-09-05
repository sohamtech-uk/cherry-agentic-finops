"""Bounded-agentic planning, deterministic execution, and investigation orchestration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from app.exception_investigation import investigate_exception
from app.fund_manager_classification import (
    ClassifiedSource,
    classify_and_validate_sources,
)
from app.fund_reconciliation import (
    EvidenceSource,
    ExceptionItem,
    attach_evidence,
    parse_cash_balances,
    parse_positions,
    parse_trades,
    prioritise_exceptions,
    reconcile_cash,
    reconcile_positions,
    reconcile_trades,
)
from app.private_markets import FindingSeverity
from app.statement_tools import compare_dates, compare_periods

PlanStatus = Literal["ready", "executed", "needs_evidence", "manual_review", "failed"]


@dataclass(frozen=True)
class EvidenceItem:
    source: ClassifiedSource
    content: bytes
    content_type: str | None


@dataclass
class ControlPlanEntry:
    control_id: str
    control_version: str
    control: str
    source_ids: list[str]
    source_roles: dict[str, str]
    required_evidence: list[str]
    status: PlanStatus
    reasoning: str
    confidence: float
    missing_evidence: list[str] = field(default_factory=list)
    tool_name: str | None = None


@dataclass(frozen=True)
class ControlDefinition:
    control_id: str
    name: str
    source_type: str
    required_roles: tuple[str, str]
    tool_name: str
    executor: Callable[
        [list[EvidenceItem], ControlPlanEntry],
        tuple[dict[str, Any], list[ExceptionItem]],
    ]


def _role_from_filename(filename: str) -> str | None:
    """Infer roles only from explicit and reportable filename signals."""
    name = filename.casefold().replace("-", "_").replace(" ", "_")
    signals = {
        "prior": ("prior", "previous", "comparative"),
        "current": ("current", "latest", "draft"),
        "internal": ("internal", "ledger", "book", "manager", "source"),
        "external": ("external", "custodian", "administrator", "admin", "broker", "bank"),
    }
    matches = [role for role, words in signals.items() if any(word in name for word in words)]
    return matches[0] if len(matches) == 1 else None


def _pair(
    items: list[EvidenceItem], roles: tuple[str, str]
) -> tuple[list[EvidenceItem], dict[str, str], float, str] | None:
    if len(items) < 2:
        return None
    matched: dict[str, EvidenceItem] = {}
    for item in items:
        role = _role_from_filename(item.source["filename"])
        if role in roles and role not in matched:
            matched[role] = item
    if all(role in matched for role in roles):
        selected = [matched[role] for role in roles]
        return (
            selected,
            {item.source["id"]: role for role, item in zip(roles, selected, strict=True)},
            0.95,
            "Explicit filename role signals supplied both comparison sides.",
        )
    if len(items) == 2:
        return (
            items,
            {items[0].source["id"]: roles[0], items[1].source["id"]: roles[1]},
            0.65,
            "Exactly two compatible sources were supplied; upload order was used and disclosed "
            "for human verification.",
        )
    return None


def _statement_executor(
    items: list[EvidenceItem], plan: ControlPlanEntry
) -> tuple[dict[str, Any], list[ExceptionItem]]:
    by_role = {plan.source_roles[item.source["id"]]: item for item in items}
    prior, current = by_role["prior"], by_role["current"]
    period = compare_periods(
        current.content,
        current.source["filename"],
        prior.content,
        prior.source["filename"],
    )
    dates = compare_dates(
        current.content,
        current.source["filename"],
        prior.content,
        prior.source["filename"],
    )
    exceptions: list[ExceptionItem] = []
    if not period["identical"]:
        exceptions.append(
            ExceptionItem(
                category="statement",
                code="statement.period_text_changed",
                key="period-comparison",
                title="Financial statement text changed between periods",
                detail=(
                    f"{len(period['lines_added'])} line(s) added and "
                    f"{len(period['lines_removed'])} line(s) removed."
                ),
                severity=FindingSeverity.WARNING,
            )
        )
    if dates["dates_in_both"]:
        exceptions.append(
            ExceptionItem(
                category="statement",
                code="statement.stale_date",
                key="date-comparison",
                title="Dates unchanged between periods",
                detail=f"Dates present in both statements: {', '.join(dates['dates_in_both'])}.",
                severity=FindingSeverity.WARNING,
            )
        )
    return {"period_comparison": period, "date_comparison": dates}, exceptions


def _reconciliation_executor(
    parser: Callable[[bytes], list[Any]], reconciler: Callable[..., Any]
) -> Callable[
    [list[EvidenceItem], ControlPlanEntry],
    tuple[dict[str, Any], list[ExceptionItem]],
]:
    def execute(
        items: list[EvidenceItem], plan: ControlPlanEntry
    ) -> tuple[dict[str, Any], list[ExceptionItem]]:
        by_role = {plan.source_roles[item.source["id"]]: item for item in items}
        result = reconciler(
            parser(by_role["internal"].content),
            parser(by_role["external"].content),
        )
        return result.model_dump(mode="json"), result.to_exceptions()

    return execute


CONTROL_CATALOGUE: tuple[ControlDefinition, ...] = (
    ControlDefinition(
        "CTRL-STMT-001",
        "Period-over-period statement comparison",
        "financial_statement",
        ("prior", "current"),
        "compare_financial_statements",
        _statement_executor,
    ),
    ControlDefinition(
        "CTRL-POS-001",
        "Position reconciliation",
        "positions",
        ("internal", "external"),
        "reconcile_positions",
        _reconciliation_executor(parse_positions, reconcile_positions),
    ),
    ControlDefinition(
        "CTRL-TRD-001",
        "Trade reconciliation",
        "trades",
        ("internal", "external"),
        "reconcile_trades",
        _reconciliation_executor(parse_trades, reconcile_trades),
    ),
    ControlDefinition(
        "CTRL-CASH-001",
        "Cash reconciliation",
        "cash_transactions",
        ("internal", "external"),
        "reconcile_cash",
        _reconciliation_executor(parse_cash_balances, reconcile_cash),
    ),
)

KNOWN_UNWIRED_CONTROLS = {
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
    "bank_transactions": "Cash transaction matching",
}


class ControlPlanningAgent:
    """Select tools from a closed catalogue and explain every decision."""

    def plan(self, items: list[EvidenceItem]) -> list[ControlPlanEntry]:
        plans: list[ControlPlanEntry] = []
        by_type: dict[str, list[EvidenceItem]] = {}
        for item in items:
            by_type.setdefault(item.source["detected_type"], []).append(item)

        for definition in CONTROL_CATALOGUE:
            candidates = by_type.get(definition.source_type, [])
            if not candidates:
                continue
            paired = _pair(candidates, definition.required_roles)
            if paired:
                selected, roles, confidence, reason = paired
                plans.append(
                    ControlPlanEntry(
                        definition.control_id,
                        "1.0",
                        definition.name,
                        [item.source["id"] for item in selected],
                        roles,
                        list(definition.required_roles),
                        "ready",
                        reason,
                        confidence,
                        tool_name=definition.tool_name,
                    )
                )
            else:
                missing = (
                    [definition.required_roles[1]]
                    if len(candidates) == 1
                    else ["a clearly labelled comparison pair"]
                )
                plans.append(
                    ControlPlanEntry(
                        definition.control_id,
                        "1.0",
                        definition.name,
                        [item.source["id"] for item in candidates],
                        {},
                        list(definition.required_roles),
                        "needs_evidence",
                        "The planning agent refused to guess source roles because a reliable "
                        "comparison pair could not be formed.",
                        1.0,
                        missing_evidence=missing,
                        tool_name=definition.tool_name,
                    )
                )

        registered_types = {definition.source_type for definition in CONTROL_CATALOGUE}
        for source_type, candidates in by_type.items():
            if (
                source_type in registered_types
                or source_type.startswith("unknown")
                or source_type == "unknown"
            ):
                continue
            control = KNOWN_UNWIRED_CONTROLS.get(source_type)
            if control:
                plans.append(
                    ControlPlanEntry(
                        f"CTRL-PENDING-{source_type.upper().replace('_', '-')}",
                        "0",
                        control,
                        [item.source["id"] for item in candidates],
                        {},
                        [source_type],
                        "needs_evidence",
                        "The agent recognised the applicable control, but no registered "
                        "deterministic adapter can consume this evidence shape yet.",
                        1.0,
                        missing_evidence=["registered deterministic execution adapter"],
                    )
                )
        return plans


def _lineage_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _evidence_sources(items: list[EvidenceItem]) -> list[EvidenceSource]:
    return [
        EvidenceSource(
            source_id=item.source["id"],
            filename=item.source["filename"],
            sha256=item.source["sha256"],
        )
        for item in items
    ]


def run_analysis(files: list[tuple[str, bytes, str | None]]) -> dict[str, Any]:
    sources = classify_and_validate_sources(files)
    all_items = [
        EvidenceItem(source, content, content_type)
        for (_, content, content_type), source in zip(files, sources, strict=True)
    ]
    items = [item for item in all_items if item.source["validation_status"] == "accepted"]
    item_by_id = {item.source["id"]: item for item in all_items}
    plans = ControlPlanningAgent().plan(items)
    catalogue = {definition.control_id: definition for definition in CONTROL_CATALOGUE}
    runs: list[dict[str, Any]] = []
    exceptions: list[ExceptionItem] = []

    for plan in plans:
        if plan.status != "ready":
            selected = [item_by_id[source_id] for source_id in plan.source_ids]
            gap = ExceptionItem(
                category="data_quality",
                code=f"control.{plan.control_id.casefold()}.evidence_missing",
                key=plan.control_id,
                title=f"{plan.control}: required evidence is unavailable",
                detail=(
                    f"{plan.reasoning} Missing: "
                    f"{', '.join(plan.missing_evidence) or 'executable evidence'}."
                ),
                severity=FindingSeverity.WARNING,
            )
            exceptions.extend(attach_evidence([gap], sources=_evidence_sources(selected)))
            continue
        selected = [item_by_id[source_id] for source_id in plan.source_ids]
        run_id = _lineage_id(plan.control_id, *plan.source_ids)
        try:
            output, generated = catalogue[plan.control_id].executor(selected, plan)
            generated = attach_evidence(generated, sources=_evidence_sources(selected))
            plan.status = "executed"
            runs.append(
                {
                    "run_id": run_id,
                    "control_id": plan.control_id,
                    "tool_name": plan.tool_name,
                    "source_ids": plan.source_ids,
                    "status": "completed",
                    "output": output,
                    "exception_count": len(generated),
                }
            )
            exceptions.extend(generated)
        except (ValueError, ValidationError, KeyError) as exc:
            plan.status = "failed"
            runs.append(
                {
                    "run_id": run_id,
                    "control_id": plan.control_id,
                    "tool_name": plan.tool_name,
                    "source_ids": plan.source_ids,
                    "status": "failed",
                    "error": str(exc),
                    "exception_count": 0,
                }
            )
            failure = ExceptionItem(
                category="data_quality",
                code=f"control.{plan.control_id.casefold()}.execution_failed",
                key=plan.control_id,
                title=f"{plan.control}: deterministic control could not execute",
                detail=str(exc),
                severity=FindingSeverity.HIGH,
            )
            exceptions.extend(attach_evidence([failure], sources=_evidence_sources(selected)))

    for item in all_items:
        if item.source["validation_status"] == "accepted":
            continue
        unknown = ExceptionItem(
            category="data_quality",
            code="evidence.unclassified",
            key=item.source["id"],
            title=f"{item.source['filename']}: evidence was rejected",
            detail="; ".join(item.source["validation_errors"])
            or ("No recognised evidence contract matched this source."),
            severity=FindingSeverity.WARNING,
        )
        exceptions.extend(attach_evidence([unknown], sources=_evidence_sources([item])))

    ranked = prioritise_exceptions(exceptions)
    investigations: list[dict[str, Any]] = []
    for index, exception in enumerate(ranked, start=1):
        result = investigate_exception(ranked, target_exception=exception)
        evidence_ids = [ref.source_id for ref in result.exception.evidence]
        investigations.append(
            {
                "investigation_id": (
                    f"INV-{index:03d}-"
                    f"{_lineage_id(exception.code, *(evidence_ids or ['no-evidence']))}"
                ),
                "selection_reason": (
                    "Selected from the deterministic exception queue in severity and "
                    "materiality order."
                ),
                "tool_calls": [
                    "prioritise_exceptions",
                    "correlate_by_key",
                    "route_by_category_and_severity",
                ],
                "result": result.model_dump(mode="json"),
                "lineage": {
                    "exception_code": exception.code,
                    "evidence_source_ids": evidence_ids,
                    "evidence_hashes": [ref.sha256 for ref in result.exception.evidence],
                    "control_run_ids": [
                        run["run_id"] for run in runs if set(run["source_ids"]) & set(evidence_ids)
                    ],
                },
                "human_decision_required": result.next_step != "accept_and_close",
            }
        )

    executed = sum(plan.status == "executed" for plan in plans)
    incomplete = sum(plan.status in {"needs_evidence", "manual_review", "failed"} for plan in plans)
    substantive = [item for item in ranked if item.category != "data_quality"]
    if substantive:
        status = "review_required"
    elif executed and not incomplete:
        status = "clean"
    elif executed:
        status = "partially_evaluated"
    else:
        status = "insufficient_evidence"

    manifest = [
        {"id": source["id"], "sha256": source["sha256"], "type": source["detected_type"]}
        for source in sources
    ]
    manifest_json = json.dumps(manifest, sort_keys=True)
    return {
        "case_id": f"CASE-{_lineage_id(manifest_json)}",
        "status": status,
        "sources": sources,
        "evidence_manifest_hash": hashlib.sha256(manifest_json.encode()).hexdigest(),
        "control_plan": [asdict(plan) for plan in plans],
        "control_runs": runs,
        "controls_executed": executed,
        "controls_incomplete": incomplete,
        "issues_found": len(ranked),
        "critical": sum(item.severity == FindingSeverity.HIGH for item in ranked),
        "material": sum(
            item.severity in {FindingSeverity.HIGH, FindingSeverity.WARNING} for item in ranked
        ),
        "issues": [
            dict(item.model_dump(mode="json"), id=f"EXC-{index:03d}")
            for index, item in enumerate(ranked, start=1)
        ],
        "investigations": investigations,
        "recommended_human_action": (
            investigations[0]["result"]["next_step"]
            if investigations
            else ("review_missing_evidence" if incomplete else "accept_and_close")
        ),
        "control_boundary": (
            "The planning agent selected registered tools and explained its choices. "
            "Deterministic controls produced every exception; investigations only correlated "
            "evidence and recommended human action, and never changed a control result."
        ),
    }
