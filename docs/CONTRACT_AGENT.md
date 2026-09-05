# Contract Agent — NAV quality-control integration

## Why this exists

The fund-manager interview identified a recurring failure: administrator calculations do not always
apply bespoke investor economics from side letters. The sponsor pack contains no LPA or side letter,
so the public example uses clearly labelled synthetic evidence: Cedar Pension Trust should pay
GBP 1,000,000 under its override, but the administrator applied the LPA default and reported
GBP 1,100,000. The deterministic control catches the GBP 100,000 potential overcall.

This component is the contract-control slice of NAV Quality Control & Reconciliation. It does not
calculate an official NAV and does not let a language model turn prose directly into an approved
number.

## Processing boundary

```text
LPA + investor side letter
          ↓
text-preserving parser
          ↓
section/page search and effective-date detection
          ↓
structured rule with citations
          ↓
deterministic Decimal calculation
          ↓
PASS / FAIL / REVIEW_REQUIRED
```

The language-model specialist chooses retrieval tools and explains evidence. Python controls source
precedence and financial arithmetic. A person resolves ambiguity.

## Tool contracts

### `search_lpa()`

Ranks LPA clauses using transparent lexical relevance. Every hit includes the document ID, filename,
section reference, page number, excerpt, effective date and SHA-linked source document.

### `search_side_letter()`

Uses the same search contract with optional exact investor and fund scoping. Side letters cannot be
ingested without an investor identity.

### `extract_clause()`

Returns the full parsed section, page range and citation. It fails with a not-found result instead of
selecting a similar provision silently.

### `get_effective_date()`

Returns the parsed or explicitly supplied effective date with its supporting text. An undated
relevant document blocks automated rule resolution.

### `get_investor_rule()`

Resolves one supported rule at a requested reporting date. An active investor-specific term takes
precedence over the fund-level LPA only when it has an exact investor match and explicit override
language. Equal-precedence contradictions return `conflict`; complex or undated provisions return
`review_required`.

## Supported structured rules

- `management_fee_offsets_called_capital`
- `management_fee_rate`
- `expense_allocation`
- `reporting_frequency`
- `carry_rate`
- `mfn`
- `excuse_right`

Only rules with a deterministic parser return an automatically consumable value. Relevant text that
cannot be structured is still cited but routed to review.

## NAV check

`POST /api/contracts/nav-checks/investor-capital` accepts gross called capital, management fee,
administrator called capital and an as-of date. It resolves the effective contract rule first, then
uses `Decimal` arithmetic to produce expected called capital and variance.

The check has three outcomes:

- `pass`: administrator and contract-derived values agree;
- `fail`: an exact variance is reported with contract citations;
- `review_required`: a rule is missing, ambiguous, conflicting or undated.

`POST /api/contracts/demo/side-letter-fee` loads the isolated fixture under
`fixtures/contracts/synthetic_side_letter_demo/`. It demonstrates both the Cedar exception and the
Orchard Institutional LP standard case, and returns document/workbook hashes, source locators, stable
finding codes, calculation components and an owned work item.

The NAV Quality Controller introduced in PR #22 can use the same evidence path. Upload the governing
documents first, then send `use_contract_documents=true` to `POST /api/nav-quality/review`. The NAV
engine receives only source-backed resolved terms; incomplete or unresolved contract evidence stops
at `needs_review` rather than becoming financial authority.

## Current limits

- PDF text must be extractable; scanned documents require OCR before ingestion.
- Search is deterministic lexical retrieval, not embeddings.
- Clause parsing recognises numbered sections and articles; unusual layouts may require a supplied
  section map.
- The in-process repository is intentionally ephemeral and suited to the hackathon demonstration,
  not durable production storage.
