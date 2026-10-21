"""Point-in-time audit of the backfilled fundamentals history, using the canonical readers.

For every decision date (default: weekly, 2022-10-17 .. 2026-10-09, decided at the end of that UTC day exactly as
``live_decision_time`` does) it asks the same selectors the score uses what is visible and fails when any fact that is
visible carries a ``known_at`` after the decision time. It additionally checks the knowledge times themselves:

* ``known_at`` parses and is not before the period it describes ends;
* ESEF facts are stamped with the registry ``date_added`` of their own filing, never with the import time;
* no restated, fetch-dated source (yfinance) is present in a store that is meant to be history.

Exit code 1 when any violation exists. Reads only; writes nothing except the optional JSON report.

Usage: python scripts/pit_history_check.py --root PATH [--start 2022-10-17 --end 2026-10-09 --step-days 7] [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT))

DEFAULT_START = date(2022, 10, 17)
DEFAULT_END = date(2026, 10, 9)
FETCH_DATED_SOURCES = frozenset({"yfinance"})


def decision_dates(start: date, end: date, step_days: int = 7) -> list[date]:
    if step_days < 1:
        raise ValueError("step_days must be positive")
    out, current = [], start
    while current <= end:
        out.append(current)
        current += timedelta(days=step_days)
    return out


def decision_time(day: date) -> datetime:
    """End of the UTC day: the convention of ``stock_universe.live_decision_time`` for a replay date."""

    return datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc)


def _utc(value: object) -> datetime | None:
    stamp = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(stamp) else stamp.to_pydatetime()


def check_stock_store(root: Path, days: Sequence[date]) -> dict[str, object]:
    """SEC/stock periods: every version the canonical merge shows at a decision time was known by then."""

    from etf_cockpit.analysis import stock_metrics as sm
    from etf_cockpit.data import stock_fundamentals as store

    frame = store.read_fundamentals(root)
    violations: list[str] = []
    result: dict[str, object] = {"rows": int(len(frame)), "instruments": 0, "decision_dates": len(days), "violations": violations}
    if frame.empty:
        result["note"] = "no stock_fundamentals rows"
        return result
    chain = list((store.load_stock_config(root).get("sources", {}) or {}).get("chain", ["sec_edgar", "yfinance"]))
    sources = sorted({str(item) for item in frame["source"].dropna()})
    result["sources"] = sources
    for source in sources:
        if source in FETCH_DATED_SOURCES:
            violations.append(f"stock_fundamentals holds fetch-dated source {source!r}: restated values must not be history")
    for row in frame.itertuples():
        known, end = _utc(row.known_at), _utc(row.period_end)
        if known is None:
            violations.append(f"{row.instrument_id} {row.period_end} {row.period_type}: unparseable known_at {row.known_at!r}")
        elif end is not None and str(row.period_type) in {"FY", "Q"} and known.date() < end.date():
            violations.append(f"{row.instrument_id} {row.period_end} {row.period_type}: known_at {known.date()} precedes the period end")
    result["instruments"] = int(frame["instrument_id"].nunique())
    for instrument_id in sorted({str(item) for item in frame["instrument_id"]}):
        periods = store.periods_for(instrument_id, frame, chain)
        for day in days:
            moment = decision_time(day)
            for period in sm.known_periods(periods, moment):
                if period.known_at > moment:
                    violations.append(f"{instrument_id} {day}: period {period.period_end} known_at {period.known_at} after the decision")
                for key, value in period.values.items():
                    if key.startswith("_") and key.endswith("_known_at"):
                        field_known = _utc(value)
                        if field_known is None or field_known > moment:
                            violations.append(f"{instrument_id} {day}: {key}={value} after the decision")
    return result


def _manifest_dates(manifest_path: Path) -> dict[str, set[datetime]]:
    """instrument id -> every registry ``date_added`` (UTC instant) of its filings."""

    if not manifest_path.is_file():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    out: dict[str, set[datetime]] = {}
    for instrument_id, entry in (payload.get("manifest") or {}).items():
        stamps = {_utc(item.get("date_added")) for item in entry.get("filings", [])}
        out[instrument_id] = {stamp for stamp in stamps if stamp is not None}
    return out


def check_statement_frame(
    frame: pd.DataFrame, allowed_dates: Mapping[str, set[datetime]], days: Sequence[date], *, label: str
) -> dict[str, object]:
    """ESEF statement facts: known_at == the registry date_added of an own filing; visible facts are known."""

    violations: list[str] = []
    result: dict[str, object] = {"store": label, "rows": int(len(frame)), "violations": violations}
    if frame.empty:
        return result
    known = pd.to_datetime(frame["known_at"], errors="coerce", utc=True)
    available = pd.to_datetime(frame["available_at"], errors="coerce", utc=True) if "available_at" in frame else known
    effective = pd.to_datetime(frame["effective_at"], errors="coerce", utc=True) if "effective_at" in frame else pd.Series(pd.NaT, index=frame.index)
    for position in range(len(frame)):
        instrument_id = str(frame["instrument_id"].iloc[position])
        stamp = known.iloc[position]
        if pd.isna(stamp):
            violations.append(f"{instrument_id}: unparseable known_at (a column mixing timestamp shapes loses rows to NaT)")
            continue
        if not pd.isna(available.iloc[position]) and available.iloc[position] != stamp:
            violations.append(f"{instrument_id}: available_at differs from known_at")
        if not pd.isna(effective.iloc[position]) and stamp.date() < effective.iloc[position].date():
            violations.append(f"{instrument_id}: known_at {stamp.date()} precedes effective_at {effective.iloc[position].date()}")
        permitted = allowed_dates.get(instrument_id)
        if permitted is not None and stamp.to_pydatetime() not in permitted:
            violations.append(f"{instrument_id}: known_at {stamp.isoformat()} is not a registry date_added of this issuer (import-time stamp?)")
    for day in days:
        moment = pd.Timestamp(decision_time(day))
        visible = known[known <= moment]
        if (visible > moment).any():  # pragma: no cover - defensive; the comparison above cannot produce it
            violations.append(f"{day}: visible fact after the decision")
    result["first_known_at"] = None if known.dropna().empty else known.min().isoformat()
    result["last_known_at"] = None if known.dropna().empty else known.max().isoformat()
    return result


def probe_days(days: Sequence[date], stamps: Iterable[datetime]) -> list[date]:
    """The decision days on each side of every knowledge time (the only days where visibility can change), plus the ends."""

    chosen: set[date] = {days[0], days[-1]} if days else set()
    for stamp in stamps:
        day = stamp.date()
        before = [item for item in days if item < day]
        after = [item for item in days if item >= day]
        if before:
            chosen.add(before[-1])
        if after:
            chosen.add(after[0])
    return sorted(chosen)


def check_norway_evidence(root: Path, days: Sequence[date], allowed_dates: Mapping[str, set[datetime]]) -> dict[str, object]:
    """Bank evidence directories read through the scorecard's own selectors."""

    from etf_cockpit.application import financial_institution_views as fiv

    violations: list[str] = []
    stores: list[dict[str, object]] = []
    base = root / "evidence" / "norway"
    ids: set[str] = set()
    if base.is_dir():
        ids = {item.name.rsplit("-", 1)[0] for item in base.iterdir() if item.is_dir() and item.name.endswith("-history")}
    for instrument_id in sorted(ids):
        frame = fiv._read_financial_statement_frame(root, instrument_id=instrument_id)
        stores.append({**check_statement_frame(frame, allowed_dates, days, label=f"evidence/norway/{instrument_id}-history"), "instrument_id": instrument_id})
        payload = fiv._read_json_artifact(root, "ec_facts.json", instrument_id=instrument_id) or {}
        for revision in payload.get("revisions", []) or []:
            stamp = _utc(revision.get("known_at"))
            if stamp is None:
                violations.append(f"{instrument_id}: EC revision without known_at")
            elif allowed_dates.get(instrument_id) is not None and stamp not in allowed_dates[instrument_id]:
                violations.append(f"{instrument_id}: EC revision known_at {stamp.isoformat()} is not a registry date_added")
        stamps = [stamp for stamp in (_utc(value) for value in frame["known_at"]) if stamp is not None] if not frame.empty else []
        stamps += [stamp for stamp in (_utc(item.get("known_at")) for item in payload.get("revisions", []) or []) if stamp is not None]
        for day in probe_days(days, stamps):
            moment = decision_time(day)
            selected = fiv._select_ec_revision(payload, instrument_id, moment) if payload else {}
            stamp = _utc(selected.get("known_at")) if selected else None
            if stamp is not None and stamp > moment:
                violations.append(f"{instrument_id} {day}: EC revision known_at {stamp} after the decision")
            for row in fiv._financial_rows_for_instrument(frame, instrument_id, moment):
                if row["_known"].to_pydatetime() > moment:
                    violations.append(f"{instrument_id} {day}: statement fact known_at after the decision")
    for store in stores:
        violations.extend(str(item) for item in store["violations"])  # type: ignore[union-attr]
    return {"instruments": len(ids), "stores": [{k: v for k, v in s.items() if k != "violations"} for s in stores], "violations": violations}


def run_checks(root: Path, days: Sequence[date]) -> dict[str, object]:
    root = Path(root)
    allowed = _manifest_dates(root / "data" / "pit_history" / "esef_manifest.json")
    report: dict[str, object] = {
        "root": str(root),
        "first_decision_date": days[0].isoformat() if days else None,
        "last_decision_date": days[-1].isoformat() if days else None,
        "decision_dates": len(days),
        "decision_time_convention": "end of the UTC decision day (23:59:59), as stock_universe.live_decision_time",
    }
    report["stock_fundamentals"] = check_stock_store(root, days)
    statements_path = root / "data" / "clean" / "statement_facts.parquet"
    statements = pd.read_parquet(statements_path) if statements_path.is_file() else pd.DataFrame()
    report["statement_facts"] = check_statement_frame(statements, allowed, days, label="data/clean/statement_facts.parquet")
    report["norway_evidence"] = check_norway_evidence(root, days, allowed)
    violations: list[str] = []
    for key in ("stock_fundamentals", "statement_facts", "norway_evidence"):
        violations.extend(str(item) for item in report[key]["violations"])  # type: ignore[index]
    report["violation_count"] = len(violations)
    report["violations_sample"] = violations[:50]
    report["passed"] = not violations
    return report


def _registry_counts(manifest: Mapping[str, object], instrument_id: str) -> tuple[str, int, str]:
    entry = (manifest.get("manifest") or {}).get(instrument_id) or {}  # type: ignore[union-attr]
    return str(entry.get("lei") or ""), len(entry.get("filings") or []), str(entry.get("reason") or "")


def _first_decision_on_or_after(day: date, days: Sequence[date]) -> str:
    return next((item.isoformat() for item in days if item >= day), "")


def build_coverage(root: Path, audit_csv: Path, days: Sequence[date]) -> list[dict[str, object]]:
    """One row per replay-universe instrument (not EXCLUDED): route, source, fiscal years, knowledge times, gaps."""

    import csv

    from etf_cockpit.data import stock_fundamentals as store

    root = Path(root)
    history = root / "data" / "pit_history"
    manifest = json.loads((history / "esef_manifest.json").read_text(encoding="utf-8")) if (history / "esef_manifest.json").is_file() else {}
    log: dict[tuple[str, str], dict[str, object]] = {}
    log_path = history / "esef_generic_import_log.jsonl"
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            log[(str(row["instrument_id"]), str(row["filing_id"]))] = row  # the last outcome of a filing wins
    summary_path = root / "evidence" / "norway" / "sparebank_refresh_summary.json"
    banks = {str(item["id"]): item for item in json.loads(summary_path.read_text(encoding="utf-8")).get("banks", [])} if summary_path.is_file() else {}
    stock = store.read_fundamentals(root)
    with Path(audit_csv).open(newline="", encoding="utf-8") as handle:
        universe = [row for row in csv.DictReader(handle) if row["replay_set"] != "EXCLUDED"]
    rows: list[dict[str, object]] = []
    for item in universe:
        instrument_id, kind = item["id"], item["type"]
        row: dict[str, object] = {"id": instrument_id, "type": kind, "ccy": item["ccy"], "replay_set": item["replay_set"], "route": "", "source": "", "lei": "", "registry_filings": 0, "imported_filings": 0, "fiscal_years": "", "first_known_at": "", "first_decision_date": "", "last_known_at": "", "gaps": ""}
        gaps: list[str] = []
        if kind == "etf":
            row.update(route="etf_snapshot_only", source="etf_holdings/etf_metadata snapshot 2026-10-11 (yfinance, issuer pages)",
                       gaps="no free dated history for holdings weights, AUM or TER: exposure and product-quality inputs are unavailable before the first snapshot")
            rows.append(row)
            continue
        lei, registry, reason = _registry_counts(manifest, instrument_id)
        row.update(lei=lei, registry_filings=registry)
        years: set[int] = set()
        stamps: list[datetime] = []
        sec = stock[(stock["instrument_id"].astype(str) == instrument_id) & (stock["source"].astype(str) == "sec_edgar")] if not stock.empty else stock
        if not sec.empty:
            fy = sec[(sec["period_type"].astype(str) == "FY") & (pd.to_datetime(sec["period_end"], errors="coerce") >= pd.Timestamp("2020-01-01"))]
            years = {int(str(value)[:4]) for value in fy["period_end"]}
            stamps = [stamp for stamp in (_utc(value) for value in fy["known_at"]) if stamp is not None]
            row.update(route="sec_edgar", source="SEC EDGAR companyfacts, as originally filed (stock_fundamentals.parquet)", imported_filings=len(fy))
        elif kind == "equity_certificate" or instrument_id in banks:
            bank = banks.get(instrument_id, {})
            outcomes = bank.get("history") or []
            imported = [o for o in outcomes if o.get("status") == "imported"]
            years = {int(str(o["period_end"])[:4]) for o in imported}
            stamps = [stamp for stamp in (_utc(o.get("known_at")) for o in imported) if stamp is not None]
            row.update(route="esef_norway_certificate", source="filings.xbrl.org ESEF -> evidence/norway/<id>-history (known_at = registry date_added)", imported_filings=len(imported))
            gaps.extend(f"{o['period_end'][:4]}: {str(o.get('reason'))[:80]}" for o in outcomes if o.get("status") != "imported")
            if not outcomes:
                gaps.append(str(bank.get("reason") or reason or "not processed"))
        else:
            mine = [value for (iid, _fid), value in log.items() if iid == instrument_id]
            imported = [o for o in mine if o.get("status") in {"imported", "already_imported"}]
            years = {int(str(o["period_end"])[:4]) for o in imported}
            stamps = [stamp for stamp in (_utc(o.get("date_added")) for o in imported) if stamp is not None]
            row.update(route="esef_statement_facts", source="filings.xbrl.org ESEF -> data/clean/statement_facts.parquet (known_at = registry date_added); not read by the stock_value/stock_quality pillars", imported_filings=len(imported))
            failed: dict[str, int] = {}
            for o in mine:
                if o.get("status") == "failed":
                    code = str(o.get("reason") or "").split("unavailable:")[-1].split(".")[0].strip()
                    failed[code or "failed"] = failed.get(code or "failed", 0) + 1
            gaps.extend(f"{count} filing(s) rejected by the ESEF parser: {code}" for code, count in sorted(failed.items()))
            if not mine:
                gaps.append(reason or "no filing in the registry")
        missing = [str(year) for year in range(2020, 2026) if year not in years]
        if years and missing:
            gaps.append("no FY" + "/".join(missing) + " (not filed/published in the registry, or rejected above)")
        if not years and not gaps:
            gaps.append(reason or "no history")
        row["fiscal_years"] = ",".join(str(year) for year in sorted(years))
        if stamps:
            first = min(stamps)
            row.update(first_known_at=first.isoformat(), last_known_at=max(stamps).isoformat(), first_decision_date=_first_decision_on_or_after(first.date(), days))
        row["gaps"] = "; ".join(item for item in gaps if item)
        rows.append(row)
    return rows


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=os.environ.get("ETF_COCKPIT_ROOT"), required=os.environ.get("ETF_COCKPIT_ROOT") is None)
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--step-days", type=int, default=7)
    parser.add_argument("--json", type=Path, help="write the full report here")
    parser.add_argument("--coverage-csv", type=Path, help="write one coverage row per replay-universe instrument here")
    parser.add_argument("--universe-csv", type=Path, help="replay universe audit CSV (needed for --coverage-csv)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root).resolve()
    os.environ["ETF_COCKPIT_ROOT"] = str(root)
    days = decision_dates(args.start, args.end, args.step_days)
    report = run_checks(root, days)
    if args.coverage_csv:
        if args.universe_csv is None:
            parser.error("--coverage-csv needs --universe-csv")
        coverage = build_coverage(root, args.universe_csv, days)
        args.coverage_csv.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(coverage).to_csv(args.coverage_csv, index=False)
        report["coverage_rows"] = len(coverage)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1, sort_keys=True, default=str), encoding="utf-8")
    print(f"PIT check: {'PASS' if report['passed'] else 'FAIL'} - {report['violation_count']} violation(s) over {report['decision_dates']} decision dates")
    for line in report["violations_sample"][:10]:  # type: ignore[index]
        print("  ", line)
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
