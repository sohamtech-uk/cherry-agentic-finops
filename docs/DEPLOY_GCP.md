# Deploy Cherry Agent to Google Cloud

Target hostname: **`finops.cherrymoney.co.uk`**

## What is needed

- the selected Google account must have a Google Cloud project with billing enabled;
- the account must be able to create service accounts, enable APIs and deploy Cloud Run;
- `cherrymoney.co.uk` must be verified in Google Search Console for custom-domain mapping;
- the domain's **DNS control panel** must be accessible.

FTP access is not used by Cloud Run and cannot create the required CNAME/A/AAAA records. Do not put
an FTP password, service-account key or API key in GitHub.

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
