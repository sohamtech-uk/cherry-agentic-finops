# Three-minute judge demo — Cherry CFO cash application

Primary artifact: `/controller-review`

## 0:00–0:25 — The CFO problem

“Cash application is easy until a receipt covers several invoices or a customer takes a deduction.
AR teams then reconstruct bank evidence, remittance, invoice state and policy before deciding what
can post. Cherry CFO clears the routine case and turns the material exception into a
decision-ready controller packet.”

Point to the header: **SIMULATED AR · NO PRODUCTION WRITES**.

## 0:25–0:55 — RCPT-1041: routine cash applies itself

1. Click **Run deterministic application**.
2. Show `POSTED_SIMULATED / MULTI_INVOICE`.
3. Read the bridge: GBP 10,000 to `INV-2208` + GBP 2,400 to `INV-2214`; GBP 0 residual.
4. Point out the hash-linked audit event count and SIMULATED label.

Key line: “The agent does not do the arithmetic. Fixed-point controls prove the receipt and every
invoice allocation before simulated posting.”

## 0:55–1:40 — RCPT-1042: the system stops for judgement

1. Show GBP 9,500 booked against GBP 10,000 open on `INV-2208`.
2. Show the explicit GBP 500 residual: cash remains HELD and GBP 0 is applied before review.
3. Show the located `DAMAGED_GOODS` remittance claim—customer evidence, not independently proven
   fact.
4. Show `SHORTPAY-01 v3`: GBP 50 automatic limit and the two stop reasons.
5. Scan the non-overridable PASS controls and evidence locators/hashes.

Key line: “This is a real accounting stop: the value exceeds policy and the reason needs human
judgement. A confidence score cannot override settlement, duplicate, currency, version or footing
controls.”

## 1:40–2:15 — Read-only agent investigation

1. Click **Run investigation agent**.
2. Show the recommended `CREATE_DISPUTE` or `LEAVE_BALANCE_OPEN` action.
3. Show that every displayed sentence carries known evidence IDs.
4. Show the actual two-step model/tool trajectory:
   `investigate_cash_application` → `submit_controller_advice`.
5. Point to **ADVISORY · HUMAN DECISION REQUIRED** and `production_write_performed=false`.

Key line: “The model chooses which supported facts matter; the server refuses invented claim IDs.
It has read-only workflow tools and no posting, payment or policy tool.”

If Vercel AI Gateway is not enabled, show the fail-closed provider message and say: “Model access
is unavailable, so the deterministic controller workflow remains usable and nothing changes.”

## 2:15–2:48 — Controller owns the accounting outcome

1. Select **Create dispute**; keep reason `DAMAGED_GOODS` and owner `Deductions team`.
2. Enter: “Customer deduction is evidenced; preserve the residual for deductions follow-up.”
3. Click **Record simulated decision**.
4. Show GBP 9,500 applied, GBP 500 still open, invoice `DISPUTED`, and the new hash-linked audit
   events.
5. If time permits, reset and show **Leave balance open** as the collections alternative.

Key line: “The controller chooses the treatment, but approval still re-runs every fundamental
control. Human judgement cannot bypass the ledger invariants.”

## 2:48–3:00 — Close

“Cherry CFO gives the Office of the CFO the right split: deterministic accounting controls,
agentic exception investigation, explicit human judgement and audit-ready evidence. It never
initiates a payment and this demo never writes to production.”
