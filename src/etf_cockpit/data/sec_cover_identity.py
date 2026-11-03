"""Dated SEC cover identities; pure parsing and conservative window selection.

SEC header timestamps are America/New_York wall time; submissions timestamps
with a trailing Z are UTC. Date-granular binding
windows start on the next UTC day unless acceptance is exactly UTC midnight.
An unreadable filing breaks continuity; an unreadable issuer scan binds nothing.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from html.parser import HTMLParser
import re
from zoneinfo import ZoneInfo

from etf_cockpit.data.sec_cik_history import cik_text

FORMS = {"10-K", "10-Q", "20-F", "40-F"}


def acceptance_utc(value: str) -> str:
    """Normalise header wall time and submissions UTC without shifting either twice."""
    if re.fullmatch(r"\d{14}", value):
        wall = datetime.strptime(value, "%Y%m%d%H%M%S")
    else:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?", value):
            raise ValueError("invalid acceptanceDateTime")
        wall = datetime.fromisoformat(value.removesuffix("Z"))
        if value.endswith("Z"):
            return wall.replace(tzinfo=timezone.utc).isoformat()
    zone = ZoneInfo("America/New_York")
    first, second = wall.replace(tzinfo=zone, fold=0), wall.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ValueError("ambiguous/nonexistent acceptance wall time")
    return first.astimezone(timezone.utc).isoformat()


class _Cover(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.active = []
        self.facts = {"dei:tradingsymbol": [], "dei:entitycentralindexkey": []}

    def handle_starttag(self, tag, attrs):
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            return
        self.depth += 1
        attributes = dict(attrs)
        name = attributes.get("name", "").lower() if tag in {"ix:nonnumeric", "ix:nonfraction"} else tag
        if name in self.facts:
            if attributes.get("xsi:nil", "false").lower() == "true" or attributes.get("continuedat"):
                raise ValueError("unsupported/nil cover fact")
            self.active.append((self.depth, name, []))

    def handle_startendtag(self, tag, attrs):
        if tag in {"br", "hr", "img", "meta", "link", "input"}:
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        for _depth, _name, parts in self.active:
            parts.append(data)

    def handle_endtag(self, tag):
        for depth, name, parts in list(self.active):
            if depth == self.depth:
                self.facts[name].append("".join(parts).strip())
                self.active.remove((depth, name, parts))
        self.depth = max(0, self.depth - 1)


def parse_cover(payload: bytes, *, cik: str, accession: str, form: str,
                acceptance: str | None, source: str) -> dict:
    """A CIK candidate becomes evidence only through the filed DEI cover facts."""
    cik = cik_text(cik)
    if form not in FORMS or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not source:
        raise ValueError("invalid cover filing identity")
    text = payload.decode("utf-8-sig", errors="strict")
    header = re.search(r"<ACCEPTANCE-DATETIME>[ \t]*([^\r\n<]*)", text, re.I)
    known = acceptance_utc(header.group(1).strip()) if header else acceptance_utc(acceptance or "")
    if header and acceptance and known != acceptance_utc(acceptance):
        raise ValueError("conflicting acceptanceDateTime")
    documents = re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", text, re.I | re.S)
    if documents:
        primary = [doc for doc in documents if re.search(r"<TYPE>\s*([^\r\n<]+)", doc, re.I)
                   and re.search(r"<TYPE>\s*([^\r\n<]+)", doc, re.I).group(1).strip() == form]
        if len(primary) != 1:
            raise ValueError("missing/ambiguous primary cover document")
        text = primary[0]
    parser = _Cover()
    parser.feed(text)
    parser.close()
    if parser.active:
        raise ValueError("unclosed cover facts")
    ids = {cik_text(item) for item in parser.facts["dei:entitycentralindexkey"]}
    symbols = set(parser.facts["dei:tradingsymbol"])
    if ids != {cik} or not symbols or any(not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,19}", s) for s in symbols):
        raise ValueError("missing/conflicting CIK or TradingSymbol cover evidence")
    return {"cik": cik, "accession": accession, "known_at": known, "tickers": sorted(symbols), "source": source}


def identity_spans(evidence: list[dict]) -> list[dict]:
    """Keep each ticker through repeated identical sets; set changes close all.

    Invalid observations have an empty set and break every live ticker. Same-time
    contradictory covers also break continuity. Cross-issuer claims are retained
    here so selection can reject overlaps instead of choosing an arbitrary winner.
    """
    grouped = {}
    for row in evidence:
        grouped.setdefault((row["cik"], row["known_at"]), []).append(row)
    active, spans = {}, []
    for (cik, stamp), rows in sorted(grouped.items()):
        sets = {tuple(row.get("tickers", [])) for row in rows}
        symbols = set(next(iter(sets))) if len(sets) == 1 else set()
        for key in list(active):
            if key[0] == cik and set(active[key]["tickers"]) != symbols:
                active.pop(key)["until"] = stamp
        for ticker in sorted(symbols):
            key = (cik, ticker)
            if key not in active:
                first = min(rows, key=lambda r: r["accession"])
                span = {**first, "ticker": ticker, "until": None}
                spans.append(span)
                active[key] = span
    return spans


def select_bindings(evidence: list[dict], intervals: list[dict], records: list, *, revision: str,
                    failed_ciks: set[str] = frozenset(), incomplete_tickers: set[str] = frozenset()) -> tuple[list, list, list]:
    """Bind entire membership windows, never backfill their unevidenced prefix."""
    spans = identity_spans(evidence)
    cik_bindings, instrument_bindings, rejected = [], [], []
    for interval in sorted(intervals, key=lambda r: (r["ticker"], r["valid_from"])):
        ticker, start, end = interval["ticker"], interval["valid_from"], interval["valid_to"]
        lower = start + "T00:00:00+00:00"
        upper = end + "T00:00:00+00:00" if end else None
        claims = [s for s in spans if s["ticker"] == ticker]
        matches = [s for s in claims if s["known_at"] <= lower and
                   (s["until"] is None or (upper is not None and upper <= s["until"]))]
        reason = None
        if ticker in incomplete_tickers:
            reason = "incomplete_cover_scan"
        elif len(matches) != 1:
            reason = "ambiguous_cover_identity" if len(matches) > 1 else "no_cover_identity_for_window"
            if not matches and any(a["cik"] != b["cik"] and a["known_at"] <= lower and b["known_at"] >= lower
                                   for a in claims for b in claims):
                reason = "recycled_ticker"
        else:
            match = matches[0]
            if match["cik"] in failed_ciks:
                reason = "incomplete_cover_scan"
            elif any(r["cik"] != match["cik"] and ticker in r.get("tickers", []) and r["known_at"] >= lower
                     for r in evidence):
                reason = "recycled_ticker"
            elif any(s["cik"] != match["cik"] and (s["until"] is None or s["until"] > lower)
                     and (upper is None or s["known_at"] < upper) for s in claims):
                reason = "ambiguous_cover_identity"
        if reason:
            rejected.append({**interval, "reason": reason})
            continue
        # Every new issuer claiming this ticker closes this claim, even when it
        # has not yet published a contradictory cover of its own.
        until = match["until"]
        other = [s["known_at"] for s in claims if s["cik"] != match["cik"] and s["known_at"] > match["known_at"]]
        until = min([until] + other) if until and other else (min(other) if other else until)
        known = datetime.fromisoformat(match["known_at"])
        first_day = known.date() + (timedelta(days=1) if known.time() != time() else timedelta())
        common = {"ticker": ticker, "valid_from": first_day.isoformat(),
                  "valid_to": until[:10] if until else None, "known_at": match["known_at"],
                  "source": f"SEC cover {match['accession']}: {match['source']}", "accession": match["accession"]}
        cik_binding = {**common, "cik": match["cik"]}
        if cik_binding not in cik_bindings:
            cik_bindings.append(cik_binding)
        provider = ticker.replace(".", "-")
        candidates = [r for r in records if r.asset_type == "stock" and r.isin_status == "verified"
                      and r.isin.startswith("US") and r.ticker == provider]
        if len(candidates) != 1:
            rejected.append({**interval, "reason": "missing_or_ambiguous_instrument_binding"})
            continue
        instrument_bindings.append({**common, "valid_from": start, "valid_to": end,
                                    "instrument_id": candidates[0].instrument_id,
                                    "source": f"provider symbol {provider}; universe revision {revision}; {common['source']}"})
    return cik_bindings, instrument_bindings, rejected
