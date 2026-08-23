# Pre-existing work disclosure

Cherry Agent is a new implementation created for Google All Things Agentic. No source files were
copied from the existing Cherry Money application or infrastructure repository into this project.

The following pre-existing repositories were reviewed to understand product vocabulary, API
boundaries and current Google Cloud direction:

| Repository | Revision reviewed | How it informed this project |
|---|---|---|
| `sohamtech-uk/cherrymoney` | `0e731e8d052469d490e899214371274a6e2709f5` | Existing invoice, expense, receipt-scanning, open-banking and rule-based reconciliation concepts; optional API integration boundary |
| `sohamtech-uk/cherrymoney-terraform` | `e9bf4a50729b457816db240aedb4716df589f799` | Existing Google Cloud direction and naming conventions |

New work in this repository includes:

- Google ADK multi-agent orchestration;
- Gemini schema-validated document extraction;
- deterministic, explainable bank-candidate scoring;
- bounded risk policy and human approval state machine;
- hash-chained audit events and downloadable evidence packs;
- the FastAPI API and responsive judge-demo interface;
- independent Cloud Run, Firestore, Pub/Sub and Cloud Storage deployment assets;
- automated tests and hackathon documentation.

The optional `CherryMoneyConnector` is disabled unless an API URL and token are explicitly supplied.
It does not make automatic writes to the existing product.
