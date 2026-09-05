# Controller review-packet qualitative rubric

Apply this rubric only after the deterministic accounting graders pass. Do not average rubric
scores with receipt, application, invoice, exception, authority, policy, or audit assertions.

## Review method

Review the rendered packet with the case input and cited source locations available. Mark each
criterion `PASS`, `FAIL`, or `NOT_APPLICABLE`, and record one sentence of evidence. Any failure of
Grounding or No invention is release-blocking even if the total score would otherwise be high.

| Criterion | PASS standard |
| --- | --- |
| Grounding | Every material claim is supported by a displayed bank, remittance, AR, policy, identity, or authority locator/hash. |
| Decision-ready | The packet names the exact accounting decision and shows only actions valid for the current state. |
| Financial impact | Receipt amount, proposed cash, adjustment, receipt residual, invoice residual, and amount at risk are distinguished and quantified. |
| Policy-aware | It cites the effective policy id/version/clause and explains which auto/manual conditions passed or failed. |
| No invention | It adds no invoice, customer identity, deduction reason, FX rate, policy permission, reviewer authority, or evidence not present in the sources. |
| Actionable | It recommends a valid next state and names missing evidence or the dispute/collections owner where required. |
| Simulation boundary | It clearly states that posting is simulated and does not imply payment initiation or a production Cherry Money write. |

## Required CA-05 observations

The packet must show GBP 9,500 booked cash against a GBP 10,000 invoice, a claimed GBP 500
`DAMAGED_GOODS` deduction, and SHORTPAY-01 v3's GBP 50 auto threshold. It must say that the receipt
is HELD and the invoice remains GBP 10,000 before review. `APPROVE_WRITE_OFF` must not appear unless
the fixture's manual action rule and authenticated authority both permit it. For the provided
fixture, the recommendation is `CREATE_DISPUTE`; after that decision the packet/timeline may show
GBP 9,500 simulated cash applied and GBP 500 still open, with no adjustment.

## Recording format

```json
{
  "case_id": "CA-05",
  "trial_id": "CA-05-trial-1",
  "reviewer": "human-or-rubric-model-id",
  "criteria": {
    "grounding": {"result": "PASS", "evidence": "..."},
    "decision_ready": {"result": "PASS", "evidence": "..."},
    "financial_impact": {"result": "PASS", "evidence": "..."},
    "policy_aware": {"result": "PASS", "evidence": "..."},
    "no_invention": {"result": "PASS", "evidence": "..."},
    "actionable": {"result": "PASS", "evidence": "..."},
    "simulation_boundary": {"result": "PASS", "evidence": "..."}
  }
}
```
