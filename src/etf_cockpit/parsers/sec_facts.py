"""SEC companyfacts normalisation with fail-closed identity and units."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_bytes, atomic_write_group, parquet_payload, validate_parquet_file
from etf_cockpit.core.file_guard import persistent_file_guard
from etf_cockpit.core.paths import FILINGS_STATEMENTS_PATH
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import ParseResult, ParseWarning, RawDocument, _sha256_file


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
) -> tuple[StatementFact, ...]:
    """Adapt parsed ESEF facts to the versioned statement-facts contract."""

    from etf_cockpit.parsers.esef_ixbrl import map_ifrs_fact

    result: list[StatementFact] = []
    for record in records:
        concept = str(getattr(record, "concept", "") or "")
        unit = str(getattr(record, "unit", "") or "")
        period_end = _record_value(record, "period_end") or None
        period_start = _record_value(record, "period_start") or None
        canonical_metric = map_ifrs_fact(concept, _record_value(record, "namespace") or None)
        source_anchor = f"{concept}:{unit}:{period_start}:{period_end}:{_record_value(record, 'context_id')}"
        provider_id = str(source_provider or "filings_xbrl_org").strip() or "filings_xbrl_org"
        source_id = f"{provider_id}:{source_sha256[:16]}:{hashlib.sha256(source_anchor.encode('utf-8')).hexdigest()[:16]}"
        mapping_status = str(getattr(record, "mapping_status", "") or "")
        namespace = str(_record_value(record, "namespace") or "")
        is_extension = mapping_status == "unmapped_extension" or (namespace and "ifrs" not in namespace.lower())
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
                dimensions="",
                currency=_currency_from_unit(unit),
                period_type="duration" if period_start else "instant",
                mapping_confidence="high" if canonical_metric else "manual_review",
                manual_review_required=canonical_metric is None,
                restatement_kind="reported",
                available_at=None,
            )
        )
    return tuple(result)


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
    cik_normalised = _normalise_cik(payload.get("cik", payload.get("cik_str")))
    if cik_normalised is None:
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
                        canonical_metric=canonical_metric,
                        mapping_status=mapping_status,
                        is_custom=is_custom,
                        dimensions=dimensions,
                        currency=_currency_from_unit(unit),
                        period_type=period_type,
                        mapping_confidence="high" if canonical_metric else "manual_review",
                        manual_review_required=canonical_metric is None,
                        restatement_kind=restatement_kind,
                        available_at=_string(entry.get("filed")),
                    )
                )
    success = bool(records) or (not had_ambiguous_units and not warnings)
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
        yield


def _statement_facts_write_frame(records: tuple[StatementFact, ...], destination: Path, vendor_records: Iterable[object]):
    import pandas as pd

    frame = statement_facts_frame(records)
    existing = _existing_parquet(destination)
    if not existing.empty:
        frame = pd.concat([existing, frame], ignore_index=True, sort=False)
    if "source_id" in frame.columns and not frame.empty:
        frame = frame.drop_duplicates(subset=["source_id"], keep="last")
    authoritative = select_authoritative_facts(frame.to_dict(orient="records"), vendor_records)
    authoritative_ids = {_record_value(record, "source_id") for record in authoritative if _record_value(record, "source_id")}
    frame["authority_selection"] = frame["source_id"].map(lambda source_id: _authority_selection(source_id, source_id in authoritative_ids))
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
            "coverage_status": "imported" if rows else "unavailable",
            "fact_count": len(rows),
            "source_ids": tuple(record.source_id for record in rows),
            "mapping_warnings": tuple(sorted({record.concept for record in rows if record.canonical_metric is None})),
            "executable_authority": False,
        }
    ], columns=["schema_version", "document_id", "instrument_id", "document_type", "path", "source_url", "source_authority", "as_of_date", "ingested_at", "checksum", "coverage_status", "fact_count", "source_ids", "mapping_warnings", "executable_authority"])
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


def select_authoritative_facts(
    sec_records: Iterable[StatementFact],
    vendor_records: Iterable[object],
) -> tuple[object, ...]:
    """Prefer SEC only for exact entity/concept/unit/period matches."""

    official = tuple(sec_records)
    vendors = tuple(vendor_records)
    authoritative = tuple(record for record in official if str(_record_value(record, "source_id")).split(":", 1)[0] in {"sec_edgar", "filings_xbrl_org"})
    retained_non_authoritative = tuple(record for record in official if record not in authoritative)
    grouped: dict[tuple[str, str, str, str], list[object]] = {}
    for record in authoritative:
        grouped.setdefault(_fact_key(record), []).append(record)
    by_key = {key: _preferred_sec_fact(records) for key, records in grouped.items()}
    selected: list[object] = []
    for vendor in vendors:
        winner = by_key.get(_fact_key(vendor))
        if winner is None:
            selected.append(vendor)
        else:
            selected.append(winner)
    vendor_keys = {_fact_key(item) for item in vendors}
    selected.extend(_preferred_sec_fact(records) for key, records in sorted(grouped.items()) if key not in vendor_keys)
    selected.extend(retained_non_authoritative)
    return tuple(selected)


def _preferred_sec_fact(records: Iterable[object]) -> object:
    """Choose one exact-key SEC fact deterministically, preferring latest filing."""

    return max(
        tuple(records),
        key=lambda record: (
            _record_value(record, "filed"),
            1 if str(_record_value(record, "form")).upper().endswith("/A") else 0,
            _record_value(record, "accession"),
            _record_value(record, "source_id"),
        ),
    )


def _fact_key(record: object) -> tuple[str, str, str, str]:
    concept = _record_value(record, "canonical_metric") or _record_value(record, "concept")
    start = _record_value(record, "start")
    end = _record_value(record, "end")
    instant = _record_value(record, "instant")
    fiscal_period = _record_value(record, "fiscal_period")
    if instant or (end and not start):
        period = f"instant:{instant or end}"
    elif start or end:
        period = f"duration:{start}:{end}:{fiscal_period}"
    else:
        period = f"period:{_record_value(record, 'period') or _record_value(record, 'as_of_date')}"
    return _record_value(record, "instrument_id"), concept, _record_value(record, "unit"), period


def _record_value(record: object, name: str, default: object = "") -> str:
    raw = record.get(name, default) if isinstance(record, dict) else getattr(record, name, default)
    return "" if raw is None else str(raw)


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


def _safe_sha(path: Path) -> str:
    try:
        return _sha256_file(path)
    except OSError:
        return ""


def _normalise_cik(value: Any) -> str | None:
    text = str(value or "").strip().upper().removeprefix("CIK")
    if not text or not text.isdigit() or len(text) > 10 or int(text) <= 0:
        return None
    return text.zfill(10)


def _string(value: Any) -> str | None:
    return None if value is None else str(value)


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
