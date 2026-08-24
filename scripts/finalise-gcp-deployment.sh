#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${REGION:-europe-west2}"
DOMAIN="${DOMAIN:-finops.cherrymoney.co.uk}"
SERVICE_NAME="${SERVICE_NAME:-cherry-agent-finops}"
LOAD_BALANCER_ADDRESS="${LOAD_BALANCER_ADDRESS:-cherrybank-lb-ip}"
URL_MAP_NAME="${URL_MAP_NAME:-cherrybank-https-map}"
TARGET_HTTPS_PROXY_NAME="${TARGET_HTTPS_PROXY_NAME:-cherrybank-https-proxy}"
SERVERLESS_NEG="${SERVERLESS_NEG:-cherry-agent-finops-neg}"
BACKEND_SERVICE="${BACKEND_SERVICE:-cherry-agent-finops-backend}"
PATH_MATCHER_NAME="${PATH_MATCHER_NAME:-finops}"
SSL_CERTIFICATE="${SSL_CERTIFICATE:-cherry-agent-finops-cert}"
RESULT_FILE="${RESULT_FILE:-/tmp/cherry-agent-finops-finalisation.json}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID or GOOGLE_CLOUD_PROJECT is required." >&2
  exit 2
fi

for command in gcloud jq curl python; do
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
    "health_url": os.environ.get("HEALTH_URL", ""),
    "load_balancer_ip": os.environ.get("LB_IP", ""),
    "dns_zone": os.environ.get("DNS_ZONE", ""),
    "manual_dns_required": os.environ.get("DNS_MANUAL", "unknown"),
    "certificate_status": os.environ.get("CERT_STATUS", ""),
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

gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" >/dev/null

# Cloud Run's preferred public-access control is disabling the invoker IAM
# check. This avoids an allUsers IAM binding, which can be blocked by domain-
# restricted-sharing policies. Fall back to the legacy invoker binding when
# the installed gcloud version does not expose the newer flag.
if gcloud run services update --help 2>/dev/null | grep -q -- '--no-invoker-iam-check'; then
  gcloud run services update "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --no-invoker-iam-check \
    --ingress=all \
    --quiet
else
  if ! gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --member=allUsers \
    --role=roles/run.invoker \
    --quiet; then
    gcloud beta run services add-iam-policy-binding "${SERVICE_NAME}" \
      --project="${PROJECT_ID}" \
      --region="${REGION}" \
      --member=allUsers \
      --role=roles/run.invoker \
      --quiet
  fi
fi

service_url="$(gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format='value(status.url)')"
project_number="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
canonical_url="https://${SERVICE_NAME}-${project_number}.${REGION}.run.app"
write_env SERVICE_URL "${service_url}"

health_ok=false
health_url=""
for attempt in $(seq 1 24); do
  for candidate in "${service_url}/health" "${canonical_url}/health"; do
    http_code="$(curl --silent --show-error \
      --output /tmp/cherry-agent-health.json \
      --write-out '%{http_code}' \
      --connect-timeout 10 \
      --max-time 30 \
      "${candidate}" || true)"
    if [[ "${http_code}" == "200" ]]; then
      health_ok=true
      health_url="${candidate}"
      break 2
    fi
    echo "Health check attempt ${attempt}: ${candidate} returned ${http_code:-no-response}."
  done
  sleep 5
done

if [[ "${health_ok}" != "true" ]]; then
  echo "Cloud Run became ready but did not expose /health publicly." >&2
  if [[ -f /tmp/cherry-agent-health.json ]]; then
    cat /tmp/cherry-agent-health.json >&2 || true
  fi
  exit 1
fi
write_env HEALTH_URL "${health_url}"
cat /tmp/cherry-agent-health.json

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

if ! jq -e --arg matcher "${PATH_MATCHER_NAME}" \
  '.pathMatchers[]? | select(.name == $matcher)' \
  <<<"${url_map_json}" >/dev/null; then
  gcloud compute url-maps add-path-matcher "${URL_MAP_NAME}" \
    --project="${PROJECT_ID}" \
    --global \
    --path-matcher-name="${PATH_MATCHER_NAME}" \
    --default-service="${BACKEND_SERVICE}"
fi

url_map_json="$(gcloud compute url-maps describe "${URL_MAP_NAME}" \
  --project="${PROJECT_ID}" \
  --global \
  --format=json)"
if ! jq -e --arg domain "${DOMAIN}" \
  '[.hostRules[]?.hosts[]?] | index($domain) != null' \
  <<<"${url_map_json}" >/dev/null; then
  gcloud compute url-maps add-host-rule "${URL_MAP_NAME}" \
    --project="${PROJECT_ID}" \
    --global \
    --hosts="${DOMAIN}" \
    --path-matcher-name="${PATH_MATCHER_NAME}"
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
  echo "Manual DNS required: create an A record for ${DOMAIN} pointing to ${lb_ip}." >&2
fi

certificate_status="$(gcloud compute ssl-certificates describe "${SSL_CERTIFICATE}" \
  --project="${PROJECT_ID}" \
  --global \
  --format='value(managed.status)' || true)"

if [[ "${DNS_MANUAL}" == "false" ]]; then
  for _ in $(seq 1 20); do
    if [[ "${certificate_status}" == "ACTIVE" ]]; then
      break
    fi
    sleep 30
    certificate_status="$(gcloud compute ssl-certificates describe "${SSL_CERTIFICATE}" \
      --project="${PROJECT_ID}" \
      --global \
      --format='value(managed.status)' || true)"
  done
fi
write_env CERT_STATUS "${certificate_status:-UNKNOWN}"

status="configured"
if [[ "${DNS_MANUAL}" == "false" && "${certificate_status}" == "ACTIVE" ]]; then
  if curl --fail --silent --show-error \
    --retry 8 \
    --retry-delay 10 \
    --retry-all-errors \
    "https://${DOMAIN}/health" >/tmp/cherry-agent-domain-health.json; then
    status="live"
    cat /tmp/cherry-agent-domain-health.json
  fi
elif [[ "${DNS_MANUAL}" == "true" ]]; then
  status="awaiting_manual_dns"
fi

record_result "${status}"
trap - ERR

echo "Cloud Run health URL: ${health_url}"
echo "Requested domain: https://${DOMAIN}"
echo "Load-balancer IP: ${lb_ip}"
echo "DNS zone: ${DNS_ZONE}"
echo "Manual DNS required: ${DNS_MANUAL}"
echo "Managed certificate: ${certificate_status:-UNKNOWN}"
