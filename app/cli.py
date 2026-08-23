from __future__ import annotations

import argparse
import json

from app.container import get_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Cherry Agent finance workflow.")
    parser.add_argument(
        "scenario", choices=["autonomous", "approval", "exception"], nargs="?", default="autonomous"
    )
    args = parser.parse_args()
    workflow = get_engine().run_demo(args.scenario)
    print(json.dumps(workflow.model_dump(mode="json"), indent=2, default=str))


if __name__ == "__main__":
    main()
