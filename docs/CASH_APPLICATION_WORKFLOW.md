# Cherry CFO cash-application workflow contract

Status: implementation contract for Syndicate Track 2, AO session `cherry-agentic-finops-2`.

This document is normative for the hackathon cash-application build. `MUST`, `MUST NOT`, and
`SHOULD` identify requirements. Where this contract differs from the repository's pre-existing
invoice-to-bank reconciliation workflow, this contract governs the new Cherry CFO workflow.

## Scope and control boundary

Cherry CFO applies incoming accounts-receivable cash to open invoices in a **simulated ledger**.
It may extract and organise evidence, propose matches, explain exceptions, and prepare decisions.
It does not initiate payments, modify production Cherry Money data, create unsupported accounting
records, or grant itself financial authority.

The implementation boundary is:

```text
model-assisted                 deterministic                       governed
evidence extraction  ->  matching, arithmetic, controls  ->  simulated post or human decision
```

The existing `app.workflow.WorkflowEngine` models an invoice-to-bank reconciliation and has a
generic approval transition. It is not safe to extend for AR cash application: its bank model does
not represent settlement status, its approval model has no delegated authority, and its state does
not distinguish cash, invoice residuals, or write-offs. The new implementation SHOULD live in an
isolated `app/cash_application/` package. It may reuse the decimal-money and hash-chain patterns,
but not the existing generic approval path.

## 1. As-is human workflow

| Step | What an AR analyst does | Nature | Cherry CFO boundary |
| --- | --- | --- | --- |
| 1 | Pull settled credits from the bank feed | Repetitive + deterministic | Ingest; reject pending/reversed cash |
| 2 | Find remittance in email, PDF, portal, or export | Repetitive; judgement when absent/conflicting | Extract only located claims; represent absence |
| 3 | Identify the legal customer account | Mixed | Use unique account/invoice/bank-alias evidence; never name-only |
| 4 | Pull that customer's open invoices | Repetitive + deterministic | Return open, versioned AR items only |
| 5 | Allocate the receipt across referenced invoices | Arithmetic is deterministic; reference interpretation may be contextual | Propose from evidence; calculate in code |
| 6 | Classify any difference | Judgement grounded in remittance | Keep partial payment, deduction, and overpayment distinct |
| 7 | Check effective policy and materiality | Deterministic | Resolve only when every policy condition passes |
| 8 | Post routine applications | Deterministic | Idempotent simulated mutation only |
| 9 | Investigate unsupported/material differences | Judgement | Create a typed exception and evidence request/recommendation |
| 10 | Approve treatment or route to collections/deductions | Human judgement within delegated authority | Record a bounded decision; re-run controls before posting |
| 11 | Retain support for audit/close | Repetitive + deterministic | Hash-linked evidence, policy, state deltas, and actor trail |

The agent removes searching and packet assembly. It does not replace the controller's judgement on
material treatment or the ledger's enforcement of accounting invariants.

## 2. Canonical vocabulary and amount equations

All money is an ISO-4217 currency plus a fixed-point decimal string at currency precision. Binary
floats are forbidden. Every mutable aggregate has an integer `version`; writes use compare-and-set.

These concepts are deliberately different:

- **Partial payment:** remittance explicitly says the cash is a payment on account of an invoice,
  with no claim that the unpaid invoice balance should be removed. Cash is applied; the invoice
  stays open. No exception is required when the reference is otherwise valid.
- **Short-pay/deduction:** remittance claims that some invoice balance should be deducted, credited,
  or written off. The claimed amount remains open until policy or an authorised decision permits an
  adjustment.
- **Overpayment:** receipt cash exceeds the total supported invoice allocation. Supported invoice
  cash may be applied; excess is a **receipt residual**, not an invoice adjustment.
- **Unapplied cash:** booked cash not allocated to an invoice. It remains a receipt asset/liability
  workflow item; it is never consumed by an invented invoice.
- **Duplicate:** the same immutable bank receipt identity was already ingested or applied. A similar
  amount/date/reference is only a suspected duplicate and cannot, by itself, prove duplication.

The posting equations are:

```text
receipt_amount = sum(cash_allocation_lines) + receipt_unapplied_residual

invoice_open_before = cash_applied + authorised_adjustment + invoice_open_after
```

An invoice shortfall is never represented as a receipt residual. A receipt excess is never
represented as a write-off.

## 3. Canonical accounting state machines

### 3.1 Receipt aggregate

Settlement and allocation are orthogonal fields; combining them would make a pending but
"unapplied" receipt look eligible.

`settlement_status`:

- `PENDING` — not eligible for any application.
- `BOOKED` — eligible if every other control passes.
- `REVERSED` — not eligible. If reversal arrives after a simulated post, create a compensating
  reversal case; never delete the original application or audit trail.

Allowed settlement transitions are `PENDING -> BOOKED`, `PENDING -> REVERSED`, and
`BOOKED -> REVERSED`, and only bank-source ingestion may perform them.

`allocation_status`:

- `UNAPPLIED` — no posted cash allocation.
- `HELD` — a proposal reserves the receipt while evidence/review is pending; no ledger mutation.
- `PARTIALLY_APPLIED` — some booked cash is posted; a receipt residual remains explicit.
- `APPLIED` — all booked cash is posted to supported invoices. An invoice may still have an open
  balance after a partial payment or unresolved short-pay.

Allowed allocation transitions:

```text
UNAPPLIED -> HELD -> UNAPPLIED
UNAPPLIED -> HELD -> PARTIALLY_APPLIED
UNAPPLIED -> HELD -> APPLIED
UNAPPLIED -> PARTIALLY_APPLIED
UNAPPLIED -> APPLIED
```

`PARTIALLY_APPLIED -> APPLIED` requires a new supported allocation and a fresh control result.
Posted states cannot return directly to `UNAPPLIED`; that requires a future compensating
unapplication workflow. A duplicate processing attempt does not change the canonical receipt; it
creates a blocked attempt against the already-known receipt identity.

### 3.2 Application aggregate

`application_kind` is one of `EXACT`, `MULTI_INVOICE`, `PARTIAL_PAYMENT`, `SHORT_PAY`, or
`OVERPAYMENT`. `residual_kind` is one of `NONE`, `INVOICE_OPEN_PARTIAL`, `CLAIMED_DEDUCTION`, or
`RECEIPT_UNAPPLIED`. These classifications are stored independently of status.

Statuses:

- `DRAFT` — evidence-linked allocation proposal; no mutation.
- `EVIDENCE_REQUIRED` — a required fact is absent or conflicting.
- `CONTROL_BLOCKED` — a fundamental invariant failed.
- `REVIEW_REQUIRED` — controls allow a human decision, but not autonomous treatment.
- `READY_TO_POST` — all controls and, when needed, a valid bounded decision pass.
- `POSTED_SIMULATED` — idempotent simulated ledger mutation completed.
- `REJECTED` — reviewer rejected the proposed match before posting.
- `SUPERSEDED` — immutable prior proposal replaced by a new evidence/proposal version.

Valid transitions:

| From | To | Required cause |
| --- | --- | --- |
| `DRAFT` | `EVIDENCE_REQUIRED` | deterministic missing/conflicting-evidence result |
| `DRAFT` | `CONTROL_BLOCKED` | deterministic invariant failure |
| `DRAFT` | `REVIEW_REQUIRED` | valid match with material/manual treatment needed |
| `DRAFT` | `READY_TO_POST` | exact/partial/overpay cash or policy-bounded treatment passes |
| `EVIDENCE_REQUIRED` | `SUPERSEDED` | new source evidence; create a new `DRAFT` version |
| `REVIEW_REQUIRED` | `EVIDENCE_REQUIRED` | authorised reviewer requests specified evidence |
| `REVIEW_REQUIRED` | `REJECTED` | authorised reviewer rejects match before posting |
| `REVIEW_REQUIRED` | `READY_TO_POST` | allowed decision passes authority and fresh controls |
| `READY_TO_POST` | `POSTED_SIMULATED` | atomic idempotent simulated post |
| `READY_TO_POST` | `SUPERSEDED` | source/policy/ledger version changed before post |

`CONTROL_BLOCKED` and `POSTED_SIMULATED` are terminal for that application version. Fixing a
blocked control creates a new evidence/application version; a human cannot transition the blocked
version to ready. Material short-pay cash is held until a valid residual-treatment decision. This
keeps `REJECT_MATCH` meaningful and makes CA-05 assertions explicit: no pre-review ledger mutation;
after `LEAVE_BALANCE_OPEN` or `CREATE_DISPUTE`, post supported cash and preserve the residual.

### 3.3 Exception aggregate

Types: `MISSING_REMITTANCE`, `AMBIGUOUS_CUSTOMER`, `CONFLICTING_EVIDENCE`,
`UNSUPPORTED_DEDUCTION`, `MATERIAL_SHORT_PAY`, `OVERPAYMENT_RESIDUAL`, `CURRENCY_MISMATCH`,
`INELIGIBLE_RECEIPT`, `DUPLICATE_RECEIPT`, `CLOSED_INVOICE`, `AUTHORITY_EXCEEDED`, and
`STALE_STATE`.

Statuses:

- `OPEN`
- `WAITING_EVIDENCE`
- `WAITING_REVIEW`
- `ESCALATED_AUTHORITY`
- `COLLECTIONS_OPEN`
- `DISPUTE_OPEN`
- `RESOLVED`
- `BLOCKED`

`OPEN` must immediately route to one of the other states. `WAITING_EVIDENCE` may return to `OPEN`
only with new evidence. `WAITING_REVIEW` may become `ESCALATED_AUTHORITY`, `COLLECTIONS_OPEN`,
`DISPUTE_OPEN`, `WAITING_EVIDENCE`, or `RESOLVED`. `ESCALATED_AUTHORITY` may return to
`WAITING_REVIEW` only after assignment to a reviewer with sufficient current authority.
`COLLECTIONS_OPEN` and `DISPUTE_OPEN` remain open operational outcomes, not write-offs.
`BLOCKED` cannot be overridden; corrected inputs create a new application attempt. Every transition
records the exact reason and prior/new versions.

### 3.4 Review aggregate

Statuses are `REQUESTED`, `ASSIGNED`, `ESCALATED`, `DECIDED`, and `SUPERSEDED`.

Allowed decisions are intentionally accounting-specific:

- `APPROVE_WRITE_OFF` — exact amount/reason, only if manual policy and reviewer authority allow it.
- `LEAVE_BALANCE_OPEN` — post supported cash and retain invoice residual for collections.
- `CREATE_DISPUTE` — post supported cash, retain residual, owner and evidenced reason required.
- `REQUEST_EVIDENCE` — identify the exact missing document/claim.
- `REJECT_MATCH` — release held cash to unapplied status; no invoice mutation.

An authority failure does not create a decision: record `review.authority_denied`, keep the review
open, and move it to `ESCALATED`. A review becomes `SUPERSEDED` if its application, evidence,
policy, or ledger version changes. Free-text comments never encode the financial action.

### 3.5 End-to-end outcomes

| Case | Receipt outcome | Application outcome | Invoice/residual outcome | Exception/review |
| --- | --- | --- | --- | --- |
| Exact/multi | `APPLIED` | `POSTED_SIMULATED` | referenced invoices reduced; no residual | none |
| Explicit partial | `APPLIED` | `POSTED_SIMULATED` | invoice remains open | none |
| Policy short-pay | `APPLIED` | `POSTED_SIMULATED` | cash + authorised adjustment closes invoice | resolved by policy |
| Material short-pay | `HELD`, then `APPLIED` after valid decision | `REVIEW_REQUIRED`, then posted/rejected | cash applied only after decision; claimed amount stays open unless authorised | review/dispute/collections |
| Missing allocation evidence | `HELD` or `UNAPPLIED` | `EVIDENCE_REQUIRED` | unchanged | waiting evidence |
| Overpayment | `PARTIALLY_APPLIED` | `POSTED_SIMULATED` | invoice closes; receipt excess stays unapplied | residual review/on-account policy |
| Duplicate/ineligible/currency block | unchanged | `CONTROL_BLOCKED` | unchanged | blocked |

## 4. Evidence model

Every material claim carries an `EvidenceRef`; copying a value into an agent message is not
evidence.

```text
EvidenceRef
  evidence_id             stable internal id
  source_type             BANK_FEED | REMITTANCE_PDF | REMITTANCE_JSON | AR_LEDGER | POLICY
  source_system           origin, e.g. SYNTHETIC_BANK
  source_object_id        immutable upstream document/row/version id
  source_sha256           SHA-256 of canonical source bytes/record
  locator                 page+bbox, CSV row+columns, JSON pointer, or ledger record id
  claim_path              schema field supported by this location
  captured_at             timestamp
  parser                   parser/model name and version, or DIRECT_SOURCE
  extraction_confidence   nullable; never substitutes for a locator
```

Minimum aggregate fields:

| Aggregate | Required fields |
| --- | --- |
| `BankReceipt` | `receipt_id`, `source_system`, `source_transaction_id`, `booking_date`, optional `value_date`, `payer_name`, optional masked `payer_account_token`, `amount`, `currency`, `reference`, `settlement_status`, `allocation_status`, `version`, field-level/source `EvidenceRef` |
| `Remittance` | `remittance_id`, `document_id`, optional evidenced `customer_account_id`, optional `payment_reference`, `lines[]`, `received_at`, `source_sha256`, parser/version; each line has raw `invoice_reference`, `cash_amount`, `intent` (`PARTIAL_PAYMENT`, `DEDUCTION`, `UNKNOWN`), optional raw deduction reason/amount, and locators |
| `OpenARItem` | `invoice_id`, `customer_id`, `invoice_date`, `due_date`, `original_amount`, `open_balance`, `currency`, `status`, `ledger_version`, `as_of`, ledger `EvidenceRef` |
| `CashApplication` | ids/versions for case, receipt, remittance and AR snapshot; classification; allocation lines; receipt/invoice residuals; status; deterministic `control_result_id`; optional policy/review ids; before/after projections; idempotency key |
| `ShortPayPolicy` | `policy_id`, `version`, `status=APPROVED`, `effective_from`, optional `effective_to`, currency, `max_auto_amount`, allowed auto reason codes, explicit-reason/evidence flags, manual action rules, authority matrix, approving actor/time, source hash/locator |
| `Exception` | `exception_id`, type/status, application/version, amount/currency, evidenced raw/canonical reason or null, failed control codes, missing evidence list, owner role/id, recommendation, evidence refs, timestamps/version |
| `ReviewDecision` | `review_id`, application/version, reviewer id/role, authority snapshot/version, decision enum, exact amount/currency, canonical reason or null, rationale, owner when routed, decided_at, policy/evidence refs, idempotency key |
| `AuditEvent` | event/sequence ids, aggregate id/version before/after, actor type/id, action, timestamp, input/output evidence refs, policy/control/review ids, state delta, idempotency key, previous/event hashes |

Rules for absence and conflicts:

- Missing values are `null` plus a typed evidence gap, never guessed defaults.
- A model-extracted invoice or reason is usable only with a locator in the hashed source.
- Reason normalisation stores both `raw_reason` and `canonical_reason_code` plus mapping version.
  An unmapped raw reason remains `canonical_reason_code=null`.
- Candidate invoice ids must come from the retrieved AR snapshot, never model-generated text.
- Contradictory remittance versions remain separate evidence objects and force
  `CONFLICTING_EVIDENCE`; later arrival does not silently overwrite earlier evidence.
- The policy reference must identify the single approved version effective at `decision_at`.

## 5. Deterministic control and policy model

### 5.1 Control result

`cash_evaluate_application` returns immutable results with:

```text
control_result_id, evaluated_at, input_versions, input_hash,
checks[{code, outcome: PASS|EVIDENCE_REQUIRED|REVIEW|BLOCK, explanation, evidence_refs}],
disposition: AUTO_APPLY|POLICY_RESOLVE|EVIDENCE_REQUIRED|REVIEW_REQUIRED|BLOCK,
allowed_next_states, policy_ref|null, expires_on_input_change
```

Checks run in this order so an approval-worthy exception is never evaluated before a hard block:

1. evidence hashes and expected aggregate versions are valid;
2. receipt is `BOOKED` and amount is positive;
3. `(source_system, source_transaction_id)` is unique and not previously posted;
4. customer identity is supported by a unique high-signal reference; name similarity alone fails;
5. every invoice exists in the retrieved snapshot, is open, and still has the expected version;
6. receipt and invoice currency agree, unless an approved FX settlement rule and rate evidence exist;
7. allocations refer only to evidenced remittance/AR items;
8. receipt and invoice equations foot and no balance becomes negative;
9. residual classification is explicit and supported by remittance intent;
10. any adjustment satisfies the effective policy or requires a permitted manual action;
11. any human decision is within current delegated authority;
12. idempotency key is unused and all versions still match at commit time.

`BLOCK` outranks every other disposition, then `EVIDENCE_REQUIRED`, `REVIEW_REQUIRED`,
`POLICY_RESOLVE`, and `AUTO_APPLY`. A control result is invalid as soon as an input version changes.

### 5.2 Auto-resolution criteria

A short-pay can be `POLICY_RESOLVE` only when **all** are true:

1. all fundamental controls 1-9 and 12 pass;
2. remittance explicitly classifies a deduction and locates its amount and reason;
3. the canonical reason is in the approved policy's auto reason list;
4. claimed deduction equals the invoice difference exactly;
5. amount and currency are within the applicable auto threshold;
6. policy is approved, effective at `decision_at`, and its source hash is recorded;
7. there is no ambiguity, conflicting evidence, prior application, or manual-review flag.

Being below a threshold is never sufficient by itself. Historical approvals are not policy.

### 5.3 Authority

The policy authority matrix keys on reviewer role, legal entity, currency, decision type, maximum
amount, and effective dates. `cash_record_review_decision` resolves the authenticated reviewer to a
current authority record; client-supplied roles or limits are untrusted. It records the authority
snapshot used.

A reviewer may choose only the actions enabled by both exception type and policy. Authority can
permit a judgement exception to an auto rule; it cannot waive duplicate use, ineligible cash,
tampered/stale evidence, arithmetic imbalance, negative invoice balance, closed invoice, or
unsupported currency conversion. After any valid decision, all controls and versions run again.

Baseline synthetic policy for the demo:

```json
{
  "policy_id": "SHORTPAY-01",
  "version": 3,
  "status": "APPROVED",
  "effective_from": "2026-09-01",
  "currency": "GBP",
  "max_auto_amount": "50.00",
  "allowed_auto_reason_codes": ["FREIGHT_DAMAGE", "ROUNDING"],
  "requires_explicit_reason": true,
  "requires_source_locator": true,
  "authority": [
    {"role": "CONTROLLER", "decision": "APPROVE_WRITE_OFF", "max_amount": "1000.00"}
  ]
}
```

Whether an unlisted but evidenced reason may be manually written off MUST be an explicit
`manual_action_rules` policy setting. The safe default is false.

### 5.4 Policy changes

Policy proposals have their own aggregate and statuses `DRAFT_PROPOSAL`, `UNDER_REVIEW`,
`APPROVED_FOR_FUTURE_VERSION`, and `REJECTED`. A proposal contains the reviewed case ids, outcome
counts, amount distribution, proposed diff, and author; it has no `effective_from` while still a
proposal. Approval creates a new immutable policy version in a separate governed action. It never
edits or activates the proposal object in place, and it never changes an in-flight control result.

## 6. Small, high-signal tool contracts

All failures return `{error: {code, message, retryable, missing_fields}}`. Read failures create no
state. Mutating tools require `idempotency_key` and `expected_version`; validation or concurrency
failure creates no financial state change, though a denied attempt is audit logged.

| Tool | Purpose and inputs | Output | Responsibility / fail-closed behaviour |
| --- | --- | --- | --- |
| `cash_get_receipt_context` | `receipt_id`, `as_of`; fetch receipt, source evidence, possible remittances/customers, duplicate status | bounded context with versions/evidence refs | Deterministic read. `NOT_FOUND`, `SOURCE_INTEGRITY_FAILED`; never fabricates candidates |
| `cash_extract_remittance` | `document_id`, `source_sha256` | schema-validated claims, per-field locators/confidence, explicit gaps | Model extracts; deterministic schema/hash/total validation. Unsupported claims are null; conflicting totals return `EVIDENCE_CONFLICT` |
| `ar_get_open_items` | `customer_id`, `as_of` | open AR snapshot with item/ledger versions and evidence refs | Deterministic read. Closed items excluded but referenced closed ids reported as controls, not silently dropped |
| `cash_match_open_items` | receipt/remittance/AR snapshot ids and versions | ranked customer result, allocation proposal(s), classifications and both residual types | Deterministic exact-reference/arithmetic engine; model may choose which returned proposal to investigate. Ambiguity never collapses to a winner |
| `policy_get_shortpay_rule` | `customer_id`, reason or null, `decision_at`, currency | one approved effective policy ref and applicable rule, or typed absence/conflict | Deterministic lookup. Multiple active versions is `POLICY_CONFLICT`; no policy is not permission |
| `cash_evaluate_application` | immutable proposal id/version and policy ref | control result described above | Sole financial-control authority. Never mutates ledger |
| `cash_create_exception` | application/control result, owner/recommendation, idempotency key | typed exception and audit event | Deterministic allowed type/route validation. Cannot downgrade `BLOCK` to review |
| `cash_prepare_review_packet` | exception id/version | packet contract below plus allowed decisions | Deterministic assembly from stored evidence; model may draft summary but every claim is reconciled to evidence refs |
| `cash_record_review_decision` | review id/version, authenticated actor, typed decision payload, idempotency key | decision, authority result, next state or escalation | Deterministic identity/authority/state validation. Does not post. Invalid approval remains open and creates no decision |
| `cash_apply_simulated` | ready application/version, fresh control result, idempotency key | receipt/invoice before-after state and audit ids | Atomic deterministic simulated write. Rechecks controls/versions. Adapter MUST have no production Cherry Money credentials or endpoints |
| `cash_propose_policy_change` | closed review ids, proposed diff | evidence-backed proposal only | Analysis may suggest; deterministic validation ensures active policy is untouched |

The agent is never given low-level `update_invoice`, `set_status`, `write_off`, or payment tools.

## 7. Human review UX contract

The controller sees, in this order:

1. case state, exact decision required, due/age, and amount at risk;
2. booked receipt identity, payer, amount/currency/date/reference and bank evidence link/hash;
3. matched customer and invoice balances with unique evidence supporting the identity;
4. proposed cash allocation, adjustment, receipt residual, and invoice before/after projection;
5. remittance claims beside page/row/JSON locators, including explicit missing/conflicting facts;
6. exception/control codes, not a generic confidence label;
7. effective policy id/version/clause, pass/fail conditions, and reviewer authority status;
8. one recommended action plus only currently valid decision buttons;
9. audit timeline and the statement `SIMULATED — no Cherry Money production write`.

### Concrete £500 review

```text
Decision: treatment of a GBP 500.00 claimed deduction

Receipt RCPT-1042 | BOOKED | GBP 9,500.00 | Northstar Retail
Bank evidence: SYNTHETIC_BANK/TX-1042, sha256 …, record TX-1042

Remittance: INV-2208, invoice amount GBP 10,000.00,
raw reason “DAMAGED_GOODS”, claimed deduction GBP 500.00 (page 1, line 4)
AR: INV-2208 | open GBP 10,000.00 | ledger version 7

Proposed after state if cash is applied and balance left open:
  receipt: APPLIED, unapplied residual GBP 0.00
  invoice: cash GBP 9,500.00, adjustment GBP 0.00, open GBP 500.00

SHORTPAY-01 v3: auto limit GBP 50.00; allowed auto reasons FREIGHT_DAMAGE, ROUNDING.
Result: REVIEW_REQUIRED. Amount exceeds auto limit by GBP 450.00 and DAMAGED_GOODS is not
an allowed auto reason. No automatic write-off is permitted.

Recommendation: CREATE_DISPUTE for GBP 500.00 and assign the deductions owner.
Other valid actions: LEAVE_BALANCE_OPEN, REQUEST_EVIDENCE, REJECT_MATCH.
APPROVE_WRITE_OFF appears only if manual_action_rules allow this reason and the authenticated
reviewer has at least GBP 500.00 authority.
```

Before a valid decision, the receipt is `HELD` and the invoice remains GBP 10,000.00. After
`CREATE_DISPUTE`, controls rerun and the simulated post applies GBP 9,500.00, leaves GBP 500.00
open, and moves the exception to `DISPUTE_OPEN`. An over-limit approval attempt only escalates.

## 8. Accounting invariants

The following are unconditional and deterministic:

1. `(source_system, source_transaction_id)` identifies at most one canonical receipt.
2. A receipt/application/idempotency key cannot post twice, including under concurrent retries.
3. Only positive `BOOKED` receipts can be allocated; pending/reversed cash cannot.
4. Sum of posted cash cannot exceed the receipt's currently available amount.
5. Receipt amount always equals posted cash plus explicit unapplied receipt residual.
6. Invoice before balance always equals cash plus authorised adjustment plus after balance.
7. No allocation or adjustment can make an invoice balance negative.
8. Only an open, version-matched invoice can receive a new application.
9. Currency must match unless an approved effective FX rule and exact rate evidence are supplied.
10. Every allocation references an existing receipt, remittance claim, customer, and AR snapshot.
11. A name-only or confidence-only customer match cannot post.
12. Partial payment never creates an adjustment; its invoice residual remains open.
13. A deduction/write-off requires an evidenced amount/reason and an approved policy/manual path.
14. Unsupported, missing, or conflicting claims remain explicit; rounding cannot hide residuals.
15. Policy-bounded actions record the exact approved, effective policy id/version/hash.
16. Manual decisions record authenticated identity, authority version, exact action/amount, and rationale.
17. Human approval cannot override invariants 1-12 or optimistic concurrency.
18. Every state change and denied mutation attempt appends a hash-linked audit event with versions.
19. Posted history is immutable; correction uses a separately authorised compensating event.
20. All hackathon mutations target an isolated simulated store; production Cherry Money writes and
    payment initiation are impossible by adapter construction.

## 9. Eval mapping

| Eval | Required path and deterministic assertions |
| --- | --- |
| `CA-01` | `EXACT`, `READY_TO_POST -> POSTED_SIMULATED`; receipt `APPLIED`, invoice zero, one post id, evidence refs, no review |
| `CA-02` | `MULTI_INVOICE`; each line references remittance/AR, cash sum GBP 3,650.00, both invoices zero, receipt residual zero |
| `CA-03` | `PARTIAL_PAYMENT` + `INVOICE_OPEN_PARTIAL`; cash GBP 6,000.00, adjustment zero, invoice GBP 4,000.00 open, no write-off/exception |
| `CA-04` | `SHORT_PAY`; all seven auto criteria pass under `SHORTPAY-01 v3`; cash GBP 9,970.00 + adjustment GBP 30.00, invoice zero, policy hash in audit |
| `CA-05` | `REVIEW_REQUIRED`; pre-review ledger unchanged and receipt held. After leave-open/dispute decision, cash GBP 9,500.00, adjustment zero, invoice GBP 500.00 open; never auto-write-off |
| `CA-06` | explicit reason evidence missing, so `EVIDENCE_REQUIRED`; adjustment zero. Packet states threshold passes but reason requirement fails |
| `CA-07` | duplicate identity yields `CONTROL_BLOCKED`; original receipt/application versions and balances unchanged; blocked attempt audited |
| `CA-08` | two plausible customers without a unique high-signal reference yield `EVIDENCE_REQUIRED`; no allocation/customer mutation |
| `CA-09` | `OVERPAYMENT`; cash GBP 1,000.00, invoice zero, receipt `PARTIALLY_APPLIED`, explicit GBP 200.00 receipt residual; no invented line |
| `CA-10` | currency mismatch without FX policy/rate is `CONTROL_BLOCKED`, not approvable review; all balances unchanged |
| `CA-11` | parameterise `PENDING` and `REVERSED`; both `CONTROL_BLOCKED`, no post/idempotency consumption |
| `CA-12` | authority lookup rejects GBP 2,500.00 against GBP 1,000.00 limit; review `ESCALATED`, no decision/post/balance change, attempt audited |
| `CA-13` | proposal cites reviewed cases and diff; active policy id/version/hash unchanged before and after proposal generation |

The existing eval plan has ambiguities this contract resolves:

- CA-05 did not state whether cash posts before review. It does not; assert both pre-review and
  post-decision state.
- CA-05 does not say whether `DAMAGED_GOODS` is an allowed manual reason. The fixture must set
  `manual_action_rules`; absent that permission, write-off is not a valid button.
- CA-07 must use exact bank-source identity for a proven duplicate. A similarity fingerprint should
  be a separate suspected-duplicate/evidence case.
- CA-10 said "review/block". It is a hard block until approved FX policy and rate evidence exist.
- CA-11 should be two parameterised cases, not one combined assertion.
- CA-12 needs an authenticated reviewer and effective authority record in the fixture.
- CA-13 must assert byte-for-byte/version equality of the active policy, not only narrative intent.

Recommended post-demo eval additions are: conflicting remittance versions, closed invoice,
stale/concurrent posting, tampered evidence hash, reversal after posting, and same-value legitimate
payments that must not be false duplicate matches.

## 10. BUILD-NOW sequence

Build only the vertical slice needed for CA-01, CA-02, CA-05, then widen controls:

1. **Models + fixtures:** create `app/cash_application/models.py` and synthetic receipt,
   remittance, AR, policy, authority fixtures. Encode enums/equations above; use decimal strings.
2. **In-memory simulated store + audit:** versions, compare-and-set, exact receipt uniqueness,
   idempotency registry, before/after snapshots, hash-linked events. No cloud/Cherry adapter.
3. **Controls first:** implement `controls.py` and unit tests for invariants 1-20, starting with
   duplicate, settlement, arithmetic, invoice state, currency, and stale versions.
4. **Exact matching:** implement exact unique customer/invoice references and multi-invoice
   arithmetic. Pass CA-01/02 without an LLM.
5. **Atomic simulated posting:** implement ready-only posting and retry/concurrency tests.
6. **Residual classifications + policy:** implement partial, short-pay, overpayment, effective policy
   lookup, and CA-03/04/05/06/09/10.
7. **Exception + review:** implement typed packets, action allow-list, authenticated authority,
   re-control-after-decision, and CA-05/08/12.
8. **Agent tools:** expose the workflow-level contracts above. Add remittance model extraction only
   after structured fixtures pass; schema/evidence validation remains deterministic.
9. **Policy proposal:** implement immutable proposal generation and CA-13; no activation endpoint in
   the demo agent surface.
10. **Judge UI + eval runner:** render the two before/after ledger states, evidence/policy links,
    review packet and audit timeline. Run required repeat trials and report only measured results.

Defer Firestore, production integrations, fuzzy optimisation, outbound collections, reversal UI,
and policy administration until the deterministic in-memory vertical slice passes.

## 11. Exact 3-minute judge demo

- **0:00-0:20 — Boundary:** show "AR cash application / simulated ledger" and state that AI reads
  evidence while deterministic controls own financial state; no payment or Cherry Money write.
- **0:20-1:05 — Clean multi-invoice:** open booked `RCPT-1041` GBP 12,400.00, its remittance, and
  Northstar open AR. Run once. Show two allocations (GBP 10,000.00 + GBP 2,400.00), zero receipt
  residual, both invoices closed, policy not needed, and the evidence-linked audit event.
- **1:05-2:20 — Material short-pay:** open `RCPT-1042` GBP 9,500.00 against `INV-2208`
  GBP 10,000.00 with located `DAMAGED_GOODS` GBP 500.00. Show the deterministic threshold/reason
  failures and controller packet. Choose `CREATE_DISPUTE`; show re-control, simulated GBP 9,500.00
  application, GBP 500.00 invoice balance, dispute owner, and no write-off.
- **2:20-2:45 — Hard boundary:** briefly retry the processed receipt or show the duplicate control;
  the post is rejected despite any approval attempt and ledger versions stay unchanged.
- **2:45-3:00 — Audit close:** show bank/remittance/AR hashes, `SHORTPAY-01 v3`, controller identity,
  before/after ledger state, and the `SIMULATED` badge. Close with: routine cash applies
  automatically; controllers see only evidenced decisions that need judgement.

## Open organisation decisions (not build blockers)

- Confirm whether `DAMAGED_GOODS` is eligible for manual write-off or must always route to disputes.
  Default fixture behaviour is dispute-only unless `manual_action_rules` explicitly permits it.
- Confirm the overpayment residual label (`UNAPPLIED` versus `ON_ACCOUNT`) for the eventual ERP;
  the hackathon fixture uses `UNAPPLIED` and performs no refund action.
- Confirm production policy ownership and identity-provider role mapping after the hackathon. The
  demo uses synthetic authenticated actors and authority records, never names typed by the agent.
