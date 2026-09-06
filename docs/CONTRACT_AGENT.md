# Contract Agent — optional Syndicate NAV control specialist

## Purpose

Cherry CFO's final Syndicate workflow is the **NAV Quality Controller**. Contract and side-letter evidence is an optional specialist input when an investor-specific term can change a NAV-related control.

This component exists to keep a language model from turning prose directly into financial authority.

The contract path is:

```text
LPA + investor side letter
          ↓
text-preserving parsing / retrieval
          ↓
source-backed clause + effective date
          ↓
structured investor rule with citation
          ↓
deterministic finance control
          ↓
PASS / FAIL / REVIEW_REQUIRED
```

A model may choose retrieval tools and explain the evidence. Deterministic code controls rule precedence and arithmetic. A human resolves ambiguity.

## Why it matters to NAV review

Fund controllers may need to verify that administrator calculations reflect bespoke investor economics. A side letter can override a fund-level default for one investor without changing the rule for everyone else.

Cherry therefore requires a source-backed rule before a contract term can affect a deterministic control.

The synthetic fixture under `fixtures/contracts/synthetic_side_letter_demo/` demonstrates this boundary without claiming that the fictional investors or figures came from a real fund.

## Tool contracts

### `search_lpa()`

Ranks LPA clauses using transparent retrieval. Hits include source identity, section reference, page/excerpt information where available, effective-date evidence and SHA-linked document identity.

### `search_side_letter()`

Uses the same contract with investor/fund scoping. A side letter cannot be treated as an investor override without an investor identity.

### `extract_clause()`

Returns the parsed clause and source locator. It fails with not-found rather than silently substituting a similar clause.

### `get_effective_date()`

Returns the parsed or supplied date and source evidence. A relevant undated rule cannot become automatic financial authority.

### `get_investor_rule()`

Resolves one supported investor rule for a reporting date. An investor-specific term takes precedence only when the system has an exact investor match, explicit override semantics and sufficient source evidence.

Contradictory, complex, missing or undated terms return `review_required` / conflict rather than being guessed.

## Supported structured rules

Current structured rule families include:

- `management_fee_offsets_called_capital`
- `management_fee_rate`
- `expense_allocation`
- `reporting_frequency`
- `carry_rate`
- `mfn`
- `excuse_right`

Only a rule with a deterministic parser can become a machine-consumable financial input. Relevant text that cannot be safely structured remains evidence for a human reviewer.

## NAV integration

The standalone contract/NAV path includes:

```text
POST /api/contracts/documents
POST /api/contracts/search/lpa
POST /api/contracts/search/side-letter
GET  /api/contracts/documents/{document_id}/clauses/{section_reference}
GET  /api/contracts/documents/{document_id}/effective-date
POST /api/contracts/investor-rules/resolve
POST /api/contracts/nav-checks/investor-capital
```

The NAV Quality Controller can consume resolved contract evidence only when its source requirements are satisfied. Incomplete evidence stops at review rather than becoming an approved number.

## Synthetic demonstration

`POST /api/contracts/demo/side-letter-fee` loads the isolated synthetic fixture. It demonstrates one investor-specific override and one standard/default investor case so the system proves that an exception is scoped rather than applied across the entire investor population.

Synthetic documents and figures are deliberately labelled as such.

## Authority boundary

- The model does not invent a contract clause.
- A retrieved clause is not automatically an approved rule.
- A rule without sufficient source/effective-date evidence is not applied automatically.
- Contract evidence cannot override deterministic NAV arithmetic by model confidence alone.
- Ambiguity is routed to a human.

## Current limits

- PDF text must be extractable; scanned documents require OCR before ingestion.
- Retrieval is deterministic lexical search rather than embeddings.
- Unusual contract layouts may need better parsing / section mapping.
- The in-process contract repository is suitable for the hackathon demonstration, not a production system of record.

## Syndicate positioning

This is a **supporting specialist capability**, not a separate judge-facing product. The final user journey remains one NAV controller workflow:

```text
Upload evidence → readiness → deterministic NAV controls → agent review → human decision
```

Contract evidence participates only when it is relevant to a supported NAV control.
