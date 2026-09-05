"""Pure cash-application planning and deterministic control evaluation."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import date
from decimal import Decimal

from app.cash_application.models import (
    ZERO,
    AllocationKind,
    ApplicationDecision,
    ApplicationKind,
    ApplicationStatus,
    CashReceipt,
    ControlDisposition,
    EvidenceRef,
    ExceptionStatus,
    InvoiceApplicationResult,
    InvoiceStatus,
    OpenARItem,
    PolicyReference,
    PolicyStatus,
    ReceiptAllocationStatus,
    ReceiptDirection,
    ReceiptIdentity,
    ReceiptSettlementStatus,
    RemittanceEvidence,
    RemittanceLine,
    ResidualKind,
    ReviewStatus,
    ShortPayPolicy,
)


def _active_policy(
    policies: Iterable[ShortPayPolicy],
    *,
    currency: str,
    customer_id: str,
    as_of_date: date,
) -> tuple[ShortPayPolicy | None, bool]:
    candidates = [
        policy
        for policy in policies
        if policy.status is PolicyStatus.APPROVED
        and policy.currency == currency
        and policy.is_effective(as_of_date)
        and (policy.customer_id is None or policy.customer_id == customer_id)
    ]
    if not candidates:
        return None, False
    customer_specific = [policy for policy in candidates if policy.customer_id == customer_id]
    eligible = customer_specific or candidates
    if len(eligible) != 1:
        return None, True
    return eligible[0], False


def _application_kind(
    lines: tuple[RemittanceLine, ...], receipt_residual: Decimal
) -> ApplicationKind:
    if any(line.kind is AllocationKind.SHORT_PAY for line in lines):
        return ApplicationKind.SHORT_PAY
    if receipt_residual > ZERO:
        return ApplicationKind.OVERPAYMENT
    if any(line.kind is AllocationKind.PARTIAL for line in lines):
        return ApplicationKind.PARTIAL_PAYMENT
    if len(lines) > 1:
        return ApplicationKind.MULTI_INVOICE
    return ApplicationKind.EXACT


def _unchanged_results(
    lines: Iterable[RemittanceLine], invoices: dict[str, OpenARItem]
) -> tuple[InvoiceApplicationResult, ...]:
    return tuple(
        InvoiceApplicationResult(
            invoice_id=line.invoice_id,
            ledger_version_before=item.ledger_version,
            balance_before=item.open_balance,
            cash_applied=ZERO,
            policy_adjustment=ZERO,
            balance_after=item.open_balance,
            status_after=item.status,
            remittance_evidence=line.evidence_ref,
            ar_evidence=item.evidence_ref,
        )
        for line in lines
        if (item := invoices.get(line.invoice_id)) is not None
    )


def _unique_evidence(
    receipt: CashReceipt,
    remittance: RemittanceEvidence,
    results: Iterable[InvoiceApplicationResult],
    policies: Iterable[ShortPayPolicy] = (),
) -> tuple[EvidenceRef, ...]:
    refs = [receipt.evidence_ref, remittance.evidence_ref]
    for result in results:
        refs.extend((result.remittance_evidence, result.ar_evidence))
    refs.extend(policy.evidence_ref for policy in policies)
    return tuple(dict.fromkeys(refs))


def _blocked_decision(
    receipt: CashReceipt,
    remittance: RemittanceEvidence,
    invoices: dict[str, OpenARItem],
    codes: Iterable[str],
    kind: ApplicationKind,
) -> ApplicationDecision:
    results = _unchanged_results(remittance.lines, invoices)
    return ApplicationDecision(
        receipt=receipt,
        remittance_id=remittance.remittance_id,
        remittance_version=remittance.version,
        application_status=ApplicationStatus.CONTROL_BLOCKED,
        disposition=ControlDisposition.BLOCK,
        application_kind=kind,
        residual_kind=ResidualKind.NONE,
        receipt_allocation_status=receipt.allocation_status,
        invoice_results=results,
        cash_allocated=ZERO,
        receipt_residual=receipt.amount,
        policy_adjustment_total=ZERO,
        control_codes=tuple(dict.fromkeys(codes)),
        evidence_refs=_unique_evidence(receipt, remittance, results),
        policy_references=(),
        exception_status=ExceptionStatus.BLOCKED,
    )


def evaluate_cash_application(
    receipt: CashReceipt,
    remittance: RemittanceEvidence,
    open_items: Iterable[OpenARItem],
    *,
    policies: Iterable[ShortPayPolicy] = (),
    processed_receipt_identities: Collection[ReceiptIdentity] = (),
    as_of_date: date,
) -> ApplicationDecision:
    """Build an immutable decision from evidenced inputs without mutating ledger state."""

    item_list = tuple(open_items)
    invoices = {item.invoice_id: item for item in item_list}
    remitted_cash = sum((line.cash_amount for line in remittance.lines), start=ZERO)
    proposed_receipt_residual = receipt.amount - remitted_cash
    kind = _application_kind(remittance.lines, proposed_receipt_residual)
    hard_blocks: list[str] = []

    if len(invoices) != len(item_list):
        hard_blocks.append("invoice.duplicate_record")
    if receipt.settlement_status is not ReceiptSettlementStatus.BOOKED:
        hard_blocks.append("receipt.ineligible_status")
    if receipt.direction is not ReceiptDirection.INBOUND:
        hard_blocks.append("receipt.not_inbound")
    if receipt.identity in processed_receipt_identities:
        hard_blocks.append("receipt.duplicate")
    if receipt.allocation_status not in {
        ReceiptAllocationStatus.UNAPPLIED,
        ReceiptAllocationStatus.HELD,
    }:
        hard_blocks.append("receipt.already_allocated")
    if remittance.receipt_id != receipt.receipt_id:
        hard_blocks.append("remittance.receipt_mismatch")

    referenced_ids = [line.invoice_id for line in remittance.lines]
    if len(set(referenced_ids)) != len(referenced_ids):
        hard_blocks.append("remittance.duplicate_invoice_line")

    for line in remittance.lines:
        item = invoices.get(line.invoice_id)
        if item is None:
            hard_blocks.append("invoice.not_found")
            continue
        if item.customer_id != remittance.customer_id:
            hard_blocks.append("invoice.customer_mismatch")
        if item.status is not InvoiceStatus.OPEN:
            hard_blocks.append("invoice.not_open")
        if item.currency != receipt.currency:
            hard_blocks.append("invoice.currency_mismatch")
        if line.cash_amount + line.deduction_amount > item.open_balance:
            hard_blocks.append("invoice.below_zero")
        if line.kind is AllocationKind.EXACT and line.cash_amount != item.open_balance:
            hard_blocks.append("remittance.unexplained_shortfall")
        if line.kind is AllocationKind.PARTIAL and line.cash_amount >= item.open_balance:
            hard_blocks.append("remittance.invalid_partial")
        if line.kind is AllocationKind.SHORT_PAY and (
            line.deduction_amount == ZERO
            or line.cash_amount + line.deduction_amount != item.open_balance
        ):
            hard_blocks.append("remittance.invalid_short_pay")

    if remitted_cash > receipt.amount:
        hard_blocks.append("receipt.allocation_exceeds_amount")

    if hard_blocks:
        return _blocked_decision(receipt, remittance, invoices, hard_blocks, kind)

    policy_list = tuple(policies)
    results: list[InvoiceApplicationResult] = []
    policies_used: list[ShortPayPolicy] = []
    policy_references: list[PolicyReference] = []
    evidence_codes: list[str] = []
    review_codes: list[str] = []

    for line in remittance.lines:
        item = invoices[line.invoice_id]
        adjustment = ZERO
        reference: PolicyReference | None = None
        if line.kind is AllocationKind.SHORT_PAY:
            policy, policy_conflict = _active_policy(
                policy_list,
                currency=receipt.currency,
                customer_id=item.customer_id,
                as_of_date=as_of_date,
            )
            line_has_exception = False
            if policy_conflict:
                evidence_codes.append("short_pay.policy_conflict")
                line_has_exception = True
            elif policy is None:
                if line.reason_code is None:
                    evidence_codes.append("short_pay.reason_required")
                review_codes.append("short_pay.policy_not_found")
                line_has_exception = True
            else:
                if policy.requires_explicit_reason and line.reason_code is None:
                    evidence_codes.append("short_pay.reason_required")
                    line_has_exception = True
                elif (
                    line.reason_code is not None
                    and line.reason_code not in policy.allowed_reason_codes
                ):
                    review_codes.append("short_pay.reason_not_allowed")
                    line_has_exception = True
                if line.deduction_amount > policy.max_auto_writeoff:
                    review_codes.append("short_pay.exceeds_policy")
                    line_has_exception = True
            if policy is not None and not line_has_exception:
                adjustment = line.deduction_amount
                reference = PolicyReference(
                    policy_id=policy.policy_id,
                    version=policy.version,
                    effective_from=policy.effective_from,
                    source_sha256=policy.evidence_ref.source_sha256,
                )
                if reference not in policy_references:
                    policy_references.append(reference)
                    policies_used.append(policy)

        balance_after = item.open_balance - line.cash_amount - adjustment
        results.append(
            InvoiceApplicationResult(
                invoice_id=item.invoice_id,
                ledger_version_before=item.ledger_version,
                balance_before=item.open_balance,
                cash_applied=line.cash_amount,
                policy_adjustment=adjustment,
                balance_after=balance_after,
                status_after=(
                    InvoiceStatus.CLOSED if balance_after == ZERO else InvoiceStatus.OPEN
                ),
                remittance_evidence=line.evidence_ref,
                ar_evidence=item.evidence_ref,
                policy_reference=reference,
            )
        )

    receipt_residual = receipt.amount - remitted_cash
    residual_kind = ResidualKind.NONE
    if kind is ApplicationKind.OVERPAYMENT:
        residual_kind = ResidualKind.RECEIPT_UNAPPLIED
    elif kind is ApplicationKind.PARTIAL_PAYMENT:
        residual_kind = ResidualKind.INVOICE_OPEN_PARTIAL
    elif kind is ApplicationKind.SHORT_PAY and (evidence_codes or review_codes):
        residual_kind = ResidualKind.CLAIMED_DEDUCTION

    codes = evidence_codes + review_codes
    if receipt_residual > ZERO:
        codes.append("receipt.unapplied_residual")

    if evidence_codes:
        status = ApplicationStatus.EVIDENCE_REQUIRED
        disposition = ControlDisposition.EVIDENCE_REQUIRED
        allocation_status = ReceiptAllocationStatus.HELD
        exception_status = ExceptionStatus.WAITING_EVIDENCE
        review_status = None
    elif review_codes:
        status = ApplicationStatus.REVIEW_REQUIRED
        disposition = ControlDisposition.REVIEW_REQUIRED
        allocation_status = ReceiptAllocationStatus.HELD
        exception_status = ExceptionStatus.WAITING_REVIEW
        review_status = ReviewStatus.REQUESTED
    else:
        status = ApplicationStatus.READY_TO_POST
        disposition = (
            ControlDisposition.POLICY_RESOLVE
            if policy_references
            else ControlDisposition.AUTO_APPLY
        )
        allocation_status = (
            ReceiptAllocationStatus.PARTIALLY_APPLIED
            if receipt_residual > ZERO
            else ReceiptAllocationStatus.APPLIED
        )
        exception_status = None
        review_status = None

    return ApplicationDecision(
        receipt=receipt,
        remittance_id=remittance.remittance_id,
        remittance_version=remittance.version,
        application_status=status,
        disposition=disposition,
        application_kind=kind,
        residual_kind=residual_kind,
        receipt_allocation_status=allocation_status,
        invoice_results=tuple(results),
        cash_allocated=remitted_cash,
        receipt_residual=receipt_residual,
        policy_adjustment_total=sum((result.policy_adjustment for result in results), start=ZERO),
        control_codes=tuple(codes),
        evidence_refs=_unique_evidence(receipt, remittance, results, policies_used),
        policy_references=tuple(policy_references),
        exception_status=exception_status,
        review_status=review_status,
    )
