from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import fund_manager_router
from app.api import app
from app.fund_manager_cases import FundManagerCaseStorageError, case_store
from app.rate_limit import limiter

client = TestClient(app)


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def mock_agentic_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    case_store.clear()

    async def fake_plan_case_controls(
        classification: dict[str, Any],
        *,
        fund_name: str | None = None,
        reporting_period: str | None = None,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        del fund_name, reporting_period, as_of_date
        source = classification["sources"][0]
        return {
            "stage": "planned",
            "orchestration_mode": "agentic",
            "agent_name": "fund_manager_control_planner",
            "agent_tool_trace": ["get_fund_manager_control_catalogue"],
            "status": "ready",
            "control_plan": [
                {
                    "control_id": "CTRL-POS-001",
                    "control": "Position reconciliation",
                    "source_ids": [source["id"]],
                    "status": "ready",
                    "reasoning": "Accepted evidence supports this control.",
                    "missing_evidence": [],
                    "tool_name": "reconcile_positions",
                }
            ],
            "agent_summary": "One control is ready. No control has run yet.",
        }

    async def fake_execute_case_controls(
        files: list[tuple[str, bytes, str | None]],
        classification: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        del files, classification
        assert plan["control_plan"][0]["status"] == "ready"
        return {
            "stage": "executed",
            "orchestration_mode": "agentic",
            "agent_name": "fund_manager_control_executor",
            "agent_tool_trace": ["reconcile_positions"],
            "status": "review_required",
            "control_plan": [
                {
                    **plan["control_plan"][0],
                    "status": "executed",
                }
            ],
            "control_runs": [
                {
                    "control_id": "CTRL-POS-001",
                    "tool_name": "reconcile_positions",
                    "status": "completed",
                    "source_ids": ["SRC-01"],
                    "output": {"matched_count": 0, "break_count": 1},
                }
            ],
            "issues": [
                {
                    "id": "EXC-001",
                    "category": "position",
                    "code": "position.mismatch",
                    "title": "Position mismatch",
                    "summary": "Position quantities differ.",
                    "severity": "warning",
                    "recommended_action": "Review the break.",
                    "evidence": [],
                }
            ],
            "issues_found": 1,
            "material": 1,
            "critical": 0,
            "agent_summary": "The approved control executed and returned one break.",
        }

    async def fake_investigate_case_execution(execution: dict[str, Any]) -> dict[str, Any]:
        assert execution["issues"][0]["code"] == "position.mismatch"
        return {
            "stage": "investigated",
            "orchestration_mode": "agentic",
            "agent_name": "fund_manager_exception_investigator",
            "agent_tool_trace": [],
            "status": "review_required",
            "investigations": [
                {
                    "issue_id": "EXC-001",
                    "finding": "A position break requires review.",
                    "likely_cause": "Different source quantities.",
                    "evidence_gap": "Confirm the authoritative source.",
                    "priority": "medium",
                    "recommended_action": "Assign for review.",
                }
            ],
            "recommended_human_action": "assign_and_monitor",
            "agent_summary": "The deterministic break was investigated without changing it.",
        }

    async def fake_run_agentic_analysis(
        files: list[tuple[str, bytes, str | None]],
        *,
        fund_name: str | None = None,
        reporting_period: str | None = None,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        del files, fund_name, reporting_period, as_of_date
        return {
            "orchestration_mode": "agentic",
            "agent_name": "fund_manager_control_orchestrator",
            "agent_tool_trace": [],
            "sources": [],
            "status": "clean",
            "control_plan": [],
            "control_runs": [],
            "issues": [],
            "issues_found": 0,
            "material": 0,
            "critical": 0,
        }

    monkeypatch.setattr(fund_manager_router, "plan_case_controls", fake_plan_case_controls)
    monkeypatch.setattr(fund_manager_router, "execute_case_controls", fake_execute_case_controls)
    monkeypatch.setattr(
        fund_manager_router,
        "investigate_case_execution",
        fake_investigate_case_execution,
    )
    monkeypatch.setattr(fund_manager_router, "run_agentic_analysis", fake_run_agentic_analysis)


def _positions() -> bytes:
    return json.dumps([{"fund": "F1", "security_id": "ABC", "quantity": 100, "price": 10}]).encode()


def _create_case() -> dict[str, Any]:
    response = client.post(
        "/api/fund-manager/cases",
        files=[("files", ("positions.json", _positions(), "application/json"))],
        data={"fund_name": "Northstar Growth Fund III"},
    )
    assert response.status_code == 200
    return response.json()


def test_health_declares_staged_agentic_pipeline() -> None:
    response = client.get("/api/fund-manager/health")
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "staged_agentic_control_pipeline"
    assert body["orchestration_mode"] == "agentic"
    assert "human_approves_control_execution" in body["pipeline"]
    assert "human_decision_recording" in body["implemented_stages"]
    assert body["case_storage"] == case_store.backend_name


def test_case_creation_classifies_only_and_returns_case_id() -> None:
    body = _create_case()
    assert body["case_id"].startswith("FM-")
    assert body["stage"] == "classified"
    assert body["classification"]["accepted_count"] == 1
    assert body["plan"] is None
    assert body["execution"] is None


def test_case_plan_requires_explicit_follow_up() -> None:
    case = _create_case()
    response = client.post(f"/api/fund-manager/cases/{case['case_id']}/plan")
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "planned"
    assert body["plan"]["agent_name"] == "fund_manager_control_planner"
    assert body["plan"]["control_plan"][0]["status"] == "ready"
    assert body["execution"] is None


def test_execute_cannot_run_before_plan() -> None:
    case = _create_case()
    response = client.post(f"/api/fund-manager/cases/{case['case_id']}/execute")
    assert response.status_code == 409


def test_execute_runs_only_after_planning() -> None:
    case = _create_case()
    client.post(f"/api/fund-manager/cases/{case['case_id']}/plan")
    response = client.post(f"/api/fund-manager/cases/{case['case_id']}/execute")
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "executed"
    assert body["execution"]["agent_name"] == "fund_manager_control_executor"
    assert body["execution"]["issues_found"] == 1


def test_investigation_happens_after_deterministic_execution() -> None:
    case = _create_case()
    client.post(f"/api/fund-manager/cases/{case['case_id']}/plan")
    client.post(f"/api/fund-manager/cases/{case['case_id']}/execute")
    response = client.post(f"/api/fund-manager/cases/{case['case_id']}/investigate")
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "investigated"
    assert body["investigation"]["recommended_human_action"] == "assign_and_monitor"


def test_human_decision_is_recorded_explicitly() -> None:
    case = _create_case()
    client.post(f"/api/fund-manager/cases/{case['case_id']}/plan")
    client.post(f"/api/fund-manager/cases/{case['case_id']}/execute")
    response = client.post(
        f"/api/fund-manager/cases/{case['case_id']}/decision",
        json={"action": "request_evidence", "note": "Need custodian positions."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "decided"
    assert body["decision"]["action"] == "request_evidence"
    assert body["decision"]["note"] == "Need custodian positions."


def test_get_case_never_returns_uploaded_bytes() -> None:
    case = _create_case()
    response = client.get(f"/api/fund-manager/cases/{case['case_id']}")
    assert response.status_code == 200
    body = response.json()
    assert "files" not in body
    assert body["classification"]["sources"][0]["filename"] == "positions.json"


def test_case_storage_failure_is_not_reported_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_load(_: str) -> None:
        raise FundManagerCaseStorageError("database unavailable")

    monkeypatch.setattr(case_store, "get", fail_to_load)
    response = client.get("/api/fund-manager/cases/FM-UNAVAILABLE")

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_classify_compatibility_endpoint_still_works() -> None:
    response = client.post(
        "/api/fund-manager/classify",
        files=[("files", ("positions.json", _positions(), "application/json"))],
    )
    assert response.status_code == 200
    assert response.json()["sources"][0]["detected_type"] == "positions"


def test_classify_endpoint_decompresses_a_zip_of_evidence_files() -> None:
    trades = json.dumps([{"trade_id": "T1", "side": "buy"}]).encode()
    archive = _zip_bytes(
        {
            "positions.json": _positions(),
            "trades.json": trades,
            "__MACOSX/._positions.json": b"junk",
            "notes/": b"",
        }
    )

    response = client.post(
        "/api/fund-manager/classify",
        files=[("files", ("evidence.zip", archive, "application/zip"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_count"] == 2
    assert {source["filename"] for source in body["sources"]} == {"positions.json", "trades.json"}
    assert {source["detected_type"] for source in body["sources"]} == {"positions", "trades"}


def test_classify_endpoint_accepts_a_zip_alongside_a_plain_file_in_one_batch() -> None:
    trades = json.dumps([{"trade_id": "T1", "side": "buy"}]).encode()
    archive = _zip_bytes({"trades.json": trades})

    response = client.post(
        "/api/fund-manager/classify",
        files=[
            ("files", ("positions.json", _positions(), "application/json")),
            ("files", ("evidence.zip", archive, "application/zip")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_count"] == 2
    assert {source["filename"] for source in body["sources"]} == {"positions.json", "trades.json"}
    assert {source["detected_type"] for source in body["sources"]} == {"positions", "trades"}


def test_case_creation_accepts_a_zip_of_evidence_files() -> None:
    archive = _zip_bytes({"positions.json": _positions()})

    response = client.post(
        "/api/fund-manager/cases",
        files=[("files", ("evidence.zip", archive, "application/zip"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["classification"]["sources"][0]["filename"] == "positions.json"
    assert body["classification"]["sources"][0]["detected_type"] == "positions"


def test_classify_endpoint_rejects_a_corrupt_zip() -> None:
    response = client.post(
        "/api/fund-manager/classify",
        files=[("files", ("evidence.zip", b"not-a-zip", "application/zip"))],
    )

    assert response.status_code == 422


def test_classify_endpoint_rejects_a_zip_with_too_many_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fund_manager_router, "MAX_FILES", 2)
    archive = _zip_bytes({f"file-{i}.json": b"[]" for i in range(3)})

    response = client.post(
        "/api/fund-manager/classify",
        files=[("files", ("evidence.zip", archive, "application/zip"))],
    )

    assert response.status_code == 413


def test_analyse_compatibility_endpoint_still_uses_agentic_flow() -> None:
    response = client.post(
        "/api/fund-manager/analyse",
        files=[("files", ("positions.json", _positions(), "application/json"))],
    )
    assert response.status_code == 200
    assert response.json()["orchestration_mode"] == "agentic"


def test_production_case_creation_fails_closed_without_server_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fund_manager_router.settings, "environment", "production")
    monkeypatch.delenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", raising=False)
    response = client.post(
        "/api/fund-manager/cases",
        files=[("files", ("positions.json", _positions(), "application/json"))],
    )
    assert response.status_code == 503


def test_fund_manager_backend_rate_limit_returns_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fund_manager_router.settings, "environment", "production")
    monkeypatch.setenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "server-only-token")
    monkeypatch.setattr(limiter, "enabled", True)
    limiter._storage.reset()
    first = client.post(
        "/api/fund-manager/classify",
        files=[("files", ("positions.json", _positions(), "application/json"))],
    )
    second = client.post(
        "/api/fund-manager/classify",
        files=[("files", ("positions.json", _positions(), "application/json"))],
    )
    assert first.status_code == 200
    assert second.status_code == 429
