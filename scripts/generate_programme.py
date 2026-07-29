"""Stage, validate and atomically publish the complete programme projection."""

from __future__ import annotations

import argparse
import hashlib
import json
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

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from etf_cockpit.core import atomic_io  # noqa: E402,F401
from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group  # noqa: E402


SCHEMA_VERSION = "programme-generation.v1"
STATIC_REQUIRED_OUTPUTS = frozenset(
    {
        "README.md",
        "CHANGELOG.md",
        "issues/open.md",
        "issues/issue_registry.json",
        "issues/programme_control_state.json",
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
    payload = path.read_bytes()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        canonical = payload
    else:
        canonical = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


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
    required_summary = {"create", "update", "close", "reopen", "blocked"}
    if (
        not isinstance(summary, dict)
        or set(summary) != required_summary
        or any(value != 0 for value in summary.values())
        or not isinstance(actions, list)
        or actions
    ):
        raise ValueError("convergence evidence must contain mandatory zero-action readback")
    if evidence.get("repository") != "Thor2709/etf_ai_cockpit":
        raise ValueError("convergence evidence repository mismatch")
    if evidence.get("schema_version") != "etf-ai-cockpit.safe-sync-evidence/1.0":
        raise ValueError("convergence evidence schema mismatch")
    semantic = evidence.get("plan_semantic_sha256")
    if not isinstance(semantic, str) or not __import__("re").fullmatch(
        r"[0-9a-f]{64}", semantic
    ):
        raise ValueError("convergence semantic plan checksum is invalid")
    if evidence.get("remote_inventory_sha256") != remote.get("inventory_sha256"):
        raise ValueError("convergence evidence does not match the immutable remote snapshot")
    evidence_bytes = evidence_path.read_bytes()
    expected_sidecar = (
        f"{hashlib.sha256(evidence_bytes).hexdigest()}  github-sync-evidence.json\n"
    ).encode()
    if sidecar_path.read_bytes().replace(b"\r\n", b"\n") != expected_sidecar:
        raise ValueError("reviewed convergence evidence sidecar checksum mismatch")


def _accept_reviewed_or_fresh_noop_sidecar(
    reviewed_sidecar: Path,
    generated_sidecar: Path,
) -> None:
    """Accept checksum drift only after the generated plan proved a safe no-op."""

    reviewed = reviewed_sidecar.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not __import__("re").fullmatch(
        r"[0-9a-f]{64}  github-sync-evidence\.json\n",
        reviewed,
    ):
        raise ValueError("reviewed convergence checksum is invalid")
    generated = generated_sidecar.read_text(encoding="utf-8").replace("\r\n", "\n")
    if reviewed == generated:
        return
    # The caller validates the generated evidence first. A checksum change is
    # therefore inventory/readback evidence only and grants no apply authority.


def _verify_exact_head(root: Path, expected_head: str, main_ref: str) -> None:
    if not __import__("re").fullmatch(r"[0-9a-f]{40}", expected_head):
        raise ValueError("convergence expected head must be a full commit SHA")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    main = subprocess.check_output(["git", "rev-parse", main_ref], cwd=root, text=True).strip()
    if head != expected_head or main != expected_head:
        raise ValueError("convergence exact head does not equal HEAD and fresh main")


def run_convergence(
    root: Path,
    stage: Path,
    *,
    expected_head: str,
    main_ref: str,
    remote_snapshot: Path | None,
    reviewed_sidecar: Path,
    control_candidate: Path | None = None,
) -> frozenset[str]:
    """Run one read-only sync plan into the staged programme transaction."""

    _verify_exact_head(root, expected_head, main_ref)
    outputs = stage_generation(
        root,
        stage,
        control_candidate=control_candidate,
        validate_convergence=False,
    )
    recon = next(
        (stage / path).parent
        for path in outputs
        if path.endswith("/github-remote-summary.json")
    )
    plan = recon / "github-sync-plan.json"
    evidence = recon / "github-sync-evidence.json"
    command = [
            sys.executable,
            "scripts/sync_github_issues.py",
            "--root",
            str(stage),
            "--plan-out",
            str(plan),
            "--inventory-out",
            str(recon / "github-remote-summary.json"),
            "--review-out",
            str(recon / "github-sync-review.md"),
            "--safe-evidence-out",
            str(evidence),
        ]
    if remote_snapshot is not None:
        command.extend(["--remote-snapshot", str(remote_snapshot.resolve())])
    subprocess.run(
        command,
        cwd=stage,
        check=True,
    )
    convergence_outputs = outputs | {plan.relative_to(stage).as_posix()}
    _validate_and_emit_convergence_evidence(stage, convergence_outputs)
    _accept_reviewed_or_fresh_noop_sidecar(
        reviewed_sidecar,
        evidence.with_suffix(".json.sha256"),
    )
    (stage / MANIFEST_PATH).write_bytes(build_manifest(stage, convergence_outputs))
    return convergence_outputs


def atomic_publish(
    root: Path,
    staged_root: Path,
    outputs: frozenset[str],
    *,
    lifecycle_hook: Callable[[str, Path], None] | None = None,
) -> None:
    """Publish through the repository's durable grouped-write journal."""

    requests = []
    for relative in sorted(outputs | {MANIFEST_PATH.as_posix()}):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        requests.append(
            AtomicWriteRequest(
                destination=destination,
                payload=(staged_root / relative).read_bytes(),
                validator=lambda path: path.read_bytes(),
            )
        )
    atomic_write_group(requests, lifecycle_hook=lifecycle_hook)


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


def stage_generation(
    root: Path,
    stage: Path,
    *,
    control_candidate: Path | None = None,
    validate_convergence: bool = True,
) -> frozenset[str]:
    _copy_tracked_tree(root, stage)
    if control_candidate is not None:
        candidate = json.loads(control_candidate.read_text(encoding="utf-8"))
        if '"execution_allowed": true' in json.dumps(candidate).lower():
            raise ValueError("reviewed control candidate must preserve execution_allowed=false")
        (stage / "issues/programme_control_state.json").write_bytes(
            (json.dumps(candidate, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        )
    _run_generators(stage)
    outputs = required_outputs(stage)
    if validate_convergence:
        _validate_and_emit_convergence_evidence(stage, outputs)
    (stage / MANIFEST_PATH).parent.mkdir(parents=True, exist_ok=True)
    (stage / MANIFEST_PATH).write_bytes(build_manifest(stage, outputs))
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--converge", action="store_true")
    parser.add_argument("--expected-head")
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--remote-snapshot", type=Path)
    parser.add_argument("--reviewed-sidecar", type=Path)
    parser.add_argument("--control-candidate", type=Path)
    parser.add_argument("--live-read", action="store_true")
    parser.add_argument("--stage-output", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    with tempfile.TemporaryDirectory(prefix=".programme-stage-", dir=root) as value:
        stage = Path(value)
        try:
            if args.converge:
                if (
                    not args.expected_head
                    or (not args.remote_snapshot and not args.live_read)
                    or not args.reviewed_sidecar
                ):
                    raise ValueError(
                        "--converge requires --expected-head, one remote input mode, and --reviewed-sidecar"
                    )
                outputs = run_convergence(
                    root,
                    stage,
                    expected_head=args.expected_head,
                    main_ref=args.main_ref,
                    remote_snapshot=args.remote_snapshot,
                    reviewed_sidecar=args.reviewed_sidecar,
                    control_candidate=args.control_candidate,
                )
            else:
                outputs = stage_generation(
                    root, stage, control_candidate=args.control_candidate
                )
            expected = outputs | {MANIFEST_PATH.as_posix()}
            stale = sorted(
                path
                for path in expected
                if not (root / path).is_file()
                or (root / path).read_bytes() != (stage / path).read_bytes()
            )
            if args.stage_output:
                destination = args.stage_output.resolve()
                destination.mkdir(parents=True, exist_ok=True)
                for relative in sorted(outputs | {MANIFEST_PATH.as_posix()}):
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(stage / relative, target)
                print(f"STAGED: {destination}")
                return 0
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
