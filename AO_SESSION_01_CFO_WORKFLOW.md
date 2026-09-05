# AO Session 01 — Cash Application Workflow Architect

## Purpose

Use this as the **first genuine AO session** for the Syndicate-specific build. Do not mark the session complete in `SYNDICATE_BUILD_LOG.md` until it has actually been run in AO and the session evidence has been captured.

## Prompt

We are building **Cherry CFO — Cash Application Exception Agent** for **Syndicate by Maximor, Track 2: Autonomous Office of the CFO**.

The hackathon judging guidance rewards deep understanding of a genuine Office of the CFO workflow, realistic accounting controls, intuitive human judgement and evidence that the solution could actually be used by accountants.

Our chosen workflow is **accounts-receivable cash application with short-pay and remittance exceptions**.

The system receives:

1. booked bank receipts;
2. remittance evidence from PDF/structured files;
3. open AR invoices;
4. versioned finance policy covering short-pay tolerances, reason codes and reviewer authority;
5. prior reviewed exception outcomes for analysis only.

The intended workflow is:

`bank receipt + remittance + open AR -> identify customer -> match invoices -> deterministic financial controls -> apply routine cash -> investigate exception -> policy check -> human review when required -> auditable AR outcome`

Important design constraints:

- This is an internal finance workflow, not a consumer banking/payment product.
- The agent must never invent a remittance reason, invoice or policy.
- Accounting arithmetic, idempotency, duplicate prevention and state invariants must be deterministic.
- AI can interpret unstructured evidence, choose tools, investigate context and prepare decision packets.
- A human review must state the accounting decision, evidence, policy, amount at risk and recommended next action — not merely a confidence score.
- Small short-pays may auto-resolve only if all conditions of an explicit approved policy are met.
- Repeated human decisions may cause the system to **propose** a policy change, but the agent must never silently alter an active finance policy.
- Human approval cannot bypass fundamental ledger invariants such as applying a receipt twice.
- Hackathon posting should be simulated state, not production writes to Cherry Money.

Read the repository's Syndicate planning files first:

- `SYNDICATE_TRACK2_PLAN.md`
- `SYNDICATE_DOMAIN_RESEARCH.md`
- `SYNDICATE_EVALS.md`
- `SYNDICATE_BUILD_LOG.md`

Then act as a **senior financial controller + agent-systems architect** and produce an implementation-ready design.

### Deliverables

1. **As-is human workflow**
   - Describe how a real AR cash-application analyst handles the process manually.
   - Identify which steps are repetitive, which are deterministic and which require judgement.

2. **Canonical accounting state machine**
   - Define states for receipt, application, exception and review.
   - Define valid transitions and forbidden transitions.
   - Make partial payment, short-pay, overpayment, unapplied cash and duplicate receipt distinct concepts.

3. **Evidence model**
   - Define the minimum fields needed for bank receipt, remittance, open AR item, policy, exception and review decision.
   - Specify evidence locators/hashes needed for auditability.

4. **Tool contracts**
   - Propose the smallest high-signal agent tool surface.
   - For each tool define purpose, inputs, outputs, deterministic vs model-based responsibility, and failure behaviour.
   - Prefer workflow-level tools over low-level CRUD endpoints.

5. **Policy and authority model**
   - Define how effective-dated/versioned short-pay policies work.
   - Define auto-resolution criteria.
   - Define reviewer authority and escalation.
   - Define how policy-change proposals remain separate from active policy.

6. **Human review UX contract**
   - Specify exactly what a controller should see and which decisions are allowed.
   - Give one concrete £500 short-pay review example.

7. **Accounting invariants**
   - List invariants that must always be enforced deterministically.

8. **Eval mapping**
   - Map the design to `CA-01` through `CA-13` in `SYNDICATE_EVALS.md`.
   - Flag any missing case or ambiguity in the current eval plan.

9. **Minimal implementation sequence**
   - Break the build into the smallest ordered tasks that can be completed during the hackathon.
   - Prioritise the 3-minute judge demo over non-essential infrastructure.

10. **Judge demo**
    - Define the exact 3-minute sequence for one clean multi-invoice case and one material short-pay case.

### Acceptance bar

Reject designs that:

- reduce the workflow to “upload invoice and ask AI what to do”;
- use an LLM for deterministic accounting arithmetic;
- auto-write off unsupported differences;
- conflate partial payment with deduction/write-off;
- lack versioned policy evidence;
- let an approval button bypass duplicate/idempotency controls;
- produce only narrative output without verifiable accounting state;
- add broad CFO features that distract from cash application.

Finish by giving a concise **BUILD-NOW checklist** for the next AO/code session.
