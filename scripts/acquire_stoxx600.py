"""Live STOXX 600 acquisition layer for UNIV1 (research only; execution_allowed is always false).

Network fetches are recorded under <root>/data/raw/univ1_stoxx600 with sha256 sidecars
and fetch times, so every later step can be re-run offline.

* GLEIF ISIN->LEI relationship files (mapping.gleif.org, one HTTP start per second):
  semi-annual historical vintages plus the newest file. A pair's known_at is the
  upload time of the earliest sampled vintage from which the SAME single LEI is present
  in every later sampled vintage; pairs seen only in the newest file are known only then.
  Continuity between sampled vintages is not proven. Conflicting, missing or shared-LEI
  pairs are reported, never guessed. Files are validated (zip, header) before use.
* ESEF filings (filings.xbrl.org) through the canonical scripts/ingest_stoxx600.py path:
  FilingsXbrlOrgProvider discovery, checksum-keyed parsed packages, issuer share counts,
  known_at = registry date_added (a date-only value counts as end of that UTC day) floored
  by the mapping known_at, appended with the canonical SHARES append rule.
* ISIN -> instrument_id only through the verified universe store; other ISINs are
  reported as unmapped, never minted. Only asset_type == "stock" is acquired.
* STOXX 600 membership snapshot/changes: no licensed source is wired. The report says
  "unavailable" and no membership is written or inferred; ESEF fundamentals do not
  depend on it, so the verified universe stocks are the acquisition set.

Parallelised: GLEIF vintage downloads (threads, shared 1/s start gate), vintage
filtering (processes) and per-LEI ESEF discovery/download/parse (processes, shared 1/s gate).
The shared fundamentals store is written by this parent only, under .ingest.lock.d.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request
import zipfile

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPOSITORY_ROOT / "src", REPOSITORY_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import yaml  # noqa: E402

from etf_cockpit.core.atomic_io import atomic_write_bytes  # noqa: E402
from etf_cockpit.core.http_fetch import host_checked_urlopen  # noqa: E402
from etf_cockpit.data.lei_isin_map import load_mapping  # noqa: E402
from etf_cockpit.data.stoxx600_history import known_timestamp  # noqa: E402
from etf_cockpit.data.universe_store import load_universe  # noqa: E402
from scripts import ingest_stoxx600 as ingest  # noqa: E402

GLEIF_LIST = "https://mapping.gleif.org/api/v2/isin-lei"
GLEIF_DOWNLOAD_PREFIX = "https://mapping.gleif.org/api/v2/isin-lei/"
USER_AGENT = "ETF AI Evidence Cockpit/1.0"
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_DOWNLOAD_BYTES = 2 * 1024 ** 3
DEFAULT_TARGETS = tuple(f"{year}-{month}-01" for year in range(2021, 2027) for month in ("01", "07"))
_OPENER = host_checked_urlopen  # tests replace this; production never does


class HostGate:
    """At most one request start per interval for one host (thread safe)."""

    def __init__(self, interval: float = 1.0):
        self.interval, self._next, self._lock = interval, 0.0, threading.Lock()

    def __call__(self) -> None:
        with self._lock:
            time.sleep(max(0.0, self._next - time.monotonic()))
            self._next = time.monotonic() + self.interval


def _log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {message}", file=sys.stderr, flush=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload) -> None:
    atomic_write_bytes(path, json.dumps(payload, sort_keys=True, indent=2).encode(),
                       lambda candidate: json.loads(candidate.read_text()))


def _retrying(action, *, retries: int, sleep=time.sleep):
    """Retry transient failures with exponential backoff; everything else fails closed."""
    for attempt in range(retries + 1):
        try:
            return action()
        except HTTPError as exc:
            transient = exc.code in RETRY_STATUS
            error = exc
        except (URLError, TimeoutError, ConnectionError, _InvalidDownload) as exc:
            transient, error = True, exc
        if not transient or attempt == retries:
            raise error
        _log(f"transient failure ({type(error).__name__}: {error}); retry {attempt + 1}/{retries}")
        sleep(min(60.0, 2.0 ** attempt))


class _InvalidDownload(ValueError):
    pass


def fetch_bytes(url: str, gate, *, timeout: float = 60.0, retries: int = 5, sleep=time.sleep) -> bytes:
    def once() -> bytes:
        gate()
        with _OPENER(Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}),
                     timeout=timeout) as response:
            return response.read(64 * 1024 * 1024)
    return _retrying(once, retries=retries, sleep=sleep)


def download_file(url: str, destination: Path, gate, validate, *, timeout: float = 120.0,
                  retries: int = 5, sleep=time.sleep) -> tuple[str, int]:
    """Stream to destination.part, validate, then publish atomically; returns (sha256, size)."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")

    def once() -> tuple[str, int]:
        gate()
        digest, size = hashlib.sha256(), 0
        with _OPENER(Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}), timeout=timeout) as response:
            with part.open("wb") as stream:
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    size += len(block)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise ValueError("download exceeds size limit")
                    digest.update(block)
                    stream.write(block)
        try:
            validate(part)
        except ValueError as exc:
            raise _InvalidDownload(str(exc)) from exc
        return digest.hexdigest(), size

    try:
        result = _retrying(once, retries=retries, sleep=sleep)
        os.replace(part, destination)
        return result
    finally:
        part.unlink(missing_ok=True)


def validate_gleif_zip(path: Path) -> None:
    """A transient HTML error page must never be recorded as evidence."""
    if not zipfile.is_zipfile(path):
        raise ValueError("GLEIF download is not a zip file")
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("GLEIF zip must contain exactly one CSV")
        with archive.open(members[0]) as stream:
            if stream.readline().decode("utf-8-sig").strip() != "LEI,ISIN":
                raise ValueError("GLEIF CSV header is not LEI,ISIN")
        if archive.testzip() is not None:
            raise ValueError("GLEIF zip is corrupt")


def list_vintages(gate, cache_path: Path, *, refresh: bool = False, page_size: int = 100) -> list[dict]:
    """Every published ISIN-LEI file, recorded with its fetch time."""
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text())["files"]
    files, url, pages = [], f"{GLEIF_LIST}?page%5Bnumber%5D=1&page%5Bsize%5D={page_size}", 0
    total = None
    while url:
        pages += 1
        if not url.startswith(GLEIF_LIST) or pages > 1000:
            raise ValueError("unsafe or excessive GLEIF listing pagination")
        _log(f"GLEIF listing page {pages}")
        payload = json.loads(fetch_bytes(url, gate))
        total = payload["meta"]["page"]["total"]
        for item in payload["data"]:
            attrs = item["attributes"]
            if item.get("type") != "isin-lei" or attrs.get("fileType") != "zip" or not attrs.get("valid") \
                    or not attrs.get("processed"):
                continue
            link = str(attrs["downloadLink"])
            if not link.startswith(GLEIF_DOWNLOAD_PREFIX):
                raise ValueError("unexpected GLEIF download link")
            files.append({"id": item["id"], "fileName": attrs["fileName"],
                          "uploadedAt": known_timestamp(attrs["uploadedAt"]), "downloadLink": link})
        url = payload["links"].get("next")
    if not files or len({f["id"] for f in files}) != len(files) or total is None or len(files) > total:
        raise ValueError("GLEIF listing incomplete or inconsistent")
    files.sort(key=lambda f: f["uploadedAt"])
    _write_json(cache_path, {"fetched_at": _now(), "source": GLEIF_LIST, "listed_total": total, "files": files})
    return files


def pick_vintages(files: list[dict], targets) -> list[dict]:
    """Earliest file on/after each target date (conservative), plus the newest file."""
    ordered = sorted(files, key=lambda f: f["uploadedAt"])
    chosen = {}
    for target in targets:
        match = next((f for f in ordered if f["uploadedAt"][:10] >= target), None)
        if match is not None:
            chosen[match["id"]] = match
    chosen[ordered[-1]["id"]] = ordered[-1]
    return sorted(chosen.values(), key=lambda f: f["uploadedAt"])


def acquire_vintage(vintage: dict, directory: Path, gate) -> dict:
    """Download (or reuse a checksum-verified copy of) one GLEIF zip."""
    directory.mkdir(parents=True, exist_ok=True)
    zip_path = directory / vintage["fileName"]
    meta_path = directory / (vintage["fileName"] + ".meta.json")
    if zip_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("sha256") == _sha256_file(zip_path):
            return {**vintage, "path": str(zip_path), "sha256": meta["sha256"]}
    _log(f"GLEIF download {vintage['fileName']}")
    sha, size = download_file(vintage["downloadLink"], zip_path, gate, validate_gleif_zip)
    _write_json(meta_path, {"source_url": vintage["downloadLink"], "fetched_at": _now(), "sha256": sha,
                            "size": size, "uploadedAt": vintage["uploadedAt"], "id": vintage["id"]})
    return {**vintage, "path": str(zip_path), "sha256": sha}


def filter_vintage(job) -> dict:
    """Process job: reduce one validated zip to the wanted ISINs; returns {isin: [lei]}."""
    zip_path, wanted, filtered_path = Path(job[0]), set(job[1]), Path(job[2])
    wanted_digest = hashlib.sha256("\n".join(sorted(wanted)).encode()).hexdigest()
    zip_sha = _sha256_file(zip_path)
    meta_path = filtered_path.with_name(filtered_path.name + ".meta.json")
    if filtered_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("source_sha256") == zip_sha and meta.get("wanted_sha256") == wanted_digest \
                and meta.get("sha256") == _sha256_file(filtered_path):
            return _read_pairs(filtered_path)
    found: dict[str, set[str]] = {}
    with zipfile.ZipFile(zip_path) as archive:
        member = next(name for name in archive.namelist() if name.lower().endswith(".csv"))
        with archive.open(member) as raw:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
            if next(reader) != ["LEI", "ISIN"]:
                raise ValueError("GLEIF CSV header is not LEI,ISIN")
            for row in reader:
                if len(row) == 2 and row[1] in wanted:
                    found.setdefault(row[1], set()).add(row[0])
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["LEI", "ISIN"])
    for isin in sorted(found):
        for lei in sorted(found[isin]):
            writer.writerow([lei, isin])
    payload = out.getvalue().encode()
    atomic_write_bytes(filtered_path, payload, lambda candidate: candidate.read_bytes())
    _write_json(meta_path, {"source_sha256": zip_sha, "wanted_sha256": wanted_digest,
                            "sha256": hashlib.sha256(payload).hexdigest(), "rows": len(payload.splitlines()) - 1})
    return {isin: sorted(leis) for isin, leis in found.items()}


def _read_pairs(path: Path) -> dict:
    found: dict[str, set[str]] = {}
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            found.setdefault(row["ISIN"], set()).add(row["LEI"])
    return {isin: sorted(leis) for isin, leis in found.items()}


def derive_pairs(wanted, vintages: list[dict]) -> tuple[dict, dict]:
    """vintages are oldest-first with a "map" {isin: [lei]}; the last is the reference.

    Returns ({isin: {lei, first_seen_index}}, {isin: reason}). Shared LEIs are excluded
    because an issuer-level share count cannot be allocated across several ISINs.
    """
    latest = vintages[-1]["map"]
    pairs, unmapped = {}, {}
    for isin in sorted(set(wanted)):
        leis = latest.get(isin, [])
        if len(leis) != 1:
            unmapped[isin] = "no_gleif_record" if not leis else "conflicting_leis"
            continue
        first = len(vintages) - 1
        for index in range(len(vintages) - 2, -1, -1):
            if vintages[index]["map"].get(isin) != leis:
                break
            first = index
        pairs[isin] = {"lei": leis[0], "first_seen_index": first}
    owners: dict[str, list[str]] = {}
    for isin, pair in pairs.items():
        owners.setdefault(pair["lei"], []).append(isin)
    for isins in owners.values():
        if len(isins) > 1:
            for isin in isins:
                unmapped[isin] = "shared_lei_multiple_isins"
                del pairs[isin]
    return pairs, unmapped


@contextlib.contextmanager
def shared_store_lock(root: Path, *, poll: float = 5.0, timeout: float = 4 * 3600.0):
    lock = Path(root) / ".ingest.lock.d"
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError("shared ingest lock not acquired")
            time.sleep(poll)
    try:
        yield
    finally:
        lock.rmdir()


def candidates(root: Path, only_isins=None) -> tuple[dict, dict]:
    """Verified universe stocks only: {isin: instrument_id} and reported exclusions."""
    universe = load_universe(Path(root))
    if universe.integrity_errors:
        raise ValueError("NEEDS_OPUS_DECISION: invalid canonical universe identities")
    identities, excluded, seen = {}, {}, {}
    for record in universe.records:
        if record.isin_status != "verified" or not record.isin:
            excluded[record.instrument_id] = "isin_not_verified"
        elif record.asset_type != "stock":
            excluded[record.instrument_id] = "not_stock:" + record.asset_type
        elif only_isins is not None and record.isin not in only_isins:
            continue
        else:
            seen.setdefault(record.isin, []).append(record.instrument_id)
    for isin, ids in seen.items():
        if len(ids) == 1:
            identities[isin] = ids[0]
        else:
            for instrument_id in ids:
                excluded[instrument_id] = "ambiguous_isin"
    return identities, excluded


def acquire(root: Path, *, targets=DEFAULT_TARGETS, workers: int = 6, config_path: Path | None = None,
            only_isins=None, persist: bool = True, refresh_listing: bool = False) -> dict:
    root = Path(root).resolve()
    raw = root / "data" / "raw" / "univ1_stoxx600"
    gleif_dir, state = raw / "gleif", raw / "state"
    config = yaml.safe_load((config_path or REPOSITORY_ROOT / "configs" / "stoxx600_universe_v1.yaml").read_text())
    if config.get("execution_allowed") is not False or config.get("scope") != "listing:stoxx600:all":
        raise ValueError("invalid research-only STOXX configuration")
    if config["request_interval"] < 1:
        raise ValueError("live acquisition requires at least one second between requests")
    # Repo convention (esef_publication_date): naive registry timestamps mean UTC.
    config["date_added_timezone"] = "UTC"
    identities, excluded = candidates(root, only_isins)
    report = {"execution_allowed": False, "started_at": _now(), "root": str(root),
              "membership": {"status": "unavailable",
                             "reason": "no licensed STOXX 600 snapshot/changes source is wired; no membership "
                                       "was written or inferred (fail closed)"},
              "excluded_instruments": excluded, "candidates": len(identities)}

    gate = HostGate(1.0)
    files = list_vintages(gate, gleif_dir / "listing.json", refresh=refresh_listing)
    chosen = pick_vintages(files, targets)
    with ThreadPoolExecutor(max_workers=min(4, len(chosen))) as pool:
        acquired = list(pool.map(lambda v: acquire_vintage(v, gleif_dir, gate), chosen))
    with ProcessPoolExecutor(max_workers=min(workers, len(acquired)),
                             mp_context=__import__("multiprocessing").get_context("spawn")) as pool:
        maps = list(pool.map(filter_vintage, [
            (v["path"], sorted(identities), str(gleif_dir / ("filtered-" + Path(v["fileName"]).stem + ".csv")))
            for v in acquired]))
    vintages = [{**v, "map": m} for v, m in zip(acquired, maps)]
    pairs, unmapped = derive_pairs(identities, vintages)
    report["gleif_vintages"] = [{k: v[k] for k in ("fileName", "uploadedAt", "sha256")} for v in vintages]

    selected = {isin: pair["lei"] for isin, pair in pairs.items()}
    known_by_lei, store_by_lei = {}, {}
    for index in sorted({pair["first_seen_index"] for pair in pairs.values()}):
        vintage = vintages[index]
        group = sorted((isin, pair["lei"]) for isin, pair in pairs.items() if pair["first_seen_index"] == index)
        path = gleif_dir / ("mapping-" + Path(vintage["fileName"]).stem + ".csv")
        rows = ["LEI,ISIN"] + [f"{lei},{isin}" for isin, lei in group]
        atomic_write_bytes(path, ("\n".join(rows) + "\n").encode(), lambda candidate: candidate.read_bytes())
        _, _, store = load_mapping(
            path, source=f"GLEIF ISIN-LEI {vintage['fileName']} sha256={vintage['sha256']} (first-seen vintage; "
                         f"same LEI in every later sampled vintage through {vintages[-1]['fileName']})",
            file_date=vintage["uploadedAt"][:10], store_dir=state / "mappings",
            isin_column=config["gleif_isin_column"], lei_column=config["gleif_lei_column"])
        for _, lei in group:
            known_by_lei[lei], store_by_lei[lei] = known_timestamp(vintage["uploadedAt"]), store.name

    settings = {**config, "mapping_known_at": known_by_lei, "mapping_store": store_by_lei,
                "cache_dir": str(raw / "esef"), "fixtures": None}
    results = ingest.run_issuers(selected.values(), settings, workers=workers) if selected else []
    by_lei = {r["lei"]: r for r in results}
    added = 0
    if persist and selected:
        with shared_store_lock(root):
            added = ingest.persist_results(results, {i: identities[i] for i in selected}, selected, root=root)

    issuers = []
    for isin, pair in sorted(pairs.items()):
        result = by_lei[pair["lei"]]
        rows = result["rows"]
        issuers.append({
            "instrument_id": identities[isin], "isin": isin, "lei": pair["lei"],
            "mapping_known_at": known_by_lei[pair["lei"]], "status": result["status"], "reason": result["reason"],
            "filings_seen": len(result["filings"]),
            "filing_statuses": {status: sum(1 for f in result["filings"] if f["status"] == status)
                                for status in sorted({f["status"] for f in result["filings"]})},
            "filings_known_at_first": min((f["known_at"] for f in result["filings"]), default=None),
            "filings_known_at_last": max((f["known_at"] for f in result["filings"]), default=None),
            "failed_filings": [f for f in result["filings"] if f["status"] == "failed"],
            "share_rows": len(rows),
            "history_period_first": min((r["period_end"] for r in rows), default=None),
            "history_period_last": max((r["period_end"] for r in rows), default=None),
            "known_at_first": min((r["known_at"] for r in rows), default=None)})
    report.update(
        finished_at=_now(), rows_added=added, persisted=bool(persist and selected),
        unmapped={identities[i]: reason for i, reason in sorted(unmapped.items())},
        issuers=issuers,
        counts={"candidates": len(identities), "mapped": len(selected), "unmapped": len(unmapped),
                "ingested": sum(1 for r in issuers if r["share_rows"]),
                "no_filings": sum(1 for r in issuers if r["status"] == "no_filings"),
                "no_shares": sum(1 for r in issuers if r["status"] == "no_shares"),
                "failed": sum(1 for r in issuers if r["status"] == "failed")})
    _write_json(raw / "acquisition_report.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--targets", default=",".join(DEFAULT_TARGETS),
                        help="comma separated ISO dates; the first GLEIF file on/after each is used")
    parser.add_argument("--only-isins", help="comma separated ISIN subset (probe runs)")
    parser.add_argument("--no-persist", action="store_true", help="acquire and parse but write no store")
    parser.add_argument("--refresh-listing", action="store_true")
    args = parser.parse_args(argv)
    if args.workers < 1:
        raise ValueError("workers must be positive")
    report = acquire(args.root, targets=[t for t in args.targets.split(",") if t], workers=args.workers,
                     only_isins=set(args.only_isins.split(",")) if args.only_isins else None,
                     persist=not args.no_persist, refresh_listing=args.refresh_listing)
    print(json.dumps({"counts": report["counts"], "rows_added": report["rows_added"],
                      "membership": report["membership"]["status"]}, sort_keys=True))
    return int(report["counts"]["failed"] > 0)


if __name__ == "__main__":
    sys.exit(main())
