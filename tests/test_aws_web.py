import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

spec = importlib.util.spec_from_file_location(
    "aws_web", Path(__file__).parents[1] / "infra/aws/web/handler.py"
)
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)


@pytest.fixture(autouse=True)
def configure(monkeypatch):
    monkeypatch.setenv("MODE", "web")
    monkeypatch.setenv("RESULT_BUCKET", "synthetic-test")
    monkeypatch.setenv("WORKER_NAME", "synthetic-worker")


def event(body):
    return {"rawPath": "/api/run", "requestContext": {"http": {"method": "POST"}}, "body": body}


@pytest.mark.parametrize(
    "body", ["{}", "[]", "invalid", '{"scenario":"payment"}', '{"scenario":[]}', "x" * 101]
)
def test_rejects_arbitrary_requests(body):
    with patch.object(web.boto3, "client") as client:
        assert web.handler(event(body), None)["statusCode"] == 400
        client.return_value.put_object.assert_not_called()
        client.return_value.invoke.assert_not_called()


def test_atomic_rate_limit_blocks_submission():
    storage = MagicMock()
    storage.put_object.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailed", "Message": "exists"}}, "PutObject"
    )
    with patch.object(web.boto3, "client", return_value=storage):
        result = web.handler(event('{"scenario":"approval"}'), None)
    assert result["statusCode"] == 429
    storage.invoke.assert_not_called()
    assert storage.put_object.call_args.kwargs["IfNoneMatch"] == "*"


def test_synthetic_submission_has_only_scenario_and_opaque_id():
    storage, worker = MagicMock(), MagicMock()
    with patch.object(web.boto3, "client", side_effect=[storage, worker]):
        result = web.handler(event('{"scenario":"approval"}'), None)
    assert result["statusCode"] == 202
    job = json.loads(result["body"])["job"]
    assert len(job) == 32
    payload = json.loads(worker.invoke.call_args.kwargs["Payload"])
    assert payload == {"scenario": "approval", "job": job}


def test_worker_error_is_sanitized(monkeypatch):
    monkeypatch.setenv("MODE", "worker")
    monkeypatch.setenv("RUNTIME_ARN", "test-runtime")
    storage, runtime = MagicMock(), MagicMock()
    runtime.invoke_agent_runtime.side_effect = RuntimeError("private-secret")
    with patch.object(web.boto3, "client", side_effect=[storage, runtime]):
        web.handler({"job": "a" * 32, "scenario": "approval"}, None)
    result = json.loads(storage.put_object.call_args.kwargs["Body"])
    assert result["status"] == "failed"
    assert "private-secret" not in json.dumps(result)
