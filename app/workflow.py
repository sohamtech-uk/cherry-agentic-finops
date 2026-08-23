from __future__ import annotations

import uuid
from typing import Any

from app.audit import append_event, verify_chain
from app.cloud import EventPublisher, EvidenceStorage
from app.config import Settings
from app.demo_data import SCENARIOS
from app.evidence import build_evidence_pack
from app.matching import rank_candidates
from app.models import (
    ApprovalRequest,
    BankTransaction,
    DocumentExtraction,
    MonthEndSummary,
    RejectionRequest,
    RiskAction,
    WorkflowRecord,
    WorkflowStatus,
    utc_now,
)
from app.repository import WorkflowRepository
from app.risk import decide


class WorkflowNotFound(KeyError):
    pass


class InvalidWorkflowAction(ValueError):
    pass


class WorkflowEngine:
    """Orchestrates a bounded autonomous finance workflow.

    Gemini understands unstructured documents. Deterministic matching and policy code control any
    state-changing action. This separation is deliberate: model output never grants itself financial
    authority.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        repository: WorkflowRepository,
        publisher: EventPublisher | None = None,
        evidence_storage: EvidenceStorage | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.publisher = publisher or EventPublisher(settings)
        self.evidence_storage = evidence_storage or EvidenceStorage(settings)

    def _save(self, workflow: WorkflowRecord, event_type: str) -> WorkflowRecord:
        workflow.updated_at = utc_now()
        workflow.audit_chain_valid = verify_chain(workflow.audit_events)
        self.repository.save(workflow)
        self.publisher.publish(
            event_type,
            {
                "workflow_id": workflow.workflow_id,
                "status": workflow.status,
                "updated_at": workflow.updated_at.isoformat(),
            },
        )
        return workflow

    def process(
        self,
        *,
        extraction: DocumentExtraction,
        transactions: list[BankTransaction],
        source_name: str,
        scenario: str | None = None,
    ) -> WorkflowRecord:
        workflow = WorkflowRecord(
            workflow_id=f"wf_{uuid.uuid4().hex[:12]}",
            source_name=source_name,
            scenario=scenario,
            extraction=extraction,
            transactions=transactions,
        )
        append_event(
            workflow.audit_events,
            actor="system",
            action="workflow.received",
            details={"source_name": source_name, "scenario": scenario},
        )
        workflow.status = WorkflowStatus.EXTRACTED
        append_event(
            workflow.audit_events,
            actor="gemini" if extraction.source == "gemini" else "demo-extractor",
            action="document.extracted",
            details={
                "supplier": extraction.supplier_name,
                "invoice_number": extraction.invoice_number,
                "currency": extraction.currency,
                "total": str(extraction.total),
                "confidence": extraction.confidence,
                "warnings": extraction.warnings,
            },
        )
        append_event(
            workflow.audit_events,
            actor="categorisation-agent",
            action="accounting.category_suggested",
            details={
                "category": extraction.suggested_category,
                "vat_treatment": extraction.vat_treatment,
            },
        )

        workflow.status = WorkflowStatus.MATCHING
        workflow.candidates = rank_candidates(extraction, transactions)
        append_event(
            workflow.audit_events,
            actor="reconciliation-agent",
            action="bank.candidates_ranked",
            details={
                "candidate_count": len(workflow.candidates),
                "top_score": workflow.candidates[0].score if workflow.candidates else None,
                "top_transaction_id": (
                    workflow.candidates[0].transaction.transaction_id
                    if workflow.candidates
                    else None
                ),
            },
        )

        workflow.decision = decide(extraction, workflow.candidates, self.settings)
        append_event(
            workflow.audit_events,
            actor="risk-policy",
            action="control.decision",
            details=workflow.decision.model_dump(mode="json"),
        )

        if workflow.decision.action == RiskAction.AUTO_RECONCILE:
            workflow.status = WorkflowStatus.RECONCILED
            workflow.matched_transaction_id = workflow.decision.selected_transaction_id
            append_event(
                workflow.audit_events,
                actor="cherry-agent",
                action="transaction.auto_reconciled",
                details={
                    "transaction_id": workflow.matched_transaction_id,
                    "bounded_by": workflow.decision.control,
                },
            )
        elif workflow.decision.action == RiskAction.REQUIRE_APPROVAL:
            workflow.status = WorkflowStatus.AWAITING_APPROVAL
            append_event(
                workflow.audit_events,
                actor="cherry-agent",
                action="approval.requested",
                details={"reasons": workflow.decision.reasons},
            )
        else:
            workflow.status = WorkflowStatus.EVIDENCE_REQUIRED
            append_event(
                workflow.audit_events,
                actor="cherry-agent",
                action="evidence.requested",
                details={"reasons": workflow.decision.reasons},
            )

        return self._save(workflow, "workflow.processed")

    def run_demo(self, scenario: str) -> WorkflowRecord:
        factory = SCENARIOS.get(scenario)
        if factory is None:
            raise ValueError(f"Unknown scenario {scenario!r}. Choose: {', '.join(SCENARIOS)}")
        extraction, transactions = factory()
        return self.process(
            extraction=extraction,
            transactions=transactions,
            source_name=f"demo-{scenario}.json",
            scenario=scenario,
        )

    def get(self, workflow_id: str) -> WorkflowRecord:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            raise WorkflowNotFound(workflow_id)
        workflow.audit_chain_valid = verify_chain(workflow.audit_events)
        return workflow

    def list(self) -> list[WorkflowRecord]:
        return self.repository.list()

    def approve(self, workflow_id: str, request: ApprovalRequest) -> WorkflowRecord:
        workflow = self.get(workflow_id)
        if workflow.status != WorkflowStatus.AWAITING_APPROVAL:
            raise InvalidWorkflowAction(
                f"Workflow {workflow_id} is {workflow.status}; only awaiting-approval workflows "
                "can be approved."
            )
        if not workflow.decision or not workflow.decision.selected_transaction_id:
            raise InvalidWorkflowAction("The workflow has no selected bank transaction.")

        workflow.approved_by = request.actor
        workflow.approval_note = request.note
        workflow.matched_transaction_id = workflow.decision.selected_transaction_id
        workflow.status = WorkflowStatus.RECONCILED
        append_event(
            workflow.audit_events,
            actor=request.actor,
            action="approval.granted",
            details={"note": request.note},
        )
        append_event(
            workflow.audit_events,
            actor="cherry-agent",
            action="transaction.reconciled_after_approval",
            details={"transaction_id": workflow.matched_transaction_id},
        )
        return self._save(workflow, "workflow.approved")

    def reject(self, workflow_id: str, request: RejectionRequest) -> WorkflowRecord:
        workflow = self.get(workflow_id)
        if workflow.status not in {
            WorkflowStatus.AWAITING_APPROVAL,
            WorkflowStatus.EVIDENCE_REQUIRED,
        }:
            raise InvalidWorkflowAction(
                f"Workflow {workflow_id} cannot be rejected from state {workflow.status}."
            )
        workflow.status = WorkflowStatus.REJECTED
        append_event(
            workflow.audit_events,
            actor=request.actor,
            action="workflow.rejected",
            details={"note": request.note},
        )
        return self._save(workflow, "workflow.rejected")

    def evidence_pack(self, workflow_id: str) -> tuple[bytes, str | None]:
        workflow = self.get(workflow_id)
        if not workflow.audit_chain_valid:
            raise InvalidWorkflowAction(
                "Evidence export was blocked because the audit hash chain failed verification."
            )
        content = build_evidence_pack(workflow)
        uri = self.evidence_storage.upload(
            f"workflows/{workflow_id}/evidence.zip", content, "application/zip"
        )
        return content, uri

    def month_end_summary(self) -> MonthEndSummary:
        workflows = self.list()
        counts: dict[WorkflowStatus, int] = {status: 0 for status in WorkflowStatus}
        for workflow in workflows:
            counts[workflow.status] += 1
        return MonthEndSummary(
            total_workflows=len(workflows),
            reconciled=counts[WorkflowStatus.RECONCILED],
            awaiting_approval=counts[WorkflowStatus.AWAITING_APPROVAL],
            evidence_required=counts[WorkflowStatus.EVIDENCE_REQUIRED],
            rejected=counts[WorkflowStatus.REJECTED],
            estimated_minutes_saved=counts[WorkflowStatus.RECONCILED] * 8,
        )

    def public_summary(self, workflow_id: str) -> dict[str, Any]:
        workflow = self.get(workflow_id)
        return {
            "workflow_id": workflow.workflow_id,
            "status": workflow.status,
            "supplier": workflow.extraction.supplier_name,
            "total": str(workflow.extraction.total),
            "currency": workflow.extraction.currency,
            "decision": workflow.decision.model_dump(mode="json") if workflow.decision else None,
            "audit_chain_valid": workflow.audit_chain_valid,
        }
