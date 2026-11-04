"""Live, recorded acquisition for the S&P 500 PIT universe (research only).

Fetches (and records with SHA-256, URL and fetch time) the fja05680 historical
components CSV, Wikipedia's historical-changes and constituents pages, SEC
company_tickers, then SEC submissions + companyfacts for current AND former
members, then Yahoo prices. Everything lands under
``<root>/data/raw/univ1_sp500``; ``scripts/ingest_sp500.py`` stays offline.

Rules: observation known_at is the actual fetch time; opt-in cover identities
use filing acceptance evidence. SEC <= 8 req/s in total, other hosts
1 req/s; retries with backoff; every step resumes from on-disk files whose
checksum matches their sidecar. Instrument IDs are NEVER minted: bindings come
only from the verified universe store (US ISIN, verified, exact ticker) and
unbound members stay out of the stores. Former-member CIKs are acquisition
candidates only (exact normalised name, unique CIK); the ingester still decides
the identity. Former-member prices are kept only when the price window covers
the membership window (otherwise: ticker reuse / no source, flagged).
execution_allowed is always false.

cover-evidence defaults to filingDate >= 2019-06-01 and includes amendments.
Only extracted filing records are cached, within a 32 MiB total cover budget.
Reports and indexes stay in memory. Inline fallback starts with a 256 KiB range,
stops on parsed facts, and widens only as needed up to 2 MiB. Acquisition stops
before consuming the last 5 GiB free.

Parallelised: per-CIK SEC fetches (thread pool, one shared limiter), name
searches, per-ticker price downloads (pool, one shared 1 req/s limiter).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html as html_lib
import http.client
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# Repository imports follow the standalone CLI's sys.path bootstrap.
from etf_cockpit.core.atomic_io import atomic_write_bytes  # noqa: E402
from etf_cockpit.data.sec_cik_history import cik_text  # noqa: E402
from etf_cockpit.data.sec_cover_identity import (  # noqa: E402
    DEFAULT_COVER_START, FORMS, acceptance_utc, parse_cover, select_bindings,
)
from etf_cockpit.data.sp500_history import (  # noqa: E402
    fja_events, intervals_from_fja, parse_fja_csv, parse_wikipedia_changes,
)

SEC_RATE, OTHER_RATE = 8.0, 1.0
COVER_FILE_CAP = 2 * 1024**2
COVER_RANGE_BYTES = 256 * 1024
COVER_READ_BYTES = 8 * 1024
COVER_CACHE_BUDGET = 32 * 1024**2
COVER_FREE_FLOOR = 5 * 1024**3
RETRY_INITIAL, RETRY_CAP, THROTTLE_PAUSE = 5.0, 60.0, 60.0
FJA_REPO, FJA_FILE = "fja05680/sp500", "S&P 500 Historical Components & Changes (Updated).csv"
WIKI_HISTORY = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
WIKI_CONSTITUENTS = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/{name}"
COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
NAME_SEARCH = "https://efts.sec.gov/LATEST/search-index?keysTyped={query}"
SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "llc", "lp",
            "holdings", "holding", "group", "sa", "nv", "the", "cos", "companies"}


class Limiter:
    """Minimum spacing between calls, shared by every thread using one host."""

    def __init__(self, per_second: float):
        self.interval, self.lock, self.next = 1.0 / per_second, threading.Lock(), 0.0

    def wait(self) -> None:
        # Recheck after sleeping: another worker may have received Retry-After.
        while True:
            with self.lock:
                delay = self.next - time.monotonic()
                if delay <= 0:
                    self.next = time.monotonic() + self.interval
                    return
            time.sleep(delay)

    def defer(self, seconds: float) -> None:
        """A provider cooldown applies to queued workers as well as the caller."""
        with self.lock:
            self.next = max(self.next, time.monotonic() + seconds)


LIMITERS = {"sec": Limiter(SEC_RATE), "github": Limiter(OTHER_RATE), "wikipedia": Limiter(OTHER_RATE),
            "yahoo": Limiter(OTHER_RATE)}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def user_agent() -> str:
    value = os.environ.get("ETF_COCKPIT_SEC_EDGAR_USER_AGENT")
    if not value and sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value = winreg.QueryValueEx(key, "ETF_COCKPIT_SEC_EDGAR_USER_AGENT")[0]
    if not value or "@" not in value:
        raise ValueError("ETF_COCKPIT_SEC_EDGAR_USER_AGENT with a contact address is required")
    return value


def retry_after(value: str | None) -> float:
    """Return the provider's minimum wait; invalid/missing headers use backoff."""
    if value is None:
        return 0.0
    value = value.strip()
    if re.fullmatch(r"[0-9]+", value):
        return float(value)
    try:
        stamp = parsedate_to_datetime(value)
        # HTTP dates are UTC, including the obsolete asctime form without a zone.
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return max(0.0, stamp.timestamp() - time.time())
    except (ValueError, TypeError, OverflowError):
        pass
    return 0.0


def http_get(url: str, host: str, *, tries: int = 5, allow_404: bool = False,
              max_bytes: int | None = None, range_bytes: int | None = None,
              range_start: int = 0, stop_when=None, on_bytes=None) -> tuple[int, bytes]:
    """Five total attempts; 5s exponential backoff capped at 60s.

    403/429 wait at least 60s. Retry-After is a lower bound and is never capped.
    All waits use the host's shared limiter, including the final failure cooldown.
    """
    if tries < 1:
        raise ValueError("tries must be positive")
    headers = {"User-Agent": user_agent(), "Accept-Encoding": "identity" if max_bytes else "gzip"}
    if range_bytes is not None:
        headers["Range"] = f"bytes={range_start}-{range_start + range_bytes - 1}"
    request = urllib.request.Request(url, headers=headers)
    for attempt in range(tries):
        LIMITERS[host].wait()
        delay = min(RETRY_INITIAL * 2 ** min(attempt, 4), RETRY_CAP)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if max_bytes is not None and response.headers.get("Content-Encoding", "identity") != "identity":
                    raise ValueError("encoded cover response rejected; exact received bytes required")
                declared_size = None
                if range_bytes is not None and response.status == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(?:\d+|\*)",
                                         response.headers.get("Content-Range", ""))
                    if (not match or int(match[1]) != range_start or int(match[2]) < range_start
                            or int(match[2]) >= range_start + range_bytes):
                        raise ValueError("invalid cover Content-Range")
                    declared_size = int(match[2]) - range_start + 1
                elif range_start:
                    raise ValueError("server ignored continuation cover Range")
                limit = range_bytes if range_bytes is not None else (max_bytes + 1 if max_bytes is not None else -1)
                stopped = False
                if stop_when is None:
                    payload = response.read(limit)
                    if on_bytes is not None:
                        on_bytes(len(payload))
                else:
                    # A 200 response ignoring Range can widen in the same stream,
                    # after checking each chunk, without downloading the prefix twice.
                    if response.status == 200:
                        limit = max_bytes
                    payload = b""
                    while len(payload) < limit:
                        chunk = response.read(min(COVER_READ_BYTES, limit - len(payload)))
                        if on_bytes is not None:
                            on_bytes(len(chunk))
                        if not chunk:
                            break
                        payload += chunk
                        if stop_when(payload):
                            stopped = True
                            break
                if max_bytes is not None and len(payload) > max_bytes:
                    raise ValueError(f"cover per-file cap exceeded ({max_bytes} bytes): {url}")
                if declared_size is not None:
                    if len(payload) > declared_size or (not stopped and len(payload) != declared_size):
                        raise ValueError("invalid cover Content-Range")
                if response.headers.get("Content-Encoding") == "gzip":
                    payload = gzip.decompress(payload)
                return response.status, payload
        except urllib.error.HTTPError as exc:
            try:
                if exc.code == 404 and allow_404:
                    return 404, b""
                if exc.code not in {403, 429} and not 500 <= exc.code < 600:
                    raise
                delay = max(delay, retry_after(exc.headers.get("Retry-After") if exc.headers else None),
                            THROTTLE_PAUSE if exc.code in {403, 429} else 0.0)
                LIMITERS[host].defer(delay)
                if attempt == tries - 1:
                    raise RuntimeError(f"{host}: HTTP {exc.code}; exhausted {tries} attempts; acquisition stopped") from exc
            finally:
                exc.close()
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as exc:
            LIMITERS[host].defer(delay)
            if attempt == tries - 1:
                raise RuntimeError(f"{host}: {type(exc).__name__}; exhausted {tries} attempts; acquisition stopped: {exc}") from exc
    raise RuntimeError("unreachable")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def record(path: Path, meta_dir: Path, payload: bytes, *, url: str, status: int = 200, **extra) -> dict:
    """Write the payload and a sidecar (url, sha256, bytes, fetched_at == known_at)."""
    atomic_write_bytes(path, payload, lambda _: None)
    meta = {"path": str(path), "url": url, "sha256": sha256(payload), "bytes": len(payload),
            "fetched_at": now(), "http_status": status, **extra}
    atomic_write_bytes(meta_dir / (path.name + ".meta.json"), json.dumps(meta, sort_keys=True, indent=1).encode(),
                       lambda p: json.loads(p.read_text()))
    return meta


def recorded(path: Path, meta_dir: Path, *, legacy_meta_dir: Path | None = None) -> dict | None:
    """Resume: a file counts only if its sidecar checksum matches the bytes on disk."""
    sidecar = meta_dir / (path.name + ".meta.json")
    if not sidecar.is_file() and legacy_meta_dir is not None:
        sidecar = legacy_meta_dir / sidecar.name
    if not path.is_file() or not sidecar.is_file():
        return None
    try:
        meta = json.loads(sidecar.read_text())
    except ValueError:
        return None
    return meta if meta.get("sha256") == sha256(path.read_bytes()) else None


def fetch_recorded(url: str, host: str, path: Path, meta_dir: Path, *, legacy_meta_dir: Path | None = None, **kwargs) -> dict:
    return recorded(path, meta_dir, legacy_meta_dir=legacy_meta_dir) or record(
        path, meta_dir, http_get(url, host)[1], url=url, **kwargs)


class Layout:
    def __init__(self, root: Path, *, cover_cache_budget: int = COVER_CACHE_BUDGET):
        self.root = root
        self.raw = root / "data" / "raw" / "univ1_sp500"
        self.sources, self.meta = self.raw / "sources", self.raw / "_meta"
        self.facts, self.subs = self.raw / "sec" / "companyfacts", self.raw / "sec" / "submissions"
        # Both endpoints use CIK{cik}.json; their checksums must not overwrite each other.
        self.facts_meta, self.subs_meta = self.meta / "companyfacts", self.meta / "submissions"
        self.prices = self.raw / "prices"
        self.cover_cache_budget = cover_cache_budget
        self._cover_cache, self._cover_lock = None, threading.Lock()
        for folder in (self.sources, self.meta, self.facts, self.subs, self.prices):
            folder.mkdir(parents=True, exist_ok=True)

    def cover_cache(self):
        with self._cover_lock:
            if self._cover_cache is None:
                self._cover_cache = CoverCache(self)
            return self._cover_cache


# ---------------------------------------------------------------- pure helpers
def sec_ticker(ticker: str) -> str:
    """SEC and Yahoo write share-class separators with '-' where S&P data uses '.'."""
    return ticker.replace(".", "-")


def name_key(name: str) -> str:
    text = re.sub(r"\([A-Z0-9, .\-]+\)\s*$", "", name.replace("&", " and "))
    tokens = [token for token in re.sub(r"[^a-z0-9]+", " ", text.casefold()).split() if token not in SUFFIXES]
    return " ".join(tokens)


def reverse_baseline(current: set[str], events: list[dict], start: str) -> tuple[list[str], list[dict]]:
    """Wikipedia-only membership at ``start``: walk the changes backwards from today.

    Returns (tickers, inconsistencies). An add after ``start`` is undone, a removal re-added.
    """
    active, issues = set(current), []
    for row in sorted((e for e in events if e["date"] > start), key=lambda e: (e["date"], e["action"]), reverse=True):
        if row["action"] == "add":
            if row["ticker"] not in active:
                issues.append({**row, "problem": "added ticker not present when walking back"})
            active.discard(row["ticker"])
        else:
            if row["ticker"] in active:
                issues.append({**row, "problem": "removed ticker already present when walking back"})
            active.add(row["ticker"])
    return sorted(active), issues


def conservative_announcements(events: list[dict]) -> list[dict]:
    """No announcement evidence is recorded by either source: knowledge = end of the effective day (UTC)."""
    note = ("conservative default: no announcement date in fja05680/Wikipedia; known no earlier than the end of "
            "the effective date")
    keys = sorted({(e["date"], e["action"], e["ticker"]) for e in events})
    return [{"date": d, "action": a, "ticker": t, "known_at": d, "source": note} for d, a, t in keys]


def select_instrument_bindings(members: dict, records: list, ciks: dict, *, known_at: str, revision: str) -> tuple[list, list]:
    """Bind only open-interval members to a verified US-ISIN stock record with the exact ticker."""
    by_ticker = {}
    for item in records:
        if item.asset_type == "stock" and item.isin_status == "verified" and item.isin.startswith("US") and item.ticker:
            by_ticker.setdefault(item.ticker, []).append(item)
    bindings, rejected = [], []
    for ticker, info in sorted(members.items()):
        if not info["current"] or ticker not in ciks:
            continue
        matches = by_ticker.get(sec_ticker(ticker), [])
        if len(matches) == 1:
            record_ = matches[0]
            bindings.append({"ticker": ticker, "valid_from": info["open_from"], "valid_to": None,
                             "instrument_id": record_.instrument_id, "known_at": known_at,
                             "source": f"universe_store revision {revision}: {record_.instrument_id} ISIN {record_.isin} "
                                       "verified, exact ticker (share-class '.'->'-' only)"})
        elif matches:
            rejected.append({"ticker": ticker, "reason": "ambiguous_universe_records"})
    return bindings, rejected


# ---------------------------------------------------------------- step: sources
def step_sources(layout: Layout) -> dict:
    manifest_path = layout.sources / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        if all(recorded(layout.sources / name, layout.meta) == manifest["files"].get(name)
               and manifest["files"].get(name) is not None for name in (
                   "fja_history.csv", "fja_LICENSE.txt", "wikipedia_changes.html",
                   "wikipedia_constituents.html", "company_tickers.json")):
            return manifest
    # Pin the discovery response too, so an interrupted run cannot mix commits.
    pinned = set()
    for name in ("fja_history.csv", "fja_LICENSE.txt"):
        meta = recorded(layout.sources / name, layout.meta)
        if meta:
            match = re.match(rf"https://raw\.githubusercontent\.com/{re.escape(FJA_REPO)}/([0-9a-f]{{40}})/", meta["url"])
            if not match:
                raise ValueError("cached fja source has no immutable commit URL")
            pinned.add(match[1])
    if len(pinned) > 1:
        raise ValueError("cached fja sources have conflicting commits")
    api = (f"https://api.github.com/repos/{FJA_REPO}/commits/{next(iter(pinned))}" if pinned else
           f"https://api.github.com/repos/{FJA_REPO}/commits?path={urllib.parse.quote(FJA_FILE)}&per_page=1")
    commit_path = layout.sources / "fja_commit.json"
    fetch_recorded(api, "github", commit_path, layout.meta)
    response = json.loads(commit_path.read_bytes())
    commit = response[0] if isinstance(response, list) else response
    sha = commit["sha"]
    if pinned and pinned != {sha}:
        raise ValueError("cached discovery and fja sources have conflicting commits")
    raw = f"https://raw.githubusercontent.com/{FJA_REPO}/{sha}/"
    files = {
        "fja_history.csv": (raw + urllib.parse.quote(FJA_FILE), "github"),
        "fja_LICENSE.txt": (raw + "LICENSE", "github"),
        "wikipedia_changes.html": (WIKI_HISTORY, "wikipedia"),
        "wikipedia_constituents.html": (WIKI_CONSTITUENTS, "wikipedia"),
        "company_tickers.json": (COMPANY_TICKERS, "sec"),
    }
    metas = {name: fetch_recorded(url, host, layout.sources / name, layout.meta) for name, (url, host) in files.items()}
    revisions = {}
    for name in ("wikipedia_changes.html", "wikipedia_constituents.html"):
        found = re.search(r'"wgRevisionId":(\d+)', (layout.sources / name).read_text(encoding="utf-8"))
        if not found:
            raise ValueError(f"no revision id in {name}")
        revisions[name] = found.group(1)
    licence = (f"fja05680/sp500 commit {sha} ({commit['commit']['committer']['date']}), MIT licence, Copyright "
               "2019-2020 Farrell J. Aultman, file 'S&P 500 Historical Components & Changes (Updated).csv'; "
               f"Wikipedia 'Historical components of the S&P 500' revision {revisions['wikipedia_changes.html']} and "
               f"'List of S&P 500 companies' revision {revisions['wikipedia_constituents.html']}, CC BY-SA 4.0 "
               "(https://creativecommons.org/licenses/by-sa/4.0/); SEC company_tickers.json (SEC public data, "
               "fair-access user agent)")
    manifest = {"fja_commit": sha, "wikipedia_revisions": revisions, "licence_ref": licence, "files": metas}
    atomic_write_bytes(layout.sources / "manifest.json", json.dumps(manifest, sort_keys=True, indent=1).encode(),
                       lambda p: json.loads(p.read_text()))
    return manifest


# ---------------------------------------------------------------- step: resolve
def constituents(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    table = text[text.find('id="constituents"'):]
    table = table[:table.find("</table>")]
    rows = []
    for row in re.findall(r"<tr.*?</tr>", table, re.S):
        rows.append([html_lib.unescape(re.sub(r"<[^>]+>", "", cell)).strip()
                     for cell in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)])
    if not rows or rows[0][:2] != ["Symbol", "Security"] or "CIK" not in rows[0]:
        raise ValueError("unexpected Wikipedia constituents header")
    index = rows[0].index("CIK")
    return [{"ticker": r[0], "name": r[1], "cik": cik_text(r[index])} for r in rows[1:] if len(r) > index]


def load_history(layout: Layout) -> dict:
    snapshots = parse_fja_csv(
        (layout.sources / "fja_history.csv").read_text(encoding="utf-8"), date_column="date", tickers_column="tickers")
    events = parse_wikipedia_changes((layout.sources / "wikipedia_changes.html").read_text(encoding="utf-8"),
                                     table_id="changes")
    return {"snapshots": snapshots, "wiki_events": events, "fja_events": fja_events(snapshots),
            "current": constituents(layout.sources / "wikipedia_constituents.html")}


def windows(snapshots: list[dict]) -> dict:
    """Half-open [from, to) membership windows per ticker from consecutive fja snapshots."""
    result, previous = {}, set()
    for snap in snapshots:
        current = set(snap["tickers"])
        for ticker in current - previous:
            result.setdefault(ticker, []).append([snap["date"], None])
        for ticker in previous - current:
            result[ticker][-1][1] = snap["date"]
        previous = current
    return result


def members_table(history: dict) -> dict:
    """Every ticker ever seen (fja windows, Wikipedia events since the fja start, current constituents)."""
    snaps = history["snapshots"]
    spans, current = windows(snaps), {row["ticker"]: row for row in history["current"]}
    names = {}
    for row in sorted(history["wiki_events"], key=lambda r: r["date"]):
        names[row["ticker"]] = row["name"]
    names.update({ticker: row["name"] for ticker, row in current.items()})
    added = {}
    for row in sorted(history["wiki_events"], key=lambda r: r["date"]):
        if row["action"] == "add":
            added[row["ticker"]] = row["date"]
    ever = set(spans) | set(current) | {e["ticker"] for e in history["wiki_events"] if e["date"] >= snaps[0]["date"]}
    members = {}
    for ticker in sorted(ever):
        open_span = next((w for w in spans.get(ticker, []) if w[1] is None), None)
        # Wikipedia's constituents (fetched later than the fja file) decide who is still a member.
        is_current = ticker in current
        members[ticker] = {"current": is_current, "name": names.get(ticker),
                           "open_from": open_span[0] if open_span else (added.get(ticker) if is_current else None),
                           "windows": spans.get(ticker, [])}
    return members


def search_names(names: dict, layout: Layout, workers: int) -> dict:
    cache_path = layout.raw / "name_search_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.is_file() else {}
    wanted = sorted({name for name in names.values() if name} - set(cache))

    def one(name: str):
        target = layout.raw / "sec" / "name_search" / (sha256(name.encode()) + ".json")
        fetch_recorded(NAME_SEARCH.format(query=urllib.parse.quote(name)), "sec", target, layout.meta / "name_search")
        hits = json.loads(target.read_bytes()).get("hits", {}).get("hits", [])
        return name, [{"cik": hit["_id"], "entity": hit["_source"].get("entity", "")} for hit in hits]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for name, hits in pool.map(one, wanted):
            cache[name] = hits
    atomic_write_bytes(cache_path, json.dumps(cache, sort_keys=True, indent=1).encode(), lambda p: json.loads(p.read_text()))
    return cache


def step_resolve(layout: Layout, workers: int) -> dict:
    history = load_history(layout)
    members = members_table(history)
    tickers = json.loads((layout.sources / "company_tickers.json").read_bytes())
    sec = {}
    for row in tickers.values():
        sec.setdefault(row["ticker"], set()).add(cik_text(row["cik_str"]))
    wiki = {sec_ticker(row["ticker"]): row["cik"] for row in history["current"]}
    ciks, flags = {}, {}
    for ticker, info in members.items():
        if info["current"]:
            from_sec, from_wiki = sec.get(sec_ticker(ticker), set()), wiki.get(sec_ticker(ticker))
            if len(from_sec) == 1 and from_wiki in from_sec:
                ciks[ticker] = {"cik": from_wiki, "evidence": "sec.company_tickers+wikipedia.constituents.CIK"}
            elif from_wiki and not from_sec:
                ciks[ticker] = {"cik": from_wiki, "evidence": "wikipedia.constituents.CIK only"}
            else:
                flags[ticker] = "current_member_cik_conflict_or_missing"
    former = {t: i["name"] for t, i in members.items() if not i["current"]}
    cache = search_names(former, layout, workers)
    for ticker, name in sorted(former.items()):
        if not name:
            flags[ticker] = "former_member_without_security_name"
            continue
        key = name_key(name)
        found = {hit["cik"] for hit in cache.get(name, []) if name_key(hit["entity"]) == key}
        if len(found) == 1:
            ciks[ticker] = {"cik": cik_text(next(iter(found))), "evidence": "efts name search, exact normalised name",
                            "candidate_only": True}
        else:
            flags[ticker] = "former_member_name_ambiguous" if found else "former_member_name_not_found"
    result = {"members": members, "ciks": ciks, "flags": flags, "resolved_at": now()}
    atomic_write_bytes(layout.raw / "resolve.json", json.dumps(result, sort_keys=True, indent=1).encode(),
                       lambda p: json.loads(p.read_text()))
    return result


# ---------------------------------------------------------------- step: sec
def fetch_issuer(task: tuple[str, Layout]) -> dict:
    cik, layout = task
    out = {"cik": cik, "submissions": "ok", "companyfacts": "ok", "pages": 0}
    try:
        name = f"CIK{cik}.json"
        fetch_recorded(SUBMISSIONS.format(name=name), "sec", layout.subs / name, layout.subs_meta, legacy_meta_dir=layout.meta)
        main = json.loads((layout.subs / name).read_bytes())
        if cik_text(main["cik"]) != cik:
            raise ValueError("submissions CIK mismatch")
        for entry in main.get("filings", {}).get("files", []):
            page = entry["name"]
            if Path(page).name != page:
                raise ValueError("unsafe submissions page name")
            fetch_recorded(SUBMISSIONS.format(name=page), "sec", layout.subs / page, layout.subs_meta, legacy_meta_dir=layout.meta)
            out["pages"] += 1
        facts = layout.facts / name
        if recorded(facts, layout.facts_meta, legacy_meta_dir=layout.meta) is None:
            status, payload = http_get(COMPANYFACTS.format(cik=cik), "sec", allow_404=True)
            if status == 404:
                out["companyfacts"] = "not_found_404"
            else:
                record(facts, layout.facts_meta, payload, url=COMPANYFACTS.format(cik=cik))
    except Exception as exc:
        out.update(submissions="failed", reason=f"{type(exc).__name__}: {exc}")
    return out


def step_sec(layout: Layout, workers: int) -> dict:
    resolved = json.loads((layout.raw / "resolve.json").read_text())
    ciks = sorted({item["cik"] for item in resolved["ciks"].values()})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(fetch_issuer, [(cik, layout) for cik in ciks]))
    summary = {"requested": len(ciks), "failed": [r for r in results if r["submissions"] == "failed"],
               "companyfacts_404": [r["cik"] for r in results if r["companyfacts"] != "ok"], "finished_at": now()}
    atomic_write_bytes(layout.raw / "sec_status.json", json.dumps(summary, sort_keys=True, indent=1).encode(),
                       lambda p: json.loads(p.read_text()))
    return summary


class CoverRunAborted(RuntimeError):
    """A shared storage limit stops all issuer workers and config publication."""


class CoverCache:
    """One process-wide budget for extracted records and legacy cover files.

    Existing legacy .txt files count towards the budget but are never read or
    reused. The caller may remove them separately; acquisition deletes nothing.
    """

    def __init__(self, layout: Layout):
        self.layout, self.lock, self.reason = layout, threading.Lock(), None
        roots = (layout.raw / "sec/covers", layout.meta / "covers")
        self.used = sum(p.stat().st_size for root in roots for p in root.rglob("*") if p.is_file())

    def _check(self, growth=0, temporary=0):
        if self.reason is None:
            if self.used + growth > self.layout.cover_cache_budget:
                self.reason = f"cover cache budget exceeded ({self.layout.cover_cache_budget} bytes)"
            elif shutil.disk_usage(self.layout.raw).free - temporary < COVER_FREE_FLOOR:
                self.reason = f"cover cache stopped: free disk below {COVER_FREE_FLOOR} bytes (5 GiB)"
        if self.reason is not None:
            raise CoverRunAborted(self.reason)

    def check(self):
        with self.lock:
            self._check()

    def store_record(self, path: Path, row: dict):
        # The received-byte hash belongs to the source, not this JSON encoding.
        encoded = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
        payload = json.dumps({"record": row, "record_sha256": sha256(encoded)},
                             sort_keys=True, separators=(",", ":")).encode()
        with self.lock:
            size = len(payload)
            previous = path.stat().st_size if path.is_file() else 0
            self._check(growth=size - previous, temporary=size)
            try:
                atomic_write_bytes(path, payload, lambda p: json.loads(p.read_text()))
            except OSError as exc:
                self.reason = f"cover cache write failed: {exc}"
                raise CoverRunAborted(self.reason) from exc
            self.used += size - previous
            self._check()

    def load_record(self, path: Path, *, cik: str, accession: str, form: str,
                    filed: str, accepted: str | None, base: str) -> dict | None:
        if not path.is_file() or path.stat().st_size > 16 * 1024:
            return None
        try:
            item = json.loads(path.read_bytes())
            row = item["record"]
            encoded = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
            if (item["record_sha256"] == sha256(encoded) and row["cik"] == cik
                    and row["accession"] == accession and row["form"] == form
                    and row["filing_date"] == filed and row["known_at"] == acceptance_utc(accepted or "")
                    and row["entity_central_index_key"] == cik and row["tickers"]
                    and re.fullmatch(r"[A-Za-z0-9_.-]+\.html?", row["source"].removeprefix(base), re.I)
                    and row["source"].startswith(base) and re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                    and 0 < row["bytes"] <= COVER_FILE_CAP):
                return row
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        return None


def cover_report_name(payload: bytes) -> str:
    """Use the cover report named by FilingSummary, never an arbitrary R1."""
    root = ET.fromstring(payload)
    for report in root.iter("Report"):
        names = " ".join(report.findtext(key, "") for key in ("ShortName", "LongName"))
        if re.search(r"\bcover\b|document\s+and\s+entity\s+information", names, re.I):
            name = report.findtext("HtmlFileName", "")
            if re.fullmatch(r"[A-Za-z0-9_.-]+\.html?", name, re.I):
                return name
            raise ValueError("unsafe/missing cover report filename")
    raise ValueError("FilingSummary has no named cover report")


def cover_failure(exc: Exception, *, cik: str, url: str, http_status: int | None,
                  accession: str | None = None) -> dict:
    """Keep transport causes and request context in both machine output and logs."""
    cause = exc
    while cause.__cause__ is not None:
        cause = cause.__cause__
    error = {"exception_type": type(cause).__name__, "message": str(cause),
             "reason": f"{type(exc).__name__}: {exc}",
             "http_status": cause.code if isinstance(cause, urllib.error.HTTPError) else http_status,
             "url": url}
    if accession is not None:
        error["accession"] = accession
    logging.getLogger(__name__).warning("SEC cover failure %s", json.dumps({"cik": cik, **error}, sort_keys=True))
    return error


def fetch_cover_issuer(task: tuple[str, Layout]) -> dict:
    """One issuer per worker; bounded cover requests share the SEC limiter.

    Filing dates before 2019-06-01 (the first cover-tagging period) are skipped.
    Fetch a named rendered cover first, then stream a primary prefix starting
    with a 256 KiB range. Persist only extracted records, including /A forms.
    """
    cik, layout = task
    evidence, errors = [], []
    downloaded = 0
    url, http_status, accession = SUBMISSIONS.format(name=f"CIK{cik}.json"), None, None

    def count_bytes(size):
        nonlocal downloaded
        downloaded += size
        cache.check()

    def fetch(request_url, *, target=None, meta_dir=None, **kwargs):
        nonlocal url, http_status
        url, http_status = request_url, None
        cache.check()
        # Reuse existing shared submissions, but never persist newly fetched ones.
        if target is not None and target.is_file() and target.stat().st_size > COVER_FILE_CAP:
            raise ValueError(f"cover per-file cap exceeded ({COVER_FILE_CAP} bytes): {url}")
        meta = recorded(target, meta_dir) if target is not None else None
        if meta is not None and meta.get("url") == url:
            http_status = meta.get("http_status")
            return target.read_bytes()
        http_status, payload = http_get(url, "sec", max_bytes=COVER_FILE_CAP,
                                       on_bytes=count_bytes, **kwargs)
        return payload

    try:
        cache = layout.cover_cache()
        name = f"CIK{cik}.json"
        subs, subs_meta = getattr(layout, "cached_submissions", (layout.subs, layout.subs_meta))
        main = json.loads(fetch(url, target=subs / name, meta_dir=subs_meta))
        if cik_text(main["cik"]) != cik:
            raise ValueError("submissions CIK mismatch")
        pages = [(main.get("filings", {}).get("recent", {}), url, http_status)]
        for entry in main.get("filings", {}).get("files", []):
            end = entry.get("filingTo")
            if end is not None and date.fromisoformat(end) < date.fromisoformat(DEFAULT_COVER_START):
                continue
            page = entry["name"]
            if Path(page).name != page or not re.fullmatch(r"CIK\d{10}-submissions-\d+\.json", page):
                raise ValueError("unsafe submissions page")
            url, http_status = SUBMISSIONS.format(name=page), None
            payload = fetch(url, target=subs / page, meta_dir=subs_meta)
            pages.append((json.loads(payload), url, http_status))
        filings = {}
        for page, url, http_status in pages:
            accession = None
            accessions, forms = page.get("accessionNumber", []), page.get("form", [])
            if len(accessions) != len(forms):
                raise ValueError("incomplete submissions filing index")
            accepts = page.get("acceptanceDateTime", [None] * len(accessions))
            if len(accepts) != len(accessions):
                raise ValueError("incomplete submissions acceptance index")
            dates, documents = page.get("filingDate", []), page.get("primaryDocument", [])
            if len(dates) != len(accessions) or len(documents) != len(accessions):
                raise ValueError("incomplete submissions date/primary document index")
            for accession, form, accepted, filed, primary in zip(accessions, forms, accepts, dates, documents):
                if form not in FORMS:
                    continue
                if date.fromisoformat(filed) < date.fromisoformat(DEFAULT_COVER_START):
                    continue
                if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
                    raise ValueError("invalid accession")
                if not re.fullmatch(r"[A-Za-z0-9_.-]+\.html?", primary, re.I):
                    raise ValueError("unsafe/non-HTML primary cover document")
                item = (form, accepted or None, primary, filed)
                if accession in filings and filings[accession] != item:
                    raise ValueError("conflicting submissions filing index")
                filings[accession] = item
        for accession, (form, accepted, primary, filed) in sorted(filings.items()):
            base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
            target = layout.raw / "sec/covers" / cik / (accession + ".json")
            row = cache.load_record(target, cik=cik, accession=accession, form=form,
                                    filed=filed, accepted=accepted, base=base)
            if row is not None:
                evidence.append(row)
                continue
            def parse(payload):
                return parse_cover(payload, cik=cik, accession=accession, form=form,
                                   acceptance=accepted, source=url, filing_date=filed)
            # An unavailable/unreadable rendered report can use inline DEI facts.
            try:
                summary = fetch(base + "FilingSummary.xml")
                report = cover_report_name(summary)
                payload = fetch(base + report)
                row = parse(payload)
            except (urllib.error.HTTPError, ET.ParseError, ValueError, UnicodeError) as exc:
                if isinstance(exc, urllib.error.HTTPError) and exc.code != 404:
                    raise
                if http_status is None and not isinstance(exc, urllib.error.HTTPError):
                    raise
                if "per-file cap exceeded" in str(exc) or str(exc) == "conflicting acceptanceDateTime":
                    raise
                payload = b""
                row = None

                def found(part):
                    nonlocal row
                    try:
                        row = parse(payload + part)
                    except (ValueError, UnicodeError) as error:
                        if str(error) == "conflicting acceptanceDateTime":
                            raise
                        return False
                    return True

                while row is None and len(payload) < COVER_FILE_CAP:
                    start = len(payload)
                    end = min(max(COVER_RANGE_BYTES, start * 2), COVER_FILE_CAP)
                    part = fetch(base + primary, range_bytes=end - start, range_start=start, stop_when=found)
                    payload += part
                    if len(part) < end - start or http_status == 200:
                        break
            try:
                row = row if row is not None else parse(payload)
            except (ValueError, UnicodeError) as exc:
                # A dated unreadable cover terminates continuity. Without a
                # trustworthy acceptance, fail the whole issuer scan closed.
                if str(exc) == "conflicting acceptanceDateTime":
                    raise
                errors.append(cover_failure(exc, cik=cik, url=url, http_status=http_status, accession=accession))
                stamp = acceptance_utc(accepted or "")
                row = {"cik": cik, "accession": accession, "form": form, "filing_date": filed,
                       "known_at": stamp, "tickers": [], "entity_central_index_key": None,
                       "source": url, "sha256": sha256(payload), "bytes": len(payload)}
            # Failed covers still break continuity, but are retried on the next run.
            row = dict(sorted(row.items()))
            if row["tickers"]:
                cache.store_record(target, row)
            evidence.append(row)
        return {"cik": cik, "status": "ok", "evidence": evidence, "errors": errors,
                "bytes_downloaded": downloaded}
    except Exception as exc:
        return {"cik": cik, "status": "failed", "evidence": evidence,
                "errors": errors + [cover_failure(exc, cik=cik, url=url, http_status=http_status, accession=accession)],
                "bytes_downloaded": downloaded}


def step_cover(layout: Layout, workers: int) -> dict:
    """Opt-in historical identities; preserve run_config.yaml byte-for-byte.

    Scan supported filings dated >= 2019-06-01; older identity windows stay unbound.
    Existing resolution residues and exact normalised former security names are
    candidates only. They never supply binding knowledge or effective dates.
    """
    from etf_cockpit.data.universe_store import load_universe

    config = yaml.safe_load((layout.raw / "run_config.yaml").read_text(encoding="utf-8"))
    if config.get("execution_allowed") is not False:
        raise ValueError("execution_allowed=false required")
    storage = layout.cover_cache()
    try:
        storage.check()
    except CoverRunAborted as exc:
        return {"status": "aborted", "reason": str(exc), "failed": [], "issuer_outcomes": [], "bytes_downloaded": 0}
    resolved = json.loads((layout.raw / "resolve.json").read_text())
    names = {t: info.get("name") for t, info in resolved["members"].items() if not info["current"]}
    cache = search_names(names, layout, workers)
    candidate_tickers = {t: set() for t in resolved["members"]}
    for ticker, item in resolved["ciks"].items():
        candidate_tickers.setdefault(ticker, set()).add(cik_text(item["cik"]))
    for ticker, name in names.items():
        if name and name_key(name):
            candidate_tickers[ticker].update(cik_text(hit["cik"]) for hit in cache.get(name, [])
                                             if name_key(hit["entity"]) == name_key(name))
    # Include current SEC claimants for former tickers as recycling evidence.
    tickers = json.loads(Path(config["company_tickers"]).read_bytes())
    for ticker in candidate_tickers:
        candidate_tickers[ticker].update(cik_text(r["cik_str"]) for r in tickers.values() if r["ticker"] == sec_ticker(ticker))
    candidates = set().union(*candidate_tickers.values())
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(fetch_cover_issuer, [(cik, layout) for cik in sorted(candidates)]))
    downloaded = sum(r.get("bytes_downloaded", 0) for r in results)
    if storage.reason is not None:
        return {"status": "aborted", "reason": storage.reason,
                "failed": [r["cik"] for r in results if r["status"] == "failed"], "issuer_outcomes": results,
                "bytes_downloaded": downloaded}
    evidence = [row for result in results for row in result["evidence"]]
    snapshots = parse_fja_csv(Path(config["history_csv"]).read_text(encoding="utf-8"), **config["csv_shape"])
    events = parse_wikipedia_changes(Path(config["wikipedia_html"]).read_text(encoding="utf-8"),
                                     table_id=config["wikipedia_table_id"])
    later = [e for e in events if e["date"] > max(snapshots[-1]["date"], config.get("history_start") or snapshots[0]["date"])]
    intervals = intervals_from_fja(
        snapshots, config["announcements"], baseline_known_at=config["baseline_known_at"],
        baseline_names=config["baseline_names"], extra_events=later if config["cross_validation"] == "report" else [],
        announcement_policy=config.get("announcement_policy", "required"), history_start=config.get("history_start"))
    final = {(r["ticker"], r["valid_from"]): r for r in intervals}
    store = load_universe(layout.root)
    if store.integrity_errors:
        raise ValueError("universe store has integrity errors")
    failed = {r["cik"] for r in results if r["status"] == "failed"}
    ciks, instruments, rejected = select_bindings(
        evidence, list(final.values()), list(store.records), revision=str(store.revision),
        failed_ciks=failed, incomplete_tickers={t for t, ids in candidate_tickers.items() if ids & failed})
    config.update(cik_bindings=ciks, instrument_bindings=instruments, identity_policy="sec_cover_v1",
                  identity_unbound=rejected, as_of=now(),
                  cover_evidence={"version": 1, "filing_date_start": DEFAULT_COVER_START,
                                  "issuers": [{k: v for k, v in r.items() if k != "bytes_downloaded"} for r in results]})
    payload = yaml.safe_dump(config, sort_keys=False, width=200).encode()
    destination = layout.raw / f"run_config_cover_v1_{sha256(payload)}.yaml"
    try:
        with storage.lock:
            storage._check(temporary=len(payload))
            atomic_write_bytes(destination, payload, lambda p: yaml.safe_load(p.read_text()))
    except (CoverRunAborted, OSError) as exc:
        return {"status": "aborted", "reason": str(exc),
                "failed": [r["cik"] for r in results if r["status"] == "failed"], "issuer_outcomes": results,
                "bytes_downloaded": downloaded}
    return {"config": str(destination), "cik_bindings": len(ciks), "instrument_bindings": len(instruments),
            "unbound_intervals": len(rejected), "failed": [r["cik"] for r in results if r["status"] == "failed"],
            "bytes_downloaded": downloaded,
            "issuer_outcomes": [{"cik": r["cik"], "status": r["status"], "evidence_count": len(r["evidence"]),
                                 "bytes_downloaded": r.get("bytes_downloaded", 0),
                                 "errors": r["errors"]} for r in results]}


# ---------------------------------------------------------------- step: prices
def fetch_prices_one(task: tuple[str, dict, Layout, date]) -> dict:
    ticker, bounds, layout, end = task
    symbol, out = sec_ticker(ticker), {"ticker": ticker, "yahoo_symbol": sec_ticker(ticker)}
    target = layout.prices / f"{symbol}.parquet"
    if recorded(target, layout.meta):
        frame = pd.read_parquet(target)
    else:
        from etf_cockpit.data.yfinance_provider import YFinanceProvider
        try:
            LIMITERS["yahoo"].wait()
            frame = YFinanceProvider().fetch_daily_prices(symbol, date(1990, 1, 1), end)
        except Exception as exc:
            return {**out, "status": "error", "reason": f"{type(exc).__name__}: {str(exc)[:120]}"}
        if frame.empty:
            return {**out, "status": "no_data"}
        frame = frame.assign(date=pd.to_datetime(frame["date"]))
        buffer = target.with_suffix(".tmp")
        frame.to_parquet(buffer, index=False)
        record(target, layout.meta, buffer.read_bytes(), url=f"yfinance:{symbol}", rows=len(frame))
        buffer.unlink()
    first, last = frame["date"].min().date(), frame["date"].max().date()
    start = date.fromisoformat(bounds[0])
    covers = first <= start + timedelta(days=31)
    if bounds[1] is not None:
        covers = covers and last >= date.fromisoformat(bounds[1]) - timedelta(days=31)
    return {**out, "status": "attributed" if covers else "window_mismatch_ticker_reuse_or_partial",
            "first": first.isoformat(), "last": last.isoformat(), "rows": len(frame)}


def step_prices(layout: Layout, workers: int) -> dict:
    resolved = json.loads((layout.raw / "resolve.json").read_text())
    tasks = []
    for ticker, info in sorted(resolved["members"].items()):
        spans = info["windows"] or [[info["open_from"] or date.today().isoformat(), None]]
        tasks.append((ticker, [spans[0][0], None if spans[-1][1] is None else spans[-1][1]], layout,
                      date.today() + timedelta(days=1)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(fetch_prices_one, tasks))
    summary = {"tickers": len(results), "finished_at": now(), "results": results}
    atomic_write_bytes(layout.raw / "prices_status.json", json.dumps(summary, sort_keys=True, indent=1).encode(),
                       lambda p: json.loads(p.read_text()))
    return summary


# ---------------------------------------------------------------- step: config
def step_config(layout: Layout) -> dict:
    manifest = json.loads((layout.sources / "manifest.json").read_text())
    resolved = json.loads((layout.raw / "resolve.json").read_text())
    history = load_history(layout)
    snapshots = history["snapshots"]
    history_start = "2021-10-01"  # Warm-up before the 2022-10-17 research interval.
    eligible = [row for row in snapshots if row["date"] <= history_start]
    if not eligible:
        raise ValueError("no fja snapshot at or before history_start")
    baseline = max(eligible, key=lambda row: row["date"])
    from etf_cockpit.data.universe_store import load_universe
    store = load_universe(layout.root)
    if store.integrity_errors:
        raise ValueError("universe store has integrity errors; no instrument bindings")
    observed = manifest["files"]["company_tickers.json"]["fetched_at"]
    ciks = {t: v for t, v in resolved["ciks"].items() if not v.get("candidate_only")}
    bindings, rejected = select_instrument_bindings(resolved["members"], list(store.records), ciks,
                                                    known_at=observed, revision=str(store.revision))
    bound = {b["ticker"] for b in bindings}
    cik_bindings = [{"ticker": t, "valid_from": resolved["members"][t]["open_from"], "valid_to": None,
                     "cik": ciks[t]["cik"], "known_at": observed,
                     "source": f"{ciks[t]['evidence']} fetched {observed}; ticker continuously in the index since valid_from"}
                    for t in sorted(ciks) if resolved["members"][t]["current"]]
    names = {t: info["name"] for t, info in resolved["members"].items() if info["name"]}
    base = yaml.safe_load((ROOT / "configs" / "sp500_universe_v1.yaml").read_text(encoding="utf-8"))
    current_now = {row["ticker"] for row in history["current"]}
    wiki_start, issues = reverse_baseline(current_now, history["wiki_events"], history_start)
    # Keep capture metadata. history_start explicitly opts into the dated fja
    # historical-record rule; it does not backdate identity or Wikipedia evidence.
    fja_known = manifest["files"]["fja_history.csv"]["fetched_at"]
    common = dict(
        history_csv=str(layout.sources / "fja_history.csv"), wikipedia_html=str(layout.sources / "wikipedia_changes.html"),
        company_tickers=str(layout.sources / "company_tickers.json"), companyfacts=str(layout.facts),
        submissions=str(layout.subs), as_of=now(), identity_observed_at=observed, baseline_known_at=fja_known,
        baseline_source=f"fja05680 dated snapshot {baseline['date']}, {manifest['fja_commit']}; captured {fja_known}",
        baseline_names={t: names[t] for t in baseline["tickers"] if t in names},
        history_start=history_start, announcement_policy="effective_date_conservative",
        csv_shape={"date_column": "date", "tickers_column": "tickers"}, wikipedia_table_id="changes",
        licence_ref=manifest["licence_ref"], cik_bindings=cik_bindings, instrument_bindings=bindings)
    block = {**base, **common, "cross_validation": "block",
             # Missing announcement evidence uses the explicit conservative policy.
             "announcements": [],
             "wikipedia_baseline": {"date": history_start, "known_at": max(
                  manifest["files"][name]["fetched_at"] for name in ("wikipedia_changes.html", "wikipedia_constituents.html")),
                                    "source": "derived: wikipedia constituents at fetch walked back through the changes table",
                                    "tickers": wiki_start, "names": {t: names[t] for t in wiki_start if t in names}}}
    report = {**base, **common, "cross_validation": "report", "invalid_fact_policy": "skip",
              "announcements": []}
    for name, config in (("run_config_block.yaml", block), ("run_config.yaml", report)):
        atomic_write_bytes(layout.raw / name, yaml.safe_dump(config, sort_keys=False, width=200).encode(),
                           lambda p: yaml.safe_load(p.read_text()))
    return {"instrument_bindings": len(bindings), "bound_tickers": sorted(bound), "cik_bindings": len(cik_bindings),
            "rejected_bindings": rejected, "wikipedia_baseline_inconsistencies": len(issues)}


# ---------------------------------------------------------------- step: ingest / commit prices
def step_report(layout: Layout) -> dict:
    """One deterministic summary of what was acquired, bound and left unbound."""
    from collections import Counter
    def load(name):
        return json.loads((layout.raw / name).read_text())
    resolved, manifest = load("resolve.json"), json.loads((layout.sources / "manifest.json").read_text())
    ingest_report, block = load("report.json"), load("report_block.json")
    unmapped = ingest_report["unmapped"]
    by_reason = {}
    for item in unmapped:
        by_reason.setdefault(item["reason"], set()).add(item["ticker"])
    bound = [item for item in ingest_report["issuers"]]
    prices = load("prices_status.json")["results"] if (layout.raw / "prices_status.json").is_file() else []
    out = {
        "execution_allowed": False, "generated_at": now(), "fja_commit": manifest["fja_commit"],
        "wikipedia_revisions": manifest["wikipedia_revisions"],
        "tickers_ever_seen": len(resolved["members"]),
        "current_members": sum(1 for v in resolved["members"].values() if v["current"]),
        "former_members": sum(1 for v in resolved["members"].values() if not v["current"]),
        "cik_resolved": Counter(v["evidence"] for v in resolved["ciks"].values()),
        "cik_unresolved": Counter(resolved["flags"].values()),
        "sec": load("sec_status.json") | {"companyfacts_404": len(load("sec_status.json")["companyfacts_404"])},
        "ingest": {"status": ingest_report["status"], "bound_and_ingested_issuers": bound,
                   "unbound_tickers_by_reason": {reason: len(tickers) for reason, tickers in by_reason.items()},
                   "membership_disagreements_fja_vs_wikipedia": len(ingest_report["disagreements"]),
                   "wikipedia_events_after_history": len(ingest_report["wikipedia_events_after_history"])},
        "strict_cross_validation": {"status": block["status"], "reason": block.get("reason")},
        "prices": {"tickers": len(prices), "by_status": Counter(item["status"] for item in prices)},
    }
    atomic_write_bytes(layout.raw / "acquisition_report.json", json.dumps(out, sort_keys=True, indent=1, default=dict).encode(),
                       lambda p: json.loads(p.read_text()))
    return out


class Lock:
    def __init__(self, root: Path):
        self.path = root / ".ingest.lock.d"

    def __enter__(self):
        for _ in range(720):
            try:
                self.path.mkdir()
                return self
            except FileExistsError:
                time.sleep(5)
        raise TimeoutError("ingest lock busy")

    def __exit__(self, *exc):
        self.path.rmdir()


def step_ingest(layout: Layout, config_name: str, workers: int) -> int:
    report = layout.raw / ("report_block.json" if "block" in config_name else "report.json")
    with Lock(layout.root):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "ingest_sp500.py"), "--config",
                               str(layout.raw / config_name), "--root", str(layout.root), "--workers", str(workers),
                               "--report", str(report)], check=False).returncode


def step_commit_prices(layout: Layout) -> dict:
    """Commit prices only for bound members, keyed by the approved instrument ID, via the repo price path."""
    from etf_cockpit.data.import_pipeline import commit_price_import
    from etf_cockpit.data.price_quarantine import quarantine_invalid_ohlc
    from etf_cockpit.data.providers import ProviderResult

    config = yaml.safe_load((layout.raw / "run_config.yaml").read_text())
    status = {row["ticker"]: row for row in json.loads((layout.raw / "prices_status.json").read_text())["results"]}
    frames, skipped = [], []
    for binding in config["instrument_bindings"]:
        row = status.get(binding["ticker"])
        if not row or row["status"] != "attributed":
            skipped.append({"ticker": binding["ticker"], "status": row["status"] if row else "not_fetched"})
            continue
        frame = pd.read_parquet(layout.prices / f"{sec_ticker(binding['ticker'])}.parquet")
        frames.append(frame.assign(etf_id=binding["instrument_id"]))
    if not frames:
        return {"committed": [], "skipped": skipped}
    new = pd.concat(frames, ignore_index=True)
    result, quarantined = quarantine_invalid_ohlc(ProviderResult("yfinance", "prices", "ok", "univ1_sp500 bound members", new))
    clean = layout.root / "data" / "clean" / "prices.parquet"
    with Lock(layout.root):
        stored = pd.read_parquet(clean) if clean.is_file() else pd.DataFrame()
        replaced = sorted(set(result.data["etf_id"]) & set(stored.get("etf_id", [])))
        kept = stored[~stored["etf_id"].isin(set(result.data["etf_id"]))] if not stored.empty else stored
        merged = pd.concat([kept.assign(date=pd.to_datetime(kept["date"])) if not kept.empty else kept,
                            result.data.assign(date=pd.to_datetime(result.data["date"]))], ignore_index=True)
        commit = commit_price_import(
            ProviderResult("yfinance", "prices", "ok", "univ1_sp500 bound-member prices merged into the store", merged),
            clean_path=clean, compatibility_path=layout.root / "data" / "validated" / "prices" / "prices_daily.parquet",
            raw_dir=layout.root / "data" / "raw" / "prices", snapshots_dir=layout.root / "data" / "snapshots" / "prices")
    return {"committed": sorted(set(result.data["etf_id"])), "replaced_existing_history": replaced, "skipped": skipped,
            "rows_in_store": commit.rows, "quarantined_rows": 0 if quarantined is None else len(quarantined)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--step", required=True, choices=["sources", "resolve", "sec", "cover-evidence", "prices", "config",
                                                          "ingest-block", "ingest", "commit-prices", "report"])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--sec-rate", type=float, default=SEC_RATE)
    parser.add_argument("--cover-cache-budget-bytes", type=int, default=COVER_CACHE_BUDGET,
                        help="Extracted cover cache budget (default: 32 MiB); stops below 5 GiB free")
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be positive")
    if not 0 < args.sec_rate <= 8:
        parser.error("--sec-rate must be positive and <=8")
    if args.cover_cache_budget_bytes < 1:
        parser.error("--cover-cache-budget-bytes must be positive")
    LIMITERS["sec"] = Limiter(args.sec_rate)
    layout = Layout(args.root.resolve(), cover_cache_budget=args.cover_cache_budget_bytes)
    if args.step == "sources":
        out = step_sources(layout)
    elif args.step == "resolve":
        out = step_resolve(layout, args.workers)
    elif args.step == "sec":
        out = step_sec(layout, args.workers)
    elif args.step == "cover-evidence":
        out = step_cover(layout, args.workers)
    elif args.step == "prices":
        out = step_prices(layout, args.workers)
    elif args.step == "config":
        out = step_config(layout)
    elif args.step == "commit-prices":
        out = step_commit_prices(layout)
    elif args.step == "report":
        out = step_report(layout)
    else:
        return step_ingest(layout, "run_config_block.yaml" if args.step == "ingest-block" else "run_config.yaml", args.workers)
    rendered = json.dumps({key: value for key, value in out.items() if key not in {"results", "members", "ciks", "flags", "files"}},
                          sort_keys=True, default=str)
    print(rendered if args.step == "cover-evidence" else rendered[:3000])
    if args.step in {"sec", "cover-evidence"} and (out["failed"] or out.get("status") == "aborted"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
