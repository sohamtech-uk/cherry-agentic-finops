# AWS / AgentCore deployment — Cherry Agent

This guide deploys the **Agents for Humans** version of Cherry Agent with:

- Strands Agents SDK;
- Amazon Bedrock;
- Amazon Bedrock AgentCore Runtime;
- the existing deterministic Cherry finance controls.

The repository intentionally does **not** contain AWS access keys, secret keys or temporary session
credentials.

## 1. Authenticate to the intended AWS account

Use AWS IAM Identity Center (SSO), an existing named AWS CLI profile, or another approved AWS
credential mechanism.

Example with a local profile:

```bash
export AWS_PROFILE=<your-profile>
export AWS_REGION=eu-west-2
export AWS_DEFAULT_REGION=eu-west-2

aws sts get-caller-identity --profile "$AWS_PROFILE"
```

Before deploying, verify the `Account` returned by STS is the account you intend to use.

London (`eu-west-2`) supports Amazon Bedrock AgentCore and is the default region used by the Cherry
Strands implementation.

## 2. Confirm Bedrock model access

Cherry Agent defaults to:

```text
global.anthropic.claude-sonnet-4-6
```

Override it if your account uses another Bedrock model or inference profile:

```bash
export STRANDS_BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6
```

The IAM identity/runtime role needs permission to invoke the configured Bedrock model.

## 3. Install the application locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Smoke-test the Strands hierarchy before provisioning anything:

```bash
python - <<'PY'
from agents.cherry_strands import invoke_cherry_agent

result = invoke_cherry_agent(
    "Run an approval scenario and explain why the workflow needs a human."
)
print(result)
PY
```

## 4. Test the AgentCore-compatible entrypoint locally

The runtime entrypoint is:

```text
agentcore/cherry_agent.py
```

Run it locally:

```bash
python agentcore/cherry_agent.py
```

Then invoke the local runtime in another terminal:

```bash
curl -sS -X POST http://localhost:8080/invocations \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Run an exception scenario and explain the evidence gap."}'
```

## 5. Deploy with the AgentCore CLI

AWS currently recommends the AgentCore CLI for new AgentCore projects.

```bash
npm install -g @aws/agentcore
```

Create a Strands/Bedrock project with the CLI and use `agentcore/cherry_agent.py` as the agent
entrypoint. The exact generated folder names can change with AgentCore CLI releases, so keep the
checked-in Cherry entrypoint as the source of truth rather than committing generated credentials or
account-specific artefacts.

Typical creation flow:

```bash
agentcore create --project-name CherryAgentAWS --no-agent
cd CherryAgentAWS
agentcore add agent \
  --name CherryAgent \
  --language Python \
  --framework Strands \
  --model-provider Bedrock \
  --memory none
```

Copy the logic from this repository's `agentcore/cherry_agent.py` into the generated agent
entrypoint and add this repository/package as the application source, then deploy:

```bash
agentcore deploy
```

The CLI provisions the AgentCore Runtime resources and runtime IAM role in the currently authenticated
AWS account.

## 6. IAM boundary

For a hackathon deployment, keep permissions narrow. The runtime requires Bedrock model invocation
and AgentCore runtime permissions. Add access to any other AWS service only if a Cherry tool actually
uses that service.

Do not give the agent permission to move money, modify bank beneficiaries or bypass human approval.
Cherry's payment boundary is intentional: the hackathon demo is reconciliation and decision support,
not payment initiation.

## 7. Judge-facing demo sequence

Use three short prompts to prove the product boundary:

1. **Autonomous routine case**

```text
Run an autonomous scenario. Tell me what was reconciled automatically and which deterministic
control allowed it.
```

2. **Human approval case**

```text
Run an approval scenario. Explain exactly why the workflow stopped and what the human must review.
```

3. **Evidence exception**

```text
Run an exception scenario. Show the missing or conflicting evidence and explain why Cherry refuses
to guess.
```

For each result, explicitly show:

```text
User request
  -> Strands orchestrator
  -> specialist agent
  -> bounded tool
  -> deterministic finance control
  -> autonomous outcome OR human review
  -> audit evidence
```

## 8. Production hardening after the hackathon

Before using real customer data:

- put AgentCore behind authenticated identity;
- use least-privilege runtime IAM;
- add request/session isolation and persistent audit storage;
- use secrets management rather than environment-file credentials;
- add CloudWatch/AgentCore observability and alarms;
- configure data-retention and privacy controls;
- complete threat modelling and financial-control review.
