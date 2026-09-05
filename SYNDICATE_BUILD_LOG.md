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
| 1 | CFO workflow architecture and acceptance criteria | Planned | — |
| 2 | Agent/tool design | Planned | — |
| 3 | Deterministic finance controls | Planned | — |
| 4 | Exception investigation | Planned | — |
| 5 | Human-review workflow | Planned | — |
| 6 | Reliability/adversarial QA | Planned | — |
| 7 | Debugging and improvement | Planned | — |
| 8 | Judge demo and submission hardening | Planned | — |

For each completed AO session, capture the session identifier or screenshot separately for the final demo video and update this table with the concrete result.

## Build decisions

1. **Keep the demo narrow.** Prioritise one complete finance workflow over a broad collection of unfinished CFO features.
2. **Deterministic controls remain authoritative** for reconciliation outcomes and financial guardrails.
3. **AI may investigate and explain exceptions**, but must not invent evidence or bypass approval rules.
4. **Human review is a first-class state**, not a generic fallback.
5. **No payment initiation or consumer-banking functionality** is in scope.
6. TensorMux and Neatlogs are optional enhancements only after the core workflow is reliable.

## Required judge scenarios

### Scenario A — clean autonomous reconciliation

A finance document is extracted, the correct bank transaction is found, deterministic controls pass, and the case is reconciled without unnecessary human intervention.

### Scenario B — controlled exception

A mismatch, duplicate, missing reference, ambiguous candidate or low-confidence extraction causes the system to stop, explain the problem, recommend the next action and route the case for human review.

## Submission evidence checklist

- [ ] AO used from the start of Syndicate-specific work
- [ ] Multiple genuine AO sessions captured for the demo video
- [ ] Clean reconciliation scenario works end to end
- [ ] Exception scenario works end to end
- [ ] Human approve/reject or request-evidence path works
- [ ] Audit/evidence output is visible
- [ ] Pre-existing work is clearly disclosed
- [ ] Demo video shows the working product and AO sessions
- [ ] Devpost links point to the Syndicate branch/build, not an unrelated pre-hackathon state
