"""Bug hunt slice S8 reproduction tests."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pandas as pd
import pytest

from etf_cockpit.analysis.screening import ScreenQuery, records_checksum, run_screen
from etf_cockpit.data import score_history as h
from etf_cockpit.data import universe_membership as m
from etf_cockpit.data import universe_store as u
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore
from etf_cockpit.data.import_export import ImportService, validate_import
from etf_cockpit.data.instrument_identity import IdentityClaim, resolve_identity
from etf_cockpit.data.portfolio_imports import PortfolioImportError, PortfolioImportStore
from etf_cockpit.data.screen_store import export_screen_csv
from etf_cockpit.data.universe_import import _rows_from_xlsx_bytes


def test_s8_01_stale_accepted_preview_is_rejected(tmp_path):
    source = tmp_path / "cash.csv"
    source.write_text(
        "record_type,source_id,occurred_at,account_id,currency,cash_amount\n"
        "cash,deposit,2026-10-01T12:00:00Z,acc,EUR,100\n"
    )
    store = PortfolioImportStore(tmp_path)
    first = store.preview(source)
    second = store.preview(source)
    assert first.valid and second.valid
    store.commit(first)
    try:
        store.commit(second)
    except PortfolioImportError:
        pass
    else:
        raise AssertionError("stale accepted preview was not rejected")


def test_s8_02_existing_unreadable_history_blocks_append(monkeypatch, tmp_path):
    published = []
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(h, "wait_for_atomic_group", lambda path: None)

    def unreadable(*args, **kwargs):
        raise PermissionError("transient sharing violation")

    monkeypatch.setattr(h.pd, "read_parquet", unreadable)
    monkeypatch.setattr(h, "_write_history_group", lambda frame, path: published.append(frame))
    scores = pd.DataFrame([{"instrument_id": "A", "final_combined_score_10": 5.0}])
    try:
        h.append_score_run(scores, "new", "2026-10-05T00:00:00Z", root=tmp_path)
    except PermissionError:
        pass
    assert not published



@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S8-04: Superseded identity claims cause false duplicate quarantines")
def test_s8_04_superseded_isin_does_not_quarantine(monkeypatch):
    old = IdentityClaim(
        "A",
        "isin",
        "US0378331005",
        "issuer",
        SourceAuthority.ISSUER,
        source_id="issuer-A",
        object_id="A",
        valid_from="2026-10-01T00:00:00Z",
        available_at="2026-10-01T00:00:00Z",
    )
    new = replace(old, value="US5949181045", revision=2, available_at="2026-10-02T00:00:00Z")
    metadata = (
        replace(old, field="ticker", value="MSFT"),
        replace(old, field="exchange", value="NASDAQ"),
    )
    other = replace(old, instrument_id="B", object_id="B", source_id="issuer-B")
    claims = (old, new, *metadata, other)
    cutoff = "2026-10-04T00:00:00Z"
    assert not resolve_identity(claims[:-1], effective_at=cutoff, decision_time=cutoff).requires_manual_review
    store = IdentityMasterStore.__new__(IdentityMasterStore)
    monkeypatch.setattr(store, "_load_claims", lambda: claims)
    monkeypatch.setattr(store, "_load_reviews", lambda: ())
    result = store.resolve("A", effective_at=cutoff, decision_time=cutoff)
    assert result.identity.isin == "US5949181045"
    assert not result.requires_manual_review


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="S8-05: Disabling every instrument leaves membership intervals open")
def test_s8_05_all_disabled_universe_records_capture(monkeypatch, tmp_path):
    record = u.UniverseRecord("A", "A", ticker="A", isin_status="needs_verification", enabled=False)
    assert u.validate_universe([record]).valid
    snapshot = SimpleNamespace(
        integrity_errors=(),
        records=(record,),
        path=SimpleNamespace(read_bytes=lambda: b"saved-disabled-universe"),
    )
    monkeypatch.setattr(u, "load_universe", lambda root: snapshot)
    status = m.record_configured_capture(root=tmp_path)
    assert status.status == "recorded"


def test_s8_06_prices_import_updates_analysis_store(tmp_path):
    source = tmp_path / "prices.csv"
    source.write_text("date,etf_id,adjusted_close\n2026-10-05,A,200\n")
    preview = validate_import("prices", source)
    assert preview.valid
    service = ImportService(tmp_path)
    service.register(preview)
    service.commit(preview.preview_id)
    analysis_path = tmp_path / "data/validated/prices/prices_daily.parquet"
    assert analysis_path.exists()
    assert pd.read_parquet(analysis_path)["adjusted_close"].iloc[0] == 200


def test_s8_07_absolute_xlsx_sheet_target():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet r:id="r1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="r1" Target="/xl/worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>ticker</t></is></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>ABC</t></is></c></row></sheetData></worksheet>',
        )
    assert _rows_from_xlsx_bytes(buffer.getvalue()) == ({"ticker": "ABC"},)


def test_s8_08_negative_numeric_screen_exports(tmp_path):
    rows = [{"instrument_id": "A", "drawdown": -0.05}]
    query = ScreenQuery(input_checksum=records_checksum(rows))
    result = run_screen(rows, query)
    destination = tmp_path / "screen.csv"
    assert export_screen_csv(result, query, destination) == destination
