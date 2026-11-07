"""B1 blocker fixes: listing calendar resolution and the proven ESEF publication date behind reported share counts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

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


class _TreasuryRecord(_Record):
    concept, value = "TreasuryShares", "0"


def _facts(filed: str | None) -> pd.DataFrame:
    facts = statement_facts_from_esef([_Record(), _TreasuryRecord()], instrument_id="XX", source_sha256="a" * 64, known_at="2023-03-30T00:00:00+00:00", published_on=filed)
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
    # HOLD audit: _facts() now carries NumberOfSharesOutstanding + TreasuryShares per package (2 facts each).
    assert count == 2
    assert list(stamped["filed"].astype(str)) == ["2023-03-30", "2023-03-30", "None", "None"]


@pytest.mark.parametrize("suffix,calendar", [
    (".HE", "XHEL"), (".CO", "XCSE"), (".SW", "XSWX"),
    (".VI", "XWBO"), (".LS", "XLIS"), (".IR", "XDUB"),
])
def test_additional_listing_suffixes_use_certified_calendars(suffix, calendar) -> None:
    assert resolve_listing_calendar("unknown venue", "TEST" + suffix) == calendar
    assert resolve_listing_calendar("XETRA", "TEST" + suffix) == "XETR"


def test_an_uncertified_calendar_stays_unmapped(monkeypatch) -> None:
    import exchange_calendars as xcals

    monkeypatch.setattr(xcals, "get_calendar_names", lambda **_kwargs: [])
    assert resolve_listing_calendar(None, "TEST.HE") is None


@pytest.mark.parametrize("published_on,expected", [
    (None, None), ("2023-03-30", "2023-03-30"),
    ("2023-03-30T00:30:00+02:00", "2023-03-29"),
    ("2023-03-30T23:30:00-02:00", "2023-03-31"),
    ("2023-03-30 00:30:00", "2023-03-30"),
])
def test_import_and_stamp_use_only_explicit_publication_in_utc(published_on, expected) -> None:
    facts = _facts(published_on)
    assert facts.iloc[0]["filed"] == expected
    if published_on is not None:
        stamped, count = _stamp_module().stamp_filed(_facts(None), [json.dumps({
            "status": "imported", "sha256": "a" * 64, "date_added": published_on,
        })])
        assert count == 2 and set(stamped["filed"]) == {expected}  # HOLD audit: two facts per package


@pytest.mark.parametrize("missing", [("filed",), ("form",), ("filed", "form")])
def test_stamp_tolerates_missing_columns_and_requires_esef_form(missing) -> None:
    facts = _facts(None).drop(columns=list(missing))
    stamped, count = _stamp_module().stamp_filed(facts, [json.dumps({
        "status": "imported", "sha256": "a" * 64, "date_added": "2023-03-30T00:30:00+02:00",
    })])
    assert count == (0 if "form" in missing else 2)  # HOLD audit: two facts per package
    if count:
        assert stamped.iloc[0]["filed"] == "2023-03-29"
    else:
        pd.testing.assert_frame_equal(facts, stamped)


@pytest.mark.parametrize("reject", [False, True])
def test_stamp_cli_uses_validated_atomic_store(monkeypatch, tmp_path, reject) -> None:
    import sys

    module = _stamp_module()
    path = tmp_path / "data" / "clean" / "statement_facts.parquet"
    path.parent.mkdir(parents=True)
    _facts(None).to_parquet(path, index=False)
    before = path.read_bytes()
    log = tmp_path / "import.jsonl"
    log.write_text(json.dumps({"status": "imported", "sha256": "a" * 64, "date_added": "2023-03-30"}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["pit_stamp_esef_filed.py", "--root", str(tmp_path), "--import-log", str(log)])
    writes = []
    original = module.atomic_write_bytes

    def write(destination, payload, validator):
        writes.append(destination)
        return original(destination, payload, validator)

    def invalid(_path):
        raise ValueError("synthetic parquet validation failure")

    monkeypatch.setattr(module, "atomic_write_bytes", write)
    if reject:
        monkeypatch.setattr(module, "validate_parquet_file", invalid)
        with pytest.raises(Exception, match="synthetic parquet validation failure"):
            module.main()
        assert path.read_bytes() == before
    else:
        assert module.main() == 0
        assert pd.read_parquet(path).iloc[0]["filed"] == "2023-03-30"
    assert writes == [path]


@pytest.mark.parametrize("published_on,expected", [(None, None), ("2023-03-30T00:30:00+02:00", "2023-03-29")])
def test_workflow_does_not_treat_explicit_acquisition_known_at_as_publication(monkeypatch, published_on, expected) -> None:
    from types import SimpleNamespace
    from etf_cockpit.application import filing_ingestion_workflows as workflow

    checksum = "a" * 64
    record = _Record()
    record.entity_lei = "test-lei"
    parsed = SimpleNamespace(success=True, records=[record], warnings=[], source_sha256=checksum)
    monkeypatch.setattr(workflow, "_preserve_esef_raw", lambda *args, **kwargs: (Path("retained.xbri"), checksum))
    monkeypatch.setattr(workflow, "parse_esef_package", lambda _path: parsed)
    monkeypatch.setattr(workflow, "_esef_source_provenance", lambda _path: ("filings_xbrl_org", "https://example.invalid/filing"))
    monkeypatch.setattr(workflow, "_load_vendor_statement_claims", lambda _id: ())
    written = []
    monkeypatch.setattr(workflow, "write_statement_evidence", lambda source, records, *args, **kwargs: written.extend(records))
    session = SimpleNamespace(_record_activity_output=lambda *args: None)
    result = workflow.import_esef_package(
        session, Path("package.xbri"), instrument_id="XX",
        known_at="2023-04-01T12:00:00+00:00", published_on=published_on,
    )
    assert result.startswith("ESEF import complete"), result
    assert len(written) == 1 and written[0].filed == expected
    assert written[0].known_at == "2023-04-01T12:00:00.000000+00:00"
