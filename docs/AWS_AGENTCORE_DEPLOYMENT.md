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

## Verified live deployment — 14 September 2026

Anthropic use-case details were submitted successfully (HTTP 201) for Soham London CIC / Cherry
Money. After propagation, the clean Bedrock hierarchy test passed. AgentCore returned HTTP 200
with a synthetic approval workflow still paused for human review.

- Account: `821465445270`; region: `eu-west-2`
- Runtime ID: `CherryAgentAWS_CherryAgent-wT0VRK4Prn`
- Runtime ARN: `arn:aws:bedrock-agentcore:eu-west-2:821465445270:runtime/CherryAgentAWS_CherryAgent-wT0VRK4Prn`
- Version: 1; status: READY
- Runtime role: `CherryAgentAWS-Runtime`
- Model: `eu.anthropic.claude-sonnet-4-6`

The generated CLI role grants broad Bedrock permissions. The actual deployment instead uses the
scoped policy plus its exact private artifact object and runtime log prefix. No CDK bootstrap or
administrator policy was created. The CLI packages Linux ARM64 dependencies; the guarded AWS SDK
script provisions the runtime directly.

### Reproduce the actual deployment

After creating the dedicated CLI project using the command above:

```bash
python scripts/prepare_agentcore_package.py ../CherryAgentAWS/CherryAgentAWS
agentcore package --directory ../CherryAgentAWS/CherryAgentAWS --runtime CherryAgent
./scripts/verify_aws_target.sh
python scripts/deploy_agentcore_runtime.py \
  ../CherryAgentAWS/CherryAgentAWS/agentcore/CherryAgent.zip
./scripts/test_agentcore_runtime.sh \
  arn:aws:bedrock-agentcore:eu-west-2:821465445270:runtime/CherryAgentAWS_CherryAgent-wT0VRK4Prn
```

The package is approximately 58 MB compressed / 164 MB uncompressed. No credential directories
or environment files are included. The smoke script allows 900 seconds; the AWS CLI default
60-second read timeout is too short for specialist workflows and can retry a completed request.

### AWS web demo

`infra/aws/web/` contains a dedicated synthetic demo frontend and Lambda gateway. `scripts/deploy_finops_web.py`
creates a CloudFront distribution with an IAM-only Lambda URL protected by CloudFront origin access
control. A separate worker invokes only the named AgentCore runtime. The gateway accepts only the
three predefined scenario names, never arbitrary prompts/customer data. An atomic S3 admission gate
allows one run per two-minute window across all visitors; synthetic result objects expire after one day.
The account Lambda quota does not currently allow reserved concurrency.

```bash
./scripts/verify_aws_target.sh
python scripts/deploy_finops_web.py
```

CloudFront distribution: `E25DLWEQBEAV79`, hostname `d32u7o814bb2xb.cloudfront.net`.
The custom domain requires a DNS-validated ACM certificate in us-east-1 (CloudFront requirement),
then adding the domain alias and replacing only the `finops` DNS record. AgentCore, Lambda and S3
remain in eu-west-2. Existing Google Cloud services are unchanged.


The public browser scenario completed end to end through CloudFront, the Lambda gateway/worker and
AgentCore on 14 September 2026. It reported auto-reconciliation for the routine item, human approval
required for the high-value item, and an evidence exception for conflicting data. All 366 tests,
Ruff lint/format and mypy checks passed. Worker IAM explicitly includes both the runtime ARN and
its `/runtime-endpoint/DEFAULT` ARN.

To finish the custom hostname, add this GoDaddy DNS record (leave it in place for certificate renewal):

| Type | Name | Value |
| --- | --- | --- |
| CNAME | `_70af0cebda8505ece993210fd8f5dbf3.finops` | `_5192b18c7b602a5ef46e674a3f1dc139.wzccmgtwzk.acm-validations.aws` |

Once ACM reports ISSUED, run `python scripts/attach_finops_domain.py`. Wait until distribution
`E25DLWEQBEAV79` reports Deployed, verify HTTPS for the custom hostname against its CloudFront IP,
then replace only the existing `finops` A record with a CNAME to `d32u7o814bb2xb.cloudfront.net`.
The custom hostname remains pending until these DNS steps are completed.


### Branded demo and focused AI reports

The AWS demo uses the Cherry Money palette: burgundy `#581425`, coral `#d93b52`,
and warm white `#f6f7f2`. Scenario states have text labels as well as green, amber and red colours.
The gateway prompt now requests only the selected scenario, shared workflow evidence across
specialists, and a structured Decision / Evidence checked / Next action / Control boundary report.
The frontend renders headings, lists and evidence tables using DOM text nodes, without executing
model-supplied HTML. It includes elapsed-time feedback, reduced-motion support and report copying.

A live approval scenario completed in 59 seconds after this update. The report concerned only
the selected approval workflow, showed `awaiting_approval`, null human consent and the deterministic
threshold, and rendered the evidence table successfully. Browser error logs were empty.
The web gateway tests (9 cases), Ruff checks and JavaScript syntax check passed.

The finops ACM certificate has been issued and attached to CloudFront; the distribution is Deployed. HTTPS for the custom hostname
has been verified directly against a CloudFront edge address with normal certificate validation.
The final GoDaddy `finops` record must point to `d32u7o814bb2xb.cloudfront.net`.


### Custom domain cutover and original animation

The GoDaddy `finops` CNAME now points to `d32u7o814bb2xb.cloudfront.net`, confirmed against
the authoritative nameserver and both Cloudflare and Google public DNS resolvers. The custom
hostname passed HTTPS checks against CloudFront for the homepage and AgentCore gateway health.
Some local DNS caches can continue serving the previous GCP address until its TTL expires.

The original FinOps Cherry character and counter-rotating orbit animation have been retained in
the AWS frontend, with the Cherry Money palette, original 24-second/18-second motion, and a
pause/resume control. Reduced-motion preferences stop the animation. Live browser checks
confirmed both animation timings, pause/resume and no horizontal overflow. Only the AWS frontend
was deployed; the existing Google Cloud service remains unchanged.


### Public architecture diagram

The AWS frontend now exposes `/#architecture` and a header navigation link. The diagram describes
the deployed path: CloudFront → Lambda gateway → asynchronous Lambda worker → AgentCore. It
shows the Strands orchestrator, three specialist agents, Bedrock Claude Sonnet 4.6, deterministic
Cherry tools and controlled outcomes. Supporting notes explain private S3 response polling,
one-day result retention, CloudWatch, scoped IAM and in-memory demo workflow state.
The previous Google Cloud diagram describes the preserved GCP implementation, not the AWS demo.
