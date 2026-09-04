# Ylookup × Encode readiness — 4 September 2026

This branch is **pre-hackathon preparation**, not the final Rebuild Private Markets submission.
The final problem should still be selected after the 5 September kickoff and fund-manager interviews.

## Frozen baseline

The repository state before this preparation is preserved on:

- `baseline/pre-ylookup-2026-09-04`

The readiness work is isolated on:

- `prep/ylookup-readiness-2026-09-04`

This makes it straightforward to disclose what existed before the event and what is built during the
hackathon itself.

## What this readiness branch adds

The goal is to remove plumbing risk without locking the team into a specific fund-manager problem.
It adds reusable private-markets primitives that can support capital-call reconciliation, exception
control or related fund-operations workflows:

- schema-validated Gemini extraction for capital-call/distribution notices;
- XLSX ingestion for LP commitments and approved banking controls;
- UTF-8 CSV ingestion for fund cash/bank transactions;
- deterministic commitment arithmetic;
- deterministic notice-to-cash reconciliation;
- changed bank-instruction detection;
- explicit `auto_reconcile`, `require_approval` and `request_evidence` outcomes;
- tests for the synthetic backup scenario;
- a standalone API route that does **not** write to Cherry Money and never initiates payments.

## API

### Health

```text
GET /api/private-markets/health
```

### Analyse a private-markets case

```text
POST /api/private-markets/analyse
```

Multipart fields:

| Field | Required | Description |
| --- | --- | --- |
| `commitments` | yes | LP commitment/control workbook (`.xlsx`) |
| `cash` | yes | fund cash/bank transaction CSV |
| `capital_call` | one of | capital-call/distribution PDF or image |
| `capital_call_json` | one of | structured JSON fallback when AI extraction is unavailable |
| `as_of_date` | no | `YYYY-MM-DD` date for due-date controls |

Example using Gemini extraction:

```bash
curl -X POST http://localhost:8080/api/private-markets/analyse \
  -F 'capital_call=@fixtures/private_markets/01_Capital_Call_Notice_2026-03_Oakfield.pdf;type=application/pdf' \
  -F 'commitments=@fixtures/private_markets/02_LP_Commitments_and_Controls.xlsx' \
  -F 'cash=@fixtures/private_markets/03_Fund_Bank_Cash_Transactions.csv;type=text/csv' \
  -F 'as_of_date=2026-09-05'
```

For an offline/demo fallback, send the same workbook and CSV with a schema-conformant
`capital_call_json` form field instead of the PDF.

## Expected synthetic control findings

The bundled Cedar Peak / Oakfield fixture intentionally contains two important exceptions:

1. the current notice uses account ending `9437`, while the approved fund control record uses
   account ending `2381` → **require human approval / independent verification**;
2. Oakfield is expected to contribute GBP 1,250,000 but the cash CSV contains GBP 1,249,500 →
   **GBP 500 short-receipt exception**.

The commitment arithmetic itself reconciles to GBP 1,000,000 remaining after the current call.

## What is deliberately NOT built tonight

To preserve tomorrow's discovery work, this branch does not decide the final product or judging
story. In particular it does not add:

- a dedicated FundFlow judge UI;
- a final workflow around a problem not yet validated with fund managers;
- payment initiation;
- writes to the existing Cherry Money product;
- production fund/customer data;
- an assumed Ylookup API integration before organisers confirm what is available;
- a final liquidity-forecasting feature.

## Tomorrow morning

After the kickoff and interviews:

1. choose one validated problem;
2. record the user, current workflow, pain, success metric and demo moment;
3. create a hackathon branch from the agreed starting point;
4. keep the frozen baseline branch unchanged;
5. build the visible product layer and event-specific workflow during the hackathon;
6. update the reuse/pre-existing-work disclosure before submission.

## Financial boundary

AI may extract and explain evidence. Deterministic controls decide reconciliation/approval states.
An identified human remains responsible for approval, and this service does not initiate payments.
