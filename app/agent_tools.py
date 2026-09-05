from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from app.container import get_engine
from app.models import ApprovalRequest, RejectionRequest
from app.nav_quality import (
    parse_administrator_nav_summary,
    parse_investor_level_gl_workbook,
    parse_side_letter_rules,
    review_nav_quality,
)
from app.nav_reconciliation import validate_balance_sheet_equity as _validate_balance_sheet_equity
from app.nav_reconciliation import validate_nav_bridge as _validate_nav_bridge
from app.reconciliation_tools import build_bridge as _build_bridge
from app.reconciliation_tools import calculate_sum as _calculate_sum
from app.reconciliation_tools import compare_values as _compare_values
from app.reconciliation_tools import read_cell as _read_cell
from app.reconciliation_tools import read_excel as _read_excel
from app.statement_tools import compare_dates as _compare_dates
from app.statement_tools import compare_periods as _compare_periods
from app.statement_tools import find_entity as _find_entity
from app.statement_tools import find_section as _find_section
from app.statement_tools import read_document as _read_document
from app.ylookup_datasets import (
    analyse_bank_statement_workbook,
    analyse_investor_gl_workbook,
    analyse_loader_sample,
    inspect_workbook,
)


def run_finance_scenario(
    scenario: Literal["autonomous", "approval", "exception"] = "autonomous",
) -> dict[str, Any]:
    """Run one safe synthetic finance workflow and return its governed outcome.

    Args:
        scenario: autonomous for a low-risk exact match, approval for a high-value exact match,
            or exception for a material amount mismatch.
    """

    workflow = get_engine().run_demo(scenario)
    return workflow.model_dump(mode="json")


def inspect_workflow(workflow_id: str) -> dict[str, Any]:
    """Retrieve a workflow, its reconciliation evidence, control decision and audit events."""

    return get_engine().get(workflow_id).model_dump(mode="json")


def query_database(workflow_id: str) -> dict[str, Any]:
    """Query the stored reconciliation state (evidence, control decision, audit trail) for a
    given workflow id. This is the Reconciliation Agent's read-only lookup into prior work rather
    than a source of new evidence."""

    return inspect_workflow(workflow_id)


def list_open_finance_exceptions() -> dict[str, Any]:
    """Return the current month-end queue and productivity summary."""

    engine = get_engine()
    open_items = [
        workflow.model_dump(mode="json")
        for workflow in engine.list()
        if workflow.status in {"awaiting_approval", "evidence_required"}
    ]
    return {
        "summary": engine.month_end_summary().model_dump(mode="json"),
        "open_items": open_items,
    }


def record_human_approval(workflow_id: str, approver_name: str, note: str) -> dict[str, Any]:
    """Record an explicit human approval and resume a paused workflow.

    Only call this tool after the user explicitly asks to approve the named workflow and supplies
    the approver name. Never infer consent from context.
    """

    return (
        get_engine()
        .approve(workflow_id, ApprovalRequest(actor=approver_name, note=note))
        .model_dump(mode="json")
    )


def reject_workflow(workflow_id: str, reviewer_name: str, reason: str) -> dict[str, Any]:
    """Reject a paused workflow after the user explicitly instructs you to do so."""

    return (
        get_engine()
        .reject(workflow_id, RejectionRequest(actor=reviewer_name, note=reason))
        .model_dump(mode="json")
    )


def _read_file_bytes(file_path: str) -> bytes:
    path = Path(file_path)
    if not path.is_file():
        raise ValueError(f"File path {file_path!r} does not exist.")
    return path.read_bytes()


def identify_ylookup_workbook(workbook_path: str) -> dict[str, Any]:
    """Identify a Ylookup workbook's contract (bank-statement working file, investor GL, loader,
    LP commitments or supporting evidence) without performing any reconciliation calculation.

    Args:
        workbook_path: Local path to an XLSX workbook.
    """

    content = _read_file_bytes(workbook_path)
    return inspect_workbook(content, Path(workbook_path).name)


def reconcile_bank_statement_workbook(
    workbook_path: str,
    pdf_file_names: list[str] | None = None,
) -> dict[str, Any]:
    """Run the deterministic bank-statement-to-journal-entries reconciliation and return its
    review queue. This tool performs the arithmetic; you explain the resulting exceptions.

    Args:
        workbook_path: Local path to the bank-statement working file (Staging Sheet + DIU).
        pdf_file_names: Names of the source bank-statement PDFs supplied alongside the workbook.
    """

    content = _read_file_bytes(workbook_path)
    return analyse_bank_statement_workbook(content, Path(workbook_path).name, pdf_file_names or [])


def reconcile_investor_gl_workbook(workbook_path: str) -> dict[str, Any]:
    """Profile the deterministic investor-level GL source-to-loader reconciliation. This tool
    performs the calculation; you explain mapping gaps and required next steps.

    Args:
        workbook_path: Local path to the investor-level GL workbook.
    """

    content = _read_file_bytes(workbook_path)
    return analyse_investor_gl_workbook(content, Path(workbook_path).name)


def reconcile_loader_sample_workbook(workbook_path: str) -> dict[str, Any]:
    """Validate a target loader sample against the required Ylookup loader contract fields.

    Args:
        workbook_path: Local path to the loader sample or mapping workbook.
    """

    content = _read_file_bytes(workbook_path)
    return analyse_loader_sample(content, Path(workbook_path).name)


def validate_balance_sheet_equity(
    assets: str,
    liabilities: str,
    reported_equity: str,
    tolerance: str = "0.01",
) -> dict[str, Any]:
    """NAV Guardian Check #1: reconcile assets minus liabilities against reported equity.

    This performs the arithmetic deterministically; report the returned status, expected and
    reported figures and difference rather than recomputing them yourself. Use this for a quick
    check when you only have three isolated figures; when you have a full administrator NAV
    summary, call run_nav_quality_review instead for the complete review.

    Args:
        assets: Total balance-sheet assets as a decimal string, e.g. "105200000.00".
        liabilities: Total balance-sheet liabilities as a decimal string.
        reported_equity: Reported partners' capital / equity as a decimal string.
        tolerance: Maximum absolute difference still treated as a rounding pass.
    """

    return _validate_balance_sheet_equity(assets, liabilities, reported_equity, tolerance)


def validate_nav_bridge(
    opening_nav: str,
    contributions: str,
    investment_movement: str,
    fx_movement: str,
    income: str,
    expenses: str,
    distributions: str,
    reported_closing_nav: str,
    tolerance: str = "0.01",
) -> dict[str, Any]:
    """NAV Guardian Check #2: independently recompute the NAV bridge and compare it to the
    administrator's reported closing NAV.

    Closing NAV = Opening NAV + contributions +/- investment movement +/- FX + income - expenses
    - distributions. This performs the arithmetic deterministically; report the returned status
    and figures rather than recomputing them yourself. Use this for a quick check against isolated
    figures; when you have a full administrator NAV summary, call run_nav_quality_review instead
    for the complete review.

    Args:
        opening_nav: Prior-period closing NAV as a decimal string.
        contributions: Capital contributions received in the period.
        investment_movement: Signed change in investment valuations (negative for a loss).
        fx_movement: Signed foreign-exchange movement (negative for an FX loss).
        income: Income earned in the period.
        expenses: Expenses incurred in the period.
        distributions: Distributions paid in the period.
        reported_closing_nav: The administrator's reported closing NAV.
        tolerance: Maximum absolute difference still treated as a rounding pass.
    """

    return _validate_nav_bridge(
        opening_nav,
        contributions,
        investment_movement,
        fx_movement,
        income,
        expenses,
        distributions,
        reported_closing_nav,
        tolerance,
    )


def read_excel(
    workbook_path: str, sheet_name: str | None = None, max_rows: int = 50
) -> dict[str, Any]:
    """Read a worksheet's header row and up to max_rows of data rows, for ad hoc inspection.

    Args:
        workbook_path: Local path to an XLSX workbook.
        sheet_name: Sheet to read; defaults to the workbook's first sheet.
        max_rows: Maximum number of data rows to return, to keep tool output bounded.
    """

    return _read_excel(workbook_path, sheet_name, max_rows)


def read_cell(workbook_path: str, sheet_name: str, cell: str) -> dict[str, Any]:
    """Read a single cell's value by its A1 reference, e.g. "B12".

    Args:
        workbook_path: Local path to an XLSX workbook.
        sheet_name: Sheet containing the cell.
        cell: A1-style cell reference, e.g. "B12".
    """

    return _read_cell(workbook_path, sheet_name, cell)


def calculate_sum(values: list[str]) -> dict[str, Any]:
    """Sum a list of decimal-string monetary values. Use this instead of adding figures yourself.

    Args:
        values: Amounts to sum, each as a decimal string, e.g. ["105200000", "-12700000"].
    """

    return _calculate_sum(values)


def compare_values(expected: str, actual: str, tolerance: str = "0.01") -> dict[str, Any]:
    """Compare two decimal-string values within a tolerance and report whether they match.

    Args:
        expected: The expected/calculated value.
        actual: The reported/administrator value.
        tolerance: Maximum absolute difference still treated as a match.
    """

    return _compare_values(expected, actual, tolerance)


def build_bridge(
    opening_balance: str,
    movements: dict[str, str],
    reported_closing: str,
    tolerance: str = "0.01",
) -> dict[str, Any]:
    """Build an ad hoc accounting bridge: opening balance plus signed movements, compared to a
    reported closing balance. Use this for bridges the packaged checks don't cover — for example
    a single investor's capital account — instead of building the bridge yourself.

    Args:
        opening_balance: The period's opening balance.
        movements: Signed movement amounts keyed by label, e.g. {"contributions": "500000",
            "management_fee": "-125000"}.
        reported_closing: The reported/administrator closing balance to check against.
        tolerance: Maximum absolute difference still treated as a rounding pass.
    """

    return _build_bridge(opening_balance, movements, reported_closing, tolerance)


def run_nav_quality_review(
    nav_summary_path: str,
    source_ledger_path: str | None = None,
    side_letter_rules_path: str | None = None,
) -> dict[str, Any]:
    """Run the full NAV Quality Controller review of an administrator's NAV pack: balance sheet
    footing, NAV bridge footing, independent NAV recalculation, investor capital reconciliation
    and side-letter rule validation, in one deterministic pass. Returns findings, work items and
    a recommended action (ready_to_submit / needs_review / return_to_administrator) — never a
    correction; report what the tool found rather than recomputing any of it yourself.

    Use validate_balance_sheet_equity / validate_nav_bridge instead when you only have isolated
    figures rather than a full NAV summary and optional source ledger.

    Args:
        nav_summary_path: Local path to the administrator's reported NAV summary (.json): legal
            entity, period end, balance sheet, NAV bridge and investor capital lines.
        source_ledger_path: Optional local path to an investor-level GL export (.xlsx) to
            independently recompute the balance sheet, NAV and investor capital against.
        side_letter_rules_path: Optional local path to structured side-letter rules (.json), e.g.
            a management-fee-offsets-called-capital rule for a named investor.
    """

    summary = parse_administrator_nav_summary(_read_file_bytes(nav_summary_path))
    ledger = (
        parse_investor_level_gl_workbook(_read_file_bytes(source_ledger_path))
        if source_ledger_path
        else None
    )
    rules = (
        parse_side_letter_rules(_read_file_bytes(side_letter_rules_path))
        if side_letter_rules_path
        else None
    )
    return review_nav_quality(summary, ledger, rules).model_dump(mode="json")


def read_document(document_path: str) -> dict[str, Any]:
    """Extract a document's full text (PDF, TXT or Markdown), for ad hoc inspection.

    Args:
        document_path: Local path to the document.
    """

    return _read_document(document_path)


def find_section(document_path: str, heading: str) -> dict[str, Any]:
    """Locate a named section by its heading and return the text from that heading up to the
    next heading-like line. Not finding a match is evidence to investigate further, not proof
    the section is absent — the heading may be phrased differently in this document.

    Args:
        document_path: Local path to the document.
        heading: Section heading to search for, e.g. "Subsequent Events".
    """

    return _find_section(document_path, heading)


def find_entity(document_path: str, entity_name: str, context_chars: int = 160) -> dict[str, Any]:
    """Find every mention of a named entity and return the surrounding text for each occurrence.

    Args:
        document_path: Local path to the document.
        entity_name: Entity to search for, e.g. a portfolio company or investor name.
        context_chars: Characters of surrounding context to include on each side of a match.
    """

    return _find_entity(document_path, entity_name, context_chars)


def compare_periods(current_document_path: str, prior_document_path: str) -> dict[str, Any]:
    """Line-diff a current-period document against the prior period's, to surface exactly what
    changed — and what stayed identical, which may be a stale carry-forward. This performs the
    comparison deterministically; report what it found rather than eyeballing the two documents.

    Args:
        current_document_path: Local path to the current-period document.
        prior_document_path: Local path to the prior-period document.
    """

    return _compare_periods(current_document_path, prior_document_path)


def compare_dates(current_document_path: str, prior_document_path: str) -> dict[str, Any]:
    """Extract every date-like string from a current and a prior document and report which
    dates are new, which disappeared, and which are identical in both — an unchanged date is a
    candidate for a stale rolled-forward disclosure, not proof of one.

    Args:
        current_document_path: Local path to the current-period document.
        prior_document_path: Local path to the prior-period document.
    """

    return _compare_dates(current_document_path, prior_document_path)
