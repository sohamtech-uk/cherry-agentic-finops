from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.cash_application.eval_adapter import (
    CanonicalReviewStatus,
    exception_to_canonical_outcome,
)
from app.cash_application.exceptions import (
    ApplicationStatus,
    CashApplicationCase,
    CashReceipt,
    CustomerCandidate,
    CustomerEvidenceBasis,
    CustomerResolution,
    EvidenceLocator,
    EvidenceType,
    ExceptionCode,
    ExceptionOwner,
    ExceptionStatus,
    FinancePolicy,
    OpenInvoice,
    PriorCashApplication,
    ReceiptAllocationStatus,
    ReceiptSettlementStatus,
    RemittanceEvidence,
    RemittanceIntent,
    ResidualType,
    ReviewDecision,
    investigate_cash_exception,
)

CAPTURED_AT = datetime(2026, 9, 5, 12, tzinfo=UTC)


def evidence(
    evidence_id: str,
    source_type: EvidenceType,
    locator: str,
    hash_character: str,
) -> EvidenceLocator:
    return EvidenceLocator(
        evidence_id=evidence_id,
        source_type=source_type,
        source_system="SYNTHETIC_FIXTURE",
        source_object_id=evidence_id,
        locator=locator,
        claim_path="/",
        source_sha256=hash_character * 64,
        captured_at=CAPTURED_AT,
    )


RECEIPT_EVIDENCE = evidence(
    "BANK-2026-09-05-1042",
    EvidenceType.BANK_FEED,
    "bank://statement/2026-09-05/line/42",
    "a",
)
REMITTANCE_EVIDENCE = evidence(
    "REM-1042",
    EvidenceType.REMITTANCE_PDF,
    "gcs://cash-evidence/remittance-1042.pdf#page=1&line=8",
    "b",
)
INVOICE_EVIDENCE = evidence(
    "AR-SNAPSHOT-2026-09-05",
    EvidenceType.AR_LEDGER,
    "erp://open-ar/CUST-0042/INV-2208",
    "c",
)
CUSTOMER_EVIDENCE = evidence(
    "CUSTOMER-MASTER-2026-09-05",
    EvidenceType.CUSTOMER_MASTER,
    "erp://customers/CUST-0042#verified-account",
    "d",
)
POLICY_EVIDENCE = evidence(
    "SHORTPAY-01-v3",
    EvidenceType.POLICY,
    "policy://SHORTPAY-01/versions/3#auto-resolution",
    "e",
)


def receipt(
    amount: str = "9500",
    *,
    currency: str = "GBP",
    settlement_status: ReceiptSettlementStatus = ReceiptSettlementStatus.BOOKED,
    receipt_id: str = "RCPT-1042",
) -> CashReceipt:
    return CashReceipt(
        receipt_id=receipt_id,
        source_system="SYNTHETIC_BANK",
        source_transaction_id="TX-1042",
        booking_date=date(2026, 9, 5),
        payer_name="Northstar Retail",
        amount=amount,
        currency=currency,
        settlement_status=settlement_status,
        allocation_status=ReceiptAllocationStatus.UNAPPLIED,
        version=1,
        evidence=[RECEIPT_EVIDENCE],
    )


def policy() -> FinancePolicy:
    return FinancePolicy(
        policy_id="SHORTPAY-01",
        version=3,
        status="APPROVED",
        effective_from=date(2026, 9, 1),
        currency="GBP",
        max_auto_shortpay="50",
        allowed_auto_reason_codes={"FREIGHT_DAMAGE", "ROUNDING"},
        manual_writeoff_reason_codes=set(),
        requires_explicit_remittance_reason=True,
        evidence=[POLICY_EVIDENCE],
    )


def verified_customer() -> CustomerResolution:
    return CustomerResolution(
        customer_id="CUST-0042",
        evidence_basis=CustomerEvidenceBasis.REMITTANCE_INVOICE,
        evidence=[CUSTOMER_EVIDENCE, REMITTANCE_EVIDENCE],
    )


def invoice(*, balance: str = "10000", currency: str = "GBP") -> OpenInvoice:
    return OpenInvoice(
        invoice_id="INV-2208",
        customer_id="CUST-0042",
        open_balance=balance,
        currency=currency,
        status="OPEN",
        ledger_version=7,
        as_of=date(2026, 9, 5),
        evidence=[INVOICE_EVIDENCE],
    )


def remittance(
    *,
    reason: str | None = "DAMAGED_GOODS",
    deduction_amount: str | None = "500",
    intent: RemittanceIntent = RemittanceIntent.DEDUCTION,
) -> RemittanceEvidence:
    return RemittanceEvidence(
        remittance_id="REM-1042",
        customer_id="CUST-0042",
        invoice_id="INV-2208",
        intent=intent,
        raw_deduction_reason=reason,
        canonical_reason_code=reason,
        reason_mapping_version="DEDUCTION-REASONS-v1" if reason else None,
        deduction_amount=deduction_amount,
        evidence=[REMITTANCE_EVIDENCE],
    )


def cash_case(
    *,
    cash: CashReceipt | None = None,
    customer: CustomerResolution | None = None,
    remittance_record: RemittanceEvidence | None = None,
    invoice_record: OpenInvoice | None = None,
    prior_applications: list[PriorCashApplication] | None = None,
) -> CashApplicationCase:
    return CashApplicationCase(
        decision_date=date(2026, 9, 5),
        receipt=cash or receipt(),
        policy=policy(),
        customer=customer or verified_customer(),
        remittance=remittance_record,
        invoice=invoice_record or invoice(),
        prior_applications=prior_applications or [],
    )


def test_ca05_material_short_pay_is_held_unchanged_for_controller_review() -> None:
    result = investigate_cash_exception(cash_case(remittance_record=remittance()))

    assert result is not None
    assert result.exception_code == ExceptionCode.MATERIAL_SHORT_PAY
    assert result.application_status == ApplicationStatus.REVIEW_REQUIRED
    assert result.exception_status == ExceptionStatus.WAITING_REVIEW
    assert result.receipt_allocation_status == ReceiptAllocationStatus.HELD
    assert result.receipt_amount == Decimal("9500.00")
    assert result.cash_applied_amount == Decimal("0.00")
    assert result.proposed_cash_application_amount == Decimal("9500.00")
    assert result.invoice_open_before == Decimal("10000.00")
    assert result.invoice_open_current == Decimal("10000.00")
    assert result.residual_amount == Decimal("500.00")
    assert result.amount_at_risk == Decimal("500.00")
    assert result.residual_type == ResidualType.INVOICE_BALANCE
    assert (result.policy_id, result.policy_version) == ("SHORTPAY-01", 3)
    assert result.owner == ExceptionOwner.CONTROLLER
    assert result.allowed_next_application_states == [
        ApplicationStatus.EVIDENCE_REQUIRED,
        ApplicationStatus.READY_TO_POST,
        ApplicationStatus.REJECTED,
    ]
    assert result.allowed_review_decisions == [
        ReviewDecision.LEAVE_BALANCE_OPEN,
        ReviewDecision.CREATE_DISPUTE,
        ReviewDecision.REQUEST_EVIDENCE,
        ReviewDecision.REJECT_MATCH,
    ]
    assert ReviewDecision.APPROVE_WRITE_OFF not in result.allowed_review_decisions
    projection = result.recommended_decision_projection
    assert projection is not None
    assert projection.decision == ReviewDecision.CREATE_DISPUTE
    assert projection.cash_applied == Decimal("9500.00")
    assert projection.authorised_adjustment == Decimal("0.00")
    assert projection.invoice_open_after == Decimal("500.00")
    assert projection.receipt_unapplied_residual == Decimal("0.00")
    assert projection.exception_status_after == ExceptionStatus.DISPUTE_OPEN
    assert "Hold the receipt with no ledger mutation" in result.recommended_action
    assert "recommend CREATE_DISPUTE" in result.recommended_action
    assert result.missing_evidence == []
    assert result.conflicting_evidence == [
        "Remittance reason DAMAGED_GOODS is not allowed by policy SHORTPAY-01 v3."
    ]

    evidence_by_id = {item.evidence_id: item for item in result.evidence}
    assert evidence_by_id["BANK-2026-09-05-1042"].source_sha256 == "a" * 64
    assert evidence_by_id["REM-1042"].locator.endswith("#page=1&line=8")
    assert evidence_by_id["AR-SNAPSHOT-2026-09-05"].source_sha256 == "c" * 64
    assert evidence_by_id["SHORTPAY-01-v3"].locator.endswith("#auto-resolution")


def test_conflicting_deduction_amount_outranks_material_review() -> None:
    result = investigate_cash_exception(
        cash_case(remittance_record=remittance(deduction_amount="450"))
    )

    assert result is not None
    assert result.exception_code == ExceptionCode.CONFLICTING_EVIDENCE
    assert result.application_status == ApplicationStatus.EVIDENCE_REQUIRED
    assert result.receipt_allocation_status == ReceiptAllocationStatus.HELD
    assert result.cash_applied_amount == Decimal("0.00")
    assert result.proposed_cash_application_amount == Decimal("0.00")
    assert result.conflicting_evidence == [
        "Remittance deduction 450.00 GBP does not equal exact invoice residual 500.00 GBP."
    ]


def test_ca06_small_difference_without_reason_requests_evidence() -> None:
    result = investigate_cash_exception(
        cash_case(
            cash=receipt("9970"),
            remittance_record=remittance(
                reason=None,
                deduction_amount=None,
                intent=RemittanceIntent.INVOICE_SETTLEMENT,
            ),
        )
    )

    assert result is not None
    assert result.exception_code == ExceptionCode.UNSUPPORTED_DEDUCTION
    assert result.application_status == ApplicationStatus.EVIDENCE_REQUIRED
    assert result.exception_status == ExceptionStatus.WAITING_EVIDENCE
    assert result.receipt_allocation_status == ReceiptAllocationStatus.HELD
    assert result.cash_applied_amount == Decimal("0.00")
    assert result.proposed_cash_application_amount == Decimal("9970.00")
    assert result.invoice_open_current == Decimal("10000.00")
    assert result.residual_amount == Decimal("30.00")
    assert result.amount_at_risk == Decimal("30.00")
    assert result.missing_evidence == [
        "explicit_remittance_deduction_reason",
        "explicit_remittance_deduction_amount",
    ]
    assert result.allowed_next_application_states == [ApplicationStatus.SUPERSEDED]
    assert result.allowed_review_decisions == []
    assert "being within the 50.00 GBP tolerance is not sufficient" in result.recommended_action


def test_missing_remittance_keeps_full_receipt_unapplied_and_held() -> None:
    result = investigate_cash_exception(cash_case(remittance_record=None))

    assert result is not None
    assert result.exception_code == ExceptionCode.MISSING_REMITTANCE
    assert result.application_status == ApplicationStatus.EVIDENCE_REQUIRED
    assert result.receipt_allocation_status == ReceiptAllocationStatus.HELD
    assert result.cash_applied_amount == Decimal("0.00")
    assert result.proposed_cash_application_amount == Decimal("0.00")
    assert result.residual_amount == Decimal("9500.00")
    assert result.residual_type == ResidualType.UNAPPLIED_CASH
    assert result.missing_evidence == ["remittance", "invoice_allocation_evidence"]


def test_ca08_ambiguous_customer_never_selects_a_name_only_candidate() -> None:
    alias_evidence = evidence(
        "CUSTOMER-ALIASES-2026-09-05",
        EvidenceType.CUSTOMER_MASTER,
        "erp://customer-aliases?alias=Northstar%20Group",
        "f",
    )
    ambiguous = CustomerResolution(
        candidates=[
            CustomerCandidate(
                customer_id="CUST-0042",
                display_name="Northstar Retail Ltd",
                evidence=[alias_evidence],
            ),
            CustomerCandidate(
                customer_id="CUST-0099",
                display_name="Northstar Wholesale Ltd",
                evidence=[alias_evidence],
            ),
        ]
    )
    no_unique_reference = RemittanceEvidence(
        remittance_id="REM-AMBIGUOUS",
        evidence=[REMITTANCE_EVIDENCE],
    )

    result = investigate_cash_exception(
        cash_case(customer=ambiguous, remittance_record=no_unique_reference)
    )

    assert result is not None
    assert result.exception_code == ExceptionCode.AMBIGUOUS_CUSTOMER
    assert result.customer_id is None
    assert result.application_status == ApplicationStatus.EVIDENCE_REQUIRED
    assert result.cash_applied_amount == Decimal("0.00")
    assert result.proposed_cash_application_amount == Decimal("0.00")
    assert result.amount_at_risk == Decimal("9500.00")
    assert result.missing_evidence == ["unique_customer_identity_evidence"]
    assert result.conflicting_evidence == [
        "Payer identity remains unresolved across customer candidates: CUST-0042, CUST-0099."
    ]
    assert "do not select a customer from name similarity" in result.recommended_action


def test_ca09_overpayment_exposes_only_supported_proposal_and_receipt_residual() -> None:
    result = investigate_cash_exception(
        cash_case(
            cash=receipt("1200"),
            remittance_record=remittance(
                reason=None,
                deduction_amount=None,
                intent=RemittanceIntent.INVOICE_SETTLEMENT,
            ),
            invoice_record=invoice(balance="1000"),
        )
    )

    assert result is not None
    assert result.exception_code == ExceptionCode.OVERPAYMENT_RESIDUAL
    assert result.application_status == ApplicationStatus.READY_TO_POST
    assert result.cash_applied_amount == Decimal("0.00")
    assert result.proposed_cash_application_amount == Decimal("1000.00")
    assert result.residual_amount == Decimal("200.00")
    assert result.residual_type == ResidualType.UNAPPLIED_CASH
    assert result.allowed_next_application_states == [ApplicationStatus.POSTED_SIMULATED]
    assert "retain 200.00 GBP as explicit unapplied cash" in result.recommended_action


def test_ca10_currency_mismatch_is_terminal_and_not_approvable() -> None:
    result = investigate_cash_exception(
        cash_case(
            cash=receipt("780", currency="GBP"),
            remittance_record=remittance(
                reason=None,
                deduction_amount=None,
                intent=RemittanceIntent.INVOICE_SETTLEMENT,
            ),
            invoice_record=invoice(balance="1000", currency="USD"),
        )
    )

    assert result is not None
    assert result.exception_code == ExceptionCode.CURRENCY_MISMATCH
    assert result.application_status == ApplicationStatus.CONTROL_BLOCKED
    assert result.exception_status == ExceptionStatus.BLOCKED
    assert result.receipt_allocation_status == ReceiptAllocationStatus.UNAPPLIED
    assert result.cash_applied_amount == Decimal("0.00")
    assert result.proposed_cash_application_amount == Decimal("0.00")
    assert result.invoice_open_current == Decimal("1000.00")
    assert result.residual_amount == Decimal("780.00")
    assert result.allowed_next_application_states == []
    assert result.allowed_review_decisions == []
    assert result.missing_evidence == [
        "approved_fx_settlement_rule",
        "approved_fx_rate_evidence",
    ]
    assert "Do not convert or apply cash" in result.recommended_action


@pytest.mark.parametrize(
    "settlement_status",
    [ReceiptSettlementStatus.PENDING, ReceiptSettlementStatus.REVERSED],
)
def test_ca11_ineligible_cash_is_terminal_and_not_approvable(
    settlement_status: ReceiptSettlementStatus,
) -> None:
    result = investigate_cash_exception(
        cash_case(
            cash=receipt(settlement_status=settlement_status),
            remittance_record=remittance(),
        )
    )

    assert result is not None
    assert result.exception_code == ExceptionCode.INELIGIBLE_RECEIPT
    assert result.application_status == ApplicationStatus.CONTROL_BLOCKED
    assert result.exception_status == ExceptionStatus.BLOCKED
    assert result.cash_applied_amount == Decimal("0.00")
    assert result.invoice_open_current == Decimal("10000.00")
    assert result.allowed_next_application_states == []
    assert result.allowed_review_decisions == []
    assert f"settlement status is {settlement_status}" in result.recommended_action


def test_exact_bank_source_identity_blocks_before_all_other_interpretation() -> None:
    prior_evidence = evidence(
        "APPLICATION-7781",
        EvidenceType.PRIOR_APPLICATION,
        "erp://cash-applications/APPL-7781",
        "1",
    )
    previous = PriorCashApplication(
        receipt_id="RCPT-ORIGINAL",
        source_system="SYNTHETIC_BANK",
        source_transaction_id="TX-1042",
        application_id="APPL-7781",
        evidence=[prior_evidence],
    )

    result = investigate_cash_exception(
        cash_case(
            cash=receipt(
                settlement_status=ReceiptSettlementStatus.REVERSED,
                receipt_id="RCPT-RETRY",
            ),
            remittance_record=None,
            prior_applications=[previous],
        )
    )

    assert result is not None
    assert result.exception_code == ExceptionCode.DUPLICATE_RECEIPT
    assert result.application_status == ApplicationStatus.CONTROL_BLOCKED
    assert result.cash_applied_amount == Decimal("0.00")
    assert result.allowed_next_application_states == []
    assert result.allowed_review_decisions == []
    assert result.conflicting_evidence == [
        "Bank source identity (SYNTHETIC_BANK, TX-1042) already has application APPL-7781 "
        "for receipt RCPT-ORIGINAL."
    ]


def test_policy_bounded_short_pay_has_no_scoped_exception_with_complete_evidence() -> None:
    result = investigate_cash_exception(
        cash_case(
            cash=receipt("9970"),
            remittance_record=remittance(
                reason="freight_damage",
                deduction_amount="30",
            ),
        )
    )

    assert result is None


def test_contract_rejects_untraceable_evidence_and_inactive_policy() -> None:
    with pytest.raises(ValidationError, match="source_sha256"):
        EvidenceLocator(
            evidence_id="bad",
            source_type=EvidenceType.REMITTANCE_JSON,
            source_system="fixture",
            source_object_id="bad",
            locator="document://bad",
            claim_path="/invoice_id",
            source_sha256="not-a-hash",
        )

    inactive_policy = policy().model_copy(update={"effective_from": date(2026, 10, 1)})
    with pytest.raises(ValidationError, match="not effective"):
        CashApplicationCase(
            decision_date=date(2026, 9, 5),
            receipt=receipt(),
            policy=inactive_policy,
            customer=verified_customer(),
            remittance=remittance(),
            invoice=invoice(),
        )


def test_ca05_maps_to_canonical_eval_sections_without_ledger_mutation() -> None:
    case = cash_case(remittance_record=remittance())
    exception = investigate_cash_exception(case)
    assert exception is not None

    outcome = exception_to_canonical_outcome(case, exception, "CA-05-trial-1")

    assert outcome.trial_id == "CA-05-trial-1"
    assert outcome.receipt.settlement_status == ReceiptSettlementStatus.BOOKED
    assert outcome.receipt.allocation_status == ReceiptAllocationStatus.HELD
    assert outcome.receipt.cash_applied_amount == Decimal("0.00")
    assert outcome.receipt.unapplied_cash_amount == Decimal("9500.00")
    assert outcome.application.status == ApplicationStatus.REVIEW_REQUIRED
    assert outcome.application.ledger_mutation_occurred is False
    assert outcome.invoice.open_before == Decimal("10000.00")
    assert outcome.invoice.open_current == Decimal("10000.00")
    assert outcome.exception.code == ExceptionCode.MATERIAL_SHORT_PAY
    assert outcome.exception.residual_amount == Decimal("500.00")
    assert outcome.review.status == CanonicalReviewStatus.REQUESTED
    assert outcome.review.recommended_decision == ReviewDecision.CREATE_DISPUTE
    assert (outcome.policy.policy_id, outcome.policy.version) == ("SHORTPAY-01", 3)
    assert outcome.policy.evidence[0].source_sha256 == "e" * 64
    assert outcome.audit.action == "cash_exception_evaluated"
    assert outcome.audit.ledger_state_delta == {}
    assert outcome.audit.deterministic is True
    assert outcome.narrative_is_authoritative is False


def test_model_narrative_cannot_change_authoritative_outcome_hash() -> None:
    case = cash_case(remittance_record=remittance())
    exception = investigate_cash_exception(case)
    assert exception is not None
    rewritten = exception.model_copy(
        update={"recommended_action": "Model-authored text attempting a different action."}
    )

    grounded = exception_to_canonical_outcome(case, exception, "CA-05-trial-2")
    with_rewritten_narrative = exception_to_canonical_outcome(
        case,
        rewritten,
        "CA-05-trial-2",
    )

    assert grounded.audit.output_hash == with_rewritten_narrative.audit.output_hash
    assert grounded.review == with_rewritten_narrative.review
    assert grounded.exception == with_rewritten_narrative.exception
    assert (
        grounded.advisory_recommended_action != with_rewritten_narrative.advisory_recommended_action
    )


def test_canonical_adapter_fails_closed_on_mismatched_case_identity() -> None:
    case = cash_case(remittance_record=remittance())
    exception = investigate_cash_exception(case)
    assert exception is not None
    different_case = case.model_copy(update={"receipt": receipt(receipt_id="RCPT-DIFFERENT")})

    with pytest.raises(ValueError, match="receipt does not match"):
        exception_to_canonical_outcome(different_case, exception, "CA-05-trial-3")


def test_canonical_adapter_rejects_model_changed_authoritative_fields() -> None:
    case = cash_case(remittance_record=remittance())
    exception = investigate_cash_exception(case)
    assert exception is not None
    changed_amount = exception.model_copy(update={"amount_at_risk": Decimal("1.00")})

    with pytest.raises(ValueError, match="do not match deterministic evaluation"):
        exception_to_canonical_outcome(case, changed_amount, "CA-05-trial-4")


@pytest.mark.parametrize(
    (
        "case",
        "expected_code",
        "expected_application_status",
        "expected_allocation_status",
        "expected_review_status",
    ),
    [
        (
            cash_case(
                cash=receipt("9970"),
                remittance_record=remittance(reason=None, deduction_amount=None),
            ),
            ExceptionCode.UNSUPPORTED_DEDUCTION,
            ApplicationStatus.EVIDENCE_REQUIRED,
            ReceiptAllocationStatus.HELD,
            CanonicalReviewStatus.NOT_CREATED,
        ),
        (
            cash_case(
                cash=receipt("1200"),
                remittance_record=remittance(reason=None, deduction_amount=None),
                invoice_record=invoice(balance="1000"),
            ),
            ExceptionCode.OVERPAYMENT_RESIDUAL,
            ApplicationStatus.READY_TO_POST,
            ReceiptAllocationStatus.UNAPPLIED,
            CanonicalReviewStatus.REQUESTED,
        ),
        (
            cash_case(
                cash=receipt("780"),
                remittance_record=remittance(reason=None, deduction_amount=None),
                invoice_record=invoice(balance="1000", currency="USD"),
            ),
            ExceptionCode.CURRENCY_MISMATCH,
            ApplicationStatus.CONTROL_BLOCKED,
            ReceiptAllocationStatus.UNAPPLIED,
            CanonicalReviewStatus.NOT_CREATED,
        ),
        (
            cash_case(
                cash=receipt(settlement_status=ReceiptSettlementStatus.PENDING),
                remittance_record=remittance(),
            ),
            ExceptionCode.INELIGIBLE_RECEIPT,
            ApplicationStatus.CONTROL_BLOCKED,
            ReceiptAllocationStatus.UNAPPLIED,
            CanonicalReviewStatus.NOT_CREATED,
        ),
    ],
    ids=["CA-06", "CA-09", "CA-10", "CA-11"],
)
def test_exception_cases_map_to_canonical_eval_states(
    case: CashApplicationCase,
    expected_code: ExceptionCode,
    expected_application_status: ApplicationStatus,
    expected_allocation_status: ReceiptAllocationStatus,
    expected_review_status: CanonicalReviewStatus,
) -> None:
    exception = investigate_cash_exception(case)
    assert exception is not None

    outcome = exception_to_canonical_outcome(case, exception, f"{expected_code}-trial")

    assert outcome.exception.code == expected_code
    assert outcome.application.status == expected_application_status
    assert outcome.receipt.allocation_status == expected_allocation_status
    assert outcome.review.status == expected_review_status
    assert outcome.application.ledger_mutation_occurred is False
    assert outcome.audit.ledger_state_delta == {}
