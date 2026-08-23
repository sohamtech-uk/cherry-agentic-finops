from __future__ import annotations

import io
import json
import zipfile
from hashlib import sha256
from typing import Any

from app.audit import verify_chain
from app.models import WorkflowRecord


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, default=str).encode("utf-8")


def build_evidence_pack(workflow: WorkflowRecord) -> bytes:
    workflow.audit_chain_valid = verify_chain(workflow.audit_events)
    files: dict[str, bytes] = {
        "workflow.json": _json_bytes(workflow.model_dump(mode="json")),
        "document-extraction.json": _json_bytes(workflow.extraction.model_dump(mode="json")),
        "reconciliation-candidates.json": _json_bytes(
            [candidate.model_dump(mode="json") for candidate in workflow.candidates]
        ),
        "risk-decision.json": _json_bytes(
            workflow.decision.model_dump(mode="json") if workflow.decision else {}
        ),
        "audit-trail.json": _json_bytes(
            [event.model_dump(mode="json") for event in workflow.audit_events]
        ),
    }

    manifest = {
        "workflow_id": workflow.workflow_id,
        "status": workflow.status,
        "audit_chain_valid": workflow.audit_chain_valid,
        "files": {
            name: {"sha256": sha256(content).hexdigest(), "bytes": len(content)}
            for name, content in files.items()
        },
        "statement": (
            "This evidence pack records what Cherry Agent observed, which deterministic controls "
            "were applied, and whether human approval was required. It is not an accounting audit "
            "opinion or tax advice."
        ),
    }
    files["manifest.json"] = _json_bytes(manifest)
    files["README.txt"] = (
        "Cherry Agent evidence pack\n"
        "==========================\n\n"
        f"Workflow: {workflow.workflow_id}\n"
        f"Status: {workflow.status}\n"
        f"Audit hash chain valid: {workflow.audit_chain_valid}\n\n"
        "Verify each file against manifest.json and inspect audit-trail.json for the append-only "
        "decision history.\n"
    ).encode()

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()
