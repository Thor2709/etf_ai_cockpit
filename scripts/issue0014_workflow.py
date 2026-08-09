"""Run the deterministic, separated ISSUE-0014 workflow contract."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    ("source", "tests/issue0014/test_source_workflows.py"),
    ("packaged", "tests/issue0014/test_packaged_workflows.py"),
    ("browser", "tests/issue0014/test_browser_workflows.py"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the exact suite commands")
    return parser


def _command(path: str) -> tuple[str, ...]:
    return (sys.executable, "-m", "pytest", "-q", path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = [{"suite": name, "command": list(_command(path))} for name, path in SUITES]
    if args.dry_run:
        print({"offline": True, "execution_allowed": False, "suites": commands})
        return 0

    environment = os.environ.copy()
    environment.update({"ETF_COCKPIT_OFFLINE": "1", "PYTHONHASHSEED": "0", "TZ": "UTC"})
    for name, path in SUITES:
        print(f"issue0014 suite={name}")
        completed = subprocess.run(_command(path), cwd=ROOT, env=environment, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
