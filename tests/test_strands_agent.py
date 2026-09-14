from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents.cherry_strands import agent
from app.models import WorkflowRecord


def test_invalid_scenario():
    with patch.object(agent, "run_finance_scenario") as run:
        assert agent.run_sme_finance_scenario("payment")["error"] == "invalid_scenario"
        run.assert_not_called()


def test_autonomous_uses_deterministic_workflow():
    with patch.object(agent, "run_finance_scenario", wraps=agent.run_finance_scenario) as run:
        result = agent.run_sme_finance_scenario("autonomous")
        run.assert_called_once_with("autonomous")
    assert WorkflowRecord.model_validate(result).status == "reconciled"


@pytest.mark.parametrize("prompt", ["", "   ", None])
def test_empty_prompt(prompt):
    with patch.object(agent, "build_cherry_agent") as build:
        assert agent.invoke_cherry_agent(prompt) == {"error": "prompt_required"}
        build.assert_not_called()


def test_large_prompt():
    with patch.object(agent, "build_cherry_agent") as build:
        assert agent.invoke_cherry_agent("x" * 8001) == {"error": "prompt_too_large"}
        build.assert_not_called()


def test_metadata_and_request_isolation(monkeypatch):
    monkeypatch.setenv("STRANDS_BEDROCK_MODEL_ID", "test-model")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    instances = [MagicMock(), MagicMock()]
    for instance in instances:
        instance.return_value = SimpleNamespace(message={"content": [{"text": "Human required"}]})
    with patch.object(agent, "build_cherry_agent", side_effect=instances) as build:
        result = agent.invoke_cherry_agent("  synthetic approval  ")
        agent.invoke_cherry_agent("second user")
        assert build.call_count == 2
    instances[0].assert_called_once_with("synthetic approval")
    instances[1].assert_called_once_with("second user")
    assert result == {
        "response": "Human required",
        "framework": "Strands Agents SDK",
        "model_provider": "Amazon Bedrock",
        "model_id": "test-model",
        "aws_region": "eu-west-1",
        "financial_boundary": agent.FINANCIAL_BOUNDARY,
    }


def test_configurable_model_and_region(monkeypatch):
    monkeypatch.setenv("STRANDS_BEDROCK_MODEL_ID", "custom-model")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    with patch.object(agent, "BedrockModel") as model:
        agent._model()
    model.assert_called_once_with(model_id="custom-model", region_name="eu-west-1", temperature=0.1)


def test_human_actions_are_not_tools():
    with patch.object(agent, "BedrockModel"), patch.object(agent, "Agent") as factory:
        agent.build_cherry_agent()
    calls = factory.call_args_list
    assert len(calls) == 4
    assert calls[0].kwargs["tools"] == [
        agent.run_sme_finance_scenario,
        agent.inspect_finance_workflow,
    ]
    assert calls[1].kwargs["tools"] == [agent.inspect_finance_workflow]
    assert calls[2].kwargs["tools"] == [
        agent.inspect_finance_workflow,
        agent.get_open_finance_exceptions,
    ]
    assert len(calls[3].kwargs["tools"]) == 3
    assert not hasattr(agent, "record_human_approval")
    assert not hasattr(agent, "reject_workflow")


def test_real_sdk_hierarchy_builds_without_network():
    # Exercise the installed SDK's constructor/as_tool contract; inference remains mocked.
    with patch.object(agent, "BedrockModel", return_value=MagicMock()):
        hierarchy = agent.build_cherry_agent()
    assert set(hierarchy.tool_names) == {
        "workflow_specialist",
        "control_specialist",
        "evidence_specialist",
    }
