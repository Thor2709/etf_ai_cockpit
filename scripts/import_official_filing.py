"""Offline, provenance-bound import of one official Norwegian ESEF package."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.data.oam_adapters import archive_manual_official_filing
from etf_cockpit.data.statement_normalisation import normalise_statement_facts
from etf_cockpit.parsers.contracts import RawDocument
from etf_cockpit.parsers.esef_ixbrl import parse_esef_package
from etf_cockpit.parsers.sec_facts import statement_facts_from_esef, write_statement_evidence


NORWAY_INSTRUMENT = {
    "ticker": "MING",
    "isin": "NO0006390301",
    "orgnr": "937901003",
    "name": "SpareBank 1 SMN equity certificate",
}
EC_FACT_NAMES = (
    "registered_ec_count",
    "outstanding_ec_count",
    "treasury_ec_count",
    "weighted_average_ec_count",
    "ec_capital",
    "overkursfond",
    "utjevningsfond",
    "sparebankens_fond",
    "gavefond",
    "kompensasjonsfond",
    "eierbrok",
    "ec_attributable_result",
    "major_foundation_holdings",
)


def import_official_filing(
    source_path: Path,
    *,
    jurisdiction: str,
    instrument_id: str,
    source_url: str,
    expected_period: str,
    orgnr: str | None = None,
    lei: str | None = None,
    ticker: str | None = None,
    published_at: str | None = None,
    expected_sha256: str | None = None,
    fact_sheet: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, object]:
    """Import one local ESEF package without making any network request."""

    if str(jurisdiction).strip().upper() != "NO":
        raise ValueError("official filing importer currently supports jurisdiction NO only")
    canonical = str(instrument_id or "").strip().upper().removeprefix("NO:").removeprefix("OSL:")
    if canonical != NORWAY_INSTRUMENT["ticker"]:
        raise ValueError("filing identity is ambiguous: expected the MING listing")
    bound_ticker = str(ticker or canonical).strip().upper()
    if bound_ticker != NORWAY_INSTRUMENT["ticker"]:
        raise ValueError("filing ticker does not match the requested listing")
    bound_orgnr = str(orgnr or NORWAY_INSTRUMENT["orgnr"]).strip()
    if bound_orgnr != NORWAY_INSTRUMENT["orgnr"]:
        raise ValueError("filing organisation number does not match SpareBank 1 SMN")
    if not lei:
        raise ValueError("an issuer LEI (from GLEIF) is required to bind the filing; none is assumed")
    bound_lei = str(lei).strip().upper()
    if len(bound_lei) != 20 or not bound_lei.isalnum():
        raise ValueError("filing LEI must be a 20-character identifier")
    expected = str(expected_period or "").strip()
    if not expected:
        raise ValueError("expected filing period is required")

    output = Path(output_dir or Path("evidence") / "norway" / f"{canonical}-{expected[:4]}").resolve()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    known_at = str(published_at or now).strip()
    source = Path(source_path)
    try:
        payload = source.read_bytes()
    except OSError as exc:
        raise ValueError("Manual official filing import requires a readable local file.") from exc
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.strip().lower():
        raise ValueError("filing checksum does not match expected sha256")

    # Parse and validate in memory.  No archive, queue or evidence path is
    # touched until the complete candidate has passed every check.
    parsed = parse_esef_package(source)
    if not parsed.success or not parsed.records:
        message = "; ".join(warning.message for warning in parsed.warnings if warning.severity in {"error", "fatal"})
        raise ValueError(f"ESEF package rejected: {message or 'no supported facts'}")
    _validate_identity_and_period(parsed.records, bound_lei, expected)
    if any(not str(getattr(record, "consolidation_scope", "") or "").strip() for record in parsed.records):
        raise ValueError("filing consolidation scope is incomplete")
    _validate_units(parsed.records)
    supplied_facts = _load_fact_sheet(fact_sheet)

    output.mkdir(parents=True, exist_ok=True)
    archive = archive_manual_official_filing(
        source,
        jurisdiction="NO",
        instrument_id=canonical,
        source_url=source_url,
        document_type="esef_report_package",
        published_at=known_at,
        available_at=now,
        raw_dir=output / "raw",
        queue_path=output / "manual_filing_queue.parquet",
    )

    facts = statement_facts_from_esef(
        parsed.records,
        instrument_id=canonical,
        source_sha256=archive.sha256,
        source_provider="esef_local_import",
    )
    facts = tuple(
        replace(
            fact,
            filed=known_at[:10],
            available_at=known_at,
            known_at=known_at,
            source_url=source_url,
            filing_version=archive.sha256,
            consolidation_scope=str(getattr(fact, "consolidation_scope", "") or "").strip() or None,
        )
        for fact in facts
    )
    facts_path = output / "statement_facts.parquet"
    inventory_path = output / "filings_statements.parquet"
    write_statement_evidence(
        RawDocument(
            path=Path(archive.raw_path),
            source_url=source_url,
            retrieved_at=datetime.now(timezone.utc),
            sha256=archive.sha256,
            provider_id="esef_local_import",
            document_type="esef_report_package",
            media_type="application/zip",
            http_status=200,
        ),
        facts,
        facts_path,
        inventory_path,
        instrument_id=canonical,
        source_url=source_url,
    )
    normalised = normalise_statement_facts(facts)
    normalised_path = output / "normalised_statements.parquet"
    _append_revision_frame(normalised, normalised_path, "source_id")
    _write_identity(output / "identity.json", canonical, bound_ticker, bound_orgnr, bound_lei, archive, expected, known_at)
    _write_ec_facts(
        supplied_facts,
        output / "ec_facts.json",
        archive,
        canonical,
        expected,
        known_at,
        source_url,
    )
    return {
        "status": "imported",
        "instrument_id": canonical,
        "isin": NORWAY_INSTRUMENT["isin"],
        "ticker": bound_ticker,
        "orgnr": bound_orgnr,
        "lei": bound_lei,
        "period": expected,
        "known_at": known_at,
        "effective_at": expected,
        "sha256": archive.sha256,
        "facts": len(facts),
        "warnings": [warning.message for warning in parsed.warnings if warning.severity == "warning"],
        "facts_path": str(facts_path),
        "normalised_path": str(normalised_path),
        "execution_allowed": False,
    }


def _validate_identity_and_period(records: Iterable[object], expected_lei: str, expected_period: str) -> None:
    items = tuple(records)
    leis = {str(getattr(record, "entity_lei", "") or "").strip().upper() for record in items}
    if not leis or "UNKNOWN" in leis or "" in leis or len(leis) != 1 or next(iter(leis)) != expected_lei:
        raise ValueError("filing issuer identity is ambiguous or does not match the requested LEI")
    period = str(expected_period).strip()
    ends = {str(getattr(record, "period_end", "") or "").strip() for record in items}
    if not any(end == period or end.startswith(period + "-") or (len(period) == 4 and end.startswith(period + "-")) for end in ends):
        raise ValueError("filing report period does not match the expected period")


def _validate_units(records: Iterable[object]) -> None:
    by_concept: dict[str, set[str]] = {}
    currencies: set[str] = set()
    for record in records:
        concept = str(getattr(record, "concept", "")).strip()
        unit = str(getattr(record, "unit", "") or "").strip()
        if not concept or not unit:
            raise ValueError("filing contains a fact with incomplete unit provenance")
        by_concept.setdefault(concept, set()).add(unit)
        if unit.upper() not in {"SHARES", "PURE", "ITEMS", "PERCENT"}:
            currencies.add(unit.split("/", 1)[0].upper())
    if any(len(units) > 1 for units in by_concept.values()) or len(currencies) > 1:
        raise ValueError("filing contains inconsistent units or currencies")


def _append_revision_frame(frame: pd.DataFrame, destination: Path, key: str) -> None:
    existing = pd.read_parquet(destination) if destination.exists() else pd.DataFrame()
    combined = pd.concat([existing, frame], ignore_index=True, sort=False) if not existing.empty else frame
    if key in combined.columns:
        combined = combined.drop_duplicates(subset=[key], keep="last")
    destination.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(destination, index=False)


def _write_identity(destination: Path, instrument_id: str, ticker: str, orgnr: str, lei: str, archive: object, period: str, known_at: str) -> None:
    payload = {
        "instrument_id": instrument_id,
        "ticker": ticker,
        "isin": NORWAY_INSTRUMENT["isin"],
        "lei": lei,
        "orgnr": orgnr,
        "identity_source": "Brønnøysund organisation number + Oslo Børs listing + filed ESEF issuer LEI",
        "source_url": archive.source_url,
        "sha256": archive.sha256,
        "known_at": known_at,
        "effective_at": period,
        "filing_version": archive.sha256,
        "execution_allowed": False,
    }
    atomic_write_json(destination, payload)


def _load_fact_sheet(source: Path | None) -> dict[str, Any]:
    if source is None:
        return {}
    try:
        supplied = json.loads(Path(source).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("EC fact sheet is not valid JSON") from exc
    if not isinstance(supplied, dict):
        raise ValueError("EC fact sheet must contain a JSON object")
    for name, item in supplied.items():
        if name not in EC_FACT_NAMES:
            raise ValueError(f"EC fact {name} is not supported")
        if not isinstance(item, dict) or not item.get("source_locator") or not item.get("unit") or not item.get("period"):
            raise ValueError(f"EC fact {name} lacks source locator, unit or period")
    return supplied


def _write_ec_facts(
    supplied: dict[str, Any],
    destination: Path,
    archive: object,
    instrument_id: str,
    period: str,
    known_at: str,
    source_url: str,
) -> None:
    facts: dict[str, object] = {}
    for name in EC_FACT_NAMES:
        item = supplied.get(name)
        if item is None:
            facts[name] = {
                "available": False,
                "value": None,
                "source_locator": None,
                "unit": None,
                "period": period,
                "known_at": known_at,
                "effective_at": period,
                "source_url": source_url,
                "sha256": archive.sha256,
                "filing_version": archive.sha256,
                "instrument_id": instrument_id,
            }
            continue
        facts[name] = {
            "available": True,
            "value": item.get("value"),
            "source_locator": str(item["source_locator"]),
            "unit": str(item["unit"]),
            "period": str(item["period"]),
            "known_at": known_at,
            "effective_at": period,
            "source_url": source_url,
            "sha256": archive.sha256,
            "filing_version": archive.sha256,
            "instrument_id": instrument_id,
        }
    revision = {
        "instrument_id": instrument_id,
        "filing_version": archive.sha256,
        "sha256": archive.sha256,
        "source_url": source_url,
        "known_at": known_at,
        "effective_at": period,
        "facts": facts,
    }
    revisions: list[dict[str, object]] = []
    if destination.exists():
        try:
            prior = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Existing EC fact evidence is unreadable") from exc
        if isinstance(prior, dict) and isinstance(prior.get("revisions"), list):
            revisions = [item for item in prior["revisions"] if isinstance(item, dict)]
    if not any(item.get("instrument_id") == instrument_id and item.get("sha256") == archive.sha256 for item in revisions):
        revisions.append(revision)
    atomic_write_json(
        destination,
        {
            "schema_version": "norway_ec_facts.v1",
            "facts": facts,
            "source_url": source_url,
            "sha256": archive.sha256,
            "known_at": known_at,
            "effective_at": period,
            "filing_version": archive.sha256,
            "instrument_id": instrument_id,
            "revisions": revisions,
            "execution_allowed": False,
        },
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="local ESEF ZIP/XBRI package")
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--instrument-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--expected-period", required=True)
    parser.add_argument("--orgnr")
    parser.add_argument("--lei")
    parser.add_argument("--ticker")
    parser.add_argument("--published-at")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--fact-sheet", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir or Path("evidence") / "norway" / f"{str(args.instrument_id).strip().upper()}-{str(args.expected_period).strip()[:4]}"
    result = import_official_filing(
        args.path,
        jurisdiction=args.jurisdiction,
        instrument_id=args.instrument_id,
        source_url=args.source_url,
        expected_period=args.expected_period,
        orgnr=args.orgnr,
        lei=args.lei,
        ticker=args.ticker,
        published_at=args.published_at,
        expected_sha256=args.expected_sha256,
        fact_sheet=args.fact_sheet,
        output_dir=output_dir,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
