"""Evaluate local timing, memory and storage evidence against versioned budgets."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from etf_cockpit.core.performance import build_performance_report, write_performance_report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = build_performance_report(root)
    destination = (args.report_dir or root / "artifacts" / "performance" / "latest").resolve()
    write_performance_report(report, destination / "performance.json", destination / "performance.md")
    print(f"performance_status={report['status']} failures={','.join(report['failures']) or 'none'}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
