"""SEC companyfacts normalisation with fail-closed identity and units."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_bytes, atomic_write_group, parquet_payload, validate_parquet_file, wait_for_atomic_group
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.paths import FILINGS_STATEMENTS_PATH
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import ParseResult, ParseWarning, RawDocument
from etf_cockpit.parsers.esef_ixbrl import _safe_sha


STATEMENT_FACTS_SCHEMA_VERSION = "statement_facts.v1"
FILINGS_STATEMENTS_SCHEMA_VERSION = "filings_statements.v1"


@dataclass(frozen=True)
class StatementFact:
    instrument_id: str
    cik: str
    taxonomy: str
    concept: str
    unit: str
    value: float | int | str
    start: str | None
    end: str | None
    instant: str | None
    filed: str | None
    form: str | None
    accession: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    source_id: str
    canonical_metric: str | None = None
    mapping_status: str = "unmapped"
    is_custom: bool = False
    dimensions: str = ""
    currency: str | None = None
    period_type: str = "unknown"
    mapping_confidence: str = "unknown"
    manual_review_required: bool = False
    restatement_kind: str = "reported"
    available_at: str | None = None
    known_at: str | None = None
    effective_at: str | None = None
    source_url: str | None = None
    filing_version: str | None = None
    consolidation_scope: str | None = None
    context_id: str | None = None
    sha256: str | None = None

    @property
    def canonical_mapping(self) -> str | None:
        """Compatibility alias used by export/UI consumers."""

        return self.canonical_metric

    @property
    def mapped_concept(self) -> str | None:
        return self.canonical_metric


def statement_facts_from_esef(
    records: Iterable[object],
    *,
    instrument_id: str,
    source_sha256: str,
    source_provider: str = "filings_xbrl_org",
    known_at: str | None = None,
    extension_namespace: str | None = None,
    extension_mappings: Mapping[str, str] | None = None,
) -> tuple[StatementFact, ...]:
    """Adapt parsed ESEF facts to the versioned statement-facts contract.

    ``known_at`` is the time the retained package was acquired; it stamps both
    ``known_at`` and ``available_at`` (the filing date is not known for a local
    import).  Without it the facts stay unavailable for point-in-time views.
    Facts reported in a dimensional context (segment, member, ...) keep their
    dimensional identity and are never mapped to a canonical total metric.
    """

    from etf_cockpit.parsers.esef_ixbrl import is_ifrs_full_namespace, map_ifrs_fact

    result: list[StatementFact] = []
    for record in records:
        concept = str(getattr(record, "concept", "") or "")
        unit = str(getattr(record, "unit", "") or "")
        period_end = _record_value(record, "period_end") or None
        period_start = _record_value(record, "period_start") or None
        dimensions = _esef_dimensions(getattr(record, "context_dimensions", ()))
        mapping_status = str(getattr(record, "mapping_status", "") or "")
        namespace = str(_record_value(record, "namespace") or "")
        canonical_metric = map_ifrs_fact(concept, namespace or None)
        if canonical_metric is None and extension_namespace and namespace == extension_namespace:
            canonical_metric = (extension_mappings or {}).get(concept)
        if is_ifrs_full_namespace(namespace):
            canonical_metric = _ESEF_IFRS_METRIC_OVERRIDES.get(concept, canonical_metric)
        if dimensions or mapping_status in {"unsupported_numeric", "non_numeric"} or not getattr(record, "is_numeric", True):
            canonical_metric = None
        source_anchor = f"{concept}:{unit}:{period_start}:{period_end}:{_record_value(record, 'context_id')}"
        provider_id = str(source_provider or "filings_xbrl_org").strip() or "filings_xbrl_org"
        source_id = f"{provider_id}:{source_sha256[:16]}:{hashlib.sha256(source_anchor.encode('utf-8')).hexdigest()[:16]}"
        is_extension = mapping_status == "unmapped_extension" or (namespace and not is_ifrs_full_namespace(namespace))
        result.append(
            StatementFact(
                instrument_id=instrument_id,
                cik="",
                taxonomy="esef-extension" if is_extension else "ifrs-full",
                concept=concept,
                unit=unit,
                value=getattr(record, "value", ""),
                start=period_start,
                end=period_end,
                instant=period_end if period_start is None else None,
                filed=None,
                form="ESEF",
                accession=None,
                fiscal_year=int(period_end[:4]) if period_end and period_end[:4].isdigit() else None,
                fiscal_period=None,
                source_id=source_id,
                canonical_metric=canonical_metric,
                mapping_status="mapped" if canonical_metric else "unmapped_extension" if is_extension else "unmapped",
                is_custom=is_extension,
                dimensions=dimensions,
                currency=_currency_from_unit(unit),
                period_type="duration" if period_start else "instant",
                mapping_confidence="high" if canonical_metric else "manual_review",
                manual_review_required=canonical_metric is None,
                restatement_kind="reported",
                available_at=known_at,
                known_at=known_at,
                effective_at=period_end,
                source_url=None,
                filing_version=source_sha256,
                consolidation_scope=_record_value(record, "consolidation_scope") or None,
                context_id=_record_value(record, "context_id") or None,
                sha256=source_sha256,
            )
        )
    return tuple(result)


# These IFRS concepts are directly reported in bank statements and have a
# canonical input name used by the financial-sector evidence adapter.  The
# aliases are explicit; extension concepts remain gated by their issuer
# namespace and per-issuer mapping table.
_ESEF_IFRS_METRIC_OVERRIDES = {
    "Assets": "total_assets",
    "ProfitLoss": "net_profit",
    "OtherIncome": "other_operating_income",
    "ImpairmentLossImpairmentGainAndReversalOfImpairmentLossDeterminedInAccordanceWithIFRS9": "impairment_losses",
}


def _esef_dimensions(value: object) -> str:
    """Serialise ESEF context dimensions like SEC ``dimensions``: sorted compact JSON, or empty."""

    if not value:
        return ""
    pairs = [(str(axis), str(member)) for axis, member in value]  # type: ignore[misc]
    return json.dumps(dict(sorted(pairs)), ensure_ascii=False, separators=(",", ":"))


# Deliberately small and explicit.  A fact not listed here is retained for
# review but never promoted to a canonical metric.
_CANONICAL_CONCEPTS = {
    ("us-gaap", "Revenues"): "revenue",
    ("us-gaap", "Revenue"): "revenue",
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"): "revenue",
    ("us-gaap", "SalesRevenueNet"): "revenue",
    ("us-gaap", "Assets"): "assets",
    ("us-gaap", "AssetsCurrent"): "assets_current",
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"): "cash",
    ("us-gaap", "NetIncomeLoss"): "net_income",
    ("us-gaap", "ProfitLoss"): "net_income",
    ("us-gaap", "StockholdersEquity"): "equity",
    ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"): "equity",
    ("us-gaap", "Liabilities"): "liabilities",
    ("us-gaap", "LiabilitiesCurrent"): "liabilities_current",
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"): "cash_from_operations",
    ("us-gaap", "NetCashProvidedByUsedInInvestingActivities"): "cash_from_investing",
    ("us-gaap", "NetCashProvidedByUsedInFinancingActivities"): "cash_from_financing",
    ("us-gaap", "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"): "cash_from_fx",
    ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"): "cash_net_change",
}
_EARLIEST = datetime.min.replace(tzinfo=timezone.utc)
_STANDARD_TAXONOMIES = frozenset({"us-gaap", "dei", "invest", "srt"})


def parse_companyfacts(path: Path, identity: CanonicalIdentity) -> ParseResult[StatementFact]:
    source_sha = _safe_sha(path)
    warnings: list[ParseWarning] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _failure(source_sha, "malformed_json", f"Could not read SEC companyfacts: {type(exc).__name__}")
    if not isinstance(payload, dict):
        return _failure(source_sha, "schema_error", "SEC companyfacts root must be an object")

    expected_cik = _normalise_cik(getattr(identity, "cik", None))
    if expected_cik is None:
        return _failure(source_sha, "identity_missing", "SEC parsing requires a canonical identity CIK")
    supplied_ciks = [payload[key] for key in ("cik", "cik_str") if key in payload]
    normalised_ciks = {_normalise_cik(value) for value in supplied_ciks}
    if len(normalised_ciks) > 1 and None not in normalised_ciks:
        return _failure(source_sha, "identity_mismatch", "SEC companyfacts cik and cik_str disagree")
    cik_normalised = _normalise_cik(payload.get("cik", payload.get("cik_str"))) if len(normalised_ciks) <= 1 else None
    if cik_normalised is None or None in normalised_ciks:
        return _failure(source_sha, "identity_missing", "SEC companyfacts is missing a valid CIK")
    if expected_cik != cik_normalised:
        return _failure(source_sha, "identity_mismatch", f"SEC CIK {cik_normalised} does not match requested identity")
    cik = str(int(cik_normalised))

    facts_root = payload.get("facts")
    if not isinstance(facts_root, dict):
        return _failure(source_sha, "schema_error", "SEC facts object is missing")
    records: list[StatementFact] = []
    seen: set[tuple[Any, ...]] = set()
    had_ambiguous_units = False
    for taxonomy_value, concepts in facts_root.items():
        taxonomy = str(taxonomy_value)
        if not isinstance(concepts, dict):
            warnings.append(ParseWarning("schema_error", f"SEC taxonomy {taxonomy} is not an object", "warning", taxonomy))
            continue
        for concept_value, definition in concepts.items():
            concept = str(concept_value)
            if not isinstance(definition, dict):
                warnings.append(ParseWarning("schema_error", f"SEC concept {concept} is not an object", "warning", concept))
                continue
            units = definition.get("units")
            if not isinstance(units, dict) or not units:
                warnings.append(ParseWarning("missing_unit", f"{concept} has no unit records", "warning", concept))
                continue
            if len(units) != 1:
                had_ambiguous_units = True
                warnings.append(ParseWarning("ambiguous_unit", f"{concept} has multiple unit types", "error", concept))
                continue
            unit, entries = next(iter(units.items()))
            if not isinstance(entries, list):
                warnings.append(ParseWarning("schema_error", f"{concept} unit entries are not a list", "warning", concept))
                continue
            canonical_metric = _CANONICAL_CONCEPTS.get((taxonomy, concept))
            is_custom = taxonomy not in _STANDARD_TAXONOMIES
            if is_custom:
                warnings.append(ParseWarning("custom_concept", f"Custom SEC concept retained without canonical mapping: {taxonomy}:{concept}", "warning", concept))
            mapping_status = "mapped" if canonical_metric else ("custom_unmapped" if is_custom else "unmapped")
            for entry in entries:
                if not isinstance(entry, dict) or "val" not in entry:
                    warnings.append(ParseWarning("malformed_fact", f"{concept} contains a fact without a value", "warning", concept))
                    continue
                value = entry["val"]
                if isinstance(value, (dict, list, tuple, set, bool)):
                    warnings.append(ParseWarning("malformed_fact", f"{concept} contains a non-scalar value", "warning", concept))
                    continue
                if not _is_finite_number(value):
                    warnings.append(ParseWarning("non_numeric_fact", f"{concept} contains a non-finite or non-numeric value; fact rejected", "warning", concept))
                    continue
                key = (
                    taxonomy,
                    concept,
                    str(unit),
                    value,
                    entry.get("start"),
                    entry.get("end"),
                    entry.get("instant"),
                    entry.get("filed"),
                    entry.get("form"),
                    entry.get("accn"),
                    entry.get("fy"),
                    entry.get("fp"),
                    entry.get("frame"),
                )
                if key in seen:
                    warnings.append(ParseWarning("duplicate_fact", f"Duplicate SEC fact ignored: {taxonomy}:{concept}", "warning", concept))
                    continue
                seen.add(key)
                accession = _string(entry.get("accn"))
                period = _string(entry.get("end") or entry.get("instant") or entry.get("filed")) or "undated"
                start_value = _string(entry.get("start"))
                end_value = _string(entry.get("end"))
                instant_value = _string(entry.get("instant")) or (end_value if start_value is None else None)
                dimensions = _dimensions(entry)
                fact_canonical_metric = canonical_metric if not dimensions else None
                fact_mapping_status = mapping_status if fact_canonical_metric else ("custom_unmapped" if is_custom else "unmapped")
                period_type = "duration" if start_value else "instant"
                restatement_kind = "amended" if str(entry.get("form") or "").upper().endswith("/A") else "reported"
                source_id = _source_id(cik, taxonomy, concept, str(unit), accession, period, entry)
                records.append(
                    StatementFact(
                        instrument_id=identity.instrument_id,
                        cik=cik,
                        taxonomy=taxonomy,
                        concept=concept,
                        unit=str(unit),
                        value=value,
                        start=start_value,
                        end=end_value,
                        instant=instant_value,
                        filed=_string(entry.get("filed")),
                        form=_string(entry.get("form")),
                        accession=accession,
                        fiscal_year=_int(entry.get("fy")),
                        fiscal_period=_string(entry.get("fp")),
                        source_id=source_id,
                        canonical_metric=fact_canonical_metric,
                        mapping_status=fact_mapping_status,
                        is_custom=is_custom,
                        dimensions=dimensions,
                        currency=_currency_from_unit(unit),
                        period_type=period_type,
                        mapping_confidence="high" if fact_canonical_metric else "manual_review",
                        manual_review_required=fact_canonical_metric is None,
                        restatement_kind=restatement_kind,
                        available_at=_string(entry.get("filed")),
                    )
                )
    if not records and not had_ambiguous_units and not any(warning.severity == "error" for warning in warnings):
        warnings.append(ParseWarning("no_facts", "SEC companyfacts contains no usable facts", "error"))
    success = bool(records)
    return ParseResult(tuple(records), tuple(warnings), "sec_companyfacts", "1.1", source_sha, success)


def statement_facts_frame(records: Iterable[StatementFact]):
    import pandas as pd

    rows = [asdict(record) for record in records]
    columns = list(StatementFact.__dataclass_fields__) + ["schema_version"]
    frame = pd.DataFrame(rows, columns=list(StatementFact.__dataclass_fields__))
    frame["schema_version"] = STATEMENT_FACTS_SCHEMA_VERSION
    return frame.reindex(columns=columns)


def write_statement_facts(records: Iterable[StatementFact], destination: Path, *, vendor_records: Iterable[object] = ()) -> Path:
    """Persist clean statement facts as a durable, de-duplicated store."""

    records_tuple = tuple(records)
    with _statement_store_guards((destination,)):
        frame = _statement_facts_write_frame(records_tuple, destination, vendor_records)
        frame = _ordered_statement_facts(frame)
        atomic_write_bytes(destination, parquet_payload(frame), validate_parquet_file)
    return destination


def write_statement_inventory(
    source: RawDocument | Path,
    records: Iterable[StatementFact],
    destination: Path | None = None,
    *,
    instrument_id: str = "",
    source_url: str = "",
) -> Path:
    """Publish a one-row filing inventory entry with fact/source IDs."""

    output = destination or FILINGS_STATEMENTS_PATH
    with _statement_store_guards((output,)):
        frame = _statement_inventory_write_frame(source, records, output, instrument_id=instrument_id, source_url=source_url)
        atomic_write_bytes(output, parquet_payload(frame), validate_parquet_file)
    return output


def write_statement_evidence(
    source: RawDocument | Path,
    records: Iterable[StatementFact],
    facts_destination: Path,
    inventory_destination: Path,
    *,
    instrument_id: str = "",
    source_url: str = "",
    vendor_records: Iterable[object] = (),
) -> tuple[Path, Path]:
    """Publish facts and inventory in one recoverable atomic transaction."""

    rows = tuple(records)
    with _statement_store_guards((facts_destination, inventory_destination)):
        facts_frame = _statement_facts_write_frame(rows, facts_destination, vendor_records)
        inventory_frame = _statement_inventory_write_frame(source, rows, inventory_destination, instrument_id=instrument_id, source_url=source_url)
        atomic_write_group(
            (
                AtomicWriteRequest(facts_destination, parquet_payload(_ordered_statement_facts(facts_frame)), validate_parquet_file),
                AtomicWriteRequest(inventory_destination, parquet_payload(inventory_frame), validate_parquet_file),
            )
        )
    return facts_destination, inventory_destination


@contextmanager
def _statement_store_guards(destinations: Iterable[Path]):
    """Serialize every statement-store read-modify-write under stable guards."""

    paths = sorted({Path(destination).resolve() for destination in destinations}, key=lambda path: (str(path).casefold(), str(path)))
    with ExitStack() as stack:
        for path in paths:
            stack.enter_context(persistent_file_guard(path.with_name(f"{path.name}.guard")))
        for path in paths:
            wait_for_atomic_group(path)
        yield


def _statement_facts_write_frame(records: tuple[StatementFact, ...], destination: Path, vendor_records: Iterable[object]):
    import pandas as pd

    frame = statement_facts_frame(records)
    existing = _existing_parquet(destination)
    if not existing.empty:
        frame = pd.concat([existing, frame], ignore_index=True, sort=False)
    if "source_id" in frame.columns and not frame.empty:
        for column in ("available_at", "known_at"):
            if column in frame.columns:
                # Keep the first observed knowledge time when a source is re-imported.
                stamped = frame.loc[frame[column].map(lambda item: isinstance(item, str) and bool(item.strip())), ["source_id", column]]
                first = stamped.groupby("source_id")[column].min()
                mapped = frame["source_id"].map(first)
                frame[column] = mapped.where(mapped.notna(), frame[column])
        frame = frame.drop_duplicates(subset=["source_id"], keep="last")
    authoritative = select_authoritative_facts(frame.to_dict(orient="records"), vendor_records)
    authoritative_ids = {_record_value(record, "source_id") for record in authoritative if _record_value(record, "source_id")}
    frame["authority_selection"] = frame["source_id"].map(lambda source_id: _authority_selection(source_id, source_id in authoritative_ids))
    # Point-in-time companion of ``authority_selection`` (see ``authority_selection_as_of``).
    supersession = _supersession(frame.to_dict(orient="records"))
    frame["superseded_at"] = frame["source_id"].map(lambda source_id: supersession.get(source_id, ""))
    return frame


def _statement_inventory_write_frame(source: RawDocument | Path, records: Iterable[StatementFact], destination: Path, *, instrument_id: str, source_url: str):
    import pandas as pd

    path = source.path if isinstance(source, RawDocument) else Path(source)
    checksum = source.sha256 if isinstance(source, RawDocument) else _safe_sha(path)
    url = source.source_url if isinstance(source, RawDocument) else source_url
    rows = tuple(records)
    frame = pd.DataFrame([
        {
            "schema_version": FILINGS_STATEMENTS_SCHEMA_VERSION,
            "document_id": f"{source.provider_id if isinstance(source, RawDocument) else 'local'}:{checksum[:20]}",
            "instrument_id": instrument_id or (rows[0].instrument_id if rows else ""),
            "document_type": source.document_type if isinstance(source, RawDocument) else "sec_companyfacts",
            "path": str(path),
            "source_url": url,
            "source_authority": _statement_source_authority(source),
            "as_of_date": max((record.filed or record.end or record.instant or "" for record in rows), default=""),
            "ingested_at": source.retrieved_at.isoformat() if isinstance(source, RawDocument) else "",
            "checksum": checksum,
            # Unmapped facts are retained for review but are not evidence coverage.
            "coverage_status": "imported" if any(record.canonical_metric for record in rows) else "unmapped_only" if rows else "unavailable",
            "fact_count": len(rows),
            "mapped_fact_count": sum(1 for record in rows if record.canonical_metric),
            "source_ids": tuple(record.source_id for record in rows),
            "mapping_warnings": tuple(sorted({record.concept for record in rows if record.canonical_metric is None})),
            "executable_authority": False,
        }
    ], columns=["schema_version", "document_id", "instrument_id", "document_type", "path", "source_url", "source_authority", "as_of_date", "ingested_at", "checksum", "coverage_status", "fact_count", "mapped_fact_count", "source_ids", "mapping_warnings", "executable_authority"])
    existing = _existing_parquet(destination)
    if not existing.empty:
        frame = pd.concat([existing, frame], ignore_index=True, sort=False)
    if not frame.empty:
        dedupe_columns = [column for column in ("document_id", "checksum") if column in frame.columns]
        if dedupe_columns:
            frame = frame.drop_duplicates(subset=dedupe_columns, keep="last")
        if "schema_version" not in frame.columns:
            frame["schema_version"] = FILINGS_STATEMENTS_SCHEMA_VERSION
        frame["schema_version"] = frame["schema_version"].fillna(FILINGS_STATEMENTS_SCHEMA_VERSION)
    return frame


def _statement_source_authority(source: RawDocument | Path) -> str:
    if not isinstance(source, RawDocument):
        return "local_unverified"
    if source.provider_id == "sec_local_import" and source.document_type == "sec_companyfacts":
        # A path-only companyfacts import has no hash or source proof (bulk archives keep manual_review).
        return "local_unverified"
    return {
        "filings_xbrl_org": "official_filing",
        "sec_edgar": "official_regulator",
        "esef_local_import": "manual_review",
    }.get(source.provider_id, "manual_review")


def _existing_parquet(path: Path):
    """Read an existing store without silently replacing a corrupt one."""

    import pandas as pd

    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        raise ValueError(f"Existing SEC evidence store is unreadable: {path}") from exc


def _ordered_statement_facts(frame):
    """Keep the public fact schema stable while retaining existing columns."""

    if "schema_version" not in frame.columns:
        frame["schema_version"] = STATEMENT_FACTS_SCHEMA_VERSION
    frame["schema_version"] = frame["schema_version"].fillna(STATEMENT_FACTS_SCHEMA_VERSION)
    columns = list(StatementFact.__dataclass_fields__) + ["schema_version"]
    extras = [column for column in frame.columns if column not in columns]
    return frame.reindex(columns=columns + extras)


# Restatement policy (explicit): for one exact fact key the LATEST fact published at or before the
# as-of time is authoritative; earlier filings stay canonical until the later one is published and a
# later-published fact never masks an earlier one at an earlier as-of.
RESTATEMENT_POLICY = "latest_published_as_of"


def select_authoritative_facts(
    sec_records: Iterable[StatementFact],
    vendor_records: Iterable[object],
    *,
    as_of: str | None = None,
) -> tuple[object, ...]:
    """Prefer SEC only for exact entity/concept/unit/period matches.

    ``as_of`` (optional, point in time) drops official facts not yet published at that time, so a
    later amendment cannot be selected for an earlier decision date.  Date-only publication dates
    count as available from the next day (see ``_available_instant``).
    """

    official = tuple(sec_records)
    vendors = tuple(vendor_records)
    if as_of is not None:
        cutoff = _available_instant(as_of, as_of=True)
        if cutoff is None:
            raise ValueError("as_of must be an ISO date or timestamp")
        official = tuple(
            record for record in official
            if (instant := _available_instant(_publication(record))) is not None and instant <= cutoff
        )
    authoritative = tuple(record for record in official if str(_record_value(record, "source_id")).split(":", 1)[0] in {"sec_edgar", "filings_xbrl_org"})
    retained_non_authoritative = tuple(record for record in official if record not in authoritative)
    grouped: dict[tuple[str, str, str, str, str], list[object]] = {}
    for record in authoritative:
        grouped.setdefault((*_fact_key(record), _scope(record)), []).append(record)
    by_key = {key: _preferred_sec_fact(records) for key, records in grouped.items()}
    selected: list[object] = []
    matched: set[tuple[str, str, str, str, str]] = set()
    for vendor in vendors:
        key = _vendor_match_key(vendor, by_key)
        if key is None:
            selected.append(vendor)
        else:
            matched.add(key)
            winner = by_key[key]
            # One official fact may match several same-key vendor rows: it is selected once.
            if not any(winner is item for item in selected):
                selected.append(winner)
    selected.extend(winner for key, winner in sorted(by_key.items(), key=lambda item: item[0]) if key not in matched)
    selected.extend(retained_non_authoritative)
    return tuple(selected)


def _vendor_match_key(vendor: object, by_key: Mapping[tuple[str, str, str, str, str], object]) -> tuple[str, str, str, str, str] | None:
    """Vendor rows without a scope match only an unscoped or consolidated official fact, never a separate one."""

    base = _fact_key(vendor)
    scope = _scope(vendor)
    for candidate in ((scope,) if scope else ("", "consolidated")):
        key = (*base, candidate)
        if key in by_key:
            return key
    return None


def _scope(record: object) -> str:
    return _record_value(record, "consolidation_scope").strip().casefold()


def _publication(record: object) -> str:
    return _record_value(record, "filed") or _record_value(record, "available_at") or _record_value(record, "known_at")


def _available_instant(value: str, *, as_of: bool = False) -> datetime | None:
    """UTC instant from which a publication/as-of string is usable; ``None`` when absent or malformed.

    A date-only publication date is not an exact midnight: the filing may land at any time that day, so
    it is conservatively available from the start of the NEXT day.  A date-only ``as_of`` is the start
    of that day.
    """

    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            day = datetime.combine(date.fromisoformat(text), time.min, tzinfo=timezone.utc)
            return day if as_of else day + timedelta(days=1)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def authority_selection_as_of(row: Mapping[str, object], as_of: str) -> str:
    """Point-in-time view of a stored ``authority_selection``.

    The stored column is the CURRENT view (latest publication wins).  Before a fact's own publication it
    is unavailable; from a superseding publication (``superseded_at``) on, it is ``retained_*``; before
    that the earlier filing stays canonical.
    """

    stored = str(row.get("authority_selection") or "")
    cutoff = _available_instant(as_of, as_of=True)
    if cutoff is None:
        raise ValueError("as_of must be an ISO date or timestamp")
    if stored not in {"canonical_sec", "retained_sec", "canonical_esef", "retained_esef"}:
        return stored
    published = _available_instant(_publication(row))
    if published is None or published > cutoff:
        return "unavailable"
    superseded = _available_instant(_record_value(row, "superseded_at"))
    family = stored.split("_", 1)[1]
    if superseded is not None and superseded <= cutoff:
        return f"retained_{family}"
    return f"canonical_{family}"


def _preferred_sec_fact(records: Iterable[object]) -> object:
    """Choose one exact-key SEC fact deterministically, preferring the latest publication.

    Publication dates are compared as instants; a malformed or missing date ranks below any valid one
    (never wins by string order).
    """

    def rank(record: object) -> tuple[object, ...]:
        instant = _available_instant(_publication(record))
        return (
            instant is not None,
            instant or _EARLIEST,
            1 if _record_value(record, "form").upper().endswith("/A") else 0,
            _record_value(record, "accession"),
            _record_value(record, "source_id"),
        )

    return max(tuple(records), key=rank)


def _supersession(records: Iterable[Mapping[str, object]]) -> dict[str, str]:
    """source_id -> publication of the next later official fact for the same exact key (``""`` if none)."""

    groups: dict[tuple[str, ...], list[Mapping[str, object]]] = {}
    for record in records:
        if str(record.get("source_id") or "").split(":", 1)[0] in {"sec_edgar", "filings_xbrl_org"}:
            groups.setdefault((*_fact_key(record), _scope(record)), []).append(record)
    result: dict[str, str] = {}
    for group in groups.values():
        dated = [(instant, record) for record in group if (instant := _available_instant(_publication(record))) is not None]
        for instant, record in dated:
            later = [item for item in dated if item[0] > instant]
            result[str(record["source_id"])] = _publication(min(later, key=lambda item: item[0])[1]) if later else ""
    return result


def _fact_key(record: object) -> tuple[str, str, str, str]:
    concept = _record_value(record, "canonical_metric") or _record_value(record, "concept")
    start = _record_value(record, "start")
    end = _record_value(record, "end")
    instant = _record_value(record, "instant")
    if instant or (end and not start):
        period = f"instant:{instant or end}"
    elif start or end:
        # Duration facts match by their start/end dates; the optional fiscal-period label is not identity.
        period = f"duration:{start}:{end}"
    else:
        period = f"period:{_record_value(record, 'period') or _record_value(record, 'as_of_date')}"
    return _record_value(record, "instrument_id"), concept, _record_value(record, "unit"), period


def _record_value(record: object, name: str, default: object = "") -> str:
    raw = record.get(name, default) if isinstance(record, dict) else getattr(record, name, default)
    if raw is None:
        return ""
    try:
        if raw != raw:  # NaN / pandas NA from a stored frame is "absent", never the text "nan"
            return ""
    except (TypeError, ValueError):
        pass
    return str(raw)


def _authority_selection(source_id: object, selected: bool) -> str:
    prefix = str(source_id or "").split(":", 1)[0]
    if prefix in {"esef_local_import", "sec_local_import"}:
        return "manual_review"
    if prefix == "filings_xbrl_org":
        return "canonical_esef" if selected else "retained_esef"
    return "canonical_sec" if selected else "retained_sec"


def _source_id(cik: str, taxonomy: str, concept: str, unit: str, accession: str | None, period: str, entry: dict[str, Any]) -> str:
    stable = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:12]
    anchor = accession or period
    return f"sec_edgar:{cik}:{taxonomy}:{concept}:{unit}:{anchor}:{digest}"


def _failure(source_sha: str, code: str, message: str) -> ParseResult[StatementFact]:
    return ParseResult((), (ParseWarning(code, message, "error"),), "sec_companyfacts", "1.1", source_sha, False)


def _normalise_cik(value: Any) -> str | None:
    text = str(value or "").strip().upper().removeprefix("CIK")
    if not text or not text.isdigit() or len(text) > 10 or int(text) <= 0:
        return None
    return text.zfill(10)


def _string(value: Any) -> str | None:
    return None if value is None else str(value)


def _is_finite_number(value: Any) -> bool:
    """Only real, finite numbers are financial facts (no NaN/Infinity/text/bool)."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _dimensions(entry: dict[str, Any]) -> str:
    value = entry.get("dimensions", entry.get("dim", entry.get("segment", "")))
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _currency_from_unit(unit: object) -> str | None:
    text = str(unit or "").strip().upper()
    if not text:
        return None
    candidate = text.split("/", 1)[0]
    return candidate if len(candidate) == 3 and candidate.isalpha() else None
