from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application import ui_facade
from etf_cockpit.application.benchmark_reference import adjusted_price_snapshot_binding
from etf_cockpit.app.selectors.instrument_detail import _factor_risk_panel
from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry, ReferencePortfolioDefinition
from etf_cockpit.portfolio.sandbox import holdings_checksum
from etf_cockpit.features.feature_pipeline import compute_features


def _snapshot():
    rng = np.random.default_rng(19)
    dates = pd.bdate_range("2025-01-01", periods=100)
    rows = []
    for index in range(8):
        identity = f"ETF{index}" if index < 7 else "STOCK"
        values = 100 * np.exp(np.cumsum(rng.normal(0.0002 + index * 0.0001, 0.006, len(dates))))
        rows.extend({"date": day.date(), "etf_id": identity, "adjusted_close": value, "volume": 10000.0, "known_at": f"{day.date()}T23:00:00+00:00"} for day, value in zip(dates, values))
    prices = pd.DataFrame(rows)
    feature_frame = compute_features(prices)
    as_of = dates[-1].date()
    window = {"start_date": str(dates[0].date()), "end_date": str(as_of), "decision_time": f"{as_of}T23:59:59+00:00"}
    feature_frame.attrs["price_binding"] = adjusted_price_snapshot_binding(prices, calculation_window=window)
    holdings = pd.DataFrame([{"etf_id": "ETF0", "current_weight": 1.0, "market_value_eur": 1000.0, "as_of_date": str(as_of), "known_at": f"{as_of}T12:00:00+00:00"}])
    reference = ReferencePortfolioDefinition(
        portfolio_id="reference:no_trade", version="1.0.0", method="no_trade",
        constituent_instrument_ids=("ETF0", "cash:EUR"), methodology="Bound test holdings",
        effective_at=f"{as_of}T00:00:00+00:00", known_at=f"{as_of}T12:00:00+00:00",
        current_weights={"ETF0": 1.0, "cash:EUR": 0.0}, currency="EUR", source_hashes=(holdings_checksum(holdings),),
    )
    return SimpleNamespace(prices=prices, features=feature_frame, latest_features=pd.DataFrame(), holdings=holdings,
        benchmark_reference_registry=CanonicalBenchmarkRegistry(reference_portfolios=(reference,)),
        data_report=SimpleNamespace(as_of_date=as_of), universe_revision="fixture-v1")


@pytest.mark.parametrize("identity", ["ETF0", "STOCK"])
def test_bound_factor_panel_has_actual_canonical_numeric_coverage(identity, monkeypatch):
    snapshot = _snapshot()
    producer = ui_facade.build_factor_risk_report
    observed = {}

    def capture(prices, allocation, features, holdings):
        observed["allocation"] = allocation
        assert holdings is None
        assert not {"sector", "region", "currency"} & set(allocation)
        return producer(prices, allocation, features, holdings)

    monkeypatch.setattr(ui_facade, "build_factor_risk_report", capture)
    panel = _factor_risk_panel(snapshot, identity)
    assert panel["status"] in {"available", "partial"}
    assert panel["selected_instrument_status"] == "available"
    assert panel["specific_risk"][0]["specific_vol_ann"] > 0
    assert all(row["instrument_id"] == identity for key in ("specific_risk", "factor_exposures", "instrument_contributions") for row in panel[key])
    assert panel["historical_binding_status"] == "verified_snapshot"
    assert panel["price_snapshot_checksum"] == snapshot.features.attrs["price_binding"]["price_snapshot_checksum"]
    assert panel["holdings_checksum"] == holdings_checksum(snapshot.holdings)
    assert panel["universe_revision"] == "fixture-v1"
    assert panel["model_version"] == "factor_risk.v1"
    assert panel["lookthrough_status"] == "unsupported"
    assert panel["retrospective_universe_replay"] == "unsupported"
    assert panel["execution_allowed"] is False
    stock = observed["allocation"].set_index("etf_id").loc["STOCK"]
    assert stock["current_weight"] == 0
    assert pd.isna(stock["market_value_eur"])


@pytest.mark.parametrize("damage", ["absent_binding", "forged_binding", "future_features", "missing_reference", "checksum", "late_known", "future_holdings", "mismatched_weights"])
def test_bound_factor_panel_rejects_unverified_inputs_before_producer(damage, monkeypatch):
    snapshot = _snapshot()
    reference = snapshot.benchmark_reference_registry.reference_portfolios[0]
    if damage == "absent_binding":
        snapshot.features.attrs.clear()
    elif damage == "forged_binding":
        snapshot.features.attrs["price_binding"]["price_snapshot_checksum"] = "0" * 64
    elif damage == "future_features":
        snapshot.features.loc[0, "date"] = "2099-01-01"
    elif damage == "missing_reference":
        snapshot.benchmark_reference_registry = CanonicalBenchmarkRegistry()
    elif damage == "checksum":
        snapshot.holdings.loc[0, "market_value_eur"] = 2000.0
    elif damage == "future_holdings":
        snapshot.holdings.loc[0, "as_of_date"] = "2099-01-01"
    else:
        fields = {"known_at": "2099-01-01T00:00:00+00:00"} if damage == "late_known" else {"current_weights": {"ETF0": 0.9, "cash:EUR": 0.1}}
        reference = replace(reference, **fields, content_hash="")
        snapshot.benchmark_reference_registry = CanonicalBenchmarkRegistry(reference_portfolios=(reference,))
    monkeypatch.setattr(ui_facade, "build_factor_risk_report", lambda *a, **kw: pytest.fail("invalid inputs reached producer"))
    panel = ui_facade.load_bound_factor_risk_panel(snapshot, "ETF0")
    assert panel["status"] == "unavailable"
    assert panel["historical_binding_status"] == "unavailable"
    assert panel["factor_exposures"] == []
    assert panel["execution_allowed"] is False


def test_bound_factor_panel_distinguishes_global_from_missing_selected_coverage():
    panel = ui_facade.load_bound_factor_risk_panel(_snapshot(), "MISSING")
    assert panel["global_report_status"] in {"available", "partial"}
    assert panel["status"] == "unavailable"
    assert panel["selected_instrument_status"] == "absent"
    assert panel["coverage"]["status"] == "unavailable"
    assert all(panel[key] == [] for key in ("factor_exposures", "specific_risk", "instrument_contributions"))


def test_bound_factor_panel_suppresses_selected_rows_without_model_coverage():
    snapshot = _snapshot()
    snapshot.prices = snapshot.prices.loc[~snapshot.prices["etf_id"].eq("STOCK") | snapshot.prices["date"].eq(snapshot.data_report.as_of_date)].copy()
    window = snapshot.features.attrs["price_binding"]["calculation_window"]
    snapshot.features = compute_features(snapshot.prices)
    snapshot.features.attrs["price_binding"] = adjusted_price_snapshot_binding(snapshot.prices, calculation_window=window)
    panel = ui_facade.load_bound_factor_risk_panel(snapshot, "STOCK")
    assert panel["global_report_status"] in {"available", "partial"}
    assert panel["selected_instrument_status"] == "insufficient_model_coverage"
    assert panel["status"] == "unavailable"
    assert panel["factor_exposures"] == []
    assert panel["specific_risk"] == []
    assert panel["instrument_contributions"] == []

@pytest.mark.parametrize("column", ["momentum_60d", "vol_60d_ann"])
def test_bound_factor_panel_rejects_descriptor_tampering_with_unchanged_price_binding(column, monkeypatch):
    snapshot = _snapshot()
    binding = dict(snapshot.features.attrs["price_binding"])
    snapshot.features[column] = 999.0
    monkeypatch.setattr(ui_facade, "build_factor_risk_report", lambda *a, **kw: pytest.fail("tampered descriptors reached producer"))
    panel = ui_facade.load_bound_factor_risk_panel(snapshot, "ETF0")
    assert snapshot.features.attrs["price_binding"] == binding
    assert panel["status"] == "unavailable"
    assert panel["historical_binding_status"] == "unavailable"
    assert "differ from canonical price replay" in panel["message"]
    assert panel["factor_exposures"] == []


def test_bound_factor_panel_accepts_real_snapshot_with_feature_service_binding(monkeypatch):
    from etf_cockpit import services
    from etf_cockpit.core.config import load_config
    from etf_cockpit.core.types import DataQualityReport
    from etf_cockpit.backtest.engine import BacktestReport

    fixture = _snapshot()
    config = load_config()
    # Keep storage publication private while executing the real feature service,
    # canonical feature calculation and binding construction without substitutions.
    monkeypatch.setattr(services, "current_settings_identity", lambda: {"settings_revision": "a" * 64})
    monkeypatch.setattr(services, "settings_bound_run_id", lambda run_id, **kw: run_id)
    monkeypatch.setattr(services, "ensure_run_manifest", lambda *a, **kw: None)
    monkeypatch.setattr(services, "write_features", lambda *a, **kw: None)
    features = services.FeatureService(config).compute_features(prices=fixture.prices, as_of_date=fixture.data_report.as_of_date)
    snapshot = services.CockpitSnapshot(
        config=config, prices=fixture.prices, holdings=fixture.holdings, features=features,
        latest_features=features.groupby("etf_id").tail(1),
        data_report=DataQualityReport(fixture.data_report.as_of_date, []), signals=[], forecasts=pd.DataFrame(),
        backtest=BacktestReport(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), False),
        model_status={}, model_inventory=[], universe_revision="fixture-v1",
        benchmark_reference_registry=fixture.benchmark_reference_registry,
    )
    for identity in ("ETF0", "STOCK"):
        panel = _factor_risk_panel(snapshot, identity)
        assert panel["status"] in {"available", "partial"}
        assert panel["historical_binding_status"] == "verified_snapshot"
        assert panel["specific_risk"][0]["specific_vol_ann"] > 0
        assert panel["execution_allowed"] is False

@pytest.mark.parametrize("source", ["prices", "holdings"])
def test_bound_factor_panel_rejects_future_source_knowledge_reproduction(source, monkeypatch):
    snapshot = _snapshot()
    frame = getattr(snapshot, source)
    frame["known_at"] = "2099-01-01T00:00:00+00:00"
    frame["available_at"] = "2099-01-01T00:00:00+00:00"
    if source == "holdings":
        reference = snapshot.benchmark_reference_registry.reference_portfolios[0]
        snapshot.benchmark_reference_registry = CanonicalBenchmarkRegistry(reference_portfolios=(
            replace(reference, source_hashes=(holdings_checksum(frame),), content_hash=""),
        ))
    monkeypatch.setattr(ui_facade, "build_factor_risk_report", lambda *a, **kw: pytest.fail("future knowledge reached producer"))
    panel = ui_facade.load_bound_factor_risk_panel(snapshot, "ETF0")
    assert panel["status"] == "unavailable"
    assert panel["historical_binding_status"] == "unavailable"

@pytest.mark.parametrize("source", ["prices", "holdings"])
@pytest.mark.parametrize("damage", ["missing_column", "missing_row", "naive", "malformed", "future_conflict", "before_effective"])
def test_bound_factor_panel_rejects_invalid_source_knowledge(source, damage, monkeypatch):
    snapshot = _snapshot()
    frame = getattr(snapshot, source)
    if damage == "missing_column":
        frame.drop(columns="known_at", inplace=True)
    elif damage == "missing_row":
        frame.loc[0, "known_at"] = None
    elif damage == "naive":
        frame.loc[0, "known_at"] = "2025-05-20T12:00:00"
    elif damage == "malformed":
        frame.loc[0, "known_at"] = "not-a-time"
    elif damage == "future_conflict":
        frame["available_at"] = "2099-01-01T00:00:00+00:00"
    else:
        frame["known_at"] = "2000-01-01T00:00:00+00:00"
    if source == "holdings":
        reference = snapshot.benchmark_reference_registry.reference_portfolios[0]
        snapshot.benchmark_reference_registry = CanonicalBenchmarkRegistry(reference_portfolios=(
            replace(reference, source_hashes=(holdings_checksum(frame),), content_hash=""),
        ))
    monkeypatch.setattr(ui_facade, "build_factor_risk_report", lambda *a, **kw: pytest.fail("invalid knowledge reached producer"))
    panel = ui_facade.load_bound_factor_risk_panel(snapshot, "ETF0")
    assert panel["status"] == "unavailable"
    assert panel["historical_binding_status"] == "unavailable"
    assert "knowledge" in panel["message"]


def test_bound_factor_panel_requires_reference_to_replay_latest_holdings_knowledge(monkeypatch):
    snapshot = _snapshot()
    snapshot.holdings["imported_at"] = f"{snapshot.data_report.as_of_date}T13:00:00+00:00"
    reference = snapshot.benchmark_reference_registry.reference_portfolios[0]
    snapshot.benchmark_reference_registry = CanonicalBenchmarkRegistry(reference_portfolios=(
        replace(reference, source_hashes=(holdings_checksum(snapshot.holdings),), content_hash=""),
    ))
    monkeypatch.setattr(ui_facade, "build_factor_risk_report", lambda *a, **kw: pytest.fail("mismatched reference knowledge reached producer"))
    panel = ui_facade.load_bound_factor_risk_panel(snapshot, "ETF0")
    assert panel["status"] == "unavailable"
    assert "source row maximum" in panel["message"]


def test_bound_factor_panel_exposes_valid_source_knowledge_and_reference_identity():
    snapshot = _snapshot()
    snapshot.holdings["imported_at"] = f"{snapshot.data_report.as_of_date}T13:00:00+00:00"
    reference = snapshot.benchmark_reference_registry.reference_portfolios[0]
    reference = replace(reference, source_hashes=(holdings_checksum(snapshot.holdings),), known_at=snapshot.holdings.loc[0, "imported_at"], content_hash="")
    snapshot.benchmark_reference_registry = CanonicalBenchmarkRegistry(reference_portfolios=(reference,))
    panel = ui_facade.load_bound_factor_risk_panel(snapshot, "STOCK")
    assert panel["status"] in {"available", "partial"}
    knowledge = panel["source_knowledge"]
    assert knowledge["prices"]["row_count"] == len(snapshot.prices)
    assert knowledge["prices"]["latest_known_at"] == f"{snapshot.data_report.as_of_date}T23:00:00+00:00"
    assert "values only" in knowledge["prices"]["checksum_scope"]
    assert knowledge["holdings"]["latest_known_at"] == reference.known_at
    assert knowledge["holdings"]["reference_content_hash"] == reference.content_hash
    assert knowledge["holdings"]["holdings_checksum"] == holdings_checksum(snapshot.holdings)
    assert panel["execution_allowed"] is False
