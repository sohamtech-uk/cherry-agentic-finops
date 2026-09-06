# Syndicate documentation index

This directory is the documentation entry point for **Cherry CFO — Autonomous Finance Agent**, built for **Syndicate by Maximor, Track 2: Autonomous Office of the CFO**.

The final judge-facing workflow is the **NAV Quality Controller**: mixed NAV evidence is classified, readiness is assessed, deterministic finance controls run, exceptions are investigated by a bounded agent, and a human records the final decision.

## Start here

1. [`SYNDICATE_READINESS.md`](SYNDICATE_READINESS.md) — hackathon scope, build boundary, judging alignment and submission checklist.
2. [`WEBSITE_SYSTEM_AND_WORKFLOW.md`](WEBSITE_SYSTEM_AND_WORKFLOW.md) — current NAV workbench, API flow and controller journey.
3. [`ARCHITECTURE.md`](ARCHITECTURE.md) — current Syndicate architecture and financial authority boundary.
4. [`ARCHITECTURE_DIAGRAM.md`](ARCHITECTURE_DIAGRAM.md) — judge-friendly architecture diagram.
5. [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) — two-minute demo script.
6. [`LOCAL_SETUP.md`](LOCAL_SETUP.md) — run the Syndicate branch locally.
7. [`HACKATHON_BLOG.md`](HACKATHON_BLOG.md) — build story and product rationale.
8. [`ANALYSIS_LOADING_UX.md`](ANALYSIS_LOADING_UX.md) — truthful upload/analysis progress and dynamic-canvas UX.

## Specialist / supporting documentation

- [`CONTRACT_AGENT.md`](CONTRACT_AGENT.md) — optional cited contract/side-letter evidence path into NAV controls.
- [`CASH_APPLICATION_WORKFLOW.md`](CASH_APPLICATION_WORKFLOW.md) — an earlier Syndicate Track 2 workflow slice used to develop deterministic-control, exception and human-review patterns. It is supporting engineering evidence, not the final NAV demo positioning.
- [`CONTROLLER_REVIEW_EVAL_ADAPTER.md`](CONTROLLER_REVIEW_EVAL_ADAPTER.md) — deterministic cash-application eval adapter from the earlier Track 2 slice.
- [`DEPLOY_GCP.md`](DEPLOY_GCP.md) — production-oriented Google Cloud deployment notes. The public Syndicate canvas demo is currently on Vercel.

## Codex implementation notes

The [`codex/`](codex/) directory contains implementation briefs used while building the Fund Manager orchestration and UI. They describe reusable capabilities and historical module names. The final product framing is the Syndicate NAV Quality Controller documented above.

## Historical names in source

This repository contains pre-existing / reusable private-markets modules whose names include `ylookup_*`. They are retained in source and tests for compatibility, provenance and regression coverage.

They should **not** be read as the current hackathon title or product positioning.

For Syndicate, use:

> **Cherry CFO — Autonomous NAV Quality Controller**
>
> Evidence intake → readiness → deterministic NAV controls → agentic exception review → human decision → audit trail.

## Hackathon evidence outside `docs/`

The canonical build evidence lives at repository root:

- [`../SYNDICATE_BUILD_LOG.md`](../SYNDICATE_BUILD_LOG.md)
- [`../SYNDICATE_TRACK2_PLAN.md`](../SYNDICATE_TRACK2_PLAN.md)
- [`../SYNDICATE_DOMAIN_RESEARCH.md`](../SYNDICATE_DOMAIN_RESEARCH.md)
- [`../SYNDICATE_EVALS.md`](../SYNDICATE_EVALS.md)
- [`../AO_SESSION_01_CFO_WORKFLOW.md`](../AO_SESSION_01_CFO_WORKFLOW.md)
- [`../PREEXISTING_CODE.md`](../PREEXISTING_CODE.md)

## Live demo

https://cherry-cfo-canvas.vercel.app

The live workbench is decision support only. It does not silently amend an official NAV, write a production ledger entry, or initiate a payment.
