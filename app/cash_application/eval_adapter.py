"""Deterministic adapter from exception investigation to canonical eval outcome fields."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.cash_application.evaluation import CashApplicationCaseInput, run_control_case
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
from app.cash_application.review import (
    ControllerReviewPacket,
    ReviewAction,
    verify_review_audit,
)
from app.private_markets import money as normalise_money


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


class TrialInvoiceOutcome(BaseModel):
    invoice_id: str
    invoice_state: str
    balance_before: Decimal
    cash_applied: Decimal
    authorised_adjustment: Decimal
    balance_after: Decimal
    ledger_version: int

    @field_validator(
        "balance_before",
        "cash_applied",
        "authorised_adjustment",
        "balance_after",
        mode="before",
    )
    @classmethod
    def normalise_amount(cls, value: Any) -> Decimal:
        return normalise_money(value)


class TrialAuditOutcome(BaseModel):
    event_count: int = Field(ge=0)
    actions: list[str]
    denial_codes: list[str]
    decision_count: int = Field(ge=0)
    simulated_post_count: int = Field(ge=0)
    chain_valid: bool


class ControllerReviewTrialOutcome(BaseModel):
    case_id: str
    trial_id: str
    control_disposition: str
    failed_control_codes: list[str]
    receipt_settlement_status: str
    receipt_allocation_status: str
    application_status: str
    exception_status: str
    review_status: str
    review_version: int
    decision_recorded: bool
    decision_action: ReviewAction | None
    latest_denial_code: str | None
    invoice: TrialInvoiceOutcome
    ledger_mutated: bool
    production_write_performed: bool
    audit: TrialAuditOutcome


def to_trial_outcome(
    packet: ControllerReviewPacket, *, trial_id: str
) -> ControllerReviewTrialOutcome:
    """Map typed controller-review state to stable grader fields."""

    state = packet.remaining_ar_state
    audit_actions = [event.action for event in packet.audit_events]
    denial_codes = [attempt.code for attempt in packet.review_attempts]
    simulated_post_count = audit_actions.count("application.posted_simulated")
    return ControllerReviewTrialOutcome(
        case_id=packet.case_id,
        trial_id=trial_id,
        control_disposition=packet.control_disposition,
        failed_control_codes=[
            check.code for check in packet.control_checks if check.outcome == "BLOCK"
        ],
        receipt_settlement_status=packet.receipt.settlement_status,
        receipt_allocation_status=packet.receipt.allocation_status,
        application_status=packet.application_status,
        exception_status=packet.exception_status,
        review_status=packet.review_status,
        review_version=packet.review_version,
        decision_recorded=packet.recorded_decision is not None,
        decision_action=(
            packet.recorded_decision.action if packet.recorded_decision is not None else None
        ),
        latest_denial_code=denial_codes[-1] if denial_codes else None,
        invoice=TrialInvoiceOutcome(
            invoice_id=state.invoice_id,
            invoice_state=state.invoice_state,
            balance_before=state.invoice_balance_before,
            cash_applied=state.cash_applied,
            authorised_adjustment=state.authorised_adjustment,
            balance_after=state.open_balance,
            ledger_version=state.ledger_version,
        ),
        ledger_mutated=(
            state.cash_applied > 0 or state.authorised_adjustment > 0 or simulated_post_count > 0
        ),
        production_write_performed=packet.production_write_performed,
        audit=TrialAuditOutcome(
            event_count=len(packet.audit_events),
            actions=audit_actions,
            denial_codes=denial_codes,
            decision_count=audit_actions.count("review.decision_recorded"),
            simulated_post_count=simulated_post_count,
            chain_valid=verify_review_audit(packet.audit_events),
        ),
    )


def _money_string(value: Any) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    if not amount.is_finite():
        raise ValueError("Money must be finite")
    return format(amount, ".2f")


def _case_id_from_trial(trial_id: str) -> str:
    if not isinstance(trial_id, str) or not trial_id.strip():
        raise ValueError("trial_id must not be blank")
    case_id, separator, _ = trial_id.partition("-trial-")
    if not separator or not case_id:
        raise ValueError("trial_id must use {case_id}-trial-{number}")
    return case_id


def _input_evidence(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == "evidence_refs" and isinstance(nested, list):
                refs.extend(item for item in nested if isinstance(item, str) and item)
            else:
                refs.extend(_input_evidence(nested))
    elif isinstance(value, list):
        for nested in value:
            refs.extend(_input_evidence(nested))
    return list(dict.fromkeys(refs))


def _policy_state(policy: dict[str, Any] | None) -> dict[str, Any]:
    policy_id = policy.get("policy_id") if policy else None
    version = policy.get("version") if policy else None
    return {
        "active_policy_id": policy_id,
        "active_policy_version": version,
        "active_policy_id_after": policy_id,
        "active_policy_version_after": version,
        "consulted_policy_id": policy_id,
        "consulted_policy_version": version,
        "proposal": None,
    }


def _audit_events(
    event_types: list[str],
    *,
    trial_id: str,
    evidence_refs: list[str],
    policy: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not evidence_refs:
        raise ValueError("Every eval path requires supplied evidence")
    events: list[dict[str, Any]] = []
    previous_hash: str | None = None
    for sequence, event_type in enumerate(event_types, start=1):
        event: dict[str, Any] = {
            "event_id": f"{trial_id}-event-{sequence}",
            "event_type": event_type,
            "previous_event_hash": previous_hash,
            "evidence_refs": evidence_refs,
            "simulation_label": "SIMULATED — no Cherry Money production write",
        }
        if event_type == "ADJUSTMENT_RECORDED" and policy is not None:
            event["policy_ref"] = {
                "policy_id": policy["policy_id"],
                "policy_version": policy["version"],
                "source_sha256": policy.get("source_sha256"),
            }
        event["event_hash"] = hashlib.sha256(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        previous_hash = str(event["event_hash"])
        events.append(event)
    return events


def _trace(names: list[str], *, trial_id: str) -> dict[str, Any]:
    return {
        "tool_calls": [
            {"call_id": f"{trial_id}-call-{index}", "name": name, "deterministic": True}
            for index, name in enumerate(names, start=1)
        ],
        "production_write_performed": False,
    }


def _unchanged_invoices(invoices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "invoice_id": invoice["id"],
            "balance_after": _money_string(invoice["balance"]),
            "state": "CLOSED" if invoice.get("status") == "CLOSED" else "OPEN",
        }
        for invoice in sorted(invoices, key=lambda item: str(item["id"]))
    ]


def _review_packet(
    case_id: str,
    evidence_refs: list[str],
    reason_code: str | None,
    *,
    decision_required: str,
) -> dict[str, Any]:
    return {
        "packet_id": f"RP-{case_id}",
        "evidence_refs": evidence_refs,
        "reason_codes": [reason_code] if reason_code else [],
        "decision_required": decision_required,
        "simulation_label": "SIMULATED — no Cherry Money production write",
    }


def _authority_case(case_input: dict[str, Any], *, case_id: str, trial_id: str) -> dict[str, Any]:
    invoices = list(case_input.get("invoices", []))
    policies = list(case_input.get("policies", []))
    remittance = case_input.get("remittance")
    actor = case_input.get("authenticated_actor")
    authorities = list(case_input.get("authority_records", []))
    requested = case_input.get("requested_review_action")
    if not (
        len(invoices) == 1
        and len(policies) == 1
        and isinstance(remittance, dict)
        and isinstance(actor, dict)
        and len(authorities) == 1
        and isinstance(requested, dict)
    ):
        raise ValueError("Authority case requires one evidenced invoice, policy and authority")
    invoice = invoices[0]
    policy = policies[0]
    authority = authorities[0]
    line = remittance.get("lines", [])[0]
    if requested.get("decision") != authority.get("decision"):
        raise ValueError("Requested action does not match supplied authority")
    if actor.get("reviewer_id") != authority.get("reviewer_id"):
        raise ValueError("Authenticated reviewer does not match supplied authority")
    requested_amount = Decimal(str(requested["amount"]))
    authority_limit = Decimal(str(authority["max_amount"]))
    if requested_amount <= authority_limit:
        raise ValueError("Authority adapter is only for a denied over-limit decision")
    evidence = list(
        dict.fromkeys(
            _input_evidence(remittance)
            + _input_evidence(invoice)
            + _input_evidence(policy)
            + _input_evidence(actor)
            + _input_evidence(authority)
        )
    )
    reason = line.get("reason_code")
    event_types = ["AUTHORITY_REJECTED", "REVIEW_ESCALATED"]
    return {
        "case_id": case_id,
        "receipt": None,
        "application": {
            "status": "REVIEW_REQUIRED",
            "application_kind": "SHORT_PAY",
            "residual_kind": "CLAIMED_DEDUCTION",
        },
        "applications": [],
        "invoices": _unchanged_invoices(invoices),
        "adjustments": [],
        "exception": {
            "type": "AUTHORITY_EXCEEDED",
            "status": "ESCALATED_AUTHORITY",
            "amount": _money_string(requested_amount),
            "reason_code": reason,
        },
        "review": {
            "status": "ESCALATED",
            "reviewer_id": actor["reviewer_id"],
            "decision": None,
            "authority_id": authority["authority_id"],
        },
        "policy": _policy_state(policy),
        "audit_events": _audit_events(
            event_types, trial_id=trial_id, evidence_refs=evidence, policy=policy
        ),
        "trace": _trace(["cash_record_review_decision"], trial_id=trial_id),
        "review_packet": _review_packet(
            case_id,
            evidence,
            str(reason) if reason else None,
            decision_required="escalate authority",
        ),
        "simulation_only": True,
        "production_write_performed": False,
    }


def _policy_proposal_case(
    case_input: dict[str, Any], *, case_id: str, trial_id: str
) -> dict[str, Any]:
    policies = list(case_input.get("policies", []))
    history = list(case_input.get("history", []))
    active_bytes = case_input.get("active_policy_bytes")
    if len(policies) != 1 or not history or not isinstance(active_bytes, str):
        raise ValueError("Policy proposal requires one active policy and reviewed history")
    policy = policies[0]
    approved = [item for item in history if item.get("status") == "APPROVED"]
    if not approved:
        raise ValueError("Policy proposal requires approved historical decisions")
    reasons = {item.get("reason_code") for item in approved}
    if len(reasons) != 1 or None in reasons:
        raise ValueError("Policy proposal history must have one evidenced reason")
    proposed_amount = max(Decimal(str(item["amount"])) for item in approved)
    state = _policy_state(policy)
    state.update(
        {
            "active_policy_bytes_before": active_bytes,
            "active_policy_bytes_after": active_bytes,
            "proposal": {
                "proposal_id": f"PROP-{case_id}",
                "base_policy_id": policy["policy_id"],
                "base_policy_version": policy["version"],
                "proposed_version": str(int(str(policy["version"])) + 1),
                "proposed_max_auto_amount": _money_string(proposed_amount),
                "reason_code": next(iter(reasons)),
                "supporting_decision_ids": [item["decision_id"] for item in approved],
                "status": "DRAFT_PROPOSAL",
            },
        }
    )
    evidence = _input_evidence({"policy": policy, "history": history})
    return {
        "case_id": case_id,
        "receipt": None,
        "application": None,
        "applications": [],
        "invoices": [],
        "adjustments": [],
        "exception": None,
        "review": None,
        "policy": state,
        "audit_events": _audit_events(
            ["POLICY_PROPOSAL_CREATED"],
            trial_id=trial_id,
            evidence_refs=evidence,
            policy=policy,
        ),
        "trace": _trace(["cash_propose_policy_change"], trial_id=trial_id),
        "review_packet": None,
        "simulation_only": True,
        "production_write_performed": False,
    }


def run_case(
    case_input: dict[str, Any] | CashApplicationCaseInput, trial_id: str
) -> dict[str, Any]:
    """Run one evidence-grounded case through deterministic simulated controls.

    The adapter consumes only public case inputs. It never reads grader expectations, calls a
    model, initiates a payment, or reaches a production accounting system.
    """

    if isinstance(case_input, CashApplicationCaseInput):
        return run_control_case(case_input, trial_id)
    if not isinstance(case_input, dict):
        raise TypeError("case_input must be a mapping")
    case_id = _case_id_from_trial(trial_id)
    if case_input.get("receipt") is None:
        if case_input.get("requested_review_action") is not None:
            return _authority_case(case_input, case_id=case_id, trial_id=trial_id)
        return _policy_proposal_case(case_input, case_id=case_id, trial_id=trial_id)

    receipt = case_input["receipt"]
    if not isinstance(receipt, dict):
        raise TypeError("receipt must be an object")
    invoices = list(case_input.get("invoices", []))
    customers = list(case_input.get("customers", []))
    remittance = case_input.get("remittance")
    policies = list(case_input.get("policies", []))
    policy = policies[0] if len(policies) == 1 else None
    amount = Decimal(str(receipt["amount"]))
    settlement = str(receipt.get("settlement_status", receipt.get("status")))
    all_evidence = _input_evidence(case_input)
    base_policy = _policy_state(policy)
    result: dict[str, Any] = {
        "case_id": case_id,
        "receipt": {
            "receipt_id": receipt["id"],
            "settlement_status": settlement,
            "allocation_status": "UNAPPLIED",
            "applied_amount": "0.00",
            "unapplied_amount": _money_string(amount),
        },
        "application": {
            "status": "CONTROL_BLOCKED",
            "application_kind": "EXACT",
            "residual_kind": "NONE",
        },
        "applications": [],
        "invoices": _unchanged_invoices(invoices),
        "adjustments": [],
        "exception": None,
        "review": None,
        "policy": base_policy,
        "audit_events": [],
        "trace": {"tool_calls": []},
        "review_packet": None,
        "simulation_only": True,
        "production_write_performed": False,
    }

    prior = list(case_input.get("prior_applications", []))
    source_identity = (receipt.get("source_system"), receipt.get("source_transaction_id"))
    duplicate = all(source_identity) and any(
        (
            item.get("receipt_source_system"),
            item.get("receipt_source_transaction_id"),
        )
        == source_identity
        for item in prior
    )
    if duplicate:
        prior_applied = sum(Decimal(str(item["amount"])) for item in prior)
        result["receipt"] = {
            "receipt_id": receipt["id"],
            "settlement_status": settlement,
            "allocation_status": "APPLIED",
            "applied_amount": _money_string(prior_applied),
            "unapplied_amount": _money_string(amount - prior_applied),
        }
        result["exception"] = {
            "type": "DUPLICATE_RECEIPT",
            "status": "BLOCKED",
            "amount": _money_string(amount),
            "reason_code": None,
        }
        result["audit_events"] = _audit_events(
            ["DUPLICATE_ATTEMPT_BLOCKED"],
            trial_id=trial_id,
            evidence_refs=all_evidence,
            policy=None,
        )
        result["trace"] = _trace(
            ["cash_get_receipt_context", "cash_evaluate_application"], trial_id=trial_id
        )
        return result

    if settlement != "BOOKED":
        result["exception"] = {
            "type": "INELIGIBLE_RECEIPT",
            "status": "BLOCKED",
            "amount": _money_string(amount),
            "reason_code": None,
        }
        result["audit_events"] = _audit_events(
            ["CONTROL_BLOCKED"], trial_id=trial_id, evidence_refs=all_evidence, policy=None
        )
        result["trace"] = _trace(
            ["cash_get_receipt_context", "cash_evaluate_application"], trial_id=trial_id
        )
        return result

    if remittance is None:
        customer_evidence = _input_evidence({"receipt": receipt, "customers": customers})
        result["receipt"]["allocation_status"] = "HELD"
        result["application"]["status"] = "EVIDENCE_REQUIRED"
        result["exception"] = {
            "type": "AMBIGUOUS_CUSTOMER" if len(customers) > 1 else "MISSING_REMITTANCE",
            "status": "WAITING_EVIDENCE",
            "amount": _money_string(amount),
            "reason_code": None,
        }
        result["review_packet"] = _review_packet(
            case_id, customer_evidence, None, decision_required="provide stronger customer evidence"
        )
        result["audit_events"] = _audit_events(
            ["EVIDENCE_LINKED", "EXCEPTION_CREATED", "REVIEW_REQUIRED"],
            trial_id=trial_id,
            evidence_refs=customer_evidence,
            policy=None,
        )
        result["trace"] = _trace(
            [
                "cash_get_receipt_context",
                "cash_evaluate_application",
                "cash_create_exception",
                "cash_prepare_review_packet",
            ],
            trial_id=trial_id,
        )
        return result

    if not isinstance(remittance, dict):
        raise TypeError("remittance must be an object or null")
    lines = list(remittance.get("lines", []))
    invoice_by_id = {str(item["id"]): item for item in invoices}
    if not lines or any(str(line.get("invoice_id")) not in invoice_by_id for line in lines):
        raise ValueError("Every allocation must reference a supplied invoice")
    matched_invoices = [invoice_by_id[str(line["invoice_id"])] for line in lines]
    packet_evidence = list(
        dict.fromkeys(
            _input_evidence(receipt)
            + _input_evidence(remittance)
            + _input_evidence(matched_invoices)
            + (_input_evidence(policy) if policy else [])
        )
    )
    currency_mismatch = any(
        invoice.get("currency") != receipt.get("currency") for invoice in matched_invoices
    )
    if currency_mismatch:
        result["exception"] = {
            "type": "CURRENCY_MISMATCH",
            "status": "BLOCKED",
            "amount": _money_string(amount),
            "reason_code": None,
        }
        result["review_packet"] = _review_packet(
            case_id, packet_evidence, None, decision_required="supply an approved FX rule"
        )
        result["audit_events"] = _audit_events(
            ["EVIDENCE_LINKED", "CONTROL_BLOCKED", "REVIEW_REQUIRED"],
            trial_id=trial_id,
            evidence_refs=packet_evidence,
            policy=None,
        )
        result["trace"] = _trace(
            [
                "cash_match_open_items",
                "cash_evaluate_application",
                "cash_create_exception",
                "cash_prepare_review_packet",
            ],
            trial_id=trial_id,
        )
        return result

    line_total = sum(Decimal(str(line["amount"])) for line in lines)
    if line_total > amount:
        raise ValueError("Allocation total exceeds booked receipt")
    shortfalls = [
        Decimal(str(invoice["balance"])) - Decimal(str(line["amount"]))
        for line, invoice in zip(lines, matched_invoices, strict=True)
    ]
    if any(value < 0 for value in shortfalls):
        raise ValueError("Allocation would reduce an invoice below zero")
    reasons = [line.get("reason_code") for line in lines if line.get("reason_code")]
    deduction_total = sum(Decimal(str(line.get("deduction_amount", "0.00"))) for line in lines)
    partial = remittance.get("payment_type") == "PARTIAL"
    overpayment = amount > line_total
    short_pay = not partial and not overpayment and any(value > 0 for value in shortfalls)

    if overpayment:
        result["receipt"] = {
            "receipt_id": receipt["id"],
            "settlement_status": settlement,
            "allocation_status": "PARTIALLY_APPLIED",
            "applied_amount": _money_string(line_total),
            "unapplied_amount": _money_string(amount - line_total),
        }
        result["application"] = {
            "status": "POSTED_SIMULATED",
            "application_kind": "OVERPAYMENT",
            "residual_kind": "RECEIPT_UNAPPLIED",
        }
        result["exception"] = {
            "type": "OVERPAYMENT_RESIDUAL",
            "status": "WAITING_REVIEW",
            "amount": _money_string(amount - line_total),
            "reason_code": None,
        }
        result["review"] = {"status": "REQUESTED", "packet_id": f"RP-{case_id}"}
        result["review_packet"] = _review_packet(
            case_id, packet_evidence, None, decision_required="route unapplied cash"
        )
        event_types = [
            "EVIDENCE_LINKED",
            "CONTROLS_PASSED",
            "CASH_APPLIED",
            "RESIDUAL_RECORDED",
            "REVIEW_REQUIRED",
        ]
        trace_names = [
            "cash_match_open_items",
            "cash_evaluate_application",
            "cash_create_exception",
            "cash_prepare_review_packet",
            "cash_apply_simulated",
        ]
    elif short_pay:
        if policy is None:
            raise ValueError("Short-pay requires an approved effective policy")
        if deduction_total and deduction_total != sum(shortfalls):
            raise ValueError("Claimed deduction does not equal the invoice shortfall")
        reason = str(reasons[0]) if len(reasons) == 1 else None
        auto_allowed = (
            reason is not None
            and policy.get("status") == "APPROVED"
            and policy.get("currency") == receipt.get("currency")
            and reason in policy.get("allowed_auto_reason_codes", [])
            and sum(shortfalls) <= Decimal(str(policy["max_auto_amount"]))
            and deduction_total == sum(shortfalls)
        )
        if auto_allowed:
            result["receipt"] = {
                "receipt_id": receipt["id"],
                "settlement_status": settlement,
                "allocation_status": "APPLIED",
                "applied_amount": _money_string(line_total),
                "unapplied_amount": "0.00",
            }
            result["application"] = {
                "status": "POSTED_SIMULATED",
                "application_kind": "SHORT_PAY",
                "residual_kind": "CLAIMED_DEDUCTION",
            }
            result["adjustments"] = [
                {
                    "invoice_id": line["invoice_id"],
                    "amount": _money_string(shortfall),
                    "reason_code": reason,
                    "mode": "AUTO",
                    "policy_id": policy["policy_id"],
                    "policy_version": policy["version"],
                }
                for line, shortfall in zip(lines, shortfalls, strict=True)
                if shortfall > 0
            ]
            event_types = [
                "EVIDENCE_LINKED",
                "POLICY_EVALUATED",
                "CONTROLS_PASSED",
                "CASH_APPLIED",
                "ADJUSTMENT_RECORDED",
            ]
            trace_names = [
                "cash_match_open_items",
                "policy_get_shortpay_rule",
                "cash_evaluate_application",
                "cash_apply_simulated",
            ]
        elif reason is None:
            result["receipt"]["allocation_status"] = "HELD"
            result["application"] = {
                "status": "EVIDENCE_REQUIRED",
                "application_kind": "SHORT_PAY",
                "residual_kind": "CLAIMED_DEDUCTION",
            }
            result["exception"] = {
                "type": "UNSUPPORTED_DEDUCTION",
                "status": "WAITING_EVIDENCE",
                "amount": _money_string(sum(shortfalls)),
                "reason_code": None,
            }
            result["review_packet"] = _review_packet(
                case_id,
                packet_evidence,
                None,
                decision_required="provide deduction reason evidence",
            )
            event_types = [
                "EVIDENCE_LINKED",
                "POLICY_EVALUATED",
                "EXCEPTION_CREATED",
                "REVIEW_REQUIRED",
            ]
            trace_names = [
                "policy_get_shortpay_rule",
                "cash_evaluate_application",
                "cash_create_exception",
                "cash_prepare_review_packet",
            ]
        else:
            scripted = case_input.get("scripted_review_action")
            manual_rules = policy.get("manual_action_rules", {})
            allowed_actions = manual_rules.get(reason, []) if isinstance(manual_rules, dict) else []
            result["receipt"]["allocation_status"] = "HELD"
            result["application"] = {
                "status": "REVIEW_REQUIRED",
                "application_kind": "SHORT_PAY",
                "residual_kind": "CLAIMED_DEDUCTION",
            }
            result["exception"] = {
                "type": "MATERIAL_SHORT_PAY",
                "status": "WAITING_REVIEW",
                "amount": _money_string(sum(shortfalls)),
                "reason_code": reason,
            }
            result["review"] = {"status": "REQUESTED", "packet_id": f"RP-{case_id}"}
            result["review_packet"] = _review_packet(
                case_id, packet_evidence, reason, decision_required="choose residual treatment"
            )
            result["checkpoints"] = {
                "pre_review": {
                    "receipt": dict(result["receipt"]),
                    "application": {"status": "REVIEW_REQUIRED"},
                    "applications": [],
                    "adjustments": [],
                    "invoices": _unchanged_invoices(invoices),
                    "exception": dict(result["exception"]),
                    "review": {"status": "REQUESTED"},
                }
            }
            event_types = [
                "EVIDENCE_LINKED",
                "POLICY_EVALUATED",
                "EXCEPTION_CREATED",
                "REVIEW_REQUIRED",
            ]
            trace_names = [
                "policy_get_shortpay_rule",
                "cash_evaluate_application",
                "cash_create_exception",
                "cash_prepare_review_packet",
            ]
            if isinstance(scripted, dict):
                decision = scripted.get("decision")
                if decision not in allowed_actions:
                    raise ValueError("Scripted decision is not allowed by the supplied policy")
                if _money_string(scripted.get("amount")) != _money_string(sum(shortfalls)):
                    raise ValueError("Scripted decision amount does not equal the residual")
                if scripted.get("reason_code") != reason:
                    raise ValueError("Scripted decision reason is not evidenced")
                if decision == "CREATE_DISPUTE" and not scripted.get("owner_id"):
                    raise ValueError("CREATE_DISPUTE requires an evidenced owner")
                if decision not in {"CREATE_DISPUTE", "LEAVE_BALANCE_OPEN"}:
                    raise ValueError("Only non-adjusting residual decisions can post this case")
                result["receipt"] = {
                    "receipt_id": receipt["id"],
                    "settlement_status": settlement,
                    "allocation_status": "APPLIED",
                    "applied_amount": _money_string(line_total),
                    "unapplied_amount": "0.00",
                }
                result["application"]["status"] = "POSTED_SIMULATED"
                result["exception"]["status"] = (
                    "DISPUTE_OPEN" if decision == "CREATE_DISPUTE" else "COLLECTIONS_OPEN"
                )
                result["review"] = {
                    "status": "DECIDED",
                    "decision": decision,
                    "packet_id": f"RP-{case_id}",
                }
                event_types += ["REVIEW_DECIDED", "CONTROLS_PASSED", "CASH_APPLIED"]
                trace_names += [
                    "cash_record_review_decision",
                    "cash_evaluate_application",
                    "cash_apply_simulated",
                ]
    else:
        result["receipt"] = {
            "receipt_id": receipt["id"],
            "settlement_status": settlement,
            "allocation_status": "APPLIED",
            "applied_amount": _money_string(line_total),
            "unapplied_amount": _money_string(amount - line_total),
        }
        result["application"] = {
            "status": "POSTED_SIMULATED",
            "application_kind": (
                "PARTIAL_PAYMENT" if partial else ("MULTI_INVOICE" if len(lines) > 1 else "EXACT")
            ),
            "residual_kind": "INVOICE_OPEN_PARTIAL" if partial else "NONE",
        }
        event_types = ["EVIDENCE_LINKED", "CONTROLS_PASSED", "CASH_APPLIED"]
        trace_names = [
            "cash_get_receipt_context",
            "ar_get_open_items",
            "cash_match_open_items",
            "cash_evaluate_application",
            "cash_apply_simulated",
        ]

    posted = result["application"]["status"] == "POSTED_SIMULATED"
    applications: list[dict[str, Any]] = []
    if posted:
        applications = [
            {
                "application_id": f"APP-{receipt['id']}-{index}-{trial_id}",
                "receipt_id": receipt["id"],
                "invoice_id": line["invoice_id"],
                "amount": _money_string(line["amount"]),
                "mode": "AUTO",
            }
            for index, line in enumerate(lines, start=1)
            if Decimal(str(line["amount"])) > 0
        ]
    result["applications"] = applications
    application_by_invoice = {
        str(item["invoice_id"]): Decimal(str(item["amount"])) for item in applications
    }
    adjustment_by_invoice = {
        str(item["invoice_id"]): Decimal(str(item["amount"])) for item in result["adjustments"]
    }
    result["invoices"] = [
        {
            "invoice_id": invoice["id"],
            "balance_after": _money_string(
                Decimal(str(invoice["balance"]))
                - application_by_invoice.get(str(invoice["id"]), Decimal("0"))
                - adjustment_by_invoice.get(str(invoice["id"]), Decimal("0"))
            ),
            "state": (
                "CLOSED"
                if Decimal(str(invoice["balance"]))
                - application_by_invoice.get(str(invoice["id"]), Decimal("0"))
                - adjustment_by_invoice.get(str(invoice["id"]), Decimal("0"))
                == 0
                else "OPEN"
            ),
        }
        for invoice in sorted(invoices, key=lambda item: str(item["id"]))
    ]
    result["audit_events"] = _audit_events(
        event_types, trial_id=trial_id, evidence_refs=packet_evidence, policy=policy
    )
    result["trace"] = _trace(trace_names, trial_id=trial_id)
    return result
