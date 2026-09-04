# Synthetic private-markets fixtures

All data in this directory is fictional and intended only for local/hackathon testing.

Run:

```bash
make ylookup-fixtures
```

This generates:

- `02_LP_Commitments_and_Controls.xlsx`
- `03_Fund_Bank_Cash_Transactions.csv`
- `capital_call_fixture.json`

The separate hackathon preparation pack also includes a synthetic capital-call PDF named
`01_Capital_Call_Notice_2026-03_Oakfield.pdf`. If that PDF is not available, use
`capital_call_fixture.json` via the `capital_call_json` form field so the complete deterministic
control path can still be demonstrated without Gemini.

Expected Oakfield findings:

- current call: GBP 1,250,000;
- cash received: GBP 1,249,500;
- short receipt: GBP 500;
- approved historical account ending: `2381`;
- current notice account ending: `9437`;
- outcome: bank-detail change requires human approval, and the cash variance remains an exception.

No file in this directory contains real banking details or customer data.
