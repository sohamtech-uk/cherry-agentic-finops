import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location(
    "cherry_runtime", Path(__file__).parents[1] / "agentcore" / "cherry_agent.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


@pytest.mark.parametrize("payload", [{}, {"prompt": " "}, {"prompt": 123}, None])
def test_invalid_payload(payload):
    with patch.object(runtime, "invoke_cherry_agent") as invoke:
        assert "error" in runtime.agent_invocation(payload)
        invoke.assert_not_called()


def test_runtime_success():
    result = {"response": "Human required", "framework": "Strands Agents SDK"}
    with patch.object(runtime, "invoke_cherry_agent", return_value=result):
        assert runtime.agent_invocation({"prompt": "synthetic"}) == result


def test_runtime_hides_exception():
    with patch.object(runtime, "invoke_cherry_agent", side_effect=RuntimeError("secret")):
        assert runtime.agent_invocation({"prompt": "synthetic"}) == {"error": "agent_unavailable"}
