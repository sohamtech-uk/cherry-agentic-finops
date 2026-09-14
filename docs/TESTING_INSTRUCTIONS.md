# Testing Instructions — Cherry Agent: Autonomous Finance Ops for SMEs

These instructions are intended for **Agents for Humans** judges and reviewers.

Cherry Agent is submitted to the **Professional Agents** track. The hackathon-specific implementation is on the feature branch:

```text
feat/agents-for-humans-strands-aws
```

## Live judge testing site

The deployed application can be tested directly at:

**https://d32u7o814bb2xb.cloudfront.net**

This is the recommended starting point for judges who want to evaluate the application without setting up a local development environment.

Suggested test flow:

1. Open the live site.
2. Run a routine/autonomous finance scenario and review the reconciliation outcome.
3. Run an approval-required scenario and confirm that Cherry Agent stops for human review rather than inventing approval.
4. Run an exception/evidence-gap scenario and confirm that the agent surfaces missing or conflicting evidence rather than guessing.
5. Review the audit/evidence output and the distinction between Strands orchestration, deterministic Cherry controls, and human approval authority.

> Financial safety boundary: Cherry Agent performs reconciliation and decision support only. It does not initiate payments, modify bank beneficiaries or invent human approval.

The project uses:

- Strands Agents SDK for orchestration and specialist-agent delegation;
- Amazon Bedrock as the model provider;
- Amazon Bedrock AgentCore-compatible runtime entrypoint;
- deterministic Cherry finance controls for reconciliation, policy and audit outcomes;
- explicit human approval boundaries for higher-risk or ambiguous cases.

---

## 1. Clone and select the hackathon branch

```bash
git clone https://github.com/sohamtech-uk/cherry-agentic-finops.git
cd cherry-agentic-finops
git checkout feat/agents-for-humans-strands-aws
```

Verify:

```bash
git branch --show-current
```

Expected:

```text
feat/agents-for-humans-strands-aws
```

---

## 2. Local prerequisites

Recommended:

- Python 3.11+
- pip
- Docker (optional, for container verification)
- AWS CLI only if testing the real Amazon Bedrock path

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

---

## 3. Run the automated test suite

The normal unit/API tests do not require AWS credentials and should not make live Bedrock calls.

```bash
ruff check .
ruff format --check .
mypy app agents
pytest
python -m compileall -q app agents agentcore
```

Optional container check:

```bash
docker build -t cherry-agent-strands:test .
```

---

## 4. Run the FastAPI application locally

```bash
uvicorn app.api:app --reload --port 8080
```

Then open:

```text
http://localhost:8080
http://localhost:8080/api/docs
```

Health endpoint:

```bash
curl -sS http://localhost:8080/health
```

---

## 5. Strands-specific API

The hackathon branch exposes a dedicated Strands API when the current feature implementation is enabled.

Health:

```bash
curl -sS http://localhost:8080/api/strands/health
```

Expected metadata includes:

```json
{
  "status": "ok",
  "framework": "Strands Agents SDK",
  "model_provider": "Amazon Bedrock"
}
```

Invoke the agent:

```bash
curl -sS -X POST http://localhost:8080/api/strands/invoke \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "Run an approval scenario and explain why the workflow needs a human."
  }'
```

---

## 6. Recommended judge demo scenarios

The fastest way to evaluate the product is to run these three synthetic scenarios.

### Scenario A — routine autonomous reconciliation

Prompt:

```text
Run an autonomous scenario. Explain what was reconciled automatically and which deterministic control allowed it.
```

What to look for:

- Strands selects/delegates to the finance workflow specialist;
- deterministic Cherry controls make the financial decision;
- a routine, sufficiently evidenced workflow can complete automatically;
- the response clearly distinguishes agent orchestration from deterministic control logic.

### Scenario B — human approval required

Prompt:

```text
Run an approval scenario. Explain exactly why the workflow stopped and what the human must review.
```

What to look for:

- the workflow stops when policy requires human review;
- the agent explains the reason and evidence;
- the agent does **not** invent approval;
- the agent does **not** initiate a payment.

### Scenario C — evidence exception / refusal to guess

Prompt:

```text
Run an exception scenario. Show the missing or conflicting evidence and explain why Cherry refuses to guess.
```

What to look for:

- missing/ambiguous evidence becomes a visible exception;
- the agent surfaces a next action rather than hallucinating a resolution;
- an audit/evidence trail is preserved.

---

## 7. Real Amazon Bedrock test (optional)

A live Bedrock test requires an AWS account with access to the configured Anthropic model/inference profile.

Example environment:

```bash
export AWS_REGION=eu-west-2
export AWS_DEFAULT_REGION=eu-west-2
export STRANDS_BEDROCK_MODEL_ID=eu.anthropic.claude-sonnet-4-6
```

Then run the project smoke-test script if present:

```bash
python scripts/test_strands_bedrock.py
```

If the AWS account has never used Anthropic models in Bedrock, AWS may require the one-time Anthropic use-case / first-time-use form before invocation is permitted.

No AWS keys, secrets or session credentials are stored in this repository.

---

## 8. AgentCore-compatible runtime

The AgentCore runtime entrypoint is:

```text
agentcore/cherry_agent.py
```

For local runtime testing:

```bash
python agentcore/cherry_agent.py
```

Then, from another terminal:

```bash
curl -sS -X POST http://localhost:8080/invocations \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "Run an exception scenario and explain the evidence gap."
  }'
```

The deployed AgentCore runtime, when available, uses the runtime IAM role rather than local AWS credentials.

---

## 9. Architecture to verify while testing

```text
User request
   -> Strands orchestrator
   -> specialist Strands agent
   -> bounded Cherry finance tool
   -> deterministic financial control
   -> autonomous outcome OR human review
   -> audit evidence
```

The key design principle is:

```text
Strands = reasoning/orchestration
Cherry deterministic engine = financial authority
Human reviewer = approval authority
```

---

## 10. Pre-existing code disclosure

This repository contains reusable work that predates the Agents for Humans hackathon, including earlier Cherry Agent / Google ADK work and Ylookup/FundOps functionality.

The AWS/Strands hackathon implementation is isolated on:

```text
feat/agents-for-humans-strands-aws
```

See:

```text
PREEXISTING_CODE.md
```

for the detailed reuse boundary.

---

## 11. Useful source files for reviewers

```text
agents/cherry_strands/agent.py         Strands orchestration and specialist agents
agents/cherry_strands/__init__.py      public Strands interface
agentcore/cherry_agent.py              AgentCore runtime entrypoint
app/agent_tools.py                     bounded finance tools / deterministic workflow bridge
app/api.py                             FastAPI application
PREEXISTING_CODE.md                    pre-existing-work disclosure
docs/AWS_AGENTCORE_DEPLOYMENT.md       AWS deployment notes
```

---

## 12. Safety note

All demo scenarios are synthetic. Reviewers should not upload real customer financial data for testing.

Cherry Agent is a hackathon prototype for finance operations and decision support. It is not an external audit opinion, tax advice, legal advice, or a payment-authorisation system.
