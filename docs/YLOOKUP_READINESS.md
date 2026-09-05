# Ylookup × Encode readiness — 5 September 2026

Cherry FundOps is ready to use as the **private-markets control layer**, while Cherry Money remains a
separate pre-existing financial system of record. The final hackathon problem should still be
validated with fund managers before claiming event-specific functionality.

## Frozen baselines

- `baseline/pre-ylookup-2026-09-04` — original Cherry Agent baseline.
- `baseline/pre-hardening-2026-09-05` — control-room baseline at
  `22f4461ee793eb9d9ab83828f9992a76c0be3ef6`.

These baselines make the pre-existing/event-built boundary auditable.

## Current FundOps capability

- schema-validated Gemini extraction for capital-call/distribution notices;
- XLSX ingestion for LP commitments and approved banking controls;
- UTF-8 CSV ingestion for fund cash transactions;
- strict commitment arithmetic and over-call prevention;
- fail-closed approved-bank validation;
- reference-bound cash reconciliation;
- changed-bank, short/over/missing cash and duplicate-ID controls;
- owned work queue for treasury, investor operations and fund accounting;
- public synthetic control-break, awaiting-cash and clean-close demos;
- protected real three-file upload path;
- SHA-256 evidence metadata for uploaded inputs and analysis;
- optional read-only Cherry Money finance snapshot;
- no payment initiation or authorisation.

## Endpoints

```text
GET  /api/private-markets/health
POST /api/private-markets/demo/exception
POST /api/private-markets/demo/awaiting-cash
POST /api/private-markets/demo/clean
POST /api/private-markets/analyse
GET  /api/private-markets/cherry-money/snapshot
```

Real-data endpoints are protected in production with `CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN`, supplied
by the client as `X-Cherry-Demo-Token`.

## Cherry Money as the base

If organisers confirm reuse is allowed, the architecture is:

```text
Cherry Money (pre-existing)
  accounting / bank / company-scoped financial data
                 |
                 | authenticated read-only bridge
                 v
Cherry FundOps / Cherry Agent (pre-existing control layer)
  Gemini extraction + strict deterministic controls
                 |
                 v
Hackathon-specific workflow
  problem validated with fund managers + Ylookup/event data/APIs
```

Cherry Money's existing `/api/webmcp/bootstrap` bridge can provide a bounded read-only finance
snapshot. FundOps does not use the legacy write helper in the private-markets route.

## Synthetic control-break scenario

- LP: Oakfield Pension Trust;
- total commitment: GBP 5,000,000;
- previously called: GBP 2,750,000;
- current call: GBP 1,250,000;
- remaining after call: GBP 1,000,000;
- approved account ending: `2381`;
- current notice account ending: `9437`;
- strongly referenced cash: GBP 1,249,500;
- short receipt: GBP 500.

Expected result: **request evidence** because a changed payment destination and a cash shortfall
cannot be resolved by approval alone. Treasury verifies payment instructions and investor operations
resolves the outstanding contribution.

## Morning checklist

1. Run `python -m pip install -e ".[dev]"`.
2. Run `make ylookup-fixtures`.
3. Run `ruff check . && ruff format --check .`.
4. Run `mypy app agents`.
5. Run `pytest`.
6. Start `uvicorn app.api:app --reload --port 8080`.
7. Check `/health` and `/api/private-markets/health`.
8. Run all three synthetic demo scenarios.
9. Confirm real uploads are token-protected before using organiser files.
10. Ask organisers whether Cherry Money + Cherry Agent may be disclosed pre-existing infrastructure.
11. Interview fund managers and select one problem before building event-specific functionality.

## Questions for organisers

- May Cherry Money be used as a disclosed pre-existing accounting/open-banking base?
- May Cherry Agent/FundOps be used as a disclosed pre-existing control framework?
- What must be materially new during the hackathon?
- Is Ylookup API/SDK access available, or only datasets/interviews?
- Which sponsor model/cloud credits are available?
- Is sponsor technology required or rewarded in judging?

## Financial boundary

AI interprets evidence. Deterministic controls decide whether evidence is sufficient. Human reviewers
remain responsible for independent verification where required. Cherry FundOps does not execute
money movement.
