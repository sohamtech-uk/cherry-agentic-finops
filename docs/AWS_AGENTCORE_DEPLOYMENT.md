# AWS / AgentCore deployment — Cherry Agent

This guide deploys the **Agents for Humans** version of Cherry Agent with:

- Strands Agents SDK;
- Amazon Bedrock;
- Amazon Bedrock AgentCore Runtime;
- the existing deterministic Cherry finance controls.

Target AWS account for the hackathon deployment:

```text
Account name: theinnerpeace
Account ID:   821465445270
Region:       eu-west-2 (London)
```

The repository intentionally does **not** contain AWS access keys, secret keys or temporary session
credentials. The account ID and CLI profile name are identifiers, not credentials.

## 1. Authenticate to the intended AWS account

For local development, use the named AWS CLI profile:

```bash
export AWS_ACCOUNT_ID=821465445270
export AWS_PROFILE=theinnerpeace
export AWS_REGION=eu-west-2
export AWS_DEFAULT_REGION=eu-west-2

aws sts get-caller-identity --profile "$AWS_PROFILE"
```

Do not deploy until the STS response contains:

```json
{
  "Account": "821465445270"
}
```

London (`eu-west-2`) supports Amazon Bedrock AgentCore and is the default region used by this
Cherry Strands implementation.

## 2. Confirm Bedrock model access

Cherry Agent defaults to the EU Claude Sonnet 4.6 inference profile:

```text
eu.anthropic.claude-sonnet-4-6
```

Set it explicitly for local testing:

```bash
export STRANDS_BEDROCK_MODEL_ID=eu.anthropic.claude-sonnet-4-6
```

The local identity and the AgentCore runtime role need permission to invoke the configured Bedrock
model. Keep these permissions separate from Cherry's deterministic financial-control permissions.

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

The checked-in runtime entrypoint is:

```text
agentcore/cherry_agent.py
```

It wraps the Strands hierarchy with `BedrockAgentCoreApp`, so it can be used as the implementation
when creating the generated AgentCore project.

## 5. Install the AgentCore CLI

AgentCore's current CLI is installed through npm and requires Node.js 20+:

```bash
npm install -g @aws/agentcore
agentcore --version
```

## 6. Create a Python + Strands + Bedrock AgentCore project

With the `theinnerpeace` profile still active:

```bash
agentcore create \
  --project-name CherryAgentAWS \
  --name CherryAgent \
  --language Python \
  --framework Strands \
  --model-provider Bedrock \
  --memory none \
  --build CodeZip

cd CherryAgentAWS
```

The generated project contains the AgentCore deployment configuration and AWS CDK assets. Replace
its generated agent implementation with the Cherry implementation from this repository, retaining
the generated AgentCore project structure.

Before creating resources, preview the deployment:

```bash
agentcore deploy --dry-run
```

Confirm that the target is account `821465445270` in `eu-west-2` before continuing.

Deploy:

```bash
agentcore deploy
```

Check status:

```bash
agentcore status
```

Invoke the deployed agent:

```bash
agentcore invoke --prompt \
  "Run an approval scenario and explain why the workflow stopped for human review."
```

The CLI provisions the AgentCore Runtime resources and runtime IAM role in the currently
authenticated AWS account.

## 7. IAM boundary

For the hackathon deployment, keep permissions narrow. The runtime requires Bedrock model invocation
and AgentCore runtime permissions. Add access to another AWS service only if a Cherry tool actually
uses that service.

The agent must not receive permission to:

- move money;
- modify bank beneficiaries;
- bypass the human-approval state machine;
- mutate source accounting evidence without an explicit product requirement.

Cherry's payment boundary is intentional: the hackathon demo is reconciliation and decision support,
not payment initiation.

## 8. Judge-facing demo sequence

Use three short prompts to prove the product boundary.

### Autonomous routine case

```text
Run an autonomous scenario. Tell me what was reconciled automatically and which deterministic
control allowed it.
```

### Human approval case

```text
Run an approval scenario. Explain exactly why the workflow stopped and what the human must review.
```

### Evidence exception

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

## 9. Production hardening after the hackathon

Before using real customer data:

- put AgentCore behind authenticated identity;
- use least-privilege runtime IAM;
- add request/session isolation and persistent audit storage;
- use AWS Secrets Manager or another approved secrets store rather than environment-file credentials;
- add CloudWatch/AgentCore observability and alarms;
- configure data-retention and privacy controls;
- complete threat modelling and financial-control review.
