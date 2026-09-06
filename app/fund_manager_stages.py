from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent_tools import (
    compare_bank_statement_cash,
    compare_dates,
    compare_periods,
    identify_ylookup_workbook,
    read_document,
    reconcile_bank_statement_workbook,
    reconcile_cash,
    reconcile_investor_gl_workbook,
    reconcile_loader_sample_workbook,
    reconcile_positions,
    reconcile_trades,
)
from app.config import get_settings
from app.fund_manager_agentic import get_fund_manager_control_catalogue

APP_NAME = "cherry_fund_manager_staged"
USER_ID = "fund-manager-ui"
settings = get_settings()


planning_agent = Agent(
    name="fund_manager_control_planner",
    model=settings.gemini_model,
    description="Plans Fund Manager controls without executing financial tools.",
    instruction="""
You are the Fund Manager control-planning agent. The evidence has already been classified by the
server. Read the supplied classification report and call get_fund_manager_control_catalogue. Select
only applicable registered controls. Do NOT execute any financial, reconciliation or document tool.

For each applicable control return one of:
- ready: required evidence is present and the catalogue has an implementation.
- awaiting_evidence: required evidence or a reliable pair is missing.
- adapter_pending: the source is recognised but no registered implementation exists.

Never mark a control executed or passed during planning. Return only valid JSON:
{
  "status": "ready|needs_input",
  "control_plan": [{
    "control_id": "...",
    "control": "...",
    "source_ids": ["SRC-01"],
    "source_roles": {},
    "required_evidence": ["..."],
    "status": "ready|awaiting_evidence|adapter_pending",
    "reasoning": "...",
    "confidence": 0.0,
    "missing_evidence": [],
    "tool_name": "..."
  }],
  "agent_summary": "..."
}
""".strip(),
    tools=[get_fund_manager_control_catalogue],
)


execution_agent = Agent(
    name="fund_manager_control_executor",
    model=settings.gemini_model,
    description=(
        "Executes only user-approved Fund Manager controls using deterministic financial tools."
    ),
    instruction="""
You are the Fund Manager execution agent. You receive a previously approved control plan plus local
paths for the case evidence. Execute ONLY plan entries whose status is ready. Do not add new
controls. Deterministic tool outputs are authoritative; never recompute or override their figures.

Tool routing:
- investor_gl -> reconcile_investor_gl_workbook
- loader_template -> reconcile_loader_sample_workbook
- bank_statement_working_file -> reconcile_bank_statement_workbook
- bank_statement + cash_transactions -> read_document first to extract account/currency/balance,
  then compare_bank_statement_cash
- positions pair -> reconcile_positions
- cash_transactions pair -> reconcile_cash
- trades pair -> reconcile_trades
- financial_statement pair -> compare_periods and compare_dates
- identify_ylookup_workbook may confirm a Ylookup workbook contract before execution.

Return only valid JSON:
{
  "status": "clean|review_required|partially_evaluated|insufficient_evidence",
  "control_plan": [{
    "control_id": "...",
    "control": "...",
    "source_ids": ["SRC-01"],
    "status": "executed|awaiting_evidence|adapter_pending|failed",
    "reasoning": "...",
    "missing_evidence": [],
    "tool_name": "..."
  }],
  "control_runs": [{
    "control_id": "...",
    "tool_name": "...",
    "status": "completed|failed",
    "source_ids": ["SRC-01"],
    "output": {}
  }],
  "issues": [{
    "id": "EXC-001",
    "category": "data_quality|statement|position|trade|cash|control",
    "code": "...",
    "title": "...",
    "summary": "...",
    "severity": "high|warning|info",
    "recommended_action": "...",
    "evidence": []
  }],
  "agent_summary": "..."
}
""".strip(),
    tools=[
        identify_ylookup_workbook,
        reconcile_bank_statement_workbook,
        compare_bank_statement_cash,
        reconcile_investor_gl_workbook,
        reconcile_loader_sample_workbook,
        reconcile_positions,
        reconcile_cash,
        reconcile_trades,
        read_document,
        compare_periods,
        compare_dates,
    ],
)


investigation_agent = Agent(
    name="fund_manager_exception_investigator",
    model=settings.gemini_model,
    description="Investigates completed Fund Manager control outputs and recommends human action.",
    instruction="""
You are the Fund Manager exception-investigation agent. Review ONLY the supplied deterministic
control results and issues. Explain likely causes, evidence gaps, correlations and priority. You may
not change a deterministic result, create a new pass/fail result, or approve a financial action.

Return only valid JSON:
{
  "status": "clean|review_required",
  "investigations": [{
    "issue_id": "EXC-001",
    "finding": "...",
    "likely_cause": "...",
    "evidence_gap": "...",
    "priority": "high|medium|low",
    "recommended_action": "..."
  }],
  "recommended_human_action":
    "accept_and_close|review_missing_evidence|assign_and_monitor|request_evidence|"
    "escalate_immediately",
  "agent_summary": "..."
}
""".strip(),
)


def _extract_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Fund Manager stage agent did not return valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Fund Manager stage response must be a JSON object.")
    return parsed


async def _run_agent(agent: Agent, prompt: str) -> tuple[dict[str, Any], list[str]]:
    session_service = InMemorySessionService()
    session_id = f"fm-stage-{uuid4().hex}"
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
    )
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    final_text = ""
    tool_trace: list[str] = []

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        new_message=message,
    ):
        content = getattr(event, "content", None)
        for part in getattr(content, "parts", []) or []:
            function_call = getattr(part, "function_call", None)
            if function_call and getattr(function_call, "name", None):
                tool_trace.append(str(function_call.name))
        is_final = getattr(event, "is_final_response", None)
        if callable(is_final) and is_final() and content:
            texts = [
                str(part.text)
                for part in getattr(content, "parts", []) or []
                if getattr(part, "text", None)
            ]
            if texts:
                final_text = "\n".join(texts)

    if not final_text:
        raise RuntimeError(f"{agent.name} completed without a final response.")
    return _extract_json(final_text), tool_trace


def _materialise_files(
    directory: str,
    files: list[tuple[str, bytes, str | None]],
) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    used: set[str] = set()
    for index, (filename, content, _) in enumerate(files, start=1):
        safe_name = Path(filename).name or f"evidence-{index}"
        if safe_name in used:
            safe_name = f"{index:02d}-{safe_name}"
        used.add(safe_name)
        path = Path(directory) / safe_name
        path.write_bytes(content)
        manifest.append({"filename": safe_name, "path": str(path)})
    return manifest


async def plan_case_controls(
    classification: dict[str, Any],
    *,
    fund_name: str | None = None,
    reporting_period: str | None = None,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    prompt = (
        "Plan the next Fund Manager controls. Do not execute any financial tool.\n"
        f"Fund name: {fund_name or 'not supplied'}\n"
        f"Reporting period: {reporting_period or 'not supplied'}\n"
        f"As-of date: {as_of_date or 'not supplied'}\n"
        f"Classification report: {json.dumps(classification)}"
    )
    result, trace = await _run_agent(planning_agent, prompt)
    result["orchestration_mode"] = "agentic"
    result["stage"] = "planned"
    result["agent_name"] = planning_agent.name
    result["agent_tool_trace"] = trace
    return result


async def execute_case_controls(
    files: list[tuple[str, bytes, str | None]],
    classification: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    with TemporaryDirectory(prefix="cherry-fund-manager-stage-") as directory:
        manifest = _materialise_files(directory, files)
        prompt = (
            "Execute the user-approved Fund Manager control plan. Run only entries marked ready.\n"
            f"Evidence manifest: {json.dumps(manifest)}\n"
            f"Classification report: {json.dumps(classification)}\n"
            f"Approved control plan: {json.dumps(plan)}"
        )
        result, trace = await _run_agent(execution_agent, prompt)

    result["orchestration_mode"] = "agentic"
    result["stage"] = "executed"
    result["agent_name"] = execution_agent.name
    result["agent_tool_trace"] = trace
    result["issues_found"] = len(result.get("issues", []))
    result["critical"] = sum(
        issue.get("severity") == "high" for issue in result.get("issues", [])
    )
    result["material"] = sum(
        issue.get("severity") in {"high", "warning"} for issue in result.get("issues", [])
    )
    return result


async def investigate_case_execution(execution: dict[str, Any]) -> dict[str, Any]:
    prompt = (
        "Investigate the completed Fund Manager control results. Do not change any result.\n"
        f"Execution report: {json.dumps(execution)}"
    )
    result, trace = await _run_agent(investigation_agent, prompt)
    result["orchestration_mode"] = "agentic"
    result["stage"] = "investigated"
    result["agent_name"] = investigation_agent.name
    result["agent_tool_trace"] = trace
    return result
