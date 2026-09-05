from __future__ import annotations

from google.adk.agents import Agent

from app.agent_tools import (
    inspect_workflow,
    list_open_finance_exceptions,
    record_human_approval,
    reject_workflow,
    run_finance_scenario,
)
from app.config import get_settings
from app.contract_tools import (
    extract_clause,
    get_effective_date,
    get_investor_rule,
    search_lpa,
    search_side_letter,
)

settings = get_settings()

reconciliation_specialist = Agent(
    name="reconciliation_specialist",
    model=settings.gemini_model,
    description="Explains transaction matching evidence without changing accounting records.",
    instruction="""
You are Cherry Agent's reconciliation specialist. Inspect workflow evidence and explain amount,
date, supplier, reference and currency factors. Never claim that an LLM score alone authorises a
financial action. When evidence is weak, recommend human review or missing evidence.
""".strip(),
    tools=[inspect_workflow],
)

control_specialist = Agent(
    name="finance_control_specialist",
    model=settings.gemini_model,
    description="Explains risk controls and records explicit human decisions.",
    instruction="""
You are Cherry Agent's human-in-the-loop control specialist. Explain why a workflow was automated,
paused or escalated. You may call record_human_approval or reject_workflow only after the user gives
an explicit instruction for a specific workflow and identifies the human reviewer. Never invent or
assume approval. Cherry Agent reconciles accounting evidence; it never initiates a bank payment.
""".strip(),
    tools=[inspect_workflow, record_human_approval, reject_workflow],
)

evidence_specialist = Agent(
    name="audit_evidence_specialist",
    model=settings.gemini_model,
    description="Summarises append-only audit evidence and month-end exceptions.",
    instruction="""
You are Cherry Agent's evidence specialist. Summarise the audit trail, identify the human or system
actor for each material decision, and make clear that the evidence pack is not an external audit
opinion or tax advice.
""".strip(),
    tools=[inspect_workflow, list_open_finance_exceptions],
)

contract_specialist = Agent(
    name="contract_specialist",
    model=settings.gemini_model,
    description=(
        "Retrieves LPA and side-letter evidence and resolves effective investor-specific rules."
    ),
    instruction="""
You are the private-markets contract specialist supporting NAV quality control. Search the LPA and
the relevant investor side letter before stating a contractual rule. Use extract_clause for the
complete provision and get_effective_date before applying a term to a reporting period. Use
get_investor_rule when a deterministic structured rule is required. Cite the document, section and
page returned by the tools. If sources conflict, lack an effective date or cannot be structured,
require human review. Never invent a clause, silently resolve a conflict, calculate official NAV,
modify source documents or approve a financial statement.
""".strip(),
    tools=[
        search_lpa,
        search_side_letter,
        extract_clause,
        get_effective_date,
        get_investor_rule,
    ],
)

root_agent = Agent(
    name="cherry_finops",
    model=settings.gemini_model,
    description="Autonomous, human-governed finance operations for small organisations.",
    instruction="""
You are Cherry Agent, an autonomous finance-operations orchestrator for UK small businesses and
community organisations. Your purpose is to turn documents and bank events into completed,
auditable accounting workflows while keeping humans in control of uncertainty and higher-risk
transactions.

Use run_finance_scenario for a working demonstration. Delegate detailed explanations to your
specialists. State clearly which parts came from Gemini and which controls were deterministic.
Never fabricate financial records, initiate payments, provide tax advice, or infer human consent.
Routine high-confidence reconciliation can be automated only when the deterministic policy says so.
""".strip(),
    tools=[run_finance_scenario, inspect_workflow, list_open_finance_exceptions],
    sub_agents=[
        reconciliation_specialist,
        control_specialist,
        evidence_specialist,
        contract_specialist,
    ],
)
