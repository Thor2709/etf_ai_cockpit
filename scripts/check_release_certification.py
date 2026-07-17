"""Run the local fail-closed release certification report."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from etf_cockpit.governance.release_certification import (  # noqa: E402
    release_certification_report,
    write_release_certification_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    destination = (args.report_dir or root / "artifacts" / "release_certification" / "latest").resolve()
    started = perf_counter()
    try:
        report = release_certification_report(root)
    except Exception as exc:  # certification must fail closed on unexpected local evidence errors
        report = {
            "schema_version": "release-certification.v1",
            "issue_id": "ISSUE-0152",
            "status": "blocked",
            "network_calls": False,
            "execution_allowed": False,
            "release_commit": "unavailable",
            "registry_sha256": "unavailable",
            "counts": {},
            "checks": [],
            "blockers": [f"certification validator failed closed: {type(exc).__name__}: {exc}"],
            "accepted_limitations": [],
            "failures": [f"certification validator failed closed: {type(exc).__name__}: {exc}"],
        }
    report["duration_ms"] = round((perf_counter() - started) * 1000, 3)
    write_release_certification_report(report, destination / "release-certification.json", destination / "release-certification.md")
    print(f"release_certification_status={report['status']} network_calls=false duration_ms={report['duration_ms']}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
