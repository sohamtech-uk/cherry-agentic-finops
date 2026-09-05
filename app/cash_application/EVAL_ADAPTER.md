# Cash-application exception eval adapter

`exception_to_canonical_outcome` is the integration boundary between grounded exception
investigation and the cross-scenario eval runner. It maps typed control results into stable
receipt, application, invoice, exception, review, policy, and audit sections. It performs no
ledger mutation and does not parse narrative text.

## `run_case(case_input, trial_id)` integration

The eval workstream owns the public runner and its handling of non-exception outcomes. Its
exception path should call this package as follows:

```python
from app.cash_application.eval_adapter import exception_to_canonical_outcome
from app.cash_application.exceptions import (
    CashApplicationCase,
    investigate_cash_exception,
)


def run_case(case_input: dict[str, object], trial_id: str) -> dict[str, object]:
    case = CashApplicationCase.model_validate(case_input)
    exception = investigate_cash_exception(case)
    if exception is None:
        # Dispatch to the deterministic clean/policy-resolution outcome adapter.
        # None is never posting authority by itself.
        return run_non_exception_case(case, trial_id)
    outcome = exception_to_canonical_outcome(case, exception, trial_id)
    return outcome.model_dump(mode="json")
```

The runner must pass the same validated `case` instance to both calls. The adapter re-runs the
deterministic investigation, rejects a receipt/invoice identity mismatch, and rejects any change
to authoritative packet fields. Only advisory recommendation wording may differ. The caller must
not splice an exception packet into a different case or use a model-generated identifier.

## Canonical mapping

| Section | Authoritative source |
| --- | --- |
| `receipt` | Receipt source identity/version plus deterministic settlement and allocation states |
| `application` | Typed application status, current/proposed cash amounts, and allowed transitions |
| `invoice` | Supplied AR ledger identity/version and unchanged current balance |
| `exception` | Enum code/status, exact residual/risk, gaps/conflicts, and owner |
| `review` | Enum status and typed allowed/recommended decisions |
| `policy` | Approved effective policy ID/version and its evidence locator/hash |
| `audit` | Stable input/output hashes, control-result ID, evidence IDs, and empty ledger delta |

`audit` is an eval trace record, not a persisted financial audit event. A state-changing service
must create its own hash-linked audit event after re-running controls and completing a simulated
write.

## Narrative boundary

`advisory_recommended_action` is context for a reviewer and
`narrative_is_authoritative` is always `false`. Graders and state machines must use the enum,
amount, evidence, policy, and allowed-transition fields. They must never infer a decision,
exception type, ledger amount, or next state by parsing the recommendation. The audit output hash
excludes advisory narrative, so changing model-drafted wording cannot change the canonical
accounting outcome.
