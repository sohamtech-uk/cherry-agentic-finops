"""Deterministic adapter from exception investigation to canonical eval outcome fields."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.cash_application.exceptions import (
    ApplicationStatus,
    CashApplicationCase,
    CashApplicationException,
    EvidenceLocator,
    EvidenceType,
    ExceptionCode,
    ExceptionOwner,
    ExceptionStatus,
    ReceiptAllocationStatus,
    ReceiptSettlementStatus,
    ResidualType,
    ReviewDecision,
    investigate_cash_exception,
)


class CanonicalReviewStatus(StrEnum):
    NOT_CREATED = "NOT_CREATED"
    REQUESTED = "REQUESTED"


class CanonicalReceiptOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: str
    settlement_status: ReceiptSettlementStatus
    allocation_status: ReceiptAllocationStatus
    version: int
    cash_applied_amount: Decimal
    unapplied_cash_amount: Decimal


class CanonicalApplicationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ApplicationStatus
    proposed_cash_application_amount: Decimal
    cash_applied_amount: Decimal
    allowed_next_states: list[ApplicationStatus]
    ledger_mutation_occurred: Literal[False] = False


class CanonicalInvoiceOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    invoice_id: str | None
    ledger_version: int | None
    currency: str | None
    open_before: Decimal | None
    open_current: Decimal | None


class CanonicalExceptionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: ExceptionCode
    status: ExceptionStatus
    residual_type: ResidualType
    residual_amount: Decimal
    amount_at_risk: Decimal
    missing_evidence: list[str]
    conflicting_evidence: list[str]
    owner: ExceptionOwner


class CanonicalReviewOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: CanonicalReviewStatus
    allowed_decisions: list[ReviewDecision]
    recommended_decision: ReviewDecision | None


class CanonicalPolicyOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str
    version: int
    evidence: list[EvidenceLocator]


class CanonicalAuditOutcome(BaseModel):
    """Eval trace identity, not a persisted ledger audit event."""

    model_config = ConfigDict(frozen=True)

    action: Literal["cash_exception_evaluated"] = "cash_exception_evaluated"
    control_result_id: str
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_ids: list[str]
    ledger_state_delta: dict[str, object] = Field(default_factory=dict)
    deterministic: Literal[True] = True


class CanonicalExceptionTrialOutcome(BaseModel):
    """Stable exception result shape consumed by the cross-scenario eval runner."""

    model_config = ConfigDict(frozen=True)

    trial_id: str = Field(min_length=1)
    receipt: CanonicalReceiptOutcome
    application: CanonicalApplicationOutcome
    invoice: CanonicalInvoiceOutcome
    exception: CanonicalExceptionOutcome
    review: CanonicalReviewOutcome
    policy: CanonicalPolicyOutcome
    audit: CanonicalAuditOutcome
    advisory_recommended_action: str
    narrative_is_authoritative: Literal[False] = False


def _canonical_hash(value: BaseModel | Mapping[str, object]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def exception_to_canonical_outcome(
    case: CashApplicationCase,
    exception: CashApplicationException,
    trial_id: str,
) -> CanonicalExceptionTrialOutcome:
    """Map a validated exception without reading or interpreting narrative text.

    The caller must pass the same case used by ``investigate_cash_exception``.  Identity checks
    fail closed so a packet cannot be combined with a different receipt or invoice.  All canonical
    statuses and amounts come from typed fields; ``recommended_action`` is copied only into the
    explicitly advisory field.
    """

    if not trial_id.strip():
        raise ValueError("trial_id must not be blank.")
    if case.receipt.receipt_id != exception.receipt_id:
        raise ValueError("Exception receipt does not match the evaluated case.")
    case_invoice_id = case.invoice.invoice_id if case.invoice else None
    if case_invoice_id != exception.invoice_id:
        raise ValueError("Exception invoice does not match the evaluated case.")

    advisory_recommended_action = exception.recommended_action
    expected_exception = investigate_cash_exception(case)
    if expected_exception is None:
        raise ValueError("The evaluated case does not produce a scoped exception.")
    authoritative_fields = exception.model_dump(exclude={"recommended_action"})
    expected_fields = expected_exception.model_dump(exclude={"recommended_action"})
    if authoritative_fields != expected_fields:
        raise ValueError("Exception fields do not match deterministic evaluation.")
    exception = expected_exception

    policy_evidence = sorted(
        (item for item in exception.evidence if item.source_type == EvidenceType.POLICY),
        key=lambda item: (item.evidence_id, item.locator, item.source_sha256),
    )
    if not policy_evidence:
        raise ValueError("Canonical outcome requires policy evidence.")

    recommended_projection = exception.recommended_decision_projection
    review_requested = exception.exception_status == ExceptionStatus.WAITING_REVIEW
    review = CanonicalReviewOutcome(
        status=(
            CanonicalReviewStatus.REQUESTED
            if review_requested
            else CanonicalReviewStatus.NOT_CREATED
        ),
        allowed_decisions=exception.allowed_review_decisions,
        recommended_decision=(
            recommended_projection.decision if recommended_projection is not None else None
        ),
    )
    receipt = CanonicalReceiptOutcome(
        receipt_id=case.receipt.receipt_id,
        settlement_status=case.receipt.settlement_status,
        allocation_status=exception.receipt_allocation_status,
        version=case.receipt.version,
        cash_applied_amount=exception.cash_applied_amount,
        unapplied_cash_amount=case.receipt.amount - exception.cash_applied_amount,
    )
    application = CanonicalApplicationOutcome(
        status=exception.application_status,
        proposed_cash_application_amount=exception.proposed_cash_application_amount,
        cash_applied_amount=exception.cash_applied_amount,
        allowed_next_states=exception.allowed_next_application_states,
    )
    invoice = CanonicalInvoiceOutcome(
        invoice_id=case_invoice_id,
        ledger_version=case.invoice.ledger_version if case.invoice else None,
        currency=case.invoice.currency if case.invoice else None,
        open_before=exception.invoice_open_before,
        open_current=exception.invoice_open_current,
    )
    exception_fields = CanonicalExceptionOutcome(
        code=exception.exception_code,
        status=exception.exception_status,
        residual_type=exception.residual_type,
        residual_amount=exception.residual_amount,
        amount_at_risk=exception.amount_at_risk,
        missing_evidence=exception.missing_evidence,
        conflicting_evidence=exception.conflicting_evidence,
        owner=exception.owner,
    )
    policy = CanonicalPolicyOutcome(
        policy_id=exception.policy_id,
        version=exception.policy_version,
        evidence=policy_evidence,
    )

    input_hash = _canonical_hash(case)
    control_result_id = hashlib.sha256(
        f"cash-exception-control:{trial_id}:{input_hash}".encode()
    ).hexdigest()
    authoritative_output = {
        "receipt": receipt.model_dump(mode="json"),
        "application": application.model_dump(mode="json"),
        "invoice": invoice.model_dump(mode="json"),
        "exception": exception_fields.model_dump(mode="json"),
        "review": review.model_dump(mode="json"),
        "policy": policy.model_dump(mode="json"),
    }
    audit = CanonicalAuditOutcome(
        control_result_id=control_result_id,
        input_hash=input_hash,
        output_hash=_canonical_hash(authoritative_output),
        evidence_ids=sorted({item.evidence_id for item in exception.evidence}),
    )
    return CanonicalExceptionTrialOutcome(
        trial_id=trial_id,
        receipt=receipt,
        application=application,
        invoice=invoice,
        exception=exception_fields,
        review=review,
        policy=policy,
        audit=audit,
        advisory_recommended_action=advisory_recommended_action,
    )
