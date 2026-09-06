# CODEX — Cherry Fund Manager UI Workflow

## 0. Mission

Build **one coherent Cherry Fund Manager workspace** for a private-markets fund operator.

The user journey is:

> **Upload fund evidence → Cherry identifies the sources → Cherry dynamically invokes the appropriate backend controls → the UI presents the control report and evidence → the Exception Agent consolidates everything requiring human attention.**

This is a **UI workstream only**.

Do not create four separate user-facing products for Reconciliation, Contract, Statement, or Exception processing. Those are backend capabilities / specialist agents. The fund manager should experience one product and one review journey.

---

## 1. Ownership boundary

### This workstream OWNS

- Information architecture for the Fund Manager.
- Navigation and page layout.
- File upload UX.
- Selected-file inventory.
- Source-classification presentation.
- Analysis/progress presentation.
- Fund review dashboard.
- Control-category summaries.
- Control-detail views.
- Exception inbox.
- Exception-detail view.
- Evidence/provenance viewer.
- Download actions for PDF, Excel, and evidence pack.
- Clear/reset review UX.
- Loading, empty, success, review-required, and failure states.
- Responsive behaviour.
- Accessibility.
- Mock fixtures so UI can be developed before the backend is complete.
- A thin API client / adapter for the agreed `/api/fund-manager/*` contract.

### This workstream MUST NOT own

- NAV calculations.
- Materiality calculations.
- Reconciliation arithmetic.
- Control pass/fail decisions.
- Contract interpretation logic.
- File parsing.
- PDF extraction.
- Excel parsing.
- LLM tool selection.
- Tool implementation.
- Root-cause calculations.
- Report generation.
- Evidence hashing.
- Production persistence.
- Payment initiation.
- Writes to Cherry Money production data.

**Rule: UI presents financial truth; it never creates financial truth.**

---

## 2. Product simplification

The UI must NOT expose four separate manager applications.

### Remove / de-emphasise this model

```text
NAV Control Manager
  ├── Reconciliation Manager
  ├── Contract Manager
  ├── Statement Agent
  └── Exception Manager
```

### Replace it with this model

```text
Cherry Fund Manager
  ├── Review
  │    ├── Add evidence
  │    ├── Analyse
  │    ├── Control report
  │    └── Review exceptions
  │
  ├── Reports & Exceptions
  │
  └── Audit Evidence
```

The specialist agents should be visible only as optional backend activity / provenance, not as primary navigation.

---

## 3. Branding

Use Cherry Money branding.

### Core colours

```css
--cherry-navy: #161E54;
--cherry-red: #AD1929;
```

Recommended supporting palette:

```css
--cherry-navy-900: #10163f;
--cherry-navy-700: #242d6d;
--cherry-red-700: #8f1220;
--cherry-red-100: #f9e8ea;

--ink: #1d2233;
--muted: #667085;
--paper: #f7f8fc;
--panel: #ffffff;
--line: #e2e5ee;

--success: #277a52;
--success-soft: #eaf7f0;
--warning: #a16400;
--warning-soft: #fff4d8;
--danger: #AD1929;
--danger-soft: #fbecee;
```

### Branding rules

- Navy is the main product / navigation / primary-action colour.
- Cherry red is used for brand emphasis, exceptions, selected states, and high-attention actions.
- Do not make every surface red.
- Use white/light-grey panels for dense fund-operations data.
- Keep dashboard data readable and professional.
- Use consistent spacing, typography, status pills, tables, and drawers.
- Do not use decorative gradients if they reduce clarity.

---

## 4. Target experience

A fund manager should be able to complete this flow without understanding the internal agent architecture:

```text
1. Start a fund review
2. Upload any supported evidence
3. See what Cherry recognised
4. Click Analyse
5. See what controls were run automatically
6. Review the fund-level result
7. Open failed controls
8. Review consolidated exceptions
9. Inspect supporting evidence
10. Download the report
11. Clear the case or start another review
```

---

# 5. Main navigation

Keep navigation simple.

Recommended:

```text
Cherry FundOps

Fund Manager     Reports & Exceptions     Audit Evidence     API
```

For the hackathon, all three user-facing entries may point to sections / tabs in the same single-page workspace.

Do not reintroduce separate top-level Reconciliation Manager, Contract Manager, Statement Agent, or Exception Manager applications.

---

# 6. Fund Manager screen — initial state

The initial screen should be task-focused.

```text
CHERRY FUND MANAGER

Review fund evidence.
Find breaks before approval.

Fund / Entity        [ optional ]
Reporting period     [ optional ]
As-of date           [ optional ]

┌──────────────────────────────────────────────────────┐
│                                                      │
│               Add fund evidence                      │
│                                                      │
│     PDF · XLSX · XLS · CSV · JSON                    │
│                                                      │
│          [ Browse files ]                            │
│                                                      │
│     or drop multiple files here                      │
│                                                      │
└──────────────────────────────────────────────────────┘

[ Analyse fund → ]
```

### Required behaviour

- Multi-file selection.
- Drag/drop.
- Allow mixed file types in the same review.
- Do not require JSON.
- Do not force the user to identify the workflow in advance.
- Do not require the user to pick an agent.
- Display file count and total size.
- Allow removing one selected file before analysis.
- Allow clearing all selected files.
- Preserve the existing protected demo-token behaviour if the deployment requires it, but keep the token UX unobtrusive.

---

# 7. Evidence inventory

Before analysis, show selected files.

```text
FUND EVIDENCE                                       8 FILES

Q2_NAV.xlsx
Excel workbook · awaiting classification

Investor_GL.xlsx
Excel workbook · awaiting classification

Bank_4319.pdf
PDF · awaiting classification

Bank_5721.pdf
PDF · awaiting classification

Financial_Statements_Q2.pdf
PDF · awaiting classification

Capital_Call_08.pdf
PDF · awaiting classification
```

After backend classification:

```text
Q2_NAV.xlsx
NAV workbook

Investor_GL.xlsx
Investor-level GL

Bank_4319.pdf
Bank statement

Financial_Statements_Q2.pdf
Financial statements

Capital_Call_08.pdf
Capital-call notice
```

### Per-file card fields

Render when available:

- filename
- source ID
- MIME / extension
- detected type
- status
- fund/entity
- reporting period
- account / investor / entity if relevant
- extraction confidence
- warning count
- evidence hash abbreviation

Never fabricate labels if the backend returns `unknown`.

Use:

```text
Unknown document
```

not a guessed document type.

---

# 8. Analysis state

After clicking **Analyse fund**, show a single review pipeline.

```text
ANALYSING NORTHSTAR GROWTH FUND III

Evidence received                  ✓
Source classification              ✓
Structured extraction              ✓
Control routing                    ✓
NAV / fund controls                Running…
Exception consolidation            Waiting
Evidence package                   Waiting
```

### Important

The UI should render backend progress when supplied.

If the backend's first implementation is synchronous and does not expose true stage progress:

- show `Analysing…`
- do not invent fake percentages
- once the response returns, render the completed stages

### Optional technical disclosure

Provide a collapsed area:

```text
View processing activity
```

Example:

```text
Statement Agent        Complete
Contract Agent         Not required
Reconciliation Agent   Complete
NAV Quality Control    Complete
Exception Agent        Complete
```

This is useful for judges and technical users but should not dominate the fund-manager workflow.

---

# 9. Completed review dashboard

After analysis:

```text
NORTHSTAR GROWTH FUND III
Q2 2026

Overall status
REVIEW REQUIRED

16 controls run     14 passed     2 exceptions

NAV                 £24.81m
Cash                £1.34m
Positions           148
Documents           8
Exceptions          2
Material exposure   £112,500
```

Possible overall states:

```text
CLEAN
REVIEW REQUIRED
EVIDENCE REQUIRED
PROCESSING
FAILED
```

Never infer the overall state in the browser from arbitrary metrics. Render the backend-provided state.

---

# 10. Control report

Render controls grouped by backend category.

Example:

```text
CONTROL REPORT

NAV Quality                         7 / 8 passed
Cash & Bank Reconciliation          4 / 5 passed
Position Reconciliation             3 / 3 passed
Capital / Investor Controls         Passed
Statement Quality                   5 / 5 passed
Contract / Investor Rules           2 / 2 passed
```

Only show categories returned by the backend.

Do not show empty specialist categories merely to advertise agents.

### Control card

Each control row should show:

- status icon
- control title
- short summary
- expected value, if applicable
- observed value, if applicable
- variance, if applicable
- currency, if applicable
- evidence count
- exception count
- `View details`

Example:

```text
⚠ NAV movement bridge

Expected     £51,550,000
Reported     £51,650,000
Variance        £100,000

1 exception · 3 evidence references

[ View details ]
```

---

# 11. Control detail drawer / panel

Render backend-provided calculation details.

Example:

```text
NAV MOVEMENT BRIDGE

Opening NAV                  £48,420,000
+ Contributions               £1,000,000
+ Investment performance      £2,850,000
- Distributions                 £620,000
- Fees                          £100,000
                            ─────────────
Expected closing NAV         £51,550,000

Reported closing NAV         £51,650,000
Variance                        £100,000

Status: FAIL
```

### UI rules

- Do not re-calculate totals in JavaScript.
- Do not decide PASS / FAIL.
- Do not independently calculate variance.
- Render calculation rows exactly as returned from the backend.
- Format numbers for readability only.
- Preserve backend raw values in the application state.
- Display source references beside the calculation.

---

# 12. Reports & Exceptions

This is the final operational inbox for all backend workflows.

Do not create a separate disconnected exception product.

```text
REPORTS & EXCEPTIONS                              2 OPEN

[ All ] [ Material ] [ NAV ] [ Cash ] [ Contract ] [ Statement ]

HIGH · £100,000
NAV movement does not reconcile

Potential root cause
Investor-specific management-fee treatment.

Affected controls
NAV movement bridge
Investor capital
Management fee

Owner
Fund Controller

[ Review exception → ]
```

### Exception list capabilities

- Sort by severity.
- Sort by materiality.
- Filter by category.
- Filter by owner.
- Filter by status.
- Search by control, fund, source filename, or exception ID.
- Show linked-control count.
- Show linked-evidence count.
- Show root-cause group when available.
- Show `Open`, `Under review`, `Evidence required`, `Resolved`, or backend equivalent.

For hackathon scope, filters may be client-side over the returned case data.

---

# 13. Exception detail

Clicking an exception should open a detailed panel.

```text
NAV-EX-0041                              HIGH

NAV movement does not reconcile
£100,000 variance

ROOT CAUSE
Possible management-fee treatment difference

HOW TO RECONCILE

1. Review management-fee rule.
2. Confirm investor-specific override.
3. Recalculate expected contribution.
4. Correct approved source data if needed.
5. Rerun affected controls.

DEPENDENCY PATH

Contract rule
     ↓
Fee calculation
     ↓
Investor capital
     ↓
NAV movement bridge

OWNER
Fund Controller
```

### Evidence area

```text
EVIDENCE

Q2_NAV.xlsx
NAV Summary · F28

Investor_GL.xlsx
Rows 1182–1191

Side_Letter.pdf
Page 3 · Clause 4.2
```

### Actions

UI may expose:

```text
[ View evidence ]
[ Download report ]
[ Mark reviewed ]
```

Only expose update actions that actually have backend support.

Do not fake persistence of review actions.

---

# 14. Audit evidence

Create a single evidence view.

Each evidence reference can show:

```text
Source
Q2_NAV.xlsx

Type
NAV workbook

Reference
NAV Summary!F28

SHA-256
a73c9c...e521

Used by
NAV_MOVEMENT_BRIDGE
INVESTOR_CAPITAL

[ View context ]
```

For PDFs:

```text
Financial_Statements_Q2.pdf
Page 18 · Subsequent events
```

For transactions:

```text
Bank_4319.pdf
Page 2 · transaction row 14
```

The evidence view should make traceability easy.

---

# 15. Downloads

Completed cases should provide:

```text
[ PDF report ↓ ]
[ Excel report ↓ ]
[ Evidence pack ↓ ]
```

The UI should call backend download endpoints.

Do not create financial reports client-side.

### Expected content

#### PDF

Management / review friendly:

- fund metadata
- review status
- control summary
- material findings
- exceptions
- reconciliation guidance
- evidence references
- governance boundary

#### Excel

Operations friendly:

- Summary
- Controls
- Exceptions
- Evidence

#### Evidence pack

Backend-defined ZIP or manifest.

---

# 16. Clear / reset

Keep a visible but safe reset action:

```text
Clear review & uploaded data
```

It should:

1. ask for confirmation;
2. call the backend case-clear endpoint when a case exists;
3. clear browser state;
4. clear selected files;
5. clear rendered results;
6. return to initial state.

Do not claim persistent data was deleted unless the backend confirms it.

---

# 17. UI state model

Use one explicit state model.

Recommended:

```ts
type FundManagerState =
  | "idle"
  | "files_selected"
  | "analysing"
  | "clean"
  | "review_required"
  | "evidence_required"
  | "failed";
```

Keep separate data for:

```ts
interface FundManagerViewModel {
  caseId?: string;
  state: FundManagerState;
  fund?: FundSummary;
  selectedFiles: File[];
  sources: SourceSummary[];
  progress?: AnalysisProgress;
  summary?: ReviewSummary;
  controls: ControlResult[];
  exceptions: ExceptionSummary[];
  evidence: EvidenceReference[];
  error?: UiError;
}
```

---

# 18. Component structure

Use the existing frontend approach in the repo. Do not introduce a large framework solely for the hackathon unless the project already uses it.

Recommended conceptual component breakdown:

```text
FundManagerShell
├── TopNavigation
├── ReviewHeader
├── FundMetadataForm
├── EvidenceUploadPanel
├── SourceInventory
├── AnalysisTimeline
├── ReviewSummaryCards
├── ControlReport
│    ├── ControlCategory
│    └── ControlDetailDrawer
├── ExceptionInbox
│    └── ExceptionDetailDrawer
├── EvidenceViewer
├── ReportDownloadActions
└── ClearReviewDialog
```

If the existing UI is plain HTML/CSS/JS, implement these as logical modules and render functions rather than introducing React.

---

# 19. API adapter

Create one frontend API module / adapter.

Conceptual methods:

```js
analyseFund(formData)
getFundCase(caseId)
getExceptions(caseId)
getEvidence(caseId)
downloadPdf(caseId)
downloadExcel(caseId)
downloadEvidencePack(caseId)
clearCase(caseId)
```

All request construction should live in this adapter.

Views must not contain hard-coded route construction.

---

# 20. Shared API contract

The UI and backend workstreams MUST converge on this contract.

## Analyse

```http
POST /api/fund-manager/analyse
Content-Type: multipart/form-data
```

Fields:

```text
files              repeated file field, one or more
fund_name          optional string
reporting_period   optional string
as_of_date         optional YYYY-MM-DD
```

A protected deployment may also require the existing Cherry demo token header.

### Accepted Phase 1 response — synchronous

```http
200 OK
```

```json
{
  "case_id": "CASE-2026-0091",
  "status": "review_required",
  "...": "full case payload"
}
```

### Accepted future response — asynchronous

```http
202 Accepted
```

```json
{
  "case_id": "CASE-2026-0091",
  "status": "processing"
}
```

The UI adapter MUST support both.

## Case

```http
GET /api/fund-manager/cases/{case_id}
```

## Exceptions

```http
GET /api/fund-manager/cases/{case_id}/exceptions
```

## Evidence

```http
GET /api/fund-manager/cases/{case_id}/evidence
```

## Downloads

```http
GET /api/fund-manager/cases/{case_id}/report.pdf
GET /api/fund-manager/cases/{case_id}/report.xlsx
GET /api/fund-manager/cases/{case_id}/evidence.zip
```

## Clear

```http
DELETE /api/fund-manager/cases/{case_id}
```

---

# 21. Canonical case payload

The UI should be able to render this shape.

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

  "sources": [
    {
      "id": "SRC-01",
      "filename": "Q2_NAV.xlsx",
      "type": "nav_workbook",
      "status": "processed",
      "confidence": 1.0,
      "sha256": "..."
    }
  ],

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

  "control_categories": [
    {
      "id": "nav_quality",
      "label": "NAV Quality",
      "controls_run": 8,
      "controls_passed": 7,
      "status": "review_required"
    }
  ],

  "controls": [],

  "exceptions": [],

  "evidence": []
}
```

Unknown / unavailable values should be `null` or omitted, never fabricated.

---

# 22. Canonical control result

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
    },
    {
      "label": "Investment performance",
      "operator": "+",
      "value": 2850000
    },
    {
      "label": "Distributions",
      "operator": "-",
      "value": 620000
    },
    {
      "label": "Fees",
      "operator": "-",
      "value": 100000
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

---

# 23. Canonical exception result

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

  "evidence_ids": [
    "EVD-001",
    "EVD-004"
  ]
}
```

---

# 24. Canonical evidence result

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

PDF example:

```json
{
  "evidence_id": "EVD-002",
  "source_id": "SRC-03",
  "filename": "Financial_Statements_Q2.pdf",
  "kind": "pdf",
  "reference": {
    "page": 18,
    "section": "Subsequent events"
  },
  "sha256": "..."
}
```

---

# 25. Mock-first development

The UI should not wait for backend completion.

Create fixtures such as:

```text
fixtures/fund-manager/case-processing.json
fixtures/fund-manager/case-clean.json
fixtures/fund-manager/case-review-required.json
fixtures/fund-manager/case-evidence-required.json
fixtures/fund-manager/case-failed.json
```

If the repo has a different fixture convention, follow it.

### Mock mode

Use a development-only flag, for example:

```text
?mock=fund-manager
```

or an existing environment mechanism.

Do not let mock data silently activate in production.

---

# 26. Error states

Handle:

- unsupported file type
- file too large
- zero files
- backend unavailable
- invalid demo token
- classification failure
- partially processed case
- report generation failure
- case not found
- delete/reset failure

Example:

```text
3 files were processed.
1 file could not be classified.

Unknown_Export.xlsx
Cherry could not determine a safe workflow for this workbook.

[ Keep review ] [ Remove file and rerun ]
```

Do not convert backend errors into false success states.

---

# 27. Accessibility

Required:

- keyboard-operable upload and navigation
- visible focus states
- semantic headings
- accessible status text, not colour alone
- `aria-live` for analysis status updates
- labels for all inputs
- accessible drawers/dialogs
- Escape closes modal/drawer where appropriate
- no hover-only functionality
- adequate contrast with Cherry branding

---

# 28. Responsive requirements

Desktop is the primary hackathon experience, but the UI must remain usable on tablet/mobile.

At narrower widths:

- summary cards wrap
- control table becomes stacked rows/cards
- exception detail becomes full-screen sheet
- navigation collapses
- file inventory remains readable
- download actions remain reachable
- no horizontal page overflow

---

# 29. Repository-change guidance

Before editing:

1. inspect current `main`;
2. identify existing FundOps static files and navigation;
3. preserve working API integrations;
4. do not delete existing backend endpoints;
5. reuse existing styles only where they support the simplified design;
6. remove or hide redundant four-manager UI components only after confirming no JavaScript depends on them.

Likely frontend areas already present in the repository include the main static HTML/CSS/JS, Ylookup result styling, and NAV-manager styling/scripts. Inspect actual current paths before editing.

Do not assume a file exists solely because it is named in this document.

---

# 30. Definition of done

The UI workstream is complete when:

- [ ] There is one coherent Fund Manager workspace.
- [ ] The user can upload mixed multiple source files.
- [ ] JSON is optional.
- [ ] The UI does not require manual workflow/agent selection.
- [ ] The UI shows classified sources from backend data.
- [ ] The UI renders analysis state.
- [ ] The UI renders a fund-level control summary.
- [ ] The UI renders backend-provided control details.
- [ ] The UI does no financial calculations.
- [ ] The UI shows one consolidated exception inbox.
- [ ] Each exception can be opened for reconciliation guidance.
- [ ] Evidence references are visible.
- [ ] PDF / Excel / evidence-pack download actions exist.
- [ ] Clear review/reset works.
- [ ] Cherry Money branding uses navy `#161E54` and red `#AD1929`.
- [ ] Mock fixture mode supports independent frontend development.
- [ ] Desktop and responsive layouts are usable.
- [ ] Existing backend behaviour is not broken.
- [ ] Lint / browser JS / relevant UI tests pass.

---

# 31. Codex operating instructions

When implementing this workstream:

1. **Stay inside UI ownership.**
2. Do not implement or modify financial control algorithms.
3. Do not fabricate backend results.
4. Do not create separate specialist-agent applications.
5. Use the shared API contract in this file.
6. If backend endpoints do not yet exist, use fixtures and an adapter.
7. Keep all backend-facing calls behind one API module.
8. Preserve backwards compatibility unless the task explicitly authorises removal.
9. Prefer small, reviewable commits.
10. Run existing frontend checks before proposing merge.
11. Summarise changed files, screenshots/states covered, and any API assumptions in the PR description.

---

## Final product principle

The user should experience:

> **One fund review, one control report, one exception inbox, one evidence trail.**

The internal agents can be sophisticated. The UI should remain simple.
