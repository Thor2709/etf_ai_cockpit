"""#950 Bughunt B/E: ETF score inputs and policy routing (policy fallback, stale evidence, class TER, hedge, shadow path)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.analysis.decision import etf as decision_etf
from etf_cockpit.analysis.decision import shadow_run
from etf_cockpit.analysis.decision.etf import compose_etf_decision
from etf_cockpit.core.config import load_config
from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.etf_economics import TotalReturnEvidence, calculate_etf_economics
from etf_cockpit.data.market_adjustments import apply_total_return_adjustments
from etf_cockpit.features.etf_economics import calculate_etf_liquidity
from etf_cockpit.models.ensemble import effective_ensemble_weights
from etf_cockpit.signals import canonical_scoring
from etf_cockpit.signals.canonical_scoring import (
    CanonicalComponent,
    CanonicalScoreError,
    build_canonical_score,
    canonical_score_from_signal_row,
    load_score_policy,
)
from etf_cockpit.signals.scoring import component_scores

from test_decision_etf import DECISION, EFFECTIVE, _economics_report, _evidence_record
from test_etf_economics import _corporate_action_coverage, _prices

_DECISION_DT = datetime(2026, 1, 6, tzinfo=timezone.utc)


def _context(instrument: str = "target", **extra: str):
    values = {"instrument_type": "ETF", "asset_class": "equity", "trading_currency": "USD", **extra}
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"{instrument}:{field}",
            instrument_id=instrument,
            field=field,
            value=value,
            source="#950 fixture",
            authority=SourceAuthority.OFFICIAL,
            source_id=f"fixture:{instrument}:{field}",
            confidence=0.95,
            valid_from="2020-01-01T00:00:00Z",
            available_at="2020-01-02T00:00:00Z",
        )
        for field, value in values.items()
    )
    return resolve_instrument_context(evidence, instrument_id=instrument, effective_at=EFFECTIVE, decision_time=DECISION)


def _vehicle_metrics(economics, context, *, decision: datetime = _DECISION_DT, liquidity=None, known_at=None):
    registry, _, _ = decision_etf._load_etf_registries(decision_etf._DEFAULT_REGISTRY_PATH)
    metrics = decision_etf._vehicle_scored_metrics(registry, economics, liquidity, known_at, None, {}, {}, context, decision)
    return {item.metric_id: item for item in metrics}


# --- B021-N002 ---------------------------------------------------------------------------------


def test_certificate_gets_stock_policy_and_unknown_asset_type_raises() -> None:
    stock = load_score_policy("STOCK")
    for name in ("Certificate", "certificate", "CERTIFICATE"):
        assert load_score_policy(name).groups == stock.groups
    assert stock.groups["attractiveness"].get("stock_value", 0.0) > 0.0
    assert load_score_policy("ETF").groups["attractiveness"].get("stock_value", 0.0) == 0.0
    for unknown in ("Instrument", "OTHER", "", None, "Fund"):
        with pytest.raises(CanonicalScoreError, match="no score policy"):
            load_score_policy(unknown)  # type: ignore[arg-type]
    component = CanonicalComponent("stock_value", 0.4, "attractiveness", "peers", "src", "vendor_verified", "ok", "low", "ok", "value")
    score = build_canonical_score(instrument_id="CERT", asset_type="Certificate", decision_time="2026-01-06", components=[component])
    assert any(row["key"] == "stock_value" and row["weight"] > 0 for row in score.components)
    with pytest.raises(CanonicalScoreError, match="no score policy"):
        build_canonical_score(instrument_id="X", asset_type="Instrument", decision_time="2026-01-06", components=[component])


@pytest.mark.parametrize("declared", ["certificate", "equity_certificate", "stock", "equity"])
def test_signal_rows_for_stock_like_types_never_fall_back_to_etf_policy(declared: str) -> None:
    assert canonical_scoring._signal_asset_type({"instrument_type": declared}, None, "X") == "STOCK"
    assert canonical_scoring._signal_asset_type({"instrument_type": "etf"}, None, "X") == "ETF"
    assert canonical_scoring._signal_asset_type({}, None, "X") == "ETF"
    assert canonical_scoring._signal_asset_type({"asset_type": "mystery"}, None, "X") == "mystery"


# --- B012-N001 / B012-N003 -----------------------------------------------------------------------


def _quote(timestamp: pd.Timestamp, **extra: object) -> pd.DataFrame:
    return pd.DataFrame([{"instrument_id": "VWCE", "quote_timestamp": timestamp, "bid": 100.0, "ask": 100.1, "nav": 100.0, **extra}])


def test_stale_quote_cannot_set_spread_premium_or_cost() -> None:
    config, prices = load_config(), _prices()
    latest = prices["date"].max()
    fresh = calculate_etf_liquidity(config, prices, "VWCE", quote_evidence=_quote(latest + pd.Timedelta(hours=20)), as_of=latest)
    stale = calculate_etf_liquidity(config, prices, "VWCE", quote_evidence=_quote(latest - pd.Timedelta(days=3)), as_of=latest)
    assert fresh.quote_status == "available" and fresh.spread_source == "quoted_bid_ask"
    assert stale.stale_quote is True and stale.quote_freshness == "stale"
    assert stale.quote_status == "unavailable"
    assert stale.quoted_spread_bps is None and stale.premium_discount_bps is None
    assert stale.bid_eur is None and stale.ask_eur is None and stale.nav_eur is None
    assert stale.spread_source != "quoted_bid_ask"
    assert "quote_stale" in stale.missing_evidence

    # A liquidity report whose spread/cost came from a stale quote is not score evidence either.
    context = _context()
    liquidity = {"as_of": EFFECTIVE, "source_id": "liq", "estimated_cost_bps": 5.0, "spread_proxy_bps": 4.0, "stale_quote": True, "spread_source": "quoted_bid_ask"}
    metrics = _vehicle_metrics(None, context, liquidity=liquidity, known_at=DECISION)
    assert "estimated_trading_cost" not in metrics and "spread_proxy_bps" not in metrics
    metrics = _vehicle_metrics(None, context, liquidity={**liquidity, "stale_quote": False}, known_at=DECISION)
    assert "estimated_trading_cost" in metrics


def test_stale_ter_and_tracking_evidence_is_not_score_eligible(tmp_path: Path) -> None:
    economics = _economics_report(tmp_path)
    context = _context()
    current = _vehicle_metrics(economics, context)
    assert {"ter", "tracking_difference_abs", "tracking_error"} <= set(current)
    later = datetime(2027, 6, 1, tzinfo=timezone.utc)
    assert _vehicle_metrics(economics, context, decision=later).keys().isdisjoint({"ter", "tracking_difference_abs", "tracking_error"})
    assert decision_etf._ter_record(economics, later, context) is None
    assert decision_etf._tracking_record(economics, later) is None
    assert decision_etf._ter_record(economics, _DECISION_DT, context) is not None


# --- B012-N002 -----------------------------------------------------------------------------------


def test_index_forecast_horizon_must_match_tracking_difference_horizon(tmp_path: Path) -> None:
    economics = _economics_report(tmp_path)  # horizon_days=3
    liquidity = {"as_of": EFFECTIVE, "source_id": "liq", "estimated_cost_bps": 10.0}

    def expected(**extra: object):
        assessment = compose_etf_decision(
            "target", _context(), DECISION, etf_economics=economics, liquidity_report=liquidity, liquidity_known_at=DECISION,
            expected_index_return=_evidence_record(0.12, "index", **extra),
        )
        return {item.metric_id: item for item in assessment.drivers}

    assert expected(horizon_days=3)["expected_etf_return"].status == "AVAILABLE"
    for extra in ({}, {"horizon_days": 30}):
        drivers = expected(**extra)
        assert "expected_etf_return" not in drivers or drivers["expected_etf_return"].status != "AVAILABLE"


# --- B012-N004 -----------------------------------------------------------------------------------


def _series(dates: list[str], values: list[float], instrument_id: str) -> TotalReturnEvidence:
    index = pd.DatetimeIndex(dates)
    adjustment = apply_total_return_adjustments(
        pd.DataFrame({"date": index, "close": values, "instrument_id": instrument_id, "currency": "EUR", "source_id": "t", "provenance": "unit-test"})
    )
    return TotalReturnEvidence.from_adjustment_result(
        adjustment, instrument_id=instrument_id, currency="EUR", known_at=str(index[-1]), as_of=str(index[-1]), source_id="t",
        provenance="unit-test", corporate_action_coverage=_corporate_action_coverage(instrument_id, index[-1], index[-1]),
    )


def _fund_record(**extra: object) -> dict[str, object]:
    return {
        "instrument_id": "VWCE", "scope": "fund", "as_of": "2026-01-04", "known_at": "2026-01-04", "currency": "EUR",
        "benchmark_id": "BM", "benchmark_currency": "EUR", "ter": 0.0022, "fee_unit": "decimal_fraction",
        "source_id": "fund", "source_provenance": "unit-test", "source_checksum": "b" * 64, **extra,
    }


def test_exchange_holiday_does_not_make_tracking_unavailable() -> None:
    # 2026-01-01 is an Euronext holiday: no observation that day is not a gap in the evidence.
    dates = ["2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05"]
    kwargs = dict(
        fund_total_return=_series(dates, [100.0, 101.0, 102.0, 104.0], "VWCE"),
        benchmark_total_return=_series(dates, [100.0, 100.5, 101.0, 103.0], "BM"),
        as_of="2026-01-05", horizon_days=3,
    )
    with_calendar = calculate_etf_economics("VWCE", [_fund_record()], session_calendar="XAMS", **kwargs)
    assert with_calendar.tracking_status == "available"
    assert with_calendar.tracking_difference == round(104 / 100 - 103 / 100, 10)
    assert "business_daily_coverage" not in with_calendar.missing_evidence
    # Without a certified calendar the window is still weekday-only and fails closed.
    weekday_only = calculate_etf_economics("VWCE", [_fund_record()], **kwargs)
    assert weekday_only.tracking_status == "unavailable" and "business_daily_coverage" in weekday_only.missing_evidence
    # A missing real session (2026-01-02 is open on XAMS) is still a gap.
    gap_dates = ["2025-12-29", "2025-12-30", "2025-12-31", "2026-01-05"]
    gap = calculate_etf_economics(
        "VWCE", [_fund_record()], session_calendar="XAMS", as_of="2026-01-05", horizon_days=3,
        fund_total_return=_series(gap_dates, [100.0, 101.0, 102.0, 104.0], "VWCE"),
        benchmark_total_return=_series(gap_dates, [100.0, 100.5, 101.0, 103.0], "BM"),
    )
    assert gap.tracking_status == "unavailable"


# --- B014-N001 / B014-N002 -----------------------------------------------------------------------


def test_class_ter_replaces_fund_ter_and_ambiguous_classes_are_unavailable(tmp_path: Path) -> None:
    def classes(*items: tuple[str, str, float]):
        return [
            _fund_record(instrument_id="target", benchmark_id="BM"),
            *[
                _fund_record(instrument_id="target", scope="share_class", share_class_id=name, currency=currency, ter=ter)
                for name, currency, ter in items
            ],
        ]

    economics = calculate_etf_economics("target", classes(("target", "EUR", 0.0035)), as_of=DECISION)
    assert economics.fund_metrics["ter"] == 0.0022
    assert _vehicle_metrics(economics, _context())["ter"].raw_value == 0.0035  # class id == instrument id
    # Selected by share-class currency when the class id is not the instrument id.
    economics = calculate_etf_economics("target", classes(("A-EUR", "EUR", 0.0035), ("A-GBP", "GBP", 0.0010)), as_of=DECISION)
    assert _vehicle_metrics(economics, _context(share_class_currency="EUR"))["ter"].raw_value == 0.0035
    # Differing class fees and no way to pick the class: no TER rather than the fund TER.
    assert "ter" not in _vehicle_metrics(economics, _context())
    # No class records: the fund TER stands.
    fund_only = calculate_etf_economics("target", [_fund_record(instrument_id="target")], as_of=DECISION)
    assert _vehicle_metrics(fund_only, _context())["ter"].raw_value == 0.0022


def test_currency_mismatch_is_graded_and_hedge_aware() -> None:
    look_through = {
        "holdings_date": "2026-01-05", "lineage": {"known_at": DECISION},
        "exposures": {"currency": {"USD": 0.7, "EUR": 0.3}},
    }
    registry, _, _ = decision_etf._load_etf_registries(decision_etf._DEFAULT_REGISTRY_PATH)
    definitions = {item.metric_id: item for item in registry.metrics}

    def mismatch(context) -> float | None:
        evidence: dict = {}
        decision_etf._add_currency_metric(evidence, definitions, look_through, context)
        return evidence["currency_mismatch"].raw_value if "currency_mismatch" in evidence else None

    assert mismatch(_context(trading_currency="USD")) == pytest.approx(0.3)  # graded, not a 0/1 cliff
    assert mismatch(_context(trading_currency="EUR")) == pytest.approx(0.7)
    assert mismatch(_context(trading_currency="EUR", hedging_currency="EUR")) == 0.0  # hedged class not penalised
    assert mismatch(_context(trading_currency="EUR", hedging_currency="GBP")) == 1.0
    partial = {**look_through, "exposures": {"currency": {"USD": 0.5}}}
    evidence: dict = {}
    decision_etf._add_currency_metric(evidence, definitions, partial, _context())
    assert evidence == {}


# --- B112-N001 / B112-N002 / B012-N002 ----------------------------------------------------------


def test_shadow_path_produces_tracking_metrics_and_expected_etf_return(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from test_decision_etf import _total_return_series

    monkeypatch.setattr(shadow_run, "_look_through", lambda *args, **kwargs: None)
    record = {
        "instrument_id": "target", "scope": "fund", "as_of": "2026-01-04", "known_at": "2026-01-04", "currency": "USD",
        "benchmark_id": "benchmark", "benchmark_currency": "USD", "ter": 0.0022, "fee_unit": "decimal_fraction",
        "source_id": "fund-economics:target", "source_provenance": "fixture", "source_checksum": "b" * 64,
    }
    fund = {"target": _total_return_series(tmp_path, [100.0, 102.0, 104.0, 106.0], instrument_id="target")}
    benchmark = {"benchmark": _total_return_series(tmp_path, [100.0, 101.0, 102.0, 103.0], instrument_id="benchmark")}
    liquidity = {"as_of": EFFECTIVE, "source_id": "liq", "model_id": "t", "estimated_cost_bps": 10.0}
    context = _context()

    bare = shadow_run._prepare_etf_candidate("target", context, pd.Timestamp(DECISION), (record,), None, liquidity_report=liquidity, liquidity_known_at=DECISION)
    assert bare["economics"].tracking_status == "unavailable"  # no typed returns -> no tracking (the old shadow behaviour)

    prepared = shadow_run._prepare_etf_candidate(
        "target", context, pd.Timestamp(DECISION), (record,), None, liquidity_report=liquidity, liquidity_known_at=DECISION,
        fund_total_return=fund, benchmark_total_return=benchmark, tracking_horizon_days=3,
        expected_index_return=_evidence_record(0.12, "index", horizon_days=3),
    )
    assert prepared["economics"].tracking_status == "available"
    assert {"tracking_difference_abs", "tracking_error"} <= {item.metric_id for item in prepared["vehicle_metrics"]}
    row = shadow_run._compose_etf_candidate(prepared, pd.Timestamp(DECISION), (), (), {}, minimum_support=3)
    drivers = {item.metric_id: item for item in row["assessment"].drivers}
    assert drivers["expected_etf_return"].status == "AVAILABLE"
    assert drivers["expected_etf_return"].raw_value == pytest.approx(0.12 + prepared["economics"].tracking_difference - 0.001)
    assert drivers["expected_etf_return_method"].reason_code == "INDEX_PLUS_TD_MINUS_TRADING_COSTS"


def test_shadow_universe_loads_typed_total_returns_and_passes_forecast_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel_fund = SimpleNamespace(instrument_id="target")
    sentinel_benchmark = SimpleNamespace(instrument_id="benchmark")
    seen: dict[str, object] = {}
    config = SimpleNamespace(universe=SimpleNamespace(etfs=(SimpleNamespace(id="target", instrument_type="etf", exchange="XETRA"),), enabled_ids=("target",)))
    monkeypatch.setattr(shadow_run, "read_instrument_context", lambda *a, **k: SimpleNamespace(instrument_type="ETF"))
    monkeypatch.setattr(shadow_run, "load_etf_economics_records", lambda: ())
    monkeypatch.setattr(
        shadow_run, "load_total_return_evidence",
        lambda path, **k: sentinel_fund if path == shadow_run.ETF_FUND_TOTAL_RETURN_PATH else sentinel_benchmark,
    )
    monkeypatch.setattr(shadow_run, "_prepare_etf_candidate", lambda *a, **k: seen.update(k) or {"instrument": "target", "asset_type": "ETF", "peer_id": "unavailable"})
    monkeypatch.setattr(shadow_run, "_compose_etf_candidate", lambda prepared, *a: prepared)
    index = _evidence_record(0.1, "index", horizon_days=252)
    shadow_run._compose_universe(
        config, (), datetime.now(timezone.utc), latest_features=None,
        expected_index_returns={"target": index}, structural_drags={"target": _evidence_record(0.001, "drag")},
    )
    assert seen["fund_total_return"] == {"target": sentinel_fund}
    assert seen["benchmark_total_return"] == {"benchmark": sentinel_benchmark}
    assert seen["expected_index_return"] is index
    assert seen["structural_drag"]["source"] == "drag"
    assert seen["session_calendar"] == "XETR"


def test_compose_etf_candidate_forwards_expected_return_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    assessment = SimpleNamespace(domain_slots=(), exposure_domain_slots=(), opportunity_slots=(), critical_domains=(), source_vintage_hash="h")
    monkeypatch.setattr(shadow_run, "compose_etf_decision", lambda *a, **k: captured.update(k) or assessment)
    prepared = {"instrument": "t", "context": object(), "economics": None, "look_through": None, "asset_type": "ETF",
                "expected_index_return": {"value": 1}, "structural_drag": {"value": 2}}
    shadow_run._compose_etf_candidate(prepared, pd.Timestamp(DECISION), (), (), {}, minimum_support=3)
    assert captured["expected_index_return"] == {"value": 1} and captured["structural_drag"] == {"value": 2}


# --- B112-N003 -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identity",
    [{"instrument_id": "VWCE", "etf_id": "OTHER"}, {"instrument_id": "OTHER", "etf_id": "VWCE"}, {"instrument_id": "VWCE", "display_id": "OTHER"}],
)
def test_conflicting_quote_identity_columns_are_rejected(identity: dict[str, str]) -> None:
    config, prices = load_config(), _prices()
    latest = prices["date"].max()
    quote = _quote(latest + pd.Timedelta(hours=20)).drop(columns="instrument_id")
    for key, value in identity.items():
        quote[key] = value
    report = calculate_etf_liquidity(config, prices, "VWCE", quote_evidence=quote, as_of=latest)
    assert report.quote_status == "unavailable" and report.quoted_spread_bps is None
    assert "quote_identity" in report.missing_evidence
    agreeing = quote.assign(**{key: "VWCE" for key in identity})
    assert calculate_etf_liquidity(config, prices, "VWCE", quote_evidence=agreeing, as_of=latest).quote_status == "available"


# --- B024-N002 -----------------------------------------------------------------------------------


def test_sparse_promoted_forecast_leaves_other_etfs_scores_and_confidence_finite() -> None:
    features = pd.DataFrame([
        {"etf_id": etf_id, "momentum_20d": 0.01, "momentum_60d": 0.02, "momentum_120d": 0.03 * scale, "momentum_180d": 0.04,
         "trend_slope": 0.01 * scale, "trend_100": 1.0, "trend_200": 1.0, "vol_60d_ann": 0.2, "ewma_vol_ann": 0.2,
         "drawdown_60d_max": -0.05, "relative_strength_60d": 0.02 * scale}
        for etf_id, scale in (("AAA", 1.0), ("BBB", 2.0), ("CCC", 3.0))
    ])
    allocation = pd.DataFrame([
        {"etf_id": etf_id, "current_weight": 0.0, "target_weight": 0.0, "hard_band": 0.05, "soft_band": 0.03, "max_weight": 0.25}
        for etf_id in ("AAA", "BBB", "CCC")
    ])
    config = load_config()
    scored = component_scores(
        features, allocation, config, toto_available=True, timesfm_available=True,
        forecast_scores={"toto": {"AAA": 0.5}, "timesfm": {"AAA": 0.4}, "baseline": {"AAA": 0.1, "BBB": 0.2, "CCC": 0.3}},
    )
    assert scored["total_score"].notna().all() and scored["confidence"].notna().all()
    weights = effective_ensemble_weights(config.models.ensemble["weights"], toto_available=True, timesfm_available=True)
    for _, row in scored.iterrows():
        row = row.copy()
        row["price_freshness"] = "ok"
        canonical = canonical_score_from_signal_row(row, config, "2026-01-06", toto_available=True, timesfm_available=True)
        assert canonical.legacy_composite_raw is not None and pd.notna(canonical.legacy_composite_raw)
        assert canonical.evidence_confidence_10 is not None and pd.notna(canonical.evidence_confidence_10)
        assert canonical.attractiveness_10 is not None and canonical.expected_return_10 is not None
    assert weights["toto"] > 0  # the global weight stays configured; per-instrument renormalisation handles sparsity
