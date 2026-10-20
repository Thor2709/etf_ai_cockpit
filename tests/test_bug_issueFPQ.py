"""FPQ: financials route, ETF product quality vs exposure, KID cost, liquidity order/ADV (audit #927 NEW-5) + V8 intake."""

from __future__ import annotations

import math
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.analysis.stock_universe import SECTOR_ROUTE_MISSING, is_non_bank_financial_sector
from etf_cockpit.application.ui_views import stock_research as stock_research_view
from etf_cockpit.data import stock_research as stock_research_data
from etf_cockpit.features import etf_economics
from etf_cockpit.parsers.priips_kid import PriipsKidRecord
from etf_cockpit.signals import simple_scores as ss
from etf_cockpit.signals.canonical_scoring import headline_evidence_weights

DECISION = date(2025, 1, 10)
PEERS_PCT = (0.10, 0.30, 0.60)


def _part(score: float | None) -> SimpleNamespace:
    return SimpleNamespace(
        score_10=score,
        why="generic industrial ratios",
        source_id="yfinance:fundamentals",
        as_of="2025-01-09",
        freshness="ok",
        band_low=None,
        band_high=None,
        used=(),
        inputs=(),
    )


def _evidence(value: float | None = 8.0, quality: float | None = 8.0) -> SimpleNamespace:
    return SimpleNamespace(
        components={"stock_value": _part(value), "stock_quality": _part(quality), "analyst_revision": _part(6.0)},
        metrics={},
    )


def _kid(cost: str | None, *, sri: int | None = 4) -> PriipsKidRecord:
    return PriipsKidRecord(
        product="Example ETF",
        isin="IE000Q4J3CW6",
        manufacturer="Vanguard",
        sri=sri,
        cost_fields={} if cost is None else {"ongoing_costs": f"{cost} of the value of your investment p.a."},
        holding_period_years=5,
        scenarios=("moderate",),
        document_date="2025-01-06",
        extraction_confidence="high",
        warnings=(),
        source_sha256="a" * 64,
        source_pages=(1, 2),
        manual_review=False,
        score_eligible=True,
    )


# --- F-02: non-bank financials -------------------------------------------------------------------------------------


@pytest.mark.parametrize("sector", ["Financials", "Insurance", "Financial exchanges", "Financial Services"])
def test_non_bank_financials_quality_and_value_are_unavailable_with_sector_route_missing(sector: str) -> None:
    components = {c.key: c for c in ss._stock_fundamental_components(_evidence(), None, sector=sector)}

    for key in ("stock_quality", "stock_value"):
        assert components[key].score_10 is None
        assert components[key].status == "N/A"
        assert SECTOR_ROUTE_MISSING in components[key].why
        assert not components[key].score_eligible
    assert components["analyst_revision"].score_10 == 6.0  # sector-neutral evidence is untouched


def test_industrial_and_bank_sectors_keep_their_routes() -> None:
    industrial = {c.key: c for c in ss._stock_fundamental_components(_evidence(), None, sector="Industrials")}
    assert industrial["stock_quality"].score_10 == 8.0 and industrial["stock_value"].score_10 == 8.0
    assert is_non_bank_financial_sector("Financials") and not is_non_bank_financial_sector("Banks")
    assert not is_non_bank_financial_sector("Savings banks") and not is_non_bank_financial_sector(None)


def test_non_bank_financial_candidate_row_has_no_generic_fundamentals() -> None:
    candidate = pd.DataFrame(
        [
            {
                "instrument_id": "BRK_B",
                "name": "Berkshire",
                "instrument_type": "stock",
                "sector": "Financials",
                "latest_date": "2025-01-09",
                "latest_price": 100.0,
                "rows": 300,
                "value_score_10": 9.0,
                "quality_score_10": 9.0,
            }
        ]
    )
    scores = ss.build_candidate_simple_scores(candidate, None, decision_date=DECISION)
    by_key = {c.key: c for c in scores[0].components}
    assert by_key["stock_value"].score_10 is None and SECTOR_ROUTE_MISSING in by_key["stock_value"].why
    assert by_key["stock_quality"].score_10 is None and SECTOR_ROUTE_MISSING in by_key["stock_quality"].why


def test_certificate_without_fundamentals_never_gets_stock_fundamental_weights() -> None:
    price = ss._component("momentum", 0.4, "m")
    unavailable = [ss._optional_score_component(k, None, "none", authority="medium") for k in ("stock_value", "stock_quality")]
    revision = ss._optional_score_component("analyst_revision", 7.0, "rev", authority="low")

    certificate = ss._headline_weights_for_components("STOCK", "Certificate", [price, *unavailable, revision])
    stock = ss._headline_weights_for_components("STOCK", "Stock", [price, *unavailable, revision])

    assert certificate["stock_value"] == certificate["stock_quality"] == certificate["analyst_revision"] == 0.0
    assert stock["analyst_revision"] > 0.0  # a normal stock is unchanged
    assert stock == headline_evidence_weights("STOCK")


# --- G-02: KID cost ------------------------------------------------------------------------------------------------


def test_kid_cost_scores_lower_cost_better_within_peers_and_sri_is_not_risk() -> None:
    cheap = ss.build_priips_kid_cost_evidence(_kid("0.2%"), as_of_date=DECISION, peer_costs_pct=(0.05, 0.5, 0.8))
    dear = ss.build_priips_kid_cost_evidence(_kid("0.5%"), as_of_date=DECISION, peer_costs_pct=(0.05, 0.5, 0.8))

    assert cheap.score_10 is not None and dear.score_10 is not None
    assert cheap.score_10 > dear.score_10
    assert cheap.key == dear.key == "etf_product_quality"

    sri_only = ss.build_priips_kid_cost_evidence(_kid(None, sri=3), as_of_date=DECISION, peer_costs_pct=PEERS_PCT)
    assert sri_only.key != "risk" and sri_only.score_10 is None and "never mapped" in sri_only.why


def test_kid_cost_without_a_peer_tier_is_unavailable_not_absolute() -> None:
    alone = ss.build_priips_kid_cost_evidence(_kid("0.2%"), as_of_date=DECISION)
    one_peer = ss.build_priips_kid_cost_evidence(_kid("0.2%"), as_of_date=DECISION, peer_costs_pct=(0.3,))

    assert alone.score_10 is None and one_peer.score_10 is None
    assert "peer" in alone.why


# --- G-01 / G-03: ETF product quality vs exposure -------------------------------------------------------------------


def _inputs(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {"ter": 0.0020, "as_of_date": "2025-01-02", "source_id": "issuer_document:etf_product_quality"}
    values.update(changes)
    return values


PEER_TER = {"ter": [0.0010, 0.0030, 0.0060]}


def test_etf_with_missing_ter_has_unavailable_product_quality_not_neutral() -> None:
    component = ss._etf_product_quality_component(_inputs(ter=None), PEER_TER, DECISION)

    assert component.key == "etf_product_quality"
    assert component.score_10 is None and component.raw_score is None and component.status == "N/A"
    assert not component.score_eligible
    assert "never assumed" in component.why
    assert ss._etf_product_quality_component(None, PEER_TER, DECISION).score_10 is None


def test_product_quality_is_scored_within_peers_and_cheaper_is_better() -> None:
    cheap = ss._etf_product_quality_component(_inputs(ter=0.0005), PEER_TER, DECISION)
    dear = ss._etf_product_quality_component(_inputs(ter=0.0070), PEER_TER, DECISION)

    assert cheap.score_10 == 10.0 and dear.score_10 == 1.0
    assert cheap.score_eligible and cheap.score_role == "product_quality" and cheap.freshness_status == "ok"
    thin = ss._etf_product_quality_component(_inputs(), {"ter": [0.0010]}, DECISION)
    assert thin.score_10 is None and "peers" in thin.why


def test_product_quality_adds_tracking_premium_and_structure_and_names_what_is_missing() -> None:
    peers = {**PEER_TER, "tracking_difference": [0.001, 0.003], "premium_discount_bps": [5.0, 20.0]}
    full = ss._etf_product_quality_component(
        _inputs(ter=0.0005, tracking_difference=-0.0004, premium_discount_bps=-2.0, structure="Physical (full replication)"),
        peers,
        DECISION,
    )
    cost_only = ss._etf_product_quality_component(_inputs(ter=0.0005), peers, DECISION)

    assert full.score_10 == 9.9  # cost/tracking/premium rank 10, physical full replication 9 (weights .50/.25/.15/.10)
    assert "tracking difference" in full.why and "premium/discount" in full.why and "structure" in full.why
    assert "tracking difference not scored (missing)" in cost_only.why


def test_product_quality_needs_a_dated_non_future_vintage() -> None:
    assert ss._etf_product_quality_component(_inputs(as_of_date=None), PEER_TER, DECISION).score_10 is None
    future = ss._etf_product_quality_component(_inputs(as_of_date="2025-02-01"), PEER_TER, DECISION)
    assert not future.score_eligible
    stale = ss._etf_product_quality_component(_inputs(as_of_date="2020-01-01"), PEER_TER, DECISION)
    assert stale.freshness_status == "stale" and not stale.score_eligible


def test_product_quality_uses_a_scorable_kid_cost_when_ter_is_missing() -> None:
    component = ss._etf_product_quality_component(
        _inputs(ter=None, kid_record=_kid("0.05%")), {"ter": [0.0010, 0.0030, 0.0060]}, DECISION
    )

    assert component.score_10 == 10.0 and component.source_id == "priips_kid:" + "a" * 64


def test_product_quality_carries_no_headline_weight_and_concentration_stays_a_risk_term() -> None:
    weights = headline_evidence_weights("ETF")

    assert weights.get("etf_product_quality", 0.0) == 0.0
    assert ss._score_engine_section("etf_product_quality")["headline_weight"] == 0.0
    assert weights["etf_exposure"] > 0.0  # unchanged v3 weight
    assert "risk term" in ss.COMPONENT_LABELS["etf_exposure"]
    assert "not exposure attractiveness" in ss.COMPONENT_EXPLANATIONS["etf_exposure"]
    # a zero-weight, differently-roled component cannot move the headline or the evidence-quality completeness
    base = [ss._component("momentum", 0.5, "m"), ss._component("trend", 0.5, "t")]
    product = ss._etf_product_quality_component(_inputs(ter=0.0005), PEER_TER, DECISION)
    assert ss.combine_component_scores([*base, product], weights) == ss.combine_component_scores(base, weights)


def test_product_quality_peer_group_is_the_same_exposure_theme() -> None:
    def identity(name: str, theme: str, ter: float | None) -> SimpleNamespace:
        return SimpleNamespace(id=name, theme=theme, ter=ter, isin=None, asset_class="equity", instrument_type="etf", model_extra={})

    members = {item.id: item for item in (identity("A", "World", 0.002), identity("B", "World", 0.004), identity("C", "World", 0.001), identity("D", "Gold", 0.0009), identity("E", "", 0.0001))}
    config = SimpleNamespace(universe=SimpleNamespace(by_id=lambda: members))

    inputs, peers = ss._etf_product_quality_lookup(config)

    assert sorted(peers["A"]["ter"]) == [0.001, 0.004]  # World peers only: never Gold, never the blank theme
    assert peers["D"]["ter"] == [] and peers["E"]["ter"] == []
    assert inputs["A"]["ter"] == 0.002


# --- G-04: liquidity -------------------------------------------------------------------------------------------------


def test_liquidity_scores_order_size_over_adv_with_a_configured_default() -> None:
    small, why = ss._liquidity_raw_and_reason(1_000_000.0, None, order_size_eur=1_000.0)
    default, _ = ss._liquidity_raw_and_reason(1_000_000.0, None)
    large, _ = ss._liquidity_raw_and_reason(1_000_000.0, None, order_size_eur=500_000.0)

    assert small > default > large
    assert "order/ADV" in why and "ADV" in why
    assert ss._liquidity_policy()["order_size"] == 10_000.0
    # the former absolute bands are reproduced at the default order size
    assert ss.raw_to_score_10(ss._liquidity_raw_and_reason(10_000_000.0, None)[0]) == 9.5
    assert ss.raw_to_score_10(ss._liquidity_raw_and_reason(24_000.0, None)[0]) == 2.0


def test_high_low_range_is_labelled_as_a_range_proxy_not_a_spread() -> None:
    _raw, why = ss._liquidity_raw_and_reason(5_000_000.0, 0.01)

    assert "range_proxy_bps" in why and "volatility proxy" in why and "spread proxy" not in why


def test_corwin_schultz_is_used_where_ohlc_exists_and_is_below_the_range() -> None:
    closes = [100.0 + (i % 3) for i in range(21)]
    high = pd.Series([c * 1.010 for c in closes])
    low = pd.Series([c * 0.990 for c in closes])
    estimate = ss._corwin_schultz_spread(high, low, min_pairs=5)

    assert estimate is not None and 0.0 <= estimate < 0.02  # the 2% range overstates the spread
    assert ss._corwin_schultz_spread(high.head(4), low.head(4), min_pairs=5) is None
    inverted = ss._corwin_schultz_spread(low, high, min_pairs=1)
    assert inverted is None  # inverted high/low rows are skipped, never guessed
    _raw, why = ss._liquidity_raw_and_reason(5_000_000.0, 0.02, corwin_schultz=estimate)
    assert "Corwin-Schultz" in why and "range_proxy_bps" not in why

    prices = pd.DataFrame(
        {
            "etf_id": "X",
            "date": pd.date_range("2024-12-01", periods=21, freq="B"),
            "close": closes,
            "high": high.to_numpy(),
            "low": low.to_numpy(),
            "volume": 10_000.0,
            "currency": "EUR",
        }
    )
    info = ss._price_liquidity_lookup(prices, currency_by_id={"X": "EUR"})["X"]
    assert info["corwin_schultz_20"] is not None and info["spread_proxy_20"] > info["corwin_schultz_20"]


# --- V8 intake ---------------------------------------------------------------------------------------------------


def test_v8_n002_quote_known_after_the_cutoff_is_not_used() -> None:
    quotes = pd.DataFrame(
        [
            {"instrument_id": "ETF1", "quote_timestamp": "2025-01-09T10:00:00Z", "known_at": "2025-01-09T10:05:00Z", "bid": 99.0},
            {"instrument_id": "ETF1", "quote_timestamp": "2025-01-10T10:00:00Z", "known_at": "2025-01-12T09:00:00Z", "bid": 101.0},
            {"instrument_id": "ETF1", "quote_timestamp": "2025-01-10T11:00:00Z", "known_at": "not-a-date", "bid": 102.0},
        ]
    )
    cutoff = pd.Timestamp("2025-01-10T23:59:59Z")

    scoped = etf_economics._scope_quote(quotes, "ETF1", cutoff)

    assert list(scoped["bid"]) == [99.0]


def test_v8_n001_provenance_known_after_the_decision_cutoff_is_not_complete() -> None:
    item = {"source_id": "s", "effective_at": "2024-12-31", "known_at": "2025-03-01T00:00:00+00:00"}
    cutoff = pd.Timestamp("2025-01-10", tz="UTC")

    assert stock_research_data._source_triplets_complete([item])  # shape alone is complete
    assert not stock_research_data._source_triplets_complete([item], cutoff=cutoff)
    assert stock_research_data._source_triplets_complete([{**item, "known_at": "2025-01-01T00:00:00+00:00"}], cutoff=cutoff)
    result = stock_research_data._margin_of_safety(100.0, 80.0, [item], [{**item, "known_at": "2025-01-01T00:00:00+00:00"}], model="dcf", cutoff=cutoff)
    assert result["status"] == "unavailable" and "model_source_timing_unavailable" in result["reason_codes"]


def test_v8_e_c2_s09_n001_forecast_quantiles_are_log_returns_and_use_exp() -> None:
    # REJECTED on the base: the fan already applies exp(q); this guards it.
    dates = pd.date_range("2025-01-01", periods=5, freq="B")
    prices = pd.DataFrame({"date": dates, "adjusted_close": [100.0] * 5})
    forecasts = pd.DataFrame(
        [
            {
                "etf_id": "X",
                "model_name": "m",
                "forecast_date": dates[-1],
                "horizon_days": 5,
                "q10_return": -0.5,
                "q25_return": -0.2,
                "q50_return": 0.0,
                "q75_return": 0.2,
                "q90_return": 0.7,
                "status": "ok",
            }
        ]
    )

    lines, _stale = stock_research_view._forecast_lines(forecasts, "X", dates[0], prices)

    assert lines[0].q10[0] == pytest.approx(100.0 * math.exp(-0.5))
    assert lines[0].q90[0] == pytest.approx(100.0 * math.exp(0.7))
    assert lines[0].q90[0] != pytest.approx(100.0 * (1.0 + 0.7))
