import importlib.util
from pathlib import Path

from botocore.exceptions import ClientError

spec = importlib.util.spec_from_file_location(
    "smoke", Path(__file__).parents[1] / "scripts" / "test_strands_bedrock.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
failure_message = smoke.failure_message


def test_wrapped_aws_error_preserves_action_and_resource():
    original = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "Denied bedrock:InvokeModel on arn:test",
            }
        },
        "ConverseStream",
    )
    wrapper = RuntimeError("internal trace secret")
    wrapper.__cause__ = original
    assert failure_message(wrapper) == (
        "Bedrock AccessDeniedException: Denied bedrock:InvokeModel on arn:test"
    )


def test_unknown_exception_is_sanitized():
    assert "secret" not in failure_message(RuntimeError("secret"))
