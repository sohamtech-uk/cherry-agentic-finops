#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-europe-west1}"
DOMAIN="${3:-finops.cherrymoney.co.uk}"
SERVICE="cherry-agent"
REPOSITORY="cherry-agent"
RUNTIME_SA="cherry-agent-runtime"
MODEL="${CHERRY_GEMINI_MODEL:-gemini-3.7-flash}"
TOPIC="finance-workflow-events"
BUCKET="${PROJECT_ID}-cherry-finops-evidence"

command -v gcloud >/dev/null || { echo "Run this script in Google Cloud Shell." >&2; exit 1; }

if [[ -z "${PROJECT_ID}" ]]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
fi
if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "(unset)" ]]; then
  echo "Usage: $0 GOOGLE_CLOUD_PROJECT_ID [REGION] [DOMAIN]" >&2
  echo "Or select a project first: gcloud config set project YOUR_PROJECT_ID" >&2
  exit 2
fi

echo "Deploying Cherry Agent as $(gcloud config get-value account 2>/dev/null)"
echo "Project: ${PROJECT_ID}"
echo "Region:  ${REGION}"
echo "Domain:  ${DOMAIN}"

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
    --description="Cherry Agent container images"
fi

if ! gcloud iam service-accounts describe "${RUNTIME_SA}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${RUNTIME_SA}" \
    --display-name="Cherry Agent Cloud Run runtime"
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

gcloud storage buckets update "gs://${BUCKET}" --versioning

if ! gcloud pubsub topics describe "${TOPIC}" >/dev/null 2>&1; then
  gcloud pubsub topics create "${TOPIC}"
fi

if ! gcloud firestore databases describe --database='(default)' >/dev/null 2>&1; then
  echo "Creating the default Firestore Native database in eur3…"
  gcloud firestore databases create --database='(default)' --location=eur3 --type=firestore-native
fi

gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_EMAIL}" \
  --role="roles/storage.objectAdmin" \
  --quiet >/dev/null

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${SERVICE}:$(date -u +%Y%m%d-%H%M%S)"

echo "Configuring Docker authentication for Artifact Registry…"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "Building ${IMAGE} in Cloud Shell…"
docker build --tag "${IMAGE}" .
docker push "${IMAGE}"

echo "Deploying Cloud Run service…"
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --service-account="${RUNTIME_EMAIL}" \
  --memory=1Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=5 \
  --set-env-vars="CHERRY_ENVIRONMENT=production,CHERRY_PUBLIC_BASE_URL=https://${DOMAIN},CHERRY_PERSISTENCE_BACKEND=firestore,CHERRY_GEMINI_MODEL=${MODEL},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=global,CHERRY_EVIDENCE_BUCKET=${BUCKET},CHERRY_PUBSUB_TOPIC=${TOPIC}"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
DETERMINISTIC_URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
LEGACY_URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --format='value(status.url)')"
SERVICE_URL="${DETERMINISTIC_URL}"

echo "Cloud Run deterministic URL: ${DETERMINISTIC_URL}"
if curl --fail --silent --show-error "${DETERMINISTIC_URL}/healthz"; then
  echo
  echo "Health check passed."
elif [[ -n "${LEGACY_URL}" && "${LEGACY_URL}" != "${DETERMINISTIC_URL}" ]] && curl --fail --silent --show-error "${LEGACY_URL}/healthz"; then
  SERVICE_URL="${LEGACY_URL}"
  echo
  echo "Health check passed on alternate Cloud Run URL: ${LEGACY_URL}"
else
  echo
  echo "WARNING: Cloud Run deployment completed but /healthz did not return HTTP 2xx yet." >&2
  echo "Check the service directly and inspect logs before changing DNS:" >&2
  echo "  curl -i ${DETERMINISTIC_URL}/healthz" >&2
  echo "  gcloud run services logs read ${SERVICE} --region=${REGION} --limit=50" >&2
fi

BASE_DOMAIN="${DOMAIN#*.}"
if gcloud domains list-user-verified --format='value(id)' 2>/dev/null | grep -qx "${BASE_DOMAIN}"; then
  echo "Creating or updating domain mapping for ${DOMAIN}…"
  if ! gcloud beta run domain-mappings describe --domain="${DOMAIN}" --region="${REGION}" >/dev/null 2>&1; then
    gcloud beta run domain-mappings create \
      --service="${SERVICE}" \
      --domain="${DOMAIN}" \
      --region="${REGION}"
  fi
  echo
  echo "Add the following records in the DNS control panel for cherrymoney.co.uk:"
  gcloud beta run domain-mappings describe \
    --domain="${DOMAIN}" \
    --region="${REGION}" \
    --format='table(status.resourceRecords[].type,status.resourceRecords[].name,status.resourceRecords[].rrdata)'
else
  cat <<MESSAGE

The Cloud Run service is live, but ${BASE_DOMAIN} is not verified for this Google account.
Complete domain verification, then run:

  gcloud domains verify ${BASE_DOMAIN}
  gcloud beta run domain-mappings create --service=${SERVICE} --domain=${DOMAIN} --region=${REGION}
  gcloud beta run domain-mappings describe --domain=${DOMAIN} --region=${REGION}

The required CNAME/A/AAAA records must be added in the domain's DNS control panel. FTP access cannot
change DNS records.
MESSAGE
fi

echo
echo "Deployment complete. Cloud Run URL: ${SERVICE_URL}"
echo "Managed TLS can take from several minutes up to 24 hours after DNS is correct."
