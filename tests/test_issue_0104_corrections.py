from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.selectors.instrument_detail import _etf_structure_panel, _score_panel, build_instrument_detail
from etf_cockpit.services import build_snapshot


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
    snapshot = build_snapshot()
    model = build_instrument_detail(snapshot, snapshot.config.universe.enabled_ids[0])

    assert {"identity", "price", "scores", "risk", "attribution", "fundamentals", "etf_disclosures", "etf_structure", "news", "forecasts", "backtests", "history", "journal", "run_changes"} <= set(model.sections)
    assert model.instrument_id


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
    structural_holdings.to_parquet(structural_holdings_path, index=False)
    signal_call: dict[str, object] = {}
    backtest_call: dict[str, object] = {}
    caps_call: dict[str, object] = {}

    class Provider:
        def fetch_prices(self, *_args, **_kwargs):
            return SimpleNamespace(ok=True, data=prices, message="prices loaded")

    monkeypatch.setattr(analysis, "load_config", lambda: config)
    monkeypatch.setattr(analysis.YFinanceProvider, "from_config", lambda _config: Provider())
    monkeypatch.setattr(analysis, "validate_prices", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(analysis, "load_holdings", lambda: pd.DataFrame())
    monkeypatch.setattr(analysis, "compute_features", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(analysis, "latest_features", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(analysis, "write_features", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(analysis, "model_availability", lambda _config: {"timesfm": False, "toto": False})
    monkeypatch.setattr(analysis, "forecast_component_maps", lambda _frame: {})
    monkeypatch.setattr(analysis, "target_policy_issues", lambda _config: [])
    monkeypatch.setattr(analysis, "read_document_registry", lambda: registry)
    monkeypatch.setattr(analysis, "read_etf_report_records", lambda: reports)
    monkeypatch.setattr(analysis, "FUND_HOLDINGS_PATH", structural_holdings_path)
    monkeypatch.setattr(analysis, "structure_confidence_caps", lambda *args, **kwargs: caps_call.update(kwargs) or {instrument: 0.5})
    monkeypatch.setattr(analysis, "generate_signals", lambda *args, **kwargs: signal_call.update(kwargs) or [])
    monkeypatch.setattr(
        analysis,
        "run_backtest",
        lambda *args, **kwargs: backtest_call.update(kwargs) or SimpleNamespace(results=pd.DataFrame(), ai_added_value=False, quality_label="unavailable"),
    )
    monkeypatch.setattr(analysis, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(analysis.sys, "argv", ["run_yfinance_analysis.py", "--no-commit", "--skip-reference", "--skip-models", "--as-of", "2026-07-10"])

    assert analysis.main() == 0
    assert signal_call["structure_confidence_caps"] == {instrument: 0.5}
    assert backtest_call["structure_document_registry"].equals(registry)
    assert backtest_call["structure_report_records"].equals(reports)
    assert backtest_call["structure_holdings"].equals(structural_holdings)
    assert caps_call["holdings"].equals(structural_holdings)
