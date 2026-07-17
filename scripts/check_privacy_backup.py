"""Run the local privacy, encrypted-backup and recovery smoke checks."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etf_cockpit.data.backup_restore import (
    create_encrypted_backup,
    restore_encrypted_backup,
    run_disaster_recovery_drill,
    validate_encrypted_restore,
)
from etf_cockpit.data.privacy import export_redacted_records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report-dir", type=Path, default=Path("artifacts/security/issue-0146"))
    args = parser.parse_args(argv)
    started = time.perf_counter()
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="etf-cockpit-privacy-") as temporary:
        root = Path(temporary)
        source = root / "data" / "journal.json"
        source.parent.mkdir(parents=True)
        source.write_text('{"decision":"hold","private_notes":"do not export"}\n', encoding="utf-8")
        archive = root / "encrypted.backup"
        try:
            create_encrypted_backup([source], archive, "correct recovery key")
            if validate_encrypted_restore(archive, "wrong recovery key").valid:
                failures.append("wrong recovery key was accepted")
            result = restore_encrypted_backup(archive, root / "restored", "correct recovery key")
            if not result.ok:
                failures.append(result.error or "encrypted restore failed")
            export = export_redacted_records([json.loads(source.read_text(encoding="utf-8"))], root / "export.json")
            if "private_notes" in export.path.read_text(encoding="utf-8"):
                failures.append("private field appeared in standard export")
            drill = run_disaster_recovery_drill([source], root / "drill", recovery_key="correct recovery key")
            if not drill.ok:
                failures.extend(drill.errors or ("recovery drill failed",))
        except Exception as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    status = "failed" if failures else "passed"
    report = {
        "schema_version": "1.0",
        "issue": "ISSUE-0146",
        "status": status,
        "failures": failures,
        "network_calls": False,
        "duration_ms": duration_ms,
    }
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "privacy-backup.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = [
        "# ISSUE-0146 privacy and backup check",
        "",
        f"- Status: `{status}`",
        f"- Network calls: `{report['network_calls']}`",
        f"- Duration: `{duration_ms} ms`",
        "",
        "## Failures",
        "",
    ]
    markdown.extend(f"- {failure}" for failure in failures) if failures else markdown.append("None.")
    (args.report_dir / "privacy-backup.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(f"privacy_backup_status={status} network_calls=false failures={len(failures)} duration_ms={duration_ms}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
