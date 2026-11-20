"""Store new FRED/ALFRED vintages of the INT-19 series in the local macro warehouse (context only).

Usage: python scripts/refresh_macro.py [--root PATH]
Runs only when the fred provider is active and an API key resolves; otherwise it prints the reason and makes no request.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None, *, transport: Callable[[str], bytes] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="data root (defaults to ETF_COCKPIT_ROOT)")
    args = parser.parse_args(argv)
    if args.root:
        os.environ["ETF_COCKPIT_ROOT"] = str(Path(args.root).resolve())
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from etf_cockpit.core import config as config_module
    from etf_cockpit.data.fred_provider import FRED_SERIES, FredProvider
    from etf_cockpit.data.macro_warehouse import MacroWarehouse

    section = config_module.load_config().data_providers.section("fred")
    if section.active_provider != "fred":
        print("FRED refresh skipped: the fred provider is not active.")
        return 0
    key = config_module.resolve_provider_api_key("fred", configured_value=section.api_key)
    if not key:
        print("FRED refresh skipped: no FRED API key is configured.")
        return 0
    root = Path(args.root).resolve() if args.root else config_module.CONFIG_DIR.parent
    provider = FredProvider(api_key=key, section=section, transport=transport)
    for series_id in FRED_SERIES:
        result = provider.fetch_vintages(series_id)
        if result.status != "available":
            print(f"{series_id}: unavailable ({result.reason})")
            continue
        try:
            manifest = MacroWarehouse().ingest_vintages(result.observations, root=root)
        except (ValueError, OSError) as exc:
            print(f"{series_id}: unavailable (ingest failed: {type(exc).__name__}: {exc})")
            continue
        print(f"{series_id}: available rows={len(result.observations)} new={manifest['row_count'] if manifest else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
