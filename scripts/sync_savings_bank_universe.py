"""List (or add) the listed Norwegian savings banks that are missing from the universe.

    python scripts/sync_savings_bank_universe.py --root <data root> [--capture] [--apply]

Source: the Euronext Oslo public listing (captured with --capture). Without --apply nothing is written.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from etf_cockpit.data.euronext_listing import capture_euronext_oslo_listing
from etf_cockpit.data.savings_bank_universe import isin_corrections, sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--capture", action="store_true", help="fetch the current Euronext Oslo listing first")
    parser.add_argument("--apply", action="store_true", help="save the new records through the universe store")
    args = parser.parse_args(argv)
    if args.capture:
        status = capture_euronext_oslo_listing(root=args.root)
        print(f"listing capture: {status.status} {status.reason or ''}")
    for instrument_id, isin in isin_corrections(args.root).items():
        print(f"{'set' if args.apply else 'would set'} ISIN {isin} on {instrument_id} (official listing)")
    created = sync(args.root, apply=args.apply)
    for record in created:
        print(f"{'added' if args.apply else 'would add'}: {record.instrument_id} {record.isin} {record.name}")
    print(f"{len(created)} bank(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
