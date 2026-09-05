#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-europe-west1}"
SERVICE="cherry-finops"
REPOSITORY="cherry-agent"
MODEL="${CHERRY_GEMINI_MODEL:-gemini-3.7-flash}"
TOKEN_FILE="${HOME}/.cherry-finops-demo-token"

command -v gcloud >/dev/null || { echo "Run this script in Google Cloud Shell." >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker is required in Cloud Shell." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required in Cloud Shell." >&2; exit 1; }

if [[ -z "${PROJECT_ID}" ]]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi
if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "(unset)" ]]; then
  echo "Usage: $0 GOOGLE_CLOUD_PROJECT_ID [REGION]" >&2
  exit 2
fi

if [[ -z "${GOOGLE_API_KEY:-}" ]]; then
  cat >&2 <<'MESSAGE'
GOOGLE_API_KEY is not set.

This gcplab.me project blocks project IAM policy changes, so this deployment intentionally uses the
hackathon-provided Gemini API key instead of creating/granting a privileged Vertex AI runtime
service account.

Rotate any key that has been shared publicly, then in Cloud Shell enter the replacement without
putting it in shell history:

  read -rsp "Gemini API key: " GOOGLE_API_KEY; echo
  export GOOGLE_API_KEY

Then rerun this script.
MESSAGE
  exit 2
fi

ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
echo "Deploying Cherry FundOps from account: ${ACCOUNT}"
echo "Project: ${PROJECT_ID}"
echo "Region:  ${REGION}"
echo "Mode:    restricted-IAM gcplab / Gemini API key / memory persistence"

gcloud config set project "${PROJECT_ID}" >/dev/null

if [[ "$(gcloud projects describe "${PROJECT_ID}" --format='value(projectId)' 2>/dev/null || true)" != "${PROJECT_ID}" ]]; then
  echo "Project ${PROJECT_ID} does not exist or this account cannot access it." >&2
  exit 1
fi

# The temporary gcplab.me accounts intentionally restrict setIamPolicy. Keep this deployment
# compatible with those restrictions: no project IAM mutations, no custom runtime role grants,
# no Firestore/Storage/PubSub dependencies. The judge-facing workflow still uses Cloud Run and
# real Gemini document understanding, while deterministic Cherry controls remain unchanged.
SERVICES=(
  run.googleapis.com
  artifactregistry.googleapis.com
  generativelanguage.googleapis.com
  serviceusage.googleapis.com
)
gcloud services enable "${SERVICES[@]}"

if ! gcloud artifacts repositories describe "${REPOSITORY}" --location "${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Cherry FundOps container images"
fi

if [[ -n "${CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN:-}" ]]; then
  UPLOAD_TOKEN="${CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN}"
else
  UPLOAD_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
fi
printf '%s\n' "${UPLOAD_TOKEN}" > "${TOKEN_FILE}"
chmod 600 "${TOKEN_FILE}"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${SERVICE}:$(date -u +%Y%m%d-%H%M%S)"

echo "Configuring Docker authentication for Artifact Registry…"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "Building ${IMAGE}…"
docker build --tag "${IMAGE}" .
docker push "${IMAGE}"

echo "Deploying Cloud Run service…"
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --platform=managed \
  --no-invoker-iam-check \
  --ingress=all \
  --default-url \
  --memory=1Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=5 \
  --set-env-vars="CHERRY_ENVIRONMENT=production,CHERRY_PERSISTENCE_BACKEND=memory,CHERRY_GEMINI_MODEL=${MODEL},CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN=${UPLOAD_TOKEN},GOOGLE_GENAI_USE_VERTEXAI=false,GOOGLE_API_KEY=${GOOGLE_API_KEY},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=global"

SERVICE_URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --format='value(status.url)')"

gcloud run services update "${SERVICE}" \
  --region="${REGION}" \
  --update-env-vars="CHERRY_PUBLIC_BASE_URL=${SERVICE_URL}" \
  --quiet >/dev/null

SERVICE_URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --format='value(status.url)')"
echo "Cloud Run URL: ${SERVICE_URL}"

echo "Running smoke tests…"
curl --fail --retry 12 --retry-delay 5 --retry-all-errors "${SERVICE_URL}/" >/dev/null
curl --fail --retry 12 --retry-delay 5 --retry-all-errors "${SERVICE_URL}/api/config" | python3 -m json.tool
curl --fail --retry 12 --retry-delay 5 --retry-all-errors "${SERVICE_URL}/api/private-markets/health" | python3 -m json.tool
curl --fail --retry 12 --retry-delay 5 --retry-all-errors "${SERVICE_URL}/api/private-markets/integration/health" | python3 -m json.tool
curl --fail --retry 12 --retry-delay 5 --retry-all-errors \
  -X POST "${SERVICE_URL}/api/private-markets/demo/clean" >/dev/null

echo
echo "Cherry FundOps deployment complete."
echo "URL: ${SERVICE_URL}"
echo "Gemini mode: API key (GOOGLE_GENAI_USE_VERTEXAI=false)"
echo "Persistence: memory (appropriate for the temporary hackathon runtime)"
echo "Demo upload token saved locally at: ${TOKEN_FILE}"
echo "Do not paste the API key or upload token into chat or commit either to Git."
echo "This temporary gcplab.me project should be treated as hackathon-only runtime infrastructure."
