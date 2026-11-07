"""Offline, resumable S&P/SEC ingest using canonical membership and stock stores.

Inputs are recorded local files only. Supply a configured membership baseline,
announcement evidence, SEC identity observation date, and sourced instrument-ID
bindings. No ticker/CIK-derived instrument IDs are minted. Unknown source shapes
or identity evidence fail closed. Issuer facts and vintage merges run in bounded
subprocesses; only the parent publishes, in CIK order. Resume compares durable store rows,
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
import os
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
    PERIOD_COLUMNS, _write, append_period_rows_batch, load_stock_config, store_paths,
)
from etf_cockpit.data.stock_sources import IDENTITY_SEC_CONCEPTS, parse_edgar_companyfacts
from etf_cockpit.data.universe_membership import import_licensed_history


ROOT = Path(__file__).resolve().parents[1]
COVERAGE_COLUMNS = ["scope", "source_ticker", "instrument_id", "valid_from", "valid_to", "member_known_at",
                    "identity_known_at", "binding_status", "reason"]


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


def _json_default(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


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
    updated_ends = {fact["end"] for fact in periods.values() if fact["known_at"] == stamp}
    rows = [row for row in rows if row["period_end"] in updated_ends]
    for row in rows:
        accessions = sorted({f["accn"] for f in periods.values() if f["end"] == row["period_end"]})
        row.update(known_at=stamp, available_at=stamp, source_ref=reference + ":" + ",".join(accessions))
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
        if task.get("prepare_fundamentals"):
            by_id = {}
            for target in task["fundamental_targets"]:
                instrument_id = target["instrument_id"]
                known = target["known_at"]
                by_id[instrument_id] = min(by_id.get(instrument_id, known), known)
            if len(by_id) > 1 and not task.get("share_class_evidence"):
                raise ValueError("multiple listing identities for one CIK require share-class evidence")
            pending = []
            pending_error = None
            for instrument_id, known in sorted(by_id.items()):
                visible_rows = [{**row, "known_at": max(row["known_at"], known),
                                 "available_at": max(row["available_at"], known)} for row in rows]
                # Identity can become known after several financial vintages:
                # only the last visible vintage per period is then publishable.
                collapsed = {}
                for row in visible_rows:
                    collapsed[(row["period_end"], row["period_type"], row["source"], row["known_at"])] = row
                existing = pd.DataFrame(task["existing_facts"].get(instrument_id, []), columns=PERIOD_COLUMNS)
                try:
                    pending.extend(_pending_facts(existing, instrument_id, list(collapsed.values()), preserve_vintages=True))
                except Exception as exc:
                    pending_error = f"{type(exc).__name__}: {exc}"
                    break
            result = {"cik": cik, "status": "ready", "fact_rows": len(rows), "pending_facts": pending}
            if pending_error is not None:
                result["pending_error"] = pending_error
            if skipped is not None:
                result["skipped_facts"] = dict(sorted(skipped.items()))
            return result
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


def _default_workers() -> int:
    return max(1, min(16, (os.cpu_count() or 1) - 2))


def _read_existing_facts(path: Path) -> pd.DataFrame:
    # The canonical reader treats corruption as empty; ingestion must never
    # replace an unreadable existing store with a partial reconstruction.
    frame = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=PERIOD_COLUMNS)
    if not set(PERIOD_COLUMNS) <= set(frame.columns):
        raise ValueError("existing fundamentals schema incomplete")
    return frame


def _pending_facts(frame: pd.DataFrame, instrument_id: str, rows: list[dict], *, preserve_vintages: bool = False) -> list[dict]:
    mine = frame[frame["instrument_id"].astype(str) == instrument_id]
    existing = {_fingerprint(row) for row in mine.to_dict("records")}
    identities = {}
    def identity(row):
        return tuple(str(row.get(key)) for key in ("period_end", "period_type", "source", "known_at"))
    for row in mine.to_dict("records"):
        identities.setdefault(identity(row), set()).add(_fingerprint(row))

    def should_skip(raw: dict) -> bool:
        row = {**raw, "instrument_id": instrument_id}
        digest = _fingerprint(row)
        if digest in existing:
            return True
        if identity(row) in identities and digest not in identities[identity(row)]:
            raise ValueError("changed fundamentals at existing known_at")
        return False

    def mark_appended(raw: dict) -> None:
        existing.add(_fingerprint({**raw, "instrument_id": instrument_id}))

    ordered = sorted(rows, key=lambda item: (item["known_at"], item["period_end"], item["period_type"], item["source"]))
    if preserve_vintages:
        # Distinct filing knowledge is evidence even when the reported value is
        # unchanged. Digest checks retain idempotence and same-time immutability.
        additions = []
        for row in ordered:
            if not should_skip(row):
                record = {column: row.get(column) for column in PERIOD_COLUMNS}
                record["instrument_id"] = instrument_id
                additions.append(record)
                mark_appended(row)
                identities.setdefault(identity(row), set()).add(_fingerprint(record))
        return additions
    # Replaying a vintage suppressed as unchanged remains suppressed even after
    # later restatements: the batch helper advances the same visible prefix.
    return append_period_rows_batch(mine, instrument_id, ordered, should_skip=should_skip, on_append=mark_appended)


def _run_issuer_process(task: dict) -> dict:
    """Anonymous stdio pipes work on Windows without multiprocessing IPC ACLs."""
    process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--issuer-worker"],
                             input=json.dumps(task, default=_json_default), text=True, capture_output=True, check=False)
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


def _publish_coverage(root: Path, rows: list[dict], *, scope: str, cutoff: str) -> dict:
    """Atomic scope replacement; retain every other scope and no revision duplicates.

    Calendar member-days are half-open and clipped at as_of's UTC date. This is
    an identity coverage census, independent of whether issuer facts ingest.
    Callers serialize ingestion just as they serialize the membership ledger.
    """
    path = root / "data" / "derived" / "universe_membership" / "index_coverage.parquet"
    incoming = pd.DataFrame(rows, columns=COVERAGE_COLUMNS)
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=COVERAGE_COLUMNS)
    if list(old.columns) != COVERAGE_COLUMNS:
        raise ValueError("existing index coverage schema mismatch")
    combined = pd.concat([old.loc[old.scope != scope], incoming], ignore_index=True)
    _write(path, combined[COVERAGE_COLUMNS])
    by_reason = {}
    for row in rows:
        reason = row["reason"] or "bound"
        bucket = by_reason.setdefault(reason, {"intervals": 0, "member_days": 0})
        end = min(row["valid_to"] or cutoff[:10], cutoff[:10])
        bucket["intervals"] += 1
        bucket["member_days"] += max(0, (pd.Timestamp(end) - pd.Timestamp(row["valid_from"])).days)
    return {"intervals": len(rows), "by_reason": dict(sorted(by_reason.items())), "member_days_end_exclusive": cutoff[:10]}


def ingest(config: dict, *, root: Path, workers: int | None = None) -> dict:
    """Return a deterministic report; membership must precede issuer fundamentals."""
    workers = _default_workers() if workers is None else workers
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
    issuers, instrument_ciks, coverage = {}, {}, []
    cover_mode = config.get("identity_policy") == "sec_cover_v1"
    for key, interval in sorted(final.items()):
        census = {"scope": config["scope"], "source_ticker": interval["ticker"], "instrument_id": None,
                  "valid_from": interval["valid_from"], "valid_to": interval["valid_to"],
                  "member_known_at": knowledge(interval["known_at"]), "identity_known_at": None,
                  "binding_status": "unbound", "reason": None}
        coverage.append(census)
        try:
            mapping = map_cik(interval["ticker"], interval["valid_from"], interval["valid_to"],
                              company_tickers={} if cover_mode else tickers,
                              submissions=[] if cover_mode else identities, observed_at=config["identity_observed_at"],
                              security_name=None if cover_mode else interval.get("name"), bindings=config["cik_bindings"])
            bindings = [item for item in config["instrument_bindings"] if item["ticker"] == interval["ticker"]
                        and day(item["valid_from"]) <= interval["valid_from"] and (item.get("valid_to") is None or
                        (interval["valid_to"] is not None and interval["valid_to"] <= day(item["valid_to"])))]
            for item in bindings:
                if not item.get("source") or not item.get("instrument_id"):
                    raise ValueError("instrument binding requires approved ID and source")
                knowledge(item["known_at"])
        except (KeyError, TypeError, ValueError):
            if not cover_mode:
                raise
            census["reason"] = "invalid_identity_evidence"
            report["unmapped"].append({**interval, "status": "unmapped", "reason": census["reason"]})
            continue
        if mapping["status"] != "mapped" or len(bindings) != 1:
            reasons = [r["reason"] for r in config.get("identity_unbound", [])
                       if (r["ticker"], r["valid_from"]) == key]
            census["reason"] = reasons[0] if cover_mode and reasons else mapping.get("reason", "missing_or_ambiguous_instrument_binding")
            report["unmapped"].append({**mapping, "reason": census["reason"]})
            continue
        binding = bindings[0]
        if not binding.get("source") or not binding.get("instrument_id"):
            raise ValueError("instrument binding requires approved ID and source")
        identity_known = max(mapping["known_at"], knowledge(binding["known_at"]))
        census["identity_known_at"] = identity_known
        if cover_mode and identity_known > interval["valid_from"] + "T00:00:00+00:00":
            census["reason"] = "cover_evidence_after_window_start"
            report["unmapped"].append({**mapping, "reason": census["reason"]})
            continue
        if identity_known > cutoff:
            census["reason"] = "identity_not_known_at_cutoff"
            report["unmapped"].append({**mapping, "reason": "identity_not_known_at_cutoff"})
            continue
        cik = mapping["cik"]
        assigned = instrument_ciks.setdefault(binding["instrument_id"], cik)
        if assigned != cik:
            raise ValueError("one canonical instrument ID resolves to conflicting CIKs")
        if cik not in members:
            census["reason"] = "submissions_missing"
            report["unmapped"].append({**mapping, "reason": "submissions_missing"})
            continue
        census.update(instrument_id=binding["instrument_id"], binding_status="bound")
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
    facts_path = store_paths(root)["periods"]
    try:
        existing_facts = _read_existing_facts(facts_path)
        facts_error = None
    except Exception as exc:
        existing_facts = pd.DataFrame(columns=PERIOD_COLUMNS)
        facts_error = exc
    existing_by_instrument = {
        str(instrument_id): group
        for instrument_id, group in existing_facts.groupby(existing_facts["instrument_id"].astype(str), sort=False)
    } if facts_error is None and not existing_facts.empty else {}
    tasks = []
    for cik in sorted(issuers):
        bindings = {}
        for instrument_id, known in issuers[cik]["bindings"]:
            bindings[instrument_id] = min(bindings.get(instrument_id, known), known)
        existing_rows = {
            instrument_id: existing_by_instrument[instrument_id].to_dict("records")
            for instrument_id in bindings if instrument_id in existing_by_instrument
        }
        tasks.append({
            "cik": cik, "config": config, "stock_config": load_stock_config(ROOT),
            "submissions_member": members[cik], "prepare_fundamentals": facts_error is None,
            "fundamental_targets": [
                {"instrument_id": instrument_id, "known_at": known}
                for instrument_id, known in sorted(bindings.items())
            ],
            "existing_facts": existing_rows,
            "share_class_evidence": cover_mode,
        })
    if workers == 1:
        results = list(map(_issuer, tasks))
    else:
        # Each task runs in its own issuer subprocess; threads only manage the
        # concurrent stdio subprocesses and never share parsed issuer state.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_run_issuer_process, tasks))
    pending_facts = []
    pending_statuses = []
    for result in results:
        cik = result["cik"]
        status = {key: value for key, value in result.items() if key not in {"rows", "pending_facts", "pending_error"}}
        if result["status"] == "ready":
            try:
                if not cover_mode and len({instrument_id for instrument_id, _known in issuers[cik]["bindings"]}) > 1:
                    raise ValueError("multiple listing identities for one CIK require share-class evidence")
                _append_membership(root, issuers[cik]["memberships"], config)
                if facts_error is not None:
                    raise facts_error
                if result.get("pending_error") is not None:
                    status.update(status="failed", reason=result["pending_error"])
                else:
                    issuer_pending = result.get("pending_facts", [])
                    status.update(status="ingested", fact_rows=result.get("fact_rows", len(result.get("rows", []))))
                    pending_facts.extend(issuer_pending)
                    if issuer_pending:
                        pending_statuses.append(status)
            except Exception as exc:
                status.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        report["issuers"].append(status)
    if pending_facts:
        try:
            additions = pd.DataFrame(pending_facts, columns=PERIOD_COLUMNS)
            updated = pd.concat([existing_facts, additions], ignore_index=True)
            _write(facts_path, updated)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            for status in pending_statuses:
                status.update(status="failed", reason=reason)
    report["coverage"] = _publish_coverage(root, coverage, scope=config["scope"], cutoff=cutoff)
    report["status"] = "complete" if report["issuers"] and not report["unmapped"] and all(
        item["status"] == "ingested" for item in report["issuers"]) else "partial"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "sp500_universe_v1.yaml")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=_default_workers())
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
