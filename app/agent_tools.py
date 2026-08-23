from __future__ import annotations

from typing import Any, Literal

from app.container import get_engine
from app.models import ApprovalRequest, RejectionRequest


def run_finance_scenario(
    scenario: Literal["autonomous", "approval", "exception"] = "autonomous",
) -> dict[str, Any]:
    """Run one safe synthetic finance workflow and return its governed outcome.

    Args:
        scenario: autonomous for a low-risk exact match, approval for a high-value exact match,
            or exception for a material amount mismatch.
    """

    workflow = get_engine().run_demo(scenario)
    return workflow.model_dump(mode="json")


def inspect_workflow(workflow_id: str) -> dict[str, Any]:
    """Retrieve a workflow, its reconciliation evidence, control decision and audit events."""

    return get_engine().get(workflow_id).model_dump(mode="json")


def list_open_finance_exceptions() -> dict[str, Any]:
    """Return the current month-end queue and productivity summary."""

    engine = get_engine()
    open_items = [
        workflow.model_dump(mode="json")
        for workflow in engine.list()
        if workflow.status in {"awaiting_approval", "evidence_required"}
    ]
    return {
        "summary": engine.month_end_summary().model_dump(mode="json"),
        "open_items": open_items,
    }


def record_human_approval(workflow_id: str, approver_name: str, note: str) -> dict[str, Any]:
    """Record an explicit human approval and resume a paused workflow.

    Only call this tool after the user explicitly asks to approve the named workflow and supplies
    the approver name. Never infer consent from context.
    """

    return get_engine().approve(
        workflow_id, ApprovalRequest(actor=approver_name, note=note)
    ).model_dump(mode="json")


def reject_workflow(workflow_id: str, reviewer_name: str, reason: str) -> dict[str, Any]:
    """Reject a paused workflow after the user explicitly instructs you to do so."""

    return get_engine().reject(
        workflow_id, RejectionRequest(actor=reviewer_name, note=reason)
    ).model_dump(mode="json")
