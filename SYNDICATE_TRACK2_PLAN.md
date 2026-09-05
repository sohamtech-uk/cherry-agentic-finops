# Cherry CFO — Syndicate Track 2 Plan

## Project

**Cherry CFO — Autonomous Finance Agent**

**Elevator pitch:** Cherry CFO autonomously processes finance documents, reconciles accounts and investigates exceptions—completing routine finance work end to end while escalating only decisions that need human judgement.

## Why this fits Track 2

Syndicate Track 2 asks for an agent that automates a real accounting, finance or treasury workflow end to end, including exceptions and human review. Cherry CFO will demonstrate exactly that with a focused invoice/document-to-reconciliation workflow.

## Judge-facing workflow

```text
Finance document
      |
      v
AI extraction
      |
      v
Candidate bank transactions
      |
      v
Deterministic controls
   /            \
pass            exception
 |                 |
 v                 v
auto-reconcile   investigate cause
 |                 |
 |                 v
 |             human review
  \               /
   v             v
 audit evidence + close summary
```

## In scope for Syndicate

- A clear Cherry CFO judge-facing workflow and UI.
- Finance-document ingestion and structured extraction.
- Candidate bank-transaction search/matching.
- Deterministic reconciliation controls.
- Explicit exception classification and explanation.
- Human review with approve/reject/request-evidence outcomes where judgement is required.
- Evidence/audit output for the completed case.
- A compact close/month-end summary of completed and unresolved work.
- Reliability tests covering clean and adverse scenarios.
- AO-assisted engineering throughout the Syndicate-specific build.

## Out of scope

- Payment initiation or authorisation.
- Consumer banking, lending, trading or investment advice.
- A full ERP/accounting-system rewrite.
- Unbounded autonomous posting to production financial systems.
- Sponsor integrations that do not improve the core CFO workflow.

## Core tools / capabilities

The Syndicate workflow should expose a small, auditable tool surface. Exact names can change during implementation, but the responsibilities should remain clear:

- `extract_finance_document()` — return schema-validated document fields and confidence.
- `find_candidate_transactions()` — retrieve plausible transaction candidates.
- `evaluate_reconciliation()` — run deterministic amount/date/reference/duplicate controls.
- `create_exception()` — create a structured exception with reason, severity and owner.
- `investigate_exception()` — summarise available evidence and recommend the next action without overriding controls.
- `request_human_review()` — route genuinely ambiguous or policy-bound cases to a person.
- `record_review_decision()` — capture approve/reject/request-evidence outcomes.
- `build_audit_evidence()` — preserve inputs, decisions and outcome evidence.
- `build_close_summary()` — summarise reconciled, open and escalated work.

## Control policy

A case may auto-reconcile only when required evidence passes deterministic checks. AI-generated reasoning may explain or prioritise a case but cannot convert insufficient evidence into a successful reconciliation.

Examples that must block automatic reconciliation:

- amount mismatch beyond tolerance;
- duplicate transaction candidate;
- missing or weak transaction reference where a strong reference is required;
- conflicting candidate transactions;
- low-confidence document extraction for a material field;
- missing evidence required by policy.

## Acceptance criteria

### Clean case

Given a valid finance document and one strongly matching booked bank transaction:

- document fields are extracted;
- the correct transaction is selected;
- deterministic controls pass;
- the workflow reaches a reconciled/completed state;
- audit evidence explains why no human intervention was required.

### Exception case

Given a finance document and evidence containing an important mismatch or ambiguity:

- the workflow does not auto-reconcile;
- the exception type and reason are explicit;
- the available evidence is summarised;
- a next action is recommended;
- the case reaches human review;
- the resulting review decision is captured in the audit trail.

## Reliability scenarios

At minimum, test:

1. clean exact match;
2. amount mismatch;
3. duplicate bank transaction ID/candidate;
4. missing or weak reference;
5. two plausible candidates;
6. low-confidence extraction;
7. human approval;
8. human rejection / request for evidence.

## AO session plan

Use separate, genuine AO sessions for meaningful phases of the build so the final video shows progression rather than artificial session count:

1. workflow architecture and acceptance criteria;
2. tool and state-machine design;
3. finance controls;
4. exception investigator;
5. human-review UX and auditability;
6. adversarial QA;
7. failure analysis and reliability improvement;
8. demo/submission hardening.

## Optional partner integrations

### TensorMux

Use only if it materially helps the exception-investigation or evaluator layer. Deterministic finance controls remain authoritative.

### Neatlogs

Use if it can clearly demonstrate a traceable `failure -> diagnosis -> AO-driven fix -> successful rerun` story without destabilising the core demo.

### Dodo Payments

Not required for this workflow. Avoid adding payment functionality merely for sponsor visibility because the selected track is focused on internal finance operations.

## Demo target

The final demo should prove two things quickly:

1. **Autonomy when evidence is sufficient.**
2. **Restraint and useful escalation when evidence is not sufficient.**

Closing message:

> Cherry CFO does the repetitive finance work. Humans stay in control of the decisions that matter.
