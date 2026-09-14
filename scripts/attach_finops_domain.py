"""Attach the DNS-validated finops certificate to the existing AWS demo distribution."""

import json
from pathlib import Path

import boto3

ACCOUNT = "821465445270"
DOMAIN = "finops.cherrymoney.co.uk"
ROOT = Path(__file__).parents[1]


def main():
    session = boto3.Session()
    if session.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        raise SystemExit("Unexpected AWS account")
    certificate = json.loads((ROOT / "artifacts/finops-certificate.json").read_text())[
        "CertificateArn"
    ]
    if not certificate.startswith(f"arn:aws:acm:us-east-1:{ACCOUNT}:certificate/"):
        raise SystemExit("Unexpected certificate target")
    cert = session.client("acm", region_name="us-east-1").describe_certificate(
        CertificateArn=certificate
    )["Certificate"]
    if cert["Status"] != "ISSUED" or DOMAIN not in cert["SubjectAlternativeNames"]:
        raise SystemExit("Certificate is not yet issued for finops")
    distribution = json.loads((ROOT / "artifacts/finops-web.json").read_text())
    cf = session.client("cloudfront")
    response = cf.get_distribution_config(Id=distribution["id"])
    config = response["DistributionConfig"]
    if config["Comment"] != "Cherry Agent AWS synthetic demo":
        raise SystemExit("Unexpected distribution target")
    aliases = config.get("Aliases", {}).get("Items", [])
    if DOMAIN not in aliases:
        aliases.append(DOMAIN)
    config["Aliases"] = {"Quantity": len(aliases), "Items": aliases}
    config["ViewerCertificate"] = {
        "ACMCertificateArn": certificate,
        "SSLSupportMethod": "sni-only",
        "MinimumProtocolVersion": "TLSv1.2_2021",
    }
    result = cf.update_distribution(
        Id=distribution["id"], IfMatch=response["ETag"], DistributionConfig=config
    )["Distribution"]
    print(json.dumps({"id": result["Id"], "status": result["Status"], "domain": DOMAIN}))


if __name__ == "__main__":
    main()
