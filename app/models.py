from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.private_markets import TWOPLACES, money


def utc_now() -> datetime:
    return datetime.now(UTC)


class WorkflowStatus(StrEnum):
    RECEIVED = "received"
    EXTRACTED = "extracted"
    MATCHING = "matching"
    AWAITING_APPROVAL = "awaiting_approval"
    RECONCILED = "reconciled"
    EVIDENCE_REQUIRED = "evidence_required"
    REJECTED = "rejected"


class RiskAction(StrEnum):
    AUTO_RECONCILE = "auto_reconcile"
    REQUIRE_APPROVAL = "require_approval"
    REQUEST_EVIDENCE = "request_evidence"


class InvoiceLine(BaseModel):
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    net_amount: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")

    @field_validator("quantity", "unit_price", "net_amount", "tax_amount", mode="before")
    @classmethod
    def decimalise(cls, value: Any) -> Decimal:
        return Decimal(str(value or 0))


class DocumentExtraction(BaseModel):
    document_type: Literal["invoice", "receipt", "credit_note", "unknown"] = "invoice"
    supplier_name: str
    supplier_registration: str | None = None
    invoice_number: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    currency: str = "GBP"
    subtotal: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total: Decimal
    payment_reference: str | None = None
    suggested_category: str = "General business expense"
    vat_treatment: str = "Standard-rated purchase"
    lines: list[InvoiceLine] = Field(default_factory=list)
    confidence: int = Field(default=0, ge=0, le=100)
    source: Literal["gemini", "demo", "manual"] = "gemini"
    warnings: list[str] = Field(default_factory=list)

    @field_validator("subtotal", "tax", "total", mode="before")
    @classmethod
    def normalise_money(cls, value: Any) -> Decimal:
        return money(value or 0)

    @field_validator("currency")
    @classmethod
    def normalise_currency(cls, value: str) -> str:
        return value.upper().strip() or "GBP"

    @model_validator(mode="after")
    def validate_financial_totals(self) -> DocumentExtraction:
        if self.total <= 0:
            raise ValueError("Document total must be greater than zero.")
        arithmetic_difference = abs((self.subtotal + self.tax) - self.total)
        if arithmetic_difference > Decimal("0.02"):
            warning = (
                "Subtotal plus tax differs from total by "
                f"{arithmetic_difference.quantize(TWOPLACES)} {self.currency}."
            )
            if warning not in self.warnings:
                self.warnings.append(warning)
            self.confidence = min(self.confidence, 75)
        if self.issue_date and self.due_date and self.due_date < self.issue_date:
            warning = "Due date precedes the issue date."
            if warning not in self.warnings:
                self.warnings.append(warning)
            self.confidence = min(self.confidence, 70)
        return self


class BankTransaction(BaseModel):
    transaction_id: str
    booking_date: date
    amount: Decimal
    currency: str = "GBP"
    direction: Literal["debit", "credit"] = "debit"
    description: str
    merchant_name: str | None = None
    reference: str | None = None
    category: str | None = None
    already_reconciled: bool = False

    @field_validator("amount", mode="before")
    @classmethod
    def positive_money(cls, value: Any) -> Decimal:
        return abs(money(value or 0))

    @field_validator("currency")
    @classmethod
    def normalise_currency(cls, value: str) -> str:
        return value.upper().strip() or "GBP"


class MatchFactor(BaseModel):
    name: str
    score: int
    maximum: int
    explanation: str


class MatchCandidate(BaseModel):
    transaction: BankTransaction
    score: int = Field(ge=0, le=100)
    amount_variance_percent: Decimal
    date_distance_days: int | None = None
    factors: list[MatchFactor] = Field(default_factory=list)

    @field_validator("amount_variance_percent", mode="before")
    @classmethod
    def decimalise_variance(cls, value: Any) -> Decimal:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class RiskDecision(BaseModel):
    action: RiskAction
    risk_score: int = Field(ge=0, le=100)
    control: str
    reasons: list[str]
    selected_transaction_id: str | None = None


class AuditEvent(BaseModel):
    sequence: int
    occurred_at: datetime = Field(default_factory=utc_now)
    actor: str
    action: str
    details: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str
    event_hash: str


class WorkflowRecord(BaseModel):
    workflow_id: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    status: WorkflowStatus = WorkflowStatus.RECEIVED
    source_name: str
    scenario: str | None = None
    extraction: DocumentExtraction
    transactions: list[BankTransaction]
    candidates: list[MatchCandidate] = Field(default_factory=list)
    decision: RiskDecision | None = None
    matched_transaction_id: str | None = None
    approved_by: str | None = None
    approval_note: str | None = None
    audit_events: list[AuditEvent] = Field(default_factory=list)
    audit_chain_valid: bool = True


class ApprovalRequest(BaseModel):
    actor: str = Field(min_length=2, max_length=120)
    note: str = Field(default="Approved after reviewing the supporting evidence.", max_length=500)


class RejectionRequest(BaseModel):
    actor: str = Field(min_length=2, max_length=120)
    note: str = Field(min_length=3, max_length=500)


class MonthEndSummary(BaseModel):
    generated_at: datetime = Field(default_factory=utc_now)
    total_workflows: int
    reconciled: int
    awaiting_approval: int
    evidence_required: int
    rejected: int
    estimated_minutes_saved: int
