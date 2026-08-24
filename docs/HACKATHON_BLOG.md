# Building Cherry Agent: Human-Governed Autonomous Finance Operations for SMEs

> **Hackathon disclosure:** I created this article specifically for the purposes of entering the **Google All Things Agentic Hackathon**.

Small organisations rarely struggle because they cannot create an invoice or upload a receipt. They struggle because the work between those steps is fragmented: documents arrive in different formats, transactions need matching, exceptions need approval, and month-end evidence must still be assembled for a human reviewer.

Cherry Agent is our attempt to turn that fragmented process into a controlled agentic workflow.

## The problem we wanted to solve

For many SMEs, charities and community organisations, finance operations still look like this:

1. A bill or receipt arrives by email or upload.
2. Someone manually reads the supplier, date, reference, subtotal, VAT and total.
3. They choose an accounting category.
4. They search the bank feed for a likely transaction.
5. They decide whether the match is safe or needs approval.
6. They preserve screenshots, notes and supporting documents for month end.

Each task is small, but together they create delay, inconsistency and a weak audit trail.

We wanted an agent that could complete the repetitive work autonomously while making its reasoning visible and preserving a strict human-control boundary.

## What Cherry Agent does

Cherry Agent turns an invoice or receipt into a governed finance-operations workflow:

- **Document understanding:** Gemini extracts structured supplier, reference, date, currency, subtotal, tax, total and line-item information.
- **Accounting suggestion:** the agent proposes a conservative bookkeeping category and VAT treatment.
- **Transaction matching:** deterministic controls rank candidate bank transactions using amount, date, reference, supplier and currency factors.
- **Risk decision:** policy rules determine whether the item can be reconciled automatically, requires human approval, or needs more evidence.
- **Human handoff:** reviewers can approve or reject an exception with an attributable note.
- **Audit evidence:** every important action is added to a tamper-evident event chain, and an evidence pack can be downloaded for review.

Cherry Agent is deliberately limited to **accounting reconciliation**. It does **not** initiate payments.

## Why this is agentic rather than a chatbot

The system does more than answer a question. It works toward an operational goal across several steps:

1. interpret an unstructured document;
2. transform it into validated structured data;
3. inspect candidate financial records;
4. apply matching and risk controls;
5. decide the next permitted action;
6. execute that action or route the case to a person;
7. preserve evidence of what happened.

The agent combines probabilistic AI with deterministic financial controls. Gemini handles ambiguity in documents, while explicit scoring and policy rules control what the system is allowed to do.

## Architecture

![Cherry Agent architecture](images/architecture.jpg)

The implementation uses:

- **Google Gemini through Vertex AI** for structured multimodal document extraction;
- **Google Agent Development Kit patterns** for orchestrating specialist finance tasks;
- **FastAPI** for the application and workflow API;
- **Cloud Run** for the containerised runtime;
- **Firestore** for workflow state;
- **Pub/Sub** for finance-workflow events;
- **Cloud Storage** for evidence retention;
- an external Google Cloud HTTPS load balancer for the public application.

The browser interface presents the document extraction, candidate matches, policy decision, approval controls and audit evidence as one visual narrative.

## The control model

A finance agent should not treat confidence as permission.

Cherry Agent separates three ideas:

- **Extraction confidence:** how reliable the document interpretation appears.
- **Match score:** how strongly a bank transaction fits the document.
- **Action policy:** whether the system is permitted to reconcile without a person.

A high extraction confidence cannot override a currency mismatch, an already-reconciled transaction, a material amount variance or a policy threshold. Exceptions are sent to a human with the relevant evidence and reasoning visible.

## Three demo paths

The public demo contains three scenarios:

### 1. Autonomous reconciliation

A high-quality invoice and a strong bank match pass the deterministic controls. The workflow is reconciled automatically and the audit chain records the decision.

### 2. Human approval

The document and transaction are plausible, but the policy requires a reviewer. The reviewer can inspect the factors, approve the match and add an attributable note.

### 3. Evidence required

The available information is not strong enough to reconcile safely. The workflow pauses and asks for additional evidence rather than guessing.

## What we learned

### Probabilistic AI and deterministic controls work better together

Gemini is valuable for understanding varied invoices and receipts, but the final financial action should be governed by explicit controls that can be inspected and tested.

### Explainability must be part of the workflow

A score alone is not enough. Reviewers need to know which factors contributed to the score, why a policy was triggered and which actor approved the exception.

### Audit evidence should be generated as work happens

Month-end evidence is more reliable when it is assembled from the workflow event stream instead of reconstructed later from memory, screenshots and messages.

### A useful agent needs a clear boundary

Cherry Agent automates reconciliation and evidence preparation, but it does not initiate payments. That boundary keeps the hackathon prototype focused on a valuable, testable and human-governed use case.

## What comes next

The next stage is to connect the workflow to live Open Banking feeds and accounting records, while preserving the same control model. We also want to add supplier-query handling, richer exception resolution and accountant-facing month-end workspaces.

## Try the project

- **Live application:** [finops.cherrymoney.co.uk](https://finops.cherrymoney.co.uk)
- **Source code:** [sohamtech-uk/cherry-agentic-finops](https://github.com/sohamtech-uk/cherry-agentic-finops)

Cherry Agent demonstrates a practical form of agentic automation: not an unrestricted autonomous accountant, but a finance-operations agent that performs repetitive work, explains its decisions, respects policy boundaries and knows when to hand control back to a person.
