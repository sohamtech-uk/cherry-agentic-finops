# Syndicate by Maximor — Build Log

## Hackathon boundary

- **Track:** 2 — Autonomous Office of the CFO
- **Project:** Cherry CFO — Autonomous Finance Agent
- **Official build start:** 2026-09-05 17:00 Europe/London
- **Working branch:** `hackathon/syndicate-cfo-2026`
- **Pre-kickoff baseline:** `811420327923a8c20795fd72bf221aab0a534bad`
- **Baseline timestamp:** 2026-09-05 16:47:28 Europe/London

This branch intentionally starts from the last repository commit before the official Syndicate kickoff. Everything reachable from the baseline commit is treated as **pre-existing work** and must not be presented as work created during Syndicate.

All Syndicate-specific development stays on this branch during the hackathon. **Do not merge this branch to `main` during the hackathon.**

## Competition objective

Build one judgeable end-to-end internal finance workflow:

`finance document -> structured extraction -> candidate transaction search -> deterministic reconciliation -> exception investigation -> human review when required -> audit evidence / close summary`

The goal is not unrestricted financial autonomy. The system should automate routine work, explain its decisions, fail closed when evidence is insufficient, and escalate genuine judgement calls to a human.

## AO evidence register

AO is mandatory for Syndicate. Record every real AO session used during the build. Do not log planned sessions as completed sessions.

| AO session | Purpose | Status | Result / commit |
| --- | --- | --- | --- |
| 1 (`cherry-agentic-finops-2`) | CFO workflow architecture and acceptance criteria | Complete | Source `29cb0f8`; integrated as `bdb0e71`. Canonical contract in `docs/CASH_APPLICATION_WORKFLOW.md` |
| 2 (`cherry-agentic-finops-7`, shared integration session) | Agent/tool design | Complete | `54b1915`. Read-only Gateway agent, two workflow-level tools, server-validated claims/actions and visible actual trajectory |
| 3 (`cherry-agentic-finops-3`) | Deterministic finance controls | Complete | Sources `31151f3` + `662fe29`; integrated as `e36a0bb` + `9cc6db7`. Fixed-point controls, simulated ledger and canonical control outcome |
| 4 (`cherry-agentic-finops-4`) | Exception investigation | Complete | Sources `5eae102` + `ae3b15e`; integrated as `980e9c7` + `c022e00`. Grounded typed exceptions and adapter boundary |
| 5 (`cherry-agentic-finops-5`) | Human-review workflow | Complete | Sources `4b55084` + `6101307`; integrated as `e219a7e` + `203b100`. Authority-bounded review API/UI and typed outcome |
| 6 (`cherry-agentic-finops-6`) | Reliability/adversarial QA | Complete | Source `33759de`; integrated as `8d66073`. CA-01..CA-13 fixtures, graders, repeatability runner and held-out cases |
| 7 (`cherry-agentic-finops-7`) | Integration, debugging and judge-path hardening | Complete | `fdba53b` + `54b1915`. Reconciled one public `run_case(case_input, trial_id)`, hardened the RCPT-1041/1042 judge slice, added grounded agent investigation, and browser-tested the workbench |
| 8 | Judge demo and submission hardening | Planned | — |

For each completed AO session, capture the session identifier or screenshot separately for the final demo video and update this table with the concrete result.

## Build decisions

1. **Keep the demo narrow.** Prioritise one complete finance workflow over a broad collection of unfinished CFO features.
2. **Deterministic controls remain authoritative** for reconciliation outcomes and financial guardrails.
3. **AI may investigate and explain exceptions**, but must not invent evidence or bypass approval rules.
4. **Human review is a first-class state**, not a generic fallback.
5. **No payment initiation or consumer-banking functionality** is in scope.
6. TensorMux and Neatlogs are optional enhancements only after the core workflow is reliable.

## Integration record — AO session `cherry-agentic-finops-7`

The worker commits were cherry-picked in the requested order onto
`ao/cherry-agentic-finops-7/root`, whose base is `origin/hackathon/syndicate-cfo-2026`. No commit
was made on, merged to or pushed to `main`.

Overlapping worker implementations were reconciled as follows:

- `app.cash_application.eval_adapter.run_case(case_input, trial_id)` is the single public eval
  entry point. It accepts the public eval task envelope and preserves compatibility with the typed
  deterministic-control input without exposing a second public `run_case`.
- Financial arithmetic, eligibility, duplicate identity, currency, invoice-state, allocation,
  evidence, stale-state, authority and idempotency decisions remain deterministic. Human review
  can select only policy-valid actions and re-runs controls before a simulated post.
- Exception recommendations remain advisory; typed facts, input evidence references and effective
  policy state are authoritative. Missing customer, invoice, remittance, reason or policy evidence
  remains absent rather than being inferred.
- The only mutation target is isolated in-memory simulated AR. The package contains no payment
  initiation or production Cherry Money write path.

### Agent/tool hardening — commit `54b1915`

- The RCPT-1042 judge path now has a genuine model boundary through Vercel AI Gateway. The model
  is forced to call `investigate_cash_application` before `submit_controller_advice`; both tools
  are read-only and expose no ledger, payment, policy-update or approval operation.
- The server—not the model—constructs all amounts, policy facts, control outcomes and evidence
  claims. Model output is restricted to `create_dispute` or `leave_balance_open` plus claim IDs
  from the packet. Unknown claims, missing residual/policy/unchanged-state grounding, wrong case
  IDs and fundamental control blocks fail closed without state change.
- The controller UI displays the actual model request/tool call/tool result trajectory and renders
  only server-validated claims. The model recommendation remains advisory; a human decision still
  enters the existing authority, freshness, idempotency and deterministic-control path.

## Measured verification — 2026-09-05

All counts below are observed results from this AO worktree, not fixture-validation counts:

| Verification | Observed result |
| --- | --- |
| Focused cash-application, agent, exception, controller and eval tests | 107/107 passed; two dependency deprecation warnings, no failures |
| Grounded-agent tests | 4/4 passed with a controlled model transport: actual tool-call trajectory, invented-claim rejection, fundamental-control stop and API/no-mutation assertions |
| Full repository test suite | 262/262 passed; two dependency deprecation warnings, no failures |
| Core CA suite with required repeat settings | 26/26 graded trials passed; 0 errors, 0 unsupported; 0/11 false-auto applications on review-required trials |
| Required six-case safety run (`CA-01`, `04`, `05`, `06`, `07`, `08`, three trials each) | 18/18 passed; 0/9 false-auto applications on review-required trials |
| Held-out changed-name/amount/invoice suite | 5/5 passed; 0 errors, 0 unsupported; 0/3 false-auto applications |
| Static checks | Ruff check passed; Ruff format check passed for 108 files; `compileall` passed; JavaScript syntax passed; mypy passed for 59 source files |
| Live model boundary | Local Vercel OIDC request reached AI Gateway and was rejected HTTP 403 because the team has no payment card on file; deployed endpoint returned truthful HTTP 503 `AGENT_RUNTIME_UNAVAILABLE`. No model trial or live-model pass count is claimed |

### Failure to fix

The first integrated focused run produced **100 passes and 1 failure**: the product integration
gate could import `app.cash_application.eval_adapter` but it had no public `run_case`. The worker
adapters exposed separate control, exception and controller mappings, so the adversarial runner
had no executable end-to-end seam. Session `cherry-agentic-finops-7` added one deterministic
`run_case(case_input, trial_id)`, routed every public fixture through isolated simulated state and
retained the narrower mappings only as internal typed helpers. The focused rerun passed 103/103;
the measured core, required-repeat and held-out results are recorded above.

The Track 2 audit then found a second integration gap: the controller page described agentic
investigation but its trace was a deterministic list and no cash-application model was called.
Commit `54b1915` replaced that gap with the bounded Gateway/tool loop above and four model-transport
tests. The first live Gateway probe reached the provider but returned HTTP 403 because Vercel
requires a payment card before unlocking the team's free credits. The implementation therefore
does not substitute deterministic advice or invent a successful model run: it returns HTTP 503,
keeps the review workflow available and records no accounting change. Enabling team Gateway
billing/authentication is the remaining external step for a live model trajectory.

## Shared-browser judge-path evidence

Session `cherry-agentic-finops-7` launched the FastAPI app at the known loopback URL and handed the
controller artifact to the AO preview/browser panel. The shared browser verified:

- **RCPT-1041 clean multi-invoice:** one user action returned `POSTED_SIMULATED / MULTI_INVOICE`,
  applied GBP 10,000.00 to `INV-2208` plus GBP 2,400.00 to `INV-2214`, left GBP 0.00 receipt
  residual and displayed three hash-linked audit events with SIMULATED labelling.
- **RCPT-1042 CREATE_DISPUTE:** before review, the receipt was HELD, cash applied was GBP 0.00 and
  `INV-2208` remained GBP 10,000.00 open. The controller decision posted GBP 9,500.00 simulated
  cash, created the dispute, preserved GBP 500.00 open, incremented the invoice ledger version and
  displayed `review.decision_recorded` plus `application.posted_simulated` audit events.
- **RCPT-1042 LEAVE_BALANCE_OPEN:** after resetting the fixture, the controller decision posted
  GBP 9,500.00 simulated cash and kept GBP 500.00 OPEN for collections with no adjustment.
- The browser reported no console messages and no page errors after both completed decision paths.
- **Grounded agent UI:** a local browser run using the controlled model transport rendered
  `CREATE_DISPUTE`, five packet-backed claim IDs, four evidence IDs, two model response IDs and the
  six observed `MODEL_REQUEST -> TOOL_CALL -> TOOL_RESULT` trajectory rows. This proves UI wiring,
  not a live provider pass. With real Vercel OIDC, the browser instead displayed the observed
  HTTP 403 fail-closed message and confirmed no accounting state changed.
- **Production Vercel:** deployment `dpl_DkLj65iueucJdEUohW7YvsV8bGXL` is READY at
  `https://cherry-agentic-finops.vercel.app/controller-review`. The shared AO browser observed the
  production RCPT-1041 `POSTED_SIMULATED / MULTI_INVOICE` result with GBP 0.00 residual, the new
  read-only agent panel, the truthful unavailable-runtime message and no console messages. Vercel
  API checks also observed RCPT-1042 `CREATE_DISPUTE` with GBP 9,500.00 applied, GBP 500.00 open,
  `DISPUTED`, three audit actions and `production_write_performed=false`.

## Required judge scenarios

### Scenario A — clean autonomous reconciliation

A finance document is extracted, the correct bank transaction is found, deterministic controls pass, and the case is reconciled without unnecessary human intervention.

### Scenario B — controlled exception

A mismatch, duplicate, missing reference, ambiguous candidate or low-confidence extraction causes the system to stop, explain the problem, recommend the next action and route the case for human review.

## Submission evidence checklist

- [x] AO used from the start of Syndicate-specific work
- [x] Multiple genuine AO sessions recorded for demo capture
- [x] Clean reconciliation scenario works end to end
- [x] Exception scenario works end to end
- [x] Human controller action paths work (tests); create-dispute and leave-open verified in browser
- [x] Audit/evidence output is visible
- [x] Pre-existing work is clearly disclosed
- [ ] Demo video shows the working product and AO sessions
- [ ] Devpost links point to the Syndicate branch/build, not an unrelated pre-hackathon state
