# Four-minute judge demo

## 0:00–0:25 — Problem

“Small organisations still spend evenings opening bills, copying VAT, hunting for bank movements,
requesting approvals and rebuilding the evidence at month-end. Most accounting AI gives another
suggestion. Cherry Agent finishes the workflow when it is safe to do so.”

## 0:25–1:25 — Autonomous scenario

1. Click **Run autonomous demo**.
2. Show Gemini-structured invoice fields and the visible `Synthetic demo` label.
3. Show the top bank candidate and factor scores: amount, date, reference, supplier and currency.
4. Point to the risk policy: below threshold, no mismatch, high evidence score.
5. Show `Auto-reconciled` and download the evidence pack.

Key line: “Gemini understood the document; deterministic code granted the action.”

## 1:25–2:25 — Human approval scenario

1. Click **Approval**.
2. Show that the match remains strong.
3. Show the £12,500 value control and `Paused safely` status.
4. Enter the named approver, explain the evidence, then click **Approve & reconcile**.
5. Show the two new audit events: human approval and resumed reconciliation.

Key line: “The agent can pause for hours or days and resume without losing state.”

## 2:25–3:10 — Exception scenario

1. Click **Exception**.
2. Show that supplier and reference match but the amount differs materially.
3. Point out that the agent does not average, guess or force a match.
4. Show `Automation stopped` and the evidence request.

Key line: “Useful autonomy includes knowing when not to act.”

## 3:10–3:45 — Agent and Google Cloud

Show the architecture section or repository:

- Google ADK orchestrator and specialists
- Gemini 3.7 Flash
- Cloud Run
- Firestore state
- Pub/Sub events
- Cloud Storage evidence

Open `/healthz` and the Cloud Run service page so the Google Cloud backend is visible.

## 3:45–4:00 — Close

“Cherry Agent changes month-end from a long to-do list into an exception queue. People retain
control of financial judgment; the agent completes the repetitive work and proves what happened.”
