"""ECB data API provider for policy and money-market rates and euro reference exchange rates.

The API serves current values without vintage history, so every stored row is known only from
the fetch time (``availability_confidence="inferred"``) and is barred from historical features.
"""

from __future__ import annotations

from collections.abc import Callable
import csv
from datetime import date, datetime
import hashlib
import io

from etf_cockpit.data.macro_warehouse import (
    FETCH_ERRORS,
    MacroFetchResult,
    MacroObservation,
    MacroWarehouseError,
    fetch_bytes,
    fetch_time,
    legal_terms_block,
)

_BASE = "https://data-api.ecb.europa.eu/service/data"
_FREQUENCY = {"D": "daily", "B": "daily", "M": "monthly", "A": "annual"}


class EcbProvider:
    name = "ecb"

    def __init__(self, transport: Callable[[str], bytes] | None = None) -> None:
        self.transport = transport

    def fetch(self, dataflow: str, key: str, *, fetched_at: datetime | None = None) -> MacroFetchResult:
        """Fetch one ECB series key, for example ``EXR`` with ``D.USD.EUR.SP00.A``."""

        blocked = legal_terms_block("ecb")
        if blocked:
            return MacroFetchResult.unavailable(blocked)
        url = f"{_BASE}/{dataflow}/{key}?format=csvdata"
        try:
            payload = self.transport(url) if self.transport else fetch_bytes(
                url, {"User-Agent": "ETF AI Evidence Cockpit/1.0", "Accept": "text/csv"}
            )
            known_at = fetch_time(fetched_at)  # taken after the response arrived, never before
            rows = parse_ecb_csv(payload, fetched_at=known_at)
        except FETCH_ERRORS as exc:
            return MacroFetchResult.unavailable(f"ECB fetch failed: {type(exc).__name__}.")
        if not rows:
            return MacroFetchResult.unavailable("ECB returned no usable observations.")
        return MacroFetchResult("available", tuple(rows))


def _unit(row: dict[str, str]) -> str:
    denominator = (row.get("CURRENCY_DENOM") or "").strip()
    if denominator:
        return f"{row['CURRENCY'].strip()}_per_{denominator}"
    if (row.get("UNIT") or "").strip() == "PCPA":
        return "percent"
    raise MacroWarehouseError("unsupported ECB unit")


def parse_ecb_csv(content: bytes, *, fetched_at: datetime) -> list[MacroObservation]:
    """Parse an ECB ``csvdata`` payload; a blank value is skipped, never filled."""

    checksum = hashlib.sha256(content).hexdigest()
    observed: list[MacroObservation] = []
    for row in csv.DictReader(io.StringIO(content.decode("utf-8-sig"))):
        if not (row["OBS_VALUE"] or "").strip():
            continue
        key = row["KEY"].strip()
        period = row["TIME_PERIOD"].strip()
        period = {4: f"{period}-01-01", 7: f"{period}-01"}.get(len(period), period)
        if date.fromisoformat(period) > fetched_at.date():
            continue  # effective after the fetch (an announced rate); a later refresh picks it up
        observed.append(MacroObservation(
            dataset_id=f"ecb:{key}",
            series_id=key,
            period_start=period,
            value=float(row["OBS_VALUE"]),
            unit=_unit(row),
            frequency=_FREQUENCY[row["FREQ"].strip()],
            country="EA",
            currency=row["CURRENCY"].strip(),
            source_id=f"ecb:{key}:{fetched_at:%Y%m%dT%H%M%SZ}",
            source_authority="official_api",
            source_checksum=checksum,
            source_terms="ecb",
            methodology="ECB data API csvdata; no vintage history, so known only from the fetch time.",
            published_at=fetched_at.isoformat(),
            available_at=fetched_at.isoformat(),
            observed_at=period,
            ingested_at=fetched_at.isoformat(),
            availability_confidence="inferred",
        ))
    return observed


__all__ = ["EcbProvider", "parse_ecb_csv"]
