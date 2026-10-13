"""Issue #965 (bughunt A/B/E): peer and analyst evidence must be fresh, supported, PIT and fail closed."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from test_peer_cohorts import AS_OF, DECISION, _context, _observation

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis import stock_universe as su
from etf_cockpit.analysis.peer_cohorts import (
    AdapterRegistry,
    PeerCohortError,
    bootstrap_percentile_interval,
    build_peer_projection,
    effective_sample_size,
)
from etf_cockpit.analysis.stock_evidence import AnalystInputs, MarketInputs, build_stock_evidence
from etf_cockpit.analysis.stock_peers import auto_peers, PeerProfile
from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data import stock_peer_picks as picks
from etf_cockpit.data.stock_fundamentals import load_stock_config

UTC = timezone.utc
CONFIG = load_stock_config()
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _period(year: int, *, income: float = 100.0, known: str | None = None) -> sm.Period:
    values = {
        "revenue": 1000.0, "gross_profit": 400.0, "ebit": 200.0, "da": 60.0, "pretax_income": 180.0, "income_tax": 45.0,
        "net_income_parent": income, "cfo": 220.0, "capex": 70.0, "dividends_paid": 30.0, "equity_parent": 900.0,
        "minority_interest": 30.0, "ib_debt": 300.0, "lease_liabilities": 50.0, "cash_sti": 150.0, "shares_outstanding": 10.0,
    }
    known_at = datetime.fromisoformat(known or f"{year + 1}-02-15").replace(tzinfo=UTC)
    return sm.Period(date(year, 12, 31), "FY", known_at, "EUR", "sec_edgar", values)


# ----- B009-N001: stale peer P/E leaves the discount ----------------------------------------------------------------


def _universe(monkeypatch: pytest.MonkeyPatch, periods: dict[str, list[sm.Period]], picks_for_t: list[str]) -> su.UniverseEvidence:
    ids = list(periods)
    rows = [{"id": i, "instrument_type": "stock", "ticker": i, "sector": "Industrials"} for i in ids]
    records = su.stock_records(rows, CONFIG)
    monkeypatch.setattr(store, "read_fundamentals", lambda _root: pd.DataFrame(columns=store.PERIOD_COLUMNS))
    monkeypatch.setattr(store, "read_snapshots", lambda _root: pd.DataFrame(columns=store.SNAPSHOT_COLUMNS))
    monkeypatch.setattr(store, "read_fx", lambda _root: pd.DataFrame(columns=store.FX_COLUMNS))
    monkeypatch.setattr(store, "periods_for", lambda iid, _frame, _chain: periods.get(iid, []))
    monkeypatch.setattr(su, "load_user_peers", lambda _root: {"T": picks_for_t})
    prices = pd.DataFrame(
        {"etf_id": ids, "date": pd.to_datetime(["2026-02-27"] * len(ids)), "close": [50.0] * len(ids), "currency": ["EUR"] * len(ids), "dividends": [0.0] * len(ids)}
    )
    return su.build_universe_evidence(records, prices, NOW, config=CONFIG)


def test_stale_peer_pe_is_excluded_from_the_discount(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh = [_period(y) for y in (2022, 2023, 2024, 2025)]
    periods = {"T": fresh, "A": fresh, "B": fresh, "C": fresh, "S": [_period(y, income=1.0) for y in (2020, 2021)]}
    evidence = _universe(monkeypatch, periods, ["A", "B", "C", "S"])
    assert evidence.evidence["S"].metrics["pe"].available  # the stale peer still has a P/E ...
    stat = evidence.evidence["T"].peer_stats["pe"]
    assert stat.count == 3  # ... but it is not part of the peer set the discount uses
    assert stat.median == pytest.approx(evidence.evidence["A"].metrics["pe"].value)


# ----- B009-N002 / B009-N003: support floor and ESS bootstrap -------------------------------------------------------


def test_projection_below_minimum_support_is_unavailable() -> None:
    target = _context("TARGET")
    observations = (_observation("P1", 1.0), _observation("P2", 2.0))
    projection = build_peer_projection(
        target, observations, metric="quality", target_value=1.5, effective_at=AS_OF, decision_time=DECISION,
        registry=AdapterRegistry(), applicable=True, minimum_support=3,
    )
    assert projection.cohort.support == 2
    assert projection.metric.status == "unavailable" and projection.metric.reason_code == "PEER_SUPPORT_BELOW_MINIMUM"
    assert projection.metric.percentile is None and projection.metric.shrunk_percentile is None and projection.metric.interval is None
    enough = build_peer_projection(
        target, (*observations, _observation("P3", 3.0)), metric="quality", target_value=1.5, effective_at=AS_OF,
        decision_time=DECISION, registry=AdapterRegistry(), applicable=True, minimum_support=3,
    )
    assert enough.metric.status == "available"


def test_bootstrap_interval_shrinks_with_the_effective_sample_size() -> None:
    weights = [1.0, 1.0, 1.0, 1000.0]
    ess = effective_sample_size(weights)
    low, high = bootstrap_percentile_interval(
        [1.0, 2.0, 3.0, 4.0], weights, 0.0, parent_percentile=1.0, shrinkage_strength=5.0, seed=3, samples=50
    )
    # every resample ranks the target at 0, so the draw is exactly the ESS-weighted shrinkage of the parent percentile
    assert low == pytest.approx(5.0 / (ess + 5.0)) and high == pytest.approx(5.0 / (ess + 5.0))
    with pytest.raises(PeerCohortError):
        bootstrap_percentile_interval([1.0], [1.0], 0.0, parent_percentile=0.5, shrinkage_strength=5.0, seed=1, samples=0)


# ----- B010-N001/N002/N003: analyst snapshot age, partial snapshots, negative counts --------------------------------


def _analyst_component(analyst: AnalystInputs | None):
    market = MarketInputs(price=50.0, price_currency="EUR", price_date=date(2026, 2, 27))
    return build_stock_evidence("T", [_period(2025)], NOW, market, analyst, CONFIG).components["analyst_revision"]


def _complete(**overrides: object) -> AnalystInputs:
    values = dict(eps_current=4.4, eps_90d_ago=4.0, revisions_up_30d=4.0, revisions_down_30d=1.0, known_at=NOW - timedelta(days=1))
    values.update(overrides)
    return AnalystInputs(**values)  # type: ignore[arg-type]


def test_old_analyst_snapshot_is_not_scored_and_partial_newer_cannot_raise_it() -> None:
    assert _analyst_component(_complete()).score_10 is not None
    old = _analyst_component(_complete(known_at=NOW - timedelta(days=400)))
    assert old.score_10 is None and "days old" in old.why
    complete = _analyst_component(_complete(eps_current=3.9, revisions_up_30d=1.0, revisions_down_30d=4.0)).score_10
    partial = _analyst_component(_complete(eps_current=None, eps_90d_ago=None, revisions_up_30d=5.0, revisions_down_30d=0.0))
    assert partial.score_10 is None and "partial" in partial.why  # not a high score built from one favourable field
    assert complete is not None and complete < 5.0


@pytest.mark.parametrize("field", ["revisions_up_30d", "revisions_down_30d"])
def test_negative_revision_counts_are_rejected(field: str) -> None:
    component = _analyst_component(_complete(**{field: -3.0}))
    assert component.score_10 is None and "negative revision" in component.why


# ----- A024-N003 / E103-N003: peer store integrity ------------------------------------------------------------------


@pytest.mark.parametrize("payload", ["[]", '"text"', "42", "null", "{broken"])
def test_non_object_peer_json_invalidates_only_the_file(tmp_path, payload: str) -> None:
    path = picks.picks_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")
    assert picks.load_user_peers(tmp_path) == {}
    assert picks.set_user_peers("T", ["A"], root=tmp_path) == ["A"]  # the file is usable again afterwards
    assert picks.load_user_peers(tmp_path) == {"T": ["A"]}


def test_non_object_peer_json_leaves_other_stock_evidence_intact(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    path = picks.picks_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("[1, 2]", encoding="utf-8")
    fresh = [_period(y) for y in (2022, 2023, 2024, 2025)]
    monkeypatch.setattr(store, "read_fundamentals", lambda _root: pd.DataFrame(columns=store.PERIOD_COLUMNS))
    monkeypatch.setattr(store, "read_snapshots", lambda _root: pd.DataFrame(columns=store.SNAPSHOT_COLUMNS))
    monkeypatch.setattr(store, "read_fx", lambda _root: pd.DataFrame(columns=store.FX_COLUMNS))
    monkeypatch.setattr(store, "periods_for", lambda _iid, _frame, _chain: fresh)
    records = su.stock_records([{"id": "T", "instrument_type": "stock", "ticker": "T"}], CONFIG)
    prices = pd.DataFrame({"etf_id": ["T"], "date": pd.to_datetime(["2026-02-27"]), "close": [50.0], "currency": ["EUR"], "dividends": [0.0]})
    evidence = su.build_universe_evidence(records, prices, NOW, root=tmp_path, config=CONFIG)
    assert evidence.evidence["T"].metrics["revenue"].available


def test_concurrent_peer_upserts_keep_both_entries(tmp_path) -> None:
    ids = [f"S{i}" for i in range(12)]
    errors: list[BaseException] = []

    def upsert(instrument_id: str) -> None:
        try:
            picks.set_user_peers(instrument_id, [f"P{instrument_id}"], root=tmp_path)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=upsert, args=(i,)) for i in ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert picks.load_user_peers(tmp_path) == {i: [f"P{i}"] for i in ids}


# ----- B103-N001 / B103-N002 / E103-N004 / E103-N005 / B110 ---------------------------------------------------------


def test_month_end_history_is_dated_by_the_last_stored_price() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-29", "2026-02-26", "2026-02-27", "2026-03-02"]),
            "close": [10.0, 11.0, 12.0, 13.0],
            "currency": ["EUR"] * 4,
        }
    )
    market = su.market_inputs(frame, None, "EUR", datetime(2026, 3, 3, tzinfo=UTC), pd.DataFrame(columns=store.FX_COLUMNS), CONFIG)
    # 2026-02-28 is a Saturday: a filing known on it must not be paired with the Friday close of the 27th
    assert market.price_series == ((date(2026, 1, 29), 10.0), (date(2026, 2, 27), 12.0))


def _profile_with_fx(snapshot: dict, currency: str = "GBP"):
    fx = pd.DataFrame(
        {"pair": ["GBPEUR", "GBPEUR"], "date": ["2026-01-10", "2026-02-28"], "rate": [1.2, 2.0], "known_at": ["2026-01-10", "2026-02-28"]}
    )
    record = su.StockRecord("X", "X", "X", currency, "", "")
    return su._profile(record, snapshot, fx, CONFIG, NOW)


def test_peer_size_uses_the_fx_vintage_of_the_capitalisation_date() -> None:
    snapshot = {"market_cap_provider": 10e9, "quote_currency": "GBP", "known_at": "2026-01-10"}
    assert _profile_with_fx(snapshot).market_cap_eur_bn == pytest.approx(12.0)
    assert _profile_with_fx({**snapshot, "known_at": None}).market_cap_eur_bn is None


def test_market_cap_without_a_currency_is_not_sized() -> None:
    assert _profile_with_fx({"market_cap_provider": 10e9, "known_at": "2026-01-10"}, currency="").market_cap_eur_bn is None


def test_unparseable_lifecycle_cutoff_fails_closed(tmp_path) -> None:
    rows = [
        {"id": "BAD", "instrument_type": "stock", "ticker": "BAD", "lifecycle_date": "not-a-date"},
        {"id": "OK", "instrument_type": "stock", "ticker": "OK", "lifecycle_date": "2026-12-31"},
        {"id": "LIVE", "instrument_type": "stock", "ticker": "LIVE"},
    ]
    records = su.stock_records(rows, CONFIG)
    assert [r.instrument_id for r in records] == ["BAD", "OK", "LIVE"]
    assert [r.invalid_lifecycle for r in records] == [True, False, False]
    result = su.build_universe_evidence(records, pd.DataFrame(), datetime(2026, 6, 1, tzinfo=timezone.utc), root=tmp_path, config=CONFIG)
    assert "BAD" not in result.evidence and "invalid_lifecycle_date" in result.excluded["BAD"]
    assert "OK" in result.evidence and "LIVE" in result.evidence


@pytest.mark.parametrize("blank", [float("nan"), pd.NaT, None, "", "  ", "NaT"])
def test_blank_lifecycle_cell_means_no_cutoff(blank: object) -> None:
    rows = [{"id": "LIVE", "instrument_type": "stock", "ticker": "LIVE", "lifecycle_date": blank}]
    (record,) = su.stock_records(rows, CONFIG)
    assert record.lifecycle_date is None and not record.invalid_lifecycle


def test_equal_peer_scores_order_by_instrument_id_not_row_order() -> None:
    target = PeerProfile("T", "T", "Industrials", "", "EU", None)
    candidates = [PeerProfile(i, i, "Industrials", "", "EU", None) for i in ("C", "A", "B")]
    forward = [p.instrument_id for p in auto_peers(target, candidates, CONFIG)]
    backward = [p.instrument_id for p in auto_peers(target, list(reversed(candidates)), CONFIG)]
    assert forward == backward == ["A", "B", "C"]


def test_dataclass_replace_keeps_support_floor_out_of_other_callers() -> None:
    # calculate_peer_metric without a floor keeps its previous behaviour (fund peers apply their own policy)
    from etf_cockpit.analysis.peer_cohorts import calculate_peer_metric, construct_cohort

    cohort = construct_cohort(_context("TARGET"), (_observation("P1", 1.0),), metric="quality", effective_at=AS_OF, decision_time=DECISION)
    assert calculate_peer_metric("quality", 1.0, cohort, applicable=True).status == "available"
    assert replace(cohort, support=3).support == 3 and cohort.support == 1


def test_sparebank_peer_ranking_uses_one_formula_version(tmp_path) -> None:
    from etf_cockpit.application import sparebank_peers as sp

    def row(identifier: str, composite: float, version: str | None) -> dict[str, object]:
        return {"instrument_id": identifier, "name": identifier, "as_of": "2026-10-01T00:00:00Z", "composite": composite, "formula_version": version}

    for item in (row("SELF", 6.0, "v2"), row("OLD", 9.9, "v1"), row("LOW", 5.0, "v2"), row("HIGH", 7.0, "v2"), row("NOVER", 9.0, None)):
        sp.record_peer_row(tmp_path, item)
    rows = sp.load_peer_rows(tmp_path, "SELF", "2026-10-09T00:00:00Z")
    assert [r["instrument_id"] for r in rows] == ["HIGH", "LOW", "NOVER", "OLD"]
    assert {r["instrument_id"]: r["formula_mismatch"] for r in rows} == {"HIGH": False, "LOW": False, "OLD": True, "NOVER": True}
    assert all(r["composite"] is None for r in rows if r["formula_mismatch"])
    # an explicit version of the viewed scorecard wins over the stored row
    assert [r["instrument_id"] for r in sp.load_peer_rows(tmp_path, "SELF", "2026-10-09T00:00:00Z", "v1")][0] == "OLD"


def test_add_peer_saves_the_current_selection_after_a_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    # E103-N002: the Save closure reads the picker live, so a rebuilt card persists the changed selection, not a stale one.
    from types import SimpleNamespace

    from etf_cockpit.app.pages import stock_page as page
    from etf_cockpit.application import stock_service as service

    class _Sync:
        def __init__(self, target, **_kw: object) -> None:
            self._target = target

        def start(self) -> None:
            self._target()

    stored: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(page, "threading", SimpleNamespace(Thread=_Sync))
    monkeypatch.setattr(service, "stock_universe_records", lambda _config: [SimpleNamespace(instrument_id=i) for i in ("A", "B", "C")])
    monkeypatch.setattr(picks, "set_user_peers", lambda iid, ids, *, root=None: stored.append((iid, list(ids))) or list(ids))
    model = SimpleNamespace(instrument_id="T", user_peers=["A"], peers=[], peer_summary="")

    def find(control: object, key: str):
        stack = [control]
        while stack:
            item = stack.pop()
            if getattr(item, "key", None) == key:
                return item
            stack.extend(getattr(item, "controls", None) or [])
            if getattr(item, "content", None) is not None:
                stack.append(item.content)
        raise AssertionError(key)

    first = page.peers_card(model, config=None)
    find(first, "stock.peers.input").value = "A, B"
    rebuilt = page.peers_card(SimpleNamespace(**{**vars(model), "user_peers": ["A", "B"]}), config=None)
    find(rebuilt, "stock.peers.input").value = "C"
    find(rebuilt, "stock.peers.save").on_click(None)
    assert stored == [("T", ["C"])]
    find(first, "stock.peers.save").on_click(None)
    assert stored[-1] == ("T", ["A", "B"])
