"""Store, point-in-time merge, refresh, notes and peer picks for normal stocks."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from etf_cockpit.analysis import stock_universe as su
from etf_cockpit.analysis.stock_evidence import MarketInputs, build_stock_evidence
from etf_cockpit.analysis.stock_peers import PeerProfile, auto_peers, effective_peers
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data import stock_notes as notes
from etf_cockpit.data import stock_peer_picks as picks
from etf_cockpit.data import stock_sources as src

UTC = timezone.utc
CONFIG = store.load_stock_config()


def _row(source: str, known: str, revenue: float, *, end: str = "2025-12-31", currency: str = "EUR", **extra: float) -> dict:
    return {"period_end": end, "period_type": "FY", "fiscal_year": 2025, "currency": currency, "source": source, "source_ref": "t", "known_at": known, "revenue": revenue, **extra}


def test_append_keeps_first_known_at_and_only_stores_changes() -> None:
    frame, added = store.append_period_rows(pd.DataFrame(columns=store.PERIOD_COLUMNS), "AAA", [_row("yfinance", "2026-01-01T00:00:00+00:00", 100.0)])
    assert added == 1
    frame, added = store.append_period_rows(frame, "AAA", [_row("yfinance", "2026-02-01T00:00:00+00:00", 100.0)])
    assert added == 0 and len(frame) == 1 and frame.iloc[0]["known_at"].startswith("2026-01-01")
    frame, added = store.append_period_rows(frame, "AAA", [_row("yfinance", "2026-03-01T00:00:00+00:00", 105.0)])
    assert added == 1 and len(frame) == 2  # a revision is a new version, the old one stays for replays


def test_merge_prefers_filings_fills_gaps_and_never_leaks_later_values() -> None:
    frame = pd.DataFrame(columns=store.PERIOD_COLUMNS)
    frame, _ = store.append_period_rows(frame, "AAA", [_row("sec_edgar", "2026-02-10T00:00:00+00:00", 100.0, net_income_parent=10.0)])
    frame, _ = store.append_period_rows(frame, "AAA", [_row("yfinance", "2026-09-01T00:00:00+00:00", 101.0, net_income_parent=11.0, da=5.0)])
    periods = store.periods_for("AAA", frame, ["sec_edgar", "yfinance"])
    early = [p for p in periods if p.known_at <= datetime(2026, 3, 1, tzinfo=UTC)]
    late = max(periods, key=lambda p: p.known_at)
    assert len(early) == 1 and "da" not in early[0].values  # yfinance was not known in March
    assert late.values["revenue"] == 100.0 and late.values["net_income_parent"] == 10.0  # filings win
    assert late.values["da"] == 5.0 and late.field_sources["da"] == "yfinance"  # gap filled, source recorded


def test_merge_does_not_mix_currencies_and_snaps_period_ends() -> None:
    frame = pd.DataFrame(columns=store.PERIOD_COLUMNS)
    frame, _ = store.append_period_rows(frame, "AAA", [_row("sec_edgar", "2026-02-10T00:00:00+00:00", 100.0, end="2025-12-31", currency="USD")])
    frame, _ = store.append_period_rows(frame, "AAA", [_row("yfinance", "2026-02-11T00:00:00+00:00", 90.0, end="2026-01-01", currency="EUR", da=5.0)])
    periods = store.periods_for("AAA", frame, ["sec_edgar", "yfinance"])
    assert len({(p.period_end.year, p.period_type) for p in periods}) == 1  # 1-day offset is one period
    assert all("da" not in p.values for p in periods)  # the EUR value is not mixed into the USD period


def test_merge_preserves_source_field_currency_metadata() -> None:
    row = _row("sec_edgar", "2026-02-10T00:00:00+00:00", 100.0, currency="USD", ebit=20.0)
    row.update(revenue_currency="USD", ebit_currency="EUR")
    frame, _ = store.append_period_rows(pd.DataFrame(columns=store.PERIOD_COLUMNS), "AAA", [row])
    period = store.periods_for("AAA", frame, ["sec_edgar"])[0]
    assert period.values["__currency_revenue"] == "USD" and period.values["__currency_ebit"] == "EUR"


def test_fx_rate_never_uses_a_later_close() -> None:
    fx = pd.DataFrame({"pair": ["GBPEUR"] * 2, "date": ["2026-10-06", "2026-10-09"], "rate": [1.17, 1.19], "known_at": ["x", "x"]})
    assert store.fx_rate("GBPEUR", date(2026, 10, 8), fx) == (1.17, "2026-10-06")
    assert store.fx_rate("GBPEUR", date(2026, 10, 1), fx) == (None, None)


def test_fx_rate_rejects_an_observation_not_yet_known_at_the_decision_time() -> None:
    fx = pd.DataFrame({"pair": ["GBPEUR"], "date": ["2026-09-30"], "rate": [1.18], "known_at": ["2026-10-02T08:00:00+00:00"]})
    decision = datetime(2026, 9, 30, 23, 0, tzinfo=UTC)
    assert store.fx_rate("GBPEUR", date(2026, 9, 30), fx, decision_time=decision) == (None, None)


def test_no_data_reason_names_the_last_fetch_outcome() -> None:
    snaps = pd.DataFrame(columns=store.SNAPSHOT_COLUMNS)
    when = datetime(2026, 10, 9, tzinfo=UTC)
    assert "never fetched" in store.no_data_reason("X", snaps, when, False)
    row = {"instrument_id": "X", "known_at": "2026-10-01T00:00:00+00:00", "status": "not_found", "reason": "Yahoo has no company profile for X"}
    snaps = pd.DataFrame([row]).reindex(columns=store.SNAPSHOT_COLUMNS)
    assert store.no_data_reason("X", snaps, when, False) == "Yahoo has no company profile for X"


def test_refresh_writes_store_and_reports_failures(tmp_path) -> None:
    (tmp_path / "data" / "clean").mkdir(parents=True)
    stamp = "2026-10-09T00:00:00+00:00"
    ok = src.FetchResult(
        "yfinance",
        rows=[_row("yfinance", stamp, 100.0)],
        snapshot={
            "known_at": stamp, "quote_currency": "GBp", "financial_currency": "EUR", "status": "ok",
            "eps_current": 4.4, "eps_90d_ago": 4.0, "revisions_up_30d": 5.0, "revisions_down_30d": 1.0,
        },
    )
    reason = "Yahoo has no company profile for B"
    gone = src.FetchResult("yfinance", status="not_found", reason=reason, snapshot={"known_at": stamp, "status": "not_found", "reason": reason})
    outcomes = {"A": ok, "B": gone}
    targets = [store.StockTarget("A", "A plc", "A.L"), store.StockTarget("B", "B", "B.AS")]
    report = store.refresh_stock_fundamentals(
        targets,
        root=tmp_path,
        now=datetime(2026, 10, 9, tzinfo=UTC),
        config=CONFIG,
        environ={},
        yfinance_fetch=lambda symbol, _cfg, now: outcomes[symbol.split(".")[0]],
        fx_fetch=lambda base, quote: [("2026-10-09", 1.18)],
    )
    assert report.rows_added == 1 and "B" in report.failures and "no company profile" in report.failures["B"]
    assert len(store.read_periods(tmp_path)) == 1
    analyst_rows = store.read_fundamentals(tmp_path)
    analyst = store.latest_analyst("A", analyst_rows, datetime(2026, 10, 9, tzinfo=UTC))
    assert analyst["eps_current"] == 4.4 and analyst["revisions_up_30d"] == 5.0
    assert "eps_current" not in store.read_snapshots(tmp_path).columns
    assert set(store.read_fx(tmp_path)["pair"]) == {"GBPEUR"}
    assert store.read_snapshots(tmp_path)["status"].tolist() == ["ok", "not_found"]


def test_analyst_component_reads_the_canonical_fundamentals_store() -> None:
    canonical, _ = store.append_period_rows(
        pd.DataFrame(columns=store.PERIOD_COLUMNS),
        "AAA",
        [
            {
                "period_end": "2026-10-01", "period_type": "ANALYST", "fiscal_year": 2026, "currency": "EUR",
                "source": "yfinance", "source_ref": "", "known_at": "2026-10-02T00:00:00+00:00",
                "eps_current": 4.4, "eps_90d_ago": 4.0, "revisions_up_30d": 5.0, "revisions_down_30d": 1.0,
            }
        ],
    )
    decision = datetime(2026, 10, 9, tzinfo=UTC)
    row = store.latest_analyst("AAA", canonical, decision)
    assert row is not None and "eps_current" not in store.SNAPSHOT_COLUMNS
    analyst = su.analyst_inputs(row)
    evidence = build_stock_evidence("AAA", [], decision, MarketInputs(), analyst, CONFIG)
    assert evidence.components["analyst_revision"].score_10 is not None


def test_refresh_moves_legacy_snapshot_analyst_rows_into_the_canonical_store(tmp_path) -> None:
    (tmp_path / "data" / "clean").mkdir(parents=True)
    legacy = {
        "instrument_id": "AAA", "known_at": "2026-10-02T00:00:00+00:00", "source": "yfinance",
        "status": "ok", "financial_currency": "EUR", "eps_current": 4.4, "eps_90d_ago": 4.0,
        "revisions_up_30d": 5.0, "revisions_down_30d": 1.0,
    }
    store._write(store.store_paths(tmp_path)["snapshots"], pd.DataFrame([legacy]))
    store.refresh_stock_fundamentals([], root=tmp_path, now=datetime(2026, 10, 9, tzinfo=UTC), config=CONFIG, environ={})
    analyst = store.latest_analyst("AAA", store.read_fundamentals(tmp_path), datetime(2026, 10, 9, tzinfo=UTC))
    assert analyst is not None and analyst["eps_current"] == 4.4


def test_targets_come_from_type_and_sector_not_from_ids() -> None:
    rows = [
        {"id": "S1", "instrument_type": "stock", "sector": "Industrials", "ticker": "S1.PA", "name": "S1"},
        {"id": "B1", "instrument_type": "stock", "sector": "Banks", "ticker": "B1.MI", "name": "B1"},
        {"id": "E1", "instrument_type": "etf", "sector": "Broad", "ticker": "E1.DE", "name": "E1"},
        {"id": "D1", "instrument_type": "stock", "sector": "Industrials", "ticker": "D1.PA", "name": "D1", "enabled": False},
    ]
    targets = store.targets_from_universe(rows, excluded_sectors=CONFIG["scope"]["excluded_sectors"])
    assert [t.instrument_id for t in targets] == ["S1"]


def test_notes_are_dated_atomic_append_only_and_can_be_retracted(tmp_path) -> None:
    first = notes.add_note("SU", "Check margin guidance in the Q3 call.", root=tmp_path, now=datetime(2026, 10, 1, tzinfo=UTC))
    second = notes.add_note("SU", "Bought 5 shares.", root=tmp_path, now=datetime(2026, 10, 5, tzinfo=UTC), tags=("trade",))
    listed = notes.list_notes("SU", root=tmp_path)
    assert [n["note_id"] for n in listed] == [second["note_id"], first["note_id"]]  # newest first
    assert listed[0]["created_at"].startswith("2026-10-05")
    notes.retract_note("SU", first["note_id"], root=tmp_path)
    assert [n["note_id"] for n in notes.list_notes("SU", root=tmp_path)] == [second["note_id"]]
    assert len(notes.list_notes("SU", root=tmp_path, include_retracted=True)) == 2
    assert (tmp_path / "data" / "notes" / "SU.jsonl").read_text(encoding="utf-8").count("\n") == 3
    with pytest.raises(notes.NoteError):
        notes.add_note("SU", "   ", root=tmp_path)
    with pytest.raises(notes.NoteError):
        notes.add_note("../evil", "x", root=tmp_path)


def test_user_peers_persist_and_override_automatic_peers(tmp_path) -> None:
    assert picks.set_user_peers("SU", ["LR", "SU", "ABB.ST", "LR", ""], root=tmp_path) == ["LR", "ABB.ST"]
    assert picks.load_user_peers(tmp_path) == {"SU": ["LR", "ABB.ST"]}
    with pytest.raises(ValueError):
        picks.set_user_peers("SU", ["bad id"], root=tmp_path)
    assert picks.set_user_peers("SU", [], root=tmp_path) == [] and picks.load_user_peers(tmp_path) == {}
    target = PeerProfile("SU", "Schneider", "Industrials", "Specialty Industrial Machinery", "Europe", 150.0)
    candidates = [
        PeerProfile("LR", "Legrand", "Industrials", "Electrical Equipment", "Europe", 36.0),
        PeerProfile("AIR", "Airbus", "Industrials", "Aerospace", "Europe", 148.0),
        PeerProfile("MSFT", "Microsoft", "Technology", "Software", "United States", 3300.0),
        PeerProfile("SU", "Schneider", "Industrials", "x", "Europe", 150.0),
    ]
    auto = auto_peers(target, candidates, CONFIG)
    assert [p.instrument_id for p in auto] == ["AIR", "LR"]  # same size band ranks AIR first; MSFT below threshold; never itself
    merged = effective_peers(auto, ["MSFT", "SU"], {"MSFT": "Microsoft"}, "SU")
    assert [(p.instrument_id, p.origin) for p in merged] == [("MSFT", "user"), ("AIR", "auto"), ("LR", "auto")]


def test_a_peer_must_share_the_industry_or_sector_region_and_size_only_rank() -> None:
    target = PeerProfile("T", "Target", sector="Technology", industry="Software", region="Europe", market_cap_eur_bn=30.0)
    same_region_and_size = PeerProfile("X", "Unrelated", sector="Utilities", industry="Power", region="Europe", market_cap_eur_bn=31.0)
    same_sector = PeerProfile("Y", "Same sector", sector="Technology", industry="Hardware", region="Europe", market_cap_eur_bn=31.0)
    picks = auto_peers(target, [same_region_and_size, same_sector], CONFIG)
    assert [p.instrument_id for p in picks] == ["Y"]  # region + size alone (score 2) is not a peer
    assert "same sector (Technology)" in picks[0].reasons and "same region (Europe)" in picks[0].reasons
