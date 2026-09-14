"""Synthetic demo web gateway; AgentCore remains the sole model execution host."""

import json
import os
import re
import time
import uuid
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

SCENARIOS = {
    "autonomous": "Run a synthetic autonomous routine reconciliation scenario.",
    "approval": "Run a synthetic approval scenario that requires human review.",
    "exception": "Run a synthetic evidence exception scenario and refuse to guess.",
}
PROMPT_END = (
    " Explain what the agent did, the deterministic outcome and evidence, what the human must "
    "review, and what the agent is prohibited from doing. Be concise. Never approve or pay."
)


def reply(status, body, content_type="application/json"):
    return {
        "statusCode": status,
        "headers": {
            "content-type": content_type,
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
        },
        "body": json.dumps(body) if content_type == "application/json" else body,
    }


def handler(event, context):
    s3 = boto3.client("s3")
    bucket = os.environ["RESULT_BUCKET"]
    if os.environ["MODE"] == "worker":
        job = event["job"]
        scenario = event["scenario"]
        if not re.fullmatch(r"[0-9a-f]{32}", job) or scenario not in SCENARIOS:
            raise ValueError("Invalid synthetic job")
        try:
            client = boto3.client(
                "bedrock-agentcore", config=Config(read_timeout=840, retries={"max_attempts": 0})
            )
            response = client.invoke_agent_runtime(
                agentRuntimeArn=os.environ["RUNTIME_ARN"],
                runtimeSessionId=str(uuid.uuid4()),
                contentType="application/json",
                payload=json.dumps({"prompt": SCENARIOS[scenario] + PROMPT_END}).encode(),
            )
            result = json.loads(response["response"].read())
            if isinstance(result, str):
                result = json.loads(result)
            if result.get("error") or not result.get("response"):
                raise ValueError("Runtime failed")
            result = {"status": "complete", **result}
        except Exception as exc:
            code = (
                exc.response.get("Error", {}).get("Code")
                if isinstance(exc, ClientError)
                else type(exc).__name__
            )
            print(json.dumps({"event": "runtime_invocation_failed", "code": code}))
            if isinstance(exc, ClientError) and code == "AccessDeniedException":
                print(exc.response["Error"].get("Message", ""))
            result = {"status": "failed", "error": "Agent is unavailable. Please try again."}
        s3.put_object(
            Bucket=bucket,
            Key=f"results/{job}.json",
            Body=json.dumps(result).encode(),
            ContentType="application/json",
        )
        return {"status": result["status"]}
    method = event.get("requestContext", {}).get("http", {}).get("method")
    path = event.get("rawPath", "/")
    if method == "GET" and path == "/":
        return reply(200, Path("index.html").read_text(), "text/html; charset=utf-8")
    if method == "GET" and path == "/health":
        return reply(
            200,
            {
                "status": "ok",
                "hosting": "Amazon Bedrock AgentCore",
                "financial_boundary": "No payment initiation or agent approval.",
            },
        )
    if method == "POST" and path == "/api/run":
        raw = event.get("body") or ""
        if event.get("isBase64Encoded") or len(raw) > 100:
            return reply(400, {"error": "Invalid scenario"})
        try:
            scenario = json.loads(raw).get("scenario")
        except (ValueError, AttributeError):
            return reply(400, {"error": "Invalid scenario"})
        if not isinstance(scenario, str) or scenario not in SCENARIOS:
            return reply(400, {"error": "Invalid scenario"})
        # Atomic shared admission limit: at most one synthetic job every two minutes.
        try:
            s3.put_object(
                Bucket=bucket,
                Key=f"results/rate-{int(time.time() // 120)}",
                Body=b"1",
                IfNoneMatch="*",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {
                "PreconditionFailed",
                "ConditionalRequestConflict",
            }:
                return reply(429, {"error": "Demo is busy. Please try again in two minutes."})
            raise
        job = uuid.uuid4().hex
        s3.put_object(
            Bucket=bucket,
            Key=f"results/{job}.json",
            Body=b'{"status":"running"}',
            ContentType="application/json",
        )
        boto3.client("lambda").invoke(
            FunctionName=os.environ["WORKER_NAME"],
            InvocationType="Event",
            Payload=json.dumps({"job": job, "scenario": scenario}).encode(),
        )
        return reply(202, {"job": job})
    if method == "GET" and re.fullmatch(r"/api/result/[0-9a-f]{32}", path):
        try:
            result = s3.get_object(Bucket=bucket, Key=f"results/{path.rsplit('/', 1)[1]}.json")
            return reply(200, json.loads(result["Body"].read()))
        except s3.exceptions.NoSuchKey:
            return reply(404, {"error": "Job not found"})
    return reply(404, {"error": "Not found"})
