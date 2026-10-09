"""Add the listed Norwegian savings banks missing from the universe (SB2, data-driven).

The source is the official Euronext Oslo listing capture (``euronext_listing``); nothing is hard-coded per bank.
A listing row becomes an ``equity_certificate`` universe record only when its name matches a savings-bank
pattern from ``configs/euronext_listing_v1.yaml`` (not merely an include-name) and its ISIN is not yet in the
universe. Whether the bank really has an equity-certificate class is decided later by the claim gate: without EC
evidence the bank stays unscored with the reason shown, so an ordinary-share bank cannot receive a score.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from etf_cockpit.data.euronext_listing import (
    _is_excluded_name,
    _normalise_name,
    capture_log,
    load_euronext_listing_config,
    load_raw_payload,
    parse_euronext_listing,
    savings_bank_view,
)
from etf_cockpit.data.universe_store import (
    UniverseRecord,
    add_record,
    import_legacy_universe,
    is_valid_isin,
    load_sparebank_records,
    load_universe,
    save_universe,
)


_ABBREVIATIONS = {"spb": "Sparebank", "spbk": "Sparebank", "sparbnk": "Sparebank"}


def display_name(listing_name: str) -> str:
    """Listing name in title case with the listing's own abbreviations of 'Sparebank' expanded."""

    return " ".join(_ABBREVIATIONS.get(word.casefold(), word) for word in listing_name.title().split())


def _listing_names(root: Path) -> dict[str, str]:
    config = load_euronext_listing_config()
    captures = capture_log(config.scope, root=root)
    if captures.empty:
        return {}
    latest = captures.sort_values(["snapshot_date", "known_at", "capture_id"]).iloc[-1]
    listing = parse_euronext_listing(load_raw_payload(str(latest["checksum"]), root=root), config)
    return {row["instrument_id"]: row["name"] for row in listing.rows}


def _all_records(root: Path) -> tuple[UniverseRecord, ...]:
    snapshot = load_universe(root)
    return tuple(snapshot.records or import_legacy_universe(root / "configs" / "universe.yaml").records)


def missing_savings_banks(root: Path) -> list[dict[str, str]]:
    """Listed savings banks (pattern match) whose ISIN is not in the universe."""

    config = load_euronext_listing_config()
    patterns = tuple(_normalise_name(item) for item in config.savings_bank_patterns)
    exclude = tuple(_normalise_name(item) for item in config.savings_bank_exclude_names)
    names = _listing_names(root)
    existing = _all_records(root)
    known = {record.isin for record in existing} | {record.instrument_id.upper() for record in existing} | {record.ticker.upper().removesuffix(".OL") for record in existing}
    rows: list[dict[str, str]] = []
    for row in savings_bank_view(root=root).to_dict(orient="records"):
        name = names.get(row["isin"], "")
        folded = _normalise_name(name)
        if row["isin"] in known or row["symbol"].upper() in known or _is_excluded_name(folded, exclude) or not any(pattern in folded for pattern in patterns):
            continue
        rows.append({**row, "name": name})
    return rows


def isin_corrections(root: Path) -> dict[str, str]:
    """Universe records with no valid ISIN whose symbol is in the official listing: {instrument_id: listing ISIN}."""

    listing = {row["symbol"].upper(): row["isin"] for row in savings_bank_view(root=root).to_dict(orient="records")}
    result: dict[str, str] = {}
    for record in load_sparebank_records(root, enabled_only=False):
        symbol = record.ticker.upper().removesuffix(".OL") or record.instrument_id.upper()
        if not is_valid_isin(record.isin) and symbol in listing:
            result[record.instrument_id] = listing[symbol]
    return result


def sync(root: Path, *, apply: bool = False) -> list[UniverseRecord]:
    """Build (and with ``apply`` save through the universe store) records for the missing banks.

    Existing records without a valid ISIN get the ISIN of the same symbol from the official listing.
    """

    root = Path(root).resolve()
    templates = load_sparebank_records(root, enabled_only=False)
    if not templates:
        raise ValueError("no existing equity-certificate record to use as a template")
    # The template must be a Norwegian savings-bank certificate (tier, currency, region and theme are copied).
    template = next((record for record in templates if record.tier.casefold() == "sparebanken" and record.currency == "NOK"), None)
    if template is None:
        raise ValueError("no Norwegian savings-bank certificate record to use as a template")
    created: list[UniverseRecord] = []
    for row in missing_savings_banks(root):
        created.append(
            replace(
                template,
                instrument_id=row["symbol"].upper(),
                name=display_name(row["name"]),
                isin=row["isin"],
                isin_status="verified",
                ticker=row["yfinance_ticker"],
                lei="",
                enabled=True,
                notes="Added from the Euronext Oslo listing; name as listed. LEI and legal name resolve on the next filings refresh.",
            )
        )
    if apply and (created or isin_corrections(root)):
        snapshot = load_universe(root)
        base = _all_records(root)
        corrections = isin_corrections(root)
        records = tuple(
            replace(record, isin=corrections[record.instrument_id], isin_status="verified") if record.instrument_id in corrections else record
            for record in base
        )
        for record in created:
            records = add_record(records, record, allow_cross_tier_duplicates=True)
        save_universe(records, snapshot.revision, root=root, allow_cross_tier_duplicates=True)
    return created
