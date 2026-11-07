"""Local research ingestion; execution_allowed is always false.

Workers only discover/download/parse one LEI each; the parent serialises canonical
append-only writes. A shared gate limits aggregate HTTP starts to one per second.
Re-runs rediscover filings and reuse checksum-keyed parsed packages, preserving
new restatements. Interrupted parent writes replay idempotently. Do not run two
ingestions against the same root concurrently (an exclusive run lock enforces it).

The existing verified universe ISIN -> instrument_id contract is mandatory.
Missing/ambiguous identities require an owner decision, never a fabricated ID.
Membership imports are incomplete research evidence, not full daily snapshots.
Mapping availability can only delay a filing's date_added ceiling. Historical
LEI changes require a separately evidenced mapping file/run; they are not guessed.
Only local inputs are accepted for snapshot, announcements and GLEIF mapping.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import hashlib
import json
import multiprocessing
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree
import zipfile

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file
from etf_cockpit.data.esef_provider import FilingsXbrlOrgProvider, extract_issuer_shares
from etf_cockpit.data.lei_isin_map import load_mapping
from etf_cockpit.data.stoxx600_history import known_timestamp, load_history, membership_rows
from etf_cockpit.data import stock_fundamentals as fundamentals
from etf_cockpit.data.universe_membership import import_licensed_history, membership_frame, record_listing_capture
from etf_cockpit.data.universe_store import load_universe
from etf_cockpit.parsers.esef_ixbrl import PARSER_VERSION, parse_esef_package


def _gate(lock, next_start, interval):
    with lock:
        time.sleep(max(0.0, next_start.value - time.monotonic()))
        next_start.value = time.monotonic() + interval


class _LocalTransport:
    """Strict recorded-response transport, used only with --fixtures."""
    def __init__(self, path):
        self.path = Path(path)
        self.payload = json.loads(self.path.read_text())

    def __call__(self, url, headers):
        if urlparse(url).path == "/api/filings":
            page = int(parse_qs(urlparse(url).query).get("page[number]", ["1"])[0])
            return json.dumps(self.payload["pages"][page - 1]).encode()
        name = self.payload["packages"][url]
        target = (self.path.parent / name).resolve()
        if not target.is_relative_to(self.path.parent.resolve()):
            raise ValueError("fixture path escapes fixture directory")
        return target.read_bytes()


def _parse_shares_package(path):
    """Require a real instant context: the shared parser can use metadata hints."""
    parsed = parse_esef_package(path)
    if not parsed.success:
        return parsed
    namespace = "{http://www.xbrl.org/2003/instance}"
    proven = set()
    with zipfile.ZipFile(path) as archive:
        for source in sorted({fact.source_location for fact in parsed.records}):
            document = ElementTree.fromstring(archive.read(source))
            for context in document.iter(namespace + "context"):
                instant = context.find(namespace + "period/" + namespace + "instant")
                entity = context.find(namespace + "entity/" + namespace + "identifier")
                if instant is not None and instant.text and entity is not None and entity.text:
                    proven.add((source, context.get("id"), instant.text.strip(), entity.text.strip()))
    records = tuple(fact for fact in parsed.records if
        (fact.source_location, fact.context_id, fact.period_end, fact.entity_lei) in proven)
    return replace(parsed, records=records)


def ingest_issuer(job):
    """Picklable process job; returns evidence, never writes a shared store."""
    lei, settings = job
    cache = Path(settings["cache_dir"]) / lei
    fixture = Path(settings["fixtures"]) / (lei + ".json") if settings.get("fixtures") else None
    result = {"lei": lei, "status": "failed", "rows": [], "filings": [], "reason": ""}
    try:
        provider = FilingsXbrlOrgProvider(
            cache_dir=cache, transport=_LocalTransport(fixture) if fixture else None,
            request_interval=settings["request_interval"], request_gate=settings.get("request_gate"),
            retries=settings.get("http_retries", 0))
        discovered = provider.list_issuer_filings(lei, error_limit=settings["error_limit"],
            page_size=settings["page_size"], history=True, entity_type=settings.get("entity_type", "entity"),
            date_added_timezone=settings.get("date_added_timezone"))
        if not discovered.ok:
            raise ValueError(discovered.message)
        if discovered.data.empty:
            result.update(status="no_filings")
            return result
        for filing in discovered.data.to_dict("records"):
            outcome = {"id": filing["id"], "known_at": filing["known_at"], "status": "no_shares"}
            try:
                declared_sha = str(filing.get("sha256") or "")
                key = hashlib.sha256(json.dumps({"filing": filing, "parser": PARSER_VERSION,
                    "extractor": 1, "classes": settings.get("share_class_members", {}).get(lei, {})}, sort_keys=True).encode()).hexdigest()
                parsed_cache = cache / (key + ".json")
                reusable = bool(re.fullmatch(r"[0-9a-f]{64}", declared_sha))
                if reusable and parsed_cache.exists():
                    saved = json.loads(parsed_cache.read_text())
                    evidence = saved["evidence"]
                    if saved["checksum"] != hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest():
                        raise ValueError("parsed package cache checksum mismatch")
                else:
                    package = provider.download_report_package(filing["id"])
                    if reusable and declared_sha != package.sha256:
                        raise ValueError("registry/package checksum mismatch")
                    parsed = settings.get("parse_package", _parse_shares_package)(package.path)
                    if not parsed.success:
                        raise ValueError("ESEF parser rejected report package: " +
                                         (",".join(sorted({w.code for w in parsed.warnings})) or "no_warning"))
                    filing["package_sha256"] = package.sha256
                    evidence = extract_issuer_shares(parsed.records, lei=lei, filing=filing,
                        share_class_members=settings.get("share_class_members", {}).get(lei, {}))
                    if reusable:
                        payload = {"evidence": evidence,
                            "checksum": hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()}
                        atomic_write_bytes(parsed_cache, json.dumps(payload, sort_keys=True).encode(),
                                           lambda p: json.loads(p.read_text()))
                if evidence is not None:
                    # Mapping provenance cannot make an older filing usable earlier.
                    mapping_known, mapping_store = settings["mapping_known_at"], settings.get("mapping_store")
                    if isinstance(mapping_known, dict):  # per-LEI first-seen evidence (live acquisition)
                        mapping_known = mapping_known[lei]
                    if isinstance(mapping_store, dict):
                        mapping_store = mapping_store[lei]
                    evidence["known_at"] = max(evidence["known_at"], mapping_known)
                    reference = json.loads(evidence["source_ref"])
                    reference.update(mapping_store=mapping_store, mapping_known_at=mapping_known)
                    evidence["source_ref"] = json.dumps(reference, sort_keys=True)
                    result["rows"].append(evidence)
                    outcome["status"] = "shares"
            except Exception as exc:
                outcome.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
            result["filings"].append(outcome)
        statuses = {row["status"] for row in result["filings"]}
        result["status"] = "partial" if "failed" in statuses or "no_shares" in statuses else "ok"
        if not result["rows"]:
            result["status"] = "failed" if "failed" in statuses else "no_shares"
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
    return result


def run_issuers(leis, settings, *, workers=6):
    if workers < 1:
        raise ValueError("workers must be positive")
    jobs = [(lei, dict(settings)) for lei in sorted(set(leis))]
    if workers == 1:
        # One provider per issuer still shares the request clock.
        class Clock:
            value = 0.0
        import threading
        gate = partial(_gate, threading.Lock(), Clock(), settings["request_interval"])
        return [ingest_issuer((lei, {**cfg, "request_gate": gate})) for lei, cfg in jobs]
    context = multiprocessing.get_context("spawn")
    with context.Manager() as manager:
        gate = partial(_gate, manager.Lock(), manager.Value("d", 0.0), settings["request_interval"])
        jobs = [(lei, {**cfg, "request_gate": gate}) for lei, cfg in jobs]
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
            return list(pool.map(ingest_issuer, jobs))


def persist_results(results, identities, mapping, *, root):
    """Use the canonical SHARES append rule; only the parent calls this."""
    frame = fundamentals.read_fundamentals(root)
    added = 0
    for isin, instrument in sorted(identities.items()):
        lei = mapping.get(isin)
        match = next((r for r in results if r["lei"] == lei), None)
        if match is not None:
            # Issuer totals cannot be assigned to multiple listed share classes.
            if sum(value == lei for value in mapping.values()) != 1:
                raise ValueError("NEEDS_OPUS_DECISION: multiple ISINs for one issuer share count")
            frame, count = fundamentals.append_period_rows(frame, instrument, match["rows"])
            added += count
    if added:
        atomic_write_bytes(fundamentals.store_paths(root)["periods"], parquet_payload(frame), validate_parquet_file)
    return added


def _import_memberships(rows, *, source, licence_ref, root):
    # The existing importer accepts one revision per identity in each call.
    # Query committed rows on restart instead of relying on a separate journal.
    from etf_cockpit.data.stoxx600_history import SCOPE
    existing = membership_frame(SCOPE, "9999-01-01T00:00:00+00:00", root=root)
    for row in rows:
        same = existing[(existing["instrument_id"] == row["instrument_id"]) &
                        (existing["snapshot_date"] == row["snapshot_date"])]
        if not same.empty:
            latest = same.sort_values("known_at").iloc[-1]
            if known_timestamp(str(latest["known_at"])) >= row["known_at"]:
                if (str(latest["valid_from"]) != row["valid_from"] or
                    (None if latest["valid_to"] is None else str(latest["valid_to"])) != row["valid_to"]):
                    # An earlier open revision of an already-closed interval is safe to skip.
                    if known_timestamp(str(latest["known_at"])) == row["known_at"]:
                        raise ValueError("conflicting membership revision")
                continue
        import_licensed_history([row], source=source, licence_ref=licence_ref, root=root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/stoxx600_universe_v1.yaml"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    for name in ("snapshot", "changes", "gleif"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("snapshot-known-at", "history-start", "mapping-known-at", "mapping-file-date", "mapping-source", "membership-source", "licence-ref"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--complete-history", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--date-added-timezone", choices=["UTC"],
                        help="Only supply after verifying the registry's naive timestamp timezone")
    args = parser.parse_args(argv)
    config = yaml.safe_load(args.config.read_text())
    if args.date_added_timezone:
        config["date_added_timezone"] = args.date_added_timezone
    if config.get("execution_allowed") is not False or config.get("scope") != "listing:stoxx600:all":
        raise ValueError("invalid research-only STOXX configuration")
    if "parse_package" in config or "request_gate" in config:
        raise ValueError("configuration cannot override parser or throttle")
    if not args.fixtures and config["request_interval"] < 1:
        raise ValueError("live ingestion requires at least one second between requests")
    root = args.root.resolve()
    state = root / "data" / "raw" / "stoxx600"
    state.mkdir(parents=True, exist_ok=True)
    lock_path = state / "ingestion.lock"
    # A crash leaves the lock for explicit operator inspection/removal.
    with lock_path.open("x") as lock:
        lock.write(str(multiprocessing.current_process().pid))
    try:
        history = load_history(args.snapshot, args.changes, snapshot_known_at=args.snapshot_known_at,
                               history_start=args.history_start, complete_history=args.complete_history)
        universe = load_universe(root)
        if universe.integrity_errors:
            raise ValueError("NEEDS_OPUS_DECISION: invalid canonical universe identities")
        identities = {}
        for record in universe.records:
            if record.isin_status == "verified" and record.isin in set(history["ISIN"]):
                if record.isin in identities:
                    raise ValueError("NEEDS_OPUS_DECISION: ambiguous canonical ISIN identity")
                identities[record.isin] = record.instrument_id
        rows = membership_rows(history, identities)
        mapping, unmapped, mapping_store = load_mapping(args.gleif, source=args.mapping_source,
            file_date=args.mapping_file_date, store_dir=state / "mappings",
            isin_column=config["gleif_isin_column"], lei_column=config["gleif_lei_column"])
        mapping_known = known_timestamp(args.mapping_known_at)
        if mapping_known[:10] < args.mapping_file_date:
            raise ValueError("mapping known_at precedes file date")
        selected = {isin: mapping[isin] for isin in identities if isin in mapping}
        if len(set(selected.values())) != len(selected):
            raise ValueError("NEEDS_OPUS_DECISION: issuer shares cannot be allocated across multiple ISINs")
        settings = {**config, "mapping_known_at": mapping_known, "mapping_store": mapping_store.name,
                    "cache_dir": str(state / "packages"), "fixtures": str(args.fixtures) if args.fixtures else None}
        results = run_issuers(selected.values(), settings, workers=args.workers)
        added = persist_results(results, identities, selected, root=root)
        _import_memberships(rows, source=args.membership_source, licence_ref=args.licence_ref, root=root)
        with args.snapshot.open(encoding="utf-8-sig", newline="") as stream:
            seed = list(csv.DictReader(stream))
        capture = record_listing_capture(
            [{"instrument_id": identities[row["ISIN"]]} for row in seed],
            source=args.membership_source, scope=config["scope"],
            known_at=known_timestamp(args.snapshot_known_at), root=root,
            snapshot_date=seed[0]["as_of"], raw_payload=args.snapshot.read_bytes())
        if capture.status not in {"recorded", "duplicate"}:
            raise ValueError(f"snapshot capture failed: {capture.reason}")
        report = {"execution_allowed": False, "mapping_store": str(mapping_store),
                  "unmapped_isins": sorted(set(identities) - selected.keys()),
                  "mapping_unmapped_isins": list(unmapped), "issuers": results}
        atomic_write_bytes(state / "status.json", json.dumps(report, sort_keys=True, indent=2).encode(),
                           lambda p: json.loads(p.read_text()))
        print(json.dumps({"rows_added": added, "report": str(state / "status.json")}, sort_keys=True))
        return int(bool(report["unmapped_isins"]) or any(r["status"] != "ok" for r in results))
    finally:
        lock_path.unlink()


if __name__ == "__main__":
    sys.exit(main())
