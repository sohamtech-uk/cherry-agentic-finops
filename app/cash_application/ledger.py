"""Atomic, idempotent, simulated-only cash-application posting boundary."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from threading import RLock

from app.cash_application.models import (
    SIMULATED_ONLY,
    ZERO,
    ApplicationDecision,
    ApplicationStatus,
    CashReceipt,
    InvoiceStatus,
    OpenARItem,
    ReceiptAllocationStatus,
    ReceiptDirection,
    ReceiptIdentity,
    ReceiptSettlementStatus,
    SimulatedPostingResult,
    money,
    required_identifier,
)


class LedgerInvariantError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SimulatedCashLedger:
    """In-memory store with no production adapter, credentials, or payment operations."""

    def __init__(self, invoices: Iterable[OpenARItem]) -> None:
        invoice_list = tuple(invoices)
        self._invoices = {item.invoice_id: item for item in invoice_list}
        if len(self._invoices) != len(invoice_list):
            raise LedgerInvariantError("invoice.duplicate_record")
        self._receipts: dict[ReceiptIdentity, CashReceipt] = {}
        self._idempotent_results: dict[str, tuple[ApplicationDecision, SimulatedPostingResult]] = {}
        self._lock = RLock()

    @property
    def processed_receipt_identities(self) -> frozenset[ReceiptIdentity]:
        return frozenset(self._receipts)

    def invoice(self, invoice_id: str) -> OpenARItem:
        return self._invoices[invoice_id]

    def receipt(self, identity: ReceiptIdentity) -> CashReceipt:
        return self._receipts[identity]

    def post(
        self,
        decision: ApplicationDecision,
        *,
        idempotency_key: str,
        approved_by: str | None = None,
    ) -> SimulatedPostingResult:
        with self._lock:
            return self._post_locked(
                decision,
                idempotency_key=idempotency_key,
                approved_by=approved_by,
            )

    def _post_locked(
        self,
        decision: ApplicationDecision,
        *,
        idempotency_key: str,
        approved_by: str | None,
    ) -> SimulatedPostingResult:
        """Apply a ready decision atomically to simulated state.

        ``approved_by`` is attribution only. It is intentionally absent from every
        invariant branch, so human approval can never make an invalid post valid.
        """

        key = required_identifier(idempotency_key, field="idempotency_key")
        existing = self._idempotent_results.get(key)
        if existing is not None:
            prior_decision, cached_result = existing
            if prior_decision != decision:
                raise LedgerInvariantError("idempotency.key_conflict")
            return cached_result

        receipt = decision.receipt
        if receipt.identity in self._receipts:
            raise LedgerInvariantError("receipt.duplicate")
        if receipt.settlement_status is not ReceiptSettlementStatus.BOOKED:
            raise LedgerInvariantError("receipt.ineligible_status")
        if receipt.direction is not ReceiptDirection.INBOUND:
            raise LedgerInvariantError("receipt.not_inbound")
        if receipt.allocation_status not in {
            ReceiptAllocationStatus.UNAPPLIED,
            ReceiptAllocationStatus.HELD,
        }:
            raise LedgerInvariantError("receipt.already_allocated")
        if decision.posting_mode != SIMULATED_ONLY:
            raise LedgerInvariantError("posting.production_not_permitted")
        if not decision.is_postable:
            raise LedgerInvariantError("decision.not_postable")
        if decision.receipt_allocation_status not in {
            ReceiptAllocationStatus.APPLIED,
            ReceiptAllocationStatus.PARTIALLY_APPLIED,
        }:
            raise LedgerInvariantError("receipt.invalid_allocation_transition")
        if not decision.invoice_results:
            raise LedgerInvariantError("decision.allocations_required")

        result_ids = [result.invoice_id for result in decision.invoice_results]
        if len(set(result_ids)) != len(result_ids):
            raise LedgerInvariantError("invoice.duplicate_allocation")
        if decision.receipt_residual < ZERO:
            raise LedgerInvariantError("receipt.allocation_exceeds_amount")

        try:
            calculated_cash = sum(
                (
                    money(result.cash_applied, field="cash_applied")
                    for result in decision.invoice_results
                ),
                start=ZERO,
            )
            calculated_adjustment = sum(
                (
                    money(result.policy_adjustment, field="policy_adjustment")
                    for result in decision.invoice_results
                ),
                start=ZERO,
            )
            receipt_residual = money(decision.receipt_residual, field="receipt_residual")
        except (TypeError, ValueError) as exc:
            raise LedgerInvariantError("decision.invalid_money") from exc

        if calculated_cash != decision.cash_allocated:
            raise LedgerInvariantError("decision.cash_total_mismatch")
        if calculated_cash > receipt.amount or receipt_residual < ZERO:
            raise LedgerInvariantError("receipt.allocation_exceeds_amount")
        if calculated_cash + receipt_residual != receipt.amount:
            raise LedgerInvariantError("decision.receipt_not_reconciled")
        if calculated_adjustment != decision.policy_adjustment_total:
            raise LedgerInvariantError("decision.adjustment_total_mismatch")
        if receipt.evidence_ref not in decision.evidence_refs:
            raise LedgerInvariantError("evidence.receipt_missing")

        next_items: dict[str, OpenARItem] = {}
        for result in decision.invoice_results:
            item = self._invoices.get(result.invoice_id)
            if item is None:
                raise LedgerInvariantError("invoice.not_found")
            if item.status is not InvoiceStatus.OPEN:
                raise LedgerInvariantError("invoice.not_open")
            if item.currency != receipt.currency:
                raise LedgerInvariantError("invoice.currency_mismatch")
            if item.ledger_version != result.ledger_version_before:
                raise LedgerInvariantError("invoice.stale_version")
            if item.open_balance != result.balance_before:
                raise LedgerInvariantError("invoice.stale_balance")
            if result.remittance_evidence not in decision.evidence_refs:
                raise LedgerInvariantError("evidence.remittance_missing")
            if (
                result.ar_evidence != item.evidence_ref
                or result.ar_evidence not in decision.evidence_refs
            ):
                raise LedgerInvariantError("evidence.ar_missing")
            reduction = result.cash_applied + result.policy_adjustment
            if reduction > item.open_balance or result.balance_after < ZERO:
                raise LedgerInvariantError("invoice.below_zero")
            if result.balance_after != item.open_balance - reduction:
                raise LedgerInvariantError("invoice.balance_mismatch")
            if result.policy_adjustment > ZERO:
                if result.policy_reference is None:
                    raise LedgerInvariantError("short_pay.policy_reference_missing")
                if result.policy_reference not in decision.policy_references:
                    raise LedgerInvariantError("short_pay.policy_reference_mismatch")
            expected_status = (
                InvoiceStatus.CLOSED if result.balance_after == ZERO else InvoiceStatus.OPEN
            )
            if result.status_after is not expected_status:
                raise LedgerInvariantError("invoice.status_mismatch")
            next_items[item.invoice_id] = replace(
                item,
                open_balance=result.balance_after,
                status=expected_status,
                ledger_version=item.ledger_version + 1,
            )

        # Mutation happens only after all receipt, evidence, arithmetic, and AR checks pass.
        posted_receipt = replace(
            receipt,
            allocation_status=decision.receipt_allocation_status,
            version=receipt.version + 1,
        )
        self._invoices.update(next_items)
        self._receipts[receipt.identity] = posted_receipt
        posting = SimulatedPostingResult(
            receipt_id=receipt.receipt_id,
            receipt_identity=receipt.identity,
            remittance_id=decision.remittance_id,
            idempotency_key=key,
            application_status=ApplicationStatus.POSTED_SIMULATED,
            receipt_allocation_status=decision.receipt_allocation_status,
            invoice_balances=tuple(
                (result.invoice_id, result.balance_after) for result in decision.invoice_results
            ),
            cash_allocated=decision.cash_allocated,
            receipt_residual=decision.receipt_residual,
            policy_adjustment_total=decision.policy_adjustment_total,
            evidence_refs=decision.evidence_refs,
            policy_references=decision.policy_references,
            approved_by=approved_by,
        )
        self._idempotent_results[key] = (decision, posting)
        return posting
