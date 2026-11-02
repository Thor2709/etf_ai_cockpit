"""Refresh configured Norwegian equity-certificate filings and rescore banks."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlencode, urljoin, urlparse

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.esef_provider import BASE_URL, FilingsXbrlOrgProvider
from etf_cockpit.data.universe_store import UniverseRecord, is_valid_isin, load_sparebank_records
from etf_cockpit.application.official_filing_import import import_official_filing


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _official_url(url: str) -> str:
    parsed = urlparse(urljoin(BASE_URL, url))
    if parsed.scheme != "https" or parsed.hostname != "filings.xbrl.org":
        raise ValueError("official filing API returned a URL outside filings.xbrl.org")
    return parsed.geturl()


class OfficialFilingClient:
    """Small, bounded extension of the existing filings provider for paging and entities."""

    def __init__(self, cache_dir: Path, transport: Callable | None = None) -> None:
        self.provider = FilingsXbrlOrgProvider(cache_dir=cache_dir, transport=transport)

    def _json(self, url: str) -> dict[str, object]:
        response = self.provider._get(_official_url(url))
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"filings.xbrl.org returned HTTP {response.status}")
        value = json.loads(response.payload.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("filings.xbrl.org returned an invalid JSON object")
        return value

    def filings_for_lei(self, lei: str) -> tuple[dict[str, object], ...]:
        url = f"{BASE_URL}/api/filings?{urlencode({'filter[entity.identifier]': lei, 'page[size]': '200'})}"
        seen: set[str] = set()
        records: list[dict[str, object]] = []
        while url:
            url = _official_url(url)
            if url in seen:
                raise ValueError("filings API pagination repeated a page")
            seen.add(url)
            payload = self._json(url)
            data = payload.get("data", ())
            included = payload.get("included", ())
            included_entities = {
                str(row.get("id") or "").upper(): row
                for row in included
                if isinstance(row, Mapping) and row.get("type") == "entity"
            } if isinstance(included, list) else {}
            if not isinstance(data, list):
                raise ValueError("filings API response has no filing list")
            for row in data:
                if not isinstance(row, Mapping):
                    continue
                attrs = row.get("attributes") if isinstance(row.get("attributes"), Mapping) else {}
                rels = row.get("relationships") if isinstance(row.get("relationships"), Mapping) else {}
                entity = rels.get("entity") if isinstance(rels.get("entity"), Mapping) else {}
                entity_lei = ""
                entity_data = entity.get("data") if isinstance(entity.get("data"), Mapping) else {}
                entity_lei = str(entity_data.get("id") or "").strip().upper()
                if not entity_lei:
                    links = entity.get("links") if isinstance(entity.get("links"), Mapping) else {}
                    related = str(links.get("related") or "").strip()
                    if related:
                        entity_lei = urlparse(urljoin(BASE_URL, related)).path.rstrip("/").split("/")[-1].upper()
                entity_lei = entity_lei or lei.upper()
                if not entity_lei:
                    fxo_id = str(attrs.get("fxo_id") or "")
                    entity_lei = fxo_id[:20].upper() if len(fxo_id) > 20 and fxo_id[20:21] == "-" else ""
                if entity_lei in included_entities:
                    entity_attrs = included_entities[entity_lei].get("attributes")
                    if isinstance(entity_attrs, Mapping):
                        entity_lei = str(entity_attrs.get("identifier") or entity_attrs.get("lei") or entity_lei).strip().upper()
                records.append({"id": str(row.get("id") or ""), **dict(attrs), "entity_lei": entity_lei})
            links = payload.get("links") if isinstance(payload.get("links"), Mapping) else {}
            next_url = links.get("next")
            url = _official_url(str(next_url)) if next_url else ""
        return tuple(records)

    def lookup_lei_by_isin(self, isin: str) -> tuple[str, dict[str, object], str]:
        """Resolve ISIN -> LEI through the GLEIF registry (one exact match required)."""
        import urllib.request

        source_url = f"https://api.gleif.org/api/v1/lei-records?{urlencode({'filter[isin]': isin})}"
        with urllib.request.urlopen(source_url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = [row for row in payload.get("data", ()) if isinstance(row, Mapping)]
        if len(rows) != 1:
            raise ValueError(f"GLEIF returned {len(rows)} LEI records for ISIN {isin}; need exactly one")
        lei = str(rows[0].get("id") or "").strip().upper()
        return lei, {"id": lei, "attributes": dict(rows[0].get("attributes") or {})}, source_url

    def download(self, filing: Mapping[str, object]):
        return self.provider.download_report_package(
            str(filing.get("id") or ""),
            str(filing.get("package_url") or ""),
        )


def _contains_exact_isin(value: object, isin: str) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_exact_isin(child, isin) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_exact_isin(child, isin) for child in value)
    return isinstance(value, str) and value.strip().upper() == isin


def _cached_lei(path: Path, record: UniverseRecord) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping) or payload.get("instrument_id") != record.instrument_id:
        return None
    if str(payload.get("isin") or "").upper() != record.isin.upper():
        return None
    lei = str(payload.get("lei") or "").strip().upper()
    return lei if len(lei) == 20 and lei.isalnum() else None


def _resolve_lei(
    record: UniverseRecord,
    evidence_dir: Path,
    client: object,
    *,
    now: str,
) -> str:
    cache_path = evidence_dir / "lei_resolution.json"
    if record.lei:
        lei = record.lei.upper()
        if len(lei) != 20 or not lei.isalnum():
            raise ValueError("configured LEI is not a valid 20-character identifier")
        atomic_write_json(cache_path, {
            "instrument_id": record.instrument_id,
            "isin": record.isin,
            "lei": lei,
            "source": "configured universe record",
            "cached_at": now,
            "execution_allowed": False,
        })
        return lei
    cached = _cached_lei(cache_path, record)
    if cached:
        return cached
    if not is_valid_isin(record.isin):
        raise ValueError("universe record has no verified ISIN for LEI resolution")
    lookup = getattr(client, "lookup_lei_by_isin")
    lei, entity, source_url = lookup(record.isin.upper())
    if len(str(lei)) != 20 or not str(lei).isalnum():
        raise ValueError("entity lookup returned an invalid LEI")
    entity_bytes = json.dumps(entity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    atomic_write_json(cache_path, {
        "instrument_id": record.instrument_id,
        "isin": record.isin.upper(),
        "lei": str(lei).upper(),
        "source": "GLEIF lei-records API",
        "source_url": source_url,
        "entity_sha256": hashlib.sha256(entity_bytes).hexdigest(),
        "entity": entity,
        "cached_at": now,
        "execution_allowed": False,
    })
    return str(lei).upper()


def _latest_filing(filings: tuple[dict[str, object], ...], lei: str) -> dict[str, object] | None:
    eligible = [
        row for row in filings
        if str(row.get("entity_lei") or "").strip().upper() == lei
        and str(row.get("period_end") or "").strip()
        and str(row.get("package_url") or "").strip()
        and str(row.get("date_added") or "").strip()
    ]
    return max(
        eligible,
        key=lambda row: (
            str(row.get("period_end") or ""),
            str(row.get("date_added") or ""),
            str(row.get("processed") or ""),
            str(row.get("id") or ""),
        ),
        default=None,
    )


def _registry_instant(value: object) -> str:
    """One fixed-width UTC ISO instant for a registry ``date_added``.

    The registry omits the fractional seconds when they are zero; a column that mixes both shapes cannot be parsed in
    one vectorised call (the unparsed rows become NaT and silently lose their knowledge time), so every stamp is
    written with microseconds.
    """

    import pandas as pd

    stamp = pd.Timestamp(str(value).strip())
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.isoformat(timespec="microseconds")


def _history_filings(filings: tuple[dict[str, object], ...], lei: str) -> tuple[dict[str, object], ...]:
    """Every importable filing of the issuer, oldest knowledge first.

    ``date_added`` (the filings.xbrl.org registry date) is the only knowledge time: a filing without one, a period
    end, a package URL or the requested entity is skipped, never dated by the import time. Order is
    (date_added, period_end, id) so the newest filing is imported last and its top-level facts are the latest.
    """

    eligible = [
        row for row in filings
        if str(row.get("entity_lei") or "").strip().upper() == lei
        and str(row.get("period_end") or "").strip()
        and str(row.get("package_url") or "").strip()
        and str(row.get("date_added") or "").strip()
    ]
    return tuple(sorted(
        eligible,
        key=lambda row: (str(row.get("date_added") or ""), str(row.get("period_end") or ""), str(row.get("id") or "")),
    ))


def _import_history(
    official: object,
    importer: Callable,
    record: UniverseRecord,
    lei: str,
    filings: tuple[dict[str, object], ...],
    root: Path,
    source_root: Path,
) -> list[dict[str, object]]:
    """Import every filing into ONE evidence directory (the bank readers take the first directory that holds facts).

    A filing that fails is recorded with its reason and the others still import; nothing is retried here.
    """

    output = root / "evidence" / "norway" / f"{record.instrument_id}-history"
    outcomes: list[dict[str, object]] = []
    for filing in _history_filings(filings, lei):
        outcome: dict[str, object] = {
            "filing_id": str(filing.get("id") or ""),
            "period_end": str(filing.get("period_end") or ""),
            "date_added": str(filing.get("date_added") or ""),
        }
        try:
            package = getattr(official, "download")(filing)
            atomic_write_json(Path(package.path).with_suffix(".json"), {
                "data": [{"id": str(filing.get("id") or ""), "attributes": {**dict(filing), "date_added": _registry_instant(filing["date_added"])}}],
                "source_url": package.source_url,
            })
            imported = importer(
                package.path,
                jurisdiction="NO",
                instrument_id=record.instrument_id,
                source_url=package.source_url,
                expected_period=str(filing.get("period_end") or ""),
                lei=lei,
                ticker=record.ticker,
                published_at=_registry_instant(filing["date_added"]),
                expected_sha256=package.sha256,
                output_dir=output,
                universe_root=source_root,
            )
            outcome.update(status="imported", known_at=str(imported.get("known_at") or ""), facts=imported.get("facts"))
        except Exception as exc:
            outcome.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        outcomes.append(outcome)
    return outcomes


def _rescore(record: UniverseRecord, data_root: Path, universe_root: Path, decision_time: str) -> tuple[float | None, float | None, str]:
    from etf_cockpit.application.financial_institution_views import load_financial_institution_projection

    projection = load_financial_institution_projection(
        record.instrument_id,
        storage_root=data_root,
        universe_root=universe_root,
        decision_time=decision_time,
        effective_at=None,  # latest reported period known at decision_time
        record_history=True,
    )
    identity = projection.get("share_class_identity") if isinstance(projection, Mapping) else None
    analysis = identity.get("sparebank_analysis") if isinstance(identity, Mapping) else None
    scorecard = analysis.get("scorecard") if isinstance(analysis, Mapping) else None
    if isinstance(analysis, Mapping) and isinstance(scorecard, Mapping):
        from etf_cockpit.application.sparebank_peers import peer_row, record_peer_row

        record_peer_row(data_root, peer_row(record.instrument_id, record.name, analysis, decision_time))
    if not isinstance(scorecard, Mapping):
        reason = str(projection.get("reason_code") or projection.get("status") or "scorecard_unavailable")
        return None, None, reason
    composite = scorecard.get("composite_10")
    coverage = scorecard.get("composite_coverage")
    return (
        float(composite) if composite is not None else None,
        float(coverage) if coverage is not None else None,
        str(scorecard.get("status") or "partial"),
    )


def refresh_sparebanks(
    data_root: Path,
    *,
    universe_root: Path | None = None,
    client: object | None = None,
    decision_time: str | None = None,
    importer: Callable = import_official_filing,
    rescorer: Callable = _rescore,
    fetch: bool = True,
    history: bool = False,
    only_ids: set[str] | None = None,
    write_summary: bool = True,
    record_loader: Callable | None = None,
) -> tuple[dict[str, object], ...]:
    """Refresh each enabled configured certificate independently and write a summary.

    ``write_summary=False`` leaves ``sparebank_refresh_summary.json`` untouched (a replay rescoring many past
    decision dates must not overwrite the live refresh record); ``rescore_sparebanks_at`` sets it.

    With ``fetch=False`` no network request is made: the retained evidence is only rescored.
    With ``history=True`` every filing of the issuer is imported (point-in-time backfill, known_at = the registry
    ``date_added`` of each filing) into one ``<id>-history`` evidence directory instead of only the latest; no
    rescoring happens because a rescore would append a score run dated by the backfill time.
    """

    if history and not fetch:
        raise ValueError("history needs fetch=True")

    root = Path(data_root).resolve()
    source_root = Path(universe_root or ROOT).resolve()
    now = decision_time or _utc_now()
    official = client or OfficialFilingClient(root / "data" / "raw" / "esef")
    loader = load_sparebank_records if record_loader is None else record_loader
    records = tuple(item for item in loader(source_root) if not only_ids or item.instrument_id in only_ids)
    summaries: list[dict[str, object]] = []
    for record in records:
        bank_evidence = root / "evidence" / "norway" / record.instrument_id
        if fetch:  # a rescore-only call creates nothing
            bank_evidence.mkdir(parents=True, exist_ok=True)
        lei = ""
        filing_date = ""
        reason = ""
        history_rows: list[dict[str, object]] = []
        try:
            if history:
                lei = _resolve_lei(record, bank_evidence, official, now=now)
                filings = tuple(official.filings_for_lei(lei))
                history_rows = _import_history(official, importer, record, lei, filings, root, source_root)
                if not history_rows:
                    reason = "no_filing_found"
                elif all(row["status"] != "imported" for row in history_rows):
                    reason = "history_import_failed"
                filing_date = max((str(row.get("known_at") or "") for row in history_rows if row["status"] == "imported"), default="")
            elif not fetch:
                lei = record.lei or ""
                filing = None
                reason = "not_fetched"
            else:
                lei = _resolve_lei(record, bank_evidence, official, now=now)
                filing = _latest_filing(tuple(official.filings_for_lei(lei)), lei)
            if history or not fetch:
                pass
            elif filing is None:
                reason = "no_filing_found"
            else:
                filing_date = str(filing["date_added"])
                package = getattr(official, "download")(filing)
                metadata_path = Path(package.path).with_suffix(".json")
                metadata = {
                    "data": [{"id": str(filing.get("id") or ""), "attributes": dict(filing)}],
                    "source_url": package.source_url,
                }
                atomic_write_json(metadata_path, metadata)
                imported = importer(
                    package.path,
                    jurisdiction="NO",
                    instrument_id=record.instrument_id,
                    source_url=package.source_url,
                    expected_period=str(filing.get("period_end") or ""),
                    lei=lei,
                    ticker=record.ticker,
                    published_at=filing_date,
                    expected_sha256=package.sha256,
                    output_dir=root / "evidence" / "norway" / f"{record.instrument_id}-{str(filing.get('period_end') or '')[:4]}",
                    universe_root=source_root,
                )
                filing_date = str(imported.get("known_at") or filing_date)
        except Exception as exc:
            if not reason:
                reason = f"refresh_failed: {type(exc).__name__}: {exc}"

        if history:
            summaries.append({
                "id": record.instrument_id,
                "lei": lei or record.lei or "",
                "filing_date": filing_date,
                "composite": None,
                "coverage": None,
                "reason": reason,
                "history": history_rows,
            })
            continue
        try:
            if decision_time is None:
                from etf_cockpit.application.identity_views import load_classification_projection

                load_classification_projection(
                    record.instrument_id,
                    storage_root=root,
                    universe_root=source_root,
                )
                score_time = _utc_now()
            else:
                score_time = now
            composite, coverage, score_status = rescorer(record, root, source_root, score_time)
            if score_status not in {"complete", "partial"}:
                failure = f"rescore_failed: {score_status}"
                reason = f"{reason}; {failure}" if reason else failure
        except Exception as exc:
            composite, coverage = None, None
            failure = f"rescore_failed: {type(exc).__name__}: {exc}"
            reason = f"{reason}; {failure}" if reason else failure
        summaries.append({
            "id": record.instrument_id,
            "lei": lei or record.lei or "",
            "filing_date": filing_date,
            "composite": composite,
            "coverage": coverage,
            "reason": reason,
        })

    if not write_summary:
        return tuple(summaries)
    banks: list[dict[str, object]] = list(summaries)
    # a history run has no scores: it gets its own file so the live refresh record keeps its composite/coverage
    summary_path = root / "evidence" / "norway" / ("sparebank_history_summary.json" if history else "sparebank_refresh_summary.json")
    if only_ids and summary_path.is_file():  # a partial run replaces its own banks and keeps the others' record
        try:
            previous = json.loads(summary_path.read_text(encoding="utf-8")).get("banks", [])
        except (OSError, ValueError):
            previous = []
        banks = [item for item in previous if isinstance(item, dict) and item.get("id") not in only_ids] + banks
    report = {"generated_at": now, "banks": banks, "execution_allowed": False}
    atomic_write_json(summary_path, report)
    return tuple(summaries)


def decision_instant(decision: object) -> str:
    """The decision-time string used by the rescore: a date means the end of that UTC day (23:59:59), as
    ``stock_universe.live_decision_time`` does; a datetime must be timezone-aware. Anything else fails closed."""

    if isinstance(decision, datetime):
        moment = decision
    elif hasattr(decision, "isoformat") and not isinstance(decision, str):  # datetime.date
        moment = datetime(decision.year, decision.month, decision.day, 23, 59, 59, tzinfo=timezone.utc)  # type: ignore[attr-defined]
    else:
        text = str(decision or "").strip()
        if not text:
            raise ValueError("decision_time is required")
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if len(text) == 10:  # a bare YYYY-MM-DD
            moment = moment.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def rescore_sparebanks_at(
    data_root: Path,
    decision: object,
    *,
    universe_root: Path | None = None,
    only_ids: set[str] | None = None,
    rescorer: Callable = _rescore,
    record_loader: Callable | None = None,
) -> tuple[dict[str, object], ...]:
    """Per-decision-date rescore hook for a score-history backfill (no network, no summary file).

    Equivalent to ``refresh_sparebanks(data_root, fetch=False, decision_time=D, write_summary=False)``: the retained
    filing evidence visible at ``D`` (``known_at <= D``) is scored and one score run per certificate is appended to
    the score history with ``data_as_of_date`` = the decision day. ``decision`` is a date (end of that UTC day), an
    ISO date or an aware datetime. ``universe_root`` defaults to ``data_root``. Each returned row has
    ``id``, ``composite``, ``coverage`` and ``reason``; a certificate without a filing known at ``D`` is
    ``unavailable`` with its reason, never a number. Usage from ``scripts/backfill_score_history.py``::

        from etf_cockpit.application.sparebank_refresh import rescore_sparebanks_at
        rows = rescore_sparebanks_at(root, decision_day)
    """

    rows = refresh_sparebanks(
        Path(data_root),
        universe_root=Path(universe_root or data_root),
        decision_time=decision_instant(decision),
        fetch=False,
        only_ids=only_ids,
        rescorer=rescorer,
        write_summary=False,
        record_loader=record_loader,
    )
    # nothing is fetched by design, so the refresh's "not_fetched" marker is not a finding of this call
    cleaned = []
    for row in rows:
        reasons = [part for part in str(row.get("reason") or "").split("; ") if part and part != "not_fetched"]
        cleaned.append({**row, "reason": "; ".join(reasons)})
    return tuple(cleaned)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="data root to update")
    parser.add_argument("--universe-root", type=Path, default=ROOT, help="root containing the universe store or configs")
    parser.add_argument("--rescore-only", action="store_true", help="make no network request; rescore the retained evidence")
    parser.add_argument("--ids", default="", help="comma separated certificate ids to refresh (default: all enabled)")
    parser.add_argument(
        "--history",
        action="store_true",
        help="import every filing per issuer (known_at = registry date_added) into <id>-history; no rescore",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = refresh_sparebanks(args.root, universe_root=args.universe_root, fetch=not args.rescore_only, history=args.history,
        only_ids={item.strip() for item in args.ids.split(",") if item.strip()} or None,
    )
    print("id\tLEI\tfiling date\tcomposite\tcoverage\treason")
    for row in rows:
        print("\t".join(str(row.get(key) if row.get(key) is not None else "") for key in ("id", "lei", "filing_date", "composite", "coverage", "reason")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
