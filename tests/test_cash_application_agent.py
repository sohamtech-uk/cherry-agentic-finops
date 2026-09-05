from __future__ import annotations

from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.cash_application.agent import (
    AgentInvestigationError,
    CashApplicationAgent,
)
from app.cash_application.review import build_short_pay_packet
from app.cash_application.router import get_controller_review_service


class FakeGatewayClient:
    model = "fake/grounded-tool-model"

    def __init__(self, *, invented_claim: bool = False) -> None:
        self.calls = 0
        self.invented_claim = invented_claim

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: Literal["required"],
    ) -> dict[str, Any]:
        del messages
        assert tool_choice == "required"
        self.calls += 1
        name = tools[0]["function"]["name"]
        if name == "investigate_cash_application":
            arguments = '{"case_id":"CA-05-RCPT-1042-500"}'
        else:
            claim_ids = [
                "RECEIPT_BOOKED",
                "RESIDUAL_MATERIAL",
                "DEDUCTION_IS_CUSTOMER_CLAIM",
                "AUTO_POLICY_STOP",
                "NO_PRE_REVIEW_MUTATION",
            ]
            if self.invented_claim:
                claim_ids.append("CUSTOMER_CONFIRMED_DAMAGE")
            arguments = (
                '{"case_id":"CA-05-RCPT-1042-500",'
                '"recommended_action":"create_dispute",'
                f'"claim_ids":{claim_ids!r}'
                "}"
            ).replace("'", '"')
        return {
            "id": f"fake-response-{self.calls}",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"fake-call-{self.calls}",
                                "type": "function",
                                "function": {"name": name, "arguments": arguments},
                            }
                        ],
                    }
                }
            ],
        }


@pytest.mark.asyncio
async def test_agent_uses_real_model_tool_calls_but_returns_only_validated_packet_claims() -> None:
    packet = build_short_pay_packet()
    before = packet.model_dump(mode="json")
    fake = FakeGatewayClient()

    result = await CashApplicationAgent(fake).investigate(packet)

    assert fake.calls == 2
    assert result.status == "ADVISORY_READY"
    assert result.model == "fake/grounded-tool-model"
    assert result.model_response_ids == ["fake-response-1", "fake-response-2"]
    assert result.recommended_action == "create_dispute"
    assert [step.kind for step in result.trajectory] == [
        "MODEL_REQUEST",
        "TOOL_CALL",
        "TOOL_RESULT",
        "MODEL_REQUEST",
        "TOOL_CALL",
        "TOOL_RESULT",
    ]
    assert [step.name for step in result.trajectory if step.kind == "TOOL_CALL"] == [
        "investigate_cash_application",
        "submit_controller_advice",
    ]
    assert {claim.claim_id for claim in result.grounded_claims} == {
        "RECEIPT_BOOKED",
        "RESIDUAL_MATERIAL",
        "DEDUCTION_IS_CUSTOMER_CLAIM",
        "AUTO_POLICY_STOP",
        "NO_PRE_REVIEW_MUTATION",
    }
    assert set(result.evidence_ids) == {
        "EV-AR-2208",
        "EV-BANK-1042",
        "EV-POLICY-SP01-V3",
        "EV-REMIT-1042",
    }
    assert result.production_write_performed is False
    assert packet.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_agent_fails_closed_when_model_invents_a_claim() -> None:
    packet = build_short_pay_packet()
    before = packet.model_dump(mode="json")

    with pytest.raises(AgentInvestigationError, match="not in the packet") as raised:
        await CashApplicationAgent(FakeGatewayClient(invented_claim=True)).investigate(packet)

    assert raised.value.code == "AGENT_GROUNDING_FAILED"
    assert packet.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_agent_never_runs_when_a_fundamental_control_is_blocked() -> None:
    packet = build_short_pay_packet()
    packet.receipt.duplicate_detected = True
    packet.control_disposition = "BLOCK"
    fake = FakeGatewayClient()

    with pytest.raises(AgentInvestigationError, match="fundamental control") as raised:
        await CashApplicationAgent(fake).investigate(packet)

    assert raised.value.code == "FUNDAMENTAL_CONTROL_BLOCK"
    assert fake.calls == 0


def test_agent_investigation_endpoint_exposes_advice_and_actual_trajectory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.cash_application import router

    get_controller_review_service().reset_demo()
    monkeypatch.setattr(
        router,
        "get_cash_application_agent",
        lambda: CashApplicationAgent(FakeGatewayClient()),
    )
    response = TestClient(app).post(
        "/api/controller-review/cases/CA-05-RCPT-1042-500/agent-investigation"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "VERCEL_AI_GATEWAY"
    assert body["recommended_action"] == "create_dispute"
    assert body["deterministic_controls_authoritative"] is True
    assert body["simulation_only"] is True
    assert body["production_write_performed"] is False
    assert [step["kind"] for step in body["trajectory"]].count("TOOL_CALL") == 2
    packet = get_controller_review_service().get_packet("CA-05-RCPT-1042-500")
    assert packet.recorded_decision is None
    assert str(packet.remaining_ar_state.cash_applied) == "0.00"
