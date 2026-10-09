"""Offline, provenance-bound import of one official Norwegian ESEF package."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from etf_cockpit.core.atomic_io import atomic_write_json
from etf_cockpit.data.classification import ClassificationEvidence, ClassificationStore
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.oam_adapters import archive_manual_official_filing
from etf_cockpit.data.statement_normalisation import normalise_statement_facts
from etf_cockpit.parsers.contracts import RawDocument
from etf_cockpit.parsers.esef_ixbrl import parse_esef_package
from etf_cockpit.parsers.sec_facts import statement_facts_from_esef, write_statement_evidence


NORWAY_ISSUER_TABLE: dict[str, dict[str, str | None]] = {
    "MING": {"ticker": "MING", "isin": "NO0006390301", "name": "SpareBank 1 SMN", "lei": "7V6Z97IO7R1SEAO84Q32", "orgnr": "937901003"},
    "NONG": {"ticker": "NONG", "isin": "NO0006000801", "name": "SpareBank 1 Nord-Norge", "lei": "549300SXM92LQ05OJQ76", "orgnr": None},
    "RING": {"ticker": "RING", "isin": "NO0006390400", "name": "SpareBank 1 Ringerike Hadeland", "lei": "5967007LIEEXZX73ZK25", "orgnr": None},
    "SOAG": {"ticker": "SOAG", "isin": "NO0010285562", "name": "SpareBank 1 Østfold Akershus", "lei": "5967007LIEEXZX7D8W16", "orgnr": None},
    "SPOL": {"ticker": "SPOL", "isin": "NO0010751910", "name": "SpareBank 1 Østlandet", "lei": "549300VRM6G42M8OWN49", "orgnr": None},
    "MORG": {"ticker": "MORG", "isin": "NO0006390004", "name": "Sparebanken Møre", "lei": "5967007LIEEXZX5PU005", "orgnr": None},
    "SPOG": {"ticker": "SPOG", "isin": "NO0006222009", "name": "Sparebanken Øst", "lei": "5967007LIEEXZX51WW28", "orgnr": None},
    "AURG": {"ticker": "AURG", "isin": None, "name": "Aurskog Sparebank", "lei": "5967007LIEEXZX7H3S04", "orgnr": None},
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
    "cet1_ratio_pct",
    "lcr_pct",
    "nsfr_pct",
    "deposit_to_loan_ratio_pct",
    "deposit_coverage_pct",
    "stage3_pct_gross_loans",
    "net_defaulted_pct_gross_loans",
    "defaulted_pct_gross_loans",
    "net_impaired_pct",
    "net_stage3_pct_net_loans",
)

# SpareBank 1 SMN's own ESEF extension taxonomy.  Extension concepts are
# mapped by exact local name and only when the filing resolves to this issuer
# namespace.  Names outside this table remain retained and unmapped.
MING_EXTENSION_PREFIX = "sb1smn"
MING_EXTENSION_NAMESPACE = "http://aarsrapport.smn.no/2024"
# GiftsAllocation is not evidence of an equity-pool Gavefond; without a
# separately cited pool fact, gavefond remains unavailable.
MING_EXTENSION_CONCEPT_MAP: dict[str, dict[str, str]] = {
    "OtherInterestIncome": {"canonical_metric": "other_interest_income"},
    "ProfitLossBeforeTaxAndImpairment": {"canonical_metric": "profit_before_tax_and_impairment"},
    "ProfitLossAttributableToAdditionalTier1CapitalHolders": {"canonical_metric": "at1_attributable_result"},
    "EgenkapitalbeviseiernesAndelAvPeriodensResultat": {
        "canonical_metric": "ec_attributable_result",
        "ec_fact": "ec_attributable_result",
    },
    "GrunnfondskapitalensAndelAvPeriodensResultat": {"canonical_metric": "foundation_attributable_result"},
    "ComprehensiveIncomeAttributableToAdditionalTier1CapitalHolders": {
        "canonical_metric": "at1_attributable_comprehensive_income"
    },
    "ComprehensiveIncomeAttributableToEquityCapitalCertificateHolders": {
        "canonical_metric": "ec_attributable_comprehensive_income"
    },
    "ComprehensiveIncomeAttributableToTheSavingBankReserve": {
        "canonical_metric": "foundation_attributable_comprehensive_income"
    },
    "SubordinatedLoanCapital": {"canonical_metric": "subordinated_debt"},
    "DividendEqualizationFund": {"canonical_metric": "utjevningsfond", "ec_fact": "utjevningsfond"},
    "DividendAllocation": {"canonical_metric": "dividend_allocation"},
    "OwnerlessCapital": {"canonical_metric": "sparebankens_fond", "ec_fact": "sparebankens_fond"},
    "UnrealisedGainsReserve": {"canonical_metric": "unrealised_gains_reserve"},
    "AdditionalTier1Capital": {"canonical_metric": "additional_tier_1_capital"},
}
MING_IFRS_EC_FACT_MAP = {
    "IssuedCapital": "ec_capital",
    "SharePremium": "overkursfond",
}


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
    canonical = _normalise_ticker(str(instrument_id or "").strip().upper().removeprefix("NO:").removeprefix("OSL:"))
    issuer = NORWAY_ISSUER_TABLE.get(canonical)
    if issuer is None:
        raise ValueError("filing identity is ambiguous: unknown Norwegian issuer ticker")
    bound_ticker = _normalise_ticker(str(ticker or canonical).strip().upper())
    if bound_ticker != canonical:
        raise ValueError("filing ticker does not match the requested listing")
    bound_orgnr = issuer["orgnr"]
    if orgnr:
        supplied_orgnr = str(orgnr).strip()
        if bound_orgnr is None:
            raise ValueError("filing organisation number is not verified for this issuer")
        if supplied_orgnr != bound_orgnr:
            raise ValueError("filing organisation number does not match the issuer table")
    if not lei:
        raise ValueError("an issuer LEI (from GLEIF) is required to bind the filing; none is assumed")
    bound_lei = str(lei).strip().upper()
    if len(bound_lei) != 20 or not bound_lei.isalnum():
        raise ValueError("filing LEI must be a 20-character identifier")
    if bound_lei != issuer["lei"]:
        raise ValueError("filing LEI does not match the issuer table")
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
    filing_facts = _extract_ec_facts(
        parsed.records,
        instrument_id=canonical,
        period=expected,
        sha256=digest,
    )
    for name, item in supplied_facts.items():
        if name in filing_facts and str(filing_facts[name].get("value")) != str(item.get("value")):
            raise ValueError(f"EC fact sheet conflicts with the filing-mapped fact: {name}")
        filing_facts.setdefault(name, item)

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
        extension_namespace=MING_EXTENSION_NAMESPACE if canonical == "MING" else None,
        extension_mappings=(
            {
                concept: values["canonical_metric"]
                for concept, values in MING_EXTENSION_CONCEPT_MAP.items()
            }
            if canonical == "MING"
            else {}
        ),
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
    _write_identity(output / "identity.json", canonical, bound_ticker, bound_orgnr, bound_lei, issuer["isin"], archive, expected, known_at)
    _write_ec_facts(
        filing_facts,
        output / "ec_facts.json",
        archive,
        canonical,
        expected,
        known_at,
        source_url,
    )
    _write_financial_classification(output, canonical, issuer, expected, known_at)
    return {
        "status": "imported",
        "instrument_id": canonical,
        "isin": issuer["isin"],
        "ticker": bound_ticker,
        "orgnr": bound_orgnr,
        "lei": bound_lei,
        "period": expected,
        "known_at": known_at,
        "effective_at": expected,
        "sha256": archive.sha256,
        "facts": len(facts),
        "warnings": [
            warning.message
            for warning in parsed.warnings
            if warning.severity == "warning" and not _mapped_ming_extension_warning(warning, canonical)
        ],
        "facts_path": str(facts_path),
        "normalised_path": str(normalised_path),
        "execution_allowed": False,
    }


def _map_issuer_extension_qname(
    qname: str,
    *,
    output_key: str = "canonical_metric",
) -> str | None:
    """Map one explicit MING extension QName, rejecting foreign prefixes."""

    prefix, separator, local_name = str(qname or "").partition(":")
    if not separator or prefix != MING_EXTENSION_PREFIX:
        return None
    entry = MING_EXTENSION_CONCEPT_MAP.get(local_name)
    return entry.get(output_key) if entry else None


def _mapped_ming_extension_warning(warning: object, instrument_id: str) -> bool:
    if instrument_id != "MING" or str(getattr(warning, "code", "")) != "unmapped_extension":
        return False
    message = str(getattr(warning, "message", ""))
    return any(f"{MING_EXTENSION_PREFIX}:{concept}" in message for concept in MING_EXTENSION_CONCEPT_MAP)


def _extract_ec_facts(
    records: Iterable[object],
    *,
    instrument_id: str,
    period: str,
    sha256: str,
) -> dict[str, dict[str, object]]:
    """Select exact consolidated ESEF facts for the native claim inputs."""

    if instrument_id != "MING":
        return {}
    candidates: dict[str, list[tuple[object, str]]] = {}
    for record in records:
        concept = str(getattr(record, "concept", "") or "")
        namespace = str(getattr(record, "namespace", "") or "")
        if namespace == MING_EXTENSION_NAMESPACE:
            ec_name = _map_issuer_extension_qname(
                f"{MING_EXTENSION_PREFIX}:{concept}", output_key="ec_fact"
            )
            qname = f"{MING_EXTENSION_PREFIX}:{concept}"
        elif "ifrs" in namespace.casefold():
            ec_name = MING_IFRS_EC_FACT_MAP.get(concept)
            qname = f"ifrs-full:{concept}"
        else:
            continue
        if not ec_name or not getattr(record, "is_numeric", True):
            continue
        if str(getattr(record, "period_end", "") or "") != period:
            continue
        if str(getattr(record, "consolidation_scope", "") or "").casefold() != "consolidated":
            continue
        if getattr(record, "context_dimensions", ()):
            continue
        if not str(getattr(record, "unit", "") or "").strip():
            continue
        candidates.setdefault(ec_name, []).append((record, qname))

    extracted: dict[str, dict[str, object]] = {}
    for name, matches in candidates.items():
        if len(matches) != 1:
            continue
        record, qname = matches[0]
        context_id = str(getattr(record, "context_id", "") or "") or None
        start = str(getattr(record, "period_start", "") or "") or None
        end = str(getattr(record, "period_end", "") or "") or None
        source_location = str(getattr(record, "source_location", "") or "")
        locator = f"{source_location}#fact={qname};context={context_id or 'unavailable'}"
        extracted[name] = {
            "value": getattr(record, "value", None),
            "source_locator": locator,
            "concept": qname,
            "context": context_id,
            "unit": str(getattr(record, "unit", "")),
            "period": end or period,
            "start": start,
            "end": end,
            "sha256": sha256,
            "dimensions": getattr(record, "context_dimensions", ()),
            "consolidation_scope": str(getattr(record, "consolidation_scope", "")),
        }
    return extracted


def _validate_identity_and_period(records: Iterable[object], expected_lei: str, expected_period: str) -> None:
    items = tuple(records)
    leis = {str(getattr(record, "entity_lei", "") or "").strip().upper() for record in items}
    if not leis or "UNKNOWN" in leis or "" in leis or len(leis) != 1 or next(iter(leis)) != expected_lei:
        raise ValueError("filing issuer identity is ambiguous or does not match the requested LEI")
    period = str(expected_period).strip()
    ends = {str(getattr(record, "period_end", "") or "").strip() for record in items}
    if not any(end == period or end.startswith(period + "-") or (len(period) == 4 and end.startswith(period + "-")) for end in ends):
        raise ValueError("filing report period does not match the expected period")


def _normalise_ticker(value: str) -> str:
    canonical = str(value or "").strip().upper()
    return canonical[:-3] if canonical.endswith(".OL") else canonical


def _classification_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _classification_storage_root(output: Path) -> Path:
    for candidate in (output, *output.parents):
        if candidate.name.casefold() == "evidence":
            return candidate.parent
    return output


def _write_financial_classification(
    output: Path,
    instrument_id: str,
    issuer: dict[str, str | None],
    period: str,
    known_at: str,
) -> None:
    row_checksum = hashlib.sha256(
        json.dumps(issuer, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence_id = f"norway_savings_bank_issuer_table:{instrument_id}:{row_checksum}"
    effective_at = _classification_timestamp(period)
    available_at = _classification_timestamp(known_at)
    # The verified issuer table establishes these facts for every row: a Norwegian savings bank whose
    # listed instrument is an equity certificate in the financials sector.
    table_facts = (
        ("sector", "financials"),
        ("issuer_type", "savings_bank"),
        ("operating_country", "NO"),
        ("instrument_type", "stock"),
        ("asset_class", "equity"),
        ("instrument_subtype", "equity_certificate"),
    )
    evidences = tuple(
        ClassificationEvidence(
            evidence_id=evidence_id if field == "sector" else f"{evidence_id}:{field}",
            instrument_id=instrument_id,
            field=field,
            value=value,
            source="verified Norwegian savings-bank issuer table",
            authority=SourceAuthority.OFFICIAL,
            source_id=f"norway_savings_bank_issuer_table:{instrument_id}",
            confidence=0.95,
            valid_from=effective_at,
            available_at=available_at,
            source_checksum=row_checksum,
        )
        for field, value in table_facts
    )
    with ClassificationStore(_classification_storage_root(output)) as store:
        current = store.classify(instrument_id, effective_at=effective_at, decision_time=available_at)
        missing = tuple(item for item in evidences if item.evidence_id not in current.evidence_ids)
        if missing:
            store.append_evidence(missing)


def _validate_units(records: Iterable[object]) -> None:
    by_concept: dict[str, set[str]] = {}
    currencies: set[str] = set()
    for record in records:
        concept = str(getattr(record, "concept", "")).strip()
        unit = str(getattr(record, "unit", "") or "").strip()
        if not concept:
            raise ValueError("filing contains a fact with incomplete unit provenance")
        if not unit:
            if not bool(getattr(record, "is_numeric", True)):
                continue
            raise ValueError("filing contains a fact with incomplete unit provenance")
        by_concept.setdefault(concept, set()).add(unit)
        if unit.upper() not in {"SHARES", "PURE", "ITEM", "ITEMS", "PERCENT"} and "/" not in unit:
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


def _write_identity(destination: Path, instrument_id: str, ticker: str, orgnr: str | None, lei: str, isin: str | None, archive: object, period: str, known_at: str) -> None:
    payload = {
        "instrument_id": instrument_id,
        "ticker": ticker,
        "isin": isin,
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


def _bank_economics_evidence(supplied: Mapping[str, object]) -> dict[str, object]:
    """Route cited percent facts to the ratio inputs consumed by the scorecard."""

    def ratio(name: str) -> float | None:
        item = supplied.get(name)
        if not isinstance(item, Mapping) or str(item.get("unit") or "").casefold() != "percent":
            return None
        value = item.get("value")
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number / 100.0 if math.isfinite(number) else None

    def citation(name: str) -> dict[str, object]:
        item = supplied.get(name)
        if not isinstance(item, Mapping):
            return {}
        return {
            key: item[key]
            for key in (
                "source_locator",
                "source_url",
                "sha256",
                "document_title",
                "page",
                "printed_text",
                "page_note",
                "source_citations",
            )
            if key in item
        }

    evidence: dict[str, object] = {}
    cet1 = ratio("cet1_ratio_pct")
    if cet1 is not None:
        evidence["cet1_ratio"] = cet1
        evidence["cet1_ratio_provenance"] = citation("cet1_ratio_pct")

    funding: dict[str, object] = {}
    funding_provenance: dict[str, object] = {}
    for output_name, fact_name in (
        ("lcr", "lcr_pct"),
        ("nsfr", "nsfr_pct"),
    ):
        value = ratio(fact_name)
        if value is not None:
            funding[output_name] = value
            funding_provenance[output_name] = citation(fact_name)
    deposit_fact = next(
        (name for name in ("deposit_to_loan_ratio_pct", "deposit_coverage_pct") if ratio(name) is not None),
        None,
    )
    if deposit_fact is not None:
        funding["deposit_to_loan_ratio"] = ratio(deposit_fact)
        funding_provenance["deposit_to_loan_ratio"] = citation(deposit_fact)
    if funding:
        funding["provenance"] = funding_provenance
        evidence["funding"] = funding

    stage3 = ratio("stage3_pct_gross_loans")
    if stage3 is not None:
        evidence["credit"] = {
            "stage_3_ratio_pct": stage3,
            "provenance": {"stage_3_ratio_pct": citation("stage3_pct_gross_loans")},
        }
    return evidence


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
                "concept": None,
                "context": None,
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
        fact_source_url = str(item.get("source_url") or source_url)
        source_is_filing = fact_source_url == source_url
        facts[name] = {
            "available": item.get("value") is not None,
            "value": item.get("value"),
            "source_locator": str(item["source_locator"]),
            "concept": item.get("concept"),
            "context": item.get("context"),
            "unit": str(item["unit"]),
            "period": str(item["period"]),
            "start": item.get("start"),
            "end": item.get("end", item.get("period")),
            "sha256": item.get("sha256", archive.sha256 if source_is_filing else None),
            "known_at": item.get("known_at", known_at),
            "effective_at": item.get("effective_at", period),
            "source_url": fact_source_url,
            "filing_version": item.get("filing_version", archive.sha256 if source_is_filing else None),
            "instrument_id": instrument_id,
        }
        for citation_field in ("document_title", "page", "printed_text", "page_note", "source_citations"):
            if citation_field in item:
                facts[name][citation_field] = item[citation_field]
    if isinstance(facts.get("gavefond"), dict) and not facts["gavefond"].get("available"):
        facts["gavefond"]["unavailable_reason"] = (
            "No cited equity-pool Gavefond fact was supplied; GiftsAllocation is not substituted."
        )
    bank_economics_evidence = _bank_economics_evidence(supplied)
    revision = {
        "instrument_id": instrument_id,
        "filing_version": archive.sha256,
        "sha256": archive.sha256,
        "source_url": source_url,
        "known_at": known_at,
        "effective_at": period,
        "facts": facts,
        "bank_economics_evidence": bank_economics_evidence,
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
            "bank_economics_evidence": bank_economics_evidence,
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
