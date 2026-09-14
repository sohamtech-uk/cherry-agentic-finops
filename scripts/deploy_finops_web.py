"""Deploy a CloudFront web demo backed by IAM-only Lambda and AgentCore."""

import contextlib
import io
import json
import zipfile
from pathlib import Path

import boto3

ACCOUNT = "821465445270"
REGION = "eu-west-2"
BUCKET = f"cherry-agentcore-demo-{ACCOUNT}-{REGION}"
ROOT = Path(__file__).parents[1]


def main():
    session = boto3.Session()
    if session.region_name != REGION:
        raise SystemExit("Unexpected configured region")
    if session.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        raise SystemExit("Unexpected AWS account")
    runtime = json.loads((ROOT / "artifacts/agentcore-deployment.json").read_text())[
        "agentRuntimeArn"
    ]
    if not runtime.startswith(f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/"):
        raise SystemExit("Unexpected runtime target")
    iam, s3, lam = [session.client(x) for x in ["iam", "s3", "lambda"]]
    if BUCKET not in {x["Name"] for x in s3.list_buckets()["Buckets"]}:
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
    s3.put_bucket_lifecycle_configuration(
        Bucket=BUCKET,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "ExpireSyntheticResults",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "results/"},
                    "Expiration": {"Days": 1},
                }
            ]
        },
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ["handler.py", "index.html"]:
            z.write(ROOT / "infra/aws/web" / name, name)
    for mode, name in [
        ("worker", "CherryFinopsWorker"),
        ("web", "CherryFinopsWeb"),
    ]:
        role = f"{name}-Role"
        trust = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
        try:
            iam.get_role(RoleName=role)
        except iam.exceptions.NoSuchEntityException:
            iam.create_role(RoleName=role, AssumeRolePolicyDocument=json.dumps(trust))
        statements = [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": f"arn:aws:s3:::{BUCKET}/results/*",
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{name}:*",
            },
        ]
        statements.append(
            {
                "Effect": "Allow",
                "Action": "bedrock-agentcore:InvokeAgentRuntime"
                if mode == "worker"
                else "lambda:InvokeFunction",
                "Resource": [runtime, runtime + "/runtime-endpoint/DEFAULT"]
                if mode == "worker"
                else f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:CherryFinopsWorker",
            }
        )
        iam.put_role_policy(
            RoleName=role,
            PolicyName="ScopedDemo",
            PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": statements}),
        )
        env = {
            "MODE": mode,
            "RESULT_BUCKET": BUCKET,
            "RUNTIME_ARN": runtime,
            "WORKER_NAME": "CherryFinopsWorker",
        }
        config = {
            "FunctionName": name,
            "Role": f"arn:aws:iam::{ACCOUNT}:role/{role}",
            "Runtime": "python3.13",
            "Handler": "handler.handler",
            "Timeout": 900 if mode == "worker" else 30,
            "MemorySize": 256,
            "Environment": {"Variables": env},
        }
        try:
            lam.get_function(FunctionName=name)
        except lam.exceptions.ResourceNotFoundException:
            # IAM propagation is handled by rerunning this idempotent script if necessary.
            lam.create_function(**config, Code={"ZipFile": buf.getvalue()})
        else:
            lam.update_function_code(FunctionName=name, ZipFile=buf.getvalue())
            lam.get_waiter("function_updated_v2").wait(FunctionName=name)
            lam.update_function_configuration(**config)
        lam.get_waiter("function_active_v2").wait(FunctionName=name)
        if mode == "worker":
            lam.put_function_event_invoke_config(
                FunctionName=name, MaximumRetryAttempts=0, MaximumEventAgeInSeconds=900
            )
    try:
        url = lam.get_function_url_config(FunctionName="CherryFinopsWeb")["FunctionUrl"]
    except lam.exceptions.ResourceNotFoundException:
        url = lam.create_function_url_config(FunctionName="CherryFinopsWeb", AuthType="AWS_IAM")[
            "FunctionUrl"
        ]
    cf = session.client("cloudfront")
    existing = cf.list_distributions().get("DistributionList", {}).get("Items", [])
    matches = [d for d in existing if d.get("Comment") == "Cherry Agent AWS synthetic demo"]
    if matches:
        dist = matches[0]
    else:
        controls = (
            cf.list_origin_access_controls().get("OriginAccessControlList", {}).get("Items", [])
        )
        oacs = [x for x in controls if x["Name"] == "CherryFinopsLambda"]
        oac = (
            oacs[0]["Id"]
            if oacs
            else cf.create_origin_access_control(
                OriginAccessControlConfig={
                    "Name": "CherryFinopsLambda",
                    "SigningProtocol": "sigv4",
                    "SigningBehavior": "always",
                    "OriginAccessControlOriginType": "lambda",
                }
            )["OriginAccessControl"]["Id"]
        )
        dist = cf.create_distribution(
            DistributionConfig={
                "CallerReference": "CherryFinops20260914",
                "Comment": "Cherry Agent AWS synthetic demo",
                "Enabled": True,
                "PriceClass": "PriceClass_100",
                "HttpVersion": "http2",
                "IsIPV6Enabled": True,
                "Origins": {
                    "Quantity": 1,
                    "Items": [
                        {
                            "Id": "web",
                            "DomainName": url.split("/")[2],
                            "OriginAccessControlId": oac,
                            "CustomOriginConfig": {
                                "HTTPPort": 80,
                                "HTTPSPort": 443,
                                "OriginProtocolPolicy": "https-only",
                                "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                            },
                        }
                    ],
                },
                "DefaultCacheBehavior": {
                    "TargetOriginId": "web",
                    "ViewerProtocolPolicy": "redirect-to-https",
                    "AllowedMethods": {
                        "Quantity": 7,
                        "Items": ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"],
                        "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
                    },
                    "Compress": True,
                    "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
                    "OriginRequestPolicyId": "b689b0a8-53d0-40ab-baf2-68738e2966ac",
                },
                "ViewerCertificate": {"CloudFrontDefaultCertificate": True},
            }
        )["Distribution"]
    arn = dist["ARN"]
    for sid, action in [
        ("CloudFrontURL", "lambda:InvokeFunctionUrl"),
        ("CloudFrontInvoke", "lambda:InvokeFunction"),
    ]:
        with contextlib.suppress(lam.exceptions.ResourceConflictException):
            lam.add_permission(
                FunctionName="CherryFinopsWeb",
                StatementId=sid,
                Action=action,
                Principal="cloudfront.amazonaws.com",
                SourceArn=arn,
            )
    result = {"id": dist["Id"], "domain": dist["DomainName"], "arn": arn}
    (ROOT / "artifacts/finops-web.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
