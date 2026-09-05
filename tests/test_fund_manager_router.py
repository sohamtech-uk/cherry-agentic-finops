from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)


def test_fund_manager_health_declares_the_pipeline_stages() -> None:
    response = client.get("/api/fund-manager/health")

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "end_to_end_control_pipeline"
    assert "agent_determines_required_controls" in body["pipeline"]
    assert "agent_determines_required_controls" in body["implemented_stages"]
    assert "agentic_investigation" in body["implemented_stages"]


def test_classify_endpoint_returns_a_source_inventory() -> None:
    positions = json.dumps([{"security_id": "ABC", "quantity": 100}]).encode()

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
    positions = json.dumps([{"security_id": "ABC", "quantity": 100}]).encode()
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


_CURRENT_STATEMENT = b"""Subsequent Events
No subsequent events occurred after 2026-06-30.
"""

_PRIOR_STATEMENT = b"""Subsequent Events
Portfolio Company X completed a transaction on 2026-05-17.
"""


def test_analyse_endpoint_flags_statement_differences() -> None:
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
    assert body["status"] == "review_required"
    assert body["issues_found"] == 1
    assert body["issues"][0]["code"] == "statement.period_text_changed"
    assert all(entry["status"] == "executed" for entry in body["control_plan"])


def test_analyse_endpoint_reports_unimplemented_controls_honestly() -> None:
    positions = json.dumps([{"security_id": "ABC", "quantity": 100}]).encode()

    response = client.post(
        "/api/fund-manager/analyse",
        files=[("files", ("positions.json", positions, "application/json"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["issues"][0]["category"] == "data_quality"
    assert body["control_plan"][0]["status"] == "needs_evidence"


def test_analyse_endpoint_rejects_empty_batch() -> None:
    response = client.post("/api/fund-manager/analyse", files=[])

    assert response.status_code == 422
