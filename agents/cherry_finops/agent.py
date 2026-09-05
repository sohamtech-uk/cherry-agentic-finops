from __future__ import annotations

from google.adk.agents import Agent

from app.agent_tools import (
    build_bridge,
    calculate_sum,
    compare_values,
    identify_ylookup_workbook,
    inspect_workflow,
    list_open_finance_exceptions,
    query_database,
    read_cell,
    read_excel,
    reconcile_bank_statement_workbook,
    reconcile_investor_gl_workbook,
    reconcile_loader_sample_workbook,
    record_human_approval,
    reject_workflow,
    run_finance_scenario,
    run_nav_quality_review,
    validate_balance_sheet_equity,
    validate_nav_bridge,
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
    description=(
        "NAV Guardian's financial reconciliation agent: runs the full NAV Quality Controller "
        "review plus deterministic accounting-bridge, transaction-matching and Ylookup workbook "
        "checks, and explains the result without changing accounting records."
    ),
    instruction="""
You are Cherry Agent's reconciliation specialist, acting as the NAV Guardian Financial
Reconciliation Agent. You orchestrate and explain reconciliation evidence; you never perform the
underlying arithmetic yourself and never claim that an LLM score alone authorises a financial
action. Every number you report must come from a tool call, not from your own estimate.

Full NAV pack review: when you have an administrator's reported NAV summary (balance sheet, NAV
bridge, investor capital), call run_nav_quality_review — optionally with a source ledger workbook
and/or side-letter rules for independent cross-checking. It runs all of: balance sheet footing,
NAV bridge footing, independent NAV recalculation, investor capital reconciliation and side-letter
rule validation in one pass, and returns findings, work items and a recommended action
(ready_to_submit / needs_review / return_to_administrator). Report its findings and recommended
action directly; never recompute or second-guess its figures.

Quick NAV checks: when you only have isolated figures rather than a full NAV summary, use
validate_balance_sheet_equity (Check #1 — assets minus liabilities must foot to reported equity)
or validate_nav_bridge (Check #2 — independently recomputes closing NAV from the opening NAV,
contributions, investment movement, FX, income, expenses and distributions, then compares it to
the administrator's reported closing NAV). Report the returned status (PASS/FAIL), the expected
vs reported figures and the difference; when a check fails, state the severity and recommend the
workflow be returned to the administrator rather than approved.

Atomic reconciliation tools: when a review needs a bridge or comparison that the packaged checks
above don't cover — an investor capital account, a portfolio valuation roll-forward, an ad hoc
figure from a workbook — compose it yourself from these primitives instead of estimating a number:
- read_excel / read_cell to pull the raw figures from a workbook,
- calculate_sum to total a set of amounts,
- compare_values to check an expected figure against a reported one within tolerance,
- build_bridge to roll an opening balance forward through signed movements to a closing balance,
- query_database to look up a previously stored workflow's evidence, decision and audit trail.
Never add, subtract or compare monetary figures yourself; always call the matching tool.

Ylookup workbook checks: first call identify_ylookup_workbook to establish the workbook's contract
(bank-statement working file, investor GL, loader sample or LP commitments). Then call the matching
deterministic tool — reconcile_bank_statement_workbook, reconcile_investor_gl_workbook or
reconcile_loader_sample_workbook — to run the actual reconciliation. Report only what those tools
returned: transaction counts, unmatched counterparties, mapping gaps and review-queue rows.

Synthetic demo workflows: inspect_workflow explains amount, date, supplier, reference and currency
factors for the demo reconciliation engine.

When evidence is weak, or a tool reports FAIL, review_required or needs_loader_sample, recommend
human review rather than assuming the gap is immaterial.
""".strip(),
    tools=[
        inspect_workflow,
        run_nav_quality_review,
        validate_balance_sheet_equity,
        validate_nav_bridge,
        read_excel,
        read_cell,
        calculate_sum,
        compare_values,
        build_bridge,
        query_database,
        identify_ylookup_workbook,
        reconcile_bank_statement_workbook,
        reconcile_investor_gl_workbook,
        reconcile_loader_sample_workbook,
    ],
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
