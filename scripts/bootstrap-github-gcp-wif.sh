#!/usr/bin/env bash
set -Eeuo pipefail

# One-time bootstrap for GitHub Actions -> Google Cloud Workload Identity Federation.
# Run from Google Cloud Shell while authenticated to the target project.
#
# Usage:
#   bash scripts/bootstrap-github-gcp-wif.sh YOUR_PROJECT_ID
#
# Optional:
#   DEPLOY_NOW=true bash scripts/bootstrap-github-gcp-wif.sh YOUR_PROJECT_ID
#
# If the GitHub CLI is authenticated, this script also writes the required
# production Environment variables/secrets into sohamtech-uk/cherry-agentic-finops.

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REPO="${GITHUB_REPOSITORY:-sohamtech-uk/cherry-agentic-finops}"
GITHUB_ENVIRONMENT="${GITHUB_ENVIRONMENT:-production}"
POOL_ID="${WIF_POOL_ID:-github-actions-pool}"
PROVIDER_ID="${WIF_PROVIDER_ID:-github-actions-provider}"
DEPLOY_SA_NAME="${GCP_DEPLOY_SA_NAME:-github-actions-deployer}"
RUNTIME_SA_NAME="${GCP_RUNTIME_SA_NAME:-cherry-agent-runtime}"
DEPLOY_NOW="${DEPLOY_NOW:-false}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Usage: $0 GOOGLE_CLOUD_PROJECT_ID" >&2
  exit 2
fi

for command in gcloud python3; do
  command -v "${command}" >/dev/null || {
    echo "Required command is unavailable: ${command}" >&2
    exit 2
  }
done

gcloud config set project "${PROJECT_ID}" >/dev/null
if [[ "$(gcloud projects describe "${PROJECT_ID}" --format='value(projectId)' 2>/dev/null || true)" != "${PROJECT_ID}" ]]; then
  echo "Project ${PROJECT_ID} does not exist or this account cannot access it." >&2
  exit 1
fi

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
DEPLOY_EMAIL="${DEPLOY_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_EMAIL="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
PROVIDER_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"

printf 'Project: %s\nRepository: %s\n' "${PROJECT_ID}" "${REPO}"

gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  serviceusage.googleapis.com \
  --project="${PROJECT_ID}" \
  --quiet

if ! gcloud iam service-accounts describe "${DEPLOY_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${DEPLOY_SA_NAME}" \
    --project="${PROJECT_ID}" \
    --display-name="GitHub Actions deployer for Cherry FundOps"
fi

# Project-scoped permissions used by .github/workflows/deploy.yml.
for role in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOY_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet >/dev/null
done

# The deployer must be allowed to attach the existing Cloud Run runtime SA.
if gcloud iam service-accounts describe "${RUNTIME_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_EMAIL}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOY_EMAIL}" \
    --role="roles/iam.serviceAccountUser" \
    --quiet >/dev/null
else
  echo "WARNING: runtime service account ${RUNTIME_EMAIL} does not exist yet." >&2
  echo "Run scripts/deploy-cloudshell.sh once or create that runtime service account before GitHub deployment." >&2
fi

if ! gcloud iam workload-identity-pools describe "${POOL_ID}" \
  --project="${PROJECT_ID}" --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "${POOL_ID}" \
    --project="${PROJECT_ID}" \
    --location=global \
    --display-name="GitHub Actions"
fi

if ! gcloud iam workload-identity-pools providers describe "${PROVIDER_ID}" \
  --project="${PROJECT_ID}" \
  --location=global \
  --workload-identity-pool="${POOL_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
    --project="${PROJECT_ID}" \
    --location=global \
    --workload-identity-pool="${POOL_ID}" \
    --display-name="GitHub Cherry FundOps" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.actor=assertion.actor" \
    --attribute-condition="assertion.repository=='${REPO}'"
fi

WIF_MEMBER="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${REPO}"
gcloud iam service-accounts add-iam-policy-binding "${DEPLOY_EMAIL}" \
  --project="${PROJECT_ID}" \
  --member="${WIF_MEMBER}" \
  --role="roles/iam.workloadIdentityUser" \
  --quiet >/dev/null

UPLOAD_TOKEN="${CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN:-$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)}"

cat <<VALUES

Created / verified Google Cloud deployment identity.

GitHub production Environment variables:
GCP_PROJECT_ID=${PROJECT_ID}
GCP_WORKLOAD_IDENTITY_PROVIDER=${PROVIDER_RESOURCE}
GCP_DEPLOY_SERVICE_ACCOUNT=${DEPLOY_EMAIL}

GitHub production Environment secret:
CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN=${UPLOAD_TOKEN}
VALUES

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "Configuring GitHub Environment ${GITHUB_ENVIRONMENT}..."
  gh variable set GCP_PROJECT_ID --repo "${REPO}" --env "${GITHUB_ENVIRONMENT}" --body "${PROJECT_ID}"
  gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "${REPO}" --env "${GITHUB_ENVIRONMENT}" --body "${PROVIDER_RESOURCE}"
  gh variable set GCP_DEPLOY_SERVICE_ACCOUNT --repo "${REPO}" --env "${GITHUB_ENVIRONMENT}" --body "${DEPLOY_EMAIL}"
  gh secret set CHERRY_PRIVATE_MARKETS_UPLOAD_TOKEN --repo "${REPO}" --env "${GITHUB_ENVIRONMENT}" --body "${UPLOAD_TOKEN}"
  echo "GitHub Environment variables and upload secret configured."

  if [[ "${DEPLOY_NOW}" == "true" ]]; then
    gh workflow run deploy.yml --repo "${REPO}" --ref main
    echo "Deploy to Cloud Run workflow triggered."
  else
    echo "To deploy now: gh workflow run deploy.yml --repo ${REPO} --ref main"
  fi
else
  cat <<MANUAL

GitHub CLI is not authenticated, so the values were not written to GitHub automatically.
Add the values printed above under:
Settings -> Environments -> ${GITHUB_ENVIRONMENT}
MANUAL
fi
