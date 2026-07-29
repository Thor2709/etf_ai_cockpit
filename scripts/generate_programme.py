"""Stage, validate and atomically publish the complete programme projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

try:
    from scripts.issue_registry_core import load_control_state
except ModuleNotFoundError:
    from issue_registry_core import load_control_state


SCHEMA_VERSION = "programme-generation.v1"
STATIC_REQUIRED_OUTPUTS = frozenset(
    {
        "README.md",
        "CHANGELOG.md",
        "issues/open.md",
        "issues/issue_registry.json",
        "docs/product-completion/CURRENT_STATUS.json",
        "docs/product-completion/PROGRESS.md",
        "docs/product-completion/programme/readiness.json",
        "docs/product-completion/programme/roadmap.md",
        "docs/product-completion/programme/implementation-order.md",
        "docs/product-completion/programme/git-workflow.md",
        "docs/product-completion/programme/prompt-2-handoff.md",
        "docs/product-completion/programme/test-and-performance-strategy.md",
        ".github/status-transition-guard-manifest.json",
    }
)
RECONCILIATION_REQUIRED_NAMES = frozenset(
    {
        "canonical-dag.json",
        "current-only-records.csv",
        "current-state-diff.md",
        "dependency-reconciliation.csv",
        "github-inventory.json",
        "github-remote-summary.json",
        "github-sync-evidence.json",
        "github-sync-evidence.json.sha256",
        "github-sync-review.md",
        "intake-report.json",
        "ownership.csv",
        "package-discrepancies.md",
        "README.md",
        "source-to-canonical.csv",
    }
)
MANIFEST_PATH = Path("docs/product-completion/programme/generation-manifest.json")


def required_outputs(root: Path) -> frozenset[str]:
    """Return the closed output set for the control state's projection identity."""

    control = load_control_state(root)
    baseline = control["metadata"]["generation_base_commit"]
    prefix = f"docs/product-completion/reconciliation/2026-07-21-{baseline[:7]}"
    phases = frozenset(
        f"docs/product-completion/programme/phases/{phase['phase']}.md"
        for phase in control["phase_definitions"]
    )
    return STATIC_REQUIRED_OUTPUTS | phases | frozenset(
        f"{prefix}/{name}" for name in RECONCILIATION_REQUIRED_NAMES
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(root: Path, outputs: frozenset[str]) -> bytes:
    missing = sorted(path for path in outputs if not (root / path).is_file())
    if missing:
        raise ValueError("mandatory programme outputs are absent: " + ", ".join(missing))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "execution_allowed": False,
        "outputs": [
            {"path": path, "sha256": _sha256(root / path)}
            for path in sorted(outputs)
        ],
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _validate_and_emit_convergence_evidence(root: Path, outputs: frozenset[str]) -> None:
    remote_path = next(root / path for path in outputs if path.endswith("/github-remote-summary.json"))
    evidence_path = next(root / path for path in outputs if path.endswith("/github-sync-evidence.json"))
    sidecar_path = next(
        root / path for path in outputs if path.endswith("/github-sync-evidence.json.sha256")
    )
    remote = json.loads(remote_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("apply_authority") is not False:
        raise ValueError("convergence evidence must not grant GitHub apply authority")
    if evidence.get("fresh_exact_plan_required_for_apply") is not True:
        raise ValueError("convergence evidence must require a fresh checksum-controlled plan")
    summary = evidence.get("summary")
    actions = evidence.get("actions")
    if (
        not isinstance(summary, dict)
        or any(value != 0 for value in summary.values())
        or not isinstance(actions, list)
        or actions
    ):
        raise ValueError("convergence evidence must contain mandatory zero-action readback")
    if evidence.get("remote_inventory_sha256") != remote.get("inventory_sha256"):
        raise ValueError("convergence evidence does not match the immutable remote snapshot")
    remote_path.write_bytes((json.dumps(remote, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    evidence_bytes = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("utf-8")
    evidence_path.write_bytes(evidence_bytes)
    sidecar_path.write_text(
        f"{hashlib.sha256(evidence_bytes).hexdigest()}  github-sync-evidence.json\n",
        encoding="utf-8",
        newline="\n",
    )


def atomic_publish(
    root: Path,
    staged_root: Path,
    outputs: frozenset[str],
    *,
    replace: Callable[[Path, Path], None] = os.replace,
) -> None:
    """Publish a validated set and restore the complete predecessor on failure."""

    transaction = Path(tempfile.mkdtemp(prefix=".programme-publish-", dir=root))
    backups = transaction / "backups"
    incoming = transaction / "incoming"
    existed: set[str] = set()
    try:
        for relative in sorted(outputs | {MANIFEST_PATH.as_posix()}):
            source = (
                staged_root / relative
                if relative != MANIFEST_PATH.as_posix()
                else staged_root / MANIFEST_PATH
            )
            destination = root / relative
            staged = incoming / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, staged)
            if destination.exists():
                backup = backups / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
                existed.add(relative)
        published: list[str] = []
        try:
            for relative in sorted(outputs | {MANIFEST_PATH.as_posix()}):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                replace(incoming / relative, destination)
                published.append(relative)
        except BaseException:
            for relative in reversed(published):
                destination = root / relative
                if relative in existed:
                    replace(backups / relative, destination)
                elif destination.exists():
                    destination.unlink()
            raise
    finally:
        shutil.rmtree(transaction, ignore_errors=True)


def _copy_tracked_tree(root: Path, stage: Path) -> None:
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root
    ).decode("utf-8").split("\0")
    for relative in (item for item in tracked if item):
        source = root / relative
        if not source.is_file():
            continue
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _run_generators(stage: Path) -> None:
    commands = (
        ("scripts/generate_issue_registry.py",),
        ("scripts/update_programme_status.py",),
        ("scripts/generate_completion_documents.py",),
        ("scripts/validate_issue_registry.py",),
    )
    for command in commands:
        subprocess.run(
            [sys.executable, *command, "--root", str(stage)],
            cwd=stage,
            check=True,
        )


def stage_generation(root: Path, stage: Path) -> frozenset[str]:
    _copy_tracked_tree(root, stage)
    _run_generators(stage)
    outputs = required_outputs(stage)
    _validate_and_emit_convergence_evidence(stage, outputs)
    (stage / MANIFEST_PATH).parent.mkdir(parents=True, exist_ok=True)
    (stage / MANIFEST_PATH).write_bytes(build_manifest(stage, outputs))
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    with tempfile.TemporaryDirectory(prefix=".programme-stage-", dir=root) as value:
        stage = Path(value)
        try:
            outputs = stage_generation(root, stage)
            expected = outputs | {MANIFEST_PATH.as_posix()}
            stale = sorted(
                path
                for path in expected
                if not (root / path).is_file()
                or (root / path).read_bytes() != (stage / path).read_bytes()
            )
            if args.check:
                if stale:
                    print("STALE: " + ", ".join(stale))
                    return 1
                print("FRESH: complete programme projection is byte-clean")
                return 0
            atomic_publish(root, stage, outputs)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"ERROR: {exc}")
            return 1
    print(f"WROTE: {len(outputs)} mandatory programme outputs atomically")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
