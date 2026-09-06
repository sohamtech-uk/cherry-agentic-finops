from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from app.config import get_settings
from app.container import get_engine
from app.exception_investigation import investigate_exception as _investigate_exception
from app.fund_reconciliation import (
    CashBalance,
    EvidenceSource,
    ExceptionItem,
    parse_administrator_expenses,
    parse_administrator_fees,
    parse_cash_balances,
    parse_expected_expense_allocations,
    parse_exposure_limits,
    parse_fee_rules,
    parse_positions,
    parse_prices,
    parse_trades,
)
from app.fund_reconciliation import (
    attach_evidence as _attach_evidence,
)
from app.fund_reconciliation import (
    detect_exposure_breaches as _detect_exposure_breaches,
)
from app.fund_reconciliation import (
    detect_stale_prices as _detect_stale_prices,
)
from app.fund_reconciliation import (
    detect_unsettled_trades as _detect_unsettled_trades,
)
from app.fund_reconciliation import (
    prioritise_exceptions as _prioritise_exceptions,
)
from app.fund_reconciliation import (
    reconcile_cash as _reconcile_cash,
)
from app.fund_reconciliation import (
    reconcile_expense_allocations as _reconcile_expense_allocations,
)
from app.fund_reconciliation import (
    reconcile_positions as _reconcile_positions,
)
from app.fund_reconciliation import (
    reconcile_trades as _reconcile_trades,
)
from app.fund_reconciliation import (
    validate_management_fees as _validate_management_fees,
)
from app.models import ApprovalRequest, RejectionRequest
from app.nav_exceptions import group_exceptions_by_root_cause
from app.nav_health_check import build_daily_health_check
from app.nav_quality import (
    SideLetterRule,
    build_case_id,
    parse_administrator_nav_summary,
    parse_investor_level_gl_workbook,
    parse_side_letter_rules,
    report_hash,
    review_nav_quality,
    sha256_hex,
)
from app.nav_reconciliation import validate_balance_sheet_equity as _validate_balance_sheet_equity
from app.nav_reconciliation import validate_nav_bridge as _validate_nav_bridge
from app.nav_review_history import get_nav_review_history_store
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


def _read_input_file(file_path: str, *, kind: str, extension: str) -> bytes:
    """Read a JSON reconciliation input, applying the same size and extension checks as the
    POST /api/nav-quality/review endpoint, so a bad path fails with a clear ValueError instead of
    an unbounded read or a raw parser exception."""

    content = _read_file_bytes(file_path)
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ValueError(
            f"{kind} {file_path!r} exceeds the {get_settings().max_upload_mb} MB upload limit."
        )
    if not file_path.lower().endswith(extension):
        raise ValueError(f"{kind} {file_path!r} must be a {extension} file.")
    return content


def _parse_input_file(
    file_path: str, *, kind: str, extension: str, parser: Callable[[bytes], Any]
) -> Any:
    """Read and parse a reconciliation input, wrapping any parse failure with the file path and
    kind so the caller knows which of several inputs was invalid."""

    content = _read_input_file(file_path, kind=kind, extension=extension)
    try:
        return parser(content)
    except (ValueError, ValidationError) as exc:
        raise ValueError(f"Invalid {kind.lower()} {file_path!r}: {exc}") from exc


def _parse_input_file_with_evidence(
    file_path: str, *, source_id: str, kind: str, extension: str, parser: Callable[[bytes], Any]
) -> tuple[Any, EvidenceSource]:
    """Like _parse_input_file, but also returns the EvidenceSource (filename and SHA-256 hash) for
    the file just read, so the caller can stamp document lineage onto the exceptions this input
    produces via app.fund_reconciliation.attach_evidence. Reads the file exactly once."""

    content = _read_input_file(file_path, kind=kind, extension=extension)
    try:
        parsed = parser(content)
    except (ValueError, ValidationError) as exc:
        raise ValueError(f"Invalid {kind.lower()} {file_path!r}: {exc}") from exc
    source = EvidenceSource(
        source_id=source_id, filename=Path(file_path).name, sha256=sha256_hex(content)
    )
    return parsed, source


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
    and side-letter rule validation, in one deterministic pass. Returns a case_id, the review
    (findings, work items and a recommended action — ready_to_submit / needs_review /
    return_to_administrator), root_causes (the same findings grouped by underlying cause and
    ranked by materiality — read this instead of the flat finding list when triaging), an
    iteration.round_number for this fund/period (this submission is recorded automatically; use
    get_nav_case_iterations for the full history), and per-input evidence hashes. Never a
    correction; report what the tool found rather than recomputing or regrouping any of it
    yourself.

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

    summary_content = _read_input_file(nav_summary_path, kind="NAV summary", extension=".json")
    try:
        summary = parse_administrator_nav_summary(summary_content)
    except (ValueError, ValidationError) as exc:
        raise ValueError(f"Invalid administrator NAV summary {nav_summary_path!r}: {exc}") from exc

    source_ledger_path = (source_ledger_path or "").strip() or None
    ledger = None
    ledger_hash: str | None = None
    if source_ledger_path is not None:
        ledger_content = _read_input_file(
            source_ledger_path, kind="Source ledger", extension=".xlsx"
        )
        try:
            ledger = parse_investor_level_gl_workbook(ledger_content)
        except (ValueError, ValidationError) as exc:
            raise ValueError(f"Invalid source ledger {source_ledger_path!r}: {exc}") from exc
        ledger_hash = sha256_hex(ledger_content)

    side_letter_rules_path = (side_letter_rules_path or "").strip() or None
    rules: list[SideLetterRule] = []
    rules_hash: str | None = None
    if side_letter_rules_path is not None:
        rules_content = _read_input_file(
            side_letter_rules_path, kind="Side-letter rules", extension=".json"
        )
        try:
            rules = parse_side_letter_rules(rules_content)
        except (ValueError, ValidationError) as exc:
            raise ValueError(
                f"Invalid side-letter rules {side_letter_rules_path!r}: {exc}"
            ) from exc
        rules_hash = sha256_hex(rules_content)

    report = review_nav_quality(summary, ledger=ledger, side_letter_rules=rules)
    root_causes = group_exceptions_by_root_cause(report)
    summary_hash = sha256_hex(summary_content)
    case_id = build_case_id(summary_hash, ledger_hash or "NO_LEDGER", rules_hash or "NO_RULES")
    round_ = get_nav_review_history_store().record_round(
        legal_entity=summary.legal_entity,
        period_end=summary.period_end.isoformat(),
        action=report.action,
        controls_passed=report.controls_passed,
        exceptions_open=report.exceptions_open,
        case_id=case_id,
        root_causes=root_causes,
    )

    return {
        "case_id": case_id,
        "legal_entity": summary.legal_entity,
        "ledger_supplied": ledger is not None,
        "side_letter_rules_supplied": bool(rules),
        "iteration": {
            "round_number": round_.round_number,
            "prior_rounds": round_.round_number - 1,
        },
        "review": report.model_dump(mode="json"),
        "root_causes": [group.model_dump(mode="json") for group in root_causes],
        "evidence": {
            "input_sha256": {
                "nav_summary": summary_hash,
                "source_ledger": ledger_hash,
                "side_letter_rules": rules_hash,
            },
            "review_sha256": report_hash(report),
        },
        "financial_boundary": (
            "This service reviews the NAV pack and recommends an action; it never posts a "
            "correcting journal entry or amends the official NAV."
        ),
    }


def read_document(document_path: str) -> dict[str, Any]:
    """Extract a document's full text (PDF, TXT or Markdown), for ad hoc inspection.

    Args:
        document_path: Local path to the document.
    """

    path = Path(document_path)
    return _read_document(_read_file_bytes(document_path), path.name)


def find_section(document_path: str, heading: str) -> dict[str, Any]:
    """Locate a named section by its heading and return the text from that heading up to the
    next heading-like line. Not finding a match is evidence to investigate further, not proof
    the section is absent — the heading may be phrased differently in this document.

    Args:
        document_path: Local path to the document.
        heading: Section heading to search for, e.g. "Subsequent Events".
    """

    path = Path(document_path)
    return _find_section(_read_file_bytes(document_path), path.name, heading)


def find_entity(document_path: str, entity_name: str, context_chars: int = 160) -> dict[str, Any]:
    """Find every mention of a named entity and return the surrounding text for each occurrence.

    Args:
        document_path: Local path to the document.
        entity_name: Entity to search for, e.g. a portfolio company or investor name.
        context_chars: Characters of surrounding context to include on each side of a match.
    """

    path = Path(document_path)
    return _find_entity(_read_file_bytes(document_path), path.name, entity_name, context_chars)


def compare_periods(current_document_path: str, prior_document_path: str) -> dict[str, Any]:
    """Line-diff a current-period document against the prior period's, to surface exactly what
    changed — and what stayed identical, which may be a stale carry-forward. This performs the
    comparison deterministically; report what it found rather than eyeballing the two documents.

    Args:
        current_document_path: Local path to the current-period document.
        prior_document_path: Local path to the prior-period document.
    """

    current_path = Path(current_document_path)
    prior_path = Path(prior_document_path)
    return _compare_periods(
        _read_file_bytes(current_document_path),
        current_path.name,
        _read_file_bytes(prior_document_path),
        prior_path.name,
    )


def compare_dates(current_document_path: str, prior_document_path: str) -> dict[str, Any]:
    """Extract every date-like string from a current and a prior document and report which
    dates are new, which disappeared, and which are identical in both — an unchanged date is a
    candidate for a stale rolled-forward disclosure, not proof of one.

    Args:
        current_document_path: Local path to the current-period document.
        prior_document_path: Local path to the prior-period document.
    """

    current_path = Path(current_document_path)
    prior_path = Path(prior_document_path)
    return _compare_dates(
        _read_file_bytes(current_document_path),
        current_path.name,
        _read_file_bytes(prior_document_path),
        prior_path.name,
    )


def get_nav_case_iterations(legal_entity: str, period_end: str) -> dict[str, Any]:
    """Return how many NAV review rounds this fund/period has taken so far through
    run_nav_quality_review, and — once it reaches ready_to_submit — how many rounds it took to
    close. This measures the actual iteration count for one case; it is not an estimate.

    Args:
        legal_entity: The fund/legal entity name exactly as reported in the NAV summary.
        period_end: The reporting period end date (ISO format), exactly as reported.
    """

    summary = get_nav_review_history_store().case_history(legal_entity, period_end)
    if summary is None:
        return {
            "legal_entity": legal_entity,
            "period_end": period_end,
            "found": False,
            "message": "No review has been recorded for this fund/period yet.",
        }
    return {"found": True, **summary.model_dump(mode="json")}


def get_nav_iteration_metrics() -> dict[str, Any]:
    """Return aggregate NAV review iteration metrics across every fund/period reviewed so far:
    how many rounds cases typically take to reach ready_to_submit, and how many rounds currently
    open cases have taken. Use this to answer "how many iterations does NAV review actually take"
    from recorded submissions rather than asserting a target figure.
    """

    return get_nav_review_history_store().metrics().model_dump(mode="json")


def run_daily_fund_health_check() -> dict[str, Any]:
    """Return a portfolio-level health check across every fund/period reviewed so far: which are
    ready_to_submit, which need attention, and — for those — the root causes still open as of
    their latest round. Built entirely from recorded review rounds (via run_nav_quality_review);
    report its entries directly rather than re-deriving fund status yourself. Running this daily
    is a scheduling choice outside this tool, not something it does itself.
    """

    return build_daily_health_check(get_nav_review_history_store()).model_dump(mode="json")


def reconcile_positions(
    internal_positions_path: str, external_positions_path: str
) -> dict[str, Any]:
    """Compare an internal fund position record against an external one (administrator or
    custodian), matched by security_id. Flags missing positions on either side, quantity breaks
    and market value breaks. Report the returned breaks and counts; the exceptions list is the
    same breaks in the common shape prioritise_exceptions expects.

    Args:
        internal_positions_path: Local path to the internal position export (.json): an array,
            or an object with a positions array, of {fund, security_id, quantity, price, ...}.
        external_positions_path: Local path to the external (administrator/custodian) position
            export in the same shape.
    """

    internal, internal_source = _parse_input_file_with_evidence(
        internal_positions_path,
        source_id="internal_positions",
        kind="Internal positions",
        extension=".json",
        parser=parse_positions,
    )
    external, external_source = _parse_input_file_with_evidence(
        external_positions_path,
        source_id="external_positions",
        kind="External positions",
        extension=".json",
        parser=parse_positions,
    )
    result = _reconcile_positions(internal, external)
    exceptions = _attach_evidence(
        result.to_exceptions(), sources=[internal_source, external_source]
    )
    return {
        **result.model_dump(mode="json"),
        "exceptions": [item.model_dump(mode="json") for item in exceptions],
    }


def reconcile_cash(internal_cash_path: str, external_cash_path: str) -> dict[str, Any]:
    """Compare internal fund cash balances against an external source (bank/custodian statement),
    matched by (account, currency). Flags missing balances on either side and balance mismatches.

    Args:
        internal_cash_path: Local path to the internal cash-balance export (.json): an array, or
            an object with a cash_balances array, of {fund, account, currency, balance, ...}.
        external_cash_path: Local path to the external cash-balance export in the same shape.
    """

    internal, internal_source = _parse_input_file_with_evidence(
        internal_cash_path,
        source_id="internal_cash",
        kind="Internal cash balances",
        extension=".json",
        parser=parse_cash_balances,
    )
    external, external_source = _parse_input_file_with_evidence(
        external_cash_path,
        source_id="external_cash",
        kind="External cash balances",
        extension=".json",
        parser=parse_cash_balances,
    )
    result = _reconcile_cash(internal, external)
    exceptions = _attach_evidence(
        result.to_exceptions(), sources=[internal_source, external_source]
    )
    return {
        **result.model_dump(mode="json"),
        "exceptions": [item.model_dump(mode="json") for item in exceptions],
    }


def compare_bank_statement_cash(
    bank_statement_path: str,
    internal_cash_path: str,
    account: str,
    currency: str,
    balance: str,
) -> dict[str, Any]:
    """Compare an internal cash balance against a bank statement's closing balance, matched by
    (account, currency). This tool performs the arithmetic deterministically -- it never reads or
    interprets the statement's raw text itself, so report only what it returns, never a figure you
    computed yourself.

    A bank statement's layout is too varied for a fixed rule to read reliably (label wording,
    IBAN vs. routing/account number, an implied vs. explicit currency), so extracting the account,
    currency and closing/available balance is your job: call read_document on
    bank_statement_path first, find the closing/available balance and the account identifier in
    its text, and pass exactly what you found here. This tool re-reads the statement file only to
    stamp tamper-evident lineage (filename, SHA-256 hash) on any resulting exception -- it never
    re-derives or double-checks the figures you extracted.

    Args:
        bank_statement_path: Local path to the bank statement PDF (used only for lineage; its
            content is not re-parsed here).
        internal_cash_path: Local path to the internal cash-balance export (.json): an array, or
            an object with a cash_balances array, of {fund, account, currency, balance, ...}.
        account: The account identifier or IBAN you found in the bank statement's text.
        currency: The ISO currency code you found, or reasonably inferred, from the statement.
        balance: The closing/available balance you found, as a decimal string (e.g. "12345.67").
    """

    internal, internal_source = _parse_input_file_with_evidence(
        internal_cash_path,
        source_id="internal_cash",
        kind="Internal cash balances",
        extension=".json",
        parser=parse_cash_balances,
    )
    bank_statement_content = _read_file_bytes(bank_statement_path)
    try:
        external = [
            CashBalance(
                fund=Path(bank_statement_path).stem,
                account=account,
                currency=currency,
                balance=balance,
            )
        ]
    except (ValueError, TypeError, ArithmeticError, ValidationError) as exc:
        raise ValueError(
            f"Invalid extracted bank statement balance for {bank_statement_path!r}: {exc}"
        ) from exc
    external_source = EvidenceSource(
        source_id="external_bank_statement",
        filename=Path(bank_statement_path).name,
        sha256=sha256_hex(bank_statement_content),
    )
    result = _reconcile_cash(internal, external)
    exceptions = _attach_evidence(
        result.to_exceptions(), sources=[internal_source, external_source]
    )
    return {
        **result.model_dump(mode="json"),
        "exceptions": [item.model_dump(mode="json") for item in exceptions],
    }


def reconcile_trades(internal_trades_path: str, external_trades_path: str) -> dict[str, Any]:
    """Compare an internal trade blotter against an external one (broker/custodian
    confirmations), matched by trade_id. Flags missing trades on either side, and side, quantity
    or price mismatches on trades present in both.

    Args:
        internal_trades_path: Local path to the internal trade export (.json): an array, or an
            object with a trades array, of {trade_id, fund, security_id, side, quantity, price,
            trade_date, settlement_date, status}.
        external_trades_path: Local path to the external trade export in the same shape.
    """

    internal, internal_source = _parse_input_file_with_evidence(
        internal_trades_path,
        source_id="internal_trades",
        kind="Internal trades",
        extension=".json",
        parser=parse_trades,
    )
    external, external_source = _parse_input_file_with_evidence(
        external_trades_path,
        source_id="external_trades",
        kind="External trades",
        extension=".json",
        parser=parse_trades,
    )
    result = _reconcile_trades(internal, external)
    exceptions = _attach_evidence(
        result.to_exceptions(), sources=[internal_source, external_source]
    )
    return {
        **result.model_dump(mode="json"),
        "exceptions": [item.model_dump(mode="json") for item in exceptions],
    }


def detect_stale_prices(prices_path: str, as_of: str, max_age_days: int = 3) -> dict[str, Any]:
    """Flag any security price older than max_age_days as of the given date. Severity escalates
    to HIGH beyond twice the threshold. Report the findings; do not judge staleness yourself.

    Args:
        prices_path: Local path to the price export (.json): an array, or an object with a
            prices array, of {security_id, price, price_date, ...}.
        as_of: Control date to measure staleness against, as YYYY-MM-DD.
        max_age_days: Maximum age in days still treated as fresh.
    """

    prices, prices_source = _parse_input_file_with_evidence(
        prices_path, source_id="prices", kind="Prices", extension=".json", parser=parse_prices
    )
    findings = _detect_stale_prices(
        prices, as_of=date.fromisoformat(as_of), max_age_days=max_age_days
    )
    exceptions = _attach_evidence(
        [finding.to_exception() for finding in findings], sources=[prices_source]
    )
    return {
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "exceptions": [item.model_dump(mode="json") for item in exceptions],
    }


def detect_unsettled_trades(trades_path: str, as_of: str, grace_days: int = 3) -> dict[str, Any]:
    """Flag trades still marked unsettled whose settlement_date has passed as_of. Severity
    escalates to HIGH once more than grace_days overdue. Report the findings; do not judge
    settlement risk yourself.

    Args:
        trades_path: Local path to a trade blotter (.json), same shape as reconcile_trades'
            inputs — only status and settlement_date are required for this check.
        as_of: Control date to measure overdue settlement against, as YYYY-MM-DD.
        grace_days: Days past settlement_date still treated as a WARNING rather than HIGH.
    """

    trades, trades_source = _parse_input_file_with_evidence(
        trades_path, source_id="trades", kind="Trades", extension=".json", parser=parse_trades
    )
    findings = _detect_unsettled_trades(
        trades, as_of=date.fromisoformat(as_of), grace_days=grace_days
    )
    exceptions = _attach_evidence(
        [finding.to_exception() for finding in findings], sources=[trades_source]
    )
    return {
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "exceptions": [item.model_dump(mode="json") for item in exceptions],
    }


def detect_exposure_breaches(positions_path: str, nav: str, limits_path: str) -> dict[str, Any]:
    """Compute each position's, issuer's, sector's and the fund's total exposure as a percentage
    of NAV and flag any that breaches the matching limit. Report the breaches; do not compute
    exposure percentages yourself.

    Args:
        positions_path: Local path to the position export (.json), same shape as
            reconcile_positions' inputs — issuer and sector are used for those limit scopes.
        nav: The fund's net asset value as a decimal string, e.g. "92500000.00".
        limits_path: Local path to the exposure-limit export (.json): an array, or an object with
            a limits array, of {label, scope, key, max_percent_of_nav}. scope is one of
            single_position, issuer, sector or gross_exposure; key names the specific
            issuer/sector for a targeted limit, or is omitted for a "no single X" rule.
    """

    positions, positions_source = _parse_input_file_with_evidence(
        positions_path,
        source_id="positions",
        kind="Positions",
        extension=".json",
        parser=parse_positions,
    )
    limits, limits_source = _parse_input_file_with_evidence(
        limits_path,
        source_id="exposure_limits",
        kind="Exposure limits",
        extension=".json",
        parser=parse_exposure_limits,
    )
    try:
        breaches = _detect_exposure_breaches(positions, nav=Decimal(nav), limits=limits)
    except ValueError as exc:
        raise ValueError(f"Could not compute exposure breaches: {exc}") from exc
    exceptions = _attach_evidence(
        [breach.to_exception() for breach in breaches], sources=[positions_source, limits_source]
    )
    return {
        "breaches": [breach.model_dump(mode="json") for breach in breaches],
        "exceptions": [item.model_dump(mode="json") for item in exceptions],
    }


def validate_management_fees(fee_rules_path: str, administrator_fees_path: str) -> dict[str, Any]:
    """Compare each administrator-calculated management fee against the governing fee rule (LPA
    default or side-letter override) for that investor, matched by investor name. Flags a fee
    calculated on the wrong basis (e.g. committed capital instead of invested capital) even if the
    amount looks close, a recomputed amount that disagrees with what the administrator reported,
    and an administrator fee with no supplied rule to check it against. Report the breaks; do not
    recompute a fee yourself.

    Args:
        fee_rules_path: Local path to the fee-rule export (.json): an array, or an object with a
            fee_rules array, of {investor, fee_rate, fee_basis, source}. fee_basis is one of
            committed_capital, invested_capital, called_capital, net_asset_value.
        administrator_fees_path: Local path to the administrator's fee-calculation export (.json):
            an array, or an object with an administrator_fees array, of {investor, fee_basis,
            basis_amount, reported_fee}.
    """

    rules, rules_source = _parse_input_file_with_evidence(
        fee_rules_path,
        source_id="fee_rules",
        kind="Fee rules",
        extension=".json",
        parser=parse_fee_rules,
    )
    administrator_fees, administrator_fees_source = _parse_input_file_with_evidence(
        administrator_fees_path,
        source_id="administrator_fees",
        kind="Administrator fees",
        extension=".json",
        parser=parse_administrator_fees,
    )
    result = _validate_management_fees(rules, administrator_fees)
    exceptions = _attach_evidence(
        result.to_exceptions(), sources=[rules_source, administrator_fees_source]
    )
    return {
        **result.model_dump(mode="json"),
        "exceptions": [item.model_dump(mode="json") for item in exceptions],
    }


def reconcile_expense_allocations(
    expected_allocations_path: str, administrator_expenses_path: str
) -> dict[str, Any]:
    """Compare the fund manager's expected expense allocation (which entity each expense belongs
    to — the fund, the management company, or a named portfolio company) against how the
    administrator actually allocated it, matched by expense_id. A category mismatch is flagged
    regardless of amount, since a misallocated expense is a control break even when the figure is
    immaterial; an amount-only difference on an otherwise correctly categorised expense is a
    separate, lower-severity break. Report the breaks; do not decide the correct allocation
    yourself.

    Args:
        expected_allocations_path: Local path to the fund manager's expected-allocation schedule
            (.json): an array, or an object with an expected_allocations array, of {expense_id,
            description, amount, expected_category, portfolio_company}. expected_category is one
            of fund, management_company, portfolio_company.
        administrator_expenses_path: Local path to the administrator's expense-allocation export
            in the same shape, with allocated_category in place of expected_category.
    """

    expected, expected_source = _parse_input_file_with_evidence(
        expected_allocations_path,
        source_id="expected_expense_allocations",
        kind="Expected expense allocations",
        extension=".json",
        parser=parse_expected_expense_allocations,
    )
    administrator, administrator_source = _parse_input_file_with_evidence(
        administrator_expenses_path,
        source_id="administrator_expenses",
        kind="Administrator expenses",
        extension=".json",
        parser=parse_administrator_expenses,
    )
    result = _reconcile_expense_allocations(expected, administrator)
    exceptions = _attach_evidence(
        result.to_exceptions(), sources=[expected_source, administrator_source]
    )
    return {
        **result.model_dump(mode="json"),
        "exceptions": [item.model_dump(mode="json") for item in exceptions],
    }


def prioritise_exceptions(
    exceptions: list[dict[str, Any]], top_n: int | None = None
) -> dict[str, Any]:
    """Rank exceptions from any of the reconciliation/detection tools above by severity (HIGH
    first, then WARNING) and, within a severity, by impact_amount (materiality) descending. Pass
    it the combined exceptions arrays already returned by those tools; do not re-rank, filter or
    recompute impact_amount yourself.

    Args:
        exceptions: Exception records to rank, each in the common shape every check above returns
            in its own "exceptions" list (category, code, key, title, detail, severity,
            impact_amount).
        top_n: Optional cap on how many ranked exceptions to return.
    """

    items = [ExceptionItem.model_validate(item) for item in exceptions]
    ranked = _prioritise_exceptions(items, top_n=top_n)
    return {"exceptions": [item.model_dump(mode="json") for item in ranked]}


def investigate_exception(
    exceptions: list[dict[str, Any]], code: str | None = None, key: str | None = None
) -> dict[str, Any]:
    """Investigate one exception from a combined exception queue — the highest-priority one by
    default (by severity, then impact_amount), or a specific one selected by its code or key.
    Finds every other exception in the queue sharing the target's key (a strong signal they are
    one underlying incident rather than several independent ones) and returns a recommended
    owner, action and escalation step (next_step). Report this directly; never correlate
    exceptions, invent a root cause, or pick a different owner/action/escalation yourself.

    Args:
        exceptions: Exception records to investigate, each in the common shape every
            reconciliation/detection/validation tool above returns in its own "exceptions" list
            (category, code, key, title, detail, severity, impact_amount). Pass the combined list
            across every check you have run, not just one tool's output, so a related exception in
            a different category can be found.
        code: Optional exact code of the exception to investigate. Defaults to the
            highest-priority one when both code and key are omitted.
        key: Optional exact key of the exception to investigate, used instead of code.
    """

    items = [ExceptionItem.model_validate(item) for item in exceptions]
    result = _investigate_exception(items, code=code, key=key)
    return result.model_dump(mode="json")
