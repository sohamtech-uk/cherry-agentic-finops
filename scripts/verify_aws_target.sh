#!/usr/bin/env bash
set -euo pipefail
EXPECTED_ACCOUNT="821465445270"
EXPECTED_REGION="eu-west-2"
export AWS_PROFILE="${AWS_PROFILE:-devops-user}"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region --profile "$AWS_PROFILE")}}"
if [[ "$region" != "$EXPECTED_REGION" ]]; then
  echo "Refusing unexpected AWS region: $region" >&2
  exit 1
fi
if [[ -n "${AWS_DEFAULT_REGION:-}" && "$AWS_DEFAULT_REGION" != "$EXPECTED_REGION" ]]; then
  echo 'Conflicting AWS_DEFAULT_REGION; refusing.' >&2
  exit 1
fi
account="$(aws sts get-caller-identity --region "$region" --query Account --output text)"
if [[ "$account" != "$EXPECTED_ACCOUNT" ]]; then
  echo "Refusing unexpected AWS account: $account" >&2
  exit 1
fi
printf 'AWS target verified\nAccount: %s\nRegion: %s\nProfile: %s\n' "$account" "$region" "$AWS_PROFILE"
