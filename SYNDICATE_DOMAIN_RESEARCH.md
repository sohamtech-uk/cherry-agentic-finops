# Syndicate Track 2 — Office of the CFO Domain Research

## Chosen workflow

**Accounts-receivable cash application, focused on short-pay and remittance exceptions.**

This is deliberately narrower than “autonomous CFO”. The project should demonstrate deep understanding of one real finance workflow and automate it end to end with intuitive human judgement.

## Why this is a genuine Office of the CFO pain point

Cash application is the process of taking incoming customer payments, finding the corresponding open receivables, applying the cash, coding deductions and resolving unapplied balances.

The apparent happy path is simple, but real finance teams encounter fragmented evidence:

- bank receipts arrive separately from remittance details;
- remittance may be in email, PDF, portal or spreadsheet form;
- a payment may cover one invoice or many;
- customers may short-pay or take deductions;
- invoice numbers can be missing or malformed;
- customer names in bank data may differ from ERP customer names;
- analysts must decide whether a difference is a legitimate deduction, write-off, dispute or unresolved balance;
- late or incorrect cash application affects AR ageing, collections and period-end reporting.

The agentic opportunity is not merely OCR or fuzzy matching. It is to perform the analyst's investigation across evidence and policy, complete routine applications safely, and prepare only genuine judgement cases for a controller.

## External grounding

### Maximor — direct sponsor/product signal

Maximor publicly positions cash application, automated close and reconciliation as core Office of the CFO workflows. Its product examples explicitly distinguish routine policy-bounded outcomes from exceptions that need human judgement, and emphasise evidence/audit trails and no silent posting without the right approval.

Useful references:

- https://www.maximor.ai/
- https://www.maximor.ai/cfo
- https://www.maximor.ai/automated-close
- https://www.maximor.ai/why

Key implications for Cherry CFO:

1. **Own a specific workflow end to end**, rather than returning an answer.
2. **Use approved policy as an explicit control surface.**
3. **Escalate with context**: what happened, why it was flagged and what is recommended.
4. **Leave evidence behind** for every automated and human action.
5. **Improve carefully**: repeated human judgements may inform a proposed policy update, but accounting policy should not mutate silently.

### Cash application process research

Industry descriptions of cash application consistently identify the same workflow stages:

1. collect payment and remittance data;
2. link remittance to the payment;
3. match the payment to open invoices;
4. identify/categorise deductions or short-pays;
5. handle exceptions;
6. post the verified application to the ERP/accounting ledger.

References:

- https://www.highradius.com/resources/Blog/cash-application/
- https://www.highradius.com/resources/Blog/cash-application-automation/
- https://www.blackline.com/campaign/i2c/lb/

These sources are vendor material, so do not treat marketing metrics as independent evidence. The useful grounding is the operational workflow and recurring exception types.

## Accountant's mental model

A realistic automation must preserve the accounting state, not just generate a plausible explanation.

For each receipt, an analyst/controller ultimately needs to know:

- **What cash actually arrived?**
- **Which legal/customer account does it belong to?**
- **Which open invoice balance(s) should it reduce?**
- **Does the remittance explain the allocation?**
- **Does the sum of allocations equal the receipt?**
- **If not, what is the residual and why?**
- **Is the residual allowed by policy?**
- **Who has authority to approve the treatment?**
- **What remains open in AR after the decision?**
- **Can an auditor reproduce the decision from source evidence and policy?**

If the demo does not answer these questions, it is not deep enough for Track 2.

## Roles and segregation of duties

### AR cash application analyst

Typical responsibility:

- gather remittances;
- match receipts to customers/invoices;
- code deductions;
- clear routine items;
- investigate unapplied cash;
- send unresolved items to collections/deductions/controllers.

### Controller / finance manager

Typical responsibility:

- approve policy and materiality thresholds;
- approve write-offs/deductions within delegated authority;
- ensure the ledger remains correct;
- review unusual or material exceptions;
- maintain auditability and internal control.

### Collections / deduction specialist

Typical responsibility:

- pursue unpaid balances;
- investigate customer deductions/disputes;
- keep valid residual balances open until resolved.

The automation should not collapse these roles into one all-powerful AI actor.

## Detailed exception taxonomy

### Exact match

Payment and remittance identify the same open invoice(s), allocations equal the booked receipt, and all controls pass.

**Expected result:** straight-through application.

### Multi-invoice remittance

One receipt covers several invoices.

**Expected result:** allocate line by line and verify that the total allocation equals the receipt before applying.

### Partial payment

Payment is lower than an invoice and remittance explicitly says it is a partial payment, with no deduction/write-off claim.

**Expected result:** apply the received amount and leave the remaining invoice balance open. Do not classify the residual as a write-off.

### Short-pay / deduction

Payment is lower than the referenced invoice and the customer claims a deduction/discount.

**Expected result:** identify reason, validate evidence, apply approved policy, and route material/unsupported cases for review.

### Missing remittance

A receipt exists but there is no reliable invoice allocation evidence.

**Expected result:** keep the receipt unapplied or on-account according to policy; request evidence rather than guessing.

### Ambiguous customer

Bank payer name maps to multiple ERP customers or a parent/child account structure.

**Expected result:** require stronger evidence before application.

### Duplicate receipt/application

The same transaction id or materially identical booked receipt has already been processed.

**Expected result:** block. A human should not be able to override this by simply pressing Approve.

### Overpayment

Receipt exceeds the referenced open balance.

**Expected result:** apply only supported amounts. Residual becomes unapplied/on-account or refund review according to policy. Never invent an invoice to consume the residual.

### Currency mismatch

Receipt currency and invoice currency differ without an approved FX settlement rule.

**Expected result:** route for review with exact currencies/amounts and applicable policy context.

### Reversed/pending cash

Bank transaction is pending, reversed or not settled.

**Expected result:** block application until the cash state is eligible.

## Human judgement design

The judging guidance asks whether human judgement is genuinely intuitive. The review experience should therefore present the accounting decision, not an AI confidence score.

Bad review prompt:

> Confidence 0.61. Approve?

Good review packet:

> Receipt RCPT-1042: £9,500 from Northstar Retail.
>
> Remittance references INV-2208 (£10,000) and reason `DAMAGED_GOODS`.
>
> Proposed application: £9,500 to INV-2208; £500 residual remains.
>
> Policy SHORTPAY-01 allows automatic write-off only when the evidenced deduction is <= £50.
>
> This case exceeds policy by £450.
>
> Recommended action: leave £500 open and create a deduction case, or approve a £500 write-off if within your delegated authority.

The reviewer should be able to inspect the remittance evidence and policy version used.

## Policy model

A policy is explicit, versioned and effective-dated.

Example:

```json
{
  "policy_id": "SHORTPAY-01",
  "version": 3,
  "effective_from": "2026-09-01",
  "max_auto_writeoff_gbp": 50,
  "allowed_reason_codes": ["FREIGHT_DAMAGE", "ROUNDING"],
  "requires_explicit_remittance_reason": true,
  "controller_approval_limit_gbp": 1000
}
```

Important rules:

- the agent must retrieve the policy applicable on the decision date;
- unsupported deductions never become valid because the amount is small;
- a reviewer cannot approve above their authority in the demo state machine;
- policy changes are separate governed actions;
- historical review patterns can generate a **proposal**, not an automatic rule change.

## Accounting invariants

These should be enforced deterministically and covered by tests:

1. A bank receipt cannot be applied twice.
2. A pending/reversed receipt cannot be applied.
3. Total allocated cash cannot exceed the eligible booked receipt.
4. An allocation cannot reduce an invoice below zero.
5. Closed invoices cannot receive a new application unless a controlled reopening workflow exists.
6. A short-pay write-off requires an approved reason/policy path.
7. Residual balances remain explicit; the agent cannot hide them through rounding or invented allocations.
8. Human approval cannot bypass fundamental ledger invariants.
9. Every state-changing action has an audit event.
10. Every policy-bounded action records the policy id/version used.

## What “agentic” means here

The LLM/agent adds value where evidence is messy and investigation is contextual:

- extract remittance details from unstructured documents;
- choose which high-level finance tool to call next;
- resolve customer aliases using evidence;
- explain why deterministic controls failed;
- assemble the relevant evidence and policy into a controller decision packet;
- recommend the correct next workflow state;
- analyse repeated reviewed exceptions and propose a policy improvement.

The agent is **not** used for arithmetic that a deterministic function can do better.

## Minimal realistic tool design

Anthropic's guidance on agent tools recommends a few high-impact tools aligned to natural workflow subdivisions rather than exposing many low-level endpoints. Reference:

- https://www.anthropic.com/engineering/writing-tools-for-agents

Apply that principle here:

- return one relevant receipt/customer/remittance context packet instead of forcing the agent to enumerate full bank and customer tables;
- return only relevant open AR items for the identified customer;
- put allocation arithmetic and invariant checking inside deterministic tools;
- make policy lookup explicit and narrow;
- make review packet generation a dedicated finance-domain operation.

## Demo data set

Use synthetic data that looks like an accountant could actually work with:

### Customer

Northstar Retail Ltd — `CUST-0042`

### Open AR

- `INV-2208` — £10,000 open
- `INV-2214` — £2,400 open

### Clean receipt

- `RCPT-1041` — £12,400 booked
- Remittance: `INV-2208 £10,000 + INV-2214 £2,400`
- Outcome: apply both invoices, zero residual.

### Material short-pay

- `RCPT-1042` — £9,500 booked
- Remittance: `INV-2208`, claimed `DAMAGED_GOODS £500`
- Current policy auto threshold: £50
- Outcome: apply £9,500, preserve £500 open balance, create exception, controller review.

### Policy-bounded short-pay

- `RCPT-1043` — £9,970 booked
- Remittance: `INV-2208`, `FREIGHT_DAMAGE £30`
- Policy permits explicit `FREIGHT_DAMAGE` <= £50
- Outcome: apply £9,970 and policy-bounded £30 deduction/write-off; full audit trail.

## Novelty to emphasise

The novelty is **not** “AI matches invoices”. Existing software already does matching.

The stronger story is:

> Cherry CFO turns cash application into an evidence-driven state machine. It uses agents for investigation and context gathering, deterministic accounting controls for authority, and versioned finance policy to decide whether a case can run automatically or needs controller judgement. It then learns from reviewed exception patterns only by proposing—not silently making—policy changes.

That is a realistic model for finance autonomy because it combines speed with auditability and controlled judgement.
