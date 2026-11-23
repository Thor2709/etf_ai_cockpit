"""ECB euro reference rates for the FX store (owner decision OD-1 = b; ADR-0003).

A rate is available at its ECB publish time, 16:00 Frankfurt time on the rate day; a rate fetched before that time
(should the ECB publish early) is live and available at its fetch time. Rows keep the published direction: EXR
``D.USD.EUR.SP00.A`` = USD per EUR is stored as pair ``EUR/USD``. ``prefer_ecb_rates`` keeps one rate per day and
currency in the store.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import csv
from datetime import date, datetime
from pathlib import Path
import io

import pandas as pd

from etf_cockpit.core.paths import RAW_DIR, SNAPSHOTS_DIR
from etf_cockpit.data.fx_data import (
    ECB_FX_SOURCE, ECB_PUBLICATION, FX_CLEAN_PATH, LIVE_INGESTION, FxImportCommit, commit_fx_import, ecb_publish_time,
    load_fx_rates, prefer_ecb_rates,
)
from etf_cockpit.data.macro_warehouse import fetch_bytes, fetch_time, legal_terms_block
from etf_cockpit.data.providers import ProviderResult

_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{currencies}.EUR.SP00.A?startPeriod={start}&format=csvdata"


def parse_ecb_fx_csv(content: bytes, *, fetched_at: datetime) -> pd.DataFrame:
    """FX store rows from an ECB EXR ``csvdata`` payload of daily reference rates; a blank value is skipped, never filled."""

    fetched = pd.Timestamp(fetch_time(fetched_at))
    rows = []
    for row in csv.DictReader(io.StringIO(content.decode("utf-8-sig"))):
        value = (row["OBS_VALUE"] or "").strip()
        if not value:
            continue
        if (row["FREQ"].strip(), row["CURRENCY_DENOM"].strip(), row["EXR_TYPE"].strip(), row["EXR_SUFFIX"].strip()) != ("D", "EUR", "SP00", "A"):
            raise ValueError(f"not a daily ECB euro reference rate: {row['KEY'].strip()}")
        rows.append({
            "as_of_date": date.fromisoformat(row["TIME_PERIOD"].strip()), "base_currency": "EUR",
            "quote_currency": row["CURRENCY"].strip(), "rate": float(value), "provider_symbol": row["KEY"].strip(),
        })
    frame = pd.DataFrame(rows, columns=["as_of_date", "base_currency", "quote_currency", "rate", "provider_symbol"])
    frame.insert(3, "pair", frame["base_currency"] + "/" + frame["quote_currency"])
    frame["source"] = ECB_FX_SOURCE
    published = ecb_publish_time(frame["as_of_date"])
    live = published.gt(fetched)
    frame["ingested_at"] = fetched
    frame["available_at"] = published.where(~live, fetched)
    frame["availability_basis"] = pd.Series(ECB_PUBLICATION, index=frame.index).where(~live, LIVE_INGESTION)
    return frame.loc[frame["as_of_date"].le(fetched.date())].reset_index(drop=True)


def fetch_ecb_fx(
    currencies: Iterable[str], *, start: date, transport: Callable[[str], bytes] | None = None,
) -> pd.DataFrame:
    """Fetch the daily ECB reference rates of ``currencies`` against EUR from ``start`` (network; not run in tests)."""

    blocked = legal_terms_block("ecb")
    if blocked:
        raise ValueError(f"ECB FX blocked: {blocked}")
    url = _URL.format(currencies="+".join(sorted({str(code).strip().upper() for code in currencies})), start=start.isoformat())
    payload = transport(url) if transport else fetch_bytes(url, {"User-Agent": "ETF AI Evidence Cockpit/1.0", "Accept": "text/csv"})
    return parse_ecb_fx_csv(payload, fetched_at=fetch_time(None))


def commit_ecb_fx(
    rows: pd.DataFrame, *, clean_path: Path = FX_CLEAN_PATH, raw_dir: Path = RAW_DIR / "fx", snapshots_dir: Path = SNAPSHOTS_DIR / "fx",
) -> FxImportCommit:
    """Merge ECB rows into the FX store: a new ECB row replaces the stored row of its day and pair."""

    stored = load_fx_rates(clean_path)
    if not stored.empty:
        new_keys = set(zip(rows["as_of_date"].astype(str), rows["pair"]))
        stored_keys = zip(pd.to_datetime(stored["as_of_date"]).dt.date.astype(str), stored["pair"])
        stored = stored.loc[[key not in new_keys for key in stored_keys]]
    merged = prefer_ecb_rates(pd.concat([stored, rows], ignore_index=True, sort=False))
    result = ProviderResult(ECB_FX_SOURCE, "fx", "ok", f"Merged {len(rows)} ECB reference rates.", merged)
    return commit_fx_import(result, clean_path=clean_path, raw_dir=raw_dir, snapshots_dir=snapshots_dir)
