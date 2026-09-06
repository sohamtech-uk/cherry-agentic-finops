# Two-minute judge demo — Cherry CFO NAV Quality Controller

**Live demo:** https://cherry-cfo-canvas.vercel.app

The goal is to show one realistic Office of the CFO workflow, not every capability in the repository.

## 0:00–0:15 — The problem

> “Fund controllers receive a NAV close pack spread across administrator files, investor GLs, side-letter rules, statements and supporting evidence. The hard part is not just calculating a number — it is proving what can be checked, finding exceptions, and knowing when a human must step in.”

Open the Cherry CFO workbench.

## 0:15–0:30 — What Cherry CFO is

> “Cherry CFO is an autonomous NAV Quality Controller. It turns fragmented evidence into deterministic finance controls, agentic exception investigation and human-governed sign-off in one visual workspace.”

Point to **NAV Quality Controller** and the empty canvas.

## 0:30–0:50 — Upload mixed evidence

Click **Upload NAV documents**.

Upload multiple evidence sources. For the current anonymised demo pack this may include:

- `Investor-Level GL - Q2 activity - all entities (anonymised).xlsx`
- a loader/reference workbook;
- a supporting workbook;
- an administrator NAV summary if available for a full NAV review.

Say:

> “I can bring the close pack as it exists and select multiple files or batches. Cherry classifies every source, preserves evidence lineage and only enables controls supported by the evidence actually present.”

Click **Upload & classify**.

If a large workbook is used, point briefly to the real preparation stages. The Vercel demo may optimise the workbook locally for transport before upload; do not spend demo time explaining the hosting limit unless asked.

## 0:50–1:10 — Evidence readiness

When the canvas appears, point to the evidence nodes and **Evidence readiness**.

> “Cherry first asks what it can safely check. It does not invent missing evidence. If I have the investor GL but no administrator NAV summary, Cherry can still run a partial source review and explicitly records the missing summary as an evidence gap.”

This fail-closed behaviour is useful to show. Missing evidence should never appear as an unexplained pass.

## 1:10–1:32 — Deterministic controls

Click **Run NAV controls**.

> “The financial checks are deterministic. The model does not generate authoritative NAV numbers. It can coordinate and explain, but the accounting result comes from reproducible controls.”

Point to the control result / finding cards and, if useful, open the evidence inspector.

> “Every finding stays connected to the evidence and control state that produced it.”

## 1:32–1:47 — Agentic review

Click **Agent review**.

> “Once the controls identify issues, the agent consolidates findings, evidence gaps and likely remediation so the controller does not have to investigate every break manually. It cannot override the deterministic result.”

Show the agentic review / remediation node.

## 1:47–1:58 — Human decision

Click **Record decision** and show the available actions:

- Approve NAV
- Approve with exception
- Request evidence
- Return to administrator
- Escalate

Say:

> “Human judgement is a first-class workflow state. Cherry does the repetitive investigation, but the controller still owns financial sign-off.”

## 1:58–2:00 — Close

> “Cherry CFO does the finance work required to reach a decision — while humans remain responsible for the decisions that matter.”

## Three judge takeaways

If time is tight, make sure the judges remember only these three points:

1. **Evidence-aware automation** — Cherry runs only what the supplied evidence supports.
2. **Deterministic finance authority** — the LLM does not create the accounting truth.
3. **Human-governed judgement** — exceptions end in an explicit controller decision, not hidden autonomous action.

## Demo safety fallback

If an external model provider is unavailable during the demo, continue through evidence readiness and deterministic controls and explain:

> “The agentic explanation layer is unavailable, so Cherry fails closed. The deterministic financial workflow still works and nothing is silently approved.”

That behaviour is consistent with the product boundary and preferable to fabricating an agent result.
