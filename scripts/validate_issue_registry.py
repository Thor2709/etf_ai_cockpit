"""Validate canonical issue state, dependencies, ownership and roadmap coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.issue_registry_core import (
        CLOSED_LEDGER,
        OPEN_LEDGER,
        REGISTRY_PATH,
        build_registry,
        deterministic_json,
        parse_closed_index,
        parse_open_ledger,
        validate_registry,
    )
except ModuleNotFoundError:
    from issue_registry_core import (
        CLOSED_LEDGER,
        OPEN_LEDGER,
        REGISTRY_PATH,
        build_registry,
        deterministic_json,
        parse_closed_index,
        parse_open_ledger,
        validate_registry,
    )


def validate_programme(root: Path) -> list[str]:
    target = root / REGISTRY_PATH
    if not target.exists():
        return [f"missing registry: {target}"]
    try:
        registry = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"invalid registry JSON: {exc}"]
    errors = validate_registry(
        registry,
        open_ids=set(parse_open_ledger(root / OPEN_LEDGER)),
        closed_ids=set(parse_closed_index(root / CLOSED_LEDGER)),
    )
    records = registry.get("records", [])
    expected = build_registry(root)
    expected_ids = {str(record.get("canonical_id")) for record in expected.get("records", [])}
    actual_ids = {str(record.get("canonical_id")) for record in records}
    if actual_ids != expected_ids:
        errors.append("canonical IDs do not reconcile to versioned source inputs")
    phase_ids = {
        str(phase.get("phase"))
        for phase in registry.get("roadmap_phases", [])
        if isinstance(phase, dict)
    }
    for record in records:
        if record.get("phase") not in phase_ids:
            errors.append(f"{record.get('canonical_id')}: missing roadmap phase")
    mapping_ids = [str(record.get("source_record_id")) for record in records]
    if len(mapping_ids) != len(records) or len(mapping_ids) != len(set(mapping_ids)):
        errors.append("source-to-canonical mapping must contain exactly one row per source record")
    if deterministic_json(registry) != deterministic_json(expected):
        errors.append("canonical registry content has drifted from versioned source inputs")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    errors = validate_programme(args.root.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("VALID: issue registry, ownership, dependencies, mappings and roadmap coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
