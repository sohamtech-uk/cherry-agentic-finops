"""Thin canonical outcome adapter for deterministic cash-application evals."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.cash_application.controls import evaluate_cash_application
from app.cash_application.ledger import SimulatedCashLedger
from app.cash_application.models import (
    ZERO,
    CashReceipt,
    OpenARItem,
    ReceiptIdentity,
    RemittanceEvidence,
    ShortPayPolicy,
    required_identifier,
)


@dataclass(frozen=True, slots=True)
class CashApplicationCaseInput:
    """Typed inputs consumed by ``run_case``; iterable fields are frozen on construction."""

    receipt: CashReceipt
    remittance: RemittanceEvidence
    open_items: tuple[OpenARItem, ...]
    policies: tuple[ShortPayPolicy, ...]
    processed_receipt_identities: frozenset[ReceiptIdentity]
    decision_date: date

    def __init__(
        self,
        *,
        receipt: CashReceipt,
        remittance: RemittanceEvidence,
        open_items: Iterable[OpenARItem],
        policies: Iterable[ShortPayPolicy] = (),
        processed_receipt_identities: Collection[ReceiptIdentity] = (),
        decision_date: date | None = None,
    ) -> None:
        object.__setattr__(self, "receipt", receipt)
        object.__setattr__(self, "remittance", remittance)
        object.__setattr__(self, "open_items", tuple(open_items))
        object.__setattr__(self, "policies", tuple(policies))
        object.__setattr__(
            self,
            "processed_receipt_identities",
            frozenset(processed_receipt_identities),
        )
        object.__setattr__(self, "decision_date", decision_date or receipt.booking_date)


def _amount(value: Decimal) -> str:
    return format(value, ".2f")


def _append_audit_event(
    events: list[dict[str, Any]],
    *,
    trial_id: str,
    action: str,
    details: dict[str, Any],
    evidence_ids: list[str],
) -> None:
    previous_hash = events[-1]["event_hash"] if events else "0" * 64
    payload = {
        "sequence": len(events) + 1,
        "trial_id": trial_id,
        "action": action,
        "details": details,
        "evidence_ids": evidence_ids,
        "previous_hash": previous_hash,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["event_hash"] = hashlib.sha256(encoded).hexdigest()
    events.append(payload)


def _audit_chain_valid(events: list[dict[str, Any]]) -> bool:
    previous_hash = "0" * 64
    for sequence, event in enumerate(events, start=1):
        if event["sequence"] != sequence or event["previous_hash"] != previous_hash:
            return False
        payload = {key: value for key, value in event.items() if key != "event_hash"}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(encoded).hexdigest() != event["event_hash"]:
            return False
        previous_hash = event["event_hash"]
    return True


def run_control_case(case_input: CashApplicationCaseInput, trial_id: str) -> dict[str, Any]:
    """Evaluate one case and return a stable, JSON-serialisable canonical outcome.

    This is an adapter only: all accounting decisions come from
    ``evaluate_cash_application`` and all mutations go through ``SimulatedCashLedger``.
    """

    canonical_trial_id = required_identifier(trial_id, field="trial_id")
    decision = evaluate_cash_application(
        case_input.receipt,
        case_input.remittance,
        case_input.open_items,
        policies=case_input.policies,
        processed_receipt_identities=case_input.processed_receipt_identities,
        as_of_date=case_input.decision_date,
    )
    ledger = SimulatedCashLedger(case_input.open_items)
    posting = None
    if decision.is_postable:
        posting = ledger.post(
            decision,
            idempotency_key=f"eval:{canonical_trial_id}:{case_input.receipt.receipt_id}",
        )

    evidence_ids = [reference.evidence_id for reference in decision.evidence_refs]
    audit_events: list[dict[str, Any]] = []
    _append_audit_event(
        audit_events,
        trial_id=canonical_trial_id,
        action="cash_application.controls_evaluated",
        details={
            "application_status": decision.application_status.value,
            "disposition": decision.disposition.value,
            "control_codes": list(decision.control_codes),
        },
        evidence_ids=evidence_ids,
    )
    if posting is not None:
        _append_audit_event(
            audit_events,
            trial_id=canonical_trial_id,
            action="cash_application.posted_simulated",
            details={
                "application_status": posting.application_status.value,
                "receipt_allocation_status": posting.receipt_allocation_status.value,
                "cash_allocated": _amount(posting.cash_allocated),
                "receipt_residual": _amount(posting.receipt_residual),
            },
            evidence_ids=evidence_ids,
        )

    result_by_invoice = {result.invoice_id: result for result in decision.invoice_results}
    invoice_outcomes: list[dict[str, Any]] = []
    for item in case_input.open_items:
        projection = result_by_invoice.get(item.invoice_id)
        actual = ledger.invoice(item.invoice_id) if posting is not None else item
        invoice_outcomes.append(
            {
                "invoice_id": item.invoice_id,
                "status_before": item.status.value,
                "status_after": actual.status.value,
                "ledger_version_before": item.ledger_version,
                "ledger_version_after": actual.ledger_version,
                "balance_before": _amount(item.open_balance),
                "cash_proposed": _amount(projection.cash_applied if projection else ZERO),
                "cash_posted": _amount(projection.cash_applied if posting and projection else ZERO),
                "policy_adjustment_proposed": _amount(
                    projection.policy_adjustment if projection else ZERO
                ),
                "policy_adjustment_posted": _amount(
                    projection.policy_adjustment if posting and projection else ZERO
                ),
                "projected_balance_after": _amount(
                    projection.balance_after if projection else item.open_balance
                ),
                "balance_after": _amount(actual.open_balance),
            }
        )

    final_application_status = (
        posting.application_status if posting is not None else decision.application_status
    )
    return {
        "schema_version": "cash_application_outcome.v1",
        "trial_id": canonical_trial_id,
        "receipt": {
            "receipt_id": case_input.receipt.receipt_id,
            "source_identity": {
                "source_system": case_input.receipt.source_system,
                "source_transaction_id": case_input.receipt.source_transaction_id,
            },
            "settlement_status": case_input.receipt.settlement_status.value,
            "allocation_status": decision.receipt_allocation_status.value,
            "version_before": case_input.receipt.version,
            "version_after": case_input.receipt.version + (1 if posting else 0),
            "amount": _amount(case_input.receipt.amount),
            "currency": case_input.receipt.currency,
            "residual": _amount(decision.receipt_residual),
        },
        "application": {
            "status": final_application_status.value,
            "pre_post_status": decision.application_status.value,
            "disposition": decision.disposition.value,
            "kind": decision.application_kind.value,
            "residual_kind": decision.residual_kind.value,
            "cash_allocated": _amount(decision.cash_allocated),
            "policy_adjustment": _amount(decision.policy_adjustment_total),
            "posted": posting is not None,
            "posting_mode": decision.posting_mode,
        },
        "invoices": invoice_outcomes,
        "exception": {
            "status": (
                decision.exception_status.value if decision.exception_status is not None else None
            ),
            "control_codes": list(decision.control_codes),
        },
        "review": {
            "status": decision.review_status.value if decision.review_status is not None else None,
        },
        "policy": {
            "references": [
                {
                    "policy_id": reference.policy_id,
                    "version": reference.version,
                    "effective_from": reference.effective_from.isoformat(),
                    "source_sha256": reference.source_sha256,
                }
                for reference in decision.policy_references
            ]
        },
        "audit": {
            "event_count": len(audit_events),
            "chain_valid": _audit_chain_valid(audit_events),
            "events": audit_events,
        },
    }
