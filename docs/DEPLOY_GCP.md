# Deploy Cherry Agent to Google Cloud

Target hostname: **`finops.cherrymoney.co.uk`**

## What is needed

- the selected Google account must have a Google Cloud project with billing enabled;
- the account must be able to create service accounts, enable APIs and deploy Cloud Run;
- `cherrymoney.co.uk` must be verified in Google Search Console for custom-domain mapping;
- the domain's **DNS control panel** must be accessible.

FTP access is not used by Cloud Run and cannot create the required CNAME/A/AAAA records. Never
commit an FTP password, service-account key or API key. Runtime credentials belong in protected
GitHub environment secrets only.

## First deployment from Cloud Shell

1. Sign into Google Cloud using the chosen account.
2. Select or create a project and note its immutable **project ID**.
3. Open Cloud Shell and run:

```bash
git clone https://github.com/sohamtech-uk/cherry-agentic-finops.git
cd cherry-agentic-finops
bash scripts/deploy-cloudshell.sh YOUR_PROJECT_ID
```

The script:

- enables Cloud Run, Cloud Build, Artifact Registry, Vertex AI, Firestore, Storage and Pub/Sub;
- creates a dedicated `cherry-agent-runtime` service account;
- creates a versioned evidence bucket and workflow topic;
- creates the default Firestore Native database when needed;
- builds and pushes the container;
- deploys a public Cloud Run service in `europe-west1`;
- verifies `/health`;
- creates the domain mapping when `cherrymoney.co.uk` is already verified;
- prints the exact DNS records to add.

## Verify the domain

If the script says the domain is not verified:

```bash
gcloud domains verify cherrymoney.co.uk
```

Complete the Search Console instructions using the DNS provider. Then run:

```bash
gcloud beta run domain-mappings create \
  --service=cherry-agent \
  --domain=finops.cherrymoney.co.uk \
  --region=europe-west1

gcloud beta run domain-mappings describe \
  --domain=finops.cherrymoney.co.uk \
  --region=europe-west1
```

Add every record under `resourceRecords` to the domain's DNS control panel. Managed TLS normally
appears within minutes, but can take up to 24 hours.

## Continuous deployment

After the first deployment, configure GitHub repository environment variables:

- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`

The workflow `.github/workflows/deploy.yml` uses short-lived Workload Identity Federation tokens.
It intentionally avoids long-lived service-account JSON keys.

The production environment must also contain the `GOOGLE_API_KEY` and `NEATLOGS_API_KEY` secrets.
The workflow deploys
the same restricted-IAM runtime configuration as `scripts/deploy-gcplab.sh`:

- `GOOGLE_GENAI_USE_VERTEXAI=false`;
- `GOOGLE_API_KEY` is passed to Cloud Run without being printed;
- `NEATLOGS_API_KEY` enables judge-visible agent traces in the Neatlogs workspace;
- `CHERRY_PERSISTENCE_BACKEND=firestore`;
- Fund Manager case state is stored in `fund_manager_cases`, with uploaded evidence split into
  integrity-checked Firestore chunks so the workflow survives Cloud Run instance changes;
- no custom runtime service account, bucket or Pub/Sub dependency is required.

`GOOGLE_API_KEY` authenticates Gemini requests only. It cannot authenticate a GitHub runner to
Artifact Registry or Cloud Run. The three `GCP_*` variables must describe an identity that can
access the same project named by `GCP_PROJECT_ID`. If the project is
`priv-mkt-hack26lon-3730`, a provider and deployment service account from another project do not
automatically grant access to it. The workflow now checks this explicitly before building.

Temporary `gcplab.me` accounts may block the IAM policy changes needed to create Workload Identity
Federation. In that case, automated GitHub deployment cannot be enabled with an API key alone;
continue using the authenticated Cloud Shell deployment:

```bash
git pull origin main
if [ -z "${GOOGLE_API_KEY:-}" ]; then
  read -rsp "Gemini API key: " GOOGLE_API_KEY; echo
  export GOOGLE_API_KEY
fi
bash scripts/deploy-gcplab.sh priv-mkt-hack26lon-3730 europe-west1
```

## Post-deployment checks

```bash
bash scripts/check-deployment.sh https://finops.cherrymoney.co.uk
```

Also verify:

- `/api/docs` loads;
- the autonomous scenario reconciles;
- the approval scenario pauses and resumes;
- the exception scenario stops safely;
- an evidence ZIP downloads;
- Firestore contains workflow documents;
- Cloud Storage contains evidence after downloading a pack;
- Cloud Logging shows application requests without secrets.

## Production hardening after the hackathon

Direct Cloud Run domain mapping is a preview feature. Move the public front door to a global
external Application Load Balancer when the prototype becomes a production service. Add user
authentication, organisation tenancy, encrypted application-level sensitive fields, retention
policies, Cloud Armor, rate limiting, formal accounting controls and penetration testing before
processing live client books.
