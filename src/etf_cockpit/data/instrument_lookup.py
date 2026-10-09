"""Resolve an ISIN or a ticker to a listing (free sources only: Yahoo search, OpenFIGI, yfinance profile).

One canonical path for "add an instrument": the identifier is classified, looked up read-only and turned
into candidate listings. Nothing is written here. A result is ``ok`` (one listing), ``ambiguous`` (the
user must pick one) or carries the exact reason it could not be resolved; no symbol, currency or ISIN is
ever guessed. An ISIN is marked verified only when OpenFIGI knows it AND its name agrees with the listing.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
_USER_AGENT = "Mozilla/5.0 (ETF-AI-Cockpit local research; read-only lookup)"
SUPPORTED_QUOTE_TYPES = {"EQUITY": "stock", "ETF": "etf"}
_NAME_NOISE = {"the", "corp", "corporation", "inc", "incorporated", "plc", "nv", "sa", "ag", "se", "ltd", "limited", "group", "holding", "holdings", "company", "co", "asa", "ab", "oyj", "spa", "as", "de", "ord", "shs"}
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_TICKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]{0,31}$")

GetJson = Callable[[str], Any]
PostJson = Callable[[str, Any], Any]
TickerFactory = Callable[[str], Any]


@dataclass(frozen=True)
class Candidate:
    symbol: str
    name: str
    exchange: str = ""
    quote_type: str = ""
    currency: str = ""
    country: str = ""
    sector: str = ""
    industry: str = ""


@dataclass
class Resolution:
    identifier: str
    kind: str  # isin | ticker | invalid
    status: str  # ok | ambiguous | not_found | unsupported | invalid | error
    reason: str = ""
    candidates: tuple[Candidate, ...] = ()
    chosen: Candidate | None = None
    isin: str = ""
    isin_status: str = "needs_verification"
    isin_note: str = ""
    sources: list[str] = field(default_factory=list)


def isin_checksum_ok(value: str) -> bool:
    """ISO 6166 check digit: letters become two digits, then the Luhn algorithm over the digit string."""

    text = value.strip().upper()
    if not _ISIN.fullmatch(text):
        return False
    digits = "".join(str(int(char, 36)) for char in text)
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2 == 1:
            number *= 2
            number = number - 9 if number > 9 else number
        total += number
    return total % 10 == 0


def classify(identifier: str) -> tuple[str, str]:
    """(kind, normalised identifier); kind is isin, ticker or invalid with the reason in the second item."""

    text = (identifier or "").strip()
    if not text:
        return "invalid", "enter an ISIN (12 characters, for example US5949181045) or a ticker (for example ASML.AS)"
    upper = text.upper()
    if len(upper) == 12 and _ISIN.fullmatch(upper):
        if isin_checksum_ok(upper):
            return "isin", upper
        return "invalid", f"{upper} looks like an ISIN but its check digit is wrong; check for a typing error"
    if _TICKER.fullmatch(text):
        return "ticker", upper
    return "invalid", f"'{text}' is neither a valid ISIN nor a ticker (letters, digits, '.', '-', '=' and '_' only)"


def _http_get_json(url: str, *, timeout: float = 15.0) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https endpoints
        return json.loads(response.read().decode("utf-8"))


def _http_post_json(url: str, payload: Any, *, timeout: float = 15.0) -> Any:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https endpoints
        return json.loads(response.read().decode("utf-8"))


def yahoo_search(query: str, get_json: GetJson = _http_get_json) -> list[Candidate]:
    """Listings Yahoo knows for an ISIN or ticker, supported types only (equity, ETF)."""

    url = f"{YAHOO_SEARCH_URL}?{urllib.parse.urlencode({'q': query, 'quotesCount': 10, 'newsCount': 0, 'listsCount': 0})}"
    payload = get_json(url)
    out: list[Candidate] = []
    for item in (payload.get("quotes") or []) if isinstance(payload, Mapping) else []:
        symbol = str(item.get("symbol") or "").strip()
        quote_type = str(item.get("quoteType") or "").upper()
        if not symbol or quote_type not in SUPPORTED_QUOTE_TYPES:
            continue
        out.append(
            Candidate(
                symbol=symbol,
                name=str(item.get("longname") or item.get("shortname") or symbol),
                exchange=str(item.get("exchDisp") or item.get("exchange") or ""),
                quote_type=quote_type,
                sector=str(item.get("sector") or ""),
                industry=str(item.get("industry") or ""),
            )
        )
    return out


def openfigi_name(isin: str, post_json: PostJson = _http_post_json) -> tuple[str | None, str]:
    """(registered name, note): OpenFIGI's record for the ISIN, or None with the reason."""

    payload = post_json(OPENFIGI_URL, [{"idType": "ID_ISIN", "idValue": isin}])
    first = payload[0] if isinstance(payload, list) and payload else {}
    data = first.get("data") if isinstance(first, Mapping) else None
    if not data:
        warning = first.get("warning") if isinstance(first, Mapping) else None
        return None, f"OpenFIGI has no record for {isin}" + (f" ({warning})" if warning else "")
    return str(data[0].get("name") or ""), f"OpenFIGI: {data[0].get('name')} ({data[0].get('ticker')}, {data[0].get('exchCode')})"


def _name_tokens(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", name.casefold())
    return [word for word in words if word not in _NAME_NOISE]


def names_agree(left: str, right: str) -> bool:
    """True when the first distinctive word of both names matches (MICROSOFT CORP / Microsoft Corporation)."""

    a, b = _name_tokens(left), _name_tokens(right)
    return bool(a) and bool(b) and a[0] == b[0]


def _profile(candidate: Candidate, ticker_factory: TickerFactory | None) -> tuple[Candidate, str]:
    """Add currency, country, sector and industry from the Yahoo company profile; the reason if it is missing."""

    try:
        if ticker_factory is None:
            import yfinance  # already a production requirement; imported lazily

            ticker_factory = yfinance.Ticker
        info = dict(ticker_factory(candidate.symbol).info or {})
    except Exception as exc:
        return candidate, f"Yahoo profile for {candidate.symbol} is unavailable ({type(exc).__name__}); currency and country must be entered by hand"
    currency = str(info.get("currency") or "")
    if not currency:
        return candidate, f"Yahoo returned no currency for {candidate.symbol}; it must be entered by hand"
    return (
        Candidate(
            candidate.symbol,
            str(info.get("longName") or info.get("shortName") or candidate.name),
            candidate.exchange or str(info.get("fullExchangeName") or ""),
            str(info.get("quoteType") or candidate.quote_type).upper(),
            currency,
            str(info.get("country") or ""),
            str(info.get("sector") or candidate.sector),
            str(info.get("industry") or candidate.industry),
        ),
        "",
    )


def resolve(
    identifier: str,
    *,
    get_json: GetJson = _http_get_json,
    post_json: PostJson = _http_post_json,
    ticker_factory: TickerFactory | None = None,
) -> Resolution:
    """Look up one ISIN or ticker; every outcome carries its reason."""

    kind, normalised = classify(identifier)
    if kind == "invalid":
        return Resolution(identifier, "invalid", "invalid", normalised)
    result = Resolution(identifier, kind, "not_found", sources=["Yahoo search"])
    try:
        found = yahoo_search(normalised, get_json)
    except Exception as exc:
        result.status = "error"
        result.reason = f"Yahoo search failed ({type(exc).__name__}: {str(exc)[:100]}); nothing was added. Try again later."
        return result
    figi_name: str | None = None
    if kind == "isin":
        result.isin = normalised
        result.sources.append("OpenFIGI")
        try:
            figi_name, result.isin_note = openfigi_name(normalised, post_json)
        except Exception as exc:
            result.isin_note = f"OpenFIGI could not be reached ({type(exc).__name__}); the ISIN stays unverified"
    if kind == "ticker":
        exact = [item for item in found if item.symbol.upper() == normalised]
        found = exact or found
    if not found:
        known = f"; {result.isin_note}" if kind == "isin" and figi_name else ""
        result.reason = f"Yahoo search lists no equity or ETF for {normalised}{known}. Check the identifier, or try the Yahoo ticker with its exchange suffix (for example ASML.AS)."
        return result
    enriched: list[Candidate] = []
    notes: list[str] = []
    for item in found[:6]:
        profiled, note = _profile(item, ticker_factory)
        enriched.append(profiled)
        if note:
            notes.append(note)
    result.candidates = tuple(enriched)
    if len(enriched) > 1:
        result.status = "ambiguous"
        result.reason = f"{len(enriched)} listings match {normalised}; pick the one you trade."
        return result
    result.chosen = enriched[0]
    result.status = "ok"
    result.reason = "; ".join(notes)
    if kind == "isin" and figi_name and names_agree(figi_name, result.chosen.name):
        result.isin_status = "verified"
        result.isin_note = f"{result.isin_note}; the name agrees with the Yahoo listing"
    elif kind == "isin":
        result.isin_note = f"{result.isin_note}; the ISIN stays unverified"
    return result


def choose(resolution: Resolution, symbol: str) -> Resolution:
    """The resolution with the user's pick from an ambiguous result (a symbol that was not offered is refused)."""

    pick = next((item for item in resolution.candidates if item.symbol == symbol), None)
    if pick is None:
        return Resolution(resolution.identifier, resolution.kind, "invalid", f"{symbol} is not one of the offered listings", resolution.candidates)
    return Resolution(
        resolution.identifier, resolution.kind, "ok", resolution.reason, resolution.candidates, pick, resolution.isin, resolution.isin_status, resolution.isin_note, list(resolution.sources)
    )


def suggest_instrument_id(symbol: str, existing: Sequence[str]) -> str:
    """Short id from the symbol (ASML.AS -> ASML); the full symbol when the short id is taken."""

    taken = {item.casefold() for item in existing}
    short = re.sub(r"[^A-Z0-9]", "", symbol.upper().split(".")[0])
    if short and short.casefold() not in taken:
        return short
    full = re.sub(r"[^A-Z0-9]", "_", symbol.upper()).strip("_")
    candidate, number = full, 2
    while candidate.casefold() in taken:
        candidate = f"{full}_{number}"
        number += 1
    return candidate
