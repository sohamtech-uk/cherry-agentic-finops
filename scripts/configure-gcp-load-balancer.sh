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
RESULT_FILE="${RESULT_FILE:-/tmp/cherry-agent-finops-load-balancer.json}"

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
    "load_balancer_ip": os.environ.get("LB_IP", ""),
    "load_balancer_health_status": os.environ.get("LB_HEALTH_STATUS", ""),
    "load_balancer_health_body": os.environ.get("LB_HEALTH_BODY", ""),
    "dns_zone": os.environ.get("DNS_ZONE", ""),
    "manual_dns_required": os.environ.get("DNS_MANUAL", "unknown"),
    "manual_dns_record": os.environ.get("MANUAL_DNS_RECORD", ""),
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
  --region="${REGION}" \
  --format=json > /tmp/cherry-agent-service.json

ready="$(jq -r '[.status.conditions[]? | select(.type == "Ready")][0].status // "False"' /tmp/cherry-agent-service.json)"
if [[ "${ready}" != "True" ]]; then
  echo "Cloud Run service ${SERVICE_NAME} is not Ready." >&2
  jq '.status.conditions' /tmp/cherry-agent-service.json >&2
  exit 1
fi

service_url="$(jq -r '.status.url // empty' /tmp/cherry-agent-service.json)"
write_env SERVICE_URL "${service_url}"

# A serverless NEG reaches Cloud Run through Google's load-balancing integration;
# it does not rely on the public run.app route that is returning a platform 404
# in this project. Configure the proven existing Cherry Money HTTPS load balancer
# first, then validate the application through the load-balancer IP and Host.
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
    --timeout=30 \
    --enable-logging \
    --logging-sample-rate=1
else
  gcloud compute backend-services update "${BACKEND_SERVICE}" \
    --project="${PROJECT_ID}" \
    --global \
    --enable-logging \
    --logging-sample-rate=1 >/dev/null
fi

backend_groups="$(gcloud compute backend-services describe "${BACKEND_SERVICE}" \
  --project="${PROJECT_ID}" \
  --global \
  --format='value(backends.group)')"
if ! grep -q "${SERVERLESS_NEG}" <<<"${backend_groups}"; then
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

# Validate the live URL map after mutation so a bad route cannot silently ship.
gcloud compute url-maps export "${URL_MAP_NAME}" \
  --project="${PROJECT_ID}" \
  --global \
  --destination=/tmp/cherry-agent-url-map.yaml >/dev/null
gcloud compute url-maps validate \
  --project="${PROJECT_ID}" \
  --global \
  --load-balancing-scheme=EXTERNAL_MANAGED \
  --source=/tmp/cherry-agent-url-map.yaml >/dev/null

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

# Test through the new host rule before DNS or the new certificate has
# propagated. -k is intentional only for this one pre-certificate validation;
# --resolve forces the real load-balancer IP while preserving the Host/SNI name.
lb_health_status=""
for attempt in $(seq 1 30); do
  lb_health_status="$(curl --silent --show-error \
    --insecure \
    --resolve "${DOMAIN}:443:${lb_ip}" \
    --output /tmp/cherry-agent-lb-health.json \
    --write-out '%{http_code}' \
    --connect-timeout 10 \
    --max-time 30 \
    "https://${DOMAIN}/healthz" || true)"
  if [[ "${lb_health_status}" == "200" ]]; then
    break
  fi
  echo "Load-balancer health attempt ${attempt} returned ${lb_health_status:-no-response}."
  sleep 10
done
write_env LB_HEALTH_STATUS "${lb_health_status:-no-response}"

lb_health_body=""
if [[ -f /tmp/cherry-agent-lb-health.json ]]; then
  lb_health_body="$(tr '\n' ' ' < /tmp/cherry-agent-lb-health.json | head -c 1000)"
  cat /tmp/cherry-agent-lb-health.json
fi
write_env LB_HEALTH_BODY "${lb_health_body}"

if [[ "${lb_health_status}" != "200" ]]; then
  echo "The load balancer did not reach Cherry Agent successfully." >&2
  exit 1
fi

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
  write_env MANUAL_DNS_RECORD ""
else
  write_env DNS_ZONE "external"
  write_env DNS_MANUAL "true"
  write_env MANUAL_DNS_RECORD "A ${DOMAIN} ${lb_ip} TTL 300"
  echo "Manual DNS required: create A ${DOMAIN} -> ${lb_ip} (TTL 300)." >&2
fi

certificate_status="$(gcloud compute ssl-certificates describe "${SSL_CERTIFICATE}" \
  --project="${PROJECT_ID}" \
  --global \
  --format='value(managed.status)' || true)"
write_env CERT_STATUS "${certificate_status:-UNKNOWN}"

status="load_balancer_verified"
if [[ "${DNS_MANUAL}" == "true" ]]; then
  status="awaiting_manual_dns"
elif [[ "${certificate_status}" == "ACTIVE" ]]; then
  status="live"
fi

record_result "${status}"
trap - ERR

echo "Cherry Agent responded through the HTTPS load balancer."
echo "Load-balancer IP: ${lb_ip}"
echo "Requested domain: https://${DOMAIN}"
echo "DNS manual: ${DNS_MANUAL}"
echo "Certificate status: ${certificate_status:-UNKNOWN}"
