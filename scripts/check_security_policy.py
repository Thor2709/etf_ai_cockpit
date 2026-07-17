"""Run the local fail-closed security policy check and write timing evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etf_cockpit.security.policy import build_security_report  # noqa: E402


def run_check(root: Path, report_dir: Path) -> tuple[int, Path, Path]:
    started = time.perf_counter()
    report = build_security_report(root)
    report["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "security.json"
    markdown_path = report_dir / "security.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    failures = report.get("failures", [])
    lines = [
        "# Security policy report",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Duration: `{report['duration_ms']:.3f} ms`",
        f"- Network calls: `{report.get('network_calls')}`",
        f"- Local UI host: `{report.get('local_ui_host', 'unavailable')}`",
        f"- HTTP API exposed: `{report.get('http_api_exposed', 'unavailable')}`",
        "",
        "## Failures",
        "",
    ]
    lines.extend(f"- {failure}" for failure in failures) if failures else lines.append("- None")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"security_policy_status={report.get('status')} network_calls=false failures={len(failures)}")
    return (1 if failures else 0), json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    report_dir = args.report_dir or args.root / "artifacts" / "security" / "latest"
    return run_check(args.root.resolve(), report_dir.resolve())[0]


if __name__ == "__main__":
    raise SystemExit(main())
