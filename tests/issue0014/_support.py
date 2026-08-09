from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.portfolio.paper_trading import _digest
from etf_cockpit.portfolio.proposal_policy import REQUIRED_GATES, current_authority_policy_checksum


ROOT = Path(__file__).resolve().parents[2]
NETWORK_GUARD = Path(__file__).resolve().parent / "network_guard"


def paper_proposal(*, instrument_id: str = "VWCE", quantity_delta: float = 10.0) -> dict[str, object]:
    """Build the smallest policy-complete proposal accepted by the paper ledger."""

    input_material = {
        "instrument_id": instrument_id,
        "target_quantity": quantity_delta,
        "source": "issue0014-fixture",
    }
    gate_policy = load_gate_policy()
    assert gate_policy.policy is not None
    proposal: dict[str, object] = {
        "schema_version": "proposal.v1",
        "proposal_id": f"proposal_{_digest(input_material)[:20]}",
        "instrument_id": instrument_id,
        "outcome": "proposal_ready",
        "proposal_allowed": True,
        "authority_stage": "paper",
        "execution_allowed": False,
        "quantity_delta": quantity_delta,
        "rationale": "Deterministic ISSUE-0014 paper fixture.",
        "gates": [
            {"gate_id": gate_id, "passed": True, "reason": "passed", "blocker": True}
            for gate_id in REQUIRED_GATES
        ],
        "alternatives": [],
        "as_of": "2099-01-01T00:00:00+00:00",
        "expires_at": "2099-01-02T00:00:00+00:00",
        "policy_version": "proposal-policy.v1",
        "authority_policy_checksum": current_authority_policy_checksum(),
        "gate_policy_version": gate_policy.policy.policy_version,
        "gate_policy_checksum": gate_policy.checksum,
        "input_checksum": _digest(input_material),
        "input_material": input_material,
    }
    proposal["decision_checksum"] = _digest(proposal)
    return proposal


def write_paper_proposal(root: Path, proposal: dict[str, object]) -> None:
    path = root / "data" / "operations" / "proposals" / f"{proposal['proposal_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal, sort_keys=True) + "\n", encoding="utf-8")


def recompute_decision_checksum(proposal: dict[str, object]) -> str:
    return _digest({key: value for key, value in proposal.items() if key != "decision_checksum"})


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def copy_repository_runtime(destination: Path, *, packaging: bool = False) -> Path:
    """Copy the exact runtime/packaging inputs without generated or mutable data."""

    destination.mkdir(parents=True)
    for directory in ("src", "configs", "scripts"):
        shutil.copytree(ROOT / directory, destination / directory)
    if packaging:
        for name in (
            "pyproject.toml",
            "MANIFEST.in",
            "README.md",
            "requirements.txt",
            "requirements-parsers.txt",
        ):
            shutil.copy2(ROOT / name, destination / name)
    return destination


def isolated_environment(runtime_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    python_path = os.pathsep.join(
        [str(NETWORK_GUARD), str(ROOT), str(runtime_root / "src"), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    environment.update(
        {
            "ETF_COCKPIT_ROOT": str(runtime_root),
            "ETF_COCKPIT_OFFLINE": "1",
            "ETF_COCKPIT_OPEN_BROWSER": "0",
            "ETF_COCKPIT_SOCKET_GUARD": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": python_path,
            "TZ": "UTC",
        }
    )
    return environment


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


def run_offline_smoke(
    root: Path,
    smoke_script: Path | None,
    *,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    if smoke_script is None or not smoke_script.is_file():
        raise RuntimeError("packaged offline smoke artifact is missing")
    completed = subprocess.run(
        [
            sys.executable,
            str(smoke_script),
            "--mode",
            "offline",
            "--port",
            str(free_loopback_port()),
            "--timeout",
            str(timeout),
        ],
        cwd=root,
        env=isolated_environment(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout + 30,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stdout + "\n" + completed.stderr).strip()
        raise RuntimeError(f"packaged offline smoke was not runnable ({completed.returncode}): {detail}")
    return completed
