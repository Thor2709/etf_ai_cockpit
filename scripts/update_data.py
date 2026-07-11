from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "app" / "src"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

from etf_cockpit.core.config import load_config
from etf_cockpit.services import DataService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="Regenerate deterministic sample data.")
    parser.add_argument("--provider", default="sample", help="Provider name. Only sample is implemented in MVP.")
    args = parser.parse_args()
    if args.provider != "sample" and not args.sample:
        raise SystemExit("Only the sample provider is implemented in the MVP.")
    config = load_config()
    DataService(config).update_prices(force_sample=True)
    print("sample_data_updated")


if __name__ == "__main__":
    main()
