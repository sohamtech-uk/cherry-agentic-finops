#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-europe-west1}"
SERVICE="cherry-finops"
REPOSITORY="cherry-agent"
RUNTIME_SA="cherry-agent-runtime"
MODEL="${CHERRY_GEMINI_MODEL:-gemini-3.7-flash}"
TOPIC="finance-workflow-events"
BUCKET="${PROJECT_ID}-cherry-finops-evidence"
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

ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
echo "Deploying Cherry FundOps from account: ${ACCOUNT}"
echo "Project: ${PROJECT_ID}"
echo "Region:  ${REGION}"

gcloud config set project "${PROJECT_ID}" >/dev/null

if [[ "$(gcloud projects describe "${PROJECT_ID}" --format='value(projectId)' 2>/dev/null || true)" != "${PROJECT_ID}" ]]; then
  echo "Project ${PROJECT_ID} does not exist or this account cannot access it." >&2
  exit 1
fi

SERVICES=(
  run.googleapis.com
  artifactregistry.googleapis.com
  aiplatform.googleapis.com
  firestore.googleapis.com
  storage.googleapis.com
  pubsub.googleapis.com
  iam.googleapis.com
  iamcredentials.googleapis.com
  serviceusage.googleapis.com
)
gcloud services enable "${SERVICES[@]}"

if ! gcloud artifacts repositories describe "${REPOSITORY}" --location "${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Cherry FundOps container images"
fi

if ! gcloud iam service-accounts describe "${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${RUNTIME_SA}" \
    --display-name="Cherry FundOps Cloud Run runtime"
fi

RUNTIME_EMAIL="${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com"
for role in roles/aiplatform.user roles/datastore.user roles/pubsub.publisher roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet >/dev/null
done

if ! gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET}" \
    --location="${REGION}" \
    --uniform-bucket-level-access
fi

gcloud storage buckets update "gs://${BUCKET}" --versioning >/dev/null

gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_EMAIL}" \
  --role="roles/storage.objectAdmin" \
  --quiet >/dev/null

if ! gcloud pubsub topics describe "${TOPIC}" >/dev/null 2>&1; then
  gcloud pubsub topics create "${TOPIC}"
fi

if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
  echo "Creating the default Firestore Native database in eur3…"
  gcloud firestore databases create --database='(default)' --location=eur3 --type=firestore-native
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
  --service-account="${RUNTIME_EMAIL}" \
  --memory=1Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=5 \
  --set-env-vars="CHERRY_ENVIRONMENT=production,CHERRY_PERSISTENCE_BACKEND=firestore,CHERRY_GEMINI_MODEL=${MODEL},CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN=${UPLOAD_TOKEN},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=global,CHERRY_EVIDENCE_BUCKET=${BUCKET},CHERRY_PUBSUB_TOPIC=${TOPIC}"

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
echo "Demo upload token saved locally at: ${TOKEN_FILE}"
echo "Do not paste that token into chat or commit it to Git."
echo "This temporary gcplab.me project should be treated as hackathon-only runtime infrastructure."
