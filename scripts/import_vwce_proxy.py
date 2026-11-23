"""Import the VWRL.AS proxy rows for the VWCE benchmark before 2019-07-29 (D8, OD-2 b).

Usage: python scripts/import_vwce_proxy.py [--root PATH]

Fetches VWRL.AS (Euronext Amsterdam, EUR) 2012-05-22..2019-07-29 through the yfinance provider with an explicit symbol
map (no settings file changes), checks it with the proxy contract and writes
data/reference/vwce_proxy_vwrl_as.parquet + .json under --root in one atomic group. Nothing is written when the check
fails. VWRL.AS never enters prices.parquet or the universe. execution_allowed stays false.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

PROXY_FILE = "vwce_proxy_vwrl_as"


def import_vwce_proxy(root: Path, *, provider: object = None, known_at: datetime | None = None) -> Path:
    """Fetch, check and write the proxy rows under ``root``/data/reference; return the parquet path."""

    import pandas as pd

    from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group
    from etf_cockpit.portfolio.benchmark_reference import (
        VWCE_PROXY_ISIN, VWCE_PROXY_START, VWCE_PROXY_SYMBOL, VWCE_SPLICE_DATE, validate_vwce_proxy_series,
        vwce_series_source_hash,
    )

    if provider is None:
        from etf_cockpit.core.config import ProviderSection
        from etf_cockpit.data.yfinance_provider import YFinanceProvider

        provider = YFinanceProvider(
            ProviderSection(symbols_map={VWCE_PROXY_SYMBOL: VWCE_PROXY_SYMBOL}),
            instrument_metadata={VWCE_PROXY_SYMBOL: {"currency": "EUR"}},
        )
    # The provider end date is exclusive: the splice-date row is the chain anchor.
    result = provider.fetch_prices([VWCE_PROXY_SYMBOL], VWCE_PROXY_START, VWCE_SPLICE_DATE + timedelta(days=1))
    if not result.ok or result.data is None or result.metadata is None:
        raise ValueError(f"VWRL.AS fetch failed: {result.message}")
    frame = result.data.reset_index(drop=True)
    stamp = known_at or result.metadata.ingested_at
    check = validate_vwce_proxy_series(frame, known_at=stamp, provider_metadata=result.metadata)
    if check.status != "available":
        raise ValueError("VWRL.AS proxy failed the proxy contract: " + ",".join(check.reasons))
    stored = frame.assign(known_at=pd.Timestamp(stamp), ingested_at=pd.Timestamp(result.metadata.ingested_at))
    buffer = io.BytesIO()
    stored.to_parquet(buffer, index=False)
    manifest = {
        "source_hash": vwce_series_source_hash(stored), "provider_symbol": VWCE_PROXY_SYMBOL, "isin": VWCE_PROXY_ISIN,
        "currency": "EUR", "source": "yfinance", "splice_date": VWCE_SPLICE_DATE.isoformat(),
        "first_date": check.first_date, "last_date": check.last_date, "rows": len(stored),
        "known_at": pd.Timestamp(stamp).isoformat(), "execution_allowed": False,
    }
    reference = Path(root) / "data" / "reference"
    reference.mkdir(parents=True, exist_ok=True)
    parquet, sidecar = reference / f"{PROXY_FILE}.parquet", reference / f"{PROXY_FILE}.json"
    atomic_write_group((
        AtomicWriteRequest(parquet, buffer.getvalue(), lambda path: pd.read_parquet(path)),
        AtomicWriteRequest(sidecar, json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
                           lambda path: json.loads(path.read_text(encoding="utf-8"))),
    ))
    return parquet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="data root (defaults to ETF_COCKPIT_ROOT)")
    args = parser.parse_args(argv)
    if not args.root:
        parser.error("--root (or ETF_COCKPIT_ROOT) is required")
    try:
        written = import_vwce_proxy(Path(args.root).resolve())
    except (ValueError, OSError) as exc:
        print(f"VWCE proxy not imported: {exc}", file=sys.stderr)
        return 1
    print(f"VWCE proxy written: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
