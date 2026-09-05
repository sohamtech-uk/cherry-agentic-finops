"""Bounded-agentic planning, deterministic execution, and investigation orchestration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from app.bank_statement_tools import extract_bank_statement_balances
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
from app.ylookup_datasets import (
    analyse_bank_statement_workbook,
    analyse_investor_gl_workbook,
    analyse_loader_sample,
)

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


ControlExecutor = Callable[
    [list[EvidenceItem], ControlPlanEntry],
    tuple[dict[str, Any], list[ExceptionItem]],
]


@dataclass(frozen=True)
class ControlDefinition:
    control_id: str
    name: str
    source_type: str
    required_evidence: tuple[str, ...]
    required_roles: tuple[str, str] | None = None
    tool_name: str | None = None
    executor: ControlExecutor | None = None
    version: str = "1.0"


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


def _pair_cross_type(
    by_type: dict[str, list[EvidenceItem]], evidence_types: tuple[str, ...], roles: tuple[str, str]
) -> tuple[list[EvidenceItem], dict[str, str], float, str] | None:
    """Pair one source from each of two distinct required evidence types. Unlike same-type
    pairing there is no filename ambiguity to resolve: the evidence type itself fixes the
    comparison role (e.g. a bank statement is always the external side of a cash reconciliation),
    so this only needs at least one source of each type to be present."""

    first = by_type.get(evidence_types[0], [])
    second = by_type.get(evidence_types[1], [])
    if not first or not second:
        return None
    confidence = 0.95 if len(first) == 1 and len(second) == 1 else 0.7
    reason = (
        "Each required evidence type was matched to its fixed comparison role."
        if confidence == 0.95
        else "Multiple sources matched a required evidence type; the first uploaded source of "
        "each type was used and disclosed for human verification."
    )
    return (
        [first[0], second[0]],
        {first[0].source["id"]: roles[0], second[0].source["id"]: roles[1]},
        confidence,
        reason,
    )


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
) -> ControlExecutor:
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


def _bank_cash_executor(
    items: list[EvidenceItem], plan: ControlPlanEntry
) -> tuple[dict[str, Any], list[ExceptionItem]]:
    """Reconcile a real bank statement's extracted closing balance against an internal
    cash-balance export, reusing app.fund_reconciliation.reconcile_cash unchanged -- the statement
    is just a differently-sourced "external" side of the same comparison CTRL-CASH-001 runs."""

    by_role = {plan.source_roles[item.source["id"]]: item for item in items}
    external_item, internal_item = by_role["external"], by_role["internal"]
    external_balances = extract_bank_statement_balances(
        external_item.content, external_item.source["filename"]
    )
    internal_balances = parse_cash_balances(internal_item.content)
    result = reconcile_cash(internal_balances, external_balances)
    return result.model_dump(mode="json"), result.to_exceptions()


def _bank_workbook_executor(
    items: list[EvidenceItem], plan: ControlPlanEntry
) -> tuple[dict[str, Any], list[ExceptionItem]]:
    """Run the organiser's bank-statements-to-journal-entries working file through the existing
    app.ylookup_datasets.analyse_bank_statement_workbook adapter and translate its review queue
    into the common ExceptionItem shape. Any bank statement PDFs uploaded alongside the workbook
    are passed through for the workbook's own filename-based cross-check; none are required for
    the workbook analysis to run."""

    workbook_item = next(
        item for item in items if item.source["detected_type"] == "bank_statement_working_file"
    )
    pdf_items = [item for item in items if item.source["detected_type"] == "bank_statement"]
    result = analyse_bank_statement_workbook(
        workbook_item.content,
        workbook_item.source["filename"],
        [item.source["filename"] for item in pdf_items],
    )

    exceptions = [
        ExceptionItem(
            category="data_quality",
            code=(
                "bank_workflow."
                + "_".join(reason.casefold().replace(" ", "_") for reason in row["reasons"])
            ),
            key=row["exception_id"],
            title=f"{row['account_name'] or workbook_item.source['filename']}: "
            f"{', '.join(row['reasons'])}",
            detail=row["narrative"] or "No narrative available for this staging row.",
            severity=FindingSeverity.WARNING,
        )
        for row in result["exceptions"]
    ]
    if not result["journal_line_count_matches"]:
        exceptions.append(
            ExceptionItem(
                category="data_quality",
                code="bank_workflow.journal_line_count_mismatch",
                key="journal-line-count",
                title=f"{workbook_item.source['filename']}: journal line count does not match "
                "expected postings",
                detail=(
                    f"Expected {result['journal_expected_lines']} DIU journal line(s) (2 per "
                    f"transaction across {result['total_transactions']} transaction(s)) but "
                    f"found {result['journal_lines']}."
                ),
                severity=FindingSeverity.WARNING,
            )
        )
    return result, exceptions


def _single_source_executor(
    analyser: Callable[[bytes, str], dict[str, Any]],
    *,
    failure_code: str,
    failure_title: str,
) -> ControlExecutor:
    def execute(
        items: list[EvidenceItem], plan: ControlPlanEntry
    ) -> tuple[dict[str, Any], list[ExceptionItem]]:
        item = items[0]
        output = analyser(item.content, item.source["filename"])
        exceptions: list[ExceptionItem] = []
        if output.get("status") == "review_required":
            exceptions.append(
                ExceptionItem(
                    category="data_quality",
                    code=failure_code,
                    key=plan.control_id,
                    title=failure_title,
                    detail=(
                        "The deterministic workbook contract check found missing or invalid "
                        "required fields."
                    ),
                    severity=FindingSeverity.WARNING,
                )
            )
        return output, exceptions

    return execute


CONTROL_CATALOGUE: tuple[ControlDefinition, ...] = (
    ControlDefinition(
        "CTRL-NAV-001",
        "NAV footing / bridge reconciliation",
        "nav_workbook",
        ("nav_workbook",),
    ),
    ControlDefinition(
        "CTRL-INV-001",
        "Investor GL source validation",
        "investor_gl",
        ("investor_gl",),
        tool_name="analyse_investor_gl_workbook",
        executor=_single_source_executor(
            analyse_investor_gl_workbook,
            failure_code="investor_gl.contract_invalid",
            failure_title="Investor GL source validation failed",
        ),
    ),
    ControlDefinition(
        "CTRL-COMMIT-001",
        "Commitment / capital-call arithmetic",
        "lp_commitments",
        ("lp_commitments", "capital_call_notice"),
    ),
    ControlDefinition(
        "CTRL-BANK-WORK-001",
        "Bank statement to journal-entry reconciliation",
        "bank_statement_working_file",
        ("bank_statement_working_file", "bank_statement"),
        tool_name="analyse_bank_statement_workbook",
        executor=_bank_workbook_executor,
    ),
    ControlDefinition(
        "CTRL-LOAD-001",
        "Loader contract validation",
        "loader_template",
        ("loader_template",),
        tool_name="analyse_loader_sample",
        executor=_single_source_executor(
            analyse_loader_sample,
            failure_code="loader.contract_invalid",
            failure_title="Loader contract validation failed",
        ),
    ),
    ControlDefinition(
        "CTRL-CALL-001",
        "Capital-call / commitment cross-check",
        "capital_call_notice",
        ("capital_call_notice", "lp_commitments"),
    ),
    ControlDefinition(
        "CTRL-LPA-001",
        "Governing-document rule extraction",
        "lpa",
        ("lpa",),
    ),
    ControlDefinition(
        "CTRL-SIDE-001",
        "Side-letter rule validation",
        "side_letter",
        ("side_letter", "lpa"),
    ),
    ControlDefinition(
        "CTRL-BANK-001",
        "Bank statement cash reconciliation",
        "bank_statement",
        ("bank_statement", "cash_transactions"),
        required_roles=("external", "internal"),
        tool_name="reconcile_cash",
        executor=_bank_cash_executor,
    ),
    ControlDefinition(
        "CTRL-STMT-001",
        "Period-over-period statement comparison",
        "financial_statement",
        ("financial_statement",),
        required_roles=("prior", "current"),
        tool_name="compare_financial_statements",
        executor=_statement_executor,
    ),
    ControlDefinition(
        "CTRL-REPORT-001",
        "Investor reporting cross-check",
        "investor_report",
        ("investor_report", "investor_gl"),
    ),
    ControlDefinition(
        "CTRL-POS-001",
        "Position reconciliation",
        "positions",
        ("positions",),
        required_roles=("internal", "external"),
        tool_name="reconcile_positions",
        executor=_reconciliation_executor(parse_positions, reconcile_positions),
    ),
    ControlDefinition(
        "CTRL-TRD-001",
        "Trade reconciliation",
        "trades",
        ("trades",),
        required_roles=("internal", "external"),
        tool_name="reconcile_trades",
        executor=_reconciliation_executor(parse_trades, reconcile_trades),
    ),
    ControlDefinition(
        "CTRL-BANK-TXN-001",
        "Cash transaction matching",
        "bank_transactions",
        ("bank_transactions", "cash_transactions"),
    ),
    ControlDefinition(
        "CTRL-CASH-001",
        "Cash reconciliation",
        "cash_transactions",
        ("cash_transactions",),
        required_roles=("internal", "external"),
        tool_name="reconcile_cash",
        executor=_reconciliation_executor(parse_cash_balances, reconcile_cash),
    ),
)


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

            if definition.executor is None:
                missing_types = [
                    evidence_type
                    for evidence_type in definition.required_evidence
                    if evidence_type not in by_type
                ]
                missing = [*missing_types, "registered deterministic execution adapter"]
                plans.append(
                    ControlPlanEntry(
                        definition.control_id,
                        definition.version,
                        definition.name,
                        [item.source["id"] for item in candidates],
                        {},
                        list(definition.required_evidence),
                        "needs_evidence",
                        "The control catalogue recognises this evidence type and its applicable "
                        "control, but a registered deterministic adapter is not available yet.",
                        1.0,
                        missing_evidence=missing,
                        tool_name=definition.tool_name,
                    )
                )
                continue

            if definition.required_roles is None:
                # A registered adapter that consumes every source of its required evidence
                # type(s) directly (e.g. a working-file analyser) rather than a two-sided
                # comparison -- no role pairing to resolve, so this is ready whenever the primary
                # evidence type is present at all.
                auxiliary = [
                    item
                    for evidence_type in definition.required_evidence
                    if evidence_type != definition.source_type
                    for item in by_type.get(evidence_type, [])
                ]
                selected = candidates + auxiliary
                plans.append(
                    ControlPlanEntry(
                        definition.control_id,
                        definition.version,
                        definition.name,
                        [item.source["id"] for item in selected],
                        {},
                        list(definition.required_evidence),
                        "ready",
                        "The registered adapter consumes every source of its required evidence "
                        "types directly; no comparison-side pairing is needed.",
                        0.9,
                        tool_name=definition.tool_name,
                    )
                )
                continue

            heterogeneous = len(set(definition.required_evidence)) > 1
            paired = (
                _pair_cross_type(by_type, definition.required_evidence, definition.required_roles)
                if heterogeneous
                else _pair(candidates, definition.required_roles)
            )
            if paired:
                selected, roles, confidence, reason = paired
                plans.append(
                    ControlPlanEntry(
                        definition.control_id,
                        definition.version,
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
                if heterogeneous:
                    missing = [
                        evidence_type
                        for evidence_type in definition.required_evidence
                        if not by_type.get(evidence_type)
                    ] or ["a clearly labelled comparison pair"]
                else:
                    missing = (
                        [definition.required_roles[1]]
                        if len(candidates) == 1
                        else ["a clearly labelled comparison pair"]
                    )
                plans.append(
                    ControlPlanEntry(
                        definition.control_id,
                        definition.version,
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
        definition = catalogue[plan.control_id]
        if definition.executor is None:
            raise RuntimeError(f"{plan.control_id} was marked ready without an executor")
        try:
            output, generated = definition.executor(selected, plan)
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
