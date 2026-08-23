# Google Cloud Terraform

This stack creates the Cherry Agent runtime resources:

- Cloud Run v2 service
- dedicated runtime service account and least-privilege roles
- Artifact Registry repository
- versioned Cloud Storage evidence bucket
- Pub/Sub workflow-event topic
- optional Firestore Native default database
- optional direct Cloud Run domain mapping for `finops.cherrymoney.co.uk`

The container image must exist before `terraform apply`. For the first deployment, the Cloud Shell
script in `scripts/deploy-cloudshell.sh` is simpler because it builds the image and deploys in one
flow.

```bash
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
```

Set `enable_domain_mapping=true` only after `cherrymoney.co.uk` is verified by the Google account
performing the deployment. Direct Cloud Run domain mapping is a preview feature; a global external
Application Load Balancer is the recommended future production front door.
