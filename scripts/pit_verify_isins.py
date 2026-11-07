"""Verify candidate ISINs for universe stocks against GLEIF ISIN<->LEI relationships (sandbox only).

The owner's universe store is never edited. For each candidate this script checks, in both directions:

1. reverse: ``lei-records?filter[isin]=<ISIN>`` returns exactly one record (status ISSUED) and its legal name
   matches the universe name;
2. forward: ``lei-records/<LEI>/isins`` lists the ISIN.

Only a candidate that passes both checks is ``verified``; it is written, with the source URLs and the UTC time of the
check, to ``data/pit_history/isin_verification.json`` and to the sandbox-only override file
``data/pit_history/universe_isin_overrides.json`` (read by ``scripts/pit_history_backfill.py --isin-overrides``).
A name-only match, an LEI without ISIN relationships, an empty or ambiguous answer is ``unverified`` with its reason
and is never imported. Network use is read-only, one request at a time with a pause between requests.

Usage: python scripts/pit_verify_isins.py --root PATH [--ids CBUK,HO]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

GLEIF = "https://api.gleif.org/api/v1"
REQUEST_PAUSE_SECONDS = 1.0
# Candidate ISINs come from the issuers' public listings (ordinary shares); they are only candidates until GLEIF confirms them.
# A stock without a candidate is looked up by name and stays unverified unless GLEIF itself lists exactly one share-like ISIN.
CANDIDATES: dict[str, dict[str, str]] = {
    "CBUK": {"name": "Cairn Homes plc", "isin": "IE00BWY4ZF18"},
    "HO": {"name": "Hochtief AG", "isin": "DE0006070006"},
    "KMAR": {"name": "Kempower Oyj", "isin": ""},
    "SEC0": {"name": "SECO SpA", "isin": "IT0005438046"},
}
_LEGAL_SUFFIXES = {
    "plc", "public", "limited", "company", "ag", "aktiengesellschaft", "spa", "s", "p", "a", "oyj", "sa", "se", "nv", "ltd", "inc", "corp",
}


def _tokens(name: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", name.lower()) if token not in _LEGAL_SUFFIXES}


def names_match(universe_name: str, legal_name: str) -> bool:
    """The distinctive words of the universe name all appear in the GLEIF legal name (suffixes like plc/AG are ignored)."""

    wanted = _tokens(universe_name)
    return bool(wanted) and wanted <= _tokens(legal_name)


def http_get_json(url: str) -> Mapping[str, object]:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.api+json", "User-Agent": "etf-cockpit-isin-verification"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _records(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [row for row in payload.get("data", ()) if isinstance(row, Mapping)]  # type: ignore[union-attr]


def _legal_name(record: Mapping[str, object]) -> str:
    entity = (record.get("attributes") or {}).get("entity") or {}  # type: ignore[union-attr]
    return str((entity.get("legalName") or {}).get("name") or "")


def _forward_isins(lei: str, get: Callable[[str], Mapping[str, object]], sleep: Callable[[float], None]) -> tuple[list[str], str]:
    url = f"{GLEIF}/lei-records/{lei}/isins?page[size]=200"
    isins: list[str] = []
    first = url
    while url:
        payload = get(url)
        isins.extend(str((row.get("attributes") or {}).get("isin") or "").upper() for row in _records(payload))  # type: ignore[union-attr]
        url = str(((payload.get("links") or {}).get("next")) or "")  # type: ignore[union-attr]
        sleep(REQUEST_PAUSE_SECONDS)
    return isins, first


def verify_candidate(
    instrument_id: str,
    name: str,
    isin: str,
    *,
    get: Callable[[str], Mapping[str, object]] = http_get_json,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """One verification record; ``verified`` is True only when the reverse and the forward check both pass."""

    result: dict[str, object] = {"instrument_id": instrument_id, "name": name, "isin": isin, "verified": False}
    if not isin:
        result["reason"] = "no_candidate_isin: no ISIN to verify; a name-only LEI match is not accepted"
        # informational only: the LEI GLEIF holds for the name and how many ISINs it lists (never imported)
        try:
            found = _records(get(f"{GLEIF}/lei-records?{urlencode({'filter[fulltext]': name})}&page[size]=5"))
            sleep(REQUEST_PAUSE_SECONDS)
            match = next((row for row in found if names_match(name, _legal_name(row))), None)
            if match is not None:
                lei = str(match.get("id") or "").upper()
                isins, _url = _forward_isins(lei, get, sleep)
                result["name_only_lei"] = lei
                result["name_only_lei_isin_count"] = len(isins)
        except Exception as exc:
            result["name_lookup_error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
        result["checked_at"] = now().isoformat(timespec="seconds")
        return result
    reverse_url = f"{GLEIF}/lei-records?{urlencode({'filter[isin]': isin})}"
    try:
        rows = _records(get(reverse_url))
        sleep(REQUEST_PAUSE_SECONDS)
        result["reverse_url"] = reverse_url
        if len(rows) != 1:
            result["reason"] = f"reverse_lookup_returned_{len(rows)}_records"
        else:
            lei = str(rows[0].get("id") or "").strip().upper()
            legal = _legal_name(rows[0])
            status = str(((rows[0].get("attributes") or {}).get("registration") or {}).get("status") or "")  # type: ignore[union-attr]
            result.update(lei=lei, legal_name=legal, lei_status=status)
            if status != "ISSUED":
                result["reason"] = f"lei_status_{status or 'unknown'}"
            elif not names_match(name, legal):
                result["reason"] = "legal_name_does_not_match_universe_name"
            else:
                listed, forward_url = _forward_isins(lei, get, sleep)
                result["forward_url"] = forward_url
                result["lei_isin_count"] = len(listed)
                if isin.upper() in listed:
                    result["verified"] = True
                else:
                    result["reason"] = "forward_lookup_does_not_list_the_isin"
    except Exception as exc:
        result["reason"] = f"gleif_error: {type(exc).__name__}: {str(exc)[:100]}"
    result["checked_at"] = now().isoformat(timespec="seconds")
    return result


def run(root: Path, ids: Sequence[str] | None = None, **kwargs: object) -> dict[str, object]:
    """Verify the candidates, write the verification record and the sandbox-only override file; return the record."""

    wanted = [item for item in CANDIDATES if not ids or item in ids]
    records = [verify_candidate(item, CANDIDATES[item]["name"], CANDIDATES[item]["isin"], **kwargs) for item in wanted]  # type: ignore[arg-type]
    history = Path(root) / "data" / "pit_history"
    history.mkdir(parents=True, exist_ok=True)
    verification = {"source": "GLEIF lei-records (filter[isin] and /isins relationships)", "records": records}
    (history / "isin_verification.json").write_text(json.dumps(verification, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    overrides = {
        str(row["instrument_id"]): {
            "isin": row["isin"],
            "lei": row["lei"],
            "verified_at": row["checked_at"],
            "source": f"GLEIF reverse {row['reverse_url']}; forward {row['forward_url']}",
            "scope": "sandbox only: the owner's universe store is not edited",
        }
        for row in records
        if row.get("verified")
    }
    (history / "universe_isin_overrides.json").write_text(json.dumps(overrides, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return verification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ids", default="")
    args = parser.parse_args(argv)
    verification = run(args.root.resolve(), [item.strip() for item in args.ids.split(",") if item.strip()] or None)
    for row in verification["records"]:  # type: ignore[union-attr]
        print(row["instrument_id"], "VERIFIED" if row["verified"] else "unverified", row.get("isin") or "-", row.get("lei") or "-", row.get("reason") or "")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
