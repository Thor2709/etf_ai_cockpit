"""Validate the local bulk-cache inventory without performing network I/O."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from etf_cockpit.data.bulk_cache import bulk_cache_health  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = bulk_cache_health(root)
    destination = (args.report_dir or root / "artifacts" / "bulk_cache" / "latest").resolve()
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "bulk-cache.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    lines = [
        "# Bulk cache report",
        "",
        f"- Schema: `{report['schema_version']}`",
        f"- Status: `{report['status']}`",
        "- Network calls: `false`",
        f"- Objects: `{report['object_count']}`",
        f"- Manifests: `{report['manifest_count']}`",
        f"- Staged files: `{report['staged_file_count']}`",
        f"- Promoted generations: `{report['promoted_generation_count']}`",
        f"- Failures: `{', '.join(str(item) for item in report['failures']) or 'none'}`",
    ]
    (destination / "bulk-cache.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"bulk_cache_status={report['status']} network_calls=false failures={len(report['failures'])}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
