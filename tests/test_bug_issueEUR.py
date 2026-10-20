"""Issue EUR (audit #927 B-06, B-07): EUR currency basis for score price features. Fixtures only."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import etf_cockpit.application.feature_service as feature_service
from etf_cockpit.application.derived_cache import _feature_cache_binding
from etf_cockpit.application.feature_service import FeatureService
from etf_cockpit.core.config import load_config
from etf_cockpit.core.versioning import build_version_registry, ensure_run_manifest
from etf_cockpit.features.feature_pipeline import (
    CURRENCY_BASIS_EUR,
    FEATURE_ALGORITHM_VERSION,
    attach_eur_basis,
    compute_features,
    eur_basis_prices,
    robust_zscore,
    robust_zscore_by_group,
)
from etf_cockpit.signals.scoring import asset_class_labels, component_scores

KNOWN_BY = "2026-12-31T23:59:59+00:00"
DAYS = pd.bdate_range("2025-10-01", periods=140)
NOK = {"NOKX": "NOK"}


def _prices(etf_id: str, closes: np.ndarray, *, currency: str | None = "NOK") -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": DAYS[: len(closes)],
            "etf_id": etf_id,
            "adjusted_close": closes,
            "close": closes,
            "volume": 1000.0,
        }
    )
    if currency is not None:
        frame["currency"] = currency
    return frame


def _fx(rates: np.ndarray, *, pair: tuple[str, str] = ("NOK", "EUR"), ingested: str = "2025-09-01T00:00:00Z") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "as_of_date": DAYS[: len(rates)].date,
            "base_currency": pair[0],
            "quote_currency": pair[1],
            "rate": rates,
            "source": "fixture",
            "ingested_at": ingested,
        }
    )


def _moving_nok_per_eur() -> np.ndarray:
    return 0.10 * np.exp(-0.002 * np.arange(len(DAYS)))  # EUR per NOK, a falling krone


# --- B-06: EUR momentum from a flat local price --------------------------------------------------
def test_flat_nok_price_with_moving_fx_has_nonzero_eur_momentum() -> None:
    prices = _prices("NOKX", np.full(len(DAYS), 100.0))
    local = compute_features(prices).iloc[-1]
    eur = eur_basis_prices(prices, _fx(_moving_nok_per_eur()), configured_currency=NOK, known_by=KNOWN_BY)
    features = attach_eur_basis(compute_features(eur.frame), eur)
    last = features.iloc[-1]

    assert local["momentum_60d"] == pytest.approx(0.0)  # the local-currency view is blind to the krone
    assert last["momentum_60d"] == pytest.approx(-0.002 * 60)
    assert last["vol_60d_ann"] == pytest.approx(0.0, abs=1e-9)  # constant FX drift has no dispersion
    assert last["last_price"] == pytest.approx(100.0)  # display-only listing-currency price
    assert features.attrs["currency_basis"] == CURRENCY_BASIS_EUR == "EUR"
    assert features.attrs["fx_unavailable"] == {}
    assert FEATURE_ALGORITHM_VERSION == "features-3"


def test_eur_listing_is_untouched_and_needs_no_fx() -> None:
    prices = _prices("VWCE", np.linspace(100.0, 120.0, len(DAYS)), currency="EUR")
    eur = eur_basis_prices(prices, None, configured_currency={"VWCE": "EUR"}, known_by=KNOWN_BY)

    assert eur.unavailable == {}
    assert eur.binding == {"currency_basis": "EUR", "fx_snapshot_checksum": "not_required"}
    pd.testing.assert_series_equal(eur.frame["adjusted_close"], prices["adjusted_close"])


# --- fail closed: missing / stale / contradictory / unverifiable FX ------------------------------
def _stale_tail() -> pd.DataFrame:
    return _fx(_moving_nok_per_eur()[:120])  # no quote for the last 19 sessions


def _no_nok_pair() -> pd.DataFrame:
    return _fx(np.full(len(DAYS), 1.1), pair=("USD", "EUR"))


def _no_ingested_at() -> pd.DataFrame:
    return _fx(_moving_nok_per_eur()).drop(columns=["ingested_at"])


def _contradictory_reciprocal() -> pd.DataFrame:
    direct = _fx(_moving_nok_per_eur())
    inverse = _fx(np.full(len(DAYS), 9.0), pair=("EUR", "NOK"))  # 0.10 * 9.0 != 1
    return pd.concat([direct, inverse], ignore_index=True)


def _ingested_after_decision() -> pd.DataFrame:
    return _fx(_moving_nok_per_eur(), ingested="2027-01-05T00:00:00Z")


@pytest.mark.parametrize(
    "fx_builder",
    [_stale_tail, _no_nok_pair, _no_ingested_at, _contradictory_reciprocal, _ingested_after_decision],
)
def test_missing_or_unverifiable_fx_makes_features_unavailable_never_local(fx_builder) -> None:
    local_price = np.linspace(100.0, 160.0, len(DAYS))  # a local fallback would show strong momentum
    prices = _prices("NOKX", local_price)
    assert compute_features(prices).iloc[-1]["momentum_60d"] > 0.1

    eur = eur_basis_prices(prices, fx_builder(), configured_currency=NOK, known_by=KNOWN_BY)
    features = attach_eur_basis(compute_features(eur.frame), eur)
    last = features.iloc[-1]

    reason = features.attrs["fx_unavailable"]["NOKX"]
    assert reason.startswith("fx_unavailable")
    for column in ("momentum_20d", "momentum_60d", "momentum_120d", "vol_60d_ann", "drawdown_60d_max", "trend_100", "trend_slope", "drawdown_current"):
        assert pd.isna(last[column]), column
    assert eur.frame["adjusted_close"].iloc[-1] != local_price[-1]  # never the local price
    assert not (eur.frame["adjusted_close"] == prices["adjusted_close"]).any()  # and never an FX of 1


def test_short_calendar_mismatch_uses_the_latest_earlier_quote_only() -> None:
    prices = _prices("NOKX", np.full(len(DAYS), 100.0))
    rates = _fx(_moving_nok_per_eur())
    rates = rates.drop(index=[100])  # one FX holiday: the previous day's quote is read, no look-ahead
    eur = eur_basis_prices(prices, rates, configured_currency=NOK, known_by=KNOWN_BY)

    assert eur.unavailable == {}
    expected = 100.0 * _moving_nok_per_eur()[99]
    assert eur.frame["adjusted_close"].iloc[100] == pytest.approx(expected)


def test_a_missing_fx_session_blanks_drawdown_from_then_on() -> None:
    prices = _prices("NOKX", np.linspace(100.0, 130.0, len(DAYS)))
    rates = _fx(_moving_nok_per_eur())
    rates = rates[(rates["as_of_date"] < DAYS[50].date()) | (rates["as_of_date"] > DAYS[60].date())]  # 11-session hole
    eur = eur_basis_prices(prices, rates, configured_currency=NOK, known_by=KNOWN_BY)
    features = attach_eur_basis(compute_features(eur.frame), eur)

    assert "NOKX" not in features.attrs["fx_unavailable"]  # the latest session is fine
    assert features["drawdown_current"].iloc[:50].notna().all()
    assert features["drawdown_current"].iloc[55:].isna().all()  # the running peak is unknown after the hole


def test_conflicting_or_unknown_quote_currency_is_unavailable() -> None:
    conflict = eur_basis_prices(
        _prices("NOKX", np.full(60, 100.0), currency="USD"), _fx(_moving_nok_per_eur()), configured_currency=NOK, known_by=KNOWN_BY
    )
    unknown = eur_basis_prices(
        _prices("NOKX", np.full(60, 100.0), currency=None), _fx(_moving_nok_per_eur()), configured_currency={}, known_by=KNOWN_BY
    )

    assert conflict.unavailable["NOKX"].startswith("fx_unavailable")
    assert unknown.unavailable["NOKX"].startswith("fx_unavailable")
    assert conflict.frame["adjusted_close"].isna().all() and unknown.frame["adjusted_close"].isna().all()


# --- B-07: normalise within asset class ----------------------------------------------------------
_FEATURE_COLUMNS = {
    "momentum_20d": 0.02,
    "momentum_60d": 0.04,
    "momentum_120d": 0.06,
    "momentum_180d": 0.08,
    "trend_slope": 0.01,
    "trend_100": 1.0,
    "trend_200": 1.0,
    "vol_60d_ann": 0.2,
    "ewma_vol_ann": 0.2,
    "drawdown_60d_max": -0.05,
    "relative_strength_60d": 0.01,
    "relative_strength_120d": 0.01,
}


def _latest(rows: dict[str, float]) -> pd.DataFrame:
    records = []
    for etf_id, scale in rows.items():
        record = {"etf_id": etf_id, "date": pd.Timestamp("2026-04-14").date()}
        for column, value in _FEATURE_COLUMNS.items():
            record[column] = value * scale if column.startswith(("momentum", "relative", "vol", "trend_slope")) else value
        records.append(record)
    return pd.DataFrame(records)


def _allocation(ids: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"etf_id": i, "current_weight": 0.0, "target_weight": 0.0, "hard_band": 0.05, "soft_band": 0.03, "max_weight": 0.25} for i in ids]
    )


def test_zscore_is_computed_within_asset_class() -> None:
    config = load_config()
    stocks = {"UCG": 1.0, "SU": 2.0, "LR": 3.0, "PRY": 5.0}
    etfs = {"VWCE": 1.0, "LYP6": 1.5, "SPYK": 2.0}
    before = component_scores(_latest(stocks | etfs), _allocation([*stocks, *etfs]), config)
    after = component_scores(_latest(stocks | etfs | {"EXX1": 40.0}), _allocation([*stocks, *etfs, "EXX1"]), config)

    for column in ("score_momentum", "score_relative_strength", "score_risk"):
        left = before.set_index("etf_id").loc[list(stocks), column]
        right = after.set_index("etf_id").loc[list(stocks), column]
        pd.testing.assert_series_equal(left, right)  # an extra ETF never moves a stock's z
    # and the stock z equals the z of the stocks alone
    alone = component_scores(_latest(stocks), _allocation(list(stocks)), config).set_index("etf_id")
    mixed = after.set_index("etf_id")
    pd.testing.assert_series_equal(alone.loc[list(stocks), "score_momentum"], mixed.loc[list(stocks), "score_momentum"])


def test_asset_class_labels_follow_the_universe_configuration() -> None:
    labels = asset_class_labels(pd.Series(["VWCE", "UCG", "SBNOR", "RABO", "NOT_IN_CONFIG"]), load_config())

    assert labels.tolist() == ["etf", "stock", "certificate", "certificate", "unclassified"]


def test_robust_zscore_by_group_matches_per_group_robust_zscore() -> None:
    values = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0, 200.0, 300.0], index=list("abcdefg"))
    groups = pd.Series(["s", "s", "s", "s", "e", "e", "e"], index=values.index)
    result = robust_zscore_by_group(values, groups)

    pd.testing.assert_series_equal(result.loc[list("abcd")], robust_zscore(values.loc[list("abcd")]))
    pd.testing.assert_series_equal(result.loc[list("efg")], robust_zscore(values.loc[list("efg")]))
    assert not result.equals(robust_zscore(values))


# --- run identity / cache binding include the FX series ------------------------------------------
_SOURCES = {
    "configs/storage_policy.yaml": "storage_schema_version: 4\n",
    "configs/universe.yaml": "schema_version: 1\n",
    "data/validated/prices/prices_daily.parquet": "price fixture\n",
}
_SETTINGS = {
    "settings_schema_version": "1",
    "settings_version": "1.0.0",
    "settings_revision": "a" * 64,
    "settings_snapshot_id": "snapshot-a",
}


def _wire(monkeypatch, root: Path, run_ids: list[str], written: list[dict]) -> None:
    for relative, content in _SOURCES.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    registry = build_version_registry(root, code_revision="fixture")

    def manifest(run_id, dependencies, *, settings_identity, **kwargs):
        run_ids.append(run_id)
        return ensure_run_manifest(run_id, dependencies, registry=registry, root=root, settings_identity=settings_identity, **kwargs)

    monkeypatch.setattr(feature_service, "current_settings_identity", lambda: _SETTINGS)
    monkeypatch.setattr(feature_service, "ensure_run_manifest", manifest)
    monkeypatch.setattr(feature_service, "write_features", lambda _frame, **kwargs: written.append(dict(kwargs["cache_metadata"])))


def _service_prices(etf_id: str, currency: str) -> pd.DataFrame:
    return _prices(etf_id, np.full(len(DAYS), 100.0), currency=currency)


def test_fx_revision_changes_the_feature_run_hash_and_cache_binding(tmp_path, monkeypatch) -> None:
    run_ids: list[str] = []
    written: list[dict] = []
    _wire(monkeypatch, tmp_path, run_ids, written)
    prices = _service_prices("KOG", "NOK")  # KOG is a NOK listing in the universe configuration
    rates = _moving_nok_per_eur()
    revised = rates.copy()
    revised[70] *= 1.01  # a corrected FX quote inside the price window

    FeatureService(load_config(), fx_rates=_fx(rates)).compute_features(prices=prices)
    FeatureService(load_config(), fx_rates=_fx(rates)).compute_features(prices=prices)
    FeatureService(load_config(), fx_rates=_fx(revised)).compute_features(prices=prices)

    assert run_ids[0] == run_ids[1] != run_ids[2]
    assert "_x" in run_ids[0]
    assert written[0]["currency_basis"] == "EUR"
    assert written[0]["fx_snapshot_checksum"] == written[1]["fx_snapshot_checksum"] != written[2]["fx_snapshot_checksum"]
    assert len(str(written[0]["fx_snapshot_checksum"])) == 64
    assert written[0]["feature_algorithm_version"] == FEATURE_ALGORITHM_VERSION
    window = {"start_date": "2025-10-01", "end_date": "2026-04-30", "decision_time": "2026-04-30T23:59:59+00:00"}
    binding_a = FeatureService(load_config(), fx_rates=_fx(rates)).fx_binding(prices, window)
    binding_b = FeatureService(load_config(), fx_rates=_fx(revised)).fx_binding(prices, window)
    assert _feature_cache_binding(prices, calculation_window=window, fx_binding=binding_a) != _feature_cache_binding(
        prices, calculation_window=window, fx_binding=binding_b
    )


def test_eur_only_universe_keeps_its_run_identity_free_of_fx(tmp_path, monkeypatch) -> None:
    run_ids: list[str] = []
    written: list[dict] = []
    _wire(monkeypatch, tmp_path, run_ids, written)

    FeatureService(load_config(), fx_rates=pd.DataFrame()).compute_features(prices=_service_prices("VWCE", "EUR"))

    assert "_x" not in run_ids[0]
    assert written[0]["fx_snapshot_checksum"] == "not_required"
    assert written[0]["currency_basis"] == "EUR"


def test_feature_service_uses_eur_prices_and_reports_unavailable_fx(tmp_path, monkeypatch) -> None:
    run_ids: list[str] = []
    written: list[dict] = []
    _wire(monkeypatch, tmp_path, run_ids, written)
    prices = _service_prices("KOG", "NOK")

    with_fx = FeatureService(load_config(), fx_rates=_fx(_moving_nok_per_eur())).compute_features(prices=prices)
    without_fx = FeatureService(load_config(), fx_rates=pd.DataFrame()).compute_features(prices=prices)

    assert with_fx.iloc[-1]["momentum_60d"] == pytest.approx(-0.002 * 60)
    assert with_fx.attrs["currency_basis"] == "EUR"
    assert pd.isna(without_fx.iloc[-1]["momentum_60d"])
    assert without_fx.attrs["fx_unavailable"]["KOG"].startswith("fx_unavailable")


# --- sample pipeline FX / export of unavailable score components ---------------------------------
def test_sample_prices_get_synthetic_fx_but_provider_prices_use_the_canonical_store(monkeypatch) -> None:
    from etf_cockpit.data import fx_data

    sample = _prices("NOKX", np.full(30, 100.0)).assign(source="sample_generator")
    provider = sample.assign(source="yfinance")
    monkeypatch.setattr(fx_data, "load_fx_rates", lambda *_a, **_k: pd.DataFrame())

    synthetic = fx_data.fx_rates_for_prices(sample)
    assert set(synthetic["base_currency"]) == {"NOK"} and set(synthetic["quote_currency"]) == {"EUR"}
    assert set(synthetic["source"]) == {"synthetic_sample"}
    assert fx_data.fx_rates_for_prices(provider).empty  # never synthesised for real prices
    book = eur_basis_prices(sample, synthetic, configured_currency=NOK, known_by=KNOWN_BY)
    assert book.unavailable == {}


def test_export_score_6m_is_unavailable_when_a_component_is_unavailable() -> None:
    from etf_cockpit.chatgpt_bridge.export_pack import _mean_of_available_pair

    assert _mean_of_available_pair(0.2, 0.4) == pytest.approx(0.3)
    assert _mean_of_available_pair(float("nan"), 0.4) is None
    assert _mean_of_available_pair(None, 0.4) is None

def test_eur_only_universe_writes_no_fx_binding_and_reruns_over_a_pre_eur_manifest(tmp_path, monkeypatch) -> None:
    from etf_cockpit.core.versioning import price_bound_run_label, settings_bound_run_id

    run_ids: list[str] = []
    written: list[dict] = []
    bindings: list[dict] = []
    _wire(monkeypatch, tmp_path, run_ids, written)
    wired_manifest = feature_service.ensure_run_manifest

    def recording(run_id, dependencies, *, settings_identity, dataset_bindings=None, **kwargs):
        bindings.append(dict(dataset_bindings or {}))
        return wired_manifest(run_id, dependencies, settings_identity=settings_identity, dataset_bindings=dataset_bindings, **kwargs)

    monkeypatch.setattr(feature_service, "ensure_run_manifest", recording)
    prices = _service_prices("VWCE", "EUR")
    service = FeatureService(load_config(), fx_rates=pd.DataFrame())
    service.compute_features(prices=prices)

    assert set(bindings[0]) == {"dataset:prices"}  # no dataset:fx for an EUR-only universe
    # The run id is the pre-EUR formula: price-bound label only, no FX suffix.
    old_id = settings_bound_run_id(
        price_bound_run_label(run_ids[0].split("_p")[0], bindings[0]["dataset:prices"]),
        root=tmp_path,
        settings_identity=_SETTINGS,
    )
    assert run_ids[0] == old_id and "_x" not in run_ids[0]
    # A manifest written before this change (prices binding only) is reused without a conflict.
    manifest = tmp_path / "data" / "derived" / "run_manifests" / f"{run_ids[0]}.json"
    assert manifest.is_file()
    before = manifest.read_bytes()
    FeatureService(load_config(), fx_rates=pd.DataFrame()).compute_features(prices=prices)
    assert run_ids[1] == run_ids[0] and manifest.read_bytes() == before
