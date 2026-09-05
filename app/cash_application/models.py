"""Immutable records for deterministic AR cash application."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
SIMULATED_ONLY = "SIMULATED_ONLY"


def money(value: Decimal, *, field: str, positive: bool = False) -> Decimal:
    """Validate fixed-point money; binary floats and hidden fractions are forbidden."""

    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field} must be finite")
    normalised = value.quantize(CENT)
    if normalised != value:
        raise ValueError(f"{field} must have no more than two decimal places")
    if positive and normalised <= ZERO:
        raise ValueError(f"{field} must be greater than zero")
    if not positive and normalised < ZERO:
        raise ValueError(f"{field} cannot be negative")
    return normalised


def currency_code(value: str) -> str:
    currency = value.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("currency must be a three-letter code")
    return currency


def required_identifier(value: str, *, field: str) -> str:
    identifier = value.strip()
    if not identifier:
        raise ValueError(f"{field} is required")
    return identifier


class EvidenceSource(StrEnum):
    BANK_FEED = "BANK_FEED"
    REMITTANCE = "REMITTANCE"
    AR_LEDGER = "AR_LEDGER"
    POLICY = "POLICY"


class ReceiptSettlementStatus(StrEnum):
    PENDING = "PENDING"
    BOOKED = "BOOKED"
    REVERSED = "REVERSED"


class ReceiptAllocationStatus(StrEnum):
    UNAPPLIED = "UNAPPLIED"
    HELD = "HELD"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    APPLIED = "APPLIED"


class ReceiptDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class InvoiceStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AllocationKind(StrEnum):
    EXACT = "EXACT"
    PARTIAL = "PARTIAL"
    SHORT_PAY = "SHORT_PAY"


class ApplicationKind(StrEnum):
    EXACT = "EXACT"
    MULTI_INVOICE = "MULTI_INVOICE"
    PARTIAL_PAYMENT = "PARTIAL_PAYMENT"
    SHORT_PAY = "SHORT_PAY"
    OVERPAYMENT = "OVERPAYMENT"


class ResidualKind(StrEnum):
    NONE = "NONE"
    INVOICE_OPEN_PARTIAL = "INVOICE_OPEN_PARTIAL"
    CLAIMED_DEDUCTION = "CLAIMED_DEDUCTION"
    RECEIPT_UNAPPLIED = "RECEIPT_UNAPPLIED"


class PolicyStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class ApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    CONTROL_BLOCKED = "CONTROL_BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    READY_TO_POST = "READY_TO_POST"
    POSTED_SIMULATED = "POSTED_SIMULATED"


class ControlDisposition(StrEnum):
    AUTO_APPLY = "AUTO_APPLY"
    POLICY_RESOLVE = "POLICY_RESOLVE"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCK = "BLOCK"


class ExceptionStatus(StrEnum):
    WAITING_EVIDENCE = "WAITING_EVIDENCE"
    WAITING_REVIEW = "WAITING_REVIEW"
    BLOCKED = "BLOCKED"


class ReviewStatus(StrEnum):
    REQUESTED = "REQUESTED"
    ESCALATED = "ESCALATED"
    DECIDED = "DECIDED"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    evidence_id: str
    source_type: EvidenceSource
    source_system: str
    source_object_id: str
    source_sha256: str
    locator: str
    claim_path: str

    def __post_init__(self) -> None:
        for field in (
            "evidence_id",
            "source_system",
            "source_object_id",
            "locator",
            "claim_path",
        ):
            object.__setattr__(
                self,
                field,
                required_identifier(getattr(self, field), field=field),
            )
        digest = self.source_sha256.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("source_sha256 must be a 64-character hexadecimal digest")
        object.__setattr__(self, "source_sha256", digest)


@dataclass(frozen=True, slots=True)
class ReceiptIdentity:
    source_system: str
    source_transaction_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_system",
            required_identifier(self.source_system, field="source_system"),
        )
        object.__setattr__(
            self,
            "source_transaction_id",
            required_identifier(self.source_transaction_id, field="source_transaction_id"),
        )


@dataclass(frozen=True, slots=True)
class CashReceipt:
    receipt_id: str
    source_system: str
    source_transaction_id: str
    booking_date: date
    amount: Decimal
    currency: str
    settlement_status: ReceiptSettlementStatus
    direction: ReceiptDirection
    evidence_ref: EvidenceRef
    allocation_status: ReceiptAllocationStatus = ReceiptAllocationStatus.UNAPPLIED
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", required_identifier(self.receipt_id, field="receipt_id")
        )
        object.__setattr__(
            self, "source_system", required_identifier(self.source_system, field="source_system")
        )
        object.__setattr__(
            self,
            "source_transaction_id",
            required_identifier(self.source_transaction_id, field="source_transaction_id"),
        )
        object.__setattr__(self, "amount", money(self.amount, field="amount", positive=True))
        object.__setattr__(self, "currency", currency_code(self.currency))
        if self.version < 1:
            raise ValueError("receipt version must be positive")
        if self.evidence_ref.source_type is not EvidenceSource.BANK_FEED:
            raise ValueError("receipt evidence must come from BANK_FEED")
        if self.evidence_ref.source_system != self.source_system:
            raise ValueError("receipt evidence source_system does not match receipt identity")
        if self.evidence_ref.source_object_id != self.source_transaction_id:
            raise ValueError("receipt evidence source object does not match receipt identity")

    @property
    def identity(self) -> ReceiptIdentity:
        return ReceiptIdentity(self.source_system, self.source_transaction_id)


@dataclass(frozen=True, slots=True)
class OpenARItem:
    invoice_id: str
    customer_id: str
    original_amount: Decimal
    open_balance: Decimal
    currency: str
    status: InvoiceStatus
    evidence_ref: EvidenceRef
    ledger_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "invoice_id", required_identifier(self.invoice_id, field="invoice_id")
        )
        object.__setattr__(
            self, "customer_id", required_identifier(self.customer_id, field="customer_id")
        )
        object.__setattr__(
            self,
            "original_amount",
            money(self.original_amount, field="original_amount", positive=True),
        )
        object.__setattr__(self, "open_balance", money(self.open_balance, field="open_balance"))
        object.__setattr__(self, "currency", currency_code(self.currency))
        if self.open_balance > self.original_amount:
            raise ValueError("open_balance cannot exceed original_amount")
        if self.ledger_version < 1:
            raise ValueError("ledger_version must be positive")
        if self.evidence_ref.source_type is not EvidenceSource.AR_LEDGER:
            raise ValueError("invoice evidence must come from AR_LEDGER")
        if self.evidence_ref.source_object_id != self.invoice_id:
            raise ValueError("invoice evidence source object does not match invoice_id")


@dataclass(frozen=True, slots=True)
class RemittanceLine:
    invoice_id: str
    cash_amount: Decimal
    evidence_ref: EvidenceRef
    kind: AllocationKind = AllocationKind.EXACT
    deduction_amount: Decimal = ZERO
    reason_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "invoice_id", required_identifier(self.invoice_id, field="invoice_id")
        )
        object.__setattr__(
            self, "cash_amount", money(self.cash_amount, field="cash_amount", positive=True)
        )
        object.__setattr__(
            self,
            "deduction_amount",
            money(self.deduction_amount, field="deduction_amount"),
        )
        if self.reason_code is not None:
            reason = self.reason_code.strip().upper()
            object.__setattr__(self, "reason_code", reason or None)
        if self.kind is not AllocationKind.SHORT_PAY and self.deduction_amount != ZERO:
            raise ValueError("only SHORT_PAY lines may contain a deduction_amount")
        if self.evidence_ref.source_type is not EvidenceSource.REMITTANCE:
            raise ValueError("remittance line evidence must come from REMITTANCE")


@dataclass(frozen=True, slots=True)
class RemittanceEvidence:
    remittance_id: str
    receipt_id: str
    customer_id: str
    evidence_ref: EvidenceRef
    lines: tuple[RemittanceLine, ...]
    version: int = 1

    def __init__(
        self,
        *,
        remittance_id: str,
        receipt_id: str,
        customer_id: str,
        evidence_ref: EvidenceRef,
        lines: Iterable[RemittanceLine],
        version: int = 1,
    ) -> None:
        object.__setattr__(
            self,
            "remittance_id",
            required_identifier(remittance_id, field="remittance_id"),
        )
        object.__setattr__(self, "receipt_id", required_identifier(receipt_id, field="receipt_id"))
        object.__setattr__(
            self, "customer_id", required_identifier(customer_id, field="customer_id")
        )
        if evidence_ref.source_type is not EvidenceSource.REMITTANCE:
            raise ValueError("remittance evidence must come from REMITTANCE")
        object.__setattr__(self, "evidence_ref", evidence_ref)
        frozen_lines = tuple(lines)
        if not frozen_lines:
            raise ValueError("remittance must contain at least one supported allocation line")
        object.__setattr__(self, "lines", frozen_lines)
        if version < 1:
            raise ValueError("remittance version must be positive")
        object.__setattr__(self, "version", version)


@dataclass(frozen=True, slots=True)
class ShortPayPolicy:
    policy_id: str
    version: int
    effective_from: date
    effective_to: date | None
    currency: str
    max_auto_writeoff: Decimal
    allowed_reason_codes: frozenset[str]
    requires_explicit_reason: bool
    status: PolicyStatus
    evidence_ref: EvidenceRef
    customer_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_id", required_identifier(self.policy_id, field="policy_id")
        )
        if self.version < 1:
            raise ValueError("policy version must be positive")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot precede effective_from")
        object.__setattr__(self, "currency", currency_code(self.currency))
        object.__setattr__(
            self,
            "max_auto_writeoff",
            money(self.max_auto_writeoff, field="max_auto_writeoff"),
        )
        reasons = frozenset(reason.strip().upper() for reason in self.allowed_reason_codes)
        if "" in reasons:
            raise ValueError("allowed_reason_codes cannot contain a blank reason")
        object.__setattr__(self, "allowed_reason_codes", reasons)
        if self.customer_id is not None:
            object.__setattr__(
                self,
                "customer_id",
                required_identifier(self.customer_id, field="customer_id"),
            )
        if self.evidence_ref.source_type is not EvidenceSource.POLICY:
            raise ValueError("policy evidence must come from POLICY")
        expected_object_id = f"{self.policy_id}:v{self.version}"
        if self.evidence_ref.source_object_id != expected_object_id:
            raise ValueError("policy evidence source object does not match policy version")

    def is_effective(self, on_date: date) -> bool:
        return self.effective_from <= on_date and (
            self.effective_to is None or on_date <= self.effective_to
        )


@dataclass(frozen=True, slots=True)
class PolicyReference:
    policy_id: str
    version: int
    effective_from: date
    source_sha256: str


@dataclass(frozen=True, slots=True)
class InvoiceApplicationResult:
    invoice_id: str
    ledger_version_before: int
    balance_before: Decimal
    cash_applied: Decimal
    policy_adjustment: Decimal
    balance_after: Decimal
    status_after: InvoiceStatus
    remittance_evidence: EvidenceRef
    ar_evidence: EvidenceRef
    policy_reference: PolicyReference | None = None


@dataclass(frozen=True, slots=True)
class ApplicationDecision:
    receipt: CashReceipt
    remittance_id: str
    remittance_version: int
    application_status: ApplicationStatus
    disposition: ControlDisposition
    application_kind: ApplicationKind
    residual_kind: ResidualKind
    receipt_allocation_status: ReceiptAllocationStatus
    invoice_results: tuple[InvoiceApplicationResult, ...]
    cash_allocated: Decimal
    receipt_residual: Decimal
    policy_adjustment_total: Decimal
    control_codes: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    policy_references: tuple[PolicyReference, ...]
    exception_status: ExceptionStatus | None = None
    review_status: ReviewStatus | None = None
    posting_mode: str = SIMULATED_ONLY

    def invoice_result(self, invoice_id: str) -> InvoiceApplicationResult:
        for result in self.invoice_results:
            if result.invoice_id == invoice_id:
                return result
        raise KeyError(invoice_id)

    @property
    def is_postable(self) -> bool:
        return self.application_status is ApplicationStatus.READY_TO_POST


@dataclass(frozen=True, slots=True)
class SimulatedPostingResult:
    receipt_id: str
    receipt_identity: ReceiptIdentity
    remittance_id: str
    idempotency_key: str
    application_status: ApplicationStatus
    receipt_allocation_status: ReceiptAllocationStatus
    invoice_balances: tuple[tuple[str, Decimal], ...]
    cash_allocated: Decimal
    receipt_residual: Decimal
    policy_adjustment_total: Decimal
    evidence_refs: tuple[EvidenceRef, ...]
    policy_references: tuple[PolicyReference, ...]
    approved_by: str | None
    posting_mode: str = SIMULATED_ONLY

    def balance_for(self, invoice_id: str) -> Decimal:
        for recorded_id, balance in self.invoice_balances:
            if recorded_id == invoice_id:
                return balance
        raise KeyError(invoice_id)
