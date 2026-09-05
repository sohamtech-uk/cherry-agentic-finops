from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)

_CURRENT_STATEMENT = b"""Notes to Financial Statements

Portfolio Company Investments
Portfolio Company X remains a controlled investment as of 2026-06-30.

Subsequent Events
No subsequent events occurred after 2026-06-30.
"""

_PRIOR_STATEMENT = b"""Notes to Financial Statements

Portfolio Company Investments
Portfolio Company X remains a controlled investment as of 2026-03-31.

Subsequent Events
Portfolio Company X completed a transaction on 2026-05-17.
"""


def test_statement_review_health_declares_the_contract() -> None:
    response = client.get("/api/statement-review/health")

    assert response.status_code == 200
    body = response.json()
    assert body["input_required"] == {
        "current_document": True,
        "prior_document": False,
        "section_heading": False,
        "entity_name": False,
    }
    assert "compare_periods" in body["checks"]


def test_compare_endpoint_accepts_current_document_only() -> None:
    response = client.post(
        "/api/statement-review/compare",
        files={"current_document": ("current.txt", _CURRENT_STATEMENT, "text/plain")},
        data={"section_heading": "Subsequent Events", "entity_name": "Portfolio Company X"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["current_document"]["document"] == "current.txt"
    assert body["section"]["found"] is True
    assert body["entity"]["occurrences"] == 1
    assert "period_diff" not in body
    assert body["evidence"]["sources"][0]["kind"] == "current_document"


def test_compare_endpoint_diffs_current_and_prior() -> None:
    response = client.post(
        "/api/statement-review/compare",
        files={
            "current_document": ("current.txt", _CURRENT_STATEMENT, "text/plain"),
            "prior_document": ("prior.txt", _PRIOR_STATEMENT, "text/plain"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["period_diff"]["identical"] is False
    assert "2026-05-17" in body["date_diff"]["dates_only_in_prior"]
    assert len(body["evidence"]["sources"]) == 2


def test_compare_endpoint_rejects_unsupported_format() -> None:
    response = client.post(
        "/api/statement-review/compare",
        files={"current_document": ("current.docx", b"binary", "application/octet-stream")},
    )

    assert response.status_code == 415
