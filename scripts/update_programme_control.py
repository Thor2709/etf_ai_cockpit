"""Create or update the canonical programme control-state input.

This command is the guarded write path for reviewed status/evidence state.  The
registry remains generated; mutable review decisions live in one versioned
companion input instead of Python constants or generated output.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


CONTROL_PATH = Path("issues/programme_control_state.json")
REGISTRY_PATH = Path("issues/issue_registry.json")


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _phase_metadata(registry: dict[str, object]) -> list[dict[str, object]]:
    phases = registry.get("roadmap_phases", [])
    return [
        {
            "phase": phase["phase"],
            "title": phase["title"],
            "order": index,
        }
        for index, phase in enumerate(phases, start=1)
        if isinstance(phase, dict)
    ]


def import_registry(root: Path, baseline: str) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise ValueError("--baseline must be a full lowercase Git SHA")
    verified = _git(root, "rev-parse", "origin/main")
    if baseline != verified:
        raise ValueError(f"--baseline {baseline} does not match freshly verified origin/main {verified}")
    registry = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
    records: dict[str, object] = {}
    source_records = [*registry.get("records", []), *registry.get("local_only_records", [])]
    for record in source_records:
        issue_id = str(record["canonical_id"])
        status = record.get(
            "programme_status",
            "closed" if record.get("ledger_state") == "closed" else "planned",
        )
        records[issue_id] = {
            "programme_status": status,
            "phase": record.get("phase", "phase-01-governance-scope"),
            "acceptance_evidence": record.get("acceptance_evidence", []),
            "dependency_edge_evidence": record.get("dependency_edge_evidence", {}),
            "verified_commit": record.get("verified_commit", baseline),
            "verified_date": record.get("verified_date", "2026-07-21"),
            "status_transition": {
                "from": status,
                "to": status,
                "review_reference": "B00 canonical import from audited programme state",
            },
        }
    return {
        "schema_version": "1.0",
        "metadata": {
            "generation_base_commit": baseline,
            "generation_base_ref": "origin/main",
            "verified_date": "2026-07-21",
        },
        "phase_definitions": _phase_metadata(registry),
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--import-registry", action="store_true")
    parser.add_argument("--baseline", help="freshly verified generation base SHA")
    parser.add_argument("--check-base", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    path = root / CONTROL_PATH
    if args.import_registry:
        if not args.baseline:
            parser.error("--import-registry requires --baseline")
        value = import_registry(root, args.baseline)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"Wrote {path.relative_to(root)}")
        return 0
    if args.check_base:
        value = json.loads(path.read_text(encoding="utf-8"))
        expected = value["metadata"]["generation_base_commit"]
        actual = _git(root, "rev-parse", value["metadata"].get("generation_base_ref", "origin/main"))
        if actual != expected:
            print(f"STALE: control base {expected}, verified ref {actual}")
            return 1
        print(f"FRESH: control base {actual}")
        return 0
    parser.error("select --import-registry or --check-base")


if __name__ == "__main__":
    raise SystemExit(main())
