"""ETF1 regressions, using local evidence and offline source fixtures."""

from pathlib import Path
from types import SimpleNamespace
import json

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.core.config import load_config
from etf_cockpit.signals.simple_scores import build_simple_instrument_scores
from etf_cockpit.data.etf_economics import load_etf_e1_fields, calculate_etf_economics, TotalReturnEvidence
from etf_cockpit.data.fund_holdings import select_holdings_as_of, holdings_splits
from etf_cockpit.data.reference_data import validate_etf_metadata


FIXTURES = Path(__file__).parent / "fixtures" / "etf"


def test_vwce_recovers_numeric_score_from_etflive_prices():
    config = load_config()
    config.universe.etfs = [config.universe.by_id()["VWCE"]]
    prices = pd.read_json(FIXTURES / "etflive_vwce_prices.json", orient="table")
    scores = build_simple_instrument_scores(
        config, [], pd.DataFrame(), prices, universe_revision="etflive-fixture"
    )
    assert len(scores) == 1
    score = scores[0]
    assert score.display_id == "VWCE"
    assert isinstance(score.final_score_10, float)
    assert 0 < score.score_coverage < 1
    assert score.missing_components
    assert "relative_strength" in score.missing_components
    assert all(c.score_10 is None for c in score.components if c.key in score.missing_components)


def _source(source, **fields):
    return dict(instrument_id="VWCE", as_of="2026-01-01", known_at="2026-01-02", source=source, **fields)


def test_ter_fallback_prefers_issuer_then_public_then_yfinance_and_reports_missing():
    issuer = _source("issuer-fixture", ter=0.22, fee_unit="percent")
    public = _source("public-fixture", ter=0.0023, fee_unit="decimal_fraction")
    yahoo = _source("yfinance", ter=0.0024)
    def field(issuer_rows=(), public_rows=(), vendor_rows=()):
        return load_etf_e1_fields("VWCE", decision_time="2026-01-03", issuer_records=issuer_rows, public_records=public_rows, vendor_records=vendor_rows)["ter"]
    best = field([issuer], [public], [yahoo])
    assert best["value"] == pytest.approx(0.0022)
    assert best["source"] == "issuer-fixture" and best["difference"]
    assert len(best["alternates"]) == 2
    assert field(public_rows=[public], vendor_rows=[yahoo])["source"] == "public-fixture"
    vendor = field(vendor_rows=[yahoo])
    assert vendor["source"] == "yfinance" and vendor["known_at"] == "2026-01-02T00:00:00+00:00"
    missing = field()
    assert missing["value"] is None and missing["reason"] == "ter_missing_all_sources"
    assert field([dict(issuer, known_at="2026-01-04")])["reason"] == "ter_no_dated_source"
    other_class = dict(issuer, scope="share_class", share_class_id="other-class-fixture")
    assert field([other_class], vendor_rows=[yahoo])["source"] == "yfinance"


def test_aum_survives_reference_normalisation_without_inventing_currency():
    result = validate_etf_metadata(pd.DataFrame([dict(as_of_date="2026-01-01", etf_id="VWCE", total_assets=100_000_000)]), known_etfs=["VWCE"])
    assert result.ok
    assert result.frame.iloc[0]["aum"] == 100_000_000
    assert result.frame.iloc[0]["aum_unit"] == "currency_units"
    assert result.frame.iloc[0]["aum_currency"] == ""
    bad = validate_etf_metadata(pd.DataFrame([dict(as_of_date="2026-01-01", etf_id="VWCE", total_assets=-1)]), known_etfs=["VWCE"])
    assert not bad.ok


def test_tracking_difference_golden_reinvests_distribution_and_needs_index(tmp_path):
    from etf_cockpit.data.market_adjustments import CorporateAction, CorporateActionCoverage, CorporateActionCoverageStore, apply_total_return_adjustments

    prices = pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=4), "close": [100.0, 99.0, 100.0, 102.0], "instrument_id": "VWCE", "currency": "EUR", "source_id": "golden-fixture", "provenance": "unit-test"})
    action = CorporateAction(action_id="distribution-fixture", instrument_id="VWCE", action_type="dividend", announced_at="2026-01-01", effective_at="2026-01-02", ex_date="2026-01-02", payable_at="2026-01-05", known_at="2026-01-01", revision=1, source="unit-test", source_id="distribution-fixture", source_checksum="e" * 64, amount=2.0, currency="EUR")
    adjusted = apply_total_return_adjustments(prices, [action])
    with CorporateActionCoverageStore(tmp_path) as store:
        coverage = store.append(CorporateActionCoverage(instrument_id="VWCE", coverage_through="2026-01-06", published_at="2026-01-06", retrieved_at="2026-01-06", known_at="2026-01-06", revision=1, source="unit-test", source_id="coverage-fixture", source_checksum="c" * 64, status="active"))
        index_coverage = store.append(CorporateActionCoverage(instrument_id="FTSE-ALL-WORLD", coverage_through="2026-01-06", published_at="2026-01-06", retrieved_at="2026-01-06", known_at="2026-01-06", revision=1, source="unit-test", source_id="index-coverage-fixture", source_checksum="d" * 64, status="active"))
    fund = TotalReturnEvidence.from_adjustment_result(adjusted, instrument_id="VWCE", currency="EUR", known_at="2026-01-06", as_of="2026-01-06", source_id="golden-fixture", provenance="unit-test", corporate_action_coverage=coverage)
    index_prices = prices.assign(close=[100, 101, 102, 103], instrument_id="FTSE-ALL-WORLD")
    index = TotalReturnEvidence.from_adjustment_result(apply_total_return_adjustments(index_prices), instrument_id="FTSE-ALL-WORLD", currency="EUR", known_at="2026-01-06", as_of="2026-01-06", source_id="golden-fixture", provenance="unit-test", corporate_action_coverage=index_coverage)
    kwargs = dict(fund_total_return=fund, as_of="2026-01-06", horizon_days=3)
    records = [_source("golden-fixture", currency="EUR", benchmark_id="FTSE-ALL-WORLD", benchmark_currency="EUR", source_id="golden-fixture", source_provenance="unit-test", source_checksum="b" * 64)]
    report = calculate_etf_economics("VWCE", records, benchmark_total_return=index, **kwargs)
    # Ex-date reinvestment: 1.01 * (100/99) * (102/100) - 1;
    # index window: 103/100 - 1. The price-only difference would be -1%.
    assert report.tracking_difference == pytest.approx(1.01 * (100 / 99) * 1.02 - 1.03, abs=1e-9)
    assert report.matched_start.startswith("2026-01-01") and report.matched_end.startswith("2026-01-06")
    missing = calculate_etf_economics("VWCE", records, **kwargs)
    assert missing.tracking_difference is None and "benchmark_total_return" in missing.missing_evidence


def _holdings():
    return pd.DataFrame([
        dict(instrument_id="VWCE", security="Fixture holding", weight=0.6, country="USA", sector="Technology", as_of="2026-01-01", known_at="2026-01-02", source_id="holdings-fixture", authority="issuer"),
        dict(instrument_id="VWCE", security="Unclassified fixture", weight=0.1, country="", sector="", as_of="2026-01-01", known_at="2026-01-02", source_id="holdings-fixture", authority="issuer"),
        dict(instrument_id="VWCE", security="Future fixture", weight=1.0, country="Japan", sector="Financials", as_of="2026-01-04", known_at="2026-01-04", source_id="future-fixture", authority="issuer"),
    ])


def test_holdings_splits_reconcile_residual_and_exclude_future_vintage():
    selected = select_holdings_as_of(_holdings(), "VWCE", "2026-01-03")
    splits = holdings_splits(selected)
    assert len(selected) == 2
    for dimension in ("country", "sector"):
        assert sum(splits[dimension].values()) == pytest.approx(1.0)
        assert splits[dimension]["Other/unclassified"] == pytest.approx(0.4)
    assert splits["as_of"].startswith("2026-01-01") and splits["known_at"].startswith("2026-01-02")
    late = _holdings().iloc[:2].assign(known_at="2026-01-04")
    assert select_holdings_as_of(late, "VWCE", "2026-01-03").empty


@pytest.mark.parametrize("decision", [None, "2026-01-03T14:00:00Z", "2026-01-03T00:00:00Z"])
def test_snapshot_cutoff_includes_same_day_only_when_known_at_decision(decision):
    from datetime import date
    from etf_cockpit.application.etf_economics_view import build_etf_economics_panel

    snapshot = SimpleNamespace(
        data_report=SimpleNamespace(as_of_date=date(2026, 1, 3)),
        etf_metadata=pd.DataFrame([
            dict(_source("yfinance", ter=0.0022), as_of="2026-01-03", known_at="2026-01-03T12:00:00Z"),
            dict(_source("yfinance", ter=0.009), as_of="2026-01-04", known_at="2026-01-04T00:00:00Z"),
        ]),
        etf_holdings=pd.concat([
            _holdings().iloc[:2].assign(as_of="2026-01-03", known_at="2026-01-03T12:00:00Z"),
            _holdings().iloc[:2].assign(as_of="2026-01-04", known_at="2026-01-04T00:00:00Z", weight=0.4),
        ], ignore_index=True),
    )
    if decision is not None:
        snapshot.decision_time = decision
    panel = build_etf_economics_panel(snapshot, "VWCE")
    if decision == "2026-01-03T00:00:00Z":
        assert panel["e1"]["ter"]["value"] is None
        assert panel["holdings_count"] == 0
    else:
        assert panel["e1"]["ter"]["value"] == pytest.approx(0.0022)
        assert panel["holdings_count"] == 2
        assert panel["disclosed_weight"] == pytest.approx(0.7)
        assert panel["holdings_as_of"].startswith("2026-01-03")


def test_holdings_prefer_usable_issuer_before_newer_vendor_and_keep_alternates():
    issuer = _holdings().iloc[:2]
    vendor = issuer.assign(as_of="2026-01-02", source_id="vendor-fixture", authority="vendor", country="Japan")
    evidence = pd.concat([issuer, vendor], ignore_index=True)
    selected = select_holdings_as_of(evidence, "VWCE", "2026-01-03")
    assert len(selected) == 2 and selected["source_id"].eq("holdings-fixture").all()
    assert len(selected.attrs["alternates"]) == 1
    assert selected.attrs["alternates"][0][0]["country"] == "Japan"
    invalid_issuer = issuer.assign(weight=0.75)
    fallback = select_holdings_as_of(pd.concat([invalid_issuer, vendor]), "VWCE", "2026-01-03")
    assert fallback["authority"].eq("vendor").all()
    assert fallback.attrs["rejections"][0]["reason"] == "holdings_weights_not_usable"


@pytest.mark.parametrize("weights", [(0.6, 0.1), (0.2, 0.1)])
def test_holdings_select_one_latest_known_acquisition_per_vintage(weights):
    first = _holdings().iloc[:2].assign(weight=list(weights))
    second = first.assign(known_at="2026-01-03T12:00:00Z")
    future = first.assign(known_at="2026-01-04T00:00:00Z", weight=0.4)
    selected = select_holdings_as_of(pd.concat([first, second, future]), "VWCE", "2026-01-03")
    assert len(selected) == 2
    assert selected["known_at"].eq(pd.Timestamp("2026-01-03T12:00:00Z")).all()
    assert holdings_splits(selected)["disclosed_weight"] == pytest.approx(sum(weights))
    assert holdings_splits(selected)["reason"] is None
    before = select_holdings_as_of(pd.concat([first, second]), "VWCE", "2026-01-03T10:00:00Z")
    assert before["known_at"].eq(pd.Timestamp("2026-01-02", tz="UTC")).all()


@pytest.mark.parametrize("invalid", [{"USA": 1.5}, {"USA": -0.2}, {"USA": float("inf")}, {"USA": "bad"}, {}])
def test_invalid_preferred_splits_fall_through_in_canonical_loader(invalid):
    from etf_cockpit.application.etf_economics_view import build_etf_economics_panel

    issuer = _source("issuer-fixture", source_authority="issuer_document", country_split=invalid, sector_split=invalid)
    public = _source("public-fixture", source_authority="public_page", country_split={"USA": 0.6}, sector_split={"Technology": 0.6})
    fields = load_etf_e1_fields("VWCE", decision_time="2026-01-03", issuer_records=[issuer], public_records=[public])
    for name in ("country_split", "sector_split"):
        assert fields[name]["source"] == "public-fixture"
        assert sum(fields[name]["value"].values()) == pytest.approx(1.0)
        assert fields[name]["value"]["Other/unclassified"] == pytest.approx(0.4)
        assert fields[name]["rejections"][0]["source"] == "issuer-fixture"
        assert fields[name]["rejections"][0]["reason"] == f"{name}_weights_not_usable"
    panel = build_etf_economics_panel(SimpleNamespace(data_report=SimpleNamespace(as_of_date="2026-01-03"), etf_metadata=pd.DataFrame([issuer, public]), etf_holdings=pd.DataFrame()), "VWCE")
    assert panel["e1"]["country_split"]["source"] == "public-fixture"


def _walk(control):
    if not isinstance(control, ft.Control):
        return
    yield control
    for name in ("controls", "items"):
        for child in getattr(control, name, None) or ():
            yield from _walk(child)
    yield from _walk(getattr(control, "content", None))


def _texts(root):
    return "\n".join(str(item.value) for item in _walk(root) if isinstance(item, ft.Text) and item.value)


def test_etf_page_renders_e1_tiles_holdings_and_both_split_charts():
    from etf_cockpit.application.etf_economics_view import build_etf_economics_panel
    from etf_cockpit.app.pages.instrument_detail import render_etf_e1_panel
    from etf_cockpit.app.components.chartkit import ChartHandle

    snapshot = SimpleNamespace(data_report=SimpleNamespace(as_of_date="2026-01-03"), etf_metadata=pd.DataFrame([_source("yfinance", ter=0.0022)]), etf_holdings=_holdings())
    payload = build_etf_economics_panel(snapshot, "VWCE")
    root = render_etf_e1_panel(payload)
    text = _texts(root)
    for label in ("TER", "TRACKING DIFFERENCE", "FUND SIZE (AUM)", "DISTRIBUTION POLICY", "DISCLOSED HOLDINGS", "Country split", "Sector split", "Fixture holding"):
        assert label in text
    for name in ("aum", "distribution_policy", "tracking_difference"):
        assert payload["e1"][name]["reason"] in text
    assert len([item for item in _walk(root) if isinstance(getattr(item, "data", None), ChartHandle)]) == 2
    assert "{'" not in text and '"value":' not in text
    assert "Other/unclassified: 40.00%" in text
    assert payload["holdings_count"] == 2 and len(payload["holdings"]) == 2


def _sector_snapshot(portfolio=True):
    config = load_config()
    by_id = config.universe.by_id()
    config.universe.etfs = [by_id["VWCE"], by_id["MSFT"].model_copy(update={"sector": "Financials"})]
    return SimpleNamespace(
        config=config, data_report=SimpleNamespace(as_of_date="2026-07-18"), prices=pd.DataFrame(), signals=[], forecasts=pd.DataFrame(),
        holdings=pd.DataFrame({"etf_id": ["VWCE", "MSFT"], "current_weight": [0.8, 0.2]}) if portfolio else pd.DataFrame(),
        sector_position_metadata={"MSFT": {"exposure_type": "security", "known_at": "2026-07-01", "country": "GB", "sector": "Financials", "entity": "Direct stock fixture"}},
        sector_score_evidence=[{"instrument_id": "MSFT", "score": 7.0}],
    )


def test_sectors_page_look_through_plus_direct_stocks_and_explicit_empty_state(monkeypatch):
    from tests.test_exposure_cube import _apple_holding
    from etf_cockpit.application.ui_views import sectors as view
    from etf_cockpit.app.pages.sectors import sectors_page

    data = view.load(_sector_snapshot(), holdings=_apple_holding("VWCE"))
    assert {item.name: item.weight for item in data.sectors} == {"Information Technology": 80.0, "Financials": 20.0}
    assert sum(item.weight for item in data.countries) == pytest.approx(100)
    assert data.attractiveness["Financials"]["score"] == 7.0
    assert data.attractiveness["Information Technology"]["score"] is None
    monkeypatch.setattr(view, "load", lambda *_args, **_kw: data)
    root = sectors_page(None, SimpleNamespace(snapshot=None)).body
    assert "Sector attractiveness heatmap" in _texts(root) and "7.0/10" in _texts(root)
    monkeypatch.undo()
    empty = view.load(SimpleNamespace(holdings=pd.DataFrame()), holdings=pd.DataFrame())
    monkeypatch.setattr(view, "load", lambda *_args, **_kw: empty)
    text = _texts(sectors_page(None, SimpleNamespace(snapshot=None)).body)
    assert "Register portfolio holdings or add enabled instruments" in text
    assert "Unavailable" in text


def test_sectors_consumes_dated_reference_holdings_when_direct_store_is_empty(monkeypatch):
    from tests.test_exposure_cube import _apple_holding
    from etf_cockpit.application import overlap, etf_economics_view
    from etf_cockpit.application.ui_views import sectors as view

    snapshot = _sector_snapshot()
    snapshot.decision_time = "2026-07-18T10:00:00Z"
    reference = pd.concat([
        _apple_holding("VWCE").assign(as_of="2026-07-18", known_at="2026-07-18T09:00:00Z"),
        _apple_holding("VWCE").assign(as_of="2026-07-18", known_at="2026-07-18T11:00:00Z", sector="Energy"),
    ], ignore_index=True)
    calls = []
    monkeypatch.setattr(overlap, "load_direct_holdings", lambda: pd.DataFrame())
    def load_reference(dataset):
        calls.append(dataset)
        return reference if dataset == "etf_holdings" else pd.DataFrame()
    monkeypatch.setattr(etf_economics_view, "load_etf_reference_context", load_reference)
    data = view.load(snapshot)
    assert calls == ["etf_holdings"]
    assert {item.name: item.weight for item in data.sectors} == {"Information Technology": 80.0, "Financials": 20.0}
    assert sum(item.weight for item in data.countries) == pytest.approx(100)
    panel = etf_economics_view.build_etf_economics_panel(snapshot, "VWCE")
    assert panel["holdings_count"] == 1
    assert panel["e1"]["sector_split"]["value"] == {"Information Technology": 1.0}


def test_no_portfolio_holdings_shows_labelled_universe_exposure_tiles(monkeypatch):
    from tests.test_exposure_cube import _apple_holding
    from etf_cockpit.application.ui_views import sectors as view
    from etf_cockpit.app.pages.sectors import sectors_page

    snapshot = _sector_snapshot(portfolio=False)
    data = view.load(snapshot, holdings=_apple_holding("VWCE"))
    assert data.exposure_label == "Universe (no portfolio holdings registered)"
    assert {item.name: item.weight for item in data.sectors} == {"Information Technology": 50.0, "Financials": 50.0}
    assert sum(item.weight for item in data.countries) == pytest.approx(100)
    unmapped = view.load(snapshot, holdings=pd.DataFrame())
    assert sum(item.weight for item in unmapped.countries) == pytest.approx(100)
    assert sum(item.weight for item in unmapped.sectors) == pytest.approx(100)
    assert any(item.name == view.UNKNOWN for item in unmapped.sectors)
    monkeypatch.setattr(view, "load", lambda *_args, **_kw: data)
    text = _texts(sectors_page(None, SimpleNamespace(snapshot=snapshot)).body)
    assert data.exposure_label in text and "Equal weight per analysed instrument" in text
    assert "50.0%" in text and "Register portfolio holdings" in text


def test_source_fetchers_use_offline_fixtures_and_fall_back_after_failure():
    from etf_cockpit.data.fund_adapters import fetch_etf_economics_sources

    fixture = json.loads((FIXTURES / "economics_sources.json").read_text(encoding="utf-8"))
    calls = []
    def reader(name):
        def fetch(instrument_id):
            assert instrument_id == "VWCE"
            calls.append(name)
            return fixture[name]
        return fetch
    result = fetch_etf_economics_sources("VWCE", decision_time="2026-01-03", issuer_reader=reader("issuer"), public_reader=reader("public_page"), vendor_reader=reader("yfinance"))
    assert calls == ["issuer", "public_page", "yfinance"]
    assert result["fields"]["ter"]["source"] == "issuer-fixture"
    assert result["fields"]["ter"]["difference"]
    def offline(_instrument_id):
        raise OSError("offline fixture")
    fallback = fetch_etf_economics_sources("VWCE", decision_time="2026-01-03", issuer_reader=offline, public_reader=offline, vendor_reader=reader("yfinance"))
    assert fallback["fields"]["ter"]["source"] == "yfinance"
    assert fallback["failures"] == {"issuer": "OSError", "public_page": "OSError"}
    assert fallback["execution_allowed"] is False


def test_yfinance_metadata_fetcher_offline_preserves_aum(monkeypatch):
    from etf_cockpit.data.yfinance_provider import YFinanceProvider

    config = load_config()
    config.universe.etfs = [config.universe.by_id()["VWCE"]]
    provider = YFinanceProvider.from_config(config)
    ticker = SimpleNamespace(info={"totalAssets": 100_000_000, "currency": "USD"}, fast_info={}, funds_data=None)
    calls = []
    def offline_ticker(symbol):
        calls.append(symbol)
        return ticker
    monkeypatch.setattr(provider, "_ticker", offline_ticker)
    result = provider.fetch_etf_metadata([])
    assert result.ok and result.provider_name == "yfinance"
    assert calls == ["VWCE.DE"]
    assert result.metadata.ingested_at is not None
    validated = validate_etf_metadata(result.data, known_etfs=["VWCE"])
    assert validated.ok and validated.frame.iloc[0]["aum"] == 100_000_000
    assert validated.frame.iloc[0]["aum_currency"] == ""


def test_live_snapshot_cutoff_is_its_build_time_and_replays_keep_their_decision_time():
    from types import SimpleNamespace

    import pandas as pd

    from etf_cockpit.data.etf_cutoff import snapshot_etf_cutoff

    built = "2026-10-09T20:15:00+00:00"
    live = SimpleNamespace(benchmark_reference_decision_time="2026-10-09T00:00:00+00:00", facts_known_at=built, data_report=None)
    assert snapshot_etf_cutoff(live) == pd.Timestamp(built)
    replay = SimpleNamespace(decision_time="2026-10-01T08:00:00+00:00", facts_known_at=built, data_report=None)
    assert snapshot_etf_cutoff(replay) == pd.Timestamp("2026-10-01T08:00:00+00:00")
