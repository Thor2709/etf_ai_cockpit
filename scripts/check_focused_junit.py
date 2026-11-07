"""Verify that the focused PR tests executed exactly what pytest collected.

Return codes alone cannot show a silently dropped, duplicated or skipped test. This reads the
``pytest --collect-only -q`` listing and the JUnit reports and fails on any difference, reusing the
release gate's execution-parity rules.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.release_gate import _junit_execution_problems, _nodeids_from_collection
except ImportError:  # also pywin32's top-level 'scripts' namespace
    from release_gate import _junit_execution_problems, _nodeids_from_collection  # type: ignore[no-redef]


def problems(reports: list[Path], collected: Path) -> list[str]:
    """Return every reason the focused run is not proven complete (empty list = proven)."""

    try:
        expected = _nodeids_from_collection(collected.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        return [f"collection listing unavailable: {exc}"]
    if not expected:
        return ["collection listing contains no test node ids"]
    if not reports:
        return ["no JUnit report was produced"]
    missing = [str(report) for report in reports if not report.is_file()]
    if missing:
        return ["JUnit report missing: " + ", ".join(missing)]
    try:
        return _junit_execution_problems(tuple(reports), expected)
    except (ET.ParseError, OSError) as exc:
        return [f"JUnit report unreadable: {exc}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collected", type=Path, required=True)
    parser.add_argument("--junit", type=Path, nargs="+", required=True)
    args = parser.parse_args(argv)
    found = problems(list(args.junit), args.collected)
    for problem in found:
        print(f"check_focused_junit: {problem}", file=sys.stderr)
    if not found:
        print("check_focused_junit: every collected focused test executed exactly once")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
