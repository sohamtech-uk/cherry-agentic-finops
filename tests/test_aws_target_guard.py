import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_aws_target.sh"


@pytest.mark.parametrize(
    ("account", "region", "default_region", "sts_exit", "success"),
    [
        ("821465445270", "eu-west-2", "eu-west-2", 0, True),
        ("123456789012", "eu-west-2", "eu-west-2", 0, False),
        ("821465445270", "us-east-1", "us-east-1", 0, False),
        ("821465445270", "eu-west-2", "us-east-1", 0, False),
        ("821465445270", "eu-west-2", "eu-west-2", 1, False),
    ],
)
def test_guard_fails_closed(tmp_path, account, region, default_region, sts_exit, success):
    aws = tmp_path / "aws"
    aws.write_text(f"#!/bin/sh\necho {account}\nexit {sts_exit}\n")
    aws.chmod(0o755)
    result = subprocess.run(
        [str(SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "AWS_REGION": region,
            "AWS_DEFAULT_REGION": default_region,
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is success
    assert ("AWS target verified" in result.stdout) is success
