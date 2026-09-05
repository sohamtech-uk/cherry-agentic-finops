# Cherry CFO — Syndicate Track 2 Plan

## Project

**Cherry CFO — Cash Application Exception Agent**

**Elevator pitch:** Cherry CFO applies incoming cash to open invoices, resolves routine remittance mismatches, and escalates only the short-pays and ambiguous cases that genuinely need controller judgement.

## Why we narrowed the project

Track 2 is not asking for a generic finance chatbot or a broad collection of CFO features. The judging guidance explicitly rewards a deep, realistic understanding of one Office of the CFO workflow, intuitive human judgement, and grounding in how accountants actually work.

For Syndicate we therefore focus on one specific workflow: **accounts-receivable cash application with short-pay and remittance exceptions**.

This is a real finance operations problem with a natural agentic shape:

- payments arrive in the bank;
- remittance details may arrive separately by PDF/email/portal/export;
- open invoices live in the ERP/accounting ledger;
- routine matches should be applied without analyst effort;
- deductions and short-pays need reason coding and policy checks;
- ambiguous or material cases require human judgement;
- every decision must remain explainable and auditable.

## Judge-facing workflow

```text
Bank receipt + remittance evidence + open AR invoices
                         |
                         v
                normalise evidence
                         |
                         v
              identify customer/account
                         |
                         v
                match open invoices
                         |
                         v
               deterministic controls
                  /              \
              clean             exception
                |                   |
                v                   v
           apply cash          investigate
                                    |
                                    v
                             check finance policy
                               /          \
                          permitted      judgement
                              |              |
                              v              v
                         resolve       human review
                              \              /
                               v            v
                         audit trail + AR outcome
```

## Office of the CFO users

### Cash application / AR analyst

Owns daily receipt matching, remittance gathering, unapplied cash, deduction coding and exception research. Cherry CFO should remove the repetitive detective work and leave the analyst with only genuinely unresolved items.

### Controller / finance manager

Owns policy, materiality, write-off authority, segregation of duties and close quality. Cherry CFO should bring the controller a compact decision packet, not raw data.

### Collections / deductions owner

Receives cases that should remain open or become disputes rather than being written off.

## Inputs

The Syndicate demo uses synthetic but realistic finance evidence:

1. **Bank receipts** — transaction id, booking date, payer, amount, currency, reference and booked status.
2. **Open AR ledger** — customer, invoice id, invoice date, due date, original amount, open balance, currency and status.
3. **Remittance evidence** — PDF/JSON/CSV containing invoice references, amounts paid and any deduction/discount reason.
4. **Finance policy** — versioned rules such as short-pay tolerance, permitted reason codes, materiality thresholds and approval authority.
5. **Prior review decisions** — used only to propose a future policy refinement; historical approvals never silently become policy.

## End-to-end workflow

### 1. Capture and normalise

Extract remittance data and normalise bank/ledger evidence into typed records. Preserve source identifiers and hashes so every conclusion can be traced back to evidence.

### 2. Identify the customer

Use high-signal fields such as payer identity, customer aliases, bank reference and remittance account number. A name-only match is not sufficient when multiple customers are plausible.

### 3. Match payment to invoice(s)

Support the realistic cases:

- one payment -> one invoice;
- one payment -> multiple invoices;
- partial payment;
- short payment;
- overpayment;
- missing invoice number;
- ambiguous remittance;
- duplicate bank receipt.

### 4. Run deterministic controls

The agent may reason about context, but financial application rules remain deterministic and testable. Controls include:

- receipt is booked, not pending/reversed;
- currency compatibility;
- invoice is open;
- no duplicate receipt/application;
- allocated amount cannot exceed available receipt amount;
- total allocations reconcile to the receipt or leave an explicit unapplied residual;
- referenced invoice/customer evidence is strong enough;
- short-pay handling follows the currently approved finance policy.

### 5. Handle short-pay / deduction exceptions

When the receipt is lower than the referenced invoice balance, Cherry CFO must determine what is known rather than invent a reason.

Example decision model:

```text
Invoice                              £10,000
Cash received                         £9,970
Short-pay                                £30
Remittance reason        FREIGHT_DAMAGED
Policy SHORTPAY-01      explicit approved reason + <= £50
Result                        auto-resolve £30
```

But:

```text
Invoice                              £10,000
Cash received                         £9,500
Short-pay                               £500
Policy SHORTPAY-01                         £50
Result                    controller review required
```

A small monetary difference does **not** automatically mean write-off. If the reason is absent, conflicting or unsupported by the remittance, the case should remain an exception even when the amount is below tolerance unless policy explicitly permits otherwise.

### 6. Human judgement

Human review is a first-class workflow state. The controller sees a concise decision packet:

- what payment arrived;
- which customer/invoice(s) Cherry CFO matched;
- what evidence supports the match;
- exact difference/deduction;
- relevant policy version and clause;
- why the agent cannot proceed autonomously;
- recommended next action;
- financial impact.

Available decisions:

- **Approve write-off / deduction** — only within the reviewer's authority;
- **Leave balance open** — collections should continue;
- **Create dispute / deduction case** — assign an owner and reason code;
- **Request evidence** — remittance or supporting documentation is insufficient;
- **Reject proposed match** — return the payment to unapplied cash for investigation.

The human never receives a vague "confidence low" alert without evidence.

### 7. Post outcome and preserve audit evidence

For the hackathon, posting can be a controlled simulated ledger state rather than a write to a real ERP. The important outcome is verifiable state:

- receipt applied/unapplied;
- invoice balance before/after;
- deduction/write-off amount and reason;
- policy version used;
- reviewer and decision where applicable;
- timestamped audit events;
- source evidence hashes/identifiers.

## Human judgement policy

Cherry CFO follows four levels:

### Level A — deterministic auto-apply

Exact/strong match; no policy exception; no ambiguity. No human needed.

### Level B — policy-bounded auto-resolution

A documented exception such as a small short-pay may be resolved automatically only when **all** conditions of an approved, versioned policy are satisfied and the supporting reason is evidenced.

### Level C — human review

Material, ambiguous, unsupported or policy-exception cases require an authorised reviewer.

### Level D — block

Duplicate payments, conflicting evidence, reversed/pending cash, currency/control failures or invalid state transitions are blocked. Human approval cannot simply override a broken accounting invariant.

## Learning without unsafe policy drift

The system may detect repeated human decisions and propose a policy amendment, for example:

> 8 freight-damage short-pays between £40 and £75 were approved by controllers this month. Consider changing SHORTPAY-01 from £50 to £75 for reason FREIGHT_DAMAGED.

The proposed policy never becomes active automatically. A controller must review and approve the new policy version. This gives us a realistic `learn -> propose -> approve -> improve` loop without letting an LLM silently alter financial controls.

## Agent tool surface

Keep the tool set small and domain-shaped:

- `cash_get_receipt_context(receipt_id)` — one high-signal packet with receipt, candidate customers and remittance references.
- `cash_extract_remittance(document)` — schema-validated remittance extraction with evidence locators and confidence.
- `ar_get_open_items(customer_id)` — relevant open invoices only.
- `cash_match_open_items(receipt, remittance, open_items)` — deterministic allocation candidates and residuals.
- `policy_get_shortpay_rule(customer_id, reason_code, as_of_date)` — exact approved policy version applicable to the case.
- `cash_evaluate_application(case)` — authoritative financial controls and allowed next states.
- `cash_create_exception(case, control_result)` — typed exception with owner, impact and required evidence.
- `cash_prepare_review_packet(exception_id)` — compact controller-facing decision context.
- `cash_record_review_decision(exception_id, decision)` — auditable review state transition.
- `cash_apply_simulated(case_id)` — idempotent simulated AR posting for the demo.
- `cash_propose_policy_change(history)` — evidence-backed proposal only; never activates policy.

## In scope for Syndicate

- synthetic bank receipts, remittances, open AR and finance policies;
- one realistic cash-application workflow end to end;
- exact and multi-invoice matching;
- short-pay/deduction exception handling;
- deterministic controls;
- controller review packet and review decisions;
- simulated AR state changes;
- audit trail/evidence lineage;
- eval suite covering common and adversarial cases;
- AO-assisted engineering throughout the Syndicate-specific build.

## Out of scope

- payment initiation;
- consumer banking, lending or trading;
- collections communication automation;
- a full ERP replacement;
- production posting to Cherry Money or another accounting platform;
- silently learning/changing accounting policy;
- login/auth/2FA work that does not improve the core finance workflow.

## Required judge scenarios

### Scenario A — straight-through cash application

A booked receipt and remittance strongly identify one or more open invoices. Amounts reconcile exactly. Cherry CFO applies the receipt in the simulated AR ledger and records why no human judgement was necessary.

### Scenario B — short-pay requiring controller judgement

A £10,000 invoice receives £9,500. The £500 deduction exceeds the approved £50 short-pay tolerance. Cherry CFO identifies the invoice correctly, preserves the £500 open balance, prepares the evidence/policy packet and routes a decision to the controller instead of inventing a write-off.

### Optional Scenario C — policy-bounded small short-pay

A £10,000 invoice receives £9,970 with an explicit approved deduction reason. The £30 difference is within the current policy. Cherry CFO resolves the difference automatically and records the policy version that authorised the action.

## Demo target

The 3-minute demo should prove:

1. **This is a real finance workflow, not a chatbot.** Show bank receipt + remittance + open AR.
2. **Autonomy is earned by evidence.** Show a clean application completing without review.
3. **Human judgement is intuitive.** Show the £500 short-pay case with a controller-ready decision packet.
4. **The result is auditable.** Show ledger state + policy + evidence trail.
5. **The system was engineered with AO.** Show genuine AO sessions used from architecture through eval/debugging.

Closing message:

> Cherry CFO applies the routine cash automatically, investigates the messy cases, and brings controllers only the decisions that require judgement.
