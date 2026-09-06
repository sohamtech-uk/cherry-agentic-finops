# CODEX — Cherry Fund Manager Backend Workflow

## 0. Mission

Build the backend orchestration for **one Cherry Fund Manager review workflow**.

The product story is:

> **Receive mixed fund evidence → classify and structure it → dynamically determine which NAV/fund controls are relevant → invoke specialist agents/tools under strict boundaries → run deterministic financial controls → generate evidence-backed control results → consolidate failures through the Exception Agent → expose one case/report API to the Fund Manager UI.**

This is a **backend workstream only**.

The backend may use multiple specialist agents internally. The UI must not be forced to operate them independently.

---

# 1. Ownership boundary

### This workstream OWNS

- Multipart evidence ingestion.
- File validation.
- File-type / workflow classification.
- PDF extraction.
- Excel/CSV/JSON parsing.
- Normalisation into typed structured data.
- Case creation.
- Dynamic control planning.
- NAV Quality Control.
- Reconciliation controls.
- Statement controls.
- Contract / side-letter rule extraction.
- Capital-call and investor controls.
- Specialist agent orchestration.
- Strict per-agent tool allowlists.
- Deterministic arithmetic.
- Deterministic comparison logic.
- Materiality calculation.
- Dependency tracing.
- Exception grouping.
- Evidence provenance.
- SHA-256 evidence identity.
- Report generation.
- PDF report generation.
- Excel report generation.
- Evidence-pack generation.
- Case retrieval.
- Case clearing.
- Existing deployment token/security behaviour.
- Tests.

### This workstream MUST NOT own

- Frontend layout.
- Brand styling.
- UI navigation.
- Browser-side financial calculations.
- Payment initiation.
- Automatic movement of money.
- Silent writes to Cherry Money production.
- Silent correction of source accounting records.
- Fabricated evidence.
- Fabricated contract terms.
- Unsupported legal conclusions.

**Rule: AI interprets and selects tools. Tools operate. Deterministic controls decide. Humans approve ambiguous/material outcomes.**

---

# 2. Architectural target

```text
                    FUND MANAGER UI
                           │
                           ▼
                /api/fund-manager/*
                           │
                           ▼
                 FUND REVIEW SERVICE
                           │
                 ┌─────────┴─────────┐
                 │                   │
                 ▼                   ▼
           CASE / INGESTION      SOURCE CLASSIFIER
                                     │
                                     ▼
                            STRUCTURED EXTRACTION
                                     │
                                     ▼
                              CONTROL PLANNER
                                     │
         ┌───────────────────────────┼────────────────────────────┐
         │                           │                            │
         ▼                           ▼                            ▼
 NAV QUALITY CONTROL       RECONCILIATION CONTROLS      DOCUMENT/RULE CONTROLS
         │                           │                            │
         └───────────────────────────┼────────────────────────────┘
                                     ▼
                              CONTROL RESULTS
                                     │
                                     ▼
                               EXCEPTION AGENT
                                     │
                    group / materiality / dependencies
                                     │
                                     ▼
                          REPORT + EVIDENCE ENGINE
                                     │
                                     ▼
                       ONE FUND REVIEW CASE PAYLOAD
```

---

# 3. Preserve existing capabilities

The current repository already contains private-markets / Ylookup analysis functionality and multiple control paths.

Do NOT rewrite working logic purely to satisfy this new API.

Instead:

1. inspect `main`;
2. identify reusable parsing/services/control functions;
3. create a **Fund Manager orchestration/facade layer**;
4. call existing services from that layer;
5. preserve old endpoints for backward compatibility;
6. migrate UI to the new facade separately.

The new `/api/fund-manager/*` routes should be an orchestration contract, not a duplicate implementation of every existing control.

---

# 4. Core backend principle: classify first, then route

The backend must never assume every Excel workbook has one schema.

The ingestion flow must be:

```text
uploaded file
    ↓
safe type check
    ↓
structure inspection
    ↓
classification
    ↓
normalisation
    ↓
control routing
```

Do not use filename-only routing when workbook/document structure is available.

Filename can be supporting evidence, not the sole classification authority.

---

# 5. Supported source families

At minimum, the classifier should be able to represent:

## Documents

```text
capital_call_notice
bank_statement
financial_statement
lpa
side_letter
investor_report
unknown_pdf
```

## Workbooks

```text
nav_workbook
investor_gl
lp_commitments
approved_bank_details
bank_statement_working_file
journal_workbook
loader_template
portfolio_positions
trades
valuation_workbook
unknown_workbook
```

## Structured feeds

```text
cash_transactions
bank_transactions
journal_entries
positions
trades
fund_metadata
unknown_json
unknown_csv
```

Not every type must have a full control workflow on day one.

Unknown types must fail safely:

```text
classified = unknown
workflow = none
review_required = true
```

Never guess a financial interpretation solely to avoid returning `unknown`.

---

# 6. Multi-file ingestion

The Fund Manager endpoint must accept mixed multiple files.

```http
POST /api/fund-manager/analyse
Content-Type: multipart/form-data
```

Repeated field:

```text
files
```

Optional metadata:

```text
fund_name
reporting_period
as_of_date
```

Deployment may also require the existing Cherry demo-token header.

### Requirements

- multiple PDFs
- multiple Excel workbooks
- CSV
- JSON
- JSON optional
- validate extension and MIME where practical
- enforce configured per-file maximum
- enforce configured file-count maximum
- never trust client-provided MIME alone
- never log uploaded document bodies
- never log Gemini/API keys
- never log demo tokens

---

# 7. Case lifecycle

Create one `FundReviewCase`.

Recommended statuses:

```text
processing
clean
review_required
evidence_required
failed
```

Recommended stage statuses:

```text
waiting
running
complete
partial
failed
not_required
```

Recommended case shape:

```python
FundReviewCase
    case_id
    fund_name
    reporting_period
    as_of_date
    status
    progress
    sources[]
    control_plan
    control_results[]
    exceptions[]
    evidence[]
    reports
    created_at
    updated_at
```

Use actual project conventions (Pydantic/dataclasses/etc.) after inspecting the codebase.

---

# 8. Structured source model

Each upload should result in a structured source record.

Example:

```json
{
  "id": "SRC-01",
  "filename": "Q2_NAV.xlsx",
  "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "detected_type": "nav_workbook",
  "status": "processed",
  "confidence": 1.0,
  "sha256": "...",
  "metadata": {
    "fund_name": "Northstar Growth Fund III",
    "reporting_period": "Q2 2026"
  },
  "warnings": []
}
```

Keep SHA-256 for provenance.

Do not return full raw document contents in the general case payload.

---

# 9. Normalised financial data

Specialist parsers/extractors should produce typed canonical data rather than passing free prose between agents.

The exact domain model can evolve, but the control layer should consume structures conceptually like:

```text
FundOpsCaseData
├── fund
├── periods[]
├── documents[]
├── statement_facts[]
├── nav_balances[]
├── ledger_entries[]
├── cash_transactions[]
├── bank_transactions[]
├── positions[]
├── trades[]
├── valuations[]
├── commitments[]
├── capital_calls[]
├── contract_rules[]
├── investor_rules[]
└── evidence_refs[]
```

### Important

Agents must not pass unsupported free-form assertions to downstream financial controls.

Any value used in a deterministic financial control needs:

- a typed field;
- a source;
- evidence reference;
- or an explicit synthetic/test provenance marker.

---

# 10. Dynamic control planner

The backend determines the control plan from available evidence.

The user does NOT select the agent.

Pseudo-logic:

```python
plan = []

if has_nav_workbook:
    plan += NAV_QUALITY_CONTROLS

if has_bank_statement or has_cash_transactions:
    plan += CASH_RECONCILIATION_CONTROLS

if has_positions:
    plan += POSITION_CONTROLS

if has_trades:
    plan += TRADE_CONTROLS

if has_financial_statements:
    plan += STATEMENT_CONTROLS

if has_lpa or has_side_letter:
    plan += CONTRACT_CONTROLS

if has_capital_call_notice and has_commitment_data:
    plan += CAPITAL_CALL_CONTROLS

if has_investor_gl:
    plan += INVESTOR_GL_CONTROLS
```

Then de-duplicate and resolve dependencies.

The plan should be returned in the case payload so the UI can explain what ran.

---

# 11. Example routing scenarios

## NAV + GL + bank evidence

```text
Q2_NAV.xlsx
Investor_GL.xlsx
Bank_*.pdf
```

Run:

```text
NAV Quality Control
Ledger/NAV reconciliation
Cash reconciliation
Statement extraction if statements are present
Exception aggregation
Evidence/report generation
```

## Capital call + commitment workbook

```text
Capital_Call.pdf
LP_Commitments.xlsx
```

Run:

```text
Capital-call extraction
Investor matching
Commitment arithmetic
Bank-instruction controls
Cash matching only if cash evidence exists
Exception aggregation
```

Cash JSON must remain optional.

If cash evidence is absent, return:

```text
cash evidence not supplied / pending evidence
```

not:

```text
no cash receipt found
```

## LPA + side letter + NAV

```text
LPA.pdf
Side_Letter.pdf
Q2_NAV.xlsx
```

Run:

```text
Contract rule extraction
Rule applicability/effective-date checks
NAV / fee controls that can be supported
Exception aggregation
```

## Bank statements + working workbook

```text
Bank_*.pdf
Bank_Working.xlsx
```

Target architecture:

```text
PDF transaction extraction
Workbook transaction normalisation
Counterparty matching
Project/position classification
Journal candidate creation
PDF-vs-workbook reconciliation
Exception aggregation
```

---

# 12. Specialist-agent model

Specialist agents are backend modules under one Supervisor / control planner.

They do not need separate UI endpoints unless required for debugging.

---

# 13. Reconciliation Agent

Allowed tools:

```text
read_excel()
read_cell()
calculate_sum()
compare_values()
build_bridge()
query_database()
```

### Responsibilities

- retrieve workbook facts;
- calculate totals through deterministic tools;
- compare expected vs observed;
- build movement bridges;
- query approved structured data;
- return typed control facts.

### Must not

- invent values;
- perform hidden arithmetic in prose;
- directly approve financial outcomes;
- update source books automatically.

---

# 14. Contract Agent

Allowed tools:

```text
search_lpa()
search_side_letter()
extract_clause()
get_effective_date()
get_investor_rule()
```

### Responsibilities

- locate relevant governing-document sections;
- identify investor-specific terms;
- establish effective date;
- identify precedence / override when evidence supports it;
- return source-linked structured rules.

### Must fail closed when

- clause applicability is ambiguous;
- multiple rules conflict;
- effective date cannot be established;
- source document is missing;
- investor identity does not resolve.

### Hackathon evidence rule

If using synthetic LPA/side-letter data, mark it explicitly as synthetic/context-derived.

Do not imply sponsor-provided legal evidence exists when it does not.

---

# 15. Statement Agent

Allowed tools:

```text
read_document()
compare_periods()
find_section()
find_entity()
compare_dates()
```

### Responsibilities

- extract statement facts;
- compare current and prior period;
- identify entities;
- identify relevant report sections;
- compare period/reporting dates;
- surface copied-forward or inconsistent disclosures where evidence supports it.

### Must not

- determine accounting materiality on its own;
- alter reported numbers;
- invent missing sections.

---

# 16. Exception Agent

Allowed tools:

```text
query_exceptions()
group_related_errors()
calculate_materiality()
trace_dependency()
```

### Responsibilities

Turn flat failures into a fund-manager review queue.

Example:

```text
75 raw findings
    ↓
12 related groups
    ↓
4 root causes
    ↓
2 material exceptions
```

It should produce:

- exception ID
- severity
- materiality
- root-cause summary
- linked controls
- dependency path
- owner
- reconciliation steps
- evidence required
- completion check
- evidence references

### Must not

- silently resolve accounting records;
- mark an exception resolved merely because an LLM says so;
- replace human approval where policy requires it.

---

# 17. Enforce tool boundaries programmatically

Do not rely only on system prompts such as:

```text
"You may only use these tools."
```

Implement a backend tool registry.

Conceptual:

```python
AGENT_TOOL_ALLOWLISTS = {
    "reconciliation": {
        "read_excel",
        "read_cell",
        "calculate_sum",
        "compare_values",
        "build_bridge",
        "query_database",
    },
    "contract": {
        "search_lpa",
        "search_side_letter",
        "extract_clause",
        "get_effective_date",
        "get_investor_rule",
    },
    "statement": {
        "read_document",
        "compare_periods",
        "find_section",
        "find_entity",
        "compare_dates",
    },
    "exception": {
        "query_exceptions",
        "group_related_errors",
        "calculate_materiality",
        "trace_dependency",
    },
}
```

Reject unapproved tool calls at runtime.

---

# 18. LLM responsibilities

The LLM may decide:

```text
Which approved tool should be called?
What evidence should be retrieved next?
What workflow appears applicable?
What human-readable explanation should accompany the finding?
```

The LLM must NOT be the authority for:

```text
sum
difference
variance
materiality arithmetic
bridge arithmetic
date ordering
exact matching
duplicate detection
control pass/fail when deterministic inputs exist
payment approval
```

Use deterministic Python/tool functions for those operations.

---

# 19. Tool-call audit record

Store a safe activity summary, not private chain-of-thought.

Example:

```json
{
  "agent": "reconciliation",
  "tool": "build_bridge",
  "reason": "Verify closing NAV against opening NAV and current-period movements.",
  "input_refs": [
    "EVD-001",
    "EVD-002"
  ],
  "status": "complete",
  "duration_ms": 31
}
```

Do not store or expose hidden reasoning traces.

---

# 20. NAV Quality Control

Build / reuse deterministic NAV controls.

Possible controls when supported by the uploaded data:

```text
NAV workbook footing
Assets vs liabilities/equity
Opening NAV vs prior close
NAV movement bridge
Investor capital reconciliation
Management fee calculation
Cash reconciliation
Position completeness
Position valuation consistency
Trade completeness
Stale valuation checks
Exposure / concentration checks
FX consistency
Period/date consistency
Statement disclosure consistency
```

Do not claim a control ran if the necessary evidence was not present.

Return:

```text
not_required
```

or:

```text
evidence_required
```

as appropriate.

---

# 21. Canonical control result

Every control should map to a common response schema.

```json
{
  "control_id": "NAV_MOVEMENT_BRIDGE",
  "category": "nav_quality",
  "title": "NAV movement bridge",
  "status": "fail",

  "summary": "Reported closing NAV exceeds expected closing NAV by £100,000.",

  "expected": 51550000,
  "observed": 51650000,
  "variance": 100000,
  "currency": "GBP",

  "calculation": [
    {
      "label": "Opening NAV",
      "operator": null,
      "value": 48420000
    },
    {
      "label": "Contributions",
      "operator": "+",
      "value": 1000000
    }
  ],

  "evidence_ids": [
    "EVD-001",
    "EVD-002"
  ],

  "exception_ids": [
    "EX-0041"
  ]
}
```

Recommended statuses:

```text
pass
fail
warning
evidence_required
not_required
error
```

---

# 22. Evidence model

Every material fact should be traceable.

Recommended evidence reference:

```json
{
  "evidence_id": "EVD-001",
  "source_id": "SRC-01",
  "filename": "Q2_NAV.xlsx",
  "kind": "spreadsheet",
  "reference": {
    "sheet": "NAV Summary",
    "cell": "F28"
  },
  "sha256": "...",
  "used_by_controls": [
    "NAV_MOVEMENT_BRIDGE"
  ]
}
```

For a row:

```json
{
  "sheet": "Investor GL",
  "row_start": 1182,
  "row_end": 1191
}
```

For a PDF:

```json
{
  "page": 18,
  "section": "Subsequent events"
}
```

For a bank transaction:

```json
{
  "page": 2,
  "transaction_index": 14,
  "statement_account": "4319"
}
```

---

# 23. Evidence hashes

Calculate SHA-256 for every uploaded source.

Use hashes to prove source identity.

Do not present SHA-256 as proof that the source is correct; it proves identity/integrity of the bytes analysed.

For derived structured artifacts, optionally hash canonical JSON if the project already has an evidence-chain mechanism.

---

# 24. Exception model

The Exception Agent should produce a common structure.

```json
{
  "exception_id": "EX-0041",
  "status": "open",
  "severity": "high",
  "materiality": 100000,
  "currency": "GBP",

  "category": "nav_quality",
  "title": "NAV movement does not reconcile",

  "root_cause": {
    "category": "contract_rule",
    "summary": "Possible investor-specific management-fee treatment."
  },

  "related_controls": [
    "NAV_MOVEMENT_BRIDGE",
    "INVESTOR_CAPITAL",
    "MANAGEMENT_FEE"
  ],

  "owner": "Fund Controller",

  "reconciliation_steps": [
    "Review the applicable management-fee rule.",
    "Confirm any investor-specific override.",
    "Recalculate the expected contribution.",
    "Correct approved source data if required.",
    "Rerun affected controls."
  ],

  "dependencies": [
    "Contract rule",
    "Fee calculation",
    "Investor capital",
    "NAV movement bridge"
  ],

  "evidence_required": [
    "Approved investor rule",
    "NAV calculation source"
  ],

  "completion_check": "Affected controls pass after approved source correction.",

  "evidence_ids": [
    "EVD-001",
    "EVD-004"
  ]
}
```

---

# 25. Root-cause grouping

Avoid producing one exception card per low-level failed field when multiple failures share one root cause.

Example:

```text
Side-letter rule not applied
    ├── fee calculation failed
    ├── investor capital failed
    └── NAV bridge failed
```

Prefer:

```text
1 root-cause exception
3 linked controls
£100,000 materiality
```

while preserving the underlying control findings.

---

# 26. Materiality

`calculate_materiality()` must be deterministic.

Inputs should be explicit.

Examples:

```text
absolute variance
fund NAV
investor NAV
configured threshold
currency
```

Do not let the LLM invent a materiality threshold.

If no materiality policy exists:

```text
materiality = null
severity = policy-dependent
```

or use an explicitly documented hackathon/demo policy.

Never silently pretend a real fund policy exists.

---

# 27. Report engine

Generate backend reports from the final case payload.

## PDF report

Recommended sections:

```text
Title / fund / period
Overall review status
Sources analysed
Controls run
Control summary
Material findings
Exception details
How to reconcile
Evidence references
Control boundary / governance
Evidence manifest
```

## Excel report

Recommended sheets:

```text
Summary
Sources
Controls
Exceptions
Evidence
```

## Evidence pack

Recommended ZIP:

```text
case_manifest.json
control_results.json
exceptions.json
evidence_manifest.json
report.pdf
report.xlsx
```

Do not include raw uploads in the ZIP unless intentionally supported and safe.

---

# 28. Fund Manager API facade

Implement:

```http
POST /api/fund-manager/analyse
GET /api/fund-manager/cases/{case_id}
GET /api/fund-manager/cases/{case_id}/exceptions
GET /api/fund-manager/cases/{case_id}/evidence

GET /api/fund-manager/cases/{case_id}/report.pdf
GET /api/fund-manager/cases/{case_id}/report.xlsx
GET /api/fund-manager/cases/{case_id}/evidence.zip

DELETE /api/fund-manager/cases/{case_id}
```

Preserve existing private-markets/Ylookup endpoints.

Do not remove old routes as part of this workstream unless explicitly authorised.

---

# 29. Analyse endpoint behaviour

## Phase 1 — synchronous compatible

For current hackathon deployment, it is acceptable for:

```http
POST /api/fund-manager/analyse
```

to process within the request and return:

```http
200 OK
```

with the completed case payload.

This is safer than relying on in-process background work in an ephemeral Cloud Run memory deployment.

## Future async compatibility

The API may later return:

```http
202 Accepted
```

```json
{
  "case_id": "CASE-2026-0091",
  "status": "processing"
}
```

The UI is being designed to support both.

Do not add complex queue infrastructure solely for the hackathon unless already available.

---

# 30. Canonical case response

Return a stable structure.

```json
{
  "case_id": "CASE-2026-0091",
  "fund_name": "Northstar Growth Fund III",
  "reporting_period": "Q2 2026",
  "as_of_date": "2026-06-30",
  "status": "review_required",

  "progress": {
    "ingestion": "complete",
    "classification": "complete",
    "extraction": "complete",
    "control_routing": "complete",
    "controls": "complete",
    "exceptions": "complete",
    "evidence_pack": "complete"
  },

  "sources": [],

  "summary": {
    "controls_run": 16,
    "controls_passed": 14,
    "controls_failed": 2,
    "exceptions_open": 2,
    "material_exposure": 112500,
    "currency": "GBP",
    "nav": 24812350,
    "cash": 1340820,
    "positions": 148
  },

  "control_categories": [],

  "controls": [],

  "exceptions": [],

  "evidence": []
}
```

Unknown values should be `null` or omitted.

Never fabricate a zero when the value is actually unknown.

---

# 31. Summary calculations

Backend owns:

```text
controls_run
controls_passed
controls_failed
exceptions_open
material_exposure
NAV
cash
position count
```

UI must not derive them independently.

Make summary generation deterministic from the case/control records.

---

# 32. Current memory deployment

For the restricted hackathon deployment, current persistence may be in-memory.

Design requirements:

- scope stored case data by `case_id`;
- do not mix results across reviews;
- case clear must remove only the requested case;
- global clear behaviour should remain protected;
- never clear Firestore/other persistent backends through an endpoint intended only for ephemeral memory unless explicitly designed and authorised.

If a generic existing memory-clear endpoint is reused, preserve its current safety check.

---

# 33. Raw-upload lifecycle

Preferred hackathon behaviour:

```text
raw upload bytes
    ↓
parse/extract within request
    ↓
store structured results + evidence refs + hashes
    ↓
discard temporary bytes unless report/evidence behaviour explicitly requires retention
```

If retaining raw files is necessary:

- use an explicit storage backend;
- record retention scope;
- never pretend in-memory deletion removed external object storage;
- keep case-scoped cleanup.

---

# 34. Security

Required:

- preserve demo-token protection on protected deployments;
- never log API keys;
- never echo secrets in exceptions;
- never log raw uploaded document bodies;
- sanitize filenames;
- validate file size;
- validate supported type;
- prevent path traversal;
- use generated case IDs;
- fail closed on unauthorised report/evidence downloads.

---

# 35. No payment boundary

The Fund Manager is a control/review product.

It must not:

- initiate payment;
- approve payment;
- alter bank instructions;
- move money;
- create direct Cherry Money production writes.

A finding can recommend:

```text
Verify bank instructions independently
```

but cannot silently approve them.

---

# 36. Error handling

Use structured errors.

Recommended:

```json
{
  "error": {
    "code": "UNSUPPORTED_WORKBOOK",
    "message": "Cherry could not determine a safe workflow for this workbook.",
    "source_id": "SRC-07",
    "retryable": false
  }
}
```

Useful error codes:

```text
NO_FILES
FILE_TOO_LARGE
UNSUPPORTED_FILE_TYPE
UNSUPPORTED_WORKBOOK
INVALID_JSON
PDF_EXTRACTION_FAILED
WORKBOOK_PARSE_FAILED
CONTROL_FAILED
REPORT_GENERATION_FAILED
CASE_NOT_FOUND
UNAUTHORISED
INTERNAL_ERROR
```

Do not return raw stack traces to the browser.

---

# 37. Partial success

Mixed evidence should allow partial analysis when safe.

Example:

```text
7 sources processed
1 source unsupported
14 controls completed
2 controls evidence-required
```

Do not fail the whole case merely because one optional source cannot be parsed, unless that source is required for the only selected workflow.

Return per-source warnings and per-control evidence requirements.

---

# 38. Backward compatibility

Existing functionality should continue to work.

Use adapters around current services.

Examples of existing conceptual capabilities likely reusable:

```text
capital-call PDF extraction
LP commitment parsing
cash matching
Ylookup workbook classification
bank-statement working-file analysis
Investor GL analysis
NAV quality review
statement comparison
exception details
PDF/Excel review reports
memory clear
```

Inspect `main` and call existing functions rather than copying logic.

---

# 39. Tests

Add / extend tests for:

## Ingestion

- multiple PDFs
- multiple XLSX
- mixed PDF/XLSX/CSV/JSON
- optional JSON
- unsupported file
- file limits

## Classification

- NAV workbook
- LP commitments
- bank working file
- investor GL
- loader template
- unknown workbook

## Routing

- NAV + GL + bank
- capital call + commitment
- capital call without cash
- LPA + side letter + NAV
- bank statements + bank working workbook

## Controls

- deterministic NAV bridge
- exact value comparison
- cash evidence missing vs zero cash
- duplicate detection where implemented
- date comparison
- bank details change

## Exceptions

- grouping related controls
- materiality
- dependency chain
- evidence-required exception

## API

- analyse success
- partial success
- case retrieval
- exceptions retrieval
- evidence retrieval
- PDF report
- Excel report
- evidence pack
- case delete
- unauthorised requests

---

# 40. Observability

Log safe operational metadata:

```text
case_id
source_count
source_types
control_count
control statuses
exception count
duration
agent/tool names
tool status
```

Do NOT log:

```text
full document text
API keys
passwords
demo token
private chain-of-thought
full bank-account data unless explicitly required and safely redacted
```

---

# 41. Performance

For hackathon scope:

- avoid reparsing the same workbook repeatedly;
- parse once, normalise once;
- cache within the case request when safe;
- reuse extracted structured data across controls;
- hash each source once;
- do not send a large PDF to the LLM multiple times for unrelated prompts if a structured extraction already exists;
- keep report generation deterministic and local where possible.

---

# 42. Integration with UI workstream

The backend team must publish/confirm:

1. exact routes;
2. request field names;
3. authentication header;
4. synchronous vs 202 behaviour;
5. status enums;
6. source type enums;
7. control status enums;
8. exception severity/status enums;
9. canonical example response;
10. error schemas.

If implementation needs to deviate from the shared contract, coordinate before changing it.

Do not silently rename fields after the UI begins integration.

---

# 43. Recommended implementation order

## Phase B1 — facade and case model

- create Fund Manager case model;
- create `POST /api/fund-manager/analyse`;
- wrap existing source classification;
- return sources and case summary.

## Phase B2 — control orchestration

- create control planner;
- connect existing NAV/reconciliation/private-markets controls;
- map all results into canonical `ControlResult`.

## Phase B3 — Exception Agent

- collect failed/warning/evidence-required controls;
- group related failures;
- calculate materiality;
- trace dependencies;
- generate reconciliation guidance.

## Phase B4 — evidence

- source hashes;
- page/sheet/cell/row references;
- case evidence manifest.

## Phase B5 — reports

- PDF
- Excel
- evidence ZIP

## Phase B6 — hardening

- partial failures;
- security;
- case clear;
- tests;
- docs.

---

# 44. Definition of done

The backend workstream is complete when:

- [ ] One Fund Manager analyse endpoint accepts mixed multiple evidence files.
- [ ] JSON is optional.
- [ ] Source classification is structure-aware.
- [ ] Unknown files fail safely.
- [ ] Uploaded evidence is normalised into typed structures.
- [ ] A dynamic control plan is created.
- [ ] Existing NAV/private-markets controls are reused where possible.
- [ ] Specialist agents are internal backend capabilities.
- [ ] Agent tool boundaries are enforced programmatically.
- [ ] Financial arithmetic is deterministic.
- [ ] Control results use one canonical schema.
- [ ] Evidence references are linked to controls.
- [ ] SHA-256 source identities are retained.
- [ ] Exception Agent groups related failures.
- [ ] Materiality calculation is deterministic.
- [ ] Dependency paths are exposed.
- [ ] Reconciliation guidance is exposed.
- [ ] Case payload matches the UI contract.
- [ ] PDF report downloads.
- [ ] Excel report downloads.
- [ ] Evidence pack downloads.
- [ ] Case clear/delete is safe.
- [ ] Existing endpoints remain functional.
- [ ] No payment initiation exists.
- [ ] No production Cherry Money writes exist.
- [ ] Tests and CI pass.

---

# 45. Codex operating instructions

When implementing this backend workstream:

1. Inspect `main` before changing architecture.
2. Reuse existing parsers, controls, reports, and evidence code.
3. Add a facade/orchestration layer rather than duplicating logic.
4. Do not modify the UI unless an API compatibility fix is absolutely necessary.
5. Preserve old endpoints.
6. Keep JSON cash evidence optional.
7. Treat missing cash evidence as missing evidence, not zero cash.
8. Enforce agent tool allowlists in code.
9. Keep LLM output away from deterministic financial authority.
10. Keep all material facts evidence-linked.
11. Do not fabricate missing contract/source evidence.
12. Do not expose chain-of-thought.
13. Do not implement payment initiation.
14. Prefer small, testable commits.
15. Include route/schema changes and compatibility notes in the PR description.

---

## Final backend principle

The backend should make the UI feel simple:

> **Upload once. Cherry decides what controls are needed. Every result is traceable. Every exception is actionable.**
