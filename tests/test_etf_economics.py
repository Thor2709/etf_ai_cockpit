from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import pytest

from etf_cockpit.app.pages.instrument_detail import _render_evidence_section, instrument_detail_page
from etf_cockpit.app.selectors.instrument_detail import build_etf_economics_panel, build_instrument_detail
from etf_cockpit.app.state import AppState
from etf_cockpit.core.config import load_config
from etf_cockpit.data.etf_economics import (
    ClosureProxyPolicy,
    EtfEconomicsError,
    EtfEconomicsReport,
    EtfEconomicsStore,
    TotalReturnEvidence,
    calculate_etf_economics,
    load_closure_proxy_policy,
    load_etf_economics_records,
    load_total_return_evidence,
)
from etf_cockpit.data.market_adjustments import (
    AdjustmentResult,
    CorporateAction,
    CorporateActionCoverage,
    CorporateActionCoverageStore,
    apply_total_return_adjustments,
)
from etf_cockpit.features.etf_economics import calculate_etf_liquidity
import etf_cockpit.services as services
from etf_cockpit.services import build_snapshot


def _trusted_artifact_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prices(rows: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2026-04-01", periods=rows, freq="B")
    close = pd.Series(range(100, 100 + rows), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "etf_id": "VWCE",
            "open": close - 0.25,
            "high": close + 0.50,
            "low": close - 0.50,
            "close": close,
            "adjusted_close": close,
            "volume": 10_000.0,
            "currency": "EUR",
        }
    )


def test_etf_capacity_is_order_size_and_horizon_specific_and_cost_stress_widens() -> None:
    config = load_config()
    one_day = calculate_etf_liquidity(config, _prices(), "VWCE", order_value_eur=10_000, horizon_days=1)
    five_day = calculate_etf_liquidity(config, _prices(), "VWCE", order_value_eur=50_000, horizon_days=5, stress_multiplier=1.5)

    assert one_day.status == "available"
    assert one_day.exchange_capacity_eur == one_day.rolling_turnover_eur_20d * config.costs.cost_model.max_participation_rate
    assert one_day.capacity_status == "within_configured_participation"
    assert five_day.horizon_days == 5
    assert five_day.order_to_daily_turnover > one_day.order_to_daily_turnover
    assert five_day.exchange_capacity_eur > one_day.exchange_capacity_eur
    assert five_day.stressed_cost_bps >= five_day.estimated_cost_bps
    assert five_day.execution_allowed is False


def test_etf_quote_panel_flags_stale_off_hours_and_calculates_premium_discount() -> None:
    config = load_config()
    prices = _prices()
    latest = prices["date"].max()
    report = calculate_etf_liquidity(
        config,
        prices,
        "VWCE",
        quote_evidence=pd.DataFrame(
            [
                {
                    "instrument_id": "VWCE",
                    "quote_timestamp": latest - pd.Timedelta(days=2),
                    "session": "after_hours",
                    "bid": 100.0,
                    "ask": 102.0,
                    "nav": 100.0,
                    "underlying_adv_eur": 2_000_000.0,
                    "primary_market_capacity_eur": 5_000_000.0,
                    "source_id": "import:quote-test",
                }
            ]
        ),
        as_of=latest,
    )

    assert report.quote_status == "available"
    assert report.stale_quote is True
    assert report.off_hours_quote is True
    assert report.quote_freshness == "stale"
    assert report.premium_discount_bps == 100.0
    assert report.underlying_liquidity_eur == 2_000_000.0
    assert report.primary_market_capacity_eur == 5_000_000.0
    assert report.primary_market_status == "available"
    assert report.source_id == "import:quote-test"


def test_missing_quote_and_primary_market_evidence_remain_explicit() -> None:
    report = calculate_etf_liquidity(load_config(), _prices(), "VWCE")

    assert report.quote_status == "unavailable"
    assert report.bid_eur is None
    assert report.ask_eur is None
    assert report.nav_eur is None
    assert {"bid_ask", "nav", "quote_timestamp"} <= set(report.missing_evidence)
    assert report.spread_source == "high_low_proxy"
    assert report.primary_market_capacity_eur is None
    assert report.primary_market_status == "unavailable_not_exchange_volume"


def test_instrument_detail_exposes_etf_liquidity_and_order_preview() -> None:
    snapshot = build_snapshot()
    snapshot = replace(
        snapshot,
        etf_economics_records=(),
        etf_fund_total_return=None,
        etf_benchmark_total_return=None,
        etf_closure_policy=None,
    )
    missing_panel = build_etf_economics_panel(snapshot, snapshot.config.ui.default_etf)
    assert missing_panel["status"] == "unavailable"
    assert {"fund_economics", "closure_policy"} <= set(missing_panel["missing_evidence"])
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    control = instrument_detail_page(None, state)

    def text_values(node: object) -> list[str]:
        values = []
        value = getattr(node, "value", None)
        if value is not None:
            values.append(str(value))
        for child in getattr(node, "controls", []) or []:
            values.extend(text_values(child))
        content = getattr(node, "content", None)
        if content is not None:
            values.extend(text_values(content))
        return values

    rendered = "\n".join(text_values(control))
    assert "ETF Liquidity" in rendered
    assert "ETF order-preview capacity meter" in rendered
    assert "ETF Economics" in rendered
    assert "fund_economics" in rendered
    assert "execution_allowed=false" in rendered


def _economics_records() -> list[dict[str, object]]:
    return [
        {
            "instrument_id": "VWCE",
            "scope": "fund",
            "as_of": "2026-01-04",
            "known_at": "2026-01-04",
            "currency": "EUR",
            "benchmark_id": "FTSE-ALL-WORLD",
            "benchmark_name": "FTSE All-World",
            "benchmark_currency": "EUR",
            "ter": 0.0022,
            "ocf": 0.0022,
            "fee_unit": "decimal_fraction",
            "aum": 100_000_000.0,
            "aum_unit": "currency_units",
            "flows": -500_000.0,
            "flows_unit": "currency_units",
            "flow_period_days": 30,
            "inception_date": "2020-01-01",
            "share_class_structure": "accumulating",
            "document_id": "kid-2026",
            "source_id": "fund-economics-test",
            "source_provenance": "unit-test",
            "source_checksum": "b" * 64,
        },
        {
            "instrument_id": "VWCE",
            "scope": "share_class",
            "share_class_id": "VWCE-EUR-ACC",
            "as_of": "2026-01-04",
            "known_at": "2026-01-04",
            "currency": "EUR",
            "benchmark_id": "FTSE-ALL-WORLD",
            "benchmark_currency": "EUR",
            "ter": 0.0022,
            "ocf": 0.0022,
            "fee_unit": "decimal_fraction",
        },
        {
            "instrument_id": "VWCE",
            "scope": "share_class",
            "share_class_id": "VWCE-GBP-HDG",
            "as_of": "2026-01-04",
            "known_at": "2026-01-04",
            "currency": "GBP",
            "benchmark_id": "FTSE-ALL-WORLD",
            "benchmark_currency": "EUR",
            "ter": 0.0035,
            "ocf": 0.0038,
            "fee_unit": "decimal_fraction",
        },
    ]


def _closure_policy() -> ClosureProxyPolicy:
    return ClosureProxyPolicy(
        "closure-v1",
        "EUR",
        "currency_units",
        100_000_000,
        30,
        1_000_000,
        5,
        "policy-test",
        "unit-test",
        "sha256:closure-policy-test",
        "2020-01-01",
        "2099-12-31",
        "2020-01-01",
    )


def _total_return_series(values: list[float], *, instrument_id: str = "VWCE", currency: str = "EUR", start: str = "2026-01-01") -> TotalReturnEvidence:
    dates = pd.bdate_range(start, periods=len(values))
    adjustment = apply_total_return_adjustments(
        pd.DataFrame(
            {
                "date": dates,
                "close": values,
                "instrument_id": instrument_id,
                "currency": currency,
                "source_id": "test",
                "provenance": "unit-test",
            }
        )
    )
    return TotalReturnEvidence.from_adjustment_result(
        adjustment,
        instrument_id=instrument_id,
        currency=currency,
        known_at=str(dates[-1]),
        as_of=str(dates[-1]),
        source_id="test",
        provenance="unit-test",
        corporate_action_coverage=_corporate_action_coverage(instrument_id, dates[-1], dates[-1]),
    )


def _corporate_action_coverage(
    instrument_id: str,
    coverage_through: object,
    known_at: object,
    *,
    status: str = "active",
) -> CorporateActionCoverage:
    coverage = CorporateActionCoverage(
        instrument_id=instrument_id,
        coverage_through=str(coverage_through),
        published_at=str(coverage_through),
        retrieved_at=str(coverage_through),
        known_at=str(known_at),
        revision=1,
        source="unit-test",
        source_id="coverage-test",
        source_checksum="c" * 64,
        status=status,
    )
    with TemporaryDirectory() as directory, CorporateActionCoverageStore(Path(directory)) as store:
        return store.append(coverage)


def _replace_evidence(evidence: TotalReturnEvidence, frame: pd.DataFrame, **changes: object) -> TotalReturnEvidence:
    raw = pd.DataFrame(
        {
            "date": frame["date"],
            "close": frame["total_return_index"],
            "instrument_id": evidence.instrument_id,
            "currency": evidence.currency,
            "source_id": evidence.source_id,
            "provenance": evidence.provenance,
        }
    )
    if "known_at" in frame:
        raw["known_at"] = frame["known_at"]
    artifact = apply_total_return_adjustments(raw, convention=evidence.total_return_convention)
    values = {
        "known_at": evidence.known_at,
        "as_of": evidence.as_of,
        **changes,
    }
    coverage_through = max(
        pd.to_datetime(frame["date"], utc=True, format="mixed").max(),
        pd.to_datetime(values["as_of"], utc=True),
    )
    existing_coverage = evidence._binding.corporate_action_coverage
    coverage = (
        existing_coverage
        if pd.Timestamp(existing_coverage.coverage_through) >= coverage_through
        else _corporate_action_coverage(evidence.instrument_id, coverage_through, values["known_at"])
    )
    return TotalReturnEvidence.from_adjustment_result(
        artifact,
        instrument_id=evidence.instrument_id,
        currency=evidence.currency,
        source_id=evidence.source_id,
        provenance=evidence.provenance,
        corporate_action_coverage=coverage,
        **values,
    )


def test_realised_tracking_reconciles_matched_series_and_states_identity_currency_horizon_coverage() -> None:
    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=_total_return_series([100.0, 101.0, 102.0, 104.0]),
        benchmark_total_return=_total_return_series([100.0, 100.5, 101.0, 103.0], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-06",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )

    assert report.status == "available"
    assert report.tracking_status == "available"
    assert report.tracking_difference == round(104 / 100 - 103 / 100, 10)
    assert report.benchmark_id == "FTSE-ALL-WORLD"
    assert report.currency == "EUR"
    assert report.benchmark_currency == "EUR"
    assert report.horizon_days == 3
    assert report.coverage == "4/4 business_daily observations"
    assert report.coverage_ratio == 1.0
    assert report.execution_allowed is False


def test_realised_tracking_scopes_longer_histories_to_requested_trailing_horizon() -> None:
    fund_values = [float(value) for value in range(100, 110)]
    benchmark_values = [100.0 + 0.5 * value for value in range(10)]
    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=_total_return_series(fund_values),
        benchmark_total_return=_total_return_series(benchmark_values, instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-14",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )

    expected_difference = fund_values[-1] / fund_values[-4] - benchmark_values[-1] / benchmark_values[-4]
    assert report.status == "available"
    assert report.tracking_status == "available"
    assert report.tracking_difference == round(expected_difference, 10)
    assert report.matched_rows == 4
    assert report.coverage == "4/4 business_daily observations"
    assert report.coverage_ratio == 1.0
    assert EtfEconomicsReport.__dataclass_fields__["execution_allowed"].init is False


def test_share_class_metrics_are_isolated_from_fund_metrics() -> None:
    report = calculate_etf_economics("VWCE", _economics_records())

    assert report.fund_metrics["ter"] == 0.0022
    assert report.share_class_metrics["VWCE-EUR-ACC"]["ter"] == 0.0022
    assert report.share_class_metrics["VWCE-GBP-HDG"]["ter"] == 0.0035
    assert report.share_class_metrics["VWCE-GBP-HDG"]["ocf"] == 0.0038


def test_fee_history_replays_by_as_of_and_exposes_fee_change() -> None:
    records = _economics_records() + [
        {
            **_economics_records()[0],
            "as_of": "2026-01-02",
            "known_at": "2026-01-02",
            "ter": 0.0025,
            "ocf": 0.0025,
            "fee_unit": "decimal_fraction",
            "document_id": "kid-2025",
        }
    ]
    store = EtfEconomicsStore(records)
    replay = store.as_of("VWCE", "2026-01-03")
    replay_fund = next(item for item in replay if item.scope == "fund")
    assert replay_fund.ter == 0.0025
    assert len(store.history("VWCE", decision_time="2026-01-03")) == 1

    report = calculate_etf_economics("VWCE", records, as_of="2026-01-04")
    assert report.fund_metrics["ter"] == 0.0022
    assert any(change["from_ter"] == 0.0025 and change["to_ter"] == 0.0022 for change in report.fee_changes)
    assert {item["document_id"] for item in report.fee_history} >= {"kid-2025", "kid-2026"}


def test_missing_benchmark_blocks_tracking_without_inventing_identity() -> None:
    records = [{**_economics_records()[0], "benchmark_id": None, "benchmark_currency": None}]
    report = calculate_etf_economics(
        "VWCE",
        records,
        fund_total_return=_total_return_series([100.0, 101.0]),
        benchmark_total_return=_total_return_series([100.0, 100.5], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-02",
    )

    assert report.tracking_difference is None
    assert report.tracking_status == "unavailable"
    assert "benchmark_identity" in report.missing_evidence
    assert report.benchmark_id is None


def test_tracking_blocks_insufficient_matched_coverage() -> None:
    benchmark = _total_return_series([100.0, 100.5, 103.0], instrument_id="FTSE-ALL-WORLD")
    benchmark_frame = benchmark.frame.copy()
    benchmark_frame["date"] = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-06"])
    benchmark = _replace_evidence(benchmark, benchmark_frame, as_of="2026-01-06", known_at="2026-01-06")
    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=_total_return_series([100.0, 101.0, 102.0, 104.0]),
        benchmark_total_return=benchmark,
        as_of="2026-01-06",
        horizon_days=3,
    )

    assert report.tracking_difference is None
    assert report.tracking_status == "unavailable"
    assert report.coverage == "3/4 business_daily observations"
    assert "matched_total_return" in report.missing_evidence


def test_missing_aum_and_flows_remain_null_and_closure_is_explicit_proxy() -> None:
    record = {key: value for key, value in _economics_records()[0].items() if key not in {"aum", "flows"}}
    report = calculate_etf_economics("VWCE", [record], as_of="2026-01-04")

    assert report.fund_metrics["aum"] is None
    assert report.fund_metrics["flows"] is None
    assert report.closure_risk_proxy["label"] == "proxy/model; not an observed fact or probability"
    assert report.closure_risk_proxy["status"] == "unavailable"


def test_untyped_numeric_frames_cannot_be_authoritative_tracking_evidence() -> None:
    report = calculate_etf_economics(
        "VWCE", _economics_records(), fund_total_return=pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=4), "total_return_index": [100, 101, 102, 104]}),
        benchmark_total_return=pd.DataFrame({"date": pd.bdate_range("2026-01-01", periods=4), "total_return_index": [100, 100.5, 101, 103]}), as_of="2026-01-06", horizon_days=3,
    )
    assert report.tracking_status == "unavailable"
    assert "untyped" in report.message


def test_identity_currency_and_benchmark_override_cannot_relabel_evidence() -> None:
    report = calculate_etf_economics(
        "VWCE", _economics_records(), fund_total_return=_total_return_series([100, 101, 102, 104]), benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="OTHER"), as_of="2026-01-06", horizon_days=3,
        benchmark_id="OTHER",
    )
    assert report.tracking_status == "unavailable"
    assert report.benchmark_id == "FTSE-ALL-WORLD"


def test_latest_known_revision_is_selected_and_future_or_missing_known_at_fails_closed() -> None:
    corrected = {**_economics_records()[0], "as_of": "2026-01-04", "known_at": "2026-01-05", "ter": 0.003, "revision_id": "r2"}
    report = calculate_etf_economics("VWCE", _economics_records() + [corrected], as_of="2026-01-06")
    assert report.fund_metrics["ter"] == 0.003
    assert calculate_etf_economics("VWCE", [{key: value for key, value in _economics_records()[0].items() if key != "known_at"}], as_of="2026-01-06").status == "unavailable"
    assert calculate_etf_economics("VWCE", [{**_economics_records()[0], "known_at": "2026-01-07"}], as_of="2026-01-06").status == "unavailable"


def test_percent_fee_unit_normalises_and_same_effective_date_correction_is_not_fee_change() -> None:
    records = [{**_economics_records()[0], "ter": 0.22, "ocf": 0.22, "fee_unit": "percent", "revision_id": "r1"}, {**_economics_records()[0], "ter": 0.21, "ocf": 0.21, "fee_unit": "percent", "known_at": "2026-01-05", "revision_id": "r2"}]
    report = calculate_etf_economics("VWCE", records, as_of="2026-01-06")
    assert report.fund_metrics["ter"] == 0.0021
    assert report.fee_changes == ()
    assert calculate_etf_economics("VWCE", [{**_economics_records()[0], "fee_unit": "pct"}], as_of="2026-01-06").status == "unavailable"


def test_closure_proxy_requires_versioned_policy_and_currency_base_match() -> None:
    policy = _closure_policy()
    report = calculate_etf_economics("VWCE", _economics_records(), as_of="2026-01-06", closure_policy=policy)
    assert report.closure_risk_proxy["status"] == "available"
    assert report.closure_risk_proxy["factor_coverage"]["ratio"] == 1.0
    eur_policy = replace(_closure_policy(), base_currency="JPY")
    assert calculate_etf_economics("VWCE", _economics_records(), as_of="2026-01-06", closure_policy=eur_policy).closure_risk_proxy["status"] == "unavailable"


def test_adjustment_result_factory_binds_canonical_total_return_contract() -> None:
    trusted = _total_return_series([100.0, 101.0, 102.0, 104.0])
    adjustment = trusted._binding.artifact
    evidence = TotalReturnEvidence.from_adjustment_result(
        adjustment, instrument_id="VWCE", currency="EUR", known_at="2026-01-06", as_of="2026-01-06", source_id="test", provenance="unit-test",
        corporate_action_coverage=trusted._binding.corporate_action_coverage,
    )
    report = calculate_etf_economics("VWCE", _economics_records(), fund_total_return=evidence, benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"), as_of="2026-01-06", horizon_days=3)
    assert adjustment.action_reconciliation == ()
    assert report.tracking_status == "available"
    assert evidence.as_dict()["corporate_action_coverage"]["source_checksum"] == "c" * 64
    assert evidence.as_dict()["execution_allowed"] is False


def test_nan_and_pd_na_optional_economics_values_remain_none() -> None:
    record = {**_economics_records()[0], "aum": float("nan"), "flows": pd.NA}
    report = calculate_etf_economics("VWCE", [record], as_of="2026-01-06")
    assert report.fund_metrics["aum"] is None
    assert report.fund_metrics["flows"] is None
    assert "'AUM': NAN" not in str(report.as_dict()).upper()
    assert "'FLOWS': NAN" not in str(report.as_dict()).upper()


def test_irregular_and_monthly_series_are_unavailable() -> None:
    irregular = _total_return_series([100, 101, 102, 104], instrument_id="FTSE-ALL-WORLD")
    irregular_frame = irregular.frame.copy()
    irregular_frame["date"] = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-07"])
    irregular = _replace_evidence(irregular, irregular_frame, as_of="2026-01-07", known_at="2026-01-07")
    report = calculate_etf_economics("VWCE", _economics_records(), fund_total_return=_total_return_series([100, 101, 102, 104]), benchmark_total_return=irregular, as_of="2026-01-07", horizon_days=3)
    assert report.tracking_status == "unavailable"
    monthly_frame = _total_return_series([100, 101, 102, 104], instrument_id="FTSE-ALL-WORLD").frame.copy()
    monthly_frame["date"] = pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-02", "2026-04-01"])
    monthly = _replace_evidence(irregular, monthly_frame, as_of="2026-04-01", known_at="2026-04-01")
    assert calculate_etf_economics("VWCE", _economics_records(), fund_total_return=_total_return_series([100, 101, 102, 104]), benchmark_total_return=monthly, as_of="2026-04-01", horizon_days=3).tracking_status == "unavailable"


def test_local_loaders_fail_closed_for_malformed_files_and_read_typed_csv(tmp_path) -> None:
    economics_path = tmp_path / "economics.csv"
    pd.DataFrame(_economics_records()).to_csv(economics_path, index=False)
    assert load_etf_economics_records(economics_path) == ()
    trusted_economics_sha = _trusted_artifact_digest(economics_path)
    assert len(
        load_etf_economics_records(
            economics_path, trusted_sha256=trusted_economics_sha
        )
    ) == 3
    economics_path.write_text(economics_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert load_etf_economics_records(economics_path, trusted_sha256=trusted_economics_sha) == ()
    evidence_path = tmp_path / "returns.csv"
    evidence = _total_return_series([100, 101, 102, 104])
    payload = evidence.frame.assign(
        total_return_convention=evidence.total_return_convention, status=evidence.status, reconciliation_status=evidence.reconciliation_status,
        source_id=evidence.source_id, provenance=evidence.provenance, known_at=evidence.known_at, as_of=evidence.as_of, frequency=evidence.frequency,
    )
    payload["checksum"] = TotalReturnEvidence.checksum_for_frame(payload)
    payload.to_csv(evidence_path, index=False)
    assert load_total_return_evidence(
        evidence_path, trusted_sha256=_trusted_artifact_digest(evidence_path)
    ) is None
    malformed = tmp_path / "bad.csv"
    pd.DataFrame({"date": ["2026-01-01"], "total_return_index": [100]}).to_csv(malformed, index=False)
    assert load_total_return_evidence(malformed) is None


def test_total_return_row_revisions_select_latest_eligible_and_exclude_future() -> None:
    fund = _total_return_series([100, 101, 102, 104])
    frame = fund.frame.assign(
        known_at=["2026-01-01T12:00:00Z", "2026-01-02T12:00:00Z", "2026-01-05T12:00:00Z", "2026-01-06T00:00:00Z"]
    )
    corrections = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-01-06"), pd.Timestamp("2026-01-06")],
            "total_return_index": [105.0, 150.0],
            "instrument_id": ["VWCE", "VWCE"],
            "currency": ["EUR", "EUR"],
            "total_return_convention": ["reinvest_on_ex_date", "reinvest_on_ex_date"],
            "known_at": ["2026-01-06T12:00:00Z", "2026-01-07T00:00:00Z"],
        }
    )
    revised_frame = pd.concat([frame, corrections], ignore_index=True)
    revised = _replace_evidence(fund, revised_frame, known_at="2026-01-07T00:00:00Z")
    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=revised,
        benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-06T18:00:00Z",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )
    assert report.status == "available"
    assert report.tracking_difference == round(105 / 100 - 103 / 100, 10)

    conflicting = pd.concat([revised.frame, corrections.iloc[[0]].assign(total_return_index=106.0)], ignore_index=True)
    conflict_report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=_replace_evidence(revised, conflicting),
        benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-06T18:00:00Z",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )
    assert conflict_report.status == "unavailable"
    assert "conflicting fund total-return revisions" in conflict_report.message

    missing_known_at = revised.frame.copy()
    missing_known_at.loc[0, "known_at"] = pd.NA
    missing_report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=_replace_evidence(revised, missing_known_at),
        benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-06T18:00:00Z",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )
    assert missing_report.status == "unavailable"
    assert "missing known_at" in missing_report.message


def test_closure_policy_loader_accepts_local_json_and_fails_closed(tmp_path) -> None:
    policy_path = tmp_path / "closure.json"
    policy_path.write_text(
        json.dumps(
            {
                "version": "closure-v1",
                "base_currency": "EUR",
                "amount_unit": "currency_units",
                "aum_threshold": 100_000_000,
                "flow_period_days": 30,
                "flow_threshold": 1_000_000,
                "young_age_years": 5,
                "source_id": "policy-test",
                "source_provenance": "unit-test",
                "source_checksum": "sha256:closure-policy-test",
                "effective_from": "2020-01-01",
                "effective_until": "2099-12-31",
                "known_at": "2020-01-01",
            }
        ),
        encoding="utf-8",
    )
    assert load_closure_proxy_policy(policy_path) is None
    assert load_closure_proxy_policy(
        policy_path, trusted_sha256=_trusted_artifact_digest(policy_path)
    ) == _closure_policy()
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")
    assert load_closure_proxy_policy(malformed) is None


def test_build_snapshot_loader_outputs_reach_available_instrument_economics(monkeypatch) -> None:
    dates = pd.bdate_range("2020-01-01", periods=253)
    effective = str(dates[-1])
    records = [{**record, "as_of": effective, "known_at": effective} for record in _economics_records()]
    fund = _total_return_series([100.0 + index * 0.1 for index in range(253)], start="2020-01-01")
    benchmark = _total_return_series(
        [100.0 + index * 0.08 for index in range(253)], instrument_id="FTSE-ALL-WORLD", start="2020-01-01"
    )
    monkeypatch.setattr(services, "load_etf_economics_records", lambda: EtfEconomicsStore(records).records)
    monkeypatch.setattr(
        services,
        "load_total_return_evidence",
        lambda path: fund if path == services.ETF_FUND_TOTAL_RETURN_PATH else benchmark,
    )
    monkeypatch.setattr(services, "load_closure_proxy_policy", _closure_policy)

    snapshot = services.build_snapshot()
    model = build_instrument_detail(
        snapshot,
        "VWCE",
        economics_as_of=effective,
        economics_horizon_days=252,
    )
    panel = model.sections["etf_economics"]
    assert panel["status"] == "available"
    assert panel["tracking_status"] == "available"
    assert panel["closure_risk_proxy"]["status"] == "available"
    assert panel["execution_allowed"] is False


def test_required_closure_policy_absence_makes_complete_economics_partial() -> None:
    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=_total_return_series([100, 101, 102, 104]),
        benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-06",
        horizon_days=3,
    )
    assert report.tracking_status == "available"
    assert report.closure_risk_proxy["status"] == "unavailable"
    assert report.status == "partial"
    assert "closure_policy" in report.missing_evidence


def test_total_return_envelope_blocks_future_rows_and_report_lookahead() -> None:
    evidence = _total_return_series([100, 101, 102, 104])
    with pytest.raises(EtfEconomicsError, match="extends beyond its as_of envelope"):
        _replace_evidence(evidence, evidence.frame.copy(deep=True), as_of="2026-01-02")


def test_total_return_checksum_and_convention_are_verified() -> None:
    evidence = _total_return_series([100, 101, 102, 104])
    with pytest.raises(EtfEconomicsError, match="checksum mismatch"):
        replace(evidence, checksum="sha256:stale")
    with pytest.raises(EtfEconomicsError, match="not canonical"):
        replace(evidence, total_return_convention="price_only")


def test_post_construction_total_return_mutation_fails_closed() -> None:
    evidence = _total_return_series([100, 101, 102, 104])
    evidence.frame.loc[3, "total_return_index"] = 200.0
    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=evidence,
        benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-06",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )
    assert report.status == "unavailable"
    assert "checksum mismatch at consumption" in report.message


def test_aum_and_flow_amount_units_are_explicit() -> None:
    ambiguous = {key: value for key, value in _economics_records()[0].items() if key != "aum_unit"}
    report = calculate_etf_economics("VWCE", [ambiguous], as_of="2026-01-06", closure_policy=_closure_policy())
    assert report.status == "unavailable"
    assert "aum requires explicit aum_unit=currency_units" in report.message
    assert _closure_policy().amount_unit == "currency_units"


def test_non_finite_total_return_values_fail_closed() -> None:
    evidence = _total_return_series([100, 101, 102, 104])
    frame = evidence.frame.astype({"total_return_index": float}).copy()
    frame.loc[2, "total_return_index"] = float("inf")
    bad = _replace_evidence(evidence, frame)
    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=bad,
        benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-06",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )
    assert report.status == "unavailable"
    assert "invalid observations" in report.message


def test_etf_economics_ui_renders_scalar_tracking_coverage() -> None:
    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=_total_return_series([100, 101, 102, 104]),
        benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-06",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )
    control = _render_evidence_section("ETF Economics", report.as_dict())

    def values(node: object) -> list[str]:
        result = [str(value)] if (value := getattr(node, "value", None)) is not None else []
        for child in getattr(node, "controls", ()) or ():
            result.extend(values(child))
        content = getattr(node, "content", None)
        if content is not None:
            result.extend(values(content))
        return result

    rendered = "\n".join(values(control))
    assert "coverage: 4/4 business_daily observations" in rendered
    assert "policy-test" in rendered
    assert report.closure_risk_proxy["policy_assumptions"]["aum_threshold"] == 100_000_000


def test_rehashed_mutable_payload_is_not_a_trusted_total_return_artifact() -> None:
    evidence = _total_return_series([100, 101, 102, 104])
    mutated = evidence.frame.copy(deep=True)
    mutated.loc[3, "total_return_index"] = 999.0
    forged = replace(evidence, frame=mutated, checksum=TotalReturnEvidence.checksum_for_frame(mutated))

    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=forged,
        benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-06",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )

    assert report.status == "unavailable"
    assert "bound canonical artifact" in report.message


def test_adjustment_result_without_corporate_action_coverage_is_rejected() -> None:
    dates = pd.bdate_range("2026-01-01", periods=4)
    adjustment = apply_total_return_adjustments(pd.DataFrame({"date": dates, "close": [100.0, 101.0, 102.0, 104.0]}))

    with pytest.raises(EtfEconomicsError, match="trusted CorporateActionCoverage"):
        TotalReturnEvidence.from_adjustment_result(
            adjustment,
            instrument_id="VWCE",
            currency="EUR",
            known_at="2026-01-06",
            as_of="2026-01-06",
            source_id="test",
            provenance="unit-test",
        )


@pytest.mark.parametrize(
    ("coverage", "message"),
    [
        (_corporate_action_coverage("OTHER", "2026-01-06", "2026-01-06"), "instrument mismatch"),
        (_corporate_action_coverage("VWCE", "2026-01-05", "2026-01-05"), "does not cover"),
        (_corporate_action_coverage("VWCE", "2026-01-06", "2026-01-07"), "known after"),
        (
            _corporate_action_coverage("VWCE", "2026-01-06", "2026-01-06", status="superseded"),
            "must be active",
        ),
    ],
)
def test_invalid_corporate_action_coverage_is_rejected(
    coverage: CorporateActionCoverage,
    message: str,
) -> None:
    trusted = _total_return_series([100, 101, 102, 104])

    with pytest.raises(EtfEconomicsError, match=message):
        TotalReturnEvidence.from_adjustment_result(
            trusted._binding.artifact,
            instrument_id="VWCE",
            currency="EUR",
            known_at="2026-01-06",
            as_of="2026-01-06",
            source_id="test",
            provenance="unit-test",
            corporate_action_coverage=coverage,
        )


def test_mutated_corporate_action_coverage_fails_at_consumption() -> None:
    fund = _total_return_series([100, 101, 102, 104])
    object.__setattr__(fund._binding.corporate_action_coverage, "source_checksum", "d" * 64)

    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=fund,
        benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-06",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )

    assert report.status == "unavailable"
    assert "corporate-action coverage changed after binding" in report.message


def test_total_return_source_provenance_is_required() -> None:
    trusted = _total_return_series([100, 101, 102, 104])
    artifact = trusted._binding.artifact

    with pytest.raises(EtfEconomicsError, match="total-return source_id is required"):
        TotalReturnEvidence.from_adjustment_result(
            artifact,
            instrument_id="VWCE",
            currency="EUR",
            known_at="2026-01-06",
            as_of="2026-01-06",
            source_id="",
            provenance="unit-test",
            corporate_action_coverage=trusted._binding.corporate_action_coverage,
        )


def test_row_known_at_before_observation_date_fails_closed() -> None:
    evidence = _total_return_series([100, 101, 102, 104])
    frame = evidence.frame.copy(deep=True)
    frame["known_at"] = "2025-12-31T23:59:59Z"
    bad = _replace_evidence(evidence, frame)

    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=bad,
        benchmark_total_return=_total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"),
        as_of="2026-01-06",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )

    assert report.status == "unavailable"
    assert "row known_at cannot precede observation date" in report.message


def test_historical_closure_policy_interval_and_knowledge_guard() -> None:
    policy = replace(
        _closure_policy(),
        effective_from="2026-01-07",
        effective_until="2026-12-31",
        known_at="2026-01-07",
    )
    report = calculate_etf_economics("VWCE", _economics_records(), as_of="2026-01-06", closure_policy=policy)

    assert report.closure_risk_proxy["status"] == "unavailable"
    assert "not applicable" in report.closure_risk_proxy["reason"]


def test_report_preserves_total_return_lineage_and_tracking_units() -> None:
    fund = _total_return_series([100, 101, 102, 104])
    benchmark = _total_return_series([100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD")
    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=fund,
        benchmark_total_return=benchmark,
        as_of="2026-01-06",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )

    assert report.tracking_unit == "decimal_fraction"
    assert report.fund_source_id == fund.source_id
    assert report.fund_source_provenance == fund.provenance
    assert report.fund_source_checksum == fund.checksum
    assert report.fund_total_return_convention == fund.total_return_convention
    assert report.fund_total_return_known_at == fund.known_at
    assert report.fund_total_return_as_of == fund.as_of
    assert report.benchmark_source_id == benchmark.source_id
    assert report.benchmark_source_provenance == benchmark.provenance
    assert report.benchmark_source_checksum == benchmark.checksum
    assert report.benchmark_total_return_convention == benchmark.total_return_convention
    assert report.benchmark_total_return_known_at == benchmark.known_at
    assert report.benchmark_total_return_as_of == benchmark.as_of


def test_closure_availability_requires_all_factors_and_fund_fee_unit() -> None:
    record = {key: value for key, value in _economics_records()[0].items() if key != "flows"}
    report = calculate_etf_economics("VWCE", [record], as_of="2026-01-06", closure_policy=_closure_policy())

    assert report.closure_risk_proxy["status"] == "unavailable"
    assert report.closure_risk_proxy["factor_coverage"]["ratio"] < 1.0
    assert report.fund_metrics["fee_unit"] == "decimal_fraction"


def test_available_economics_requires_fund_record_provenance() -> None:
    record = {key: value for key, value in _economics_records()[0].items() if key not in {"source_id", "source_checksum"}}
    report = calculate_etf_economics("VWCE", [record], as_of="2026-01-06")

    assert report.status == "partial"
    assert "fund_economics_provenance" in report.missing_evidence


def test_public_adjustment_result_wrapper_cannot_claim_canonical_derivation() -> None:
    trusted = _total_return_series([100, 101, 102, 104])
    forged = AdjustmentResult(
        "available",
        trusted.frame.assign(total_return_index=[100.0, 250.0, 25.0, 999.0]),
        trusted.total_return_convention,
        (),
    )

    with pytest.raises(EtfEconomicsError, match="authoritative total-return evidence"):
        TotalReturnEvidence.from_adjustment_result(
            forged,
            instrument_id="VWCE",
            currency="EUR",
            known_at="2026-01-06",
            as_of="2026-01-06",
            source_id="test",
            provenance="unit-test",
            corporate_action_coverage=trusted._binding.corporate_action_coverage,
        )


def test_economically_material_action_mutation_invalidates_bound_result() -> None:
    dates = pd.bdate_range("2026-01-01", periods=4)
    action = CorporateAction(
        action_id="DIV-001",
        instrument_id="VWCE",
        action_type="dividend",
        announced_at="2026-01-01",
        effective_at="2026-01-05",
        ex_date="2026-01-05",
        payable_at="2026-01-06",
        known_at="2026-01-01",
        revision=1,
        source="unit-test",
        source_id="action-test",
        source_checksum="a" * 64,
        amount=1.0,
        currency="EUR",
    )
    raw = pd.DataFrame(
        {
            "date": dates,
            "close": [100.0, 101.0, 102.0, 104.0],
            "instrument_id": "VWCE",
            "currency": "EUR",
            "source_id": "test",
            "provenance": "unit-test",
        }
    )
    artifact = apply_total_return_adjustments(raw, actions=(action,))
    evidence = TotalReturnEvidence.from_adjustment_result(
        artifact,
        instrument_id="VWCE",
        currency="EUR",
        known_at="2026-01-06",
        as_of="2026-01-06",
        source_id="test",
        provenance="unit-test",
        corporate_action_coverage=_corporate_action_coverage("VWCE", "2026-01-06", "2026-01-06"),
    )
    object.__setattr__(artifact.action_reconciliation[0].observations[0], "amount", 500.0)

    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=evidence,
        benchmark_total_return=_total_return_series(
            [100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"
        ),
        as_of="2026-01-06",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )

    assert report.status == "unavailable"
    assert "canonical AdjustmentResult artifact changed" in report.message


@pytest.mark.parametrize(
    ("action_instrument", "action_currency", "action_known_at", "message"),
    (
        ("OTHER", "EUR", "2026-01-01", "instrument"),
        ("VWCE", "USD", "2026-01-01", "currency"),
        ("VWCE", "EUR", "2026-01-07", "not known"),
    ),
)
def test_corporate_actions_must_match_identity_currency_and_knowledge_envelope(
    action_instrument: str,
    action_currency: str,
    action_known_at: str,
    message: str,
) -> None:
    dates = pd.bdate_range("2026-01-01", periods=4)
    action = CorporateAction(
        action_id="DIV-SCOPE",
        instrument_id=action_instrument,
        action_type="dividend",
        announced_at="2026-01-01",
        effective_at="2026-01-05",
        ex_date="2026-01-05",
        payable_at="2026-01-06",
        known_at=action_known_at,
        revision=1,
        source="unit-test",
        source_id="action-scope-test",
        source_checksum="a" * 64,
        amount=1.0,
        currency=action_currency,
    )
    artifact = apply_total_return_adjustments(
        pd.DataFrame(
            {
                "date": dates,
                "close": [100.0, 101.0, 102.0, 104.0],
                "instrument_id": "VWCE",
                "currency": "EUR",
                "source_id": "test",
                "provenance": "unit-test",
            }
        ),
        actions=(action,),
    )

    with pytest.raises(EtfEconomicsError, match=message):
        TotalReturnEvidence.from_adjustment_result(
            artifact,
            instrument_id="VWCE",
            currency="EUR",
            known_at="2026-01-06",
            as_of="2026-01-06",
            source_id="test",
            provenance="unit-test",
            corporate_action_coverage=_corporate_action_coverage(
                "VWCE", "2026-01-06", "2026-01-06"
            ),
        )


def test_row_revision_known_at_cannot_exceed_evidence_envelope() -> None:
    evidence = _total_return_series([100, 101, 102, 104])
    frame = evidence.frame.assign(
        known_at=[
            "2026-01-01T12:00:00Z",
            "2026-01-02T12:00:00Z",
            "2026-01-05T12:00:00Z",
            "2026-01-10T00:00:00Z",
        ]
    )
    revised = _replace_evidence(evidence, frame, known_at="2026-01-06T00:00:00Z")

    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=revised,
        benchmark_total_return=_total_return_series(
            [100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"
        ),
        as_of="2026-01-10",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )

    assert report.status == "unavailable"
    assert "exceeds the evidence envelope" in report.message


def test_report_exposes_selected_revision_and_action_coverage_lineage() -> None:
    fund = _total_return_series([100, 101, 102, 104])
    benchmark = _total_return_series(
        [100, 100.5, 101, 103], instrument_id="FTSE-ALL-WORLD"
    )
    report = calculate_etf_economics(
        "VWCE",
        _economics_records(),
        fund_total_return=fund,
        benchmark_total_return=benchmark,
        as_of="2026-01-06",
        horizon_days=3,
        closure_policy=_closure_policy(),
    )

    assert report.fund_total_return_selected_known_at == fund.known_at
    assert report.benchmark_total_return_selected_known_at == benchmark.known_at
    assert report.fund_corporate_action_coverage["source_checksum"] == "c" * 64
    assert report.benchmark_corporate_action_coverage["source_checksum"] == "c" * 64


def test_future_inception_and_malformed_policy_checksum_fail_closed() -> None:
    future = {**_economics_records()[0], "inception_date": "2030-01-01"}
    report = calculate_etf_economics(
        "VWCE", [future], as_of="2026-01-06", closure_policy=_closure_policy()
    )
    assert report.closure_risk_proxy["status"] == "unavailable"
    assert "inception" in report.closure_risk_proxy["reason"]

    with pytest.raises(EtfEconomicsError, match="SHA-256 identity"):
        replace(_closure_policy(), source_checksum="not-a-checksum")
