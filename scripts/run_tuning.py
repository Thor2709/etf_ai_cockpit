"""Run bounded parameter tuning and write a proposal artefact plus report.

Output is advisory only: the run reads current settings, writes a JSON proposal and a
Markdown report under --output-dir, and never changes a settings file.  Only the
synthetic mode is wired; walk-forward on real history stays unavailable until a
point-in-time objective is supplied and the owner defines acceptance.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etf_cockpit.core.atomic_io import atomic_write_bytes, atomic_write_json  # noqa: E402
from etf_cockpit.validation.optimisation import (  # noqa: E402
    TuningProposal,
    render_tuning_report,
    run_walk_forward_tuning,
    synthetic_tuning_fixture,
)
from etf_cockpit.core.paths import CONFIG_DIR  # noqa: E402
from etf_cockpit.validation.tuning_registry import DEFAULT_REGISTRY_PATH, TuningRegistryError, load_tuning_registry  # noqa: E402

_FORBIDDEN_NAMES = (".owner-root", "models", "configs")
_FORBIDDEN_PREFIXES = ("c:/users/thor2/desktop/trading app",)


def _normal(value: object) -> str:
    return str(value).replace("\\", "/").rstrip("/").lower()


def forbidden_output_reason(raw: Path, resolved: Path, registry_path: Path) -> str | None:
    """Why ``--output-dir`` may not be written, or None.  Checks the raw and resolved spellings."""

    for text in (_normal(raw), _normal(resolved)):
        if any(part in _FORBIDDEN_NAMES for part in text.split("/")):
            return "output_dir_inside_protected_directory"
        if any(text == prefix or text.startswith(prefix + "/") for prefix in _FORBIDDEN_PREFIXES):
            return "output_dir_inside_protected_directory"
    for settings_dir in (registry_path.parent, Path(CONFIG_DIR).resolve()):
        if resolved == settings_dir or settings_dir in resolved.parents:
            return "output_dir_inside_settings_directory"
    return None


def _planted(registry) -> dict[str, float]:  # noqa: ANN001
    """Deterministic, group-consistent synthetic optimum: first member of each group up one step, last member down."""

    planted = {item.key: item.current for item in registry.parameters}
    groups: dict[str, list] = {}
    for item in registry.parameters:
        groups.setdefault(item.group or item.key, []).append(item)
    for members in groups.values():
        if len(members) > 1:
            first, last = members[0], members[-1]
            planted[first.key] = min(first.upper, first.current + first.step)
            planted[last.key] = max(last.lower, last.current - first.step)
    return planted


def _write(output_dir: Path, proposal: TuningProposal) -> tuple[Path, Path]:
    json_path = output_dir / "tuning_proposal.json"
    markdown_path = output_dir / "tuning_report.md"
    atomic_write_json(json_path, proposal.to_dict())
    atomic_write_bytes(markdown_path, render_tuning_report(proposal).encode("utf-8"), lambda path: path.read_text(encoding="utf-8"))
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("synthetic", "walk-forward"), default="synthetic")
    parser.add_argument("--run-id", default="tuning-run")
    parser.add_argument("--samples", type=int, default=800, help="synthetic sample count")
    args = parser.parse_args(argv)
    registry_path = args.registry.resolve()
    output_dir = args.output_dir.resolve()
    refusal = forbidden_output_reason(args.output_dir, output_dir, registry_path)
    if refusal is not None:  # before any ledger or artefact write
        print(f"tuning_status=refused reason={refusal}")
        return 2
    try:
        registry = load_tuning_registry(registry_path)
    except TuningRegistryError as exc:
        print(f"tuning_status=unavailable reason={exc}")
        return 2
    if args.mode == "walk-forward":
        print("tuning_status=unavailable reason=real_history_objective_not_wired (acceptance is owner-defined)")
        return 2
    dates, evaluate = synthetic_tuning_fixture(registry, _planted(registry), n_samples=args.samples)
    proposal = run_walk_forward_tuning(output_dir / "store", args.run_id, registry, evaluate, dates, data_provenance="synthetic")
    json_path, markdown_path = _write(output_dir, proposal)
    print(f"tuning_status={proposal.decision} reasons={','.join(proposal.reasons)} applied=false json={json_path} report={markdown_path}")
    return 0 if proposal.decision != "unavailable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
