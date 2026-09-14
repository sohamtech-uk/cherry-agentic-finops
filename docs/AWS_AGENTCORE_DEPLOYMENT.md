# Cherry Strands deployment to Amazon Bedrock AgentCore

Target: account **821465445270**, profile **devops-user**, region **eu-west-2**.
Only deploy `feat/agents-for-humans-strands-aws`. Existing Google Cloud services are outside this
 deployment. Never store AWS credentials in source or runtime environment configuration.

## Local setup and account guard

```bash
export AWS_PROFILE=devops-user
export AWS_REGION=eu-west-2
export AWS_DEFAULT_REGION=eu-west-2
export AWS_ACCOUNT_ID=821465445270
export STRANDS_BEDROCK_MODEL_ID=eu.anthropic.claude-sonnet-4-6
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[dev]'
./scripts/verify_aws_target.sh
aws bedrock list-foundation-models --region eu-west-2 --by-provider Anthropic \
  --query 'modelSummaries[].{Name:modelName,Id:modelId}' --output table
aws bedrock get-inference-profile --region eu-west-2 \
  --inference-profile-identifier eu.anthropic.claude-sonnet-4-6
```

The guard fails on an account mismatch, region mismatch, conflicting default region or STS failure.
Local BedrockModel uses boto's credential chain. AgentCore uses its execution role; do not configure
`AWS_PROFILE`, access keys or session tokens inside the runtime.

## Quality gates and synthetic Bedrock test

```bash
ruff check .
ruff format --check .
mypy app agents
pytest
python -m compileall -q app agents agentcore
docker build -t cherry-agent-strands:test .
./scripts/verify_aws_target.sh
python scripts/test_strands_bedrock.py
```

Unit/API tests mock model invocations and require no AWS credentials. Live tests use synthetic
fixtures only. On AccessDenied, record the denied action/resource and correct the specific policy;
do not attach broad managed policies. Deployment is gated on passing local checks and live Bedrock.

## Dedicated API and runtime

`GET /api/strands/health` returns safe framework/model/region/boundary metadata; it is process health,
not proof of Bedrock reachability. `POST /api/strands/invoke` accepts `{"prompt":"..."}`. Prompts must
contain 1–8000 characters after whitespace normalization. Backend exceptions return a generic 503.

`agentcore/cherry_agent.py` uses `BedrockAgentCoreApp`, validates input and returns sanitized errors.
Each invocation constructs a fresh specialist hierarchy. Human approval and rejection are absent
from the Strands tool surface. The underlying existing demo workflow store is process-local/shared;
this synthetic hackathon endpoint is not a tenant-scoped customer-data API. Deploy only synthetic
fixtures until authenticated tenant-scoped storage is implemented.

## CLI syntax verified against installed AgentCore 0.29.0

```bash
agentcore --version
agentcore --help
agentcore create --help
agentcore deploy --help
```

Create a dedicated project outside the source tree (creation generates local files):

```bash
./scripts/verify_aws_target.sh
agentcore create --project-name CherryAgentAWS --name CherryAgent \
  --language Python --framework Strands --model-provider Bedrock \
  --memory none --build CodeZip --skip-git --skip-python-setup --skip-install \
  --output-dir ../CherryAgentAWS
```

Before deploying, replace the generated agent implementation with this repository's
`agentcore/cherry_agent.py`, and package `agents/`, `app/`, and `fixtures/` with the project dependencies.
The runtime must start that entrypoint, not the generated demo chatbot or the legacy FastAPI server.
Inspect the generated project schema and synthesized IAM before deployment; scaffold generation alone
is not a deployable Cherry build. Runtime environment must include the selected model and region.
Use the proposed scoped runtime policy below in place of any generated broad Bedrock permissions.

From the generated project, with the repository's absolute guard-script path available:

```bash
"$CHERRY_REPO/scripts/verify_aws_target.sh"
agentcore deploy --dry-run
agentcore deploy --diff
"$CHERRY_REPO/scripts/verify_aws_target.sh"
agentcore deploy --yes
agentcore status
```

Set `CHERRY_REPO` to your repository path before these commands. Capture the actual runtime ARN from
successful deployment/status output, then invoke it from the repository:

```bash
./scripts/test_agentcore_runtime.sh "$RUNTIME_ARN"
```

The script checks account/region and ARN scope, fails on AWS API errors and runtime error responses,
and requires a Strands response. Do not claim deployment succeeded until creation and invocation pass.

## A. Deployment identity permissions

Provisioning permissions belong to the deployment identity, never the runtime identity. AgentCore CLI
0.29.0 deploys via CDK/CloudFormation. Scope CloudFormation operations to the generated Cherry stack;
artifact upload to its exact deployment bucket/prefix; AgentCore create/update/get/list operations to
this runtime where AWS supports resource scoping; IAM role/policy operations to the Cherry runtime
role; and `iam:PassRole` to that exact role with `iam:PassedToService=bedrock-agentcore.amazonaws.com`.
CDK bootstrap roles/artifact bucket must be pre-provisioned or separately reviewed. Container builds
add ECR/build permissions; CodeZip does not justify unrestricted ECR, S3 or Secrets Manager access.
Derive exact resource names from the generated template before granting provisioning permissions.

## B. Runtime identity permissions

`infra/aws/agentcore-runtime-policy.json` proposes only `bedrock:InvokeModel` and
`bedrock:InvokeModelWithResponseStream` for the selected EU profile and its seven actual destination
model ARNs (verified using GetInferenceProfile). Foundation-model invocation is conditioned on the
selected profile, following [AWS inference-profile IAM guidance](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html).

The runtime role trust must allow AgentCore with source account 821465445270 and the runtime ARN
scope. If the selected deployment needs artifact reads or log delivery, add only its exact artifact
object and log group/stream permissions after inspecting generated assets. No payment, beneficiary,
approval, administrator, unrestricted IAM/S3 or secrets permissions are part of the runtime policy.

## Demo / Devpost

Track: **Professional Agents**. Built with Strands Agents SDK, Amazon Bedrock, Amazon Bedrock AgentCore,
Python, FastAPI, Pydantic, Docker and deterministic financial controls.

1. Autonomous routine reconciliation: show deterministic match and policy evidence.
2. Human approval required: explain the blocked workflow and explicit human review.
3. Evidence exception: explain missing/conflicting evidence and refuse to guess.

Strands orchestrates; Cherry deterministic code holds financial authority; humans hold approval
 authority. The existing reconciliation engine, Google ADK, Ylookup/FundOps and Cherry Money work
are reused, not claimed as new hackathon work. See `PREEXISTING_CODE.md`.

## Verification recorded 14 September 2026

Account guard verified 821465445270 / eu-west-2 / devops-user. The selected EU Sonnet 4.6
profile is ACTIVE and its foundation model is listed in London. The live hierarchy reached
ConverseStream but failed with `ResourceNotFoundException`: Anthropic model use-case details
have not been submitted for this account. AWS asks the account owner to submit the Anthropic
use-case form (or allow 15 minutes if already submitted). This is an account onboarding blocker,
not a missing profile or reason to broaden IAM. Other Sonnet profiles are listed as ACTIVE,
but switching profiles does not resolve the account-wide Anthropic prerequisite.

No AgentCore runtime has been created or invoked by this implementation run. Complete the
account's Anthropic use-case details with accurate organisational information, rerun the guarded
Bedrock smoke test, and only then prepare/deploy the dedicated runtime as described above.
