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
    assert "Finance operations that" in response.text
