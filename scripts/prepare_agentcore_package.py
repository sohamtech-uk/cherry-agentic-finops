"""Copy only repository application assets into an existing AgentCore CLI project."""

import argparse
import json
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    source = Path(__file__).parents[1]
    target = args.project / "app/CherryAgent"
    if not (args.project / "agentcore/agentcore.json").is_file():
        raise SystemExit("Create the dedicated AgentCore project first")
    for name in ["app", "agents", "fixtures"]:
        shutil.copytree(
            source / name,
            target / name,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    for name in ["pyproject.toml", "README.md"]:
        shutil.copy2(source / name, target / name)
    shutil.copy2(source / "agentcore/cherry_agent.py", target / "main.py")
    config = args.project / "agentcore/agentcore.json"
    spec = json.loads(config.read_text())
    spec["runtimes"] = [
        {
            "name": "CherryAgent",
            "build": "CodeZip",
            "entrypoint": "main.py",
            "codeLocation": "app/CherryAgent/",
            "runtimeVersion": "PYTHON_3_13",
            "networkMode": "PUBLIC",
            "protocol": "HTTP",
            "instrumentation": {"enableOtel": False},
            "executionRoleArn": "arn:aws:iam::821465445270:role/CherryAgentAWS-Runtime",
            "envVars": [
                {"name": "AWS_REGION", "value": "eu-west-2"},
                {"name": "STRANDS_BEDROCK_MODEL_ID", "value": "eu.anthropic.claude-sonnet-4-6"},
                {"name": "CHERRY_PERSISTENCE_BACKEND", "value": "memory"},
            ],
        }
    ]
    config.write_text(json.dumps(spec, indent=2) + "\n")
    (args.project / "agentcore/aws-targets.json").write_text(
        json.dumps(
            [{"name": "default", "account": "821465445270", "region": "eu-west-2"}], indent=2
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
