# Building Cherry CFO for Syndicate: From NAV Evidence to Human-Governed Sign-Off

> **Hackathon disclosure:** This document describes the Cherry CFO submission for **Syndicate by Maximor — Track 2: Autonomous Office of the CFO**. The repository includes pre-existing finance infrastructure; the post-kickoff build boundary is documented in `SYNDICATE_BUILD_LOG.md` and `PREEXISTING_CODE.md`.

## The problem

Fund controllers do not usually receive NAV evidence as one clean, machine-ready object.

A close pack can contain administrator workbooks, investor-level GL exports, statements, side-letter terms, bank/custodian evidence and supporting documents. Some arrive together; others arrive later. Before a controller can sign off, someone has to answer a chain of questions:

- What evidence did we receive?
- Which controls can actually run from it?
- Which balances foot?
- What is missing?
- Which breaks share a root cause?
- What needs to go back to the administrator?
- Does a human have enough support to approve the NAV?

That is the workflow we wanted Cherry CFO to automate.

## What we built

**Cherry CFO** is an autonomous finance agent with a judge-facing **NAV Quality Controller** workflow.

The operating model is:

```text
Evidence → Readiness → Deterministic NAV Controls → Exceptions
        → Agentic Investigation → Human Decision → Audit-Ready Review
```

The important design decision is that the model is not the financial authority.

> **AI understands. Deterministic controls verify. AI investigates. Humans decide.**

## Evidence first

The workbench accepts mixed evidence rather than requiring the user to manually map every file before starting.

Cherry classifies each source, validates recognised schemas and preserves evidence identity. Unknown or invalid sources remain visible as review items instead of being silently coerced into a convenient interpretation.

This gives the system a truthful answer to the first controller question: **what evidence do we actually have?**

## Readiness before reconciliation

A common automation mistake is to jump directly from upload to “analysis complete.”

Cherry adds a readiness stage first.

If an investor-level GL is present but an administrator NAV summary is not, Cherry can still perform the controls supported by the GL while explicitly showing the missing administrator summary as an evidence gap. It does not invent the missing NAV figures to make the workflow look complete.

That means the system can be useful with partial evidence without pretending partial evidence is complete evidence.

## Deterministic financial controls

Authoritative NAV checks run in deterministic Python code.

Depending on the evidence supplied, the control layer can support checks such as:

- balance-sheet footing;
- NAV bridge footing;
- independent NAV recalculation;
- investor-level GL validation;
- balance-sheet versus source-ledger checks;
- investor-capital reconciliation; and
- source-backed side-letter rule validation.

A language model can help choose or explain a supported workflow, but it cannot make an arithmetic break disappear.

## Agentic exception investigation

The agent becomes most valuable after the deterministic controls have done their work.

Instead of giving a controller a flat list of warnings, the agent can help consolidate:

- related findings;
- likely root causes;
- missing evidence;
- remediation steps; and
- the next supported human action.

This is the part of finance work where context and synthesis are valuable, while the underlying accounting result remains grounded in deterministic state.

## Human judgement as a product state

Human review is not a bolt-on “approve” button at the end.

The workflow explicitly supports decisions such as:

- Approve NAV;
- Approve with exception;
- Request evidence;
- Return to administrator; or
- Escalate.

The user can inspect the evidence, control state and agentic review before recording the outcome.

Cherry CFO does not silently amend an official NAV, post a correcting ledger entry or initiate a payment.

## A dynamic finance workspace

For Syndicate we wanted the interface to show how the finance work is connected, not just display a conventional dashboard.

The **Canvas** view turns evidence and generated control objects into a visual map. Documents, readiness, controls, exceptions, agent review and human decision can appear as connected components with inspectable provenance.

The **Document** view turns the same case state into a controller-style review report.

That dual representation makes the system useful for both investigation and communication:

- the canvas is good for understanding the work;
- the document is good for reviewing and discussing the result.

## How we built it

The repository uses:

- **Python / FastAPI** for the finance workflow and API;
- **Pydantic** for typed boundaries;
- **OpenPyXL and deterministic Python controls** for workbook and finance logic;
- **Google ADK / Gemini** for bounded model-backed planning and investigation where configured;
- **AO (Agent Orchestrator)** for coordinating hackathon engineering sessions;
- **Codex** for implementation/review work during those sessions;
- **Neatlogs** for agent observability when configured;
- **JavaScript / CSS** for the dynamic canvas workbench; and
- **Vercel** for the public Syndicate demo.

## What was difficult

### Defining the autonomy boundary

The hardest question was not “can an LLM read this?” It was:

> **When is the system allowed to continue, and when should it stop?**

Finance automation needs more than a confidence score. A confident explanation cannot waive a missing source, broken balance, unsupported rule or human authority boundary.

### Incomplete evidence

Real close packs arrive incrementally. Designing readiness separately from reconciliation allowed Cherry to remain useful without hiding missing evidence.

### Making provenance visible

A controller needs to know where a finding came from. Evidence lineage therefore had to be part of the product experience, not only a backend log.

### Hosted upload constraints

The anonymised Excel evidence used for testing can be large. The public Vercel demo therefore performs browser-side transport optimisation and can split evidence into smaller requests. That optimisation changes transport representation, not the product's authority model: the backend still validates the structured evidence it receives before enabling controls.

### Keeping the demo narrow

The repository contains multiple finance-control capabilities. For the final Syndicate story we deliberately narrowed the judge-facing experience to one workflow: **NAV Quality Control**.

## What we learned

### Useful autonomy is not maximum autonomy

The best finance agent is not the one that makes the most decisions. It is the one that removes repetitive investigation while making the remaining human decisions safer and faster.

### Workflow-shaped tools are easier to trust

Controllers think in actions such as “assess evidence,” “run NAV controls,” “investigate exceptions” and “record a decision.” Those are better agent boundaries than exposing low-level database or calculation operations directly.

### Evals should grade state, not eloquence

A finance agent should be evaluated on whether it ran the correct control, preserved evidence, blocked unsupported automation and required human review at the right moment — not just whether its explanation sounds plausible.

### Visualising agent work helps trust

When a reviewer can see:

```text
what came in → what was checked → what failed → why → what needs judgement
```

the system is easier to interrogate than a black-box conversational answer.

## AO and build provenance

AO was mandatory for Syndicate, so we kept explicit session and commit evidence rather than treating the orchestration tool as a last-minute demo dependency.

The build record is in:

- `SYNDICATE_BUILD_LOG.md`
- `SYNDICATE_TRACK2_PLAN.md`
- `SYNDICATE_DOMAIN_RESEARCH.md`
- `SYNDICATE_EVALS.md`
- `AO_SESSION_01_CFO_WORKFLOW.md`

The repository also records a pre-kickoff baseline so pre-existing work is not presented as hackathon-created work.

## What's next

The NAV Quality Controller is one Office of the CFO workflow. The same governed architecture can extend to:

- month-end close;
- account reconciliation;
- cash application;
- AP review;
- invoice processing;
- audit evidence gathering;
- variance investigation;
- management reporting; and
- controller close checklists.

For NAV specifically, the next steps are persistent workspaces, administrator/custodian connectors, a broader control library, policy/materiality configuration, multi-period comparisons, reviewer assignment and exportable evidence packs.

## Try it

**Live Syndicate workbench:** https://cherry-cfo-canvas.vercel.app

**Source branch:** `ui/syndicate-cfo-canvas`

Cherry CFO's goal is not to replace financial judgement. It is to make sure the controller spends that judgement on the cases that genuinely need it.
