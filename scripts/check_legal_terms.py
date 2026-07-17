"""Validate the local legal/source/model terms registry without network access."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from etf_cockpit.data.legal_terms import LegalTermsError, legal_terms_report, write_legal_terms_report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    destination = (args.report_dir or root / "artifacts" / "legal_terms" / "latest").resolve()
    started = perf_counter()
    failures: list[str] = []
    try:
        report = legal_terms_report(root)
    except LegalTermsError as exc:
        report = {
            "schema_version": "legal-terms.v1",
            "status": "failed",
            "review_status": "unavailable",
            "professional_review_required": True,
            "network_calls": False,
            "rows": [],
            "unresolved_mandatory": [],
            "failures": [],
        }
        failures.append(str(exc))
    report["duration_ms"] = round((perf_counter() - started) * 1000, 3)
    report.setdefault("failures", []).extend(failures)
    if report.get("failures"):
        report["status"] = "failed"
    write_legal_terms_report(report, destination / "legal-terms.json", destination / "legal-terms.md")
    print(f"legal_terms_status={report['status']} network_calls=false duration_ms={report['duration_ms']}")
    return 1 if report["status"] != "passed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
