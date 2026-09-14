"""Explicit live smoke test using synthetic data only; never run in CI."""

import json
import subprocess
from pathlib import Path

from botocore.exceptions import ClientError

from agents.cherry_strands import invoke_cherry_agent
from agents.cherry_strands.agent import agent_metadata


def main() -> None:
    subprocess.run([str(Path(__file__).with_name("verify_aws_target.sh"))], check=True)
    print(json.dumps(agent_metadata(), indent=2))
    result = invoke_cherry_agent(
        "Run a synthetic approval scenario and explain: what the agent did, which deterministic "
        "control stopped the workflow, what the human must review, and what the agent is "
        "prohibited from doing. Be concise."
    )
    if "error" in result:
        raise SystemExit(result["error"])
    print(result["response"])


if __name__ == "__main__":
    try:
        main()
    except ClientError as exc:
        error = exc.response.get("Error", {})
        raise SystemExit(f"Bedrock {error.get('Code')}: {error.get('Message')}") from None
