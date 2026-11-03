"""Offline, resumable S&P/SEC ingest using canonical membership and stock stores.

Inputs are recorded local files only. Supply a configured membership baseline,
announcement evidence, SEC identity observation date, and sourced instrument-ID
bindings. No ticker/CIK-derived instrument IDs are minted. Unknown source shapes
or identity evidence fail closed. Issuer parsing runs in bounded subprocesses;
only the parent publishes, in CIK order. Resume compares durable store rows,
not a potentially stale success log. A crash between the two stores can leave
one ahead; rerunning repairs the missing appends without rewriting history.

Only new knowledge vintages are appended. Existing corrupt stores, changed
evidence at the same knowledge time, or backdated membership corrections block.
execution_allowed is always false. No acquisition/network calls are made.

cross_validation=report (opt-in) publishes the complete fja history extended by
later Wikipedia changes and only lists source differences; invalid_fact_policy=skip
(opt-in) counts and drops unprovable SEC facts. Both defaults fail closed.
announcement_policy=effective_date_conservative uses effective-date UTC midnight
without sourced earlier announcements. history_start uses the latest dated fja
snapshot at or before that date, known at snapshot-date UTC midnight.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import zipfile

if str(Path(__file__).resolve().parents[1] / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import yaml

from etf_cockpit.analysis.stock_metrics import FLOW_FIELDS
from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.data.sec_cik_history import cik_text, map_cik
from etf_cockpit.data.sec_pit_facts import acceptance_index, fact_known_at, select_facts
from etf_cockpit.data.sp500_history import (
    build_intervals, compare_events, cross_validate, day, fja_events, intervals_from_fja, knowledge, parse_fja_csv,
    parse_wikipedia_changes,
)
from etf_cockpit.data.stock_fundamentals import (
    PERIOD_COLUMNS, _write, append_period_rows, load_stock_config, store_paths,
)
from etf_cockpit.data.stock_sources import IDENTITY_SEC_CONCEPTS, parse_edgar_companyfacts
from etf_cockpit.data.universe_membership import import_licensed_history


ROOT = Path(__file__).resolve().parents[1]


def _json(payload: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    result = json.loads(payload, object_pairs_hook=pairs)
    if not isinstance(result, dict):
        raise ValueError("expected JSON object")
    return result


def _read_member(location: str, member: str) -> dict:
    if Path(member).name != member or "/" in member or "\\" in member:
        raise ValueError("unsafe SEC member name")
    path = Path(location)
    if path.is_dir():
        return _json((path / member).read_bytes())
    with zipfile.ZipFile(path) as archive:
        if archive.namelist().count(member) != 1:
            raise ValueError(f"missing/duplicate SEC member: {member}")
        return _json(archive.read(member))


def _submission_identities(location: str, template: str) -> tuple[list[dict], dict]:
    path = Path(location)
    if template.count("{cik}") != 1:
        raise ValueError("submissions template must contain exactly one {cik}")
    pattern = re.compile(re.escape(template).replace(re.escape("{cik}"), r"(\d{10})"))
    names = [item.name for item in path.iterdir() if item.is_file()] if path.is_dir() else None
    identities, members = [], {}
    def consume(name, payload):
        cik = pattern.fullmatch(name).group(1)
        if cik_text(payload["cik"]) != cik or cik in members:
            raise ValueError("submissions member identity mismatch/duplicate")
        members[cik] = name
        identities.append({key: payload[key] for key in ("cik", "name", "tickers", "formerNames")})
    if names is not None:
        for name in sorted(names):
            if pattern.fullmatch(name):
                consume(name, _read_member(location, name))
    else:
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if pattern.fullmatch(name):
                    consume(name, _json(archive.read(name)))
    if not identities:
        raise ValueError("no submissions match configured member template")
    return identities, members


def _specs(stock_config: dict, currency: str) -> dict:
    result = {}
    flows = set(FLOW_FIELDS) | {"capex_extra"}
    concepts = {**IDENTITY_SEC_CONCEPTS, **stock_config["sec_edgar_concepts"]}
    for field, tags in concepts.items():
        for tag in tags:
            spec = {"unit": "shares" if field == "shares_outstanding" else currency,
                    "kind": "duration" if field in flows else "instant"}
            key = "us-gaap:" + tag
            if key in result and result[key] != spec:
                raise ValueError("inconsistent configured concept shape")
            result[key] = spec
    result["dei:EntityCommonStockSharesOutstanding"] = {"unit": "shares", "kind": "instant"}
    return result


def _period_rows(payload: dict, selected: list[dict], config: dict, stamp: str, reference: str,
                 skipped: dict | None = None) -> list[dict]:
    """Reuse the canonical SEC financial mapper on one already-visible vintage."""
    visible = {"cik": payload["cik"], "facts": {}}
    # fp describes the filing, not the period. Repeated comparisons across fp
    # must not let an earlier value suppress a visible restatement.
    groups, periods = {}, {}
    for fact in selected:
        if not (fact["derived"] or fact["tag"].startswith("dei:")):
            groups.setdefault((fact["tag"], fact["start"], fact["end"]), []).append(fact)
    for key, facts in groups.items():
        top = max((fact["filed"], fact["known_at"]) for fact in facts)
        winners = [fact for fact in facts if (fact["filed"], fact["known_at"]) == top]
        if len({(fact["val"], fact["unit"]) for fact in winners}) != 1:
            if skipped is None:
                raise ValueError("conflicting period values across filing fp")
            # Same period, same filing time, different values: unavailable, never a pick.
            skipped["conflicting_period_values"] = skipped.get("conflicting_period_values", 0) + 1
            continue
        periods[key] = winners[0]
    for fact in periods.values():
        namespace, tag = fact["tag"].split(":", 1)
        units = visible["facts"].setdefault(namespace, {}).setdefault(tag, {"units": {}})["units"]
        raw = {key: fact[key] for key in ("end", "fp", "filed", "accn")}
        raw["val"] = fact["val"]
        if fact["start"]:
            raw["start"] = fact["start"]
        units.setdefault(fact["unit"], []).append(raw)
    rows = parse_edgar_companyfacts(visible, config, source_ref=reference, preselected_vintage=True)
    for row in rows:
        row.update(known_at=stamp, available_at=stamp)
    shares = {}
    for fact in selected:
        if fact["tag"] != "dei:EntityCommonStockSharesOutstanding":
            continue
        previous = shares.get(fact["end"])
        rank = (fact["filed"], fact["known_at"])
        if previous is None or rank > (previous["filed"], previous["known_at"]):
            shares[fact["end"]] = fact
        elif rank == (previous["filed"], previous["known_at"]) and fact["val"] != previous["val"]:
            raise ValueError("ambiguous DEI counts across filing fp")
    for fact in shares.values():
        rows.append({"period_end": fact["end"], "period_type": "SHARES", "fiscal_year": int(fact["end"][:4]),
                     "currency": "", "source": "sec_dei", "source_ref": reference + ":" + fact["accn"],
                     "known_at": fact["known_at"], "available_at": fact["known_at"], "shares_outstanding": fact["val"],
                     "value_status": json.dumps({"shares_outstanding": "observed"}, sort_keys=True)})
    return sorted(rows, key=lambda row: (row["period_end"], row["period_type"], row["source"]))


def _issuer(task: dict) -> dict:
    """Process-only lane: read/parse one issuer; never write a shared store."""
    cik = task["cik"]
    try:
        config = task["config"]
        payload = _read_member(config["companyfacts"], config["companyfacts_member_template"].format(cik=cik))
        if cik_text(payload["cik"]) != cik:
            raise ValueError("companyfacts member CIK mismatch")
        submissions = _read_member(config["submissions"], task["submissions_member"])
        if cik_text(submissions["cik"]) != cik:
            raise ValueError("submissions member CIK mismatch")
        pages = []
        for entry in submissions.get("filings", {}).get("files", []):
            try:
                pages.append(_read_member(config["submissions"], entry["name"]))
            except (FileNotFoundError, KeyError, ValueError):
                if config["require_historical_pages"]:
                    raise
        accepts = acceptance_index(submissions, pages)
        specs = _specs(task["stock_config"], config["currency_unit"])
        policy = config.get("invalid_fact_policy", "raise")
        if policy not in {"raise", "skip"}:
            raise ValueError("invalid_fact_policy must be raise or skip")
        # skip: unprovable facts are dropped and counted (from the final vintage), never repaired.
        skipped = {} if policy == "skip" else None
        stamps = set()
        for tag in specs:
            namespace, concept = tag.split(":", 1)
            for entries in payload.get("facts", {}).get(namespace, {}).get(concept, {}).get("units", {}).values():
                for raw in entries:
                    try:
                        stamps.add(fact_known_at(raw, accepts, require_acceptance=config["require_acceptance"]))
                    except (KeyError, TypeError, ValueError):
                        if skipped is None:
                            raise
        cutoff = knowledge(config["as_of"])
        rows = []
        reference = str(Path(config["companyfacts"]).resolve()) + "!" + config["companyfacts_member_template"].format(cik=cik)
        ordered = sorted(item for item in stamps if item <= cutoff)
        for stamp in ordered:
            bucket = skipped if stamp == ordered[-1] else ({} if skipped is not None else None)
            # Q4 is derived in the selector but the canonical mapper ignores derived rows.
            selected = select_facts(payload, stamp, specs=specs, submissions=submissions, derive_q4=False,
                                    historical_pages=pages, require_acceptance=config["require_acceptance"], skipped=bucket)
            rows.extend(_period_rows(payload, selected, task["stock_config"], stamp, reference, bucket))
        if not rows:
            raise ValueError("no usable fundamentals at cutoff")
        result = {"cik": cik, "status": "ready", "rows": rows}
        if skipped is not None:
            result["skipped_facts"] = dict(sorted(skipped.items()))
        return result
    except Exception as exc:
        return {"cik": cik, "status": "failed", "reason": f"{type(exc).__name__}: {exc}", "rows": []}


def _fingerprint(row: dict) -> str:
    def clean(value):
        if value is None or (not isinstance(value, (dict, list)) and pd.isna(value)):
            return None
        # Parquet can coerce integer facts to floating point in sparse columns.
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
    payload = {key: clean(row.get(key)) for key in PERIOD_COLUMNS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _append_facts(root: Path, instrument_id: str, rows: list[dict]) -> None:
    path = store_paths(root)["periods"]
    # The canonical reader treats corruption as empty; ingestion must never
    # replace an unreadable existing store with a partial reconstruction.
    frame = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=PERIOD_COLUMNS)
    if not set(PERIOD_COLUMNS) <= set(frame.columns):
        raise ValueError("existing fundamentals schema incomplete")
    mine = frame[frame["instrument_id"].astype(str) == instrument_id]
    existing = {_fingerprint(row) for row in mine.to_dict("records")}
    identities = {}
    def identity(row):
        return tuple(str(row.get(key)) for key in ("period_end", "period_type", "source", "known_at"))
    for row in mine.to_dict("records"):
        identities.setdefault(identity(row), set()).add(_fingerprint(row))
    pending = []
    for raw in sorted(rows, key=lambda item: (item["known_at"], item["period_end"], item["period_type"], item["source"])):
        row = {**raw, "instrument_id": instrument_id}
        digest = _fingerprint(row)
        if digest in existing:
            continue
        if identity(row) in identities and digest not in identities[identity(row)]:
            raise ValueError("changed fundamentals at existing known_at")
        # Replaying a vintage previously suppressed as unchanged must not add it
        # merely because a later restatement is now the latest row in the store.
        visible = frame[frame["known_at"].astype(str) <= raw["known_at"]]
        candidate, would_add = append_period_rows(visible, instrument_id, [raw])
        if not would_add:
            continue
        pending.append(raw)
        existing.add(digest)
        frame = pd.concat([frame, candidate.tail(would_add)], ignore_index=True)
    if pending:
        _write(path, frame)


def _run_issuer_process(task: dict) -> dict:
    """Anonymous stdio pipes work on Windows without multiprocessing IPC ACLs."""
    process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--issuer-worker"],
                             input=json.dumps(task), text=True, capture_output=True, check=False)
    if process.returncode:
        return {"cik": task["cik"], "status": "failed", "rows": [],
                "reason": f"issuer process exited {process.returncode}"}
    result = _json(process.stdout.encode())
    if result.get("cik") != task["cik"] or result.get("status") not in {"ready", "failed"}:
        raise ValueError("unexpected issuer subprocess response")
    return result


def _append_membership(root: Path, rows: list[dict], config: dict) -> None:
    path = root / "data" / "derived" / "universe_membership" / "membership.sqlite"
    existing = {}
    if path.exists():
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            for item in connection.execute(
                "SELECT instrument_id, valid_from, valid_to, known_at, snapshot_date, complete "
                "FROM licensed_history WHERE scope=? ORDER BY known_at", (config["scope"],)
            ):
                # The store serializes UTC as Z with fixed microseconds; compare
                # in the same representation as incoming knowledge timestamps.
                item = (*item[:3], knowledge(item[3]), *item[4:])
                existing.setdefault((item[0], item[1]), []).append(item)
    for row in sorted(rows, key=lambda item: (item["known_at"], item["instrument_id"], item["valid_from"])):
        previous = existing.get((row["instrument_id"], row["valid_from"]), [])
        expected = (row["instrument_id"], row["valid_from"], row["valid_to"], row["known_at"], row["snapshot_date"], 0)
        if expected in previous:
            continue
        if previous and row["known_at"] <= max(item[3] for item in previous):
            raise ValueError("changed/backdated membership knowledge")
        import_licensed_history([row], source=config["source"], licence_ref=config["licence_ref"], root=root)
        existing.setdefault((row["instrument_id"], row["valid_from"]), []).append(expected)


def ingest(config: dict, *, root: Path, workers: int = 8) -> dict:
    """Return a deterministic report; membership must precede issuer fundamentals."""
    if workers < 1 or config.get("execution_allowed") is not False:
        raise ValueError("positive workers and execution_allowed=false required")
    if not config.get("source") or not config.get("licence_ref"):
        raise ValueError("membership attribution/licence required")
    report = {"execution_allowed": False, "disagreements": [], "unmapped": [], "issuers": []}
    snapshots = parse_fja_csv(Path(config["history_csv"]).read_text(encoding="utf-8"), **config["csv_shape"])
    events = parse_wikipedia_changes(Path(config["wikipedia_html"]).read_text(encoding="utf-8"), table_id=config["wikipedia_table_id"])
    mode = config.get("cross_validation", "block")
    if mode not in {"block", "report"}:
        raise ValueError("cross_validation must be block or report")
    if not config.get("baseline_source") or (mode == "block" and not config.get("wikipedia_baseline", {}).get("source")):
        raise ValueError("independently sourced baselines required")
    # Each source retains its own baseline knowledge, never borrowed from the other.
    # Report mode extends the fja history with Wikipedia changes dated after its last snapshot.
    history_start = config.get("history_start")
    policy = config.get("announcement_policy", "required")
    provenance = []
    baseline_date = snapshots[0]["date"]
    if history_start is not None:
        history_start = day(history_start)
        eligible = [row for row in snapshots if row["date"] <= history_start]
        if not eligible:
            raise ValueError("no fja snapshot at or before history_start")
        baseline_date = history_start
        snapshot = max(eligible, key=lambda row: row["date"])
        report["history_start"] = history_start
        report["history_baseline"] = {
            "source": "fja05680", "snapshot_date": snapshot["date"], "valid_from": history_start,
            "known_at": snapshot["date"] + "T00:00:00+00:00",
            "provenance": "dated historical membership record; known_at=snapshot_date; earlier changes not ingested",
            "baseline_source": config["baseline_source"],
        }
    report["announcement_policy"] = policy
    report["membership_provenance"] = provenance
    later = [row for row in events if row["date"] > max(snapshots[-1]["date"], baseline_date)] if mode == "report" else []
    left = intervals_from_fja(snapshots, config["announcements"], baseline_known_at=config["baseline_known_at"],
                              baseline_names=config["baseline_names"], extra_events=later,
                              announcement_policy=policy, history_start=history_start, provenance=provenance)
    if mode == "block":
        baseline = config["wikipedia_baseline"]
        if baseline["date"] != baseline_date:
            raise ValueError("source baselines must have the same observation date")
        # Wikipedia lists changes older than the baseline (1976+); they predate the observed history.
        right = build_intervals(baseline, [row for row in events if row["date"] > baseline["date"]],
                                config["announcements"], source="wikipedia", announcement_policy=policy)
        report["disagreements"] = cross_validate(left, right)
        if report["disagreements"]:
            report["status"] = "blocked"
            return report
    else:
        # Explicit opt-in (recorded run config): the selected daily fja history is
        # published; Wikipedia's selected changes are only compared and reported.
        right = left
        report["cross_validation"] = "report"
        report["disagreements"] = compare_events(fja_events(snapshots), events, start=baseline_date, end=snapshots[-1]["date"])
        # Changes after the last fja snapshot are not comparable, but must stay visible.
        report["wikipedia_events_after_history"] = [{key: row[key] for key in ("date", "action", "ticker")} for row in later]
    identities, members = _submission_identities(config["submissions"], config["submissions_member_template"])
    tickers = _json(Path(config["company_tickers"]).read_bytes())
    cutoff = knowledge(config["as_of"])
    # Resolve each complete listing window, then attach its open/closed revisions.
    final = {}
    for row in right:
        final[(row["ticker"], row["valid_from"])] = row
    issuers, instrument_ciks = {}, {}
    for key, interval in sorted(final.items()):
        mapping = map_cik(interval["ticker"], interval["valid_from"], interval["valid_to"], company_tickers=tickers,
                          submissions=identities, observed_at=config["identity_observed_at"], security_name=interval.get("name"),
                          bindings=config["cik_bindings"])
        bindings = [item for item in config["instrument_bindings"] if item["ticker"] == interval["ticker"]
                    and item["valid_from"] <= interval["valid_from"] and (item.get("valid_to") is None or
                    (interval["valid_to"] is not None and interval["valid_to"] <= item["valid_to"]))]
        if mapping["status"] != "mapped" or len(bindings) != 1:
            report["unmapped"].append({**mapping, "reason": mapping.get("reason", "missing_or_ambiguous_instrument_binding")})
            continue
        binding = bindings[0]
        if not binding.get("source") or not binding.get("instrument_id"):
            raise ValueError("instrument binding requires approved ID and source")
        identity_known = max(mapping["known_at"], knowledge(binding["known_at"]))
        if identity_known > cutoff:
            report["unmapped"].append({**mapping, "reason": "identity_not_known_at_cutoff"})
            continue
        cik = mapping["cik"]
        assigned = instrument_ciks.setdefault(binding["instrument_id"], cik)
        if assigned != cik:
            raise ValueError("one canonical instrument ID resolves to conflicting CIKs")
        if cik not in members:
            report["unmapped"].append({**mapping, "reason": "submissions_missing"})
            continue
        issuer = issuers.setdefault(cik, {"bindings": [], "memberships": []})
        issuer["bindings"].append((binding["instrument_id"], identity_known))
        revisions = {}
        for row in right:
            if (row["ticker"], row["valid_from"]) != key:
                continue
            known = max(row["known_at"], identity_known)
            if known <= cutoff:
                revisions[known] = {"scope": config["scope"], "instrument_id": binding["instrument_id"],
                                    "valid_from": row["valid_from"], "valid_to": row["valid_to"], "known_at": known,
                                    "snapshot_date": row["valid_from"], "snapshot_complete": False}
        issuer["memberships"].extend(revisions.values())
    tasks = [{"cik": cik, "config": config, "stock_config": load_stock_config(ROOT), "submissions_member": members[cik]}
             for cik in sorted(issuers)]
    if workers == 1:
        results = list(map(_issuer, tasks))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_run_issuer_process, tasks))
    for result in results:
        cik = result["cik"]
        status = {key: value for key, value in result.items() if key != "rows"}
        if result["status"] == "ready":
            try:
                bindings = issuers[cik]["bindings"]
                by_id = {}
                for instrument_id, known in bindings:
                    by_id[instrument_id] = min(by_id.get(instrument_id, known), known)
                if len(by_id) > 1:
                    raise ValueError("multiple listing identities for one CIK require share-class evidence")
                _append_membership(root, issuers[cik]["memberships"], config)
                for instrument_id, known in sorted(by_id.items()):
                    rows = [{**row, "known_at": max(row["known_at"], known)} for row in result["rows"]]
                    # Identity can become known after several financial vintages:
                    # only the last visible vintage per period is then publishable.
                    collapsed = {}
                    for row in rows:
                        collapsed[(row["period_end"], row["period_type"], row["source"], row["known_at"])] = row
                    _append_facts(root, instrument_id, list(collapsed.values()))
                status.update(status="ingested", fact_rows=len(result["rows"]))
            except Exception as exc:
                status.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        report["issuers"].append(status)
    report["status"] = "complete" if report["issuers"] and not report["unmapped"] and all(
        item["status"] == "ingested" for item in report["issuers"]) else "partial"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "sp500_universe_v1.yaml")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    try:
        report = ingest(config, root=args.root, workers=args.workers)
    except Exception as exc:
        report = {"execution_allowed": False, "status": "blocked", "reason": f"{type(exc).__name__}: {exc}"}
    atomic_write_bytes(args.report, (json.dumps(report, sort_keys=True, indent=2) + "\n").encode(),
                       lambda path: _json(path.read_bytes()))
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--issuer-worker"]:
        print(json.dumps(_issuer(_json(sys.stdin.buffer.read())), sort_keys=True))
        raise SystemExit(0)
    raise SystemExit(main())
