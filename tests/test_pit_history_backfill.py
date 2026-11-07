"""Point-in-time history backfill (HDP1): source restriction, filing knowledge times, one-directory bank history, PIT audit."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.parsers.contracts import RawDocument

FIXTURE = Path(__file__).parent / "fixtures" / "official" / "esef_report_package" / "synthetic-ming-2025.xbri"
LEI = "FAKELEI0000000000001"


def test_refresh_chain_restriction_keeps_restated_sources_out_of_history(monkeypatch) -> None:
    from etf_cockpit.application import stock_service
    from etf_cockpit.data import stock_fundamentals as store

    seen: list[list[str]] = []
    monkeypatch.setattr(store, "refresh_stock_fundamentals", lambda targets, **kw: seen.append(list(kw["config"]["sources"]["chain"])) or store.RefreshReport())
    config = SimpleNamespace(universe=SimpleNamespace(etfs=[{"id": "MSFT", "name": "Microsoft", "ticker": "MSFT", "asset_type": "stock", "enabled": True}]))

    stock_service.refresh_universe_stock_fundamentals(config, chain=("sec_edgar",))
    stock_service.refresh_universe_stock_fundamentals(config)
    with pytest.raises(ValueError, match="not in the configured chain"):
        stock_service.refresh_universe_stock_fundamentals(config, chain=("bloomberg",))

    assert seen == [["sec_edgar"], ["sec_edgar", "esef", "yfinance"]]


def test_esef_import_is_known_from_the_filing_date_not_the_import_time(tmp_path: Path, monkeypatch) -> None:
    import etf_cockpit.application.filing_ingestion as filing_ingestion
    import etf_cockpit.application.filing_ingestion_workflows as workflows
    from etf_cockpit.parsers import esef_ixbrl

    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: False)
    monkeypatch.setattr(workflows, "STATEMENT_FACTS_PATH", tmp_path / "statement_facts.parquet")
    monkeypatch.setattr(workflows, "FILINGS_STATEMENTS_PATH", tmp_path / "filings_statements.parquet")
    monkeypatch.setattr(workflows, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(filing_ingestion, "RAW_DIR", tmp_path / "raw")

    class Session:
        last_message = ""

        def _record_activity_output(self, step, path):  # noqa: ANN001
            pass

    future = workflows.import_esef_package(Session(), FIXTURE, instrument_id="NL_ENTITY", known_at="2999-01-01")
    assert "unavailable" in future and not (tmp_path / "statement_facts.parquet").exists()

    message = workflows.import_esef_package(Session(), FIXTURE, instrument_id="NL_ENTITY", known_at="2022-03-16 00:00:00")

    assert message.startswith("ESEF import complete")
    facts = pd.read_parquet(tmp_path / "statement_facts.parquet")
    stamps = set(pd.to_datetime(facts["known_at"], utc=True))
    assert stamps == {pd.Timestamp("2022-03-16T00:00:00Z")}
    assert set(pd.to_datetime(facts["available_at"], utc=True)) == stamps


def _universe(root: Path) -> None:
    (root / "configs").mkdir(parents=True, exist_ok=True)
    (root / "configs" / "universe.yaml").write_text(
        "etfs:\n  - id: HISTBANK.OL\n    name: History Sparebank\n    isin: NO0000000001\n    ticker: HIST.OL\n"
        f"    instrument_type: equity_certificate\n    analysis_tier: sparebanken\n    data_policy: yfinance_only\n    region: Norway\n    sector: Banks\n    enabled: true\n    lei: {LEI}\n",
        encoding="utf-8",
    )


def _package(path: Path, variant: str, year: str = "2025") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(FIXTURE) as source, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename.lower().endswith((".xhtml", ".html")):
                payload = payload.replace(b"7V6Z97IO7R1SEAO84Q32", LEI.encode("ascii")).replace(b"2025-", f"{year}-".encode()) + f"\n<!-- {variant} -->\n".encode()
            target.writestr(member, payload)
    return path


class _HistoryClient:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.rows = (
            {"id": "f-late", "entity_lei": LEI, "period_end": "2025-12-31", "date_added": "2026-03-05", "package_url": "https://filings.xbrl.org/h/late.xbri"},
            {"id": "f-early", "entity_lei": LEI, "period_end": "2024-12-31", "date_added": "2026-02-10", "package_url": "https://filings.xbrl.org/h/early.xbri"},
            {"id": "f-nodate", "entity_lei": LEI, "period_end": "2025-12-31", "date_added": "", "package_url": "https://filings.xbrl.org/h/nodate.xbri"},
            {"id": "f-other", "entity_lei": "OTHERLEI000000000002", "period_end": "2025-12-31", "date_added": "2026-02-01", "package_url": "https://filings.xbrl.org/h/other.xbri"},
        )

    def filings_for_lei(self, lei):  # noqa: ANN001
        return self.rows

    def download(self, filing):  # noqa: ANN001
        name = "early" if filing["id"] == "f-early" else "late"
        path = _package(self.root / f"{name}.xbri", name, "2024" if name == "early" else "2025")
        return RawDocument(path, str(filing["package_url"]), datetime.now(timezone.utc), hashlib.sha256(path.read_bytes()).hexdigest(), "filings_xbrl_org", "esef_report_package", "application/octet-stream", 200)


def test_bank_history_imports_every_filing_into_one_directory_with_registry_dates(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.parsers import esef_ixbrl
    from scripts.sparebank_refresh import _history_filings, refresh_sparebanks

    # This tests history persistence and PIT dates; optional Arelle process startup
    # can exceed its wall-clock timeout on loaded parallel Windows workers.
    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: False)

    client = _HistoryClient(tmp_path / "downloads")
    assert [row["id"] for row in _history_filings(client.rows, LEI)] == ["f-early", "f-late"]  # oldest knowledge first; no date / other LEI dropped
    _universe(tmp_path)
    rescored: list[object] = []

    rows = refresh_sparebanks(tmp_path, universe_root=tmp_path, client=client, decision_time="2026-03-06T00:00:00Z", history=True, rescorer=lambda *a: rescored.append(a))

    assert rescored == []  # a rescore would append a score run dated by the backfill
    outcomes = rows[0]["history"]
    assert [(item["filing_id"], item["status"]) for item in outcomes] == [("f-early", "imported"), ("f-late", "imported")]
    history = tmp_path / "evidence" / "norway" / "HISTBANK.OL-history"
    facts = pd.read_parquet(history / "statement_facts.parquet")
    assert set(pd.to_datetime(facts["known_at"], utc=True)) == {pd.Timestamp("2026-02-10T00:00:00Z"), pd.Timestamp("2026-03-05T00:00:00Z")}
    revisions = json.loads((history / "ec_facts.json").read_text(encoding="utf-8"))["revisions"]
    assert sorted(item["known_at"] for item in revisions) == ["2026-02-10T00:00:00.000000+00:00", "2026-03-05T00:00:00.000000+00:00"]  # fixed width
    # identity.json is rewritten by every import (it now names the FY2025 filing): an earlier decision must not be
    # pinned to a period that was only published later, so it reads the filing known at its own time.
    from etf_cockpit.application.financial_institution_views import load_financial_institution_projection

    def view_at(cutoff: str) -> tuple[object, str]:
        projection = load_financial_institution_projection("HISTBANK.OL", storage_root=tmp_path, universe_root=tmp_path, decision_time=cutoff, record_history=False)
        return projection.get("status"), str((projection.get("lineage") or {}).get("sources", ""))

    early = hashlib.sha256((tmp_path / "downloads" / "early.xbri").read_bytes()).hexdigest()[:16]
    late = hashlib.sha256((tmp_path / "downloads" / "late.xbri").read_bytes()).hexdigest()[:16]
    assert view_at("2026-02-01T00:00:00Z")[0] == "unavailable"  # before any filing: nothing is scored
    status, between = view_at("2026-02-20T00:00:00Z")
    assert status == "partial" and early in between and late not in between  # the FY2024 filing known on 2026-02-10, not the FY2025 one added 2026-03-05
    assert late in view_at("2026-03-06T00:00:00Z")[1]
    with pytest.raises(ValueError, match="history needs fetch"):
        refresh_sparebanks(tmp_path, universe_root=tmp_path, client=client, fetch=False, history=True)


def test_backfill_driver_fails_closed_and_is_idempotent(tmp_path: Path) -> None:
    from scripts import pit_history_backfill as driver

    targets = [{"id": "OK", "type": "stock"}, {"id": "UNVERIFIED", "type": "stock"}, {"id": "BROKEN", "type": "stock"}]
    records = {
        "OK": {"isin": "NL0000235190"},
        "UNVERIFIED": {"isin": "NEEDS_VERIFICATION"},
        "BROKEN": {"isin": "FR0000121329"},
    }

    def lookup(isin: str):
        if isin == "FR0000121329":
            raise TimeoutError("gleif down")
        return "MINO79WLOO247M1IL051", {}, "https://api.gleif.org/x"

    leis = driver.resolve_leis(targets, records, lookup, sleep=lambda _s: None)
    assert leis["OK"]["lei"] == "MINO79WLOO247M1IL051"
    assert leis["UNVERIFIED"]["lei"] == "" and "not verified" in leis["UNVERIFIED"]["reason"]  # never resolved by name
    assert leis["BROKEN"]["lei"] == "" and "TimeoutError" in leis["BROKEN"]["reason"]

    filings = [
        {"id": "2", "entity_lei": "L", "period_end": "2023-12-31", "date_added": "2024-03-01 10:00:00.5", "package_url": "/b.zip"},
        {"id": "1", "entity_lei": "L", "period_end": "2022-12-31", "date_added": "2023-03-01 00:00:00", "package_url": "/a.zip"},
        {"id": "3", "entity_lei": "L", "period_end": "2024-12-31", "date_added": "", "package_url": "/c.zip"},
    ]
    calls: list[tuple[str, str]] = []

    def importer(_session, path, *, instrument_id, known_at):  # noqa: ANN001
        calls.append((Path(path).name, known_at))
        return "ESEF import complete: 1 facts"

    def download(filing):  # noqa: ANN001
        return SimpleNamespace(path=tmp_path / f"{filing['id']}.xbri", sha256="a" * 64)

    log = tmp_path / "log.jsonl"
    first = driver.import_generic_history("X", "L", filings, download, log, importer=importer, sleep=lambda _s: None)
    second = driver.import_generic_history("X", "L", filings, download, log, importer=importer, sleep=lambda _s: None)

    assert calls == [("1.xbri", "2023-03-01T00:00:00"), ("2.xbri", "2024-03-01T10:00:00.5")]  # oldest first, date_added as known_at, no import twice
    assert [item["status"] for item in first] == ["skipped", "imported", "imported"]  # no date_added: never dated by the import time
    assert [item["status"] for item in second] == ["skipped", "already_imported", "already_imported"]


def _stock_store(root: Path, rows: list[dict]) -> None:
    from etf_cockpit.data import stock_fundamentals as store

    path = store.store_paths(root)["periods"]
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    for column in store.PERIOD_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    store._write(path, frame)


def _row(**changes) -> dict:
    base = {"instrument_id": "MSFT", "period_end": "2022-06-30", "period_type": "FY", "fiscal_year": 2022, "currency": "USD", "source": "sec_edgar", "source_ref": "x", "known_at": "2022-07-28", "revenue": 198.0e9, "net_income_parent": 72.0e9, "equity_parent": 166.0e9}
    return {**base, **changes}


def test_pit_check_passes_clean_history_and_flags_leaks(tmp_path: Path) -> None:
    from scripts import pit_history_check as check

    days = check.decision_dates(date(2022, 7, 4), date(2022, 9, 1), 7)
    assert len(days) == 9 and days[0] == date(2022, 7, 4)
    _stock_store(tmp_path, [_row()])
    clean = check.check_stock_store(tmp_path, days)
    assert clean["violations"] == [] and clean["instruments"] == 1

    _stock_store(tmp_path, [_row(), _row(source="yfinance", known_at="2026-10-21"), _row(instrument_id="BAD", known_at="2022-01-01")])
    dirty = check.check_stock_store(tmp_path, days)
    text = " | ".join(dirty["violations"])
    assert "fetch-dated source 'yfinance'" in text  # restated values are not history
    assert "precedes the period end" in text  # a fact known before its period ended

    statements = pd.DataFrame(
        {"instrument_id": ["AIR", "AIR"], "known_at": ["2022-03-16T00:00:00+00:00", "2026-10-21T09:00:00+00:00"],
         "available_at": ["2022-03-16T00:00:00+00:00", "2026-10-21T09:00:00+00:00"], "effective_at": ["2021-12-31", "2021-12-31"]}
    )
    result = check.check_statement_frame(statements, {"AIR": {datetime(2022, 3, 16, tzinfo=timezone.utc)}}, days, label="t")
    assert len(result["violations"]) == 1 and "import-time stamp" in result["violations"][0]

    mixed = statements.assign(known_at=["2022-03-16T00:00:00+00:00", "2022-03-16T11:02:16.151649+00:00"], available_at=["2022-03-16T00:00:00+00:00", "2022-03-16T11:02:16.151649+00:00"])
    assert any("mixing timestamp shapes" in item for item in check.check_statement_frame(mixed, {}, days, label="t")["violations"])


def test_coverage_has_a_row_per_replay_instrument_with_reasons(tmp_path: Path) -> None:
    from scripts import pit_history_check as check

    audit = tmp_path / "audit.csv"
    audit.write_text(
        "id,type,ccy,first,last,rows,cover,max_gap_d,zero_vol,replay_set,reason\n"
        "MSFT,stock,USD,2021-10-11,2026-10-09,1,1,1,0,CORE,\n"
        "VWCE,etf,EUR,2021-10-11,2026-10-09,1,1,1,0,CORE,\n"
        "HO,stock,EUR,2021-10-11,2026-10-09,1,1,1,0,CORE,\n"
        "AM,stock,USD,2021-10-11,2026-10-09,1,1,1,0,EXCLUDED,ambiguous\n",
        encoding="utf-8",
    )
    _stock_store(tmp_path, [_row(period_end="2021-06-30", known_at="2021-07-29"), _row(period_end="2022-06-30", known_at="2022-07-28")])
    history = tmp_path / "data" / "pit_history"
    history.mkdir(parents=True)
    (history / "esef_manifest.json").write_text(
        json.dumps({"leis": {}, "manifest": {"HO": {"lei": "", "filings": [], "reason": "lei_unresolved: universe ISIN is not verified (NEEDS_VERIFICATION)"}}}), encoding="utf-8"
    )

    rows = {row["id"]: row for row in check.build_coverage(tmp_path, audit, check.decision_dates(date(2022, 10, 17), date(2026, 10, 9)))}

    assert set(rows) == {"MSFT", "VWCE", "HO"}  # the EXCLUDED id has no row
    assert rows["MSFT"]["route"] == "sec_edgar" and rows["MSFT"]["fiscal_years"] == "2021,2022"
    assert rows["MSFT"]["first_known_at"].startswith("2021-07-29") and rows["MSFT"]["first_decision_date"] == "2022-10-17"
    assert "no FY2020/2023/2024/2025" in rows["MSFT"]["gaps"]
    assert rows["VWCE"]["route"] == "etf_snapshot_only" and "unavailable before the first snapshot" in rows["VWCE"]["gaps"]
    assert "not verified" in rows["HO"]["gaps"] and rows["HO"]["fiscal_years"] == ""


def test_classification_merge_copies_only_history_rows_and_is_idempotent(tmp_path: Path) -> None:
    import sqlite3

    from scripts.pit_history_merge_classification import merge

    ddl = (
        "CREATE TABLE transactional_records (entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload_json TEXT NOT NULL, "
        "revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT, PRIMARY KEY(entity_type, entity_id))"
    )
    rows = {
        "source": [
            ("classification_evidence_v2", "a", '{"evidence":{"evidence_id":"norway_configured_equity_certificate:MING:abc"}}'),
            ("classification_evidence_v2", "b", '{"evidence":{"evidence_id":"universe-config:VWCE:sector:xyz"}}'),
        ],
        "target": [("classification_evidence_v2", "b", '{"keep":"target"}')],
    }
    for name, content in rows.items():
        path = tmp_path / name / "data" / "storage" / "cockpit.sqlite3"
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as connection:
            connection.execute(ddl)
            connection.executemany("INSERT INTO transactional_records VALUES (?,?,?,1,'t','t',NULL)", content)

    assert merge(tmp_path / "source", tmp_path / "target") == 1  # the bank row only; the target's own row 'b' is untouched
    assert merge(tmp_path / "source", tmp_path / "target") == 0
    with sqlite3.connect(tmp_path / "target" / "data" / "storage" / "cockpit.sqlite3") as connection:
        assert connection.execute("SELECT payload_json FROM transactional_records WHERE entity_id='b'").fetchone()[0] == '{"keep":"target"}'
