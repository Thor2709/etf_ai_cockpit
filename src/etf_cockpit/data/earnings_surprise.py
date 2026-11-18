"""Analyst-free earnings information keyed to the SEC receipt time (ISSUE-0186).

``sec_receipt_time`` is the acceptance time of the first SEC filing that carries the quarter:
an 8-K with Item 2.02, else the 10-Q/10-K. It is not the public announcement time, which is
left unavailable here. ``sue_revenue`` uses the earliest-filed (originally reported) revenue
and is visible from the later of the receipt gate and the filing that holds the figure.
``filing_reaction_3s`` is the VWCE-relative return from the close before the first session
closing after the receipt (``t``) to the close of ``t+1``, visible at the open after ``t+1``.
Anything unprovable is ``unavailable`` with a reason; nothing is zero-filled.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import statistics

import exchange_calendars as xcals
import pandas as pd

from etf_cockpit.analysis.decision.rank_validation import _date_value, _forward_return
from etf_cockpit.data.bitemporal import BitemporalStore
from etf_cockpit.data.sec_pit_facts import acceptance_index, fact_known_at
from etf_cockpit.features.feature_store import FeatureDefinition, LocalFeatureStore

DATASET_ID = "earnings_information"
FEATURES = ("sue_revenue", "filing_reaction_3s")
_REVENUE_TAGS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenue")
_US = {"US", "USA", "UNITED STATES"}
_MIN_DIFFERENCES, _MAX_DIFFERENCES = 6, 8


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def _quarters(companyfacts: dict, acceptances: dict) -> list[dict]:
    """Earliest-filed discrete quarters (Q4 = FY - 9M), oldest first; filing order is filed date, acceptance time, accession, tag rank."""
    earliest: dict[tuple[str, str], dict] = {}
    gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    for rank, tag in enumerate(_REVENUE_TAGS):
        for row in gaap.get(tag, {}).get("units", {}).get("USD", []):
            value = row.get("val")
            if (row.get("dimensions") or not row.get("start") or not row.get("end") or not row.get("accn")
                    or not row.get("filed") or isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                continue
            known = datetime.fromisoformat(fact_known_at(row, acceptances))
            key = (row["start"], row["end"])
            stamp = (acceptances.get(row["accn"]) or {}).get("accepted")
            order = (row["filed"], datetime.fromisoformat(stamp) if stamp else datetime.min.replace(tzinfo=timezone.utc), row["accn"], rank)
            if key not in earliest or order < earliest[key]["order"]:
                earliest[key] = {"val": value, "known": known, "accn": row["accn"], "filed": row["filed"], "order": order}
    quarters = {end: {"end": end, **row} for (start, end), row in earliest.items() if 70 <= _days(start, end) <= 110}
    for (start, end), annual in earliest.items():
        if end in quarters or not 330 <= _days(start, end) <= 380:
            continue
        nine = [row for (s, e), row in earliest.items()
                if s == start and e < end and 240 <= _days(s, e) <= 290 and 70 <= (date.fromisoformat(end) - date.fromisoformat(e)).days <= 110]
        if len(nine) == 1:
            quarters[end] = {"end": end, "val": annual["val"] - nine[0]["val"], "known": max(annual["known"], nine[0]["known"]),
                             "accn": annual["accn"], "filed": max(annual["filed"], nine[0]["filed"])}
    return [quarters[end] for end in sorted(quarters)]


def _receipt(quarter: dict, tables: list[dict], acceptances: dict) -> tuple[datetime, datetime, str]:
    """(sec_receipt_time, availability gate, source) of the first filing that carries the quarter."""
    candidates = []
    for table in tables:
        for accn, form, items in zip(table.get("accessionNumber", []), table.get("form", []), table.get("items", [])):
            entry = acceptances.get(accn)
            if (form == "8-K" and "2.02" in str(items).split(",") and entry and entry["accepted"]
                    and quarter["end"] < entry["filed"] <= quarter["filed"]):
                candidates.append((datetime.fromisoformat(entry["accepted"]), accn, entry["filed"]))
    if candidates:
        accepted, accn, filed = min(candidates)
        return accepted, datetime.fromisoformat(fact_known_at({"filed": filed, "accn": accn}, acceptances)), "8-K item 2.02"
    entry = acceptances.get(quarter["accn"])
    accepted = datetime.fromisoformat(entry["accepted"]) if entry and entry["accepted"] else quarter["known"]
    return accepted, quarter["known"], "periodic filing"


def _sue(quarters: list[dict], index: int, receipt: datetime) -> dict:
    def seasonal(position: int) -> float | None:
        if position < 4:
            return None
        now, before = quarters[position], quarters[position - 4]
        if not 350 <= (date.fromisoformat(now["end"]) - date.fromisoformat(before["end"])).days <= 380:
            return None
        if (position != index and now["known"] >= receipt) or before["known"] >= receipt:
            return None
        return now["val"] - before["val"]

    current = seasonal(index)
    history = [d for d in (seasonal(p) for p in range(max(0, index - _MAX_DIFFERENCES), index)) if d is not None]
    if len(history) < _MIN_DIFFERENCES:
        return {"status": "unavailable", "reason": "fewer_than_6_seasonal_differences"}
    if current is None:
        return {"status": "unavailable", "reason": "seasonal_pair_missing"}
    dispersion = statistics.stdev(history)
    if dispersion <= 0:
        return {"status": "unavailable", "reason": "zero_seasonal_dispersion"}
    return {"status": "available", "value": current / dispersion,
            "inputs": {"seasonal_difference": current, "std": dispersion, "n_differences": len(history)}}


def _reaction(instrument_id: str, receipt: datetime, exact_acceptance: bool, prices: pd.DataFrame, benchmark: pd.DataFrame) -> dict:
    if not exact_acceptance:
        return {"status": "unavailable", "reason": "sec_acceptance_time_unknown"}
    day = receipt.date()
    schedule = xcals.get_calendar("XETR", start=str(day - timedelta(days=10)), end=str(day + timedelta(days=20))).schedule
    after = (schedule["close"] > pd.Timestamp(receipt)).to_numpy().nonzero()[0]
    if len(after) == 0 or after[0] < 1 or after[0] + 2 >= len(schedule):
        return {"status": "unavailable", "reason": "trading_window_unavailable"}
    first = int(after[0])
    entry_day, target_day = schedule.index[first - 1].date(), schedule.index[first + 1].date()
    available_at = schedule["open"].iloc[first + 2]
    benchmark = benchmark.assign(instrument_id="VWCE")
    returns = []
    for frame, name in ((prices, instrument_id), (benchmark, "VWCE")):
        closes = pd.to_numeric(frame.loc[frame["instrument_id"].astype(str).eq(name) & frame["date"].map(_date_value).eq(entry_day), "adjusted_close"], errors="coerce")
        if not (closes.map(math.isfinite) & closes.gt(0)).any():
            return {"status": "unavailable", "reason": f"{name}:entry_close_missing"}
        value, status = _forward_return(frame, name, schedule["close"].iloc[first - 1], 2,
                                        target_session=target_day, outcome_known_by=available_at)
        if value is None:
            return {"status": "unavailable", "reason": f"{name}:{status}"}
        returns.append(value)
    return {"status": "available", "value": returns[0] - returns[1], "available_at": available_at.isoformat(),
            "inputs": {"stock_return": returns[0], "benchmark_return": returns[1], "t": schedule.index[first].date().isoformat()}}


def compute_earnings_events(
    instrument_id: str, companyfacts: dict, submissions: dict, prices: pd.DataFrame, benchmark_prices: pd.DataFrame,
    *, country: str | None, historical_pages: list[dict] = (),
) -> dict:
    """One event per quarter with both features; ``prices`` and ``benchmark_prices`` are adjusted EUR."""
    if str(country or "").strip().upper() not in _US:
        return {"status": "unavailable", "reason": "non_us_issuer", "events": []}
    acceptances = acceptance_index(submissions, list(historical_pages))
    tables = [submissions.get("filings", {}).get("recent", {}), *historical_pages]
    quarters = _quarters(companyfacts, acceptances)
    events = []
    for index, quarter in enumerate(quarters):
        receipt, gate, source = _receipt(quarter, tables, acceptances)
        sue = _sue(quarters, index, receipt)
        exact = source == "8-K item 2.02" or bool((acceptances.get(quarter["accn"]) or {}).get("accepted"))
        if sue["status"] == "available":
            sue["available_at"] = max(gate, quarter["known"]).isoformat()
        events.append({
            "quarter_end": quarter["end"], "sec_receipt_time": receipt.isoformat(), "receipt_source": source,
            "exact_acceptance": exact,
            "features": {"sue_revenue": sue, "filing_reaction_3s": _reaction(instrument_id, receipt, exact, prices, benchmark_prices)},
        })
    return {"status": "available" if events else "unavailable", "reason": None if events else "no_quarterly_revenue", "events": events}


def record_earnings_events(store: BitemporalStore, instrument_id: str, events: list[dict], *, run_id: str) -> None:
    """Append available features as observed rows; rows already stored are skipped."""
    stored = {item.stable_id for item in store.observations(DATASET_ID, entity_id=instrument_id)}
    for event in events:
        for feature, result in event["features"].items():
            stable_id = f"{event['quarter_end']}:{feature}"
            if result["status"] != "available" or stable_id in stored:
                continue
            value = {"feature": feature, "value": result["value"], "event_key": event["quarter_end"],
                     "event_definition": "sec_receipt", "sec_receipt_time": event["sec_receipt_time"],
                     "public_announcement_time": "unavailable", "pit_grade": "observed", "inputs": result["inputs"]}
            store.record_observation(
                dataset_id=DATASET_ID, entity_id=instrument_id, stable_id=stable_id, value=value,
                source_id="sec_receipt", source_checksum=hashlib.sha256(
                    json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
                revision=1, valid_from=event["sec_receipt_time"], published_at=event["sec_receipt_time"],
                observed_at=event["sec_receipt_time"], available_at=result["available_at"], run_id=run_id,
                availability_confidence="exact" if event["exact_acceptance"] else "inferred",
            )


def earnings_information_features(store: BitemporalStore, feature_store: LocalFeatureStore, instrument_id: str) -> pd.DataFrame:
    """Register the features and return panel input rows; one row per event and availability time."""
    for feature in FEATURES:
        feature_store.register_feature(FeatureDefinition(
            feature, feature, units="ratio" if feature.startswith("sue") else "decimal", source_dataset=DATASET_ID))
    rows: dict[tuple[str, str], dict] = {}
    known: dict[str, dict] = {}
    for item in sorted(store.observations(DATASET_ID, entity_id=instrument_id), key=lambda o: o.available_at):
        if item.status != "active":
            continue
        event = item.value["event_key"]
        known.setdefault(event, {name: None for name in FEATURES})[item.value["feature"]] = item.value["value"]
        rows[(event, item.available_at)] = {
            "instrument_id": instrument_id, "date": item.valid_from[:10], "available_at": item.available_at,
            "pit_grade": item.value["pit_grade"], **known[event],
        }
    return pd.DataFrame(list(rows.values()), columns=["instrument_id", "date", "available_at", "pit_grade", *FEATURES])
