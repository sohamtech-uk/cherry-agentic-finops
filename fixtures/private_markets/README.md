# Synthetic private-markets fixtures

All data in this directory is fictional and intended only for local/hackathon testing.

Run:

```bash
make ylookup-fixtures
```

This generates:

- `02_LP_Commitments_and_Controls.xlsx`
- `03_Fund_Bank_Cash_Transactions.csv` — retained for backwards compatibility;
- `03_Fund_Bank_Cash_Transactions.json` — preferred for the integrated workflow;
- `capital_call_fixture.json` — deterministic fallback for the legacy endpoint.

The separate hackathon preparation pack also includes the synthetic capital-call PDF:

- `01_Capital_Call_Notice_2026-03_Oakfield.pdf`

The judge-facing integrated endpoint expects exactly the three evidence types requested for the
combined demo:

1. PDF capital-call notice;
2. Excel commitment/control workbook;
3. JSON fund cash/bank export.

Endpoint:

```text
POST /api/private-markets/analyse-integrated
```

Expected Oakfield findings:

- current call: GBP 1,250,000;
- cash received: GBP 1,249,500;
- short receipt: GBP 500;
- approved historical account ending: `2381`;
- current notice account ending: `9437`;
- outcome: bank-detail change requires human review, and the cash variance remains an exception.

No file in this directory contains real banking details or customer data.
