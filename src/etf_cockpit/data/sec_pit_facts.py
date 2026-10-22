"""SEC companyfacts selection with explicit publication knowledge.

No frames, fiscal-year labels or acquisition times are used as filing evidence.
Date-only filed evidence is gated at end of that day in America/New_York.
An acceptance later than 17:30 ET is gated at next CALENDAR day midnight ET
(no trading-calendar assumption). Missing acceptance falls back to filed only
unless require_acceptance=True. Malformed joined evidence fails closed.

The configured tag specs declare unit and instant/cumulative duration shape.
Direct and cumulative durations must not compete for the same (tag,end,fp):
ambiguous values/units/durations raise rather than winning by input order.
Q4 needs a common fiscal start, FY and 9M, matching units and a quarter-sized
remainder. No zero filling or multi-class shares aggregation is permitted.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import math
from zoneinfo import ZoneInfo

from etf_cockpit.data.sp500_history import knowledge

ET = ZoneInfo("America/New_York")
_DURATIONS = {"Q1": (70, 110), "Q2": (150, 200), "Q3": (240, 290), "FY": (330, 380)}


def acceptance_index(submissions: dict, historical_pages: list[dict] = ()) -> dict:
    """Join recent and archived parallel-array submissions by accession number."""
    result = {}
    tables = [submissions.get("filings", {}).get("recent", {})] + list(historical_pages)
    for table in tables:
        if not isinstance(table, dict):
            raise ValueError("unexpected submissions filing table")
        accessions = table.get("accessionNumber", [])
        filed = table.get("filingDate", [])
        accepted = table.get("acceptanceDateTime")
        if not isinstance(accessions, list) or not isinstance(filed, list) or len(accessions) != len(filed):
            raise ValueError("submissions parallel-array length mismatch")
        if accepted is None:
            accepted = [None] * len(accessions)
        if not isinstance(accepted, list) or len(accepted) != len(accessions):
            raise ValueError("submissions acceptance array length mismatch")
        for accession, filing, stamp in zip(accessions, filed, accepted):
            date.fromisoformat(filing)
            if not isinstance(accession, str) or not accession:
                raise ValueError("missing submissions accession")
            entry = {"filed": filing, "accepted": knowledge(stamp) if stamp else None}
            if stamp and len(stamp) == 10:
                raise ValueError("acceptanceDateTime must be a zoned timestamp")
            if accession in result and result[accession] != entry:
                raise ValueError("conflicting accession acceptance evidence")
            result[accession] = entry
    return result


def fact_known_at(row: dict, acceptances: dict, *, require_acceptance: bool = False) -> str:
    filed = date.fromisoformat(row["filed"])
    evidence = acceptances.get(row.get("accn"))
    if evidence and evidence["filed"] != row["filed"]:
        raise ValueError("companyfacts/submissions filingDate disagreement")
    if evidence and evidence["accepted"]:
        accepted = datetime.fromisoformat(evidence["accepted"]).astimezone(ET)
        gate = accepted
        if accepted.time().replace(tzinfo=None) > time(17, 30):
            gate = datetime.combine(accepted.date() + timedelta(days=1), time.min, ET)
        gate = max(gate, datetime.combine(filed, time.min, ET))
    elif require_acceptance:
        raise ValueError("acceptanceDateTime unavailable for fact")
    else:
        gate = datetime.combine(filed, time.max, ET)
    return gate.astimezone(timezone.utc).isoformat()


def select_facts(companyfacts: dict, as_of: str, *, specs: dict, submissions: dict | None = None,
                 historical_pages: list[dict] = (), require_acceptance: bool = False,
                 derive_q4: bool = True, skipped: dict | None = None) -> list[dict]:
    """Latest filed visible value per (namespace:tag, end, fp, start), plus optional Q4.

    ``specs`` maps ``namespace:tag`` to ``{unit, kind: instant|duration}``.
    Tags outside specs are deliberately out of scope, never guessed.
    By default any unprovable fact raises. With a ``skipped`` dict (explicit opt-in)
    each per-fact evidence problem instead drops that fact and is counted by reason
    (live data: 8-K/prospectus facts carry no fp, a few share counts are zero);
    unit mismatches and malformed container shapes still raise.
    """
    def reject(reason: str, message: str) -> None:
        if skipped is None:
            raise ValueError(message)
        skipped[reason] = skipped.get(reason, 0) + 1

    cutoff = datetime.fromisoformat(knowledge(as_of))
    acceptances = acceptance_index(submissions or {}, historical_pages)
    facts = companyfacts.get("facts")
    if not isinstance(facts, dict) or not specs:
        raise ValueError("companyfacts facts/specs unavailable")
    grouped = defaultdict(list)
    for tag, spec in sorted(specs.items()):
        namespace, concept = tag.split(":", 1)
        if spec.get("kind") not in {"instant", "duration"} or not spec.get("unit"):
            raise ValueError("tag needs explicit unit and duration kind")
        item = facts.get(namespace, {}).get(concept)
        if item is None:
            continue
        units = item.get("units")
        if not isinstance(units, dict):
            raise ValueError("unexpected companyfacts units shape")
        for unit, rows in units.items():
            if not isinstance(rows, list):
                raise ValueError("unexpected companyfacts rows shape")
            for raw in rows:
                if not isinstance(raw, dict):
                    raise ValueError("unexpected companyfacts row")
                try:
                    filed, end = date.fromisoformat(raw["filed"]), date.fromisoformat(raw["end"])
                    known = fact_known_at(raw, acceptances, require_acceptance=require_acceptance)
                except (KeyError, TypeError) as exc:
                    if skipped is None:
                        raise ValueError("fact lacks provable filed/end/known_at") from exc
                    reject("fact_lacks_filed_end", "")
                    continue
                except ValueError as exc:
                    if skipped is None:
                        raise
                    reject("known_at_unprovable", str(exc))
                    continue
                if filed > cutoff.astimezone(ET).date() or datetime.fromisoformat(known) > cutoff:
                    continue
                if end > filed or not raw.get("accn") or raw.get("dimensions"):
                    reject("invalid_period_accession_dimensions", "invalid fact period/accession/dimensions")
                    continue
                value = raw.get("val")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    reject("non_finite_value", "fact is not a finite reported number")
                    continue
                fp = raw.get("fp")
                if fp not in _DURATIONS:
                    reject("unsupported_fp", "unsupported fact fp")
                    continue
                start = raw.get("start")
                duration = None
                if spec["kind"] == "duration":
                    if not start:
                        reject("duration_without_start", "duration fact lacks start")
                        continue
                    duration = (end - date.fromisoformat(start)).days + 1
                elif start:
                    reject("instant_with_duration", "instant fact has a duration")
                    continue
                # Live filings report the discrete quarter and the cumulative year-to-date
                # value under the same end/fp; the start date is part of the fact identity.
                grouped[(tag, end.isoformat(), fp, start)].append({
                    "tag": tag, "end": end.isoformat(), "fp": fp, "start": start,
                    "unit": unit, "val": value, "filed": filed.isoformat(), "accn": raw["accn"],
                    "known_at": known, "period_days": duration, "derived": False,
                })
    selected = []
    for (tag, end, fp, _start), rows in sorted(grouped.items(), key=lambda item: tuple(str(part) for part in item[0])):
        latest = max((row["filed"], row["known_at"]) for row in rows)
        winners = [row for row in rows if (row["filed"], row["known_at"]) == latest]
        signatures = {(row["val"], row["unit"], row["start"]) for row in winners}
        if len(signatures) != 1:
            reject("conflicting_values_same_filing", f"conflicting values/units/durations: {tag}/{end}/{fp}")
            continue
        winner = min(winners, key=lambda row: row["accn"])
        spec = specs[tag]
        if winner["unit"] != spec["unit"]:
            raise ValueError(f"unit mismatch: {tag}")
        # fp names the filing, not the period: quarter, year-to-date and annual lengths all occur.
        if spec["kind"] == "duration" and not any(low <= winner["period_days"] <= high for low, high in _DURATIONS.values()):
            reject("duration_out_of_range", f"duration mismatch: {tag}/{fp}")
            continue
        if tag == "dei:EntityCommonStockSharesOutstanding" and winner["val"] <= 0:
            reject("nonpositive_shares", "nonpositive reported shares")
            continue
        selected.append(winner)
    if derive_q4:
        quarters = []
        for annual in selected:
            if annual["fp"] != "FY" or annual["start"] is None:
                continue
            candidates = [row for row in selected if row["tag"] == annual["tag"] and row["fp"] == "Q3"
                          and row["start"] == annual["start"] and row["end"] < annual["end"]]
            if not candidates:
                continue
            if len(candidates) != 1:
                raise ValueError("ambiguous 9M leg for Q4")
            nine = candidates[0]
            days = (date.fromisoformat(annual["end"]) - date.fromisoformat(nine["end"])).days
            if nine["unit"] != annual["unit"] or not 70 <= days <= 110:
                raise ValueError("Q4 unit/duration mismatch")
            value = annual["val"] - nine["val"]
            if not math.isfinite(value):
                raise ValueError("non-finite derived Q4")
            quarters.append({**annual, "fp": "Q4", "val": value,
                             "start": (date.fromisoformat(nine["end"]) + timedelta(days=1)).isoformat(),
                             "period_days": days, "known_at": max(annual["known_at"], nine["known_at"]),
                             "filed": max(annual["filed"], nine["filed"]),
                             "accn": annual["accn"] + "+" + nine["accn"], "derived": True})
        selected.extend(quarters)
    return sorted(selected, key=lambda row: (row["tag"], row["end"], row["fp"]))
