"""Fetch and record the current Euronext Oslo listing snapshot."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from etf_cockpit.data.euronext_listing import capture_euronext_oslo_listing  # noqa: E402


def main() -> int:
    status = capture_euronext_oslo_listing(root=PROJECT_ROOT)
    print(f"Euronext Oslo listing capture: {status.status}")
    if status.as_of_date:
        print(f"As of: {status.as_of_date}; accepted rows: {status.accepted_rows}")
    if status.reason:
        print(status.reason)
    for rejection in status.rejected_rows:
        print(f"Rejected row {rejection.row_number} ({rejection.instrument_id}): {rejection.reason}")
    return 0 if status.status in {"recorded", "duplicate"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
