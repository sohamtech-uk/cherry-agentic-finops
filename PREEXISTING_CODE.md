# Pre-existing work disclosure

This repository contains work that predates both the **Rebuild Private Markets: Ylookup × Encode AI
Hackathon** and the later **Agents for Humans** hackathon. We disclose that work explicitly so judges
can distinguish the reusable platform from features built for each event.

## Cherry Money — pre-existing financial system of record

`sohamtech-uk/cherrymoney` is an existing private Laravel accounting/open-banking application. It
predates these hackathons and remains a separate codebase. It provides underlying accounting,
authentication and finance-data capabilities that may be used as infrastructure if the organisers
permit pre-existing platforms.

Cherry Money has an authenticated, company-scoped WebMCP production bridge with bounded finance
projections. Cherry FundOps can optionally read that bridge server-to-server when
`CHERRY_MONEY_API_URL` and `CHERRY_MONEY_API_TOKEN` are configured. The private-markets workflow is
read-only against Cherry Money and does not initiate payments.

## Cherry Agent — pre-existing agentic finance framework

Cherry Agent was originally created for Google All Things Agentic. No Cherry Money Laravel source
files were copied into this repository. The earlier implementation added:

- Google ADK multi-agent orchestration;
- Gemini schema-validated document extraction;
- deterministic, explainable bank-candidate scoring;
- bounded risk policy and human approval state machine;
- hash-chained audit events and downloadable evidence packs;
- FastAPI API and judge-demo interface;
- Cloud Run, Firestore, Pub/Sub and Cloud Storage deployment assets;
- automated tests and hackathon documentation.

The original repositories reviewed when that service was created were:

| Repository | Revision reviewed | How it informed Cherry Agent |
|---|---|---|
| `sohamtech-uk/cherrymoney` | `0e731e8d052469d490e899214371274a6e2709f5` | Product vocabulary, accounting/open-banking concepts and API boundary |
| `sohamtech-uk/cherrymoney-terraform` | `e9bf4a50729b457816db240aedb4716df589f799` | Google Cloud direction and naming conventions |

## Ylookup pre-event preparation

The repository state immediately before the Ylookup-specific hardening is preserved at:

- `baseline/pre-ylookup-2026-09-04` — original Cherry Agent baseline;
- `baseline/pre-hardening-2026-09-05` — private-markets control-room baseline at commit
  `22f4461ee793eb9d9ab83828f9992a76c0be3ef6`.

Pre-event preparation includes synthetic private-markets fixtures, capital-call/commitment/cash
schemas, deterministic controls and the initial capital-call control-room UI. These should **not** be
represented as work built during the event.

## 5 September safety hardening

The `harden/ylookup-ready-2026-09-05` branch added operational hardening before using real or
organiser-supplied data:

- fail-closed approved-bank validation;
- protection against calls that exceed remaining LP commitment;
- reference-bound cash matching so investor-name-only candidates cannot auto-reconcile;
- duplicate transaction detection;
- production token protection for real PDF/XLSX/CSV uploads;
- SHA-256 input/analysis evidence metadata;
- an optional **read-only** Cherry Money finance snapshot connector;
- CI type checking in addition to lint, tests, compilation and container build.

## Agents for Humans — new AWS / Strands layer

For Agents for Humans, the pre-existing finance engines above are reused as bounded tools. The new
hackathon-specific implementation is intentionally separated so it can be reviewed independently:

```text
agents/cherry_strands/agent.py   Strands Agents SDK orchestrator + specialist agents
agentcore/cherry_agent.py        Amazon Bedrock AgentCore Runtime entrypoint
app/strands_router.py            Dedicated Strands API, preserving existing routers
tests/test_strands_*.py          Offline Strands/API validation
scripts/verify_aws_target.sh     Account/region deployment guard
scripts/test_*bedrock.py         Synthetic Bedrock verification
scripts/test_agentcore_runtime.sh Synthetic deployed-runtime verification
infra/aws/agentcore-runtime-policy.json Proposed scoped model invocation policy
docs/AWS_AGENTCORE_DEPLOYMENT.md AWS/AgentCore deployment documentation
```

The new Strands hierarchy uses the **Agents as Tools** pattern and Amazon Bedrock for model inference.
It does not claim that the underlying reconciliation, NAV, private-markets, Google ADK or Cherry Money
features were newly written for Agents for Humans.

Human approval remains outside the LLM tool surface. The existing explicit approval state machine and
API record the human decision; the Strands agent can explain that an approval is needed but cannot
grant it itself.

## Financial boundary

Cherry Agent / Cherry FundOps is reconciliation and decision-support software. It does not authorise
or execute money movement. Changed or unverified payment instructions are blocked for independent
human verification. Any Cherry Money integration used by the private-markets route is read-only.
