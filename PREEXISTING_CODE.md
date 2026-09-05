# Pre-existing work disclosure

This repository contains work that predates the **Rebuild Private Markets: Ylookup × Encode AI
Hackathon**. We disclose that work explicitly so judges can distinguish the reusable platform from
features built after the event starts.

## Cherry Money — pre-existing financial system of record

`sohamtech-uk/cherrymoney` is an existing private Laravel accounting/open-banking application. It
predates this hackathon and remains a separate codebase. It provides the underlying accounting,
authentication and finance-data capabilities that may be used as infrastructure if the organisers
permit pre-existing platforms.

Cherry Money now has an authenticated, company-scoped WebMCP production bridge with bounded finance
projections. Cherry FundOps can optionally read that bridge server-to-server when
`CHERRY_MONEY_API_URL` and `CHERRY_MONEY_API_TOKEN` are configured. The private-markets workflow is
read-only against Cherry Money and does not initiate payments.

## Cherry Agent — pre-existing agentic finance framework

Cherry Agent was originally created for Google All Things Agentic. No Cherry Money Laravel source
files were copied into this repository. The earlier implementation added:

- Google ADK multi-agent orchestration;
- Gemini schema-validated document extraction;
- deterministic, explainable bank-candidate scoring;
- bounded risk policy and human approval state machine;
- hash-chained audit events and downloadable evidence packs;
- FastAPI API and judge-demo interface;
- Cloud Run, Firestore, Pub/Sub and Cloud Storage deployment assets;
- automated tests and hackathon documentation.

The original repositories reviewed when that service was created were:

| Repository | Revision reviewed | How it informed Cherry Agent |
|---|---|---|
| `sohamtech-uk/cherrymoney` | `0e731e8d052469d490e899214371274a6e2709f5` | Product vocabulary, accounting/open-banking concepts and API boundary |
| `sohamtech-uk/cherrymoney-terraform` | `e9bf4a50729b457816db240aedb4716df589f799` | Google Cloud direction and naming conventions |

## Ylookup pre-event preparation

The repository state immediately before the Ylookup-specific hardening is preserved at:

- `baseline/pre-ylookup-2026-09-04` — original Cherry Agent baseline;
- `baseline/pre-hardening-2026-09-05` — private-markets control-room baseline at commit
  `22f4461ee793eb9d9ab83828f9992a76c0be3ef6`.

Pre-event preparation includes synthetic private-markets fixtures, capital-call/commitment/cash
schemas, deterministic controls and the initial capital-call control-room UI. These should **not** be
represented as work built during the event.

## 5 September safety hardening

The `harden/ylookup-ready-2026-09-05` branch adds operational hardening before using real or
organiser-supplied data:

- fail-closed approved-bank validation;
- protection against calls that exceed remaining LP commitment;
- reference-bound cash matching so investor-name-only candidates cannot auto-reconcile;
- duplicate transaction detection;
- production token protection for real PDF/XLSX/CSV uploads;
- SHA-256 input/analysis evidence metadata;
- an optional **read-only** Cherry Money finance snapshot connector;
- CI type checking in addition to lint, tests, compilation and container build.

## Financial boundary

Cherry FundOps is reconciliation and decision-support software. It does not authorise or execute
money movement. Changed or unverified payment instructions are blocked for independent human
verification. Any Cherry Money integration used by the private-markets route is read-only.
