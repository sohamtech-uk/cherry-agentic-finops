from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import utc_now
from app.private_markets import money


class ReviewAction(StrEnum):
    APPROVE_WRITE_OFF = "approve_write_off"
    LEAVE_BALANCE_OPEN = "leave_balance_open"
    CREATE_DISPUTE = "create_dispute"
    REQUEST_EVIDENCE = "request_evidence"
    REJECT_MATCH = "reject_match"


class ReviewStatus(StrEnum):
    AWAITING_CONTROLLER = "awaiting_controller"
    ESCALATED = "escalated"
    WRITE_OFF_APPROVED = "write_off_approved"
    BALANCE_LEFT_OPEN = "balance_left_open"
    DISPUTE_CREATED = "dispute_created"
    EVIDENCE_REQUESTED = "evidence_requested"
    MATCH_REJECTED = "match_rejected"


class ApplicationStatus(StrEnum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    CONTROL_BLOCKED = "CONTROL_BLOCKED"
    POSTED_SIMULATED = "POSTED_SIMULATED"
    REJECTED = "REJECTED"


class ExceptionStatus(StrEnum):
    WAITING_REVIEW = "WAITING_REVIEW"
    ESCALATED_AUTHORITY = "ESCALATED_AUTHORITY"
    COLLECTIONS_OPEN = "COLLECTIONS_OPEN"
    DISPUTE_OPEN = "DISPUTE_OPEN"
    WAITING_EVIDENCE = "WAITING_EVIDENCE"
    RESOLVED = "RESOLVED"
    BLOCKED = "BLOCKED"


class ReceiptEvidence(BaseModel):
    receipt_id: str
    source_system: str
    source_transaction_id: str
    booking_date: date
    payer_name: str
    amount: Decimal
    available_amount: Decimal
    currency: str
    settlement_status: Literal["BOOKED", "PENDING", "REVERSED"]
    allocation_status: Literal["UNAPPLIED", "HELD", "PARTIALLY_APPLIED", "APPLIED"]
    version: int = Field(gt=0)
    duplicate_detected: bool = False

    @field_validator("amount", "available_amount", mode="before")
    @classmethod
    def normalise_money(cls, value: Any) -> Decimal:
        return money(value)

    @field_validator("currency")
    @classmethod
    def normalise_currency(cls, value: str) -> str:
        return value.upper().strip()


class CustomerInvoiceMatch(BaseModel):
    customer_id: str
    customer_name: str
    invoice_id: str
    invoice_currency: str
    invoice_open_balance_before: Decimal
    invoice_status_at_snapshot: Literal["OPEN", "CLOSED"]
    invoice_ledger_version: int = Field(gt=0)
    proposed_cash_application: Decimal
    receipt_unapplied_amount_after_post: Decimal
    remittance_raw_reason: str | None
    remittance_canonical_reason_code: str | None
    match_basis: list[str] = Field(min_length=1)

    @field_validator(
        "invoice_open_balance_before",
        "proposed_cash_application",
        "receipt_unapplied_amount_after_post",
        mode="before",
    )
    @classmethod
    def normalise_money(cls, value: Any) -> Decimal:
        return money(value)

    @field_validator("invoice_currency")
    @classmethod
    def normalise_currency(cls, value: str) -> str:
        return value.upper().strip()


class EvidenceReference(BaseModel):
    evidence_id: str
    source_type: Literal["BANK_FEED", "REMITTANCE_PDF", "AR_LEDGER", "POLICY"]
    source_system: str
    source_object_id: str
    locator: str
    claim_path: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    supports: str


class PolicyClause(BaseModel):
    clause: str
    requirement: str


class PolicyReference(BaseModel):
    policy_id: str
    version: int = Field(gt=0)
    status: Literal["APPROVED"] = "APPROVED"
    effective_from: date
    clauses: list[PolicyClause] = Field(min_length=1)
    max_auto_writeoff_gbp: Decimal
    allowed_auto_reason_codes: list[str]
    manual_writeoff_reason_codes: list[str]
    requires_explicit_remittance_reason: bool

    @field_validator("max_auto_writeoff_gbp", mode="before")
    @classmethod
    def normalise_money(cls, value: Any) -> Decimal:
        return money(value)


class AutomationStop(BaseModel):
    code: str
    explanation: str
    excess_over_auto_limit: Decimal

    @field_validator("excess_over_auto_limit", mode="before")
    @classmethod
    def normalise_money(cls, value: Any) -> Decimal:
        return money(value)


class ARState(BaseModel):
    invoice_id: str
    ledger_version: int = Field(gt=0)
    invoice_balance_before: Decimal
    cash_applied: Decimal
    authorised_adjustment: Decimal
    open_balance: Decimal
    invoice_state: Literal["OPEN", "CLOSED", "DISPUTED"]
    receipt_allocation_status: Literal["UNAPPLIED", "HELD", "PARTIALLY_APPLIED", "APPLIED"]
    receipt_unapplied_amount: Decimal

    @field_validator(
        "invoice_balance_before",
        "cash_applied",
        "authorised_adjustment",
        "open_balance",
        "receipt_unapplied_amount",
        mode="before",
    )
    @classmethod
    def normalise_money(cls, value: Any) -> Decimal:
        return money(value)


class InputVersions(BaseModel):
    expected_receipt_version: int = Field(gt=0)
    expected_invoice_ledger_version: int = Field(gt=0)
    expected_policy_version: int = Field(gt=0)


class ControlCheck(BaseModel):
    code: str
    outcome: Literal["PASS", "BLOCK"]
    explanation: str

    @property
    def passed(self) -> bool:
        return self.outcome == "PASS"


class AllowedAction(BaseModel):
    action: ReviewAction
    label: str
    accounting_effect: str
    authority_required: bool


class ReviewerAuthority(BaseModel):
    reviewer_id: str
    reviewer_name: str
    role: str
    authority_id: str
    authority_version: int = Field(gt=0)
    effective_from: date
    legal_entity_id: str
    currency: str
    approval_limit_gbp: Decimal
    permitted_actions: list[ReviewAction]

    @field_validator("approval_limit_gbp", mode="before")
    @classmethod
    def normalise_money(cls, value: Any) -> Decimal:
        return money(value)


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=6, max_length=80)
    expected_review_version: int = Field(gt=0)
    reviewer_id: str = Field(min_length=2, max_length=80)
    action: ReviewAction
    rationale: str = Field(min_length=3, max_length=500)
    reason_code: str | None = Field(default=None, max_length=80)
    dispute_owner: str | None = Field(default=None, max_length=120)
    requested_evidence: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def require_action_details(self) -> ReviewDecisionRequest:
        if self.action in {
            ReviewAction.APPROVE_WRITE_OFF,
            ReviewAction.CREATE_DISPUTE,
        } and not (self.reason_code or "").strip():
            raise ValueError(f"reason_code is required for {self.action}.")
        if self.action == ReviewAction.CREATE_DISPUTE and not (self.dispute_owner or "").strip():
            raise ValueError("dispute_owner is required for create_dispute.")
        if self.action == ReviewAction.REQUEST_EVIDENCE and not (
            self.requested_evidence or ""
        ).strip():
            raise ValueError("requested_evidence is required for request_evidence.")
        return self


class ReviewDecision(BaseModel):
    decision_id: str
    review_version: int
    reviewer_id: str
    reviewer_name: str
    authority_id: str
    authority_version: int
    action: ReviewAction
    rationale: str
    reason_code: str | None
    dispute_owner: str | None
    requested_evidence: str | None
    decided_at: datetime = Field(default_factory=utc_now)
    authorised_amount_gbp: Decimal
    resulting_ar_state: ARState
    idempotent_replay: bool = False
    simulated_only: Literal[True] = True

    @field_validator("authorised_amount_gbp", mode="before")
    @classmethod
    def normalise_money(cls, value: Any) -> Decimal:
        return money(value)


class ReviewAttempt(BaseModel):
    occurred_at: datetime = Field(default_factory=utc_now)
    decision_id: str
    reviewer_id: str
    action: ReviewAction
    outcome: Literal["DENIED"] = "DENIED"
    code: str
    explanation: str


class ReviewAuditEvent(BaseModel):
    sequence: int = Field(gt=0)
    actor: str
    action: str
    details: dict[str, Any]
    previous_hash: str
    event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ControllerReviewPacket(BaseModel):
    case_id: str
    legal_entity_id: str
    review_version: int = Field(gt=0)
    review_status: ReviewStatus
    application_status: ApplicationStatus
    exception_status: ExceptionStatus
    control_disposition: Literal["REVIEW_REQUIRED", "BLOCK"]
    receipt: ReceiptEvidence
    customer_invoice_match: CustomerInvoiceMatch
    evidence: list[EvidenceReference] = Field(min_length=4)
    amount_at_risk: Decimal
    policy: PolicyReference
    automation_stopped: list[AutomationStop] = Field(min_length=1)
    remaining_ar_state: ARState
    proposed_after_valid_decision: ARState
    input_versions: InputVersions
    control_checks: list[ControlCheck]
    allowed_actions: list[AllowedAction]
    review_attempts: list[ReviewAttempt] = Field(default_factory=list)
    audit_events: list[ReviewAuditEvent] = Field(default_factory=list)
    recorded_decision: ReviewDecision | None = None
    simulation_only: Literal[True] = True
    production_write_performed: Literal[False] = False
    control_boundary: str

    @field_validator("amount_at_risk", mode="before")
    @classmethod
    def normalise_money(cls, value: Any) -> Decimal:
        return money(value)


class ControllerReviewError(ValueError):
    def __init__(self, code: str, message: str, **context: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.context}


_REVIEWERS = {
    "ar_analyst_01": ReviewerAuthority(
        reviewer_id="ar_analyst_01",
        reviewer_name="Jamie Patel",
        role="AR_ANALYST",
        authority_id="AUTH-AR-UK",
        authority_version=2,
        effective_from="2026-09-01",
        legal_entity_id="CHERRY-UK-LTD",
        currency="GBP",
        approval_limit_gbp="0",
        permitted_actions=[
            ReviewAction.LEAVE_BALANCE_OPEN,
            ReviewAction.CREATE_DISPUTE,
            ReviewAction.REQUEST_EVIDENCE,
            ReviewAction.REJECT_MATCH,
        ],
    ),
    "controller_uk_01": ReviewerAuthority(
        reviewer_id="controller_uk_01",
        reviewer_name="Alex Morgan",
        role="CONTROLLER",
        authority_id="AUTH-CONTROLLER-UK",
        authority_version=4,
        effective_from="2026-09-01",
        legal_entity_id="CHERRY-UK-LTD",
        currency="GBP",
        approval_limit_gbp="1000",
        permitted_actions=list(ReviewAction),
    ),
    "finance_director_01": ReviewerAuthority(
        reviewer_id="finance_director_01",
        reviewer_name="Robin Shaw",
        role="FINANCE_DIRECTOR",
        authority_id="AUTH-FD-UK",
        authority_version=1,
        effective_from="2026-09-01",
        legal_entity_id="CHERRY-UK-LTD",
        currency="GBP",
        approval_limit_gbp="10000",
        permitted_actions=list(ReviewAction),
    ),
}


def _evidence_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _audit_hash(
    sequence: int,
    actor: str,
    action: str,
    details: dict[str, Any],
    previous_hash: str,
) -> str:
    canonical_details = json.dumps(details, sort_keys=True, separators=(",", ":"))
    payload = f"{sequence}|{actor}|{action}|{canonical_details}|{previous_hash}"
    return _evidence_hash(payload)


def append_review_audit(
    packet: ControllerReviewPacket,
    *,
    actor: str,
    action: str,
    details: dict[str, Any],
) -> None:
    sequence = len(packet.audit_events) + 1
    previous_hash = packet.audit_events[-1].event_hash if packet.audit_events else "GENESIS"
    packet.audit_events.append(
        ReviewAuditEvent(
            sequence=sequence,
            actor=actor,
            action=action,
            details=details,
            previous_hash=previous_hash,
            event_hash=_audit_hash(sequence, actor, action, details, previous_hash),
        )
    )


def verify_review_audit(events: list[ReviewAuditEvent]) -> bool:
    previous_hash = "GENESIS"
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence or event.previous_hash != previous_hash:
            return False
        expected_hash = _audit_hash(
            event.sequence,
            event.actor,
            event.action,
            event.details,
            event.previous_hash,
        )
        if event.event_hash != expected_hash:
            return False
        previous_hash = event.event_hash
    return True


def _action_contract() -> list[AllowedAction]:
    return [
        AllowedAction(
            action=ReviewAction.APPROVE_WRITE_OFF,
            label="Approve write-off / deduction",
            accounting_effect=(
                "Post the held cash and close the residual with an authorised simulated adjustment."
            ),
            authority_required=True,
        ),
        AllowedAction(
            action=ReviewAction.LEAVE_BALANCE_OPEN,
            label="Leave balance open",
            accounting_effect="Post the held cash and preserve £500 open for collections.",
            authority_required=False,
        ),
        AllowedAction(
            action=ReviewAction.CREATE_DISPUTE,
            label="Create dispute",
            accounting_effect="Post held cash; preserve £500 and create a simulated dispute.",
            authority_required=False,
        ),
        AllowedAction(
            action=ReviewAction.REQUEST_EVIDENCE,
            label="Request evidence",
            accounting_effect="Keep cash HELD and the £10,000 invoice unchanged pending evidence.",
            authority_required=False,
        ),
        AllowedAction(
            action=ReviewAction.REJECT_MATCH,
            label="Reject match",
            accounting_effect="Release HELD cash to UNAPPLIED; leave the invoice unchanged.",
            authority_required=False,
        ),
    ]


def _ar_state(
    *,
    cash: Decimal | str,
    adjustment: Decimal | str,
    open_balance: Decimal | str,
    invoice_state: Literal["OPEN", "CLOSED", "DISPUTED"],
    receipt_status: Literal["UNAPPLIED", "HELD", "PARTIALLY_APPLIED", "APPLIED"],
    receipt_unapplied: Decimal | str,
) -> ARState:
    return ARState(
        invoice_id="INV-2208",
        ledger_version=7,
        invoice_balance_before="10000",
        cash_applied=cash,
        authorised_adjustment=adjustment,
        open_balance=open_balance,
        invoice_state=invoice_state,
        receipt_allocation_status=receipt_status,
        receipt_unapplied_amount=receipt_unapplied,
    )


def build_short_pay_packet(short_pay_gbp: Decimal | str = "500") -> ControllerReviewPacket:
    short_pay = money(short_pay_gbp)
    invoice_balance = money("10000")
    receipt_amount = money(invoice_balance - short_pay)
    case_id = f"CA-05-RCPT-1042-{int(short_pay)}"
    source_payloads = {
        "bank": (
            f"SYNTHETIC_BANK|TX-1042|2026-09-05|Northstar Retail Ltd|"
            f"{receipt_amount}|GBP|BOOKED|v2"
        ),
        "remittance": (
            f"Northstar Retail Ltd|CUST-0042|INV-2208|{receipt_amount}|"
            f"DAMAGED_GOODS|{short_pay}|GBP"
        ),
        "ledger": "CUST-0042|Northstar Retail Ltd|INV-2208|10000.00|GBP|OPEN|v7",
        "policy": (
            "SHORTPAY-01|v3|APPROVED|2026-09-01|4.2|max_auto=50.00|"
            "FREIGHT_DAMAGE,ROUNDING|7.1|manual=DAMAGED_GOODS|authority_required"
        ),
    }
    packet = ControllerReviewPacket(
        case_id=case_id,
        legal_entity_id="CHERRY-UK-LTD",
        review_version=1,
        review_status=ReviewStatus.AWAITING_CONTROLLER,
        application_status=ApplicationStatus.REVIEW_REQUIRED,
        exception_status=ExceptionStatus.WAITING_REVIEW,
        control_disposition="REVIEW_REQUIRED",
        receipt=ReceiptEvidence(
            receipt_id="RCPT-1042",
            source_system="SYNTHETIC_BANK",
            source_transaction_id="TX-1042",
            booking_date="2026-09-05",
            payer_name="Northstar Retail Ltd",
            amount=receipt_amount,
            available_amount=receipt_amount,
            currency="GBP",
            settlement_status="BOOKED",
            allocation_status="HELD",
            version=2,
        ),
        customer_invoice_match=CustomerInvoiceMatch(
            customer_id="CUST-0042",
            customer_name="Northstar Retail Ltd",
            invoice_id="INV-2208",
            invoice_currency="GBP",
            invoice_open_balance_before=invoice_balance,
            invoice_status_at_snapshot="OPEN",
            invoice_ledger_version=7,
            proposed_cash_application=receipt_amount,
            receipt_unapplied_amount_after_post="0",
            remittance_raw_reason="DAMAGED_GOODS",
            remittance_canonical_reason_code="DAMAGED_GOODS",
            match_basis=[
                "Remittance locates customer CUST-0042 and invoice INV-2208.",
                "Bank payer and remittance customer both identify Northstar Retail Ltd.",
                f"Receipt equals the evidenced cash allocation of £{receipt_amount:,.2f}.",
            ],
        ),
        evidence=[
            EvidenceReference(
                evidence_id="EV-BANK-1042",
                source_type="BANK_FEED",
                source_system="SYNTHETIC_BANK",
                source_object_id="TX-1042",
                locator="record TX-1042",
                claim_path="receipt",
                source_sha256=_evidence_hash(source_payloads["bank"]),
                supports="Booked GBP receipt, payer, date and exact bank-source identity.",
            ),
            EvidenceReference(
                evidence_id="EV-REMIT-1042",
                source_type="REMITTANCE_PDF",
                source_system="SYNTHETIC_REMITTANCE",
                source_object_id="REMIT-RCPT-1042",
                locator="page 1, lines 8-12",
                claim_path="remittance.lines[0]",
                source_sha256=_evidence_hash(source_payloads["remittance"]),
                supports=(
                    f"Customer, invoice, £{receipt_amount:,.2f} allocation and claimed "
                    f"£{short_pay:,.2f} DAMAGED_GOODS deduction."
                ),
            ),
            EvidenceReference(
                evidence_id="EV-AR-2208",
                source_type="AR_LEDGER",
                source_system="SYNTHETIC_AR",
                source_object_id="INV-2208-v7",
                locator="customer CUST-0042 / invoice INV-2208 / version 7",
                claim_path="open_ar[INV-2208]",
                source_sha256=_evidence_hash(source_payloads["ledger"]),
                supports="GBP invoice, OPEN status and £10,000 balance before application.",
            ),
            EvidenceReference(
                evidence_id="EV-POLICY-SP01-V3",
                source_type="POLICY",
                source_system="SYNTHETIC_POLICY_STORE",
                source_object_id="SHORTPAY-01-v3",
                locator="SHORTPAY-01 version 3, clauses 4.2 and 7.1",
                claim_path="policies[SHORTPAY-01].versions[3]",
                source_sha256=_evidence_hash(source_payloads["policy"]),
                supports="Approved effective auto rule, manual reason and authority requirement.",
            ),
        ],
        amount_at_risk=short_pay,
        policy=PolicyReference(
            policy_id="SHORTPAY-01",
            version=3,
            effective_from="2026-09-01",
            clauses=[
                PolicyClause(
                    clause="4.2",
                    requirement=(
                        "Automatic write-off requires an evidenced allowed reason and an amount "
                        "not exceeding £50."
                    ),
                ),
                PolicyClause(
                    clause="7.1",
                    requirement=(
                        "DAMAGED_GOODS may be manually written off only by a reviewer with current "
                        "delegated authority; fundamental controls remain mandatory."
                    ),
                ),
            ],
            max_auto_writeoff_gbp="50",
            allowed_auto_reason_codes=["FREIGHT_DAMAGE", "ROUNDING"],
            manual_writeoff_reason_codes=["DAMAGED_GOODS"],
            requires_explicit_remittance_reason=True,
        ),
        automation_stopped=[
            AutomationStop(
                code="AUTO_LIMIT_EXCEEDED",
                explanation=(
                    f"The £{short_pay:,.2f} residual exceeds SHORTPAY-01 v3 clause 4.2's "
                    "£50.00 automatic limit."
                ),
                excess_over_auto_limit=short_pay - money("50"),
            ),
            AutomationStop(
                code="REASON_NOT_AUTO_APPROVED",
                explanation=(
                    "The located remittance claims DAMAGED_GOODS, which is not an automatic reason "
                    "in SHORTPAY-01 v3. The claim is evidence, not independently proven fact."
                ),
                excess_over_auto_limit=short_pay - money("50"),
            ),
        ],
        remaining_ar_state=_ar_state(
            cash="0",
            adjustment="0",
            open_balance=invoice_balance,
            invoice_state="OPEN",
            receipt_status="HELD",
            receipt_unapplied=receipt_amount,
        ),
        proposed_after_valid_decision=_ar_state(
            cash=receipt_amount,
            adjustment="0",
            open_balance=short_pay,
            invoice_state="OPEN",
            receipt_status="APPLIED",
            receipt_unapplied="0",
        ),
        input_versions=InputVersions(
            expected_receipt_version=2,
            expected_invoice_ledger_version=7,
            expected_policy_version=3,
        ),
        control_checks=[],
        allowed_actions=_action_contract(),
        control_boundary=(
            "Synthetic hackathon state only. Material short-pay cash remains HELD and the ledger "
            "unchanged until a valid decision. No payment initiation, production ledger write or "
            "policy mutation is available."
        ),
    )
    append_review_audit(
        packet,
        actor="cash-application-control",
        action="review.requested",
        details={
            "application_status": ApplicationStatus.REVIEW_REQUIRED,
            "receipt_allocation_status": "HELD",
            "invoice_open_balance": str(invoice_balance),
            "amount_at_risk": str(short_pay),
        },
    )
    _refresh_disposition(packet)
    return packet


def evaluate_fundamental_controls(packet: ControllerReviewPacket) -> list[ControlCheck]:
    receipt = packet.receipt
    match = packet.customer_invoice_match
    current = packet.remaining_ar_state
    proposed = packet.proposed_after_valid_decision
    exact_identity = f"({receipt.source_system}, {receipt.source_transaction_id})"
    current_equation = money(
        current.cash_applied + current.authorised_adjustment + current.open_balance
    ) == current.invoice_balance_before
    proposed_equation = money(
        proposed.cash_applied + proposed.authorised_adjustment + proposed.open_balance
    ) == proposed.invoice_balance_before
    checks = [
        (
            "NO_DUPLICATE_RECEIPT",
            not receipt.duplicate_detected,
            f"Exact bank-source identity {exact_identity} is unique."
            if not receipt.duplicate_detected
            else f"Exact bank-source identity {exact_identity} already exists or was posted.",
        ),
        (
            "RECEIPT_BOOKED_POSITIVE",
            receipt.settlement_status == "BOOKED" and receipt.amount > 0,
            f"Receipt is {receipt.settlement_status} for £{receipt.amount:,.2f}.",
        ),
        (
            "INPUT_VERSIONS_CURRENT",
            (
                receipt.version == packet.input_versions.expected_receipt_version
                and match.invoice_ledger_version
                == packet.input_versions.expected_invoice_ledger_version
                and packet.policy.version == packet.input_versions.expected_policy_version
            ),
            (
                f"Receipt v{receipt.version}, invoice ledger v{match.invoice_ledger_version}, "
                f"policy v{packet.policy.version} match the captured review inputs."
            ),
        ),
        (
            "INVOICE_OPEN_AT_SNAPSHOT",
            match.invoice_status_at_snapshot == "OPEN",
            f"Invoice was {match.invoice_status_at_snapshot} at ledger version "
            f"{match.invoice_ledger_version}.",
        ),
        (
            "CURRENCY_COMPATIBLE",
            receipt.currency == match.invoice_currency,
            f"Receipt is {receipt.currency}; invoice is {match.invoice_currency}.",
        ),
        (
            "RECEIPT_ALLOCATION_VALID",
            (
                match.proposed_cash_application >= 0
                and match.receipt_unapplied_amount_after_post >= 0
                and match.proposed_cash_application <= receipt.available_amount
                and money(
                    match.proposed_cash_application + match.receipt_unapplied_amount_after_post
                )
                == receipt.amount
            ),
            (
                f"Proposed £{match.proposed_cash_application:,.2f} cash + "
                f"£{match.receipt_unapplied_amount_after_post:,.2f} residual = "
                f"£{receipt.amount:,.2f} receipt."
            ),
        ),
        (
            "INVOICE_BALANCE_VALID",
            (
                match.proposed_cash_application <= match.invoice_open_balance_before
                and money(
                    match.invoice_open_balance_before - match.proposed_cash_application
                )
                == packet.amount_at_risk
                and current_equation
                and proposed_equation
                and proposed.open_balance == packet.amount_at_risk
            ),
            (
                f"Current ledger: £{current.cash_applied:,.2f} cash + "
                f"£{current.authorised_adjustment:,.2f} adjustment + "
                f"£{current.open_balance:,.2f} open = £{current.invoice_balance_before:,.2f}; "
                f"proposed open balance is £{proposed.open_balance:,.2f}."
            ),
        ),
        (
            "DECISION_IDEMPOTENCY_READY",
            True,
            "A unique decision_id and the current review_version are required for every mutation.",
        ),
    ]
    return [
        ControlCheck(code=code, outcome="PASS" if passed else "BLOCK", explanation=explanation)
        for code, passed, explanation in checks
    ]


def _refresh_disposition(packet: ControllerReviewPacket) -> None:
    packet.control_checks = evaluate_fundamental_controls(packet)
    if any(not check.passed for check in packet.control_checks):
        packet.control_disposition = "BLOCK"
        packet.application_status = ApplicationStatus.CONTROL_BLOCKED
        packet.exception_status = ExceptionStatus.BLOCKED
        packet.receipt.allocation_status = "UNAPPLIED"
        packet.remaining_ar_state.receipt_allocation_status = "UNAPPLIED"
        packet.allowed_actions = []
    elif packet.application_status == ApplicationStatus.REVIEW_REQUIRED:
        packet.control_disposition = "REVIEW_REQUIRED"


class ControllerReviewService:
    def __init__(self, packet: ControllerReviewPacket | None = None) -> None:
        self._lock = RLock()
        self._packet = (packet or build_short_pay_packet()).model_copy(deep=True)
        self._requests: dict[str, ReviewDecisionRequest] = {}
        self._decisions: dict[str, ReviewDecision] = {}
        _refresh_disposition(self._packet)

    def reset_demo(self) -> ControllerReviewPacket:
        with self._lock:
            self._packet = build_short_pay_packet()
            self._requests.clear()
            self._decisions.clear()
            return self.get_packet(self._packet.case_id)

    def reviewers(self) -> list[ReviewerAuthority]:
        return [reviewer.model_copy(deep=True) for reviewer in _REVIEWERS.values()]

    def get_packet(self, case_id: str) -> ControllerReviewPacket:
        with self._lock:
            if case_id != self._packet.case_id:
                raise ControllerReviewError(
                    "CASE_NOT_FOUND", f"Review case {case_id} was not found."
                )
            _refresh_disposition(self._packet)
            return self._packet.model_copy(deep=True)

    def decide(self, case_id: str, request: ReviewDecisionRequest) -> ControllerReviewPacket:
        with self._lock:
            if case_id != self._packet.case_id:
                raise ControllerReviewError(
                    "CASE_NOT_FOUND", f"Review case {case_id} was not found."
                )

            prior_request = self._requests.get(request.decision_id)
            if prior_request is not None:
                if prior_request != request:
                    raise ControllerReviewError(
                        "IDEMPOTENCY_CONFLICT",
                        "The decision_id was already used with different decision content.",
                        decision_id=request.decision_id,
                    )
                replay = self._decisions[request.decision_id].model_copy(
                    deep=True, update={"idempotent_replay": True}
                )
                packet = self._packet.model_copy(deep=True)
                packet.recorded_decision = replay
                return packet

            _refresh_disposition(self._packet)
            if self._packet.control_disposition == "BLOCK":
                failed_controls = [
                    check.code for check in self._packet.control_checks if not check.passed
                ]
                self._deny(
                    request,
                    "HARD_BLOCK",
                    "A blocked application version is never approvable.",
                )
                raise ControllerReviewError(
                    "HARD_BLOCK",
                    (
                        "A blocked application version is terminal; corrected inputs require a "
                        "new version."
                    ),
                    failed_controls=failed_controls,
                )
            if request.expected_review_version != self._packet.review_version:
                self._deny(request, "STALE_REVIEW", "Review version changed before the decision.")
                raise ControllerReviewError(
                    "STALE_REVIEW",
                    "The review version is stale; reload before deciding. No ledger state changed.",
                    expected_review_version=request.expected_review_version,
                    current_review_version=self._packet.review_version,
                )
            if self._packet.review_status not in {
                ReviewStatus.AWAITING_CONTROLLER,
                ReviewStatus.ESCALATED,
            }:
                raise ControllerReviewError(
                    "REVIEW_ALREADY_DECIDED",
                    f"Case is already {self._packet.review_status}; no second decision is allowed.",
                )

            reviewer = _REVIEWERS.get(request.reviewer_id)
            if reviewer is None:
                self._deny(request, "REVIEWER_NOT_FOUND", "No current authority record was found.")
                raise ControllerReviewError(
                    "REVIEWER_NOT_FOUND", "Reviewer authority record was not found."
                )
            if request.action not in reviewer.permitted_actions:
                self._deny(
                    request,
                    "ACTION_NOT_PERMITTED",
                    "Reviewer role cannot take this action.",
                )
                raise ControllerReviewError(
                    "ACTION_NOT_PERMITTED",
                    f"{reviewer.role} is not permitted to perform {request.action}.",
                    reviewer_id=reviewer.reviewer_id,
                )
            if (
                reviewer.legal_entity_id != self._packet.legal_entity_id
                or reviewer.currency != self._packet.receipt.currency
                or reviewer.effective_from > self._packet.receipt.booking_date
            ):
                self._deny(
                    request,
                    "AUTHORITY_SCOPE_MISMATCH",
                    "Reviewer authority is not effective for this entity and currency.",
                )
                raise ControllerReviewError(
                    "AUTHORITY_SCOPE_MISMATCH",
                    "Reviewer authority is not effective for this legal entity and currency.",
                    reviewer_id=reviewer.reviewer_id,
                )

            if request.action == ReviewAction.APPROVE_WRITE_OFF:
                reason = request.reason_code or ""
                if reason not in self._packet.policy.manual_writeoff_reason_codes:
                    self._deny(
                        request,
                        "MANUAL_POLICY_DENIED",
                        "Policy does not permit manual write-off for this reason.",
                    )
                    raise ControllerReviewError(
                        "MANUAL_POLICY_DENIED",
                        "The active policy does not permit this manual write-off reason.",
                        policy_id=self._packet.policy.policy_id,
                        policy_version=self._packet.policy.version,
                    )
                if self._packet.amount_at_risk > reviewer.approval_limit_gbp:
                    self._packet.review_status = ReviewStatus.ESCALATED
                    self._packet.exception_status = ExceptionStatus.ESCALATED_AUTHORITY
                    self._deny(
                        request,
                        "AUTHORITY_EXCEEDED",
                        "Amount exceeds the reviewer's current delegated authority.",
                    )
                    raise ControllerReviewError(
                        "AUTHORITY_EXCEEDED",
                        (
                            f"£{self._packet.amount_at_risk:,.2f} exceeds "
                            f"{reviewer.reviewer_name}'s £{reviewer.approval_limit_gbp:,.2f} limit."
                        ),
                        amount_at_risk_gbp=str(self._packet.amount_at_risk),
                        reviewer_limit_gbp=str(reviewer.approval_limit_gbp),
                    )

            resulting_state, status, application_status, exception_status = (
                self._apply_simulated_action(request.action)
            )
            decision = ReviewDecision(
                decision_id=request.decision_id,
                review_version=self._packet.review_version,
                reviewer_id=reviewer.reviewer_id,
                reviewer_name=reviewer.reviewer_name,
                authority_id=reviewer.authority_id,
                authority_version=reviewer.authority_version,
                action=request.action,
                rationale=request.rationale,
                reason_code=request.reason_code,
                dispute_owner=request.dispute_owner,
                requested_evidence=request.requested_evidence,
                authorised_amount_gbp=(
                    self._packet.amount_at_risk
                    if request.action == ReviewAction.APPROVE_WRITE_OFF
                    else "0"
                ),
                resulting_ar_state=resulting_state,
            )
            self._requests[request.decision_id] = request.model_copy(deep=True)
            self._decisions[request.decision_id] = decision.model_copy(deep=True)
            self._packet.review_status = status
            self._packet.application_status = application_status
            self._packet.exception_status = exception_status
            self._packet.remaining_ar_state = resulting_state
            self._packet.receipt.allocation_status = resulting_state.receipt_allocation_status
            self._packet.recorded_decision = decision
            self._packet.review_version += 1
            self._packet.control_checks = evaluate_fundamental_controls(self._packet)
            append_review_audit(
                self._packet,
                actor=reviewer.reviewer_id,
                action="review.decision_recorded",
                details={
                    "action": request.action,
                    "authority_id": reviewer.authority_id,
                    "authority_version": reviewer.authority_version,
                    "decision_id": request.decision_id,
                    "review_version_before": request.expected_review_version,
                    "review_version_after": self._packet.review_version,
                },
            )
            if application_status == ApplicationStatus.POSTED_SIMULATED:
                append_review_audit(
                    self._packet,
                    actor="simulated-ar-adapter",
                    action="application.posted_simulated",
                    details={
                        "cash_applied": str(resulting_state.cash_applied),
                        "authorised_adjustment": str(resulting_state.authorised_adjustment),
                        "invoice_open_after": str(resulting_state.open_balance),
                        "invoice_ledger_version_before": (
                            self._packet.customer_invoice_match.invoice_ledger_version
                        ),
                        "invoice_ledger_version_after": resulting_state.ledger_version,
                        "receipt_allocation_status": resulting_state.receipt_allocation_status,
                    },
                )
            return self._packet.model_copy(deep=True)

    def _deny(self, request: ReviewDecisionRequest, code: str, explanation: str) -> None:
        self._packet.review_attempts.append(
            ReviewAttempt(
                decision_id=request.decision_id,
                reviewer_id=request.reviewer_id,
                action=request.action,
                code=code,
                explanation=explanation,
            )
        )
        action = {
            "AUTHORITY_EXCEEDED": "review.authority_denied",
            "HARD_BLOCK": "review.control_denied",
            "STALE_REVIEW": "review.stale_denied",
        }.get(code, "review.action_denied")
        append_review_audit(
            self._packet,
            actor=request.reviewer_id,
            action=action,
            details={
                "action": request.action,
                "code": code,
                "decision_id": request.decision_id,
                "ledger_mutated": False,
                "review_version": self._packet.review_version,
            },
        )

    def _apply_simulated_action(
        self, action: ReviewAction
    ) -> tuple[ARState, ReviewStatus, ApplicationStatus, ExceptionStatus]:
        if action == ReviewAction.APPROVE_WRITE_OFF:
            state = self._packet.proposed_after_valid_decision.model_copy(deep=True)
            state.ledger_version += 1
            state.authorised_adjustment = self._packet.amount_at_risk
            state.open_balance = money("0")
            state.invoice_state = "CLOSED"
            return (
                state,
                ReviewStatus.WRITE_OFF_APPROVED,
                ApplicationStatus.POSTED_SIMULATED,
                ExceptionStatus.RESOLVED,
            )
        if action == ReviewAction.LEAVE_BALANCE_OPEN:
            state = self._packet.proposed_after_valid_decision.model_copy(deep=True)
            state.ledger_version += 1
            return (
                state,
                ReviewStatus.BALANCE_LEFT_OPEN,
                ApplicationStatus.POSTED_SIMULATED,
                ExceptionStatus.COLLECTIONS_OPEN,
            )
        if action == ReviewAction.CREATE_DISPUTE:
            state = self._packet.proposed_after_valid_decision.model_copy(deep=True)
            state.ledger_version += 1
            state.invoice_state = "DISPUTED"
            return (
                state,
                ReviewStatus.DISPUTE_CREATED,
                ApplicationStatus.POSTED_SIMULATED,
                ExceptionStatus.DISPUTE_OPEN,
            )
        if action == ReviewAction.REQUEST_EVIDENCE:
            return (
                self._packet.remaining_ar_state.model_copy(deep=True),
                ReviewStatus.EVIDENCE_REQUESTED,
                ApplicationStatus.EVIDENCE_REQUIRED,
                ExceptionStatus.WAITING_EVIDENCE,
            )
        if action == ReviewAction.REJECT_MATCH:
            state = self._packet.remaining_ar_state.model_copy(deep=True)
            state.receipt_allocation_status = "UNAPPLIED"
            return (
                state,
                ReviewStatus.MATCH_REJECTED,
                ApplicationStatus.REJECTED,
                ExceptionStatus.RESOLVED,
            )
        raise AssertionError(f"Unhandled review action: {action}")
