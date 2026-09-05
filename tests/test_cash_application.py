from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.cash_application import (
    AllocationKind,
    ApplicationKind,
    ApplicationStatus,
    CashReceipt,
    ControlDisposition,
    EvidenceRef,
    EvidenceSource,
    InvoiceStatus,
    LedgerInvariantError,
    OpenARItem,
    PolicyStatus,
    ReceiptAllocationStatus,
    ReceiptDirection,
    ReceiptSettlementStatus,
    RemittanceEvidence,
    RemittanceLine,
    ResidualKind,
    ShortPayPolicy,
    SimulatedCashLedger,
    evaluate_cash_application,
)

DECISION_DATE = date(2026, 9, 5)


def evidence(
    evidence_id: str,
    source_type: EvidenceSource,
    source_object_id: str,
    *,
    source_system: str = "SYNTHETIC",
) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=evidence_id,
        source_type=source_type,
        source_system=source_system,
        source_object_id=source_object_id,
        source_sha256="a" * 64,
        locator=f"record:{source_object_id}",
        claim_path="$",
    )


def receipt(
    receipt_id: str,
    amount: str,
    *,
    currency: str = "GBP",
    status: ReceiptSettlementStatus = ReceiptSettlementStatus.BOOKED,
    direction: ReceiptDirection = ReceiptDirection.INBOUND,
) -> CashReceipt:
    source_system = "SYNTHETIC_BANK"
    source_transaction_id = f"TX-{receipt_id}"
    return CashReceipt(
        receipt_id=receipt_id,
        source_system=source_system,
        source_transaction_id=source_transaction_id,
        booking_date=DECISION_DATE,
        amount=Decimal(amount),
        currency=currency,
        settlement_status=status,
        direction=direction,
        evidence_ref=evidence(
            f"BANK-{receipt_id}",
            EvidenceSource.BANK_FEED,
            source_transaction_id,
            source_system=source_system,
        ),
    )


def invoice(
    invoice_id: str,
    balance: str,
    *,
    currency: str = "GBP",
    status: InvoiceStatus = InvoiceStatus.OPEN,
) -> OpenARItem:
    return OpenARItem(
        invoice_id=invoice_id,
        customer_id="CUST-0042",
        original_amount=Decimal(balance),
        open_balance=Decimal(balance),
        currency=currency,
        status=status,
        evidence_ref=evidence(
            f"AR-{invoice_id}",
            EvidenceSource.AR_LEDGER,
            invoice_id,
            source_system="SYNTHETIC_AR",
        ),
    )


def remittance(receipt_id: str, *lines: RemittanceLine) -> RemittanceEvidence:
    remittance_id = f"REMIT-{receipt_id}"
    return RemittanceEvidence(
        remittance_id=remittance_id,
        receipt_id=receipt_id,
        customer_id="CUST-0042",
        evidence_ref=evidence(
            f"DOC-{receipt_id}",
            EvidenceSource.REMITTANCE,
            remittance_id,
            source_system="SYNTHETIC_REMITTANCE",
        ),
        lines=lines,
    )


def line(
    invoice_id: str,
    amount: str,
    *,
    kind: AllocationKind = AllocationKind.EXACT,
    deduction: str = "0.00",
    reason: str | None = None,
) -> RemittanceLine:
    return RemittanceLine(
        invoice_id=invoice_id,
        cash_amount=Decimal(amount),
        evidence_ref=evidence(
            f"LINE-{invoice_id}",
            EvidenceSource.REMITTANCE,
            f"LINE-{invoice_id}",
            source_system="SYNTHETIC_REMITTANCE",
        ),
        kind=kind,
        deduction_amount=Decimal(deduction),
        reason_code=reason,
    )


def short_pay_policy(
    *,
    version: int = 3,
    effective_from: date = date(2026, 9, 1),
    effective_to: date | None = None,
    maximum: str = "50.00",
    status: PolicyStatus = PolicyStatus.APPROVED,
) -> ShortPayPolicy:
    policy_object_id = f"SHORTPAY-01:v{version}"
    return ShortPayPolicy(
        policy_id="SHORTPAY-01",
        version=version,
        effective_from=effective_from,
        effective_to=effective_to,
        currency="GBP",
        max_auto_writeoff=Decimal(maximum),
        allowed_reason_codes=frozenset({"FREIGHT_DAMAGE", "ROUNDING"}),
        requires_explicit_reason=True,
        status=status,
        evidence_ref=evidence(
            f"POLICY-v{version}",
            EvidenceSource.POLICY,
            policy_object_id,
            source_system="SYNTHETIC_POLICY",
        ),
    )


def test_ca_01_exact_one_invoice_match_closes_invoice_in_simulation() -> None:
    cash = receipt("RCPT-1001", "1250.00")
    open_item = invoice("INV-1001", "1250.00")
    decision = evaluate_cash_application(
        cash,
        remittance(cash.receipt_id, line(open_item.invoice_id, "1250.00")),
        [open_item],
        as_of_date=DECISION_DATE,
    )

    assert decision.application_status is ApplicationStatus.READY_TO_POST
    assert decision.cash_allocated == Decimal("1250.00")
    assert decision.receipt_residual == Decimal("0.00")
    assert decision.invoice_result("INV-1001").balance_after == Decimal("0.00")
    assert decision.invoice_result("INV-1001").policy_adjustment == Decimal("0.00")

    ledger = SimulatedCashLedger([open_item])
    posted = ledger.post(decision, idempotency_key="apply-RCPT-1001")

    assert posted.balance_for("INV-1001") == Decimal("0.00")
    assert ledger.invoice("INV-1001").status is InvoiceStatus.CLOSED
    assert posted.posting_mode == "SIMULATED_ONLY"


def test_ca_02_exact_multi_invoice_remittance_reconciles_to_receipt() -> None:
    cash = receipt("RCPT-1002", "3650.00")
    invoices = [invoice("INV-1002", "1250.00"), invoice("INV-1003", "2400.00")]

    decision = evaluate_cash_application(
        cash,
        remittance(
            cash.receipt_id,
            line("INV-1002", "1250.00"),
            line("INV-1003", "2400.00"),
        ),
        invoices,
        as_of_date=DECISION_DATE,
    )

    assert decision.application_status is ApplicationStatus.READY_TO_POST
    assert decision.application_kind is ApplicationKind.MULTI_INVOICE
    assert decision.cash_allocated == Decimal("3650.00")
    assert decision.receipt_residual == Decimal("0.00")
    assert [item.cash_applied for item in decision.invoice_results] == [
        Decimal("1250.00"),
        Decimal("2400.00"),
    ]
    assert all(item.balance_after == Decimal("0.00") for item in decision.invoice_results)


def test_ca_03_explicit_partial_payment_preserves_open_balance_without_writeoff() -> None:
    cash = receipt("RCPT-1003", "6000.00")
    open_item = invoice("INV-1004", "10000.00")

    decision = evaluate_cash_application(
        cash,
        remittance(
            cash.receipt_id,
            line("INV-1004", "6000.00", kind=AllocationKind.PARTIAL),
        ),
        [open_item],
        as_of_date=DECISION_DATE,
    )

    outcome = decision.invoice_result("INV-1004")
    assert decision.application_status is ApplicationStatus.READY_TO_POST
    assert decision.application_kind is ApplicationKind.PARTIAL_PAYMENT
    assert decision.residual_kind is ResidualKind.INVOICE_OPEN_PARTIAL
    assert decision.cash_allocated == Decimal("6000.00")
    assert outcome.policy_adjustment == Decimal("0.00")
    assert outcome.balance_after == Decimal("4000.00")
    assert outcome.status_after is InvoiceStatus.OPEN


def test_ca_04_short_pay_uses_only_approved_policy_effective_on_decision_date() -> None:
    cash = receipt("RCPT-1004", "9970.00")
    open_item = invoice("INV-1005", "10000.00")
    expired_v2 = short_pay_policy(
        version=2,
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 8, 31),
        maximum="20.00",
    )
    draft_v4 = short_pay_policy(
        version=4,
        effective_from=date(2026, 9, 1),
        maximum="100.00",
        status=PolicyStatus.DRAFT,
    )

    decision = evaluate_cash_application(
        cash,
        remittance(
            cash.receipt_id,
            line(
                "INV-1005",
                "9970.00",
                kind=AllocationKind.SHORT_PAY,
                deduction="30.00",
                reason="FREIGHT_DAMAGE",
            ),
        ),
        [open_item],
        policies=[expired_v2, short_pay_policy(), draft_v4],
        as_of_date=DECISION_DATE,
    )

    outcome = decision.invoice_result("INV-1005")
    assert decision.application_status is ApplicationStatus.READY_TO_POST
    assert decision.disposition is ControlDisposition.POLICY_RESOLVE
    assert decision.cash_allocated == Decimal("9970.00")
    assert decision.policy_adjustment_total == Decimal("30.00")
    assert outcome.balance_after == Decimal("0.00")
    assert decision.policy_references[0].policy_id == "SHORTPAY-01"
    assert decision.policy_references[0].version == 3
    assert decision.policy_references[0].source_sha256 == "a" * 64


def test_material_short_pay_is_held_without_pre_review_ledger_mutation() -> None:
    cash = receipt("RCPT-1005", "9500.00")
    open_item = invoice("INV-1005", "10000.00")
    decision = evaluate_cash_application(
        cash,
        remittance(
            cash.receipt_id,
            line(
                open_item.invoice_id,
                "9500.00",
                kind=AllocationKind.SHORT_PAY,
                deduction="500.00",
                reason="DAMAGED_GOODS",
            ),
        ),
        [open_item],
        policies=[short_pay_policy()],
        as_of_date=DECISION_DATE,
    )

    assert decision.application_status is ApplicationStatus.REVIEW_REQUIRED
    assert decision.disposition is ControlDisposition.REVIEW_REQUIRED
    assert decision.receipt_allocation_status is ReceiptAllocationStatus.HELD
    assert decision.residual_kind is ResidualKind.CLAIMED_DEDUCTION
    assert decision.cash_allocated == Decimal("9500.00")
    assert decision.policy_adjustment_total == Decimal("0.00")
    assert decision.invoice_result("INV-1005").balance_after == Decimal("500.00")
    assert "short_pay.reason_not_allowed" in decision.control_codes
    assert "short_pay.exceeds_policy" in decision.control_codes

    ledger = SimulatedCashLedger([open_item])
    with pytest.raises(LedgerInvariantError, match="decision.not_postable"):
        ledger.post(
            decision,
            idempotency_key="material-shortpay-before-review",
            approved_by="controller@example.test",
        )
    assert ledger.invoice("INV-1005").open_balance == Decimal("10000.00")
    assert ledger.processed_receipt_identities == frozenset()


def test_overlapping_approved_policy_versions_fail_closed() -> None:
    cash = receipt("RCPT-POLICY-CONFLICT", "9970.00")
    open_item = invoice("INV-POLICY-CONFLICT", "10000.00")
    overlapping_v4 = short_pay_policy(
        version=4,
        effective_from=date(2026, 9, 1),
        maximum="100.00",
    )

    decision = evaluate_cash_application(
        cash,
        remittance(
            cash.receipt_id,
            line(
                open_item.invoice_id,
                "9970.00",
                kind=AllocationKind.SHORT_PAY,
                deduction="30.00",
                reason="FREIGHT_DAMAGE",
            ),
        ),
        [open_item],
        policies=[short_pay_policy(), overlapping_v4],
        as_of_date=DECISION_DATE,
    )

    assert decision.application_status is ApplicationStatus.EVIDENCE_REQUIRED
    assert decision.disposition is ControlDisposition.EVIDENCE_REQUIRED
    assert decision.receipt_allocation_status is ReceiptAllocationStatus.HELD
    assert decision.policy_adjustment_total == Decimal("0.00")
    assert "short_pay.policy_conflict" in decision.control_codes


def test_ca_07_processed_receipt_is_blocked_without_ledger_change() -> None:
    cash = receipt("RCPT-1007", "1250.00")
    open_item = invoice("INV-1007", "1250.00")

    decision = evaluate_cash_application(
        cash,
        remittance(cash.receipt_id, line(open_item.invoice_id, "1250.00")),
        [open_item],
        processed_receipt_identities={cash.identity},
        as_of_date=DECISION_DATE,
    )

    assert decision.application_status is ApplicationStatus.CONTROL_BLOCKED
    assert "receipt.duplicate" in decision.control_codes
    assert decision.cash_allocated == Decimal("0.00")
    assert decision.invoice_result("INV-1007").balance_after == Decimal("1250.00")


def test_ca_07_posting_is_idempotent_by_key_and_blocks_second_application() -> None:
    cash = receipt("RCPT-1007", "1250.00")
    open_item = invoice("INV-1007", "1250.00")
    decision = evaluate_cash_application(
        cash,
        remittance(cash.receipt_id, line(open_item.invoice_id, "1250.00")),
        [open_item],
        as_of_date=DECISION_DATE,
    )
    ledger = SimulatedCashLedger([open_item])

    first = ledger.post(decision, idempotency_key="retry-safe-key")
    replay = ledger.post(decision, idempotency_key="retry-safe-key")

    assert replay is first
    assert ledger.invoice("INV-1007").open_balance == Decimal("0.00")
    with pytest.raises(LedgerInvariantError, match="receipt.duplicate"):
        ledger.post(decision, idempotency_key="different-attempt")
    assert ledger.invoice("INV-1007").open_balance == Decimal("0.00")


def test_ca_09_overpayment_applies_only_supported_amount_and_exposes_residual() -> None:
    cash = receipt("RCPT-1009", "1200.00")
    open_item = invoice("INV-1009", "1000.00")

    decision = evaluate_cash_application(
        cash,
        remittance(cash.receipt_id, line(open_item.invoice_id, "1000.00")),
        [open_item],
        as_of_date=DECISION_DATE,
    )

    assert decision.application_status is ApplicationStatus.READY_TO_POST
    assert decision.application_kind is ApplicationKind.OVERPAYMENT
    assert decision.residual_kind is ResidualKind.RECEIPT_UNAPPLIED
    assert decision.receipt_allocation_status is ReceiptAllocationStatus.PARTIALLY_APPLIED
    assert decision.cash_allocated == Decimal("1000.00")
    assert decision.receipt_residual == Decimal("200.00")
    assert decision.invoice_result("INV-1009").balance_after == Decimal("0.00")
    assert "receipt.unapplied_residual" in decision.control_codes


def test_ca_10_currency_mismatch_blocks_without_conversion() -> None:
    cash = receipt("RCPT-1010", "780.00", currency="GBP")
    open_item = invoice("INV-1010", "1000.00", currency="USD")

    decision = evaluate_cash_application(
        cash,
        remittance(cash.receipt_id, line(open_item.invoice_id, "780.00")),
        [open_item],
        as_of_date=DECISION_DATE,
    )

    assert decision.application_status is ApplicationStatus.CONTROL_BLOCKED
    assert "invoice.currency_mismatch" in decision.control_codes
    assert decision.cash_allocated == Decimal("0.00")
    assert decision.invoice_result("INV-1010").balance_after == Decimal("1000.00")


@pytest.mark.parametrize(
    "status",
    [ReceiptSettlementStatus.PENDING, ReceiptSettlementStatus.REVERSED],
)
def test_ca_11_ineligible_receipt_status_blocks_application(
    status: ReceiptSettlementStatus,
) -> None:
    cash = receipt("RCPT-1011", "1250.00", status=status)
    open_item = invoice("INV-1011", "1250.00")

    decision = evaluate_cash_application(
        cash,
        remittance(cash.receipt_id, line(open_item.invoice_id, "1250.00")),
        [open_item],
        as_of_date=DECISION_DATE,
    )

    assert decision.application_status is ApplicationStatus.CONTROL_BLOCKED
    assert "receipt.ineligible_status" in decision.control_codes
    assert decision.cash_allocated == Decimal("0.00")
    assert decision.receipt_residual == Decimal("1250.00")


def test_invoice_floor_and_closed_state_are_hard_blocks() -> None:
    cash = receipt("RCPT-FLOOR", "1300.00")
    overallocated = invoice("INV-FLOOR", "1250.00")
    floor_decision = evaluate_cash_application(
        cash,
        remittance(cash.receipt_id, line(overallocated.invoice_id, "1300.00")),
        [overallocated],
        as_of_date=DECISION_DATE,
    )
    closed_item = invoice("INV-CLOSED", "1250.00", status=InvoiceStatus.CLOSED)
    closed_decision = evaluate_cash_application(
        receipt("RCPT-CLOSED", "1250.00"),
        remittance("RCPT-CLOSED", line(closed_item.invoice_id, "1250.00")),
        [closed_item],
        as_of_date=DECISION_DATE,
    )

    assert floor_decision.application_status is ApplicationStatus.CONTROL_BLOCKED
    assert "invoice.below_zero" in floor_decision.control_codes
    assert floor_decision.invoice_result("INV-FLOOR").balance_after == Decimal("1250.00")
    assert closed_decision.application_status is ApplicationStatus.CONTROL_BLOCKED
    assert "invoice.not_open" in closed_decision.control_codes


def test_human_approval_cannot_bypass_posting_time_ledger_invariants() -> None:
    cash = receipt("RCPT-APPROVAL", "1250.00")
    open_item = invoice("INV-APPROVAL", "1250.00")
    decision = evaluate_cash_application(
        cash,
        remittance(cash.receipt_id, line(open_item.invoice_id, "1250.00")),
        [open_item],
        as_of_date=DECISION_DATE,
    )
    concurrently_closed = invoice(
        "INV-APPROVAL",
        "1250.00",
        status=InvoiceStatus.CLOSED,
    )
    ledger = SimulatedCashLedger([concurrently_closed])

    with pytest.raises(LedgerInvariantError, match="invoice.not_open"):
        ledger.post(
            decision,
            idempotency_key="approved-but-invalid",
            approved_by="controller@example.test",
        )

    assert ledger.invoice("INV-APPROVAL").open_balance == Decimal("1250.00")
    assert ledger.processed_receipt_identities == frozenset()


def test_human_approval_cannot_bypass_receipt_ceiling_on_tampered_decision() -> None:
    original_receipt = receipt("RCPT-TAMPER", "1500.00")
    open_item = invoice("INV-TAMPER", "1500.00")
    valid_decision = evaluate_cash_application(
        original_receipt,
        remittance(original_receipt.receipt_id, line(open_item.invoice_id, "1500.00")),
        [open_item],
        as_of_date=DECISION_DATE,
    )
    smaller_receipt = receipt("RCPT-TAMPER", "1250.00")
    tampered_decision = replace(
        valid_decision,
        receipt=smaller_receipt,
        receipt_residual=Decimal("-250.00"),
    )
    ledger = SimulatedCashLedger([open_item])

    with pytest.raises(LedgerInvariantError, match="receipt.allocation_exceeds_amount"):
        ledger.post(
            tampered_decision,
            idempotency_key="approved-tampered-decision",
            approved_by="controller@example.test",
        )

    assert ledger.invoice("INV-TAMPER").open_balance == Decimal("1500.00")
    assert ledger.processed_receipt_identities == frozenset()


def test_only_booked_inbound_receipts_are_eligible() -> None:
    cash = receipt(
        "RCPT-OUTBOUND",
        "1250.00",
        direction=ReceiptDirection.OUTBOUND,
    )
    open_item = invoice("INV-OUTBOUND", "1250.00")

    decision = evaluate_cash_application(
        cash,
        remittance(cash.receipt_id, line(open_item.invoice_id, "1250.00")),
        [open_item],
        as_of_date=DECISION_DATE,
    )

    assert decision.application_status is ApplicationStatus.CONTROL_BLOCKED
    assert "receipt.not_inbound" in decision.control_codes
    assert decision.cash_allocated == Decimal("0.00")


def test_simulated_ledger_rejects_any_production_posting_mode() -> None:
    cash = receipt("RCPT-NO-PRODUCTION", "1250.00")
    open_item = invoice("INV-NO-PRODUCTION", "1250.00")
    decision = evaluate_cash_application(
        cash,
        remittance(cash.receipt_id, line(open_item.invoice_id, "1250.00")),
        [open_item],
        as_of_date=DECISION_DATE,
    )
    production_attempt = replace(decision, posting_mode="PRODUCTION")
    ledger = SimulatedCashLedger([open_item])

    with pytest.raises(LedgerInvariantError, match="posting.production_not_permitted"):
        ledger.post(
            production_attempt,
            idempotency_key="production-is-impossible",
            approved_by="controller@example.test",
        )

    assert ledger.invoice(open_item.invoice_id).open_balance == Decimal("1250.00")
    assert ledger.processed_receipt_identities == frozenset()
