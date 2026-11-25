"""ECB euro overnight cash rates and the forward cash return of rank validation (train E1).

Rates: EONIA (``EON/D.EONIA_TO.RATE``) before 2019-10-01, the euro short-term rate €STR (``EST/B.EU000A2X2A25.WT``)
from 2019-10-01; each row names its source. A rate is available at its ECB publication: €STR of day t at 08:00
Frankfurt time on the next TARGET day (the next €STR row), EONIA of day t on day t at 19:00 Frankfurt time. A rate
fetched before that time (or the last €STR row, whose next TARGET day is not yet known) is available at its fetch time.

Cash return: an overnight rate (percent, ACT/360) applies from its day until the next rate day; the forward return of
a decision date compounds those rates over the calendar days from the decision date to the session that ends the
holding period. A rate gap longer than any TARGET closure, or a series that stops inside the window, gives no row.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Sequence
import csv
from datetime import date, datetime
import hashlib
import io
import json
from pathlib import Path

import pandas as pd

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group
from etf_cockpit.data.fx_data import LIVE_INGESTION
from etf_cockpit.data.macro_warehouse import fetch_bytes, fetch_time, legal_terms_block
from etf_cockpit.data.provenance import sha256_dataframe

ESTR_START = date(2019, 10, 1)
SERIES = {"eonia": ("EON", "D.EONIA_TO.RATE"), "estr": ("EST", "B.EU000A2X2A25.WT")}
_STARTS = {"eonia": date(1999, 1, 1), "estr": ESTR_START}
_URL = "https://data-api.ecb.europa.eu/service/data/{flow}/{key}?startPeriod={start}&format=csvdata"
_BASIS = {"eonia": "eonia_same_day_publication", "estr": "estr_next_target_day_publication"}
CASH_RATES_FILE = "ecb_overnight_rates"  # <root>/data/reference/<name>.parquet + .json manifest
# The longest TARGET closure (Good Friday + Easter Monday) puts 5 calendar days between two rate days.
MAX_RATE_GAP_DAYS = 5
_COLUMNS = ["rate_date", "rate_pct", "source", "provider_symbol", "ingested_at", "available_at", "availability_basis"]


def parse_ecb_rate_csv(content: bytes, *, source: str, fetched_at: datetime) -> pd.DataFrame:
    """Rate rows from an ECB ``csvdata`` payload of ``source`` (eonia or estr); a blank value is skipped, never filled."""

    flow, key = SERIES[source]
    fetched = pd.Timestamp(fetch_time(fetched_at))
    rows = []
    for row in csv.DictReader(io.StringIO(content.decode("utf-8-sig"))):
        if row["KEY"].strip() != f"{flow}.{key}":
            raise ValueError(f"not the {source} series: {row['KEY'].strip()}")
        value = (row["OBS_VALUE"] or "").strip()
        if value:
            rows.append({"rate_date": date.fromisoformat(row["TIME_PERIOD"].strip()), "rate_pct": float(value)})
    frame = pd.DataFrame(rows, columns=["rate_date", "rate_pct"]).sort_values("rate_date", ignore_index=True)
    if frame["rate_date"].duplicated().any():
        raise ValueError(f"duplicate {source} rate days")
    frame = frame.loc[frame["rate_date"].le(fetched.date())].reset_index(drop=True)
    frame["source"] = source
    frame["provider_symbol"] = f"{flow}.{key}"
    day = pd.to_datetime(frame["rate_date"])
    if source == "estr":  # published on the next TARGET day = the next row; the last row's day is not yet known
        published = (day.shift(-1) + pd.Timedelta(hours=8)).dt.tz_localize("Europe/Berlin").dt.tz_convert("UTC")
    else:
        published = (day + pd.Timedelta(hours=19)).dt.tz_localize("Europe/Berlin").dt.tz_convert("UTC")
    live = published.isna() | published.gt(fetched)
    frame["ingested_at"] = fetched
    frame["available_at"] = published.where(~live, fetched)
    frame["availability_basis"] = pd.Series(_BASIS[source], index=frame.index).where(~live, LIVE_INGESTION)
    return frame[_COLUMNS]


def splice_overnight_rates(eonia: pd.DataFrame, estr: pd.DataFrame) -> pd.DataFrame:
    """EONIA rows before 2019-10-01, €STR rows from 2019-10-01."""

    parts = [eonia.loc[eonia["rate_date"].lt(ESTR_START)], estr.loc[estr["rate_date"].ge(ESTR_START)]]
    return pd.concat(parts, ignore_index=True)[_COLUMNS]


def fetch_overnight_rates(root: Path, *, transport: Callable[[str], bytes] | None = None) -> Path:
    """Fetch EONIA and €STR, splice them and write them with a sha256 manifest under ``root``/data/reference."""

    blocked = legal_terms_block("ecb")
    if blocked:
        raise ValueError(f"ECB cash rates blocked: {blocked}")
    fetched = fetch_time(None)
    parsed, series = {}, {}
    for source, (flow, key) in SERIES.items():
        url = _URL.format(flow=flow, key=key, start=_STARTS[source].isoformat())
        payload = transport(url) if transport else fetch_bytes(url, {"User-Agent": "ETF AI Evidence Cockpit/1.0", "Accept": "text/csv"})
        parsed[source] = parse_ecb_rate_csv(payload, source=source, fetched_at=fetched)
        series[source] = {"url": url, "payload_sha256": hashlib.sha256(payload).hexdigest()}
    rates = splice_overnight_rates(parsed["eonia"], parsed["estr"])
    if rates.empty:
        raise ValueError("the ECB returned no overnight rates")
    buffer = io.BytesIO()
    rates.to_parquet(buffer, index=False)
    manifest = {
        "sha256": sha256_dataframe(rates), "rows": len(rates), "series": series, "split_date": ESTR_START.isoformat(),
        "first_date": rates["rate_date"].min().isoformat(), "last_date": rates["rate_date"].max().isoformat(),
        "fetched_at": pd.Timestamp(fetched).isoformat(), "attribution": "Source: ECB.", "execution_allowed": False,
    }
    reference = Path(root) / "data" / "reference"
    reference.mkdir(parents=True, exist_ok=True)
    parquet, sidecar = reference / f"{CASH_RATES_FILE}.parquet", reference / f"{CASH_RATES_FILE}.json"
    atomic_write_group([
        AtomicWriteRequest(parquet, buffer.getvalue(), lambda path: pd.read_parquet(path)),
        AtomicWriteRequest(sidecar, json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
                           lambda path: json.loads(path.read_text(encoding="utf-8"))),
    ])
    return parquet


def forward_cash_returns(rates: pd.DataFrame, sessions: Sequence[date], holding_period_sessions: int) -> pd.DataFrame:
    """``decision_date, net_return, source`` per session with a full holding period of later sessions.

    The window runs from the decision session to the ``holding_period_sessions``-th later session, as rank validation's
    forward return. Each overnight rate accrues ``rate/100 * days/360`` over the calendar days it applies in the window.
    """

    ordered = rates.sort_values("rate_date", ignore_index=True)
    days = [pd.Timestamp(item).date() for item in ordered["rate_date"]]
    values = ordered["rate_pct"].astype(float).tolist()
    sources = ordered["source"].astype(str).tolist()
    calendar = sorted(set(sessions))
    rows = []
    for position, decision in enumerate(calendar[: max(len(calendar) - holding_period_sessions, 0)]):
        end = calendar[position + holding_period_sessions]
        index = bisect_right(days, decision) - 1
        growth, cursor, used = 1.0, decision, set()
        while index >= 0 and cursor < end:
            if index + 1 >= len(days) or (days[index + 1] - days[index]).days > MAX_RATE_GAP_DAYS:
                break  # the series stops or has a gap inside the window
            stop = min(days[index + 1], end)
            growth *= 1.0 + values[index] / 100.0 * (stop - cursor).days / 360.0
            used.add(sources[index])
            cursor, index = stop, index + 1
        if index >= 0 and cursor == end:
            rows.append({"decision_date": decision.isoformat(), "net_return": growth - 1.0, "source": "+".join(sorted(used))})
    return pd.DataFrame(rows, columns=["decision_date", "net_return", "source"])
