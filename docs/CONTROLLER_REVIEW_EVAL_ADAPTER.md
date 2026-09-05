# Controller review eval adapter

The controller UI is a view, not an evaluation interface. Canonical grader state comes from
`app.cash_application.eval_adapter.to_trial_outcome(packet, trial_id=...)` or the equivalent
read-only API:

```text
GET /api/controller-review/cases/{case_id}/outcome?trial_id={trial_id}
```

## `run_case` seam

An eval runner should construct its case-specific simulated service state, submit the typed review
decision, catch any expected `ControllerReviewError`, and map the packet left by the attempt:

```python
service = ControllerReviewService(packet_from_case_input(case_input))
try:
    service.decide(case_input.case_id, decision_from_case_input(case_input))
except ControllerReviewError:
    pass
outcome = to_trial_outcome(service.get_packet(case_input.case_id), trial_id=trial_id)
```

`packet_from_case_input` is the integration seam for the broader cash-application fixture/store; it
must supply the immutable receipt, AR, policy and review versions rather than copying UI values.
The controller slice does not define the eval runner's fixture schema or own its persistence.

The returned outcome exposes deterministic fields for:

- receipt settlement and allocation states;
- application, exception and review states;
- review version, recorded decision and latest denial code;
- exact invoice before, cash, authorised adjustment and after amounts;
- failed hard-control codes and whether any ledger mutation occurred;
- ordered audit actions, denial codes, decision/post counts and audit-chain validity;
- the always-false production-write flag.

For CA-12, an over-authority attempt maps to `review_status=escalated`,
`exception_status=ESCALATED_AUTHORITY`, `decision_recorded=false`, `ledger_mutated=false`, unchanged
invoice amounts, `latest_denial_code=AUTHORITY_EXCEEDED`, and zero simulated posts. A successful
CA-05 dispute maps to `POSTED_SIMULATED`, `DISPUTE_OPEN`, GBP 9,500 cash applied, GBP 0 adjustment,
GBP 500 open, invoice ledger version 8 (from version 7) and exactly one simulated-post audit action.

Idempotent replay returns the existing decision and does not append another decision or posting
audit event. The adapter never reads DOM text, labels, CSS classes or client-supplied authority.
