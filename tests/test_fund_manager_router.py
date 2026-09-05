from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import fund_manager_router
from app.api import app
from app.rate_limit import limiter

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_agentic_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_agentic_analysis(
        files: list[tuple[str, bytes, str | None]],
        *,
        fund_name: str | None = None,
        reporting_period: str | None = None,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        del fund_name, reporting_period, as_of_date
        filenames = [filename for filename, _, _ in files]
        if {"prior.txt", "current.txt"}.issubset(filenames):
            return {
                "orchestration_mode": "agentic",
                "agent_name": "fund_manager_control_orchestrator",
                "agent_tool_trace": [
                    "classify_uploaded_evidence",
                    "get_fund_manager_control_catalogue",
                    "compare_periods",
                    "compare_dates",
                ],
                "sources": [
                    {
                        "id": "SRC-01",
                        "filename": "prior.txt",
                        "detected_type": "financial_statement",
                        "status": "processed",
                        "validation_status": "accepted",
                    },
                    {
                        "id": "SRC-02",
                        "filename": "current.txt",
                        "detected_type": "financial_statement",
                        "status": "processed",
                        "validation_status": "accepted",
                    },
                ],
                "status": "review_required",
                "control_plan": [
                    {
                        "control_id": "CTRL-STMT-001",
                        "control": "Period-over-period statement comparison",
                        "filename": "prior.txt, current.txt",
                        "source_ids": ["SRC-01", "SRC-02"],
                        "status": "executed",
                    }
                ],
                "control_runs": [],
                "controls_executed": 1,
                "controls_incomplete": 0,
                "issues_found": 1,
                "critical": 0,
                "material": 1,
                "issues": [
                    {
                        "id": "EXC-001",
                        "category": "statement",
                        "code": "statement.period_text_changed",
                        "title": "Financial statement text changed between periods",
                        "summary": "Statement text changed.",
                        "severity": "warning",
                        "recommended_action": "Review the statement changes.",
                        "evidence": [],
                    }
                ],
                "investigations": [],
                "recommended_human_action": "assign_and_monitor",
            }

        return {
            "orchestration_mode": "agentic",
            "agent_name": "fund_manager_control_orchestrator",
            "agent_tool_trace": [
                "classify_uploaded_evidence",
                "get_fund_manager_control_catalogue",
            ],
            "sources": [
                {
                    "id": "SRC-01",
                    "filename": filenames[0],
                    "detected_type": "positions",
                    "status": "processed",
                    "validation_status": "accepted",
                }
            ],
            "status": "insufficient_evidence",
            "control_plan": [
                {
                    "control_id": "CTRL-POS-001",
                    "control": "Position reconciliation",
                    "filename": filenames[0],
                    "source_ids": ["SRC-01"],
                    "status": "awaiting_evidence",
                    "missing_evidence": ["external positions source"],
                }
            ],
            "control_runs": [],
            "controls_executed": 0,
            "controls_incomplete": 1,
            "issues_found": 1,
            "critical": 0,
            "material": 1,
            "issues": [
                {
                    "id": "EXC-001",
                    "category": "data_quality",
                    "code": "control.ctrl-pos-001.evidence_missing",
                    "title": "Position reconciliation requires another source",
                    "summary": "External positions evidence is missing.",
                    "severity": "warning",
                    "recommended_action": "Upload the comparison source.",
                    "evidence": [],
                }
            ],
            "investigations": [],
            "recommended_human_action": "review_missing_evidence",
        }

    monkeypatch.setattr(fund_manager_router, "run_agentic_analysis", fake_run_agentic_analysis)


def test_fund_manager_health_declares_the_pipeline_stages() -> None:
    response = client.get("/api/fund-manager/health")

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "end_to_end_agentic_control_pipeline"
    assert body["orchestration_mode"] == "agentic"
    assert "agent_calls_file_classification" in body["pipeline"]
    assert "agent_determines_required_controls" in body["implemented_stages"]
    assert "agent_invokes_deterministic_tools" in body["implemented_stages"]
    assert "agentic_investigation" in body["implemented_stages"]


def test_classify_endpoint_returns_a_source_inventory() -> None:
    positions = json.dumps(
        [{"fund": "F1", "security_id": "ABC", "quantity": 100, "price": 10}]
    ).encode()

    response = client.post(
        "/api/fund-manager/classify",
        files=[("files", ("positions.json", positions, "application/json"))],
        data={"fund_name": "Northstar Growth Fund III", "reporting_period": "Q2 2026"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["fund_name"] == "Northstar Growth Fund III"
    assert body["source_count"] == 1
    assert body["unknown_count"] == 0
    assert body["sources"][0]["detected_type"] == "positions"
    assert body["sources"][0]["id"] == "SRC-01"


def test_classify_endpoint_accepts_multiple_mixed_files() -> None:
    positions = json.dumps(
        [{"fund": "F1", "security_id": "ABC", "quantity": 100, "price": 10}]
    ).encode()
    trades = json.dumps([{"trade_id": "T1", "side": "buy"}]).encode()

    response = client.post(
        "/api/fund-manager/classify",
        files=[
            ("files", ("positions.json", positions, "application/json")),
            ("files", ("trades.json", trades, "application/json")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_count"] == 2
    assert {source["detected_type"] for source in body["sources"]} == {"positions", "trades"}


def test_classify_endpoint_rejects_empty_batch() -> None:
    response = client.post("/api/fund-manager/classify", files=[])

    assert response.status_code == 422


def test_classify_endpoint_counts_unknown_sources() -> None:
    response = client.post(
        "/api/fund-manager/classify",
        files=[("files", ("mystery.txt", b"hello", "text/plain"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["unknown_count"] == 1
    assert body["sources"][0]["status"] == "unknown"


def test_classification_agent_rejects_schema_invalid_financial_document() -> None:
    incomplete_positions = json.dumps([{"security_id": "ABC", "quantity": 100}]).encode()

    response = client.post(
        "/api/fund-manager/classify",
        files=[
            (
                "files",
                ("positions.json", incomplete_positions, "application/json"),
            )
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_count"] == 0
    assert body["rejected_count"] == 1
    source = body["sources"][0]
    assert source["detected_type"] == "positions"
    assert source["validation_status"] == "rejected"
    assert source["agent_decision"]["action"] == "reject"
    assert "Schema validation failed" in source["validation_errors"][0]


_CURRENT_STATEMENT = b"""Subsequent Events
No subsequent events occurred after 2026-06-30.
"""

_PRIOR_STATEMENT = b"""Subsequent Events
Portfolio Company X completed a transaction on 2026-05-17.
"""


def test_analyse_endpoint_uses_agentic_orchestration() -> None:
    response = client.post(
        "/api/fund-manager/analyse",
        files=[
            ("files", ("prior.txt", _PRIOR_STATEMENT, "text/plain")),
            ("files", ("current.txt", _CURRENT_STATEMENT, "text/plain")),
        ],
        data={"fund_name": "Northstar Growth Fund III"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["fund_name"] == "Northstar Growth Fund III"
    assert body["orchestration_mode"] == "agentic"
    assert body["agent_name"] == "fund_manager_control_orchestrator"
    assert body["agent_tool_trace"][:2] == [
        "classify_uploaded_evidence",
        "get_fund_manager_control_catalogue",
    ]
    assert body["status"] == "review_required"
    assert body["issues_found"] == 1
    assert body["issues"][0]["code"] == "statement.period_text_changed"
    assert all(entry["status"] == "executed" for entry in body["control_plan"])


def test_analyse_endpoint_reports_missing_pair_from_agent() -> None:
    positions = json.dumps(
        [{"fund": "F1", "security_id": "ABC", "quantity": 100, "price": 10}]
    ).encode()

    response = client.post(
        "/api/fund-manager/analyse",
        files=[("files", ("positions.json", positions, "application/json"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["orchestration_mode"] == "agentic"
    assert body["status"] == "insufficient_evidence"
    assert body["issues"][0]["category"] == "data_quality"
    assert body["control_plan"][0]["status"] == "awaiting_evidence"


def test_analyse_endpoint_rejects_empty_batch() -> None:
    response = client.post("/api/fund-manager/analyse", files=[])

    assert response.status_code == 422


def test_production_fund_manager_uses_server_side_token_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fund_manager_router.settings, "environment", "production")
    monkeypatch.setenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "server-only-token")
    positions = json.dumps([{"security_id": "ABC", "quantity": 100}]).encode()

    response = client.post(
        "/api/fund-manager/analyse",
        files=[("files", ("positions.json", positions, "application/json"))],
    )

    assert response.status_code == 200


def test_production_fund_manager_fails_closed_without_server_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fund_manager_router.settings, "environment", "production")
    monkeypatch.delenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", raising=False)
    positions = json.dumps([{"security_id": "ABC", "quantity": 100}]).encode()

    response = client.post(
        "/api/fund-manager/analyse",
        files=[("files", ("positions.json", positions, "application/json"))],
    )

    assert response.status_code == 503


def test_fund_manager_backend_rate_limit_returns_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fund_manager_router.settings, "environment", "production")
    monkeypatch.setenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "server-only-token")
    monkeypatch.setattr(limiter, "enabled", True)
    limiter._storage.reset()
    positions = json.dumps([{"security_id": "RATE-LIMIT", "quantity": 100}]).encode()

    first = client.post(
        "/api/fund-manager/classify",
        files=[("files", ("positions.json", positions, "application/json"))],
    )
    second = client.post(
        "/api/fund-manager/classify",
        files=[("files", ("positions.json", positions, "application/json"))],
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert "Retry-After" in second.headers
