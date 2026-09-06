from fastapi.testclient import TestClient

from app import fund_manager_router
from app.api import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_private_markets_health_reports_upload_token_configuration(monkeypatch) -> None:
    monkeypatch.setenv("CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN", "configured-demo-token")

    response = client.get("/api/private-markets/health")

    assert response.status_code == 200
    assert response.json()["upload_token_configured"] is True


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
    assert "Clear uploaded data &amp; memory" in response.text
    assert "Contract Agent" in response.text
    assert "SYNTHETIC HACKATHON DEMO — NOT A REAL CONTRACT" in response.text
    assert "Run side-letter demo" in response.text


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


def test_unhandled_exception_returns_a_clean_json_500(monkeypatch) -> None:
    """A route that lets a truly unexpected exception through must still get a well-formed JSON
    error response, not Starlette's bare-text 500, so the frontend can render it.

    Uses a dedicated client with raise_server_exceptions=False: Starlette's ServerErrorMiddleware
    always sends the handler's response *and* re-raises the original exception afterward (so
    servers can log it) -- TestClient surfaces that re-raise by default for debugging, which would
    otherwise hide the very response this test needs to inspect.
    """

    def boom(files):
        raise Exception("simulated unexpected internal failure")

    monkeypatch.setattr(fund_manager_router, "classify_and_validate_sources", boom)

    permissive_client = TestClient(app, raise_server_exceptions=False)
    response = permissive_client.post(
        "/api/fund-manager/classify",
        files=[("files", ("positions.json", b"[]", "application/json"))],
    )

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "An unexpected error occurred. Please try again."
    assert "simulated unexpected internal failure" not in response.text


def test_clear_memory_endpoint_removes_ephemeral_workflows() -> None:
    client.post("/api/session/clear-memory")
    workflow = client.post("/api/demo/autonomous").json()
    contract_upload = client.post(
        "/api/contracts/documents",
        files={
            "files": (
                "fund-lpa.txt",
                b"Effective as of 1 January 2025\nSection 1.1 Fund Term\nThe term is ten years.",
                "text/plain",
            )
        },
        data={"document_type": "lpa", "fund_name": "Cedar Peak Fund"},
    ).json()
    assert workflow["workflow_id"]
    assert contract_upload["count"] == 1
    assert client.get("/api/workflows").json()

    response = client.post("/api/session/clear-memory")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cleared"
    assert body["persistence_backend"] == "memory"
    assert body["cleared_workflow_records"] >= 1
    assert body["cleared_contract_documents"] == 1
    assert body["raw_uploads_retained"] is False
    assert client.get("/api/workflows").json() == []
