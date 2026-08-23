import io
import zipfile

import pytest

from app.audit import verify_chain
from app.config import Settings
from app.models import ApprovalRequest, WorkflowStatus
from app.repository import InMemoryWorkflowRepository
from app.workflow import InvalidWorkflowAction, WorkflowEngine


@pytest.fixture
def engine() -> WorkflowEngine:
    return WorkflowEngine(settings=Settings(), repository=InMemoryWorkflowRepository())


def test_demo_scenarios_show_three_control_paths(engine: WorkflowEngine) -> None:
    autonomous = engine.run_demo("autonomous")
    approval = engine.run_demo("approval")
    exception = engine.run_demo("exception")

    assert autonomous.status == WorkflowStatus.RECONCILED
    assert approval.status == WorkflowStatus.AWAITING_APPROVAL
    assert exception.status == WorkflowStatus.EVIDENCE_REQUIRED
    assert all(verify_chain(item.audit_events) for item in [autonomous, approval, exception])


def test_human_approval_resumes_paused_workflow(engine: WorkflowEngine) -> None:
    workflow = engine.run_demo("approval")
    completed = engine.approve(
        workflow.workflow_id,
        ApprovalRequest(actor="Test Reviewer", note="Invoice and bank evidence reviewed."),
    )

    assert completed.status == WorkflowStatus.RECONCILED
    assert completed.approved_by == "Test Reviewer"
    assert completed.matched_transaction_id == "bank_tx_nds_2048"
    assert verify_chain(completed.audit_events)


def test_cannot_approve_already_reconciled_workflow(engine: WorkflowEngine) -> None:
    workflow = engine.run_demo("autonomous")

    with pytest.raises(InvalidWorkflowAction):
        engine.approve(
            workflow.workflow_id,
            ApprovalRequest(actor="Test Reviewer", note="Should not be necessary."),
        )


def test_evidence_pack_contains_manifest_and_audit(engine: WorkflowEngine) -> None:
    workflow = engine.run_demo("autonomous")
    content, cloud_uri = engine.evidence_pack(workflow.workflow_id)

    assert cloud_uri is None
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "audit-trail.json" in names
        assert "workflow.json" in names
        manifest = archive.read("manifest.json").decode("utf-8")
        assert '"audit_chain_valid": true' in manifest
