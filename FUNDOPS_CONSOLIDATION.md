# FundOps consolidation target

## Goal

End with **one runtime repository and one MySQL database**:

- Runtime repo: `sohamtech-uk/cherry-agentic-finops`
- Database engine: MySQL 8
- Raw inputs: PDF + Excel + JSON
- Cherry remains the financial-control authority
- Reusable FundOps agent code is absorbed from `Sunilkumarsahu11/fundops-agent-studio`

## Database ownership

The final runtime can use the same MySQL database infrastructure as Cherry Money while keeping table ownership explicit.

FundOps-owned tables use the `fundops_` prefix:

- `fundops_alembic_version`
- `fundops_models`
- `fundops_model_versions`
- `fundops_entity_definitions`
- `fundops_field_definitions`
- `fundops_relationship_definitions`

FundOps must not write directly to Cherry Money accounting/application tables unless a later explicit application contract is introduced.

## Repository migration sequence

1. Convert Agent Studio from PostgreSQL to MySQL and prove migrations/tests/container build on MySQL.
2. Keep the existing HTTP integration only as a temporary compatibility boundary.
3. Move reusable deterministic modules into this repository under a dedicated FundOps package.
4. Replace the HTTP call from `app/fundops_studio.py` with an in-process adapter.
5. Move the namespaced FundOps Alembic migration into this repository.
6. Run the PDF + Excel + JSON end-to-end tests against one MySQL database.
7. Remove the transitional Agent Studio deployment workflow and archive the source repository after parity is proven.

## Modules to absorb

Prioritise the modules that add unique capability rather than duplicating Cherry functionality:

- canonical fund model and provenance records;
- reconciliation tool layer;
- capital-call review;
- exception investigation;
- deterministic agent library;
- optional LLM planner/guardrails only after deterministic parity.

Do not duplicate Cherry's existing PDF extraction, Excel commitment parsing, JSON cash parsing, strict matching, financial controls, UI, or payment boundary.

## End-state flow

```text
PDF + Excel + JSON
       |
       v
Cherry ingestion / extraction
       |
       v
Strict deterministic controls
       |
       +--> FundOps canonical model
       +--> FundOps reconciliation
       +--> FundOps exception investigation
       |
       v
Human review / audit trail
       |
       v
Shared MySQL database
```

## Rule until consolidation is complete

Do not add permanent features to both repositories. New user-facing behaviour belongs in Cherry. New reusable FundOps analysis logic can be developed in Agent Studio only when it is intended to be moved into Cherry during consolidation.
