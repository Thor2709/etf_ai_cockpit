from __future__ import annotations

from datetime import date
import inspect
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import etf_cockpit.services as services
from etf_cockpit.app.selectors.instrument_detail import (
    InstrumentDetailViewModel,
    _SECTION_NAMES,
    _etf_structure_panel,
    _score_panel,
    build_etf_structure_panel,
)
from etf_cockpit.backtest.engine import BacktestReport, backtest_input_checksum, run_backtest
from etf_cockpit.data.fund_documents import read_document_registry
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.signals.quality_momentum import FRAME_COLUMNS, QUALITY_MOMENTUM_VERSION


def test_score_panel_prefers_current_structurally_capped_signal_confidence_including_zero() -> None:
    class Signal:
        blocked_by = []
        authority_decision = None
        total_score = 0.8
        canonical_score = None
        research_state = "available"
        reason_long = "Current signal evidence."
        warnings = []
        supporting_metrics = {"canonical_evidence_confidence_10": 0.0}

    panel = _score_panel(
        Signal(),
        {
            "canonical_evidence_confidence_10": 9.0,
            "final_label": "hold",
            "one_line_reason": "Current signal evidence.",
            "freshness_status": "fresh",
        },
        {"crowding": {}, "attribution": {}},
        {},
    )

    assert panel["canonical_evidence_confidence_10"] == 0.0


def test_instrument_detail_standard_loading_reaches_local_factsheet_and_holdings_structure(tmp_path, monkeypatch) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector

    registry = pd.DataFrame(
        [
            {
                "instrument_id": "ETF-1",
                "source_id": "factsheet-1",
                "document_type": "factsheet",
                "document_kind": "factsheet",
                "sha256": "a" * 64,
                "checksum": "a" * 64,
                "document_date": "2026-07-01",
                "known_at": "2026-07-02T00:00:00Z",
                "coverage_status": "available",
            },
            {
                "instrument_id": "ETF-1",
                "source_id": "holdings-1",
                "document_type": "holdings",
                "document_kind": "holdings",
                "sha256": "b" * 64,
                "checksum": "b" * 64,
                "document_date": "2026-07-01",
                "known_at": "2026-07-02T00:00:00Z",
                "coverage_status": "available",
            },
        ]
    )
    factsheet = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "factsheet-1", "document_type": "factsheet",
        "checksum": "a" * 64, "document_date": "2026-07-01", "known_at": "2026-07-02T00:00:00Z",
        "field_name": "replication_method", "value": "Physical", "page": 1, "confidence": "high", "status": "extracted",
    }])
    holdings = pd.DataFrame([{
        "instrument_id": "ETF-1", "source_id": "holdings-1", "document_type": "holdings",
        "checksum": "b" * 64, "document_date": "2026-07-01", "known_at": "2026-07-02T00:00:00Z",
        "field_name": "replication_method", "value": "Synthetic swap", "page": 1, "confidence": "high", "status": "extracted",
    }])
    factsheet_path = tmp_path / "etf_metadata.parquet"
    holdings_path = tmp_path / "fund_holdings.parquet"
    factsheet.to_parquet(factsheet_path, index=False)
    holdings.to_parquet(holdings_path, index=False)
    monkeypatch.setattr(selector, "ETF_METADATA_CLEAN_PATH", factsheet_path)
    monkeypatch.setattr(selector, "FUND_HOLDINGS_PATH", holdings_path)

    projection = _etf_structure_panel(
        "ETF-1",
        document_registry=registry,
        report_records=pd.DataFrame(),
    )

    assert projection["fields"]["replication_method"]["status"] == "conflict"
    assert {projection["documents"][family]["status"] for family in ("factsheet", "holdings")} == {"available"}
    assert projection["execution_allowed"] is False


def test_instrument_detail_keeps_required_structure_section() -> None:
    model = InstrumentDetailViewModel(
        instrument_id="ETF-1",
        display_name="ETF 1",
        status="ready",
        identity={},
        sections={"etf_structure": {"status": "available", "execution_allowed": False}},
    )

    assert "etf_structure" in _SECTION_NAMES
    assert build_etf_structure_panel(model)["status"] == "available"
    assert build_etf_structure_panel(model)["execution_allowed"] is False


def test_real_backtest_signature_accepts_structural_holdings() -> None:
    parameters = inspect.signature(run_backtest).parameters

    assert "structure_holdings" in parameters
    assert parameters["structure_holdings"].kind is inspect.Parameter.KEYWORD_ONLY


def test_real_260_session_backtest_accepts_structural_holdings() -> None:
    config = services.load_config()
    prices = generate_sample_prices(config, periods=260, end_date=date(2026, 7, 10))
    holdings = pd.DataFrame([{"instrument_id": config.universe.enabled_ids[0], "source_id": "holdings-1", "weight": 0.4}])

    report = run_backtest(config, prices, structure_holdings=holdings)

    assert report.metadata["complete_price_rows"] == 260
    assert report.metadata["input_checksum"] == backtest_input_checksum(
        config, prices, pd.DataFrame(), structure_holdings=holdings
    )


def test_backtest_service_reads_holdings_for_run_and_invalidates_cache(tmp_path, monkeypatch) -> None:
    config = services.load_config()
    prices = pd.DataFrame([{"etf_id": config.universe.enabled_ids[0], "date": "2026-07-10", "adjusted_close": 100.0}])
    fundamentals = pd.DataFrame()
    registry = pd.DataFrame([{"instrument_id": config.universe.enabled_ids[0], "source_id": "registry-1"}])
    reports = pd.DataFrame([{"instrument_id": config.universe.enabled_ids[0], "source_id": "report-1"}])
    holdings_path = tmp_path / "fund_holdings.parquet"
    holdings = pd.DataFrame([{"instrument_id": config.universe.enabled_ids[0], "source_id": "holdings-1", "weight": 0.4}])
    holdings.to_parquet(holdings_path, index=False)
    factsheet_path = tmp_path / "etf_metadata.parquet"
    factsheet = pd.DataFrame([{"instrument_id": config.universe.enabled_ids[0], "source_id": "factsheet-1", "field_name": "domicile", "value": "IE"}])
    factsheet.to_parquet(factsheet_path, index=False)
    captured: dict[str, object] = {}

    def fake_run_backtest(
        config_arg,
        prices_arg,
        *,
        fundamentals=None,
        initial_value_eur=10000,
        rebalance_frequency_days=21,
        transaction_cost_bps=None,
        structure_document_registry=None,
        structure_report_records=None,
        structure_supplemental_rows=None,
        structure_holdings=None,
    ):
        captured["structure_holdings"] = structure_holdings.copy()
        captured["structure_supplemental_rows"] = structure_supplemental_rows.copy()
        evidence = pd.DataFrame(columns=FRAME_COLUMNS)
        checksum = backtest_input_checksum(
            config_arg,
            prices_arg,
            fundamentals,
            structure_document_registry=structure_document_registry,
            structure_report_records=structure_report_records,
            structure_supplemental_rows=structure_supplemental_rows,
            structure_holdings=structure_holdings,
        )
        results = pd.DataFrame(
            [
                {
                    "strategy_name": strategy,
                    "calmar": 1.0,
                    "backtest_quality": "low",
                    "return_hit_rate": 0.5,
                    "average_win_return": 0.1,
                    "average_loss_return": -0.1,
                    "payoff_ratio": 1.0,
                    "expected_value_per_period": 0.0,
                    "payoff_asymmetry_warning": "none",
                }
                for strategy in ("momentum_only", "signal_strategy", "quality_momentum")
            ]
        )
        return BacktestReport(
            results=results,
            equity_curves=pd.DataFrame({"signal_strategy": [100.0]}, index=pd.to_datetime(["2026-07-10"])),
            trade_log=pd.DataFrame(columns=["event"]),
            signal_log=pd.DataFrame(columns=["event"]),
            ai_added_value=False,
            quality_label="low",
            metadata={
                "input_checksum": checksum,
                "quality_momentum_strategy_version": QUALITY_MOMENTUM_VERSION,
                "quality_momentum_evidence_checksum": services.quality_momentum_evidence_checksum(evidence),
            },
            quality_momentum_evidence=evidence,
        )

    def fake_settings_identity():
        return {"settings_revision": "settings-1"}

    def fake_settings_revision():
        return "settings-1"

    def fake_run_id(name, *, settings_identity):
        return "backtest-test"

    def fake_manifest(run_id, dependencies, *, settings_identity):
        return None

    def fake_append(path, event, payload):
        return None

    monkeypatch.setattr(services, "BACKTESTS_DIR", tmp_path / "backtests")
    monkeypatch.setattr(services, "FUND_HOLDINGS_PATH", holdings_path)
    monkeypatch.setattr(services, "ETF_METADATA_CLEAN_PATH", factsheet_path)
    monkeypatch.setattr(services, "load_prices", lambda: prices)
    monkeypatch.setattr(services, "load_fundamental_evidence", lambda: fundamentals)
    monkeypatch.setattr(services, "read_document_registry", lambda: registry)
    monkeypatch.setattr(services, "read_etf_report_records", lambda: reports)
    monkeypatch.setattr(services, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(services, "current_settings_identity", fake_settings_identity)
    monkeypatch.setattr(services, "current_settings_revision", fake_settings_revision)
    monkeypatch.setattr(services, "settings_bound_run_id", fake_run_id)
    monkeypatch.setattr(services, "ensure_run_manifest", fake_manifest)
    monkeypatch.setattr(services, "append_jsonl", fake_append)

    service = services.BacktestService(config, universe_revision="universe-1")
    service.run_backtest()
    assert captured["structure_holdings"].equals(holdings)
    assert captured["structure_supplemental_rows"]["source_id"].tolist() == ["factsheet-1"]
    assert service._load_cached_backtest() is not None

    changed = holdings.copy()
    changed.loc[0, "weight"] = 0.6
    changed.to_parquet(holdings_path, index=False)
    assert service._load_cached_backtest() is None


def test_canonical_document_registry_fails_closed_on_duplicate_source_id(tmp_path) -> None:
    path = tmp_path / "fund_documents.parquet"
    pd.DataFrame(
        [
            {"instrument_id": "ETF-1", "source_id": "duplicate", "document_type": "factsheet", "sha256": "a" * 64},
            {"instrument_id": "ETF-1", "source_id": "duplicate", "document_type": "factsheet", "sha256": "b" * 64},
        ]
    ).to_parquet(path, index=False)

    with pytest.raises(ValueError, match="duplicate source_id"):
        read_document_registry(path=path)


def test_canonical_report_reader_fails_closed_on_duplicate_source_id(tmp_path) -> None:
    from etf_cockpit.data.parsed_disclosures import read_etf_report_records

    path = tmp_path / "etf_report_records.parquet"
    pd.DataFrame([{"source_id": "duplicate"}, {"source_id": "duplicate"}]).to_parquet(path, index=False)

    with pytest.raises(ValueError, match="duplicate source_id"):
        read_etf_report_records(path)


def test_yfinance_script_reuses_local_structural_evidence_for_signals_and_backtest(tmp_path, monkeypatch) -> None:
    script_path = Path(__file__).parents[1] / "scripts" / "run_yfinance_analysis.py"
    spec = importlib.util.spec_from_file_location("issue_0104_run_yfinance_analysis", script_path)
    assert spec is not None and spec.loader is not None
    analysis = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analysis)

    instrument = "VWCE"
    config = SimpleNamespace(universe=SimpleNamespace(enabled_ids=[instrument], etfs=[]))
    prices = pd.DataFrame([{"etf_id": instrument, "date": date(2026, 7, 10), "adjusted_close": 100.0}])
    report = SimpleNamespace(as_of_date=date(2026, 7, 10), issues=[], status="ok")
    registry = pd.DataFrame([{"source_id": "local-registry"}])
    reports = pd.DataFrame([{"source_id": "local-report"}])
    structural_holdings = pd.DataFrame([{"source_id": "local-holdings"}])
    structural_holdings_path = tmp_path / "fund_holdings.parquet"
    factsheet = pd.DataFrame([{"source_id": "local-factsheet", "field_name": "domicile", "value": "IE"}])
    factsheet_path = tmp_path / "etf_metadata.parquet"
    structural_holdings.to_parquet(structural_holdings_path, index=False)
    factsheet.to_parquet(factsheet_path, index=False)
    signal_call: dict[str, object] = {}
    backtest_call: dict[str, object] = {}
    caps_call: dict[str, object] = {}

    class Provider:
        def fetch_prices(self, symbols, start_date, end_date):
            return SimpleNamespace(ok=True, data=prices, message="prices loaded")

    def fake_validate_prices(prices_arg, *, as_of_date):
        return report

    def fake_compute_features(prices_arg, *, benchmark_etf_id):
        return pd.DataFrame()

    def fake_latest_features(features_arg, as_of_date):
        return pd.DataFrame()

    def fake_structure_caps(instrument_ids, *, document_registry, report_records, supplemental_rows, holdings, decision_time):
        caps_call.update(
            {
                "document_registry": document_registry,
                "report_records": report_records,
                "supplemental_rows": supplemental_rows,
                "holdings": holdings,
                "decision_time": decision_time,
            }
        )
        return {instrument: 0.5}

    def fake_generate_signals(
        config_arg,
        latest_arg,
        holdings_arg,
        data_report_arg,
        *,
        as_of_date,
        toto_available,
        timesfm_available,
        forecast_scores,
        structure_confidence_caps,
    ):
        signal_call.update({"structure_confidence_caps": structure_confidence_caps})
        return []

    def fake_run_backtest_for_script(
        config_arg,
        prices_arg,
        *,
        fundamentals=None,
        initial_value_eur=10000,
        rebalance_frequency_days=21,
        transaction_cost_bps=None,
        structure_document_registry=None,
        structure_report_records=None,
        structure_supplemental_rows=None,
        structure_holdings=None,
    ):
        backtest_call.update(
            {
                "structure_document_registry": structure_document_registry,
                "structure_report_records": structure_report_records,
                "structure_supplemental_rows": structure_supplemental_rows,
                "structure_holdings": structure_holdings,
            }
        )
        return SimpleNamespace(results=pd.DataFrame(), ai_added_value=False, quality_label="unavailable")

    monkeypatch.setattr(analysis, "load_config", lambda: config)
    monkeypatch.setattr(analysis.YFinanceProvider, "from_config", lambda _config: Provider())
    monkeypatch.setattr(analysis, "validate_prices", fake_validate_prices)
    monkeypatch.setattr(analysis, "load_holdings", lambda: pd.DataFrame())
    monkeypatch.setattr(analysis, "compute_features", fake_compute_features)
    monkeypatch.setattr(analysis, "latest_features", fake_latest_features)
    monkeypatch.setattr(analysis, "write_features", lambda features_arg: None)
    monkeypatch.setattr(analysis, "model_availability", lambda _config: {"timesfm": False, "toto": False})
    monkeypatch.setattr(analysis, "forecast_component_maps", lambda _frame: {})
    monkeypatch.setattr(analysis, "target_policy_issues", lambda _config: [])
    monkeypatch.setattr(analysis, "read_document_registry", lambda: registry)
    monkeypatch.setattr(analysis, "read_etf_report_records", lambda: reports)
    monkeypatch.setattr(analysis, "FUND_HOLDINGS_PATH", structural_holdings_path)
    monkeypatch.setattr(analysis, "ETF_METADATA_CLEAN_PATH", factsheet_path)
    monkeypatch.setattr(analysis, "structure_confidence_caps", fake_structure_caps)
    monkeypatch.setattr(analysis, "generate_signals", fake_generate_signals)
    monkeypatch.setattr(analysis, "run_backtest", fake_run_backtest_for_script)
    monkeypatch.setattr(analysis, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(analysis.sys, "argv", ["run_yfinance_analysis.py", "--no-commit", "--skip-reference", "--skip-models", "--as-of", "2026-07-10"])

    assert analysis.main() == 0
    assert signal_call["structure_confidence_caps"] == {instrument: 0.5}
    assert backtest_call["structure_document_registry"].equals(registry)
    assert backtest_call["structure_report_records"].equals(reports)
    assert backtest_call["structure_supplemental_rows"]["source_id"].tolist() == ["local-factsheet"]
    assert backtest_call["structure_holdings"].equals(structural_holdings)
    assert caps_call["supplemental_rows"]["source_id"].tolist() == ["local-factsheet"]
    assert caps_call["holdings"].equals(structural_holdings)
