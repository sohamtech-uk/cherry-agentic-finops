from __future__ import annotations

import json
import mimetypes
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
from app.fund_manager_classification import classify_and_validate_sources
from app.fund_manager_orchestrator import CONTROL_CATALOGUE

APP_NAME = "cherry_fund_manager"
USER_ID = "fund-manager-ui"


def classify_uploaded_evidence(file_paths: list[str]) -> dict[str, Any]:
    """Classify and validate the uploaded evidence paths before any control is selected.

    Args:
        file_paths: Local paths created for the current Fund Manager request.
    """

    items: list[tuple[str, bytes, str | None]] = []
    for file_path in file_paths:
        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"Evidence path {file_path!r} does not exist.")
        content_type, _ = mimetypes.guess_type(path.name)
        items.append((path.name, path.read_bytes(), content_type))

    sources = classify_and_validate_sources(items)
    rejected = sum(source["validation_status"] == "rejected" for source in sources)
    return {
        "source_count": len(sources),
        "accepted_count": len(sources) - rejected,
        "rejected_count": rejected,
        "sources": sources,
    }


def get_fund_manager_control_catalogue() -> dict[str, Any]:
    """Return the closed control catalogue available to the Fund Manager agent.

    The agent may choose from this catalogue, but deterministic tools remain responsible for
    arithmetic, reconciliation and source-contract checks.
    """

    return {
        "controls": [
            {
                "control_id": definition.control_id,
                "name": definition.name,
                "source_type": definition.source_type,
                "required_evidence": list(definition.required_evidence),
                "required_roles": list(definition.required_roles or ()),
                "tool_name": definition.tool_name,
                "implemented": definition.executor is not None,
                "version": definition.version,
            }
            for definition in CONTROL_CATALOGUE
        ]
    }


settings = get_settings()

fund_manager_agent = Agent(
    name="fund_manager_control_orchestrator",
    model=settings.gemini_model,
    description=(
        "Agentic Fund Manager control orchestrator that classifies uploaded evidence, selects "
        "applicable controls from a closed catalogue, invokes deterministic tools, investigates "
        "their returned exceptions and recommends human action."
    ),
    instruction="""
You are Cherry Fund Manager's control orchestrator. You decide which controls should run from the
actual uploaded evidence, but you never perform financial arithmetic, reconciliation or pass/fail
calculation yourself.

Mandatory workflow:
1. ALWAYS call classify_uploaded_evidence first with every supplied local file path.
2. ALWAYS call get_fund_manager_control_catalogue after classification.
3. Reject or mark for review any source that classification says is rejected. Never guess its type.
4. Select only controls whose source_type and evidence requirements are supported by the accepted
   sources. Do not claim a dimension was tested when its evidence was absent.
5. For implemented controls, call the matching deterministic tool. The tool result is authoritative
   for figures, differences, contract validation and reconciliation status. Never recompute or
   override it.
6. For controls needing a pair, only run them when both sides can be identified reliably. Otherwise
   mark the control awaiting_evidence.
7. If the catalogue says a recognised control is not implemented, mark it adapter_pending. Never
   treat that as a pass.
8. Investigate and explain exceptions from tool results, but never turn missing evidence into a
   clean result and never approve a financial action.

Tool routing guidance:
- investor_gl -> reconcile_investor_gl_workbook
- loader_template -> reconcile_loader_sample_workbook
- bank_statement_working_file -> reconcile_bank_statement_workbook
- positions pair -> reconcile_positions
- cash_transactions pair -> reconcile_cash
- trades pair -> reconcile_trades
- financial_statement pair -> compare_periods and compare_dates; read_document when semantic context
  is needed
- identify_ylookup_workbook may be used to confirm a workbook contract before a Ylookup control.

Return ONLY valid JSON, with no markdown fences, in this shape:
{
  "status": "clean|review_required|partially_evaluated|insufficient_evidence",
  "control_plan": [
    {
      "control_id": "...",
      "control": "...",
      "source_ids": ["SRC-01"],
      "source_roles": {},
      "required_evidence": ["..."],
      "status": "executed|awaiting_evidence|adapter_pending|failed",
      "reasoning": "...",
      "confidence": 0.0,
      "missing_evidence": [],
      "tool_name": "..."
    }
  ],
  "control_runs": [
    {
      "control_id": "...",
      "tool_name": "...",
      "status": "completed|failed",
      "source_ids": ["SRC-01"],
      "output": {}
    }
  ],
  "issues": [
    {
      "id": "EXC-001",
      "category": "data_quality|statement|position|trade|cash|control",
      "code": "...",
      "title": "...",
      "summary": "...",
      "severity": "high|warning|info",
      "recommended_action": "...",
      "evidence": []
    }
  ],
  "investigations": [],
  "recommended_human_action":
    "accept_and_close|review_missing_evidence|assign_and_monitor|request_evidence|"
    "escalate_immediately",
  "agent_summary": "short explanation of what the agent selected and why"
}

Set overall status from tool/control outcomes only:
- clean: every applicable recognised control executed and tool outputs show no issue.
- review_required: an executed tool returned a material exception or failure.
- partially_evaluated: at least one control executed and at least one is awaiting evidence or
  adapter.
- insufficient_evidence: no substantive control could execute.
""".strip(),
    tools=[
        classify_uploaded_evidence,
        get_fund_manager_control_catalogue,
        identify_ylookup_workbook,
        reconcile_bank_statement_workbook,
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


def _extract_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Fund Manager agent did not return valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Fund Manager agent response must be a JSON object.")
    return parsed


def _materialise_files(
    directory: str, files: list[tuple[str, bytes, str | None]]
) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    used_names: set[str] = set()
    for index, (filename, content, _) in enumerate(files, start=1):
        safe_name = Path(filename).name or f"evidence-{index}"
        if safe_name in used_names:
            safe_name = f"{index:02d}-{safe_name}"
        used_names.add(safe_name)
        path = Path(directory) / safe_name
        path.write_bytes(content)
        manifest.append({"filename": safe_name, "path": str(path)})
    return manifest


def _shape_response_metadata(
    result: dict[str, Any], files: list[tuple[str, bytes, str | None]]
) -> None:
    sources = classify_and_validate_sources(files)
    result["sources"] = sources
    filename_by_source = {source["id"]: source["filename"] for source in sources}
    for entry in result.get("control_plan", []):
        if not isinstance(entry, dict):
            continue
        source_ids = entry.get("source_ids") or []
        if "filename" not in entry:
            entry["filename"] = ", ".join(
                filename_by_source[source_id]
                for source_id in source_ids
                if source_id in filename_by_source
            )


async def run_agentic_analysis(
    files: list[tuple[str, bytes, str | None]],
    *,
    fund_name: str | None = None,
    reporting_period: str | None = None,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Run Fund Manager analysis through the ADK agent rather than the deterministic planner."""

    with TemporaryDirectory(prefix="cherry-fund-manager-") as directory:
        manifest = _materialise_files(directory, files)
        prompt = (
            "Run the Fund Manager control review for this evidence batch. Follow the mandatory "
            "classification -> catalogue -> tool execution workflow and return only the required "
            "JSON object.\n\n"
            f"Fund name: {fund_name or 'not supplied'}\n"
            f"Reporting period: {reporting_period or 'not supplied'}\n"
            f"As-of date: {as_of_date or 'not supplied'}\n"
            f"Evidence manifest: {json.dumps(manifest)}"
        )

        session_service = InMemorySessionService()
        session_id = f"fm-{uuid4().hex}"
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session_id,
        )
        runner = Runner(
            agent=fund_manager_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
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
            raise RuntimeError("Fund Manager agent completed without a final response.")

        result = _extract_json(final_text)
        _shape_response_metadata(result, files)
        result["orchestration_mode"] = "agentic"
        result["agent_name"] = fund_manager_agent.name
        result["agent_tool_trace"] = tool_trace
        result["controls_executed"] = sum(
            entry.get("status") == "executed" for entry in result.get("control_plan", [])
        )
        result["controls_incomplete"] = sum(
            entry.get("status") in {"awaiting_evidence", "adapter_pending", "failed"}
            for entry in result.get("control_plan", [])
        )
        result["issues_found"] = len(result.get("issues", []))
        result["critical"] = sum(
            issue.get("severity") == "high" for issue in result.get("issues", [])
        )
        result["material"] = sum(
            issue.get("severity") in {"high", "warning"} for issue in result.get("issues", [])
        )
        result["control_boundary"] = (
            "The ADK Fund Manager agent classified the evidence and selected the applicable "
            "controls. Deterministic tools performed financial calculations and reconciliations. "
            "The agent investigated their outputs and recommended the next human action."
        )
        return result
