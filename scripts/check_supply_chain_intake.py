"""Validate local supply-chain intake and provenance evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from etf_cockpit.governance.supply_chain_intake import (  # noqa: E402
    SupplyChainIntakeError,
    supply_chain_intake_report,
    write_supply_chain_intake_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    destination = (args.report_dir or root / "artifacts" / "supply_chain_intake" / "latest").resolve()
    started = perf_counter()
    try:
        report = supply_chain_intake_report(root)
    except (SupplyChainIntakeError, OSError, ValueError, TypeError) as exc:
        report = {
            "schema_version": "supply-chain-intake.v1",
            "status": "failed",
            "review_status": "unavailable",
            "network_calls": False,
            "execution_allowed": False,
            "failures": [str(exc)],
            "hardening_required": [],
            "components": [],
            "dependencies": [],
        }
    report["duration_ms"] = round((perf_counter() - started) * 1000, 3)
    write_supply_chain_intake_report(report, destination / "supply-chain-intake.json", destination / "supply-chain-intake.md")
    print(f"supply_chain_intake_status={report['status']} review_status={report.get('review_status', 'unavailable')} network_calls=false duration_ms={report['duration_ms']}")
    return 1 if report.get("status") != "passed" or report.get("review_status") != "approved" or report.get("failures") else 0


if __name__ == "__main__":
    raise SystemExit(main())
