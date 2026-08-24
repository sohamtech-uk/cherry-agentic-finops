#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${REGION:-europe-west2}"
DOMAIN="${DOMAIN:-finops.cherrymoney.co.uk}"
SERVICE_NAME="${SERVICE_NAME:-cherry-agent-finops}"
ARTIFACT_REPOSITORY="${ARTIFACT_REPOSITORY:-cherrybank}"
IMAGE_NAME="${IMAGE_NAME:-cherry-agent-finops}"
RUNTIME_SERVICE_ACCOUNT_NAME="${RUNTIME_SERVICE_ACCOUNT_NAME:-cherry-agent-finops}"
EVIDENCE_BUCKET="${EVIDENCE_BUCKET:-${PROJECT_ID}-cherry-agent-evidence}"
PUBSUB_TOPIC="${PUBSUB_TOPIC:-cherry-agent-events}"
GEMINI_MODEL="${CHERRY_GEMINI_MODEL:-gemini-3.7-flash}"
LOAD_BALANCER_ADDRESS="${LOAD_BALANCER_ADDRESS:-cherrybank-lb-ip}"
URL_MAP_NAME="${URL_MAP_NAME:-cherrybank-https-map}"
TARGET_HTTPS_PROXY_NAME="${TARGET_HTTPS_PROXY_NAME:-cherrybank-https-proxy}"
SERVERLESS_NEG="${SERVERLESS_NEG:-cherry-agent-finops-neg}"
BACKEND_SERVICE="${BACKEND_SERVICE:-cherry-agent-finops-backend}"
SSL_CERTIFICATE="${SSL_CERTIFICATE:-cherry-agent-finops-cert}"
RESULT_FILE="${RESULT_FILE:-/tmp/cherry-agent-finops-deployment.json}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID or GOOGLE_CLOUD_PROJECT is required." >&2
  exit 2
fi

for command in gcloud docker jq curl; do
  command -v "${command}" >/dev/null || {
    echo "Required command is unavailable: ${command}" >&2
    exit 2
  }
done

write_env() {
  local key="$1"
  local value="$2"
  export "${key}=${value}"
  if [[ -n "${GITHUB_ENV:-}" ]]; then
    printf '%s=%s\n' "${key}" "${value}" >> "${GITHUB_ENV}"
  fi
}

record_result() {
  local status="$1"
  python - "${RESULT_FILE}" "${status}" <<'PY'
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

path = Path(sys.argv[1])
status = sys.argv[2]
result = {
    "status": status,
    "project_id": os.environ.get("PROJECT_ID", ""),
    "region": os.environ.get("REGION", ""),
    "domain": os.environ.get("DOMAIN", ""),
    "domain_url": f"https://{os.environ.get('DOMAIN', '')}",
    "service": os.environ.get("SERVICE_NAME", ""),
    "service_url": os.environ.get("SERVICE_URL", ""),
    "image": os.environ.get("IMAGE", ""),
    "load_balancer_ip": os.environ.get("LB_IP", ""),
    "dns_zone": os.environ.get("DNS_ZONE", ""),
    "manual_dns_required": os.environ.get("DNS_MANUAL", "unknown"),
    "certificate_status": os.environ.get("CERT_STATUS", ""),
    "persistence_backend": os.environ.get("CHERRY_PERSISTENCE_BACKEND", ""),
    "source_commit": os.environ.get("SOURCE_COMMIT", ""),
    "recorded_at": datetime.now(UTC).isoformat(),
}
path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2))
PY
}

on_error() {
  local exit_code=$?
  record_result "failed" || true
  exit "${exit_code}"
}
trap on_error ERR

export PROJECT_ID REGION DOMAIN SERVICE_NAME RESULT_FILE

gcloud config set project "${PROJECT_ID}" >/dev/null

if [[ "$(gcloud projects describe "${PROJECT_ID}" --format='value(projectId)')" != "${PROJECT_ID}" ]]; then
  echo "Google Cloud project is unavailable: ${PROJECT_ID}" >&2
  exit 1
fi

required_services=(
  run.googleapis.com
  artifactregistry.googleapis.com
  aiplatform.googleapis.com
  firestore.googleapis.com
  pubsub.googleapis.com
  storage.googleapis.com
  compute.googleapis.com
  dns.googleapis.com
  iam.googleapis.com
  iamcredentials.googleapis.com
  cloudresourcemanager.googleapis.com
  serviceusage.googleapis.com
)
gcloud services enable "${required_services[@]}" --project="${PROJECT_ID}" --quiet

runtime_email="${RUNTIME_SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "${runtime_email}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${RUNTIME_SERVICE_ACCOUNT_NAME}" \
    --project="${PROJECT_ID}" \
    --display-name="Cherry Agent FinOps runtime"
fi

runtime_roles=(
  roles/aiplatform.user
  roles/datastore.user
  roles/pubsub.publisher
  roles/storage.objectAdmin
  roles/logging.logWriter
)
for role in "${runtime_roles[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${runtime_email}" \
    --role="${role}" \
    --condition=None \
    --quiet >/dev/null
done

if ! gcloud artifacts repositories describe "${ARTIFACT_REPOSITORY}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${ARTIFACT_REPOSITORY}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --repository-format=docker \
    --description="Cherry Money container images"
fi

if ! gcloud storage buckets describe "gs://${EVIDENCE_BUCKET}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${EVIDENCE_BUCKET}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --uniform-bucket-level-access
fi
gcloud storage buckets update "gs://${EVIDENCE_BUCKET}" --versioning >/dev/null

gcloud storage buckets add-iam-policy-binding "gs://${EVIDENCE_BUCKET}" \
  --member="serviceAccount:${runtime_email}" \
  --role="roles/storage.objectAdmin" \
  --quiet >/dev/null

if ! gcloud pubsub topics describe "${PUBSUB_TOPIC}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud pubsub topics create "${PUBSUB_TOPIC}" --project="${PROJECT_ID}"
fi

persistence_backend="firestore"
if ! gcloud firestore databases describe \
  --database='(default)' \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  if ! gcloud firestore databases create \
    --database='(default)' \
    --location=eur3 \
    --type=firestore-native \
    --project="${PROJECT_ID}" \
    --quiet; then
    echo "Firestore could not be created; using in-memory workflow persistence." >&2
    persistence_backend="memory"
  fi
fi
write_env CHERRY_PERSISTENCE_BACKEND "${persistence_backend}"

image_tag="finops-${GITHUB_RUN_ID:-$(date -u +%Y%m%d%H%M%S)}-${GITHUB_RUN_ATTEMPT:-1}"
image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPOSITORY}/${IMAGE_NAME}:${image_tag}"

gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker build \
  --label "org.opencontainers.image.revision=${SOURCE_COMMIT:-unknown}" \
  --label "org.opencontainers.image.source=https://github.com/sohamtech-uk/cherry-agentic-finops" \
  --tag "${image}" \
  .
docker push "${image}"
write_env IMAGE "${image}"

run_flags=(
  --project="${PROJECT_ID}"
  --region="${REGION}"
  --platform=managed
  --image="${image}"
  --service-account="${runtime_email}"
  --port=8080
  --execution-environment=gen2
  --cpu=1
  --memory=1Gi
  --min-instances=0
  --max-instances=3
  --concurrency=40
  --timeout=300
  --allow-unauthenticated
  --ingress=all
  --set-env-vars="CHERRY_ENVIRONMENT=production,CHERRY_PUBLIC_BASE_URL=https://${DOMAIN},CHERRY_PERSISTENCE_BACKEND=${persistence_backend},CHERRY_GEMINI_MODEL=${GEMINI_MODEL},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=global,CHERRY_FIRESTORE_COLLECTION=cherry_agent_finops_workflows,CHERRY_EVIDENCE_BUCKET=${EVIDENCE_BUCKET},CHERRY_PUBSUB_TOPIC=${PUBSUB_TOPIC},CHERRY_MONEY_API_URL=https://cherrymoney.co.uk/api"
  --labels="app=cherry-agent,environment=hackathon,managed-by=github-actions"
  --quiet
)
if gcloud run deploy --help 2>/dev/null | grep -q -- '--default-url'; then
  run_flags+=(--default-url)
fi

gcloud run deploy "${SERVICE_NAME}" "${run_flags[@]}"

service_url="$(gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format='value(status.url)')"
write_env SERVICE_URL "${service_url}"

curl --fail --silent --show-error \
  --retry 12 \
  --retry-delay 5 \
  --retry-all-errors \
  "${service_url}/health"

if ! gcloud compute network-endpoint-groups describe "${SERVERLESS_NEG}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" >/dev/null 2>&1; then
  gcloud compute network-endpoint-groups create "${SERVERLESS_NEG}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --network-endpoint-type=serverless \
    --cloud-run-service="${SERVICE_NAME}"
fi

if ! gcloud compute backend-services describe "${BACKEND_SERVICE}" \
  --project="${PROJECT_ID}" \
  --global >/dev/null 2>&1; then
  gcloud compute backend-services create "${BACKEND_SERVICE}" \
    --project="${PROJECT_ID}" \
    --global \
    --load-balancing-scheme=EXTERNAL_MANAGED \
    --protocol=HTTP \
    --port-name=http \
    --timeout=30
fi

if ! gcloud compute backend-services describe "${BACKEND_SERVICE}" \
  --project="${PROJECT_ID}" \
  --global \
  --format='value(backends.group)' | grep -q "${SERVERLESS_NEG}"; then
  gcloud compute backend-services add-backend "${BACKEND_SERVICE}" \
    --project="${PROJECT_ID}" \
    --global \
    --network-endpoint-group="${SERVERLESS_NEG}" \
    --network-endpoint-group-region="${REGION}"
fi

url_map_json="$(gcloud compute url-maps describe "${URL_MAP_NAME}" \
  --project="${PROJECT_ID}" \
  --global \
  --format=json)"
if ! jq -e --arg domain "${DOMAIN}" \
  '[.hostRules[]?.hosts[]?] | index($domain) != null' \
  <<<"${url_map_json}" >/dev/null; then
  gcloud compute url-maps add-path-matcher "${URL_MAP_NAME}" \
    --project="${PROJECT_ID}" \
    --global \
    --path-matcher-name=finops \
    --default-service="${BACKEND_SERVICE}" \
    --new-hosts="${DOMAIN}"
fi

if ! gcloud compute ssl-certificates describe "${SSL_CERTIFICATE}" \
  --project="${PROJECT_ID}" \
  --global >/dev/null 2>&1; then
  gcloud compute ssl-certificates create "${SSL_CERTIFICATE}" \
    --project="${PROJECT_ID}" \
    --global \
    --domains="${DOMAIN}"
fi

proxy_json="$(gcloud compute target-https-proxies describe "${TARGET_HTTPS_PROXY_NAME}" \
  --project="${PROJECT_ID}" \
  --global \
  --format=json)"
mapfile -t certificates < <(
  jq -r '.sslCertificates[]? | split("/")[-1]' <<<"${proxy_json}"
)
if ! printf '%s\n' "${certificates[@]}" | grep -qx "${SSL_CERTIFICATE}"; then
  certificates+=("${SSL_CERTIFICATE}")
  certificate_csv="$(IFS=,; echo "${certificates[*]}")"
  gcloud compute target-https-proxies update "${TARGET_HTTPS_PROXY_NAME}" \
    --project="${PROJECT_ID}" \
    --global \
    --ssl-certificates="${certificate_csv}"
fi

lb_ip="$(gcloud compute addresses describe "${LOAD_BALANCER_ADDRESS}" \
  --project="${PROJECT_ID}" \
  --global \
  --format='value(address)')"
write_env LB_IP "${lb_ip}"

dns_name="${DOMAIN}."
dns_zone="$(gcloud dns managed-zones list \
  --project="${PROJECT_ID}" \
  --filter='dnsName=cherrymoney.co.uk.' \
  --format='value(name)' | head -n 1)"

if [[ -n "${dns_zone}" ]]; then
  current_record="$(gcloud dns record-sets list \
    --project="${PROJECT_ID}" \
    --zone="${dns_zone}" \
    --name="${dns_name}" \
    --type=A \
    --format='value(rrdatas)' | tr ';' ',' || true)"

  if [[ -n "${current_record}" && "${current_record}" != "${lb_ip}" ]]; then
    gcloud dns record-sets delete "${dns_name}" \
      --project="${PROJECT_ID}" \
      --zone="${dns_zone}" \
      --type=A \
      --quiet
    current_record=""
  fi

  if [[ -z "${current_record}" ]]; then
    gcloud dns record-sets create "${dns_name}" \
      --project="${PROJECT_ID}" \
      --zone="${dns_zone}" \
      --type=A \
      --ttl=300 \
      --rrdatas="${lb_ip}"
  fi

  write_env DNS_ZONE "${dns_zone}"
  write_env DNS_MANUAL "false"
else
  write_env DNS_ZONE "external"
  write_env DNS_MANUAL "true"
  echo "Manual DNS required: create A ${DOMAIN} -> ${lb_ip}" >&2
fi

certificate_status="$(gcloud compute ssl-certificates describe "${SSL_CERTIFICATE}" \
  --project="${PROJECT_ID}" \
  --global \
  --format='value(managed.status)' || true)"
write_env CERT_STATUS "${certificate_status:-UNKNOWN}"

record_result "deployed"
trap - ERR

echo "Cloud Run URL: ${service_url}"
echo "Requested domain: https://${DOMAIN}"
echo "Load-balancer IP: ${lb_ip}"
echo "Managed certificate: ${certificate_status:-UNKNOWN}"
