#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${REGION:-europe-west2}"
SERVICE_NAME="${SERVICE_NAME:-cherry-agent-finops}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID or GOOGLE_CLOUD_PROJECT is required." >&2
  exit 2
fi

gcloud config set project "${PROJECT_ID}" >/dev/null

# The project can create Cloud Run services with their default run.app URL
# disabled. Public invoker configuration alone then produces Google's
# platform-level 404. Explicitly enable the default URL before validating the
# application and configuring the external HTTPS load balancer.
gcloud run services update "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --default-url \
  --no-invoker-iam-check \
  --ingress=all \
  --quiet

sleep 10
exec bash "$(dirname "$0")/finalise-gcp-deployment.sh"
