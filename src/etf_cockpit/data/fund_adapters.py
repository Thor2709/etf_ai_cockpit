"""Explicit, point-in-time adapters for fund evidence and SEC bulk datasets.

Network access is opt-in at the run boundary. Quarterly SEC archives are
acquired only through :mod:`sec_edgar_bulk`, which supplies resumable,
content-addressed storage and bounded ZIP validation.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd

from etf_cockpit.data.contracts import SourceAuthority, preferred_authority, redact_text
from etf_cockpit.data.fund_holdings import HoldingsNormalisationResult, normalise_holdings
from etf_cockpit.data.sec_edgar_bulk import fetch_bulk


EVIDENCE_TYPE = "sec_official"
UNKNOWN = "UNKNOWN"
_PERIOD_PATTERN = re.compile(r"(?P<year>20\d{2})q(?P<quarter>[1-4])", re.IGNORECASE)
_COVERAGE_COLUMNS = (
    "instrument_id", "accession_number", "report_date", "market", "market_basis", "asset_type",
    "evidence_type", "denominator_pct", "mapped_pct", "unknown_pct", "coverage_pct", "unknown_reason",
)


def fetch_etf_economics_sources(
    instrument_id: str,
    *,
    decision_time: object,
    issuer_reader: object,
    public_reader: object,
    vendor_reader: object,
) -> dict[str, object]:
    """Acquire explicit source bindings in priority order, with offline readers.

    Readers return dated records for the exact instrument. URLs and identities
    belong to those bindings; this adapter never constructs issuer addresses.
    All available sources are retained so disagreements can be displayed.
    This function does not publish records or confer scoring authority.
    """
    from etf_cockpit.data.etf_economics import load_etf_e1_fields

    records = []
    failures = {}
    failure_details = {}
    for name, reader in (("issuer", issuer_reader), ("public_page", public_reader), ("yfinance", vendor_reader)):
        try:
            rows = reader(instrument_id) if callable(reader) else ()
            records.append(list(rows))
        except Exception as exc:
            records.append([])
            failures[name] = type(exc).__name__
            failure_details[name] = redact_text(f"{type(exc).__name__}: {exc}")
    cutoff = decision_time() if callable(decision_time) else decision_time
    fields = load_etf_e1_fields(instrument_id, decision_time=cutoff, issuer_records=records[0], public_records=records[1], vendor_records=records[2])
    return {"fields": fields, "records": records, "failures": failures, "failure_details": failure_details, "execution_allowed": False}


@dataclass(frozen=True)
class SecFundAdapterRun:
    """Result of one explicit N-PORT/N-CEN period acquisition and parse."""

    documents: Mapping[str, object]
    nav_observations: tuple[dict[str, object], ...]
    holdings: tuple[HoldingsNormalisationResult, ...]
    identity_records: tuple[dict[str, object], ...]
    coverage_denominators: pd.DataFrame
    resolved_evidence: tuple[dict[str, object], ...]
    conflicts: tuple[dict[str, object], ...]
    failures: Mapping[str, str]


def _period_dataset(form: str, period: str) -> str:
    """Return an SEC bulk dataset key for a documented quarterly archive."""

    match = _PERIOD_PATTERN.fullmatch(str(period).strip())
    if match is None:
        raise ValueError("SEC fund bulk period must use YYYYqN form")
    year, quarter = int(match.group("year")), int(match.group("quarter"))
    if form == "nport" and (year, quarter) < (2019, 4):
        raise ValueError("SEC N-PORT bulk archives begin in 2019q4")
    if form == "ncen" and (year, quarter) < (2018, 3):
        raise ValueError("SEC N-CEN bulk archives begin in 2018q3")
    if form not in {"nport", "ncen"}:
        raise ValueError("SEC fund bulk form must be nport or ncen")
    return f"{form}_{year}q{quarter}"


def _canonical_cik(value: object) -> str:
    text = str(value or "").strip()
    if not text.isdecimal():
        return ""
    return text.lstrip("0").zfill(10)


def _acceptance_time(value: object) -> str | None:
    """Keep only an explicit timezone-aware acceptance timestamp."""

    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.isoformat()


def _accepted_at(row: Mapping[str, str], accepted_at_by_accession: Mapping[str, object]) -> tuple[str | None, str | None]:
    accession = row.get("ACCESSION_NUMBER", "").strip()
    supplied = accepted_at_by_accession.get(accession)
    if supplied is not None:
        accepted = _acceptance_time(supplied)
        if accepted is not None:
            return accepted, None
        return None, "invalid_or_timezone_missing_acceptance_time"
    for name in ("ACCEPTANCE_DATETIME", "ACCEPTANCE-DATETIME", "ACCEPTED_AT"):
        if row.get(name):
            accepted = _acceptance_time(row[name])
            if accepted is not None:
                return accepted, None
            return None, "invalid_or_timezone_missing_acceptance_time"
    # SEC N-PORT/N-CEN bulk SUBMISSION tables expose filing dates, not the
    # EDGAR acceptance timestamp. Retrieval time is never a substitute.
    return None, "sec_bulk_dataset_omits_acceptance_time"


def _date_field(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _zip_table(archive: zipfile.ZipFile, name: str, *, required: bool = True):
    target = name.upper()
    info = next(
        (
            member for member in archive.infolist()
            if not member.is_dir() and Path(member.filename).stem.upper() == target
        ),
        None,
    )
    if info is None:
        if required:
            raise ValueError(f"SEC fund archive is missing {target}.tsv")
        return iter(())

    def rows():
        with archive.open(info, "r") as binary:
            with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as text:
                reader = csv.DictReader(text, delimiter="\t")
                if reader.fieldnames is None:
                    raise ValueError(f"SEC fund table {target} has no header")
                for source_row in reader:
                    yield {
                        str(key or "").strip().upper(): str(value or "").strip()
                        for key, value in source_row.items()
                    }

    return rows()


def _instrument_map(funds: Mapping[tuple[str, str], str]) -> tuple[dict[tuple[str, str], str], set[str]]:
    result: dict[tuple[str, str], str] = {}
    for key, instrument_id in funds.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise ValueError("fund mapping keys must be (CIK, series ID) pairs")
        cik, series_id = _canonical_cik(key[0]), str(key[1] or "").strip()
        instrument = str(instrument_id or "").strip()
        if not cik or not series_id or not instrument:
            raise ValueError("fund mapping requires a CIK, series ID, and instrument ID")
        result[(cik, series_id)] = instrument
    return result, {cik for cik, _series in result}


def _decimal_percentage(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _coverage_row(
    instrument_id: str | None,
    accession: str | None,
    report_date: date | None,
    market: str,
    asset_type: str,
    denominator: Decimal,
    mapped: Decimal,
    reason: str,
) -> dict[str, object]:
    denominator_float, mapped_float = float(denominator), float(mapped)
    return {
        "instrument_id": instrument_id,
        "accession_number": accession,
        "report_date": report_date.isoformat() if report_date else None,
        "market": market,
        "market_basis": "sec_investment_country" if market != UNKNOWN else "unknown",
        "asset_type": asset_type,
        "evidence_type": EVIDENCE_TYPE,
        "denominator_pct": denominator_float,
        "mapped_pct": mapped_float,
        "unknown_pct": denominator_float - mapped_float,
        "coverage_pct": mapped_float,
        "unknown_reason": reason,
    }


def _unknown_coverage(instrument_id: str | None, reason: str, *, accession: str | None = None, report_date: date | None = None) -> dict[str, object]:
    return _coverage_row(instrument_id, accession, report_date, UNKNOWN, UNKNOWN, Decimal("100"), Decimal("0"), reason)


def _holdings_for_filing(
    *,
    instrument_id: str,
    accession: str,
    report_date: date | None,
    filing_date: date | None,
    filing_row: Mapping[str, str],
    nav_row: Mapping[str, str] | None,
    holding_rows: Sequence[Mapping[str, str]],
    identifiers: Mapping[str, Mapping[str, str]],
    accepted_at_by_accession: Mapping[str, object],
    dataset_sha256: str | None,
    today: str | date | datetime | None,
) -> tuple[HoldingsNormalisationResult, list[dict[str, object]], list[dict[str, object]]]:
    accepted_at, acceptance_reason = _accepted_at(filing_row, accepted_at_by_accession)
    mapped_rows: list[dict[str, object]] = []
    buckets: dict[tuple[str, str], list[object]] = defaultdict(lambda: [Decimal("0"), Decimal("0"), set()])
    parsed_weights: list[tuple[Mapping[str, str], Mapping[str, str], Decimal]] = []
    invalid_weight = False
    for row in holding_rows:
        percent = _decimal_percentage(row.get("PERCENTAGE", ""))
        if percent is None or percent < 0:
            invalid_weight = True
            break
        parsed_weights.append((row, identifiers.get(row.get("HOLDING_ID", ""), {}), percent))
    raw_total = sum((item[2] for item in parsed_weights), Decimal("0"))
    if not parsed_weights or invalid_weight or raw_total > Decimal("100"):
        reason = "holdings_percentage_missing_or_invalid" if invalid_weight or not parsed_weights else "holdings_percentage_exceeds_nav"
        coverage = [_unknown_coverage(instrument_id, reason, accession=accession, report_date=report_date)]
    else:
        mapped_total = Decimal("0")
        for holding, extra_ids, percent in parsed_weights:
            if percent == 0:
                continue
            country = holding.get("INVESTMENT_COUNTRY", "").upper() or UNKNOWN
            asset_type = holding.get("ASSET_CAT", "").upper() or UNKNOWN
            market_bucket = buckets[(country, asset_type)]
            market_bucket[0] = market_bucket[0] + percent
            security = holding.get("ISSUER_NAME", "") or holding.get("ISSUER_TITLE", "")
            isin = extra_ids.get("IDENTIFIER_ISIN", "")
            ticker = extra_ids.get("IDENTIFIER_TICKER", "")
            cusip = holding.get("ISSUER_CUSIP", "")
            if security and (isin or ticker or cusip):
                market_bucket[1] = market_bucket[1] + percent
                mapped_total += percent
                mapped_rows.append({
                    "security": security,
                    "weight": float(percent / Decimal("100")),
                    "isin": isin,
                    "ticker": ticker,
                    "security_id": cusip,
                    "security_id_namespace": "CUSIP" if cusip else "",
                    "country": country if country != UNKNOWN else "",
                    "instrument_type": asset_type if asset_type != UNKNOWN else "",
                })
            else:
                reasons = market_bucket[2]
                reasons.add("holding_identity_missing")
        residual = Decimal("100") - raw_total
        if residual:
            buckets[(UNKNOWN, UNKNOWN)][0] += residual
            buckets[(UNKNOWN, UNKNOWN)][2].add("unreported_nav_weight")
        coverage = [
            _coverage_row(
                instrument_id,
                accession,
                report_date,
                market,
                asset_type,
                values[0],
                values[1],
                ";".join(sorted(values[2])),
            )
            for (market, asset_type), values in sorted(buckets.items())
        ]
        # The existing holdings contract accepts 99%-101% as full. Coverage
        # itself uses exact percentage points and assigns every residual to
        # unknown, so mapped + unknown always conserves the 100% NAV base.
        if mapped_total > Decimal("100"):
            mapped_rows = []
            coverage = [_unknown_coverage(instrument_id, "mapped_holdings_exceed_nav", accession=accession, report_date=report_date)]

    holding_frame = pd.DataFrame(mapped_rows, columns=(
        "security", "weight", "isin", "ticker", "security_id", "security_id_namespace", "country", "instrument_type",
    ))
    if not holding_frame.empty:
        # SEC may report separate lots with the same public identity. The
        # shared normalizer removes exact duplicate rows, so aggregate those
        # lots first to keep their full reported percentage in mapped coverage.
        identity_columns = [column for column in holding_frame.columns if column != "weight"]
        holding_frame = holding_frame.groupby(identity_columns, dropna=False, sort=False, as_index=False)["weight"].sum()
    result = normalise_holdings(
        holding_frame,
        instrument_id,
        report_date.isoformat() if report_date else "",
        "sec_nport",
        today=today,
    )
    if not result.frame.empty:
        enriched = result.frame.copy()
        enriched["accession_number"] = accession
        enriched["filing_date"] = filing_date.isoformat() if filing_date else None
        enriched["known_at"] = accepted_at
        enriched["known_at_reason"] = acceptance_reason
        enriched["evidence_type"] = EVIDENCE_TYPE
        enriched["dataset_sha256"] = dataset_sha256
        result = replace(result, frame=enriched)
    if acceptance_reason:
        result = replace(result, warnings=(*result.warnings, acceptance_reason))

    observations: list[dict[str, object]] = []
    net_assets = _decimal_percentage(nav_row.get("NET_ASSETS", "")) if nav_row else None
    nav_reason = None if net_assets is not None else "net_assets_missing_or_invalid"
    lag_days = (filing_date - report_date).days if filing_date and report_date else None
    observations.append({
        "instrument_id": instrument_id,
        "metric": "net_assets",
        "value": str(net_assets) if net_assets is not None else None,
        "currency": None,
        "as_of": report_date.isoformat() if report_date else None,
        "filing_date": filing_date.isoformat() if filing_date else None,
        "filing_lag_days": lag_days,
        "known_at": accepted_at,
        "known_at_reason": acceptance_reason or ("filing_acceptance_time_missing" if accepted_at is None else None),
        "retrieved_at": None,
        "dealing_eligibility": None,
        "dealing_eligibility_reason": "not_reported_by_n_port_bulk_dataset",
        "value_reason": nav_reason,
        "accession_number": accession,
        "source": "sec_nport",
        "source_id": f"sec_nport:{accession}",
        "authority": SourceAuthority.OFFICIAL.value,
        "evidence_type": EVIDENCE_TYPE,
        "dataset_sha256": dataset_sha256,
    })
    return result, coverage, observations


def parse_sec_nport_archive(
    path: Path,
    funds: Mapping[tuple[str, str], str],
    *,
    accepted_at_by_accession: Mapping[str, object] | None = None,
    dataset_sha256: str | None = None,
    retrieved_at: datetime | str | None = None,
    today: str | date | datetime | None = None,
) -> tuple[tuple[HoldingsNormalisationResult, ...], tuple[dict[str, object], ...], pd.DataFrame]:
    """Parse a SEC N-PORT quarterly TSV archive for explicitly mapped funds.

    SEC ``PERCENTAGE`` is the reported value compared with fund net assets and
    is divided by 100 for ``normalise_holdings``. The coverage denominator is
    the standard 100% NAV base; percentages that cannot be reconciled are kept
    as unknown. ``INVESTMENT_COUNTRY`` is retained only as the issuer-country
    market bucket and is never treated as an exchange or dealing market.
    """

    instrument_map, target_ciks = _instrument_map(funds)
    if not instrument_map:
        raise ValueError("SEC N-PORT parsing requires explicit (CIK, series ID) fund mappings")
    accepted = accepted_at_by_accession or {}
    with zipfile.ZipFile(Path(path), "r") as archive:
        registrants = {
            row.get("ACCESSION_NUMBER", ""): row
            for row in _zip_table(archive, "REGISTRANT")
            if row.get("ACCESSION_NUMBER") and _canonical_cik(row.get("CIK")) in target_ciks
        }
        submissions = {
            row.get("ACCESSION_NUMBER", ""): row
            for row in _zip_table(archive, "SUBMISSION")
            if row.get("ACCESSION_NUMBER") in registrants
        }
        fund_info: dict[str, tuple[str, str]] = {}
        for row in _zip_table(archive, "FUND_REPORTED_INFO"):
            accession = row.get("ACCESSION_NUMBER", "")
            registrant = registrants.get(accession)
            series_id = row.get("SERIES_ID", "")
            if not registrant or not series_id:
                continue
            key = (_canonical_cik(registrant.get("CIK")), series_id)
            instrument = instrument_map.get(key)
            if instrument:
                fund_info[accession] = (series_id, instrument)
        selected = {accession: info for accession, info in fund_info.items() if accession in submissions}
        holdings_by_accession: dict[str, list[Mapping[str, str]]] = defaultdict(list)
        selected_ids: set[str] = set()
        for row in _zip_table(archive, "FUND_REPORTED_HOLDING"):
            accession = row.get("ACCESSION_NUMBER", "")
            if accession in selected:
                holdings_by_accession[accession].append(row)
                if row.get("HOLDING_ID"):
                    selected_ids.add(row["HOLDING_ID"])
        identifiers: dict[str, dict[str, str]] = defaultdict(dict)
        for row in _zip_table(archive, "IDENTIFIERS", required=False):
            holding_id = row.get("HOLDING_ID", "")
            if holding_id in selected_ids:
                identifiers[holding_id].update(row)
        nav_by_accession = {
            row.get("ACCESSION_NUMBER", ""): row
            for row in _zip_table(archive, "FUND_REPORTED_INFO")
            if row.get("ACCESSION_NUMBER") in selected
        }

    results: list[HoldingsNormalisationResult] = []
    coverage_rows: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    seen_instruments: set[str] = set()
    for accession, (_series_id, instrument_id) in sorted(selected.items()):
        submission = submissions[accession]
        report_date = _date_field(submission.get("REPORT_DATE"))
        filing_date = _date_field(submission.get("FILING_DATE"))
        result, coverage, nav = _holdings_for_filing(
            instrument_id=instrument_id,
            accession=accession,
            report_date=report_date,
            filing_date=filing_date,
            filing_row=submission,
            nav_row=nav_by_accession.get(accession),
            holding_rows=holdings_by_accession.get(accession, ()),
            identifiers=identifiers,
            accepted_at_by_accession=accepted,
            dataset_sha256=dataset_sha256,
            today=today,
        )
        results.append(result)
        coverage_rows.extend(coverage)
        observations.extend(nav)
        seen_instruments.add(instrument_id)
    for instrument_id in sorted(set(instrument_map.values()) - seen_instruments):
        results.append(normalise_holdings(pd.DataFrame(), instrument_id, "", "sec_nport", today=today))
        coverage_rows.append(_unknown_coverage(instrument_id, "filing_not_present_in_selected_bulk_period"))
    if not coverage_rows:
        coverage_rows.append(_unknown_coverage(None, "no_mapped_fund_filing"))
    if retrieved_at is not None:
        for observation in observations:
            observation["retrieved_at"] = retrieved_at.isoformat() if isinstance(retrieved_at, datetime) else str(retrieved_at)
    return tuple(results), tuple(observations), pd.DataFrame(coverage_rows, columns=_COVERAGE_COLUMNS)


def parse_sec_ncen_archive(
    path: Path,
    funds: Mapping[tuple[str, str], str],
    *,
    accepted_at_by_accession: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], ...]:
    """Parse N-CEN registrant/series identity evidence without deriving NAV."""

    instrument_map, target_ciks = _instrument_map(funds)
    if not instrument_map:
        raise ValueError("SEC N-CEN parsing requires explicit (CIK, series ID) fund mappings")
    accepted = accepted_at_by_accession or {}
    with zipfile.ZipFile(Path(path), "r") as archive:
        submissions = {
            row.get("ACCESSION_NUMBER", ""): row
            for row in _zip_table(archive, "SUBMISSION")
            if _canonical_cik(row.get("CIK")) in target_ciks and row.get("ACCESSION_NUMBER")
        }
        registrants = {
            row.get("ACCESSION_NUMBER", ""): row
            for row in _zip_table(archive, "REGISTRANT")
            if row.get("ACCESSION_NUMBER") in submissions
        }
        series_by_accession: dict[str, list[Mapping[str, str]]] = defaultdict(list)
        for row in _zip_table(archive, "FUND_REPORTED_INFO", required=False):
            if row.get("ACCESSION_NUMBER") in submissions:
                series_by_accession[row["ACCESSION_NUMBER"]].append(row)

    records: list[dict[str, object]] = []
    for accession, submission in sorted(submissions.items()):
        registrant = registrants.get(accession, {})
        cik = _canonical_cik(submission.get("CIK") or registrant.get("CIK"))
        filing_date = _date_field(submission.get("FILING_DATE"))
        report_date = _date_field(submission.get("REPORT_ENDING_PERIOD"))
        accepted_at, accepted_reason = _accepted_at(submission, accepted)
        series_rows = series_by_accession.get(accession) or ({},)
        for series in series_rows:
            series_id = series.get("SERIES_ID", "")
            records.append({
                "instrument_id": instrument_map.get((cik, series_id)) if series_id else None,
                "cik": cik or None,
                "series_id": series_id or None,
                "series_name": series.get("SERIES_NAME") or None,
                "registrant_name": registrant.get("REGISTRANT_NAME") or submission.get("REGISTRANT_SIGNED_NAME") or None,
                "file_number": submission.get("FILE_NUM") or registrant.get("FILE_NUM") or None,
                "accession_number": accession,
                "as_of": report_date.isoformat() if report_date else None,
                "filing_date": filing_date.isoformat() if filing_date else None,
                "known_at": accepted_at,
                "known_at_reason": accepted_reason or ("filing_acceptance_time_missing" if accepted_at is None else None),
                "source": "sec_ncen",
                "source_id": f"sec_ncen:{accession}:{series_id}" if series_id else f"sec_ncen:{accession}",
                "authority": SourceAuthority.OFFICIAL.value,
                "evidence_type": EVIDENCE_TYPE,
                "nav_per_share": None,
                "nav_per_share_reason": "not_reported_by_n_cen_bulk_dataset",
                "dealing_eligibility": None,
                "dealing_eligibility_reason": "not_reported_by_n_cen_bulk_dataset",
            })
    return tuple(records)


def _authority(value: object) -> SourceAuthority:
    text = str(value or "").strip().lower()
    if text == "convenience":
        text = SourceAuthority.VENDOR.value
    try:
        return SourceAuthority(text)
    except ValueError as exc:
        raise ValueError(f"unsupported fund evidence authority: {redact_text(value)}") from exc


def resolve_fund_evidence(candidates: Iterable[Mapping[str, object]]) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Resolve same-date fund evidence by authority and record every conflict.

    The repository's :class:`SourceAuthority` ranks official above issuer,
    vendor/convenience, community, manual, and model evidence. Two different
    values at the same highest rank remain unresolved rather than being
    selected by retrieval time or row order.
    """

    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for candidate in candidates:
        if candidate.get("value") is None or not str(candidate.get("value")).strip():
            continue
        key = tuple(str(candidate.get(field) or "").strip() for field in ("instrument_id", "metric", "as_of"))
        if not all(key):
            raise ValueError("fund evidence requires instrument_id, metric, and as_of")
        row = dict(candidate)
        row["authority"] = _authority(row.get("authority")).value
        grouped[key].append(row)

    resolved: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    for key, rows in sorted(grouped.items()):
        preferred = preferred_authority(row["authority"] for row in rows)
        top = [row for row in rows if _authority(row["authority"]) is preferred]
        top_values = {str(row.get("value")) for row in top}
        selected = None
        if len(top_values) == 1:
            selected = sorted(top, key=lambda row: (str(row.get("source", "")), str(row.get("source_id", ""))))[0]
        resolved.append({
            "instrument_id": key[0],
            "metric": key[1],
            "as_of": key[2],
            "selected": selected,
            "authority": preferred.value,
            "status": "resolved" if selected is not None else "conflict_at_preferred_authority",
        })
        if selected is not None:
            selected_value = str(selected.get("value"))
            for rejected in rows:
                if rejected is selected or str(rejected.get("value")) == selected_value:
                    continue
                conflicts.append({
                    "instrument_id": key[0],
                    "metric": key[1],
                    "as_of": key[2],
                    "preferred_source": selected.get("source"),
                    "preferred_authority": preferred.value,
                    "preferred_value": selected.get("value"),
                    "conflicting_source": rejected.get("source"),
                    "conflicting_authority": rejected.get("authority"),
                    "conflicting_value": rejected.get("value"),
                    "reason": "lower_authority_source_conflicts_with_preferred_evidence",
                })
        elif len(rows) > 1:
            conflicts.append({
                "instrument_id": key[0],
                "metric": key[1],
                "as_of": key[2],
                "preferred_source": None,
                "preferred_authority": preferred.value,
                "conflicting_source": tuple(sorted(str(row.get("source", "")) for row in top)),
                "conflicting_authority": preferred.value,
                "conflicting_value": tuple(sorted(top_values)),
                "reason": "conflict_at_preferred_authority",
            })
    return tuple(resolved), tuple(conflicts)


def run_sec_fund_adapters(
    provider: object | None,
    period: str,
    funds: Mapping[tuple[str, str], str] | None = None,
    *,
    network_enabled: bool = False,
    accepted_at_by_accession: Mapping[str, object] | None = None,
    comparison_evidence: Iterable[Mapping[str, object]] = (),
    today: str | date | datetime | None = None,
) -> SecFundAdapterRun:
    """Acquire and parse one user-selected period, isolating each SEC region.

    ``network_enabled`` deliberately defaults to false. Callers must explicitly
    opt in to public SEC network acquisition; offline cache-only reads and
    local synthetic fixtures remain available without transport access.
    """

    fund_map = funds or {}
    try:
        instrument_map, _target_ciks = _instrument_map(fund_map)
    except ValueError as exc:
        instrument_map = {}
        mapping_error = redact_text(exc)
    else:
        mapping_error = None if instrument_map else "explicit_fund_mapping_required"
    documents: dict[str, object] = {}
    failures: dict[str, str] = {}
    holdings: tuple[HoldingsNormalisationResult, ...] = ()
    nav_observations: tuple[dict[str, object], ...] = ()
    identity_records: tuple[dict[str, object], ...] = ()
    coverage = pd.DataFrame(columns=_COVERAGE_COLUMNS)

    for form in ("nport", "ncen"):
        if mapping_error:
            failures[form] = mapping_error
            continue
        if provider is None:
            failures[form] = "sec_provider_not_configured"
            continue
        try:
            dataset = _period_dataset(form, period)
            document = fetch_bulk(provider, dataset, cache_only=not network_enabled)
            documents[form] = document
        except Exception as exc:
            failures[form] = f"{type(exc).__name__}: {redact_text(exc)}"
            continue
        try:
            if form == "nport":
                parsed_holdings, parsed_nav, parsed_coverage = parse_sec_nport_archive(
                    Path(document.path),
                    fund_map,
                    accepted_at_by_accession=accepted_at_by_accession,
                    dataset_sha256=str(document.sha256),
                    retrieved_at=document.retrieved_at,
                    today=today,
                )
                holdings = parsed_holdings
                nav_observations = parsed_nav
                coverage = parsed_coverage
            else:
                identity_records = parse_sec_ncen_archive(
                    Path(document.path),
                    fund_map,
                    accepted_at_by_accession=accepted_at_by_accession,
                )
        except Exception as exc:
            failures[form] = f"{type(exc).__name__}: {redact_text(exc)}"

    if coverage.empty:
        coverage_rows = [
            _unknown_coverage(instrument_id, failures.get("nport", "nport_dataset_unavailable"))
            for instrument_id in sorted(set(instrument_map.values()))
        ] or [_unknown_coverage(None, failures.get("nport", "nport_dataset_unavailable"))]
        coverage = pd.DataFrame(coverage_rows, columns=_COVERAGE_COLUMNS)
    comparison_rows = [*nav_observations, *[dict(row) for row in comparison_evidence]]
    resolved, conflicts = resolve_fund_evidence(comparison_rows)
    return SecFundAdapterRun(
        documents=documents,
        nav_observations=nav_observations,
        holdings=holdings,
        identity_records=identity_records,
        coverage_denominators=coverage,
        resolved_evidence=resolved,
        conflicts=conflicts,
        failures=failures,
    )
