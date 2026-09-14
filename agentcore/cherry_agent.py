from __future__ import annotations

from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agents.cherry_strands import invoke_cherry_agent

app = BedrockAgentCoreApp()


@app.entrypoint
def agent_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    """Amazon Bedrock AgentCore Runtime entrypoint for Cherry Agent."""

    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": "prompt_required"}
    return invoke_cherry_agent(prompt)


if __name__ == "__main__":
    app.run()
