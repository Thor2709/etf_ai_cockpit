"""Evidence-only (ticker, half-open date window) -> SEC issuer resolution.

Current company_tickers and submissions tickers have no historical validity
dates: they are usable only for a window starting on their observation date.
formerNames are company names, NOT former tickers. A historical ticker needs
an exact security-name link from the membership evidence, with the entire
window contained in a formerNames window, or an explicitly sourced dated
binding. Ambiguous matches and recycled/unknown symbols stay unmapped.
Identity knowledge is the observation/binding knowledge date; it is never
backdated to a former-name start. No fuzzy matching or punctuation aliases.
"""
from __future__ import annotations

import re

from etf_cockpit.data.sp500_history import day, knowledge


def cik_text(value: object) -> str:
    text = str(value)
    if isinstance(value, bool) or not re.fullmatch(r"\d{1,10}", text) or int(text) <= 0:
        raise ValueError("invalid SEC CIK")
    return text.zfill(10)


def _name(value: str) -> str:
    return " ".join(value.casefold().split())


def _covers(row: dict, start: str, end: str | None) -> bool:
    lower = day(row["valid_from"])
    upper = day(row["valid_to"]) if row.get("valid_to") else None
    return lower <= start and (upper is None or (end is not None and end <= upper))


def map_cik(ticker: str, valid_from: str, valid_to: str | None, *, company_tickers: dict,
            submissions: list[dict], observed_at: str, security_name: str | None = None,
            bindings: list[dict] = ()) -> dict:
    """Return a mapping/status dict; never substitute a ticker for an issuer ID."""
    start, end, observed = day(valid_from), day(valid_to) if valid_to else None, knowledge(observed_at)
    if end is not None and end <= start:
        raise ValueError("invalid identity date window")
    candidates = []
    for binding in bindings:
        if binding["ticker"] != ticker or not _covers(binding, start, end):
            continue
        if not binding.get("source") or not binding.get("known_at"):
            raise ValueError("dated identity binding requires source and known_at")
        candidates.append((cik_text(binding["cik"]), knowledge(binding["known_at"]), binding["source"]))
    if not isinstance(company_tickers, dict):
        raise ValueError("unexpected company_tickers shape")
    for index, row in company_tickers.items():
        if not str(index).isdigit() or not isinstance(row, dict) or not {"cik_str", "ticker", "title"} <= row.keys():
            raise ValueError("unexpected company_tickers row")
        cik = cik_text(row["cik_str"])
        if row["ticker"] == ticker and start == observed[:10]:
            candidates.append((cik, observed, "company_tickers"))
    for issuer in submissions:
        cik = cik_text(issuer["cik"])
        if not isinstance(issuer.get("tickers"), list) or not isinstance(issuer.get("formerNames"), list):
            raise ValueError("unexpected submissions identity shape")
        if ticker in issuer["tickers"] and start == observed[:10]:
            candidates.append((cik, observed, "submissions.tickers"))
        for former in issuer["formerNames"]:
            if not isinstance(former, dict) or not {"name", "from", "to"} <= former.keys():
                raise ValueError("unexpected formerNames shape")
            if not security_name or _name(former["name"]) != _name(security_name):
                continue
            # Conservatively exclude the final boundary day: upstream inclusivity
            # is not proven by the recorded contract. Never extend a name window.
            lower, last = day(former["from"][:10]), day(former["to"][:10])
            if lower <= start and end is not None and end <= last:
                candidates.append((cik, observed, "submissions.formerNames+membership.security"))
    ids = {item[0] for item in candidates}
    result = {"ticker": ticker, "valid_from": start, "valid_to": end, "cik": None,
              "status": "unmapped", "known_at": None, "source": None}
    if len(ids) == 1:
        cik, known, source = min(candidates, key=lambda item: (item[1], item[2]))
        result.update(cik=cik, status="mapped", known_at=known, source=source)
    elif ids:
        result["reason"] = "ambiguous_cik"
    else:
        result["reason"] = "no_dated_ticker_identity_evidence"
    return result
