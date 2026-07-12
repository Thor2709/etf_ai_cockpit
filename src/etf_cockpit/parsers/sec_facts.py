"""SEC companyfacts normalisation with fail-closed identity and units."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from etf_cockpit.core.atomic_io import atomic_write_bytes, parquet_payload, validate_parquet_file
from etf_cockpit.core.paths import FILINGS_STATEMENTS_PATH
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import ParseResult, ParseWarning, RawDocument, _sha256_file


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

    @property
    def canonical_mapping(self) -> str | None:
        """Compatibility alias used by export/UI consumers."""

        return self.canonical_metric

    @property
    def mapped_concept(self) -> str | None:
        return self.canonical_metric


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
                source_id = _source_id(cik, taxonomy, concept, str(unit), accession, period, entry)
                records.append(
                    StatementFact(
                        instrument_id=identity.instrument_id,
                        cik=cik,
                        taxonomy=taxonomy,
                        concept=concept,
                        unit=str(unit),
                        value=value,
                        start=_string(entry.get("start")),
                        end=_string(entry.get("end")),
                        instant=_string(entry.get("instant")),
                        filed=_string(entry.get("filed")),
                        form=_string(entry.get("form")),
                        accession=accession,
                        fiscal_year=_int(entry.get("fy")),
                        fiscal_period=_string(entry.get("fp")),
                        source_id=source_id,
                        canonical_metric=canonical_metric,
                        mapping_status=mapping_status,
                        is_custom=is_custom,
                    )
                )
    success = bool(records) or (not had_ambiguous_units and not warnings)
    return ParseResult(tuple(records), tuple(warnings), "sec_companyfacts", "1.1", source_sha, success)


def statement_facts_frame(records: Iterable[StatementFact]):
    import pandas as pd

    rows = [asdict(record) for record in records]
    columns = list(StatementFact.__dataclass_fields__)
    return pd.DataFrame(rows, columns=columns)


def write_statement_facts(records: Iterable[StatementFact], destination: Path) -> Path:
    """Persist clean statement facts as a durable, de-duplicated store."""

    import pandas as pd

    frame = statement_facts_frame(records)
    existing = _existing_parquet(destination)
    if not existing.empty:
        frame = pd.concat([existing, frame], ignore_index=True, sort=False)
    if "source_id" in frame.columns and not frame.empty:
        frame = frame.drop_duplicates(subset=["source_id"], keep="last")
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

    import pandas as pd

    path = source.path if isinstance(source, RawDocument) else Path(source)
    checksum = source.sha256 if isinstance(source, RawDocument) else _safe_sha(path)
    url = source.source_url if isinstance(source, RawDocument) else source_url
    rows = tuple(records)
    frame = pd.DataFrame(
        [
            {
                "document_id": f"sec:{checksum[:20]}",
                "instrument_id": instrument_id or (rows[0].instrument_id if rows else ""),
                "document_type": "sec_companyfacts",
                "path": str(path),
                "source_url": url,
                "source_authority": "official_regulator",
                "as_of_date": max((record.filed or record.end or record.instant or "" for record in rows), default=""),
                "ingested_at": source.retrieved_at.isoformat() if isinstance(source, RawDocument) else "",
                "checksum": checksum,
                "coverage_status": "imported" if rows else "unavailable",
                "fact_count": len(rows),
                "source_ids": tuple(record.source_id for record in rows),
                "mapping_warnings": tuple(sorted({record.concept for record in rows if record.canonical_metric is None})),
                "executable_authority": False,
            }
        ],
        columns=[
            "document_id", "instrument_id", "document_type", "path", "source_url", "source_authority",
            "as_of_date", "ingested_at", "checksum", "coverage_status", "fact_count", "source_ids",
            "mapping_warnings", "executable_authority",
        ],
    )
    output = destination or FILINGS_STATEMENTS_PATH
    existing = _existing_parquet(output)
    if not existing.empty:
        frame = pd.concat([existing, frame], ignore_index=True, sort=False)
    if not frame.empty:
        dedupe_columns = [column for column in ("document_id", "checksum") if column in frame.columns]
        if dedupe_columns:
            frame = frame.drop_duplicates(subset=dedupe_columns, keep="last")
    atomic_write_bytes(output, parquet_payload(frame), validate_parquet_file)
    return output


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

    columns = list(StatementFact.__dataclass_fields__)
    extras = [column for column in frame.columns if column not in columns]
    return frame.reindex(columns=columns + extras)


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
