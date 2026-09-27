from __future__ import annotations

import subprocess
import sys


MODULES = [
    "tests/test_frontend_design_system.py",
    "tests/test_accessibility_contracts.py",
    "tests/test_comparison_workspace.py",
    "tests/test_e2e_workflow.py",
    "tests/test_issue_0051_cash_comparison.py",
    "tests/test_sec_facts_parser.py",
    "tests/test_task19_instrument_detail.py",
]


for module in MODULES:
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-vv", module],
        check=True,
        capture_output=True,
        text=True,
    )
    nodeids = [
        f"{module}::{line.split('<Function ', 1)[1][:-1]}"
        for line in collected.stdout.splitlines()
        if "<Function " in line
    ]
    if not nodeids:
        raise RuntimeError(f"no nodeids collected for {module}: {collected.stdout}")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:randomly", "-q", *reversed(nodeids)],
        check=False,
    )
    print(f"REVERSE {module} count={len(nodeids)} rc={result.returncode}", flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)
