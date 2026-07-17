"""Validate the local-first source policy and write no-network evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from etf_cockpit.data.source_policy import source_policy_report, write_source_policy_report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = source_policy_report(root)
    destination = (args.report_dir or root / "artifacts" / "source_policy" / "latest").resolve()
    write_source_policy_report(report, destination / "source-policy.json", destination / "source-policy.md")
    print(f"source_policy_status={report['status']} network_calls={str(report['network_calls']).lower()}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
