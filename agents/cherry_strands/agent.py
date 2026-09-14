from __future__ import annotations

import os
from typing import Any, Literal, cast

from strands import Agent, tool
from strands.models import BedrockModel

from app.agent_tools import inspect_workflow, list_open_finance_exceptions, run_finance_scenario

# Use the EU inference profile by default because the hackathon deployment targets London (eu-west-2).
# Override STRANDS_BEDROCK_MODEL_ID if the AWS account uses another Bedrock model/profile.
DEFAULT_MODEL_ID = "eu.anthropic.claude-sonnet-4-6"
DEFAULT_AWS_REGION = "eu-west-2"


def _model() -> BedrockModel:
    """Build the Bedrock model used by every Strands agent in one invocation."""

    return BedrockModel(
        model_id=os.getenv("STRANDS_BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
        region_name=os.getenv("AWS_REGION", DEFAULT_AWS_REGION),
        temperature=0.1,
    )


@tool
def run_sme_finance_scenario(scenario: str = "autonomous") -> dict[str, Any]:
    """Run a safe synthetic SME finance workflow.

    Args:
        scenario: One of autonomous, approval, or exception.

    Returns:
        The deterministic Cherry workflow result, including its control decision and audit evidence.
    """

    allowed = {"autonomous", "approval", "exception"}
    if scenario not in allowed:
        return {
            "error": "invalid_scenario",
            "allowed": sorted(allowed),
            "message": "Choose autonomous, approval, or exception.",
        }
    typed = cast(Literal["autonomous", "approval", "exception"], scenario)
    return run_finance_scenario(typed)


@tool
def inspect_finance_workflow(workflow_id: str) -> dict[str, Any]:
    """Inspect one Cherry workflow and return reconciliation evidence, controls and audit events."""

    return inspect_workflow(workflow_id)


@tool
def get_open_finance_exceptions() -> dict[str, Any]:
    """Return the current month-end exception queue and productivity summary."""

    return list_open_finance_exceptions()


def build_cherry_agent() -> Agent:
    """Build the Agents-for-Humans Strands hierarchy.

    The orchestrator delegates to specialist Strands agents. The specialists can only call bounded
    finance tools; deterministic Cherry controls remain authoritative for financial decisions.
    Human approval is deliberately outside the model tool surface and continues through the existing
    approval API/UI, so the agent cannot invent consent.
    """

    model = _model()

    workflow_specialist = Agent(
        name="workflow_specialist",
        description=(
            "Runs and explains Cherry's bounded SME finance workflows: document/bank matching, "
            "reconciliation outcomes and deterministic policy decisions."
        ),
        model=model,
        system_prompt=(
            "You are Cherry Agent's workflow specialist. Use tools for every workflow fact. "
            "Never fabricate transactions, totals, matches or approvals. For a demonstration, call "
            "run_sme_finance_scenario. If a workflow needs human approval, report that state and stop; "
            "do not claim the approval happened. Cherry performs accounting reconciliation only and "
            "does not initiate payments."
        ),
        tools=[run_sme_finance_scenario, inspect_finance_workflow],
    )

    control_specialist = Agent(
        name="control_specialist",
        description=(
            "Explains why deterministic finance controls allowed automation or required a human."
        ),
        model=model,
        system_prompt=(
            "You are Cherry Agent's finance-control specialist. Inspect the workflow before explaining "
            "a control decision. Distinguish agent orchestration from deterministic controls. Never "
            "invent consent, never approve a workflow, and never recommend bypassing a failed control."
        ),
        tools=[inspect_finance_workflow],
    )

    evidence_specialist = Agent(
        name="evidence_specialist",
        description=(
            "Summarises audit evidence, open exceptions and what a human reviewer needs to do next."
        ),
        model=model,
        system_prompt=(
            "You are Cherry Agent's audit-evidence specialist. Use the workflow and exception tools; "
            "do not infer evidence that is absent. Make actor, status and next required human action "
            "clear. Do not present the evidence pack as an external audit opinion or tax advice."
        ),
        tools=[inspect_finance_workflow, get_open_finance_exceptions],
    )

    orchestrator_prompt = """
You are Cherry Agent, an autonomous but human-governed finance-operations agent for UK SMEs.

Your job is to reduce repetitive finance administration while preserving clear financial controls.
Use your specialist agents rather than inventing workflow facts yourself:

- workflow_specialist: run/inspect finance workflows and reconciliation outcomes.
- control_specialist: explain deterministic control decisions and why human review is required.
- evidence_specialist: summarise audit evidence and open exceptions.

Operating boundary:
1. Strands provides reasoning, tool selection and specialist delegation.
2. Deterministic Cherry code decides arithmetic, reconciliation and policy outcomes.
3. Human approval is required where the deterministic workflow says so. You cannot grant approval.
4. Do not initiate payments or change bank details.
5. Do not provide tax, legal or external-audit opinions.
6. When data is missing or ambiguous, surface the exception instead of guessing.

For demos, start with workflow_specialist and choose the scenario that best matches the user's request.
Always make it obvious what the agent did, what deterministic controls did, and where a human is still
required.
""".strip()

    return Agent(
        name="cherry_agent",
        description="Strands-powered autonomous finance operations with deterministic controls.",
        model=model,
        system_prompt=orchestrator_prompt,
        tools=[
            workflow_specialist.as_tool(
                name="workflow_specialist",
                description="Run or inspect bounded SME finance workflows and reconciliations.",
            ),
            control_specialist.as_tool(
                name="control_specialist",
                description="Explain deterministic finance-control outcomes and escalation reasons.",
            ),
            evidence_specialist.as_tool(
                name="evidence_specialist",
                description="Summarise audit evidence and open finance exceptions.",
            ),
        ],
    )


def _result_text(result: Any) -> str:
    """Extract the text blocks from a Strands AgentResult without depending on private internals."""

    message = getattr(result, "message", None)
    if isinstance(message, dict):
        content = message.get("content", [])
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            ]
            text = "\n".join(part for part in parts if part).strip()
            if text:
                return text
    return str(result)


def invoke_cherry_agent(prompt: str) -> dict[str, Any]:
    """Invoke a fresh Strands hierarchy for one request to avoid cross-user conversation leakage."""

    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": "prompt_required"}

    agent = build_cherry_agent()
    result = agent(prompt.strip())
    return {
        "response": _result_text(result),
        "framework": "Strands Agents SDK",
        "model_provider": "Amazon Bedrock",
        "model_id": os.getenv("STRANDS_BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
        "aws_region": os.getenv("AWS_REGION", DEFAULT_AWS_REGION),
        "financial_boundary": "Reconciliation and decision support only; no payment initiation.",
    }
