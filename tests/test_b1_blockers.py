"""B1 blocker fixes: listing calendar resolution and the proven ESEF publication date behind reported share counts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

from etf_cockpit.data.esef_provider import parse_reported_shares
from etf_cockpit.data.etf_economics import resolve_listing_calendar
from etf_cockpit.parsers.sec_facts import statement_facts_from_esef

ROOT = Path(__file__).resolve().parents[1]


def _stamp_module():
    spec = importlib.util.spec_from_file_location("pit_stamp_esef_filed", ROOT / "scripts" / "pit_stamp_esef_filed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_listing_calendar_falls_back_to_the_ticker_suffix_and_stays_uncertified_otherwise() -> None:
    assert resolve_listing_calendar("Oslo Bors", "EQNR.OL") == "XOSL"
    assert resolve_listing_calendar("unknown venue", "SAP.DE") == "XETR"
    assert resolve_listing_calendar("unknown venue", "MSFT", "USD") == "XNYS"
    assert resolve_listing_calendar("unknown venue", "MSFT", "EUR") is None
    assert resolve_listing_calendar(None, None) is None


class _Record:
    concept, namespace, unit = "NumberOfSharesOutstanding", "http://xbrl.ifrs.org/taxonomy/2023-03-23/ifrs-full", "shares"
    period_start, period_end, value, mapping_status, is_numeric = None, "2022-12-31", "1000", "mapped", True
    context_id, consolidation_scope, context_dimensions = "c1", "consolidated", ()


def _facts(filed: str | None) -> pd.DataFrame:
    facts = statement_facts_from_esef([_Record()], instrument_id="XX", source_sha256="a" * 64, known_at="2023-03-30T00:00:00+00:00", filed=filed)
    return pd.DataFrame([fact.model_dump() if hasattr(fact, "model_dump") else fact.__dict__ for fact in facts])


def test_a_reported_share_count_needs_a_proven_publication_date() -> None:
    assert parse_reported_shares(_facts(None), source_ref="x") == []  # known_at alone may be acquisition time
    rows = parse_reported_shares(_facts("2023-03-30"), source_ref="x")
    assert len(rows) == 1 and rows[0]["source"] == "esef_reported" and rows[0]["shares_outstanding"] == 1000.0


def test_stamping_uses_only_the_import_log_date_added_of_the_matching_package() -> None:
    facts = _facts(None)
    other = facts.copy()
    other["filing_version"] = "b" * 64
    both = pd.concat([facts, other], ignore_index=True)
    log = [json.dumps({"status": "imported", "sha256": "a" * 64, "date_added": "2023-03-30 10:03:36.514266"}),
           json.dumps({"status": "failed", "sha256": "b" * 64, "date_added": "2023-04-01 00:00:00"})]
    stamped, count = _stamp_module().stamp_filed(both, log)
    assert count == 1
    assert list(stamped["filed"].astype(str)) == ["2023-03-30", "None"]
