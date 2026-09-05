"""Grounded, deterministic cash-application exception investigation.

This module is intentionally a read-only decision boundary.  It accepts facts that have already
been extracted from supplied evidence, applies fixed accounting controls, and returns a typed
exception packet.  It does not call a model, infer missing remittance facts, mutate policy, or post
to an AR ledger.  A model may help an upstream adapter interpret a document, but every interpreted
fact supplied here must retain its source locator and SHA-256 identity.

The first integration boundary is deliberately narrow: one receipt and, where evidence permits,
one referenced open invoice.  Multi-invoice allocation and state-changing review decisions belong
to separate deterministic services.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TWOPLACES = Decimal("0.01")


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


class EvidenceType(StrEnum):
    BANK_FEED = "BANK_FEED"
    REMITTANCE_PDF = "REMITTANCE_PDF"
    REMITTANCE_JSON = "REMITTANCE_JSON"
    AR_LEDGER = "AR_LEDGER"
    CUSTOMER_MASTER = "customer_master"
    POLICY = "POLICY"
    PRIOR_APPLICATION = "prior_application"


class EvidenceLocator(BaseModel):
    """Stable source identity carried through to every exception packet."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(min_length=1)
    source_type: EvidenceType
    source_system: str = Field(min_length=1)
    source_object_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    claim_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    parser: str = Field(default="DIRECT_SOURCE", min_length=1)
    extraction_confidence: int | None = Field(default=None, ge=0, le=100)


class ReceiptSettlementStatus(StrEnum):
    BOOKED = "BOOKED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"


class ReceiptAllocationStatus(StrEnum):
    UNAPPLIED = "UNAPPLIED"
    HELD = "HELD"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    APPLIED = "APPLIED"


class CashReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_transaction_id: str = Field(min_length=1)
    booking_date: date
    payer_name: str = Field(min_length=1)
    amount: Decimal
    currency: str
    settlement_status: ReceiptSettlementStatus
    allocation_status: ReceiptAllocationStatus = ReceiptAllocationStatus.UNAPPLIED
    version: int = Field(default=1, ge=1)
    evidence: list[EvidenceLocator] = Field(min_length=1)

    @field_validator("amount", mode="before")
    @classmethod
    def normalise_amount(cls, value: Any) -> Decimal:
        amount = _money(value)
        if amount <= 0:
            raise ValueError("Receipt amount must be greater than zero.")
        return amount

    @field_validator("currency")
    @classmethod
    def normalise_currency(cls, value: str) -> str:
        currency = value.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("Currency must be a three-letter code.")
        return currency


class RemittanceIntent(StrEnum):
    INVOICE_SETTLEMENT = "invoice_settlement"
    PARTIAL_PAYMENT = "partial_payment"
    DEDUCTION = "deduction"


class RemittanceEvidence(BaseModel):
    """Normalised claims from supplied remittance; absent fields remain explicitly absent."""

    model_config = ConfigDict(frozen=True)

    remittance_id: str = Field(min_length=1)
    customer_id: str | None = None
    invoice_id: str | None = None
    intent: RemittanceIntent = RemittanceIntent.INVOICE_SETTLEMENT
    raw_deduction_reason: str | None = None
    canonical_reason_code: str | None = None
    reason_mapping_version: str | None = None
    deduction_amount: Decimal | None = None
    evidence: list[EvidenceLocator] = Field(min_length=1)

    @field_validator("canonical_reason_code")
    @classmethod
    def normalise_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        reason = value.strip().upper()
        return reason or None

    @field_validator("deduction_amount", mode="before")
    @classmethod
    def normalise_deduction(cls, value: Any) -> Decimal | None:
        if value is None:
            return None
        amount = _money(value)
        if amount < 0:
            raise ValueError("Deduction amount cannot be negative.")
        return amount

    @model_validator(mode="after")
    def require_mapping_provenance(self) -> RemittanceEvidence:
        if self.canonical_reason_code is not None and (
            self.raw_deduction_reason is None or self.reason_mapping_version is None
        ):
            raise ValueError(
                "A canonical reason requires the evidenced raw reason and mapping version."
            )
        return self


class CustomerEvidenceBasis(StrEnum):
    REMITTANCE_ACCOUNT = "remittance_account"
    REMITTANCE_INVOICE = "remittance_invoice"
    VERIFIED_BANK_ACCOUNT = "verified_bank_account"


class CustomerCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    customer_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    evidence: list[EvidenceLocator] = Field(min_length=1)


class CustomerResolution(BaseModel):
    """A verified identity or unresolved candidates; payer-name similarity is not a basis."""

    model_config = ConfigDict(frozen=True)

    customer_id: str | None = None
    evidence_basis: CustomerEvidenceBasis | None = None
    evidence: list[EvidenceLocator] = Field(default_factory=list)
    candidates: list[CustomerCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_grounding_for_verified_identity(self) -> CustomerResolution:
        supplied = self.customer_id is not None
        if supplied != (self.evidence_basis is not None):
            raise ValueError("Verified customer id and evidence basis must be supplied together.")
        if supplied and not self.evidence:
            raise ValueError("A verified customer identity requires source evidence.")
        return self


class OpenInvoice(BaseModel):
    model_config = ConfigDict(frozen=True)

    invoice_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    open_balance: Decimal
    currency: str
    status: str = "OPEN"
    ledger_version: int = Field(default=1, ge=1)
    as_of: date
    evidence: list[EvidenceLocator] = Field(min_length=1)

    @field_validator("open_balance", mode="before")
    @classmethod
    def normalise_balance(cls, value: Any) -> Decimal:
        balance = _money(value)
        if balance <= 0:
            raise ValueError("Open invoice balance must be greater than zero.")
        return balance

    @field_validator("currency")
    @classmethod
    def normalise_currency(cls, value: str) -> str:
        currency = value.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("Currency must be a three-letter code.")
        return currency


class FinancePolicy(BaseModel):
    """The effective, approved policy snapshot selected by an upstream policy repository."""

    model_config = ConfigDict(frozen=True)

    policy_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    status: str = "APPROVED"
    effective_from: date
    effective_to: date | None = None
    currency: str
    max_auto_shortpay: Decimal
    allowed_auto_reason_codes: set[str] = Field(default_factory=set)
    manual_writeoff_reason_codes: set[str] = Field(default_factory=set)
    requires_explicit_remittance_reason: bool = True
    evidence: list[EvidenceLocator] = Field(min_length=1)

    @field_validator("max_auto_shortpay", mode="before")
    @classmethod
    def normalise_threshold(cls, value: Any) -> Decimal:
        threshold = _money(value)
        if threshold < 0:
            raise ValueError("Short-pay threshold cannot be negative.")
        return threshold

    @field_validator("allowed_auto_reason_codes", "manual_writeoff_reason_codes")
    @classmethod
    def normalise_reason_codes(cls, values: set[str]) -> set[str]:
        return {value.strip().upper() for value in values if value.strip()}

    @field_validator("currency")
    @classmethod
    def normalise_currency(cls, value: str) -> str:
        currency = value.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("Currency must be a three-letter code.")
        return currency

    @model_validator(mode="after")
    def validate_effective_period(self) -> FinancePolicy:
        if self.status != "APPROVED":
            raise ValueError("Only an APPROVED finance policy can govern an application.")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("Policy effective_to cannot precede effective_from.")
        return self


class PriorCashApplication(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_transaction_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    evidence: list[EvidenceLocator] = Field(min_length=1)


class CashApplicationCase(BaseModel):
    """Read-only facts for a deterministic, single-invoice exception investigation."""

    model_config = ConfigDict(frozen=True)

    decision_date: date
    receipt: CashReceipt
    policy: FinancePolicy
    customer: CustomerResolution
    remittance: RemittanceEvidence | None = None
    invoice: OpenInvoice | None = None
    prior_applications: list[PriorCashApplication] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_effective_policy(self) -> CashApplicationCase:
        if self.decision_date < self.policy.effective_from or (
            self.policy.effective_to is not None and self.decision_date > self.policy.effective_to
        ):
            raise ValueError("The supplied finance policy is not effective on the decision date.")
        if self.policy.currency != self.receipt.currency:
            raise ValueError("The supplied finance policy does not govern the receipt currency.")
        return self


class ExceptionCode(StrEnum):
    MATERIAL_SHORT_PAY = "MATERIAL_SHORT_PAY"
    UNSUPPORTED_DEDUCTION = "UNSUPPORTED_DEDUCTION"
    MISSING_REMITTANCE = "MISSING_REMITTANCE"
    AMBIGUOUS_CUSTOMER = "AMBIGUOUS_CUSTOMER"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    OVERPAYMENT_RESIDUAL = "OVERPAYMENT_RESIDUAL"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    INELIGIBLE_RECEIPT = "INELIGIBLE_RECEIPT"
    DUPLICATE_RECEIPT = "DUPLICATE_RECEIPT"


class ApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    CONTROL_BLOCKED = "CONTROL_BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    READY_TO_POST = "READY_TO_POST"
    POSTED_SIMULATED = "POSTED_SIMULATED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ExceptionStatus(StrEnum):
    WAITING_EVIDENCE = "WAITING_EVIDENCE"
    WAITING_REVIEW = "WAITING_REVIEW"
    DISPUTE_OPEN = "DISPUTE_OPEN"
    COLLECTIONS_OPEN = "COLLECTIONS_OPEN"
    RESOLVED = "RESOLVED"
    BLOCKED = "BLOCKED"


class ResidualType(StrEnum):
    INVOICE_BALANCE = "invoice_balance"
    UNAPPLIED_CASH = "unapplied_cash"
    BLOCKED_CASH = "blocked_cash"


class ReviewDecision(StrEnum):
    APPROVE_WRITE_OFF = "APPROVE_WRITE_OFF"
    LEAVE_BALANCE_OPEN = "LEAVE_BALANCE_OPEN"
    CREATE_DISPUTE = "CREATE_DISPUTE"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    REJECT_MATCH = "REJECT_MATCH"


class ExceptionOwner(StrEnum):
    AR_ANALYST = "ar_analyst"
    CONTROLLER = "controller"
    TREASURY = "treasury"
    CASH_APPLICATION_CONTROL = "cash_application_control"


class DecisionProjection(BaseModel):
    """Non-posting projection for a typed review decision; current balances remain unchanged."""

    model_config = ConfigDict(frozen=True)

    decision: ReviewDecision
    cash_applied: Decimal
    authorised_adjustment: Decimal
    invoice_open_after: Decimal
    receipt_unapplied_residual: Decimal
    exception_status_after: ExceptionStatus

    @field_validator(
        "cash_applied",
        "authorised_adjustment",
        "invoice_open_after",
        "receipt_unapplied_residual",
        mode="before",
    )
    @classmethod
    def normalise_non_negative_money(cls, value: Any) -> Decimal:
        amount = _money(value)
        if amount < 0:
            raise ValueError("Projected accounting amounts cannot be negative.")
        return amount


class CashApplicationException(BaseModel):
    """Grounded context only; this object neither applies cash nor records a review decision."""

    model_config = ConfigDict(frozen=True)

    exception_code: ExceptionCode
    application_status: ApplicationStatus
    exception_status: ExceptionStatus
    receipt_allocation_status: ReceiptAllocationStatus
    receipt_id: str
    invoice_id: str | None
    customer_id: str | None
    currency: str
    receipt_amount: Decimal
    cash_applied_amount: Decimal
    proposed_cash_application_amount: Decimal
    invoice_open_before: Decimal | None
    invoice_open_current: Decimal | None
    residual_amount: Decimal
    residual_type: ResidualType
    amount_at_risk: Decimal
    policy_id: str
    policy_version: int
    evidence: list[EvidenceLocator]
    missing_evidence: list[str]
    conflicting_evidence: list[str]
    owner: ExceptionOwner
    allowed_next_application_states: list[ApplicationStatus]
    allowed_review_decisions: list[ReviewDecision]
    recommended_decision_projection: DecisionProjection | None = None
    recommended_action: str


def _evidence(case: CashApplicationCase) -> list[EvidenceLocator]:
    records = [*case.receipt.evidence, *case.policy.evidence, *case.customer.evidence]
    for candidate in case.customer.candidates:
        records.extend(candidate.evidence)
    if case.remittance is not None:
        records.extend(case.remittance.evidence)
    if case.invoice is not None:
        records.extend(case.invoice.evidence)
    for application in case.prior_applications:
        records.extend(application.evidence)

    unique: dict[tuple[str, str, str], EvidenceLocator] = {}
    for record in records:
        unique[(record.evidence_id, record.locator, record.source_sha256)] = record
    return list(unique.values())


def _exception(
    case: CashApplicationCase,
    *,
    code: ExceptionCode,
    application_status: ApplicationStatus,
    exception_status: ExceptionStatus,
    receipt_allocation_status: ReceiptAllocationStatus,
    supported: Decimal,
    residual: Decimal,
    residual_type: ResidualType,
    owner: ExceptionOwner,
    allowed_application_states: list[ApplicationStatus],
    allowed_review_decisions: list[ReviewDecision],
    action: str,
    recommended_projection: DecisionProjection | None = None,
    missing: list[str] | None = None,
    conflicting: list[str] | None = None,
) -> CashApplicationException:
    return CashApplicationException(
        exception_code=code,
        application_status=application_status,
        exception_status=exception_status,
        receipt_allocation_status=receipt_allocation_status,
        receipt_id=case.receipt.receipt_id,
        invoice_id=case.invoice.invoice_id if case.invoice else None,
        customer_id=case.customer.customer_id,
        currency=case.receipt.currency,
        receipt_amount=case.receipt.amount,
        cash_applied_amount=Decimal("0.00"),
        proposed_cash_application_amount=_money(supported),
        invoice_open_before=case.invoice.open_balance if case.invoice else None,
        invoice_open_current=case.invoice.open_balance if case.invoice else None,
        residual_amount=_money(residual),
        residual_type=residual_type,
        amount_at_risk=_money(residual),
        policy_id=case.policy.policy_id,
        policy_version=case.policy.version,
        evidence=_evidence(case),
        missing_evidence=missing or [],
        conflicting_evidence=conflicting or [],
        owner=owner,
        allowed_next_application_states=allowed_application_states,
        allowed_review_decisions=allowed_review_decisions,
        recommended_decision_projection=recommended_projection,
        recommended_action=action,
    )


def investigate_cash_exception(case: CashApplicationCase) -> CashApplicationException | None:
    """Return the authoritative exception context, or ``None`` when this layer finds none.

    Hard controls run first so a duplicate or ineligible receipt cannot be made eligible by richer
    remittance evidence or a human-facing recommendation.  Returning ``None`` is not posting
    authority; it only means this exception layer found no scoped exception.
    """

    duplicate = next(
        (
            item
            for item in case.prior_applications
            if (
                item.source_system,
                item.source_transaction_id,
            )
            == (
                case.receipt.source_system,
                case.receipt.source_transaction_id,
            )
        ),
        None,
    )
    if duplicate is not None:
        return _exception(
            case,
            code=ExceptionCode.DUPLICATE_RECEIPT,
            application_status=ApplicationStatus.CONTROL_BLOCKED,
            exception_status=ExceptionStatus.BLOCKED,
            receipt_allocation_status=case.receipt.allocation_status,
            supported=Decimal("0"),
            residual=case.receipt.amount,
            residual_type=ResidualType.BLOCKED_CASH,
            owner=ExceptionOwner.CASH_APPLICATION_CONTROL,
            allowed_application_states=[],
            allowed_review_decisions=[],
            action=(
                f"Keep the receipt blocked; prior application {duplicate.application_id} must not "
                "be duplicated or overridden by review."
            ),
            conflicting=[
                f"Bank source identity ({case.receipt.source_system}, "
                f"{case.receipt.source_transaction_id}) already has application "
                f"{duplicate.application_id} for receipt {duplicate.receipt_id}."
            ],
        )

    if case.receipt.settlement_status != ReceiptSettlementStatus.BOOKED:
        return _exception(
            case,
            code=ExceptionCode.INELIGIBLE_RECEIPT,
            application_status=ApplicationStatus.CONTROL_BLOCKED,
            exception_status=ExceptionStatus.BLOCKED,
            receipt_allocation_status=case.receipt.allocation_status,
            supported=Decimal("0"),
            residual=case.receipt.amount,
            residual_type=ResidualType.BLOCKED_CASH,
            owner=ExceptionOwner.TREASURY,
            allowed_application_states=[],
            allowed_review_decisions=[],
            action=(
                "Do not apply the receipt while its bank settlement status is "
                f"{case.receipt.settlement_status}; "
                "wait for independently evidenced BOOKED cash."
            ),
            conflicting=[
                f"Receipt settlement status {case.receipt.settlement_status} is not eligible for "
                "cash application."
            ],
        )

    if case.remittance is None:
        return _exception(
            case,
            code=ExceptionCode.MISSING_REMITTANCE,
            application_status=ApplicationStatus.EVIDENCE_REQUIRED,
            exception_status=ExceptionStatus.WAITING_EVIDENCE,
            receipt_allocation_status=ReceiptAllocationStatus.HELD,
            supported=Decimal("0"),
            residual=case.receipt.amount,
            residual_type=ResidualType.UNAPPLIED_CASH,
            owner=ExceptionOwner.AR_ANALYST,
            allowed_application_states=[ApplicationStatus.SUPERSEDED],
            allowed_review_decisions=[],
            action=(
                "Keep the receipt unapplied and request remittance with invoice allocation "
                "evidence."
            ),
            missing=["remittance", "invoice_allocation_evidence"],
        )

    identity_conflicts: list[str] = []
    if case.customer.customer_id is None:
        candidate_ids = sorted({item.customer_id for item in case.customer.candidates})
        if candidate_ids:
            identity_conflicts.append(
                "Payer identity remains unresolved across customer candidates: "
                + ", ".join(candidate_ids)
                + "."
            )
    elif case.remittance.customer_id not in (None, case.customer.customer_id):
        identity_conflicts.append(
            f"Verified customer {case.customer.customer_id} conflicts with remittance customer "
            f"{case.remittance.customer_id}."
        )
    if case.invoice is not None and case.customer.customer_id not in (
        None,
        case.invoice.customer_id,
    ):
        identity_conflicts.append(
            f"Verified customer {case.customer.customer_id} conflicts with invoice customer "
            f"{case.invoice.customer_id}."
        )
    if case.customer.customer_id is None or identity_conflicts:
        return _exception(
            case,
            code=ExceptionCode.AMBIGUOUS_CUSTOMER,
            application_status=ApplicationStatus.EVIDENCE_REQUIRED,
            exception_status=ExceptionStatus.WAITING_EVIDENCE,
            receipt_allocation_status=ReceiptAllocationStatus.HELD,
            supported=Decimal("0"),
            residual=case.receipt.amount,
            residual_type=ResidualType.UNAPPLIED_CASH,
            owner=ExceptionOwner.AR_ANALYST,
            allowed_application_states=[ApplicationStatus.SUPERSEDED],
            allowed_review_decisions=[],
            action=(
                "Keep the receipt unapplied and obtain a unique account, invoice, or verified "
                "bank-account identifier; do not select a customer from name similarity."
            ),
            missing=["unique_customer_identity_evidence"],
            conflicting=identity_conflicts,
        )

    if case.invoice is None or case.remittance.invoice_id != case.invoice.invoice_id:
        conflicts = []
        if case.invoice is not None and case.remittance.invoice_id is not None:
            conflicts.append(
                f"Remittance invoice {case.remittance.invoice_id} conflicts with supplied open AR "
                f"invoice {case.invoice.invoice_id}."
            )
        return _exception(
            case,
            code=ExceptionCode.MISSING_REMITTANCE,
            application_status=ApplicationStatus.EVIDENCE_REQUIRED,
            exception_status=ExceptionStatus.WAITING_EVIDENCE,
            receipt_allocation_status=ReceiptAllocationStatus.HELD,
            supported=Decimal("0"),
            residual=case.receipt.amount,
            residual_type=ResidualType.UNAPPLIED_CASH,
            owner=ExceptionOwner.AR_ANALYST,
            allowed_application_states=[ApplicationStatus.SUPERSEDED],
            allowed_review_decisions=[],
            action=(
                "Keep the receipt unapplied and request remittance that identifies a supplied open "
                "AR invoice."
            ),
            missing=["supported_open_invoice_allocation"],
            conflicting=conflicts,
        )

    if case.receipt.currency != case.invoice.currency:
        return _exception(
            case,
            code=ExceptionCode.CURRENCY_MISMATCH,
            application_status=ApplicationStatus.CONTROL_BLOCKED,
            exception_status=ExceptionStatus.BLOCKED,
            receipt_allocation_status=case.receipt.allocation_status,
            supported=Decimal("0"),
            residual=case.receipt.amount,
            residual_type=ResidualType.BLOCKED_CASH,
            owner=ExceptionOwner.CONTROLLER,
            allowed_application_states=[],
            allowed_review_decisions=[],
            action=(
                "Do not convert or apply cash; obtain an approved FX settlement rule and evidenced "
                "rate for controller review."
            ),
            missing=["approved_fx_settlement_rule", "approved_fx_rate_evidence"],
            conflicting=[
                f"Receipt currency {case.receipt.currency} conflicts with invoice currency "
                f"{case.invoice.currency}."
            ],
        )

    invoice_balance = case.invoice.open_balance
    receipt_amount = case.receipt.amount
    if receipt_amount > invoice_balance:
        residual = receipt_amount - invoice_balance
        return _exception(
            case,
            code=ExceptionCode.OVERPAYMENT_RESIDUAL,
            application_status=ApplicationStatus.READY_TO_POST,
            exception_status=ExceptionStatus.WAITING_REVIEW,
            receipt_allocation_status=ReceiptAllocationStatus.UNAPPLIED,
            supported=invoice_balance,
            residual=residual,
            residual_type=ResidualType.UNAPPLIED_CASH,
            owner=ExceptionOwner.AR_ANALYST,
            allowed_application_states=[ApplicationStatus.POSTED_SIMULATED],
            allowed_review_decisions=[],
            action=(
                f"Apply no more than {invoice_balance} {case.receipt.currency} to invoice "
                f"{case.invoice.invoice_id}; retain {residual} {case.receipt.currency} as explicit "
                "unapplied cash for on-account or refund review."
            ),
        )

    exact_payment = receipt_amount == invoice_balance
    explicit_partial_payment = case.remittance.intent == RemittanceIntent.PARTIAL_PAYMENT
    if exact_payment or explicit_partial_payment:
        return None

    residual = invoice_balance - receipt_amount
    reason = case.remittance.canonical_reason_code
    claimed_amount = case.remittance.deduction_amount
    missing: list[str] = []
    conflicting: list[str] = []
    if reason is None:
        missing.append("explicit_remittance_deduction_reason")
    if claimed_amount is None:
        missing.append("explicit_remittance_deduction_amount")
    elif claimed_amount != residual:
        conflicting.append(
            f"Remittance deduction {claimed_amount} {case.receipt.currency} does not equal exact "
            f"invoice residual {residual} {case.receipt.currency}."
        )

    if claimed_amount is not None and claimed_amount != residual:
        return _exception(
            case,
            code=ExceptionCode.CONFLICTING_EVIDENCE,
            application_status=ApplicationStatus.EVIDENCE_REQUIRED,
            exception_status=ExceptionStatus.WAITING_EVIDENCE,
            receipt_allocation_status=ReceiptAllocationStatus.HELD,
            supported=Decimal("0"),
            residual=residual,
            residual_type=ResidualType.INVOICE_BALANCE,
            owner=ExceptionOwner.AR_ANALYST,
            allowed_application_states=[ApplicationStatus.SUPERSEDED],
            allowed_review_decisions=[],
            action=(
                "Do not apply cash while the claimed deduction conflicts with the exact invoice "
                "residual; obtain corrected source evidence."
            ),
            missing=missing,
            conflicting=conflicting,
        )

    reason_allowed = reason is not None and reason in case.policy.allowed_auto_reason_codes
    if reason is not None and not reason_allowed:
        conflicting.append(
            f"Remittance reason {reason} is not allowed by policy "
            f"{case.policy.policy_id} v{case.policy.version}."
        )

    if residual > case.policy.max_auto_shortpay:
        return _exception(
            case,
            code=ExceptionCode.MATERIAL_SHORT_PAY,
            application_status=ApplicationStatus.REVIEW_REQUIRED,
            exception_status=ExceptionStatus.WAITING_REVIEW,
            receipt_allocation_status=ReceiptAllocationStatus.HELD,
            supported=receipt_amount,
            residual=residual,
            residual_type=ResidualType.INVOICE_BALANCE,
            owner=ExceptionOwner.CONTROLLER,
            allowed_application_states=[
                ApplicationStatus.EVIDENCE_REQUIRED,
                ApplicationStatus.READY_TO_POST,
                ApplicationStatus.REJECTED,
            ],
            allowed_review_decisions=[
                ReviewDecision.LEAVE_BALANCE_OPEN,
                ReviewDecision.CREATE_DISPUTE,
                ReviewDecision.REQUEST_EVIDENCE,
                ReviewDecision.REJECT_MATCH,
            ]
            + (
                [ReviewDecision.APPROVE_WRITE_OFF]
                if reason in case.policy.manual_writeoff_reason_codes
                else []
            ),
            recommended_projection=DecisionProjection(
                decision=ReviewDecision.CREATE_DISPUTE,
                cash_applied=receipt_amount,
                authorised_adjustment=Decimal("0.00"),
                invoice_open_after=residual,
                receipt_unapplied_residual=Decimal("0.00"),
                exception_status_after=ExceptionStatus.DISPUTE_OPEN,
            ),
            action=(
                f"Hold the receipt with no ledger mutation, preserve the full "
                f"{invoice_balance} {case.receipt.currency} invoice balance, and recommend "
                f"CREATE_DISPUTE for the evidenced {residual} {case.receipt.currency} claim; "
                "supported cash may post only after a valid decision and fresh controls."
            ),
            missing=missing,
            conflicting=conflicting,
        )

    evidence_complete = (
        case.remittance.intent == RemittanceIntent.DEDUCTION
        and (not case.policy.requires_explicit_remittance_reason or reason is not None)
        and reason_allowed
        and claimed_amount == residual
    )
    if not evidence_complete:
        return _exception(
            case,
            code=ExceptionCode.UNSUPPORTED_DEDUCTION,
            application_status=ApplicationStatus.EVIDENCE_REQUIRED,
            exception_status=ExceptionStatus.WAITING_EVIDENCE,
            receipt_allocation_status=ReceiptAllocationStatus.HELD,
            supported=receipt_amount,
            residual=residual,
            residual_type=ResidualType.INVOICE_BALANCE,
            owner=ExceptionOwner.AR_ANALYST,
            allowed_application_states=[ApplicationStatus.SUPERSEDED],
            allowed_review_decisions=[],
            action=(
                f"Keep the {residual} {case.receipt.currency} balance open and request supported "
                f"deduction evidence; being within the {case.policy.max_auto_shortpay} "
                f"{case.receipt.currency} tolerance is not sufficient."
            ),
            missing=missing,
            conflicting=conflicting,
        )

    return None
