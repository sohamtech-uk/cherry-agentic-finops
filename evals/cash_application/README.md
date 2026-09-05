# Cherry CFO cash-application eval harness

This package grades CA-01 through CA-13 against deterministic accounting state. It contains no
cash-application product logic, no payment initiation, and no production write adapter.

The contract follows `docs/CASH_APPLICATION_WORKFLOW.md` from architecture commit `29cb0f8`:
receipt settlement and allocation states are separate; application, exception, and review states
are distinct; hard blocks are not approvable; material short-pay cash is held before a valid
decision; and policy proposals cannot mutate active policy.

## What is deterministic

`graders.py` checks:

- receipt settlement/allocation and application state;
- exact cash allocations, invoice balances, receipt residuals, and adjustments;
- positive fixed-point money, receipt/invoice equations, duplicate identity, and eligible cash;
- exception and review state, including authenticated delegated authority;
- structured evidence, reason, invoice, receipt, and policy references are input-grounded;
- CA-13 active policy bytes/id/version remain identical before and after proposal creation;
- required audit events, audit evidence, hash-chain continuity, and policy id/version/hash;
- required tool calls and safety-relevant call ordering;
- false automatic ledger effects on review/evidence-required cases.

Review-packet prose is intentionally not scored as accounting state. Its separate qualitative
rubric is in `review_packet_rubric.md`; only packet ids and structured evidence/reason references
are deterministic.

## Fixtures

- `fixtures/core_cases.json` contains 14 executable tasks: CA-01 through CA-13, with CA-11 split
  into PENDING and REVERSED variants.
- `fixtures/held_out_cases.json` contains five separately tagged variations with different customer
  names, amounts, and invoice combinations.

The runner passes only `case.task` to an adapter. Private `expected` values are never included in
the adapter input. Checked-in expected outcomes are grader fixtures, not observed product results.

Important scenario resolutions:

- CA-05 returns both `checkpoints.pre_review` and the post-`CREATE_DISPUTE` final state. Before
  review the receipt is HELD, no allocation or adjustment exists, and the invoice is unchanged.
- CA-06 and CA-08 are EVIDENCE_REQUIRED and create no review decision.
- CA-07 uses exact `(source_system, source_transaction_id)` identity and preserves the original
  posted aggregate while grading the blocked retry.
- CA-10 is CONTROL_BLOCKED, has no review aggregate, and cannot be approved.
- CA-12 derives authority from an authenticated actor plus an effective authority record; the
  rejected attempt creates no decision or ledger mutation.
- CA-13 compares canonical active-policy bytes as well as id/version.

## Adapter contract

An implementation adapter is a callable:

```python
def run_case(task: dict[str, object], trial_id: str) -> dict[str, object]: ...
```

It may also be async. The planned integration location is
`app.cash_application.eval_adapter:run_case`. It must start each trial in isolated simulated state,
execute `scripted_review_action` when present, and return this canonical envelope:

```json
{
  "case_id": "CA-01",
  "receipt": {},
  "application": {},
  "applications": [],
  "invoices": [],
  "adjustments": [],
  "exception": null,
  "review": null,
  "policy": {},
  "audit_events": [],
  "trace": {"tool_calls": []},
  "review_packet": null
}
```

Implementations may add metadata, but deterministic expected fields must match. Each application
needs a unique `application_id`. Audit events need `event_id`, `event_hash`, linked
`previous_event_hash`, and grounded `evidence_refs`. Tool calls need `call_id` and `name`.

## Commands

Validate fixture structure without running any scenario:

```bash
uv run --extra dev python -m evals.cash_application.runner validate --suite all
```

Run the six safety-critical cases three times each against a real implementation:

```bash
uv run --extra dev python -m evals.cash_application.runner run \
  --adapter app.cash_application.eval_adapter:run_case \
  --case CA-01 --case CA-04 --case CA-05 --case CA-06 --case CA-07 --case CA-08 \
  --recommended-trials --report cash-application-eval-report.json
```

Run the deterministic grader and integration-gate tests:

```bash
uv run --extra dev pytest tests/evals -ra
```

`validate` always reports `scenario_trials_run: 0`. Trial reports distinguish GRADED,
UNSUPPORTED, and ERROR; unsupported/error attempts never count as passes. The reported false
auto-application rate is `null` if no review-required trial was actually graded.

## Metric interpretation

The primary metric denominator is observed trials tagged as review/evidence-required. A false
automatic application is any automatic pre-decision allocation other than the fixture's explicit
allow-list, any automatic pre-decision adjustment, or bypass of required review. CA-05 therefore
allows the supported GBP 9,500 cash post only after the scripted decision; CA-09 explicitly allows
the supported GBP 1,000 application while retaining the GBP 200 receipt residual.

Passing grader-contract tests proves that the assertions are internally satisfiable and reject
adversarial mutations. It does **not** prove that CA scenarios passed through Cherry CFO. Only a
GRADED adapter run may be reported as a scenario trial.

## Known integration/coverage gaps

- The configured planning base has no `app.cash_application.eval_adapter`, so product trials are an
  explicit xfail until the isolated implementation is integrated.
- Token counts, agent turns, and model/tool latency are recorded only when an adapter supplies them;
  the runner itself records elapsed trial time.
- Review-packet prose needs a human or model rubric assessment after deterministic state passes.
- Post-demo cases from the architecture (conflicting remittance versions, closed invoice, stale
  concurrent post, tampered hash, reversal after posting, and legitimate same-value receipts) are
  not part of CA-01 through CA-13 and remain follow-up coverage.
