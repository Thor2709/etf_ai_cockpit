from types import SimpleNamespace

from etf_cockpit.application.feature_service import RELATIVE_STRENGTH_FALLBACK_ANCHOR, relative_strength_anchor


def test_canonical_benchmark_wins_when_its_prices_exist():
    context = SimpleNamespace(benchmark_data_id="IWDA")
    assert relative_strength_anchor(context, {"IWDA", "VWCE", "X"}) == "IWDA"


def test_falls_back_to_broad_market_tracker_without_canonical_evidence():
    assert RELATIVE_STRENGTH_FALLBACK_ANCHOR == "VWCE"
    assert relative_strength_anchor(SimpleNamespace(benchmark_data_id=None), {"VWCE", "X"}) == "VWCE"
    assert relative_strength_anchor(None, {"VWCE"}) == "VWCE"


def test_no_anchor_prices_means_relative_strength_stays_unavailable():
    assert relative_strength_anchor(SimpleNamespace(benchmark_data_id="IWDA"), {"X", "Y"}) is None
