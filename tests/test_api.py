from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_autonomous_demo_endpoint() -> None:
    response = client.post("/api/demo/autonomous")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "reconciled"
    assert body["decision"]["action"] == "auto_reconcile"
    assert body["audit_chain_valid"] is True


def test_approval_endpoint() -> None:
    workflow = client.post("/api/demo/approval").json()
    response = client.post(
        f"/api/workflows/{workflow['workflow_id']}/approve",
        json={"actor": "API Reviewer", "note": "Reviewed all evidence."},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "reconciled"


def test_homepage_is_served() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Close capital calls" in response.text


def test_private_markets_demo_surfaces_work_queue() -> None:
    response = client.post("/api/private-markets/demo/exception")
    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["action"] == "request_evidence"
    assert body["analysis"]["outstanding_amount"] == "500.00"
    assert len(body["analysis"]["work_items"]) == 2


def test_awaiting_cash_demo_assigns_investor_operations() -> None:
    body = client.post("/api/private-markets/demo/awaiting-cash").json()

    assert body["analysis"]["action"] == "request_evidence"
    assert body["analysis"]["work_items"][0]["owner"] == "Investor operations"
