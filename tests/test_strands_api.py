from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agents.cherry_strands.agent import agent_metadata
from app.api import app

client = TestClient(app)


def test_health_safe_metadata(monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-sentinel")
    response = client.get("/api/strands/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", **agent_metadata()}
    assert "secret-sentinel" not in response.text
    assert "no payment initiation" in response.json()["financial_boundary"]


def test_invoke():
    result = {"response": "Human approval required", **agent_metadata()}
    with patch("agents.cherry_strands.invoke_cherry_agent", return_value=result) as invoke:
        response = client.post("/api/strands/invoke", json={"prompt": " synthetic approval "})
    assert response.status_code == 200
    assert response.json() == result
    invoke.assert_called_once_with("synthetic approval")


@pytest.mark.parametrize(
    "payload", [{}, {"prompt": ""}, {"prompt": "  "}, {"prompt": "x" * 8001}, {"prompt": 123}]
)
def test_invalid_prompt(payload):
    with patch("agents.cherry_strands.invoke_cherry_agent") as invoke:
        assert client.post("/api/strands/invoke", json=payload).status_code == 422
        invoke.assert_not_called()


def test_exception_is_sanitized():
    with patch(
        "agents.cherry_strands.invoke_cherry_agent", side_effect=RuntimeError("secret-token")
    ):
        response = client.post("/api/strands/invoke", json={"prompt": "synthetic"})
    assert response.status_code == 503
    assert "secret-token" not in response.text
    assert response.json() == {"detail": "Agent invocation unavailable."}
