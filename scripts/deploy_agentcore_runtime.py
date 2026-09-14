"""Deploy the packaged synthetic Cherry runtime with scoped IAM and account checks."""

import argparse
import hashlib
import json
from pathlib import Path

import boto3

ACCOUNT = "821465445270"
REGION = "eu-west-2"
NAME = "CherryAgentAWS_CherryAgent"
ROLE = "CherryAgentAWS-Runtime"
BUCKET = f"cherry-agentcore-artifacts-{ACCOUNT}-{REGION}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    session = boto3.Session()
    if session.region_name != REGION:
        raise SystemExit("Unexpected configured region")
    if session.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        raise SystemExit("Unexpected AWS account")
    package = args.package.read_bytes()
    digest = hashlib.sha256(package).hexdigest()
    key = f"cherry/{digest}.zip"
    iam = session.client("iam")
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": ACCOUNT},
                    "ArnLike": {
                        "aws:SourceArn": (
                            f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/{NAME}-*"
                        )
                    },
                },
            }
        ],
    }
    try:
        iam.get_role(RoleName=ROLE)
    except iam.exceptions.NoSuchEntityException:
        iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust))
    policy = json.loads(
        (Path(__file__).parents[1] / "infra/aws/agentcore-runtime-policy.json").read_text()
    )
    logs = f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/bedrock-agentcore/runtimes/{NAME}*"
    policy["Statement"].extend(
        [
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:DescribeLogStreams"],
                "Resource": logs,
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": f"{logs}:log-stream:*",
            },
            {
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{BUCKET}/{key}",
            },
        ]
    )
    iam.put_role_policy(
        RoleName=ROLE, PolicyName="CherryRuntime", PolicyDocument=json.dumps(policy)
    )
    s3 = session.client("s3")
    existing = {b["Name"] for b in s3.list_buckets()["Buckets"]}
    if BUCKET not in existing:
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
    s3.put_public_access_block(
        Bucket=BUCKET,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_object(Bucket=BUCKET, Key=key, Body=package, ServerSideEncryption="AES256")
    client = session.client("bedrock-agentcore-control")
    params = {
        "agentRuntimeArtifact": {
            "codeConfiguration": {
                "code": {"s3": {"bucket": BUCKET, "prefix": key}},
                "runtime": "PYTHON_3_13",
                "entryPoint": ["main.py"],
            }
        },
        "roleArn": f"arn:aws:iam::{ACCOUNT}:role/{ROLE}",
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "protocolConfiguration": {"serverProtocol": "HTTP"},
        "environmentVariables": {
            "AWS_REGION": REGION,
            "STRANDS_BEDROCK_MODEL_ID": "eu.anthropic.claude-sonnet-4-6",
            "CHERRY_PERSISTENCE_BACKEND": "memory",
        },
        "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 300, "maxLifetime": 3600},
    }
    matches = [
        r for r in client.list_agent_runtimes()["agentRuntimes"] if r["agentRuntimeName"] == NAME
    ]
    if matches:
        result = client.update_agent_runtime(agentRuntimeId=matches[0]["agentRuntimeId"], **params)
    else:
        result = client.create_agent_runtime(agentRuntimeName=NAME, **params)
    result.pop("ResponseMetadata", None)
    output = Path(__file__).parents[1] / "artifacts/agentcore-deployment.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(output.read_text())


if __name__ == "__main__":
    main()
