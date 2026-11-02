"""Canonical MCP flows in fresh processes with isolated, seeded data roots.

Section 2 limits responses to 8k tokens. We use the documented conservative
estimate of 4 JSON characters per token, hence a 32,000-character ceiling.
Only Yahoo search/profile and OpenFIGI HTTP responses are stubbed (offline
identity lookup); external AI research is supplied fixture evidence. No job,
persistence, score, proposal, gate or status service is stubbed. Optional model
weights are disabled. Independent flows run in separate processes under xdist.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


class KnownToolDefect(AssertionError):
    """An explicitly reproduced product defect, never an arbitrary test failure."""


@pytest.mark.parametrize("flow", [
    pytest.param(1, marks=pytest.mark.xfail(strict=True, raises=KnownToolDefect,
        reason="DEFECT L9-refresh: tools_data omits HeadlessSession.submit_workflow's required dedupe_key")),
    2, 3,
    pytest.param(4, marks=pytest.mark.xfail(strict=True, raises=KnownToolDefect,
        reason="DEFECT L9-paper-capacity: manual order cost call supplies no ADV, so liquidity always blocks")),
    5,
    pytest.param(6, marks=pytest.mark.xfail(strict=True, raises=KnownToolDefect,
        reason="D2: ticket/fill tools deferred by owner")),
])
def test_owner_flow(flow: int, tmp_path: Path) -> None:
    fixture_dir = Path(__file__).parent / "fixtures"
    root = tmp_path / "root"
    (root / "configs").mkdir(parents=True)
    # project_root requires this marker before any etf_cockpit import.
    (root / "configs" / "universe.yaml").write_text(
        (fixture_dir / "universe.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    env = {**os.environ, "ETF_COCKPIT_ROOT": str(root), "CUDA_VISIBLE_DEVICES": "",
           "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    completed = subprocess.run(
        [sys.executable, str(fixture_dir / "run_flows.py"), str(flow), str(root)],
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode == 23:
        raise KnownToolDefect(output)
    assert completed.returncode == 0, output
