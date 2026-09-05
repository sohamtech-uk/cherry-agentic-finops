from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)


def test_fund_manager_health_declares_the_pipeline_stages() -> None:
    response = client.get("/api/fund-manager/health")

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "classification"
    assert "agent_determines_required_controls" in body["pipeline"]
    assert body["implemented_stages"] == [
        "multiple_files",
        "file_classification",
        "canonical_data_room",
    ]


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
