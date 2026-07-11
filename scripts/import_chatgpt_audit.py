from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "app" / "src"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

from etf_cockpit.core.config import load_config
from etf_cockpit.services import ChatGPTBridge


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    args = parser.parse_args()
    audit = ChatGPTBridge(load_config()).import_audit_json(Path(args.path))
    print(f"imported {audit.review_date} {audit.overall_view}")


if __name__ == "__main__":
    main()
