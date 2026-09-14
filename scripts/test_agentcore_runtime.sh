#!/usr/bin/env bash
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-devops-user}"
export AWS_REGION="${AWS_REGION:-eu-west-2}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-eu-west-2}"
"$(dirname "$0")/verify_aws_target.sh"
runtime_arn="${1:?Usage: test_agentcore_runtime.sh runtime-arn}"
case "$runtime_arn" in
  arn:aws:bedrock-agentcore:eu-west-2:821465445270:runtime/*) ;;
  *) echo 'Runtime ARN must match the verified account and region.' >&2; exit 1 ;;
esac
response_file="$(mktemp)"
trap 'rm -f "$response_file"' EXIT
aws bedrock-agentcore invoke-agent-runtime \
  --region "$AWS_REGION" \
  --cli-read-timeout 900 \
  --agent-runtime-arn "$runtime_arn" \
  --content-type application/json \
  --accept application/json \
  --cli-binary-format raw-in-base64-out \
  --payload '{"prompt":"Run a synthetic approval scenario. Explain the deterministic control and required human review. Never approve or initiate payments."}' \
  "$response_file"
python3 - "$response_file" <<'PY'
import json
import sys
from pathlib import Path
result = json.loads(Path(sys.argv[1]).read_text())
if isinstance(result, str):
    result = json.loads(result)
if not isinstance(result, dict) or result.get("error") or not result.get("response"):
    raise SystemExit("Runtime returned an invalid or error response")
if result.get("framework") != "Strands Agents SDK":
    raise SystemExit("Unexpected runtime implementation")
print(json.dumps(result, indent=2))
PY
