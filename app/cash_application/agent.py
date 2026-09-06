from __future__ import annotations

import json
from contextlib import suppress
from typing import Any, Literal, Protocol, cast

import httpx
import neatlogs
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from app.cash_application.review import ControllerReviewPacket, ReviewAction
from app.config import Settings, get_settings


class AgentInvestigationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AgentTraceStep(BaseModel):
    sequence: int = Field(gt=0)
    kind: Literal["MODEL_REQUEST", "TOOL_CALL", "TOOL_RESULT"]
    name: str
    detail: dict[str, Any]


class GroundedClaim(BaseModel):
    claim_id: str
    statement: str
    evidence_ids: list[str]


class AgentInvestigationResult(BaseModel):
    case_id: str
    status: Literal["ADVISORY_READY"] = "ADVISORY_READY"
    provider: Literal["VERCEL_AI_GATEWAY"] = "VERCEL_AI_GATEWAY"
    model: str
    model_response_ids: list[str]
    recommended_action: Literal["create_dispute", "leave_balance_open"]
    recommendation_label: str
    grounded_claims: list[GroundedClaim]
    evidence_ids: list[str]
    trajectory: list[AgentTraceStep]
    deterministic_controls_authoritative: Literal[True] = True
    simulation_only: Literal[True] = True
    production_write_performed: Literal[False] = False
    boundary: str = (
        "Agent advice is read-only. A human decision remains required, and the decision endpoint "
        "re-runs duplicate, settlement, version, currency, allocation, invoice, evidence, "
        "authority "
        "and idempotency controls before simulated state can change."
    )


class ChatCompletionClient(Protocol):
    model: str

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: Literal["required"],
    ) -> dict[str, Any]: ...


class VercelGatewayClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.model = self.settings.cash_agent_model

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: Literal["required"],
    ) -> dict[str, Any]:
        token = self.settings.cash_agent_token
        if token is None:
            raise AgentInvestigationError(
                "AGENT_RUNTIME_UNAVAILABLE",
                "The read-only investigation agent is not configured. Deterministic review "
                "remains available.",
            )
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": 0,
            "max_tokens": 700,
        }
        with neatlogs.trace(
            "vercel_ai_gateway.chat.completions",
            kind="LLM",
            **{"neatlogs.internal": False},
        ) as span:
            span.set_attribute("neatlogs.llm.provider", "vercel_ai_gateway")
            span.set_attribute("neatlogs.llm.model_name", self.model)
            span.set_attribute("input.value", json.dumps(payload, sort_keys=True))
            for index, message in enumerate(messages):
                span.set_attribute(
                    f"neatlogs.llm.input_messages.{index}.role",
                    str(message.get("role", "")),
                )
                span.set_attribute(
                    f"neatlogs.llm.input_messages.{index}.content",
                    json.dumps(message.get("content", ""), sort_keys=True),
                )
            try:
                async with httpx.AsyncClient(
                    timeout=self.settings.cash_agent_timeout_seconds
                ) as client:
                    response = await client.post(
                        "https://ai-gateway.vercel.sh/v1/chat/completions",
                        headers={"Authorization": f"Bearer {token}"},
                        json=payload,
                    )
            except httpx.HTTPError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise AgentInvestigationError(
                    "AGENT_PROVIDER_UNAVAILABLE",
                    "The investigation provider could not be reached; no accounting state changed.",
                ) from exc
            if response.status_code >= 400:
                provider_code = f"HTTP_{response.status_code}"
                with suppress(ValueError):
                    provider_code = response.json().get("error", {}).get("code") or provider_code
                error = AgentInvestigationError(
                    "AGENT_PROVIDER_UNAVAILABLE",
                    f"The investigation provider rejected the request ({provider_code}); "
                    "no accounting state changed.",
                )
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, error.message))
                raise error
            try:
                decoded: Any = response.json()
            except (TypeError, ValueError) as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise AgentInvestigationError(
                    "AGENT_INVALID_RESPONSE",
                    "The investigation provider returned invalid JSON; "
                    "no accounting state changed.",
                ) from exc
            if not isinstance(decoded, dict):
                error = AgentInvestigationError(
                    "AGENT_INVALID_RESPONSE",
                    "The investigation provider returned a non-object response.",
                )
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, error.message))
                raise error
            decoded_dict = cast(dict[str, Any], decoded)
            span.set_attribute("output.value", json.dumps(decoded_dict, sort_keys=True))
            choices = decoded_dict.get("choices") or []
            if choices and isinstance(choices[0], dict):
                output_message = choices[0].get("message")
                span.set_attribute(
                    "neatlogs.llm.output_messages.0.role",
                    (
                        str(output_message.get("role", "assistant"))
                        if isinstance(output_message, dict)
                        else "assistant"
                    ),
                )
                span.set_attribute(
                    "neatlogs.llm.output_messages.0.content",
                    json.dumps(output_message, sort_keys=True),
                )
                if choices[0].get("finish_reason") is not None:
                    span.set_attribute(
                        "neatlogs.llm.finish_reason", str(choices[0]["finish_reason"])
                    )
            usage = decoded_dict.get("usage")
            if isinstance(usage, dict):
                for source, target in (
                    ("prompt_tokens", "prompt"),
                    ("completion_tokens", "completion"),
                    ("total_tokens", "total"),
                ):
                    if isinstance(usage.get(source), int):
                        span.set_attribute(
                            f"neatlogs.llm.token_count.{target}", usage[source]
                        )
        return decoded_dict


def _tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


_INVESTIGATE_TOOL = _tool(
    "investigate_cash_application",
    (
        "Read the authoritative receipt, invoice, policy, evidence and deterministic control "
        "packet for one cash-application exception. This tool is read-only."
    ),
    {
        "type": "object",
        "properties": {"case_id": {"type": "string"}},
        "required": ["case_id"],
        "additionalProperties": False,
    },
)

_SUBMIT_TOOL = _tool(
    "submit_controller_advice",
    (
        "Submit a bounded advisory recommendation using only claim IDs returned by the "
        "investigation tool. This tool never records a decision or changes accounting state."
    ),
    {
        "type": "object",
        "properties": {
            "case_id": {"type": "string"},
            "recommended_action": {
                "type": "string",
                "enum": ["create_dispute", "leave_balance_open"],
            },
            "claim_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 4,
                "uniqueItems": True,
            },
        },
        "required": ["case_id", "recommended_action", "claim_ids"],
        "additionalProperties": False,
    },
)

_SYSTEM_PROMPT = """You are Cherry CFO's read-only cash-application investigation agent.
You do not calculate financial values, infer identities, invent evidence, approve write-offs,
initiate payments, or mutate accounting state. First call investigate_cash_application for the
requested case. Then call submit_controller_advice using only returned facts and claim IDs.
Recommend CREATE_DISPUTE when an evidenced customer deduction claim warrants deductions follow-up;
recommend LEAVE_BALANCE_OPEN when collections should retain the residual without a dispute.
The deterministic control packet is authoritative and a human controller makes the decision."""


def _claims(packet: ControllerReviewPacket) -> dict[str, GroundedClaim]:
    evidence = {item.source_type: item.evidence_id for item in packet.evidence}
    receipt = packet.receipt
    match = packet.customer_invoice_match
    policy = packet.policy
    return {
        "RECEIPT_BOOKED": GroundedClaim(
            claim_id="RECEIPT_BOOKED",
            statement=(
                f"{receipt.receipt_id} is a booked {receipt.currency} "
                f"{receipt.amount:,.2f} receipt with exact source identity "
                f"{receipt.source_system}/{receipt.source_transaction_id}."
            ),
            evidence_ids=[evidence["BANK_FEED"]],
        ),
        "INVOICE_MATCH_LOCATED": GroundedClaim(
            claim_id="INVOICE_MATCH_LOCATED",
            statement=(
                f"Located remittance links customer {match.customer_id} to invoice "
                f"{match.invoice_id}; this is evidence-backed identity, not an inferred customer."
            ),
            evidence_ids=[evidence["REMITTANCE_PDF"], evidence["AR_LEDGER"]],
        ),
        "RESIDUAL_MATERIAL": GroundedClaim(
            claim_id="RESIDUAL_MATERIAL",
            statement=(
                f"Deterministic arithmetic leaves {receipt.currency} {packet.amount_at_risk:,.2f} "
                "open after applying the booked cash."
            ),
            evidence_ids=[evidence["BANK_FEED"], evidence["AR_LEDGER"]],
        ),
        "DEDUCTION_IS_CUSTOMER_CLAIM": GroundedClaim(
            claim_id="DEDUCTION_IS_CUSTOMER_CLAIM",
            statement=(
                f"The located remittance states {match.remittance_raw_reason}; it is recorded as "
                "the customer's claim and is not independently asserted as fact."
            ),
            evidence_ids=[evidence["REMITTANCE_PDF"]],
        ),
        "AUTO_POLICY_STOP": GroundedClaim(
            claim_id="AUTO_POLICY_STOP",
            statement=(
                f"{policy.policy_id} v{policy.version} stops auto-treatment because the residual "
                f"exceeds {policy.max_auto_writeoff_gbp:,.2f} and the reason is not auto-approved."
            ),
            evidence_ids=[evidence["POLICY"]],
        ),
        "CONTROLS_PASS_FOR_REVIEW": GroundedClaim(
            claim_id="CONTROLS_PASS_FOR_REVIEW",
            statement="All non-overridable deterministic controls pass for human review.",
            evidence_ids=[item.evidence_id for item in packet.evidence],
        ),
        "NO_PRE_REVIEW_MUTATION": GroundedClaim(
            claim_id="NO_PRE_REVIEW_MUTATION",
            statement=(
                f"Cash remains {receipt.allocation_status}; applied cash is "
                f"{receipt.currency} {packet.remaining_ar_state.cash_applied:,.2f} and invoice "
                f"{match.invoice_id} remains {receipt.currency} "
                f"{packet.remaining_ar_state.open_balance:,.2f} open before review."
            ),
            evidence_ids=[evidence["BANK_FEED"], evidence["AR_LEDGER"]],
        ),
    }


def _investigation_payload(packet: ControllerReviewPacket) -> dict[str, Any]:
    claims = _claims(packet)
    return {
        "case_id": packet.case_id,
        "receipt_id": packet.receipt.receipt_id,
        "invoice_id": packet.customer_invoice_match.invoice_id,
        "currency": packet.receipt.currency,
        "receipt_amount": str(packet.receipt.amount),
        "invoice_open_balance": str(packet.customer_invoice_match.invoice_open_balance_before),
        "residual": str(packet.amount_at_risk),
        "remittance_claim": packet.customer_invoice_match.remittance_raw_reason,
        "policy": {
            "policy_id": packet.policy.policy_id,
            "version": packet.policy.version,
            "clauses": [item.model_dump(mode="json") for item in packet.policy.clauses],
        },
        "automation_stops": [item.model_dump(mode="json") for item in packet.automation_stopped],
        "deterministic_controls": [
            {"code": item.code, "outcome": item.outcome} for item in packet.control_checks
        ],
        "allowed_advisory_actions": ["create_dispute", "leave_balance_open"],
        "claim_catalog": [claim.model_dump(mode="json") for claim in claims.values()],
        "simulation_only": True,
        "production_write_performed": False,
    }


def _message(response: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    try:
        response_id = str(response["id"])
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AgentInvestigationError(
            "AGENT_INVALID_RESPONSE",
            "The model response did not contain a usable assistant message.",
        ) from exc
    if not isinstance(message, dict):
        raise AgentInvestigationError("AGENT_INVALID_RESPONSE", "Invalid assistant message.")
    return response_id, message


def _single_tool_call(message: dict[str, Any], expected_name: str) -> dict[str, Any]:
    calls = message.get("tool_calls") or []
    if len(calls) != 1 or calls[0].get("function", {}).get("name") != expected_name:
        raise AgentInvestigationError(
            "AGENT_GROUNDING_FAILED",
            f"The agent did not call the required read-only tool {expected_name}.",
        )
    return cast(dict[str, Any], calls[0])


def _arguments(call: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(call["function"]["arguments"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AgentInvestigationError(
            "AGENT_GROUNDING_FAILED", "The agent supplied invalid tool arguments."
        ) from exc
    if not isinstance(value, dict):
        raise AgentInvestigationError(
            "AGENT_GROUNDING_FAILED", "The agent supplied non-object tool arguments."
        )
    return cast(dict[str, Any], value)


class CashApplicationAgent:
    def __init__(self, client: ChatCompletionClient | None = None) -> None:
        self.client = client or VercelGatewayClient()

    @neatlogs.span(kind="WORKFLOW", name="cash-application-investigation")
    async def investigate(self, packet: ControllerReviewPacket) -> AgentInvestigationResult:
        if packet.recorded_decision is not None:
            raise AgentInvestigationError(
                "CASE_ALREADY_DECIDED",
                "Reset the simulated case before requesting fresh agent advice.",
            )
        if packet.control_disposition == "BLOCK" or any(
            check.outcome == "BLOCK" for check in packet.control_checks
        ):
            raise AgentInvestigationError(
                "FUNDAMENTAL_CONTROL_BLOCK",
                "Agent advice is unavailable while a fundamental control is blocked.",
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Investigate {packet.case_id} and prepare grounded controller advice.",
            },
        ]
        trajectory: list[AgentTraceStep] = []
        response_ids: list[str] = []

        first = await self._call(messages, [_INVESTIGATE_TOOL], trajectory)
        first_id, first_message = _message(first)
        response_ids.append(first_id)
        investigate_call = _single_tool_call(first_message, "investigate_cash_application")
        investigate_args = _arguments(investigate_call)
        self._validate_case_id(investigate_args, packet.case_id)
        investigation = _investigation_payload(packet)
        self._record_call(trajectory, investigate_call, investigate_args)
        self._record_result(trajectory, investigate_call, investigation)
        messages.extend(
            [
                first_message,
                {
                    "role": "tool",
                    "tool_call_id": investigate_call["id"],
                    "content": json.dumps(investigation, sort_keys=True),
                },
            ]
        )

        second = await self._call(messages, [_SUBMIT_TOOL], trajectory)
        second_id, second_message = _message(second)
        response_ids.append(second_id)
        submit_call = _single_tool_call(second_message, "submit_controller_advice")
        submit_args = _arguments(submit_call)
        self._record_call(trajectory, submit_call, submit_args)
        action, chosen_claims = self._validate_submission(packet, submit_args)
        submit_result = {
            "accepted": True,
            "advisory_only": True,
            "human_decision_required": True,
            "production_write_performed": False,
        }
        self._record_result(trajectory, submit_call, submit_result)

        evidence_ids = sorted(
            {evidence_id for claim in chosen_claims for evidence_id in claim.evidence_ids}
        )
        recommendation_label = (
            "Create a simulated dispute and preserve GBP 500.00 open for deductions follow-up."
            if action == ReviewAction.CREATE_DISPUTE
            else "Post the held cash in simulation and leave GBP 500.00 open for collections."
        )
        return AgentInvestigationResult(
            case_id=packet.case_id,
            model=self.client.model,
            model_response_ids=response_ids,
            recommended_action=action.value,
            recommendation_label=recommendation_label,
            grounded_claims=chosen_claims,
            evidence_ids=evidence_ids,
            trajectory=trajectory,
        )

    async def _call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        trajectory: list[AgentTraceStep],
    ) -> dict[str, Any]:
        trajectory.append(
            AgentTraceStep(
                sequence=len(trajectory) + 1,
                kind="MODEL_REQUEST",
                name=self.client.model,
                detail={"tool_choice": "required", "tools": [t["function"]["name"] for t in tools]},
            )
        )
        return await self.client.complete(messages=messages, tools=tools, tool_choice="required")

    @staticmethod
    def _record_call(
        trajectory: list[AgentTraceStep], call: dict[str, Any], arguments: dict[str, Any]
    ) -> None:
        trajectory.append(
            AgentTraceStep(
                sequence=len(trajectory) + 1,
                kind="TOOL_CALL",
                name=call["function"]["name"],
                detail={"call_id": call["id"], "arguments": arguments},
            )
        )

    @staticmethod
    def _record_result(
        trajectory: list[AgentTraceStep], call: dict[str, Any], result: dict[str, Any]
    ) -> None:
        trajectory.append(
            AgentTraceStep(
                sequence=len(trajectory) + 1,
                kind="TOOL_RESULT",
                name=call["function"]["name"],
                detail={"call_id": call["id"], "result": result},
            )
        )

    @staticmethod
    def _validate_case_id(arguments: dict[str, Any], expected: str) -> None:
        if arguments.get("case_id") != expected:
            raise AgentInvestigationError(
                "AGENT_GROUNDING_FAILED", "The agent requested a different case identifier."
            )

    @staticmethod
    def _validate_submission(
        packet: ControllerReviewPacket, arguments: dict[str, Any]
    ) -> tuple[ReviewAction, list[GroundedClaim]]:
        CashApplicationAgent._validate_case_id(arguments, packet.case_id)
        action_value = arguments.get("recommended_action")
        if not isinstance(action_value, str):
            raise AgentInvestigationError(
                "AGENT_GROUNDING_FAILED", "The agent recommended an unsupported action."
            )
        try:
            action = ReviewAction(action_value)
        except ValueError as exc:
            raise AgentInvestigationError(
                "AGENT_GROUNDING_FAILED", "The agent recommended an unsupported action."
            ) from exc
        if action not in {ReviewAction.CREATE_DISPUTE, ReviewAction.LEAVE_BALANCE_OPEN}:
            raise AgentInvestigationError(
                "AGENT_GROUNDING_FAILED", "The agent recommendation exceeded its advisory scope."
            )
        available = _claims(packet)
        claim_ids = arguments.get("claim_ids")
        if (
            not isinstance(claim_ids, list)
            or len(claim_ids) < 4
            or len(set(claim_ids)) != len(claim_ids)
        ):
            raise AgentInvestigationError(
                "AGENT_GROUNDING_FAILED", "The recommendation lacks distinct grounded claims."
            )
        if any(
            not isinstance(claim_id, str) or claim_id not in available for claim_id in claim_ids
        ):
            raise AgentInvestigationError(
                "AGENT_GROUNDING_FAILED", "The agent cited a claim that is not in the packet."
            )
        required = {"RESIDUAL_MATERIAL", "AUTO_POLICY_STOP", "NO_PRE_REVIEW_MUTATION"}
        if not required.issubset(claim_ids):
            raise AgentInvestigationError(
                "AGENT_GROUNDING_FAILED",
                "The recommendation omitted residual, policy-stop or unchanged-state grounding.",
            )
        if action == ReviewAction.CREATE_DISPUTE and "DEDUCTION_IS_CUSTOMER_CLAIM" not in claim_ids:
            raise AgentInvestigationError(
                "AGENT_GROUNDING_FAILED",
                "A dispute recommendation must cite the located customer deduction claim.",
            )
        return action, [available[claim_id] for claim_id in claim_ids]
