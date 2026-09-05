from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.private_markets import (
    ApprovedBankDetails,
    CapitalCallExtraction,
    FindingSeverity,
    FundCashTransaction,
    LPCommitment,
    PrivateMarketsAction,
    PrivateMarketsAnalysis,
    PrivateMarketsDataset,
    PrivateMarketsFinding,
    PrivateMarketsWorkItem,
    WorkItemPriority,
    money,
)

_SETTLED_STATUSES = {"BOOKED", "CLEARED", "RECONCILED", "SETTLED"}


def _find_commitment(
    call: CapitalCallExtraction, commitments: list[LPCommitment]
) -> LPCommitment | None:
    candidates = list(commitments)
    if call.lp_reference:
        candidates = [
            item for item in candidates if item.lp_id.casefold() == call.lp_reference.casefold()
        ]
    if call.notice_id and candidates:
        notice_matches = [
            item
            for item in candidates
            if item.call_notice_id and item.call_notice_id.casefold() == call.notice_id.casefold()
        ]
        if notice_matches:
            candidates = notice_matches
    if call.investor_name and candidates:
        name_matches = [
            item for item in candidates if item.lp_name.casefold() == call.investor_name.casefold()
        ]
        if name_matches:
            candidates = name_matches
    return candidates[0] if len(candidates) == 1 else None


def _eligible_cash(call: CapitalCallExtraction, transaction: FundCashTransaction) -> bool:
    if transaction.direction != "credit" or transaction.currency != call.currency:
        return False
    return not transaction.status or transaction.status.upper() in _SETTLED_STATUSES


def _cash_haystack(transaction: FundCashTransaction) -> str:
    return " ".join(
        value
        for value in [transaction.reference, transaction.description, transaction.counterparty]
        if value
    ).casefold()


def _within_call_window(call: CapitalCallExtraction, transaction: FundCashTransaction) -> bool:
    if call.issue_date and transaction.booking_date < call.issue_date - timedelta(days=3):
        return False
    if call.due_date and transaction.booking_date > call.due_date + timedelta(days=10):
        return False
    return True


def _strict_cash_matches(
    call: CapitalCallExtraction,
    transactions: list[FundCashTransaction],
) -> tuple[list[FundCashTransaction], list[FundCashTransaction], bool]:
    """Return strong matches, weak candidates and whether duplicate transaction ids were supplied.

    A transaction is strong enough for automatic reconciliation only when the call/LP reference is
    present in booked cash evidence. Investor-name-only matches are retained as weak evidence and
    never counted toward an automatic close.
    """

    notice = (call.notice_id or "").casefold()
    lp_reference = (call.lp_reference or "").casefold()
    investor = (call.investor_name or "").casefold()
    payment_reference = (call.payment_reference or "").casefold()

    strong: dict[str, FundCashTransaction] = {}
    weak: dict[str, FundCashTransaction] = {}
    seen: set[str] = set()
    duplicate_ids = False

    for transaction in transactions:
        if not _eligible_cash(call, transaction):
            continue
        if transaction.transaction_id in seen:
            duplicate_ids = True
        seen.add(transaction.transaction_id)

        haystack = _cash_haystack(transaction)
        has_notice = bool(notice and notice in haystack)
        has_lp = bool(lp_reference and lp_reference in haystack)
        has_payment_reference = bool(payment_reference and payment_reference in haystack)

        if has_payment_reference or (has_notice and (not lp_reference or has_lp)):
            strong[transaction.transaction_id] = transaction
            continue

        exact_amount = money(transaction.amount) == money(call.current_call)
        has_investor = bool(investor and investor in haystack)
        if has_investor and exact_amount and _within_call_window(call, transaction):
            weak[transaction.transaction_id] = transaction

    return list(strong.values()), list(weak.values()), duplicate_ids


def _approved_bank_record(
    call: CapitalCallExtraction,
    records: list[ApprovedBankDetails],
) -> tuple[ApprovedBankDetails | None, list[ApprovedBankDetails]]:
    fund_records = [
        item for item in records if item.fund_name.casefold() == call.fund_name.casefold()
    ]
    approved = [
        item for item in fund_records if (item.approval_status or "").strip().upper() == "APPROVED"
    ]
    return (approved[0] if len(approved) == 1 else None), fund_records


def analyse_private_markets_case_strict(
    call: CapitalCallExtraction,
    dataset: PrivateMarketsDataset,
    transactions: list[FundCashTransaction],
    *,
    as_of_date: date | None = None,
) -> PrivateMarketsAnalysis:
    findings: list[PrivateMarketsFinding] = []
    commitment = _find_commitment(call, dataset.commitments)

    if call.confidence < 85:
        findings.append(
            PrivateMarketsFinding(
                code="extraction.low_confidence",
                severity=FindingSeverity.HIGH,
                title="Document extraction needs review",
                detail=(
                    f"Extraction confidence is {call.confidence}%. The source notice must be "
                    "reviewed before a control decision can complete."
                ),
                expected="85% or higher",
                observed=f"{call.confidence}%",
            )
        )
    elif call.warnings:
        findings.append(
            PrivateMarketsFinding(
                code="extraction.warnings_present",
                severity=FindingSeverity.WARNING,
                title="Extraction contains warnings",
                detail="; ".join(call.warnings),
            )
        )

    if call.currency != "GBP":
        findings.append(
            PrivateMarketsFinding(
                code="commitment.currency_not_supported",
                severity=FindingSeverity.HIGH,
                title="Commitment currency cannot be verified",
                detail=(
                    "The supplied commitment workbook is GBP-denominated while the notice is not. "
                    "Provide a same-currency commitment record before reconciliation."
                ),
                expected="GBP",
                observed=call.currency,
            )
        )

    calculated_remaining: Decimal | None = None
    if commitment is None:
        findings.append(
            PrivateMarketsFinding(
                code="commitment.not_found",
                severity=FindingSeverity.HIGH,
                title="Unique commitment record not found",
                detail=(
                    "The capital call could not be tied to exactly one LP commitment record using "
                    "the LP, notice and investor identifiers."
                ),
            )
        )
    else:
        numeric_values = {
            "total commitment": commitment.total_commitment,
            "called before current": commitment.called_before_current,
            "current call": commitment.current_call,
        }
        if any(value < 0 for value in numeric_values.values()):
            findings.append(
                PrivateMarketsFinding(
                    code="commitment.negative_value",
                    severity=FindingSeverity.HIGH,
                    title="Commitment ledger contains a negative control value",
                    detail="Commitment amounts must be non-negative before reconciliation.",
                )
            )

        amount_difference = money(commitment.current_call - call.current_call)
        if amount_difference == 0:
            findings.append(
                PrivateMarketsFinding(
                    code="commitment.call_amount_match",
                    severity=FindingSeverity.PASS,
                    title="Capital call matches commitment schedule",
                    detail="The notice amount matches the current call recorded for the LP.",
                    expected=str(commitment.current_call),
                    observed=str(call.current_call),
                )
            )
        else:
            findings.append(
                PrivateMarketsFinding(
                    code="commitment.call_amount_mismatch",
                    severity=FindingSeverity.HIGH,
                    title="Capital call amount differs from commitment schedule",
                    detail="The notice and commitment workbook contain different current-call values.",
                    expected=str(commitment.current_call),
                    observed=str(call.current_call),
                )
            )

        available_before_call = money(
            commitment.total_commitment - commitment.called_before_current
        )
        calculated_remaining = money(available_before_call - commitment.current_call)
        if commitment.current_call > available_before_call or calculated_remaining < 0:
            findings.append(
                PrivateMarketsFinding(
                    code="commitment.call_exceeds_remaining",
                    severity=FindingSeverity.HIGH,
                    title="Capital call exceeds remaining commitment",
                    detail=(
                        "The current call is greater than the LP commitment available before this "
                        "call. Reconciliation is blocked until the ledger is corrected or evidenced."
                    ),
                    expected=f"No more than {available_before_call}",
                    observed=str(commitment.current_call),
                )
            )
        elif (
            commitment.remaining_after_current is not None
            and calculated_remaining != commitment.remaining_after_current
        ):
            findings.append(
                PrivateMarketsFinding(
                    code="commitment.remaining_math_mismatch",
                    severity=FindingSeverity.HIGH,
                    title="Remaining commitment arithmetic does not reconcile",
                    detail="The workbook remaining commitment differs from deterministic arithmetic.",
                    expected=str(calculated_remaining),
                    observed=str(commitment.remaining_after_current),
                )
            )
        else:
            findings.append(
                PrivateMarketsFinding(
                    code="commitment.remaining_math_valid",
                    severity=FindingSeverity.PASS,
                    title="Remaining commitment arithmetic reconciles",
                    detail="Total commitment less prior calls and the current call reconciles.",
                    observed=str(calculated_remaining),
                )
            )

    approved_bank, fund_bank_records = _approved_bank_record(call, dataset.approved_bank_details)
    approved_count = sum(
        (item.approval_status or "").strip().upper() == "APPROVED" for item in fund_bank_records
    )
    if approved_count > 1:
        findings.append(
            PrivateMarketsFinding(
                code="bank.multiple_approved_records",
                severity=FindingSeverity.HIGH,
                title="Multiple approved banking records found",
                detail="A single current approved payment destination is required for comparison.",
                observed=str(approved_count),
            )
        )
    elif approved_bank is None:
        code = "bank.approved_record_missing"
        title = "No approved banking record available"
        detail = (
            "Do not release funds until a current explicitly approved banking record is attached."
        )
        if fund_bank_records:
            code = "bank.record_not_approved"
            title = "Banking record is not explicitly approved"
            detail = (
                "A banking record exists, but its approval status is blank or not APPROVED. "
                "Missing approval metadata must not be treated as approval."
            )
        findings.append(
            PrivateMarketsFinding(
                code=code,
                severity=FindingSeverity.HIGH,
                title=title,
                detail=detail,
            )
        )
    elif not call.account_last4 or not call.sort_code:
        findings.append(
            PrivateMarketsFinding(
                code="bank.instructions_incomplete",
                severity=FindingSeverity.HIGH,
                title="Banking instructions are incomplete",
                detail=(
                    "The notice does not contain enough account evidence to compare it with the "
                    "approved fund record. Independent verification is required."
                ),
            )
        )
    else:
        changed_account = bool(
            approved_bank.account_last4 and approved_bank.account_last4 != call.account_last4
        )
        changed_sort = bool(
            approved_bank.sort_code
            and approved_bank.sort_code.replace("-", "") != call.sort_code.replace("-", "")
        )
        changed_beneficiary = bool(
            approved_bank.beneficiary
            and call.beneficiary
            and approved_bank.beneficiary.casefold() != call.beneficiary.casefold()
        )
        if changed_account or changed_sort or changed_beneficiary:
            findings.append(
                PrivateMarketsFinding(
                    code="bank.instructions_changed",
                    severity=FindingSeverity.HIGH,
                    title="Banking instructions changed",
                    detail=(
                        "The notice payment instructions differ from the approved fund record. "
                        "Independent out-of-band verification is required before any payment."
                    ),
                    expected=(
                        f"{approved_bank.bank_name or 'approved bank'} / "
                        f"****{approved_bank.account_last4 or 'unknown'}"
                    ),
                    observed=f"{call.bank_name or 'notice bank'} / ****{call.account_last4}",
                )
            )
        else:
            findings.append(
                PrivateMarketsFinding(
                    code="bank.instructions_match",
                    severity=FindingSeverity.PASS,
                    title="Banking instructions match approved record",
                    detail="The notice account evidence matches the explicitly approved fund record.",
                )
            )

    strong_matches, weak_matches, duplicate_ids = _strict_cash_matches(call, transactions)
    if duplicate_ids:
        findings.append(
            PrivateMarketsFinding(
                code="cash.duplicate_transaction_ids",
                severity=FindingSeverity.HIGH,
                title="Duplicate transaction identifiers supplied",
                detail="Duplicate cash rows are excluded from a safe automatic close.",
            )
        )
    if weak_matches and not strong_matches:
        findings.append(
            PrivateMarketsFinding(
                code="cash.weak_match_only",
                severity=FindingSeverity.WARNING,
                title="Only weak cash candidates were found",
                detail=(
                    "Investor-name and amount evidence exists, but the capital-call/LP reference "
                    "is missing. These transactions are not counted toward automatic reconciliation."
                ),
                observed=", ".join(item.transaction_id for item in weak_matches),
            )
        )

    received = money(sum((item.amount for item in strong_matches), Decimal("0")))
    variance = money(received - call.current_call)
    if variance == 0 and strong_matches:
        findings.append(
            PrivateMarketsFinding(
                code="cash.exact_match",
                severity=FindingSeverity.PASS,
                title="Booked cash exactly matches the capital call",
                detail="Strongly referenced cash equals the expected call amount.",
                expected=str(call.current_call),
                observed=str(received),
            )
        )
    elif received == 0:
        severity = (
            FindingSeverity.HIGH
            if as_of_date and call.due_date and call.due_date <= as_of_date
            else FindingSeverity.WARNING
        )
        findings.append(
            PrivateMarketsFinding(
                code="cash.missing",
                severity=severity,
                title="No strongly referenced cash receipt found",
                detail="No booked credit contains sufficient capital-call reference evidence.",
                expected=str(call.current_call),
                observed="0.00",
            )
        )
    elif variance < 0:
        findings.append(
            PrivateMarketsFinding(
                code="cash.short_receipt",
                severity=FindingSeverity.HIGH,
                title="Capital call is under-received",
                detail=f"Strongly matched cash is {abs(variance)} {call.currency} below the call.",
                expected=str(call.current_call),
                observed=str(received),
            )
        )
    else:
        findings.append(
            PrivateMarketsFinding(
                code="cash.over_receipt",
                severity=FindingSeverity.HIGH,
                title="Capital call is over-received",
                detail=f"Strongly matched cash exceeds the call by {variance} {call.currency}.",
                expected=str(call.current_call),
                observed=str(received),
            )
        )

    all_codes = {item.code for item in findings}
    high_codes = {item.code for item in findings if item.severity == FindingSeverity.HIGH}
    evidence_blockers = high_codes - {"bank.instructions_changed"}
    if evidence_blockers:
        action = PrivateMarketsAction.REQUEST_EVIDENCE
    elif "bank.instructions_changed" in high_codes:
        action = PrivateMarketsAction.REQUIRE_APPROVAL
    elif any(item.severity == FindingSeverity.WARNING for item in findings):
        action = PrivateMarketsAction.REQUEST_EVIDENCE
    else:
        action = PrivateMarketsAction.AUTO_RECONCILE

    work_items: list[PrivateMarketsWorkItem] = []
    if high_codes & {
        "bank.instructions_changed",
        "bank.instructions_incomplete",
        "bank.record_not_approved",
        "bank.approved_record_missing",
        "bank.multiple_approved_records",
    }:
        work_items.append(
            PrivateMarketsWorkItem(
                code="verify_bank_instructions",
                priority=WorkItemPriority.CRITICAL,
                owner="Treasury control",
                title="Verify the payment destination",
                instruction=(
                    "Use an independently sourced contact and record the verifier, timestamp and "
                    "current approved banking record before any payment release."
                ),
            )
        )
    if all_codes & {"cash.short_receipt", "cash.missing", "cash.weak_match_only"}:
        work_items.append(
            PrivateMarketsWorkItem(
                code="resolve_cash_shortfall",
                priority=WorkItemPriority.HIGH,
                owner="Investor operations",
                title="Resolve the outstanding contribution",
                instruction=(
                    "Confirm the receipt reference and amount, then attach evidence or request the "
                    "outstanding balance."
                ),
            )
        )
    if "cash.over_receipt" in high_codes or "cash.duplicate_transaction_ids" in high_codes:
        work_items.append(
            PrivateMarketsWorkItem(
                code="review_cash_ledger",
                priority=WorkItemPriority.HIGH,
                owner="Fund accounting",
                title="Review fund cash evidence",
                instruction="Resolve duplicated or over-received cash before posting the close.",
            )
        )
    if high_codes & {
        "commitment.not_found",
        "commitment.negative_value",
        "commitment.call_amount_mismatch",
        "commitment.call_exceeds_remaining",
        "commitment.remaining_math_mismatch",
        "commitment.currency_not_supported",
    }:
        work_items.append(
            PrivateMarketsWorkItem(
                code="review_commitment_ledger",
                priority=WorkItemPriority.HIGH,
                owner="Fund accounting",
                title="Review the commitment ledger",
                instruction="Correct or evidence the LP commitment schedule before reconciliation.",
            )
        )
    if "extraction.low_confidence" in high_codes:
        work_items.append(
            PrivateMarketsWorkItem(
                code="review_extraction",
                priority=WorkItemPriority.HIGH,
                owner="Fund operations",
                title="Review extracted notice fields",
                instruction="Compare extracted fields with the source notice and correct them.",
            )
        )

    outstanding = money(max(call.current_call - received, Decimal("0")))
    progress = Decimal("0")
    if call.current_call:
        progress = min(
            Decimal("100"),
            (received / call.current_call * Decimal("100")).quantize(Decimal("0.01")),
        )
    remaining_commitment = (
        calculated_remaining if calculated_remaining is not None else call.remaining_after_current
    )
    days_to_due = (
        (call.due_date - as_of_date).days if call.due_date is not None and as_of_date else None
    )

    return PrivateMarketsAnalysis(
        action=action,
        fund_name=call.fund_name,
        investor_name=call.investor_name,
        notice_id=call.notice_id,
        expected_amount=call.current_call,
        received_amount=received,
        variance_amount=variance,
        outstanding_amount=outstanding,
        funding_progress_percent=progress,
        total_commitment=commitment.total_commitment if commitment else call.total_commitment,
        called_before_current=(
            commitment.called_before_current if commitment else call.called_before_current
        ),
        remaining_commitment=remaining_commitment,
        days_to_due=days_to_due,
        due_date=call.due_date,
        matched_transaction_ids=[item.transaction_id for item in strong_matches],
        findings=findings,
        work_items=work_items,
        controls_passed=sum(item.severity == FindingSeverity.PASS for item in findings),
        exceptions_open=sum(
            item.severity in {FindingSeverity.HIGH, FindingSeverity.WARNING} for item in findings
        ),
        controls_summary=(
            "AI extracts the notice; strict deterministic commitment, approved-bank and "
            "reference-bound cash controls decide whether the case can close."
        ),
    )
