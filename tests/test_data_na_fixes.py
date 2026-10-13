from __future__ import annotations

import sqlite3
import os
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.application import decision_views, identity_views, instrument_detail_view, overlap, sector_views
from etf_cockpit.application import snapshot_builder, financial_institution_views, selection_views
from etf_cockpit.app import state as state_module
from etf_cockpit.core.config import _load_universe_config
from etf_cockpit.data.identity_master import identity_master_exists
from etf_cockpit.data.local_storage import TransactionalStore, storage_layout
from etf_cockpit.data import trade_candidate_analysis


def test_identity_projection_falls_back_when_master_marker_is_missing(tmp_path: Path) -> None:
    with TransactionalStore(tmp_path):
        pass
    clean = tmp_path / "data" / "clean"
    clean.mkdir(parents=True)
    pd.DataFrame(
        [{"instrument_id": "NONG", "identity_confidence": "manual_review", "identity_status": "manual_review"}]
    ).to_parquet(clean / "instrument_identity.parquet", index=False)

    assert identity_master_exists(tmp_path) is False
    projection = identity_views.load_identity_projection("NONG", storage_root=tmp_path)

    assert projection["status"] == "available"
    assert projection["identity_confidence"] == "manual_review"


def test_identity_projection_prefers_configured_duplicate_and_retains_candidate_sources(tmp_path: Path) -> None:
    path = tmp_path / "instrument_identity.parquet"
    pd.DataFrame(
        [
            {"instrument_id": "BA", "display_name": "Boeing Co", "source": "configs/universe.yaml", "warnings": ""},
            {"instrument_id": "BA", "display_name": "BAE Systems plc", "source": "candidate:BA", "warnings": ""},
        ]
    ).to_parquet(path, index=False)

    projection = identity_views.load_identity_projection("BA", path=path)

    assert projection["status"] == "available"
    assert projection["candidate_count"] == 2
    assert projection["display_name"] == "Boeing Co"
    assert "candidate:BA" in projection["candidate_sources"]
    assert "duplicate_identity_candidates_retained" in projection["warnings"]


def test_scoreboard_lookup_uses_scored_row_before_pending_refresh(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(instrument_detail_view, "SCOREBOARD_PATH", tmp_path / "scoreboard.parquet")
    monkeypatch.setattr(
        instrument_detail_view,
        "load_simple_scoreboard",
        lambda _path: pd.DataFrame(
            [
                {"instrument_id": "NONG", "final_label": "positive_evidence_candidate", "evidence_score_10": 8.6},
                {"instrument_id": "NONG", "final_label": "pending_refresh", "evidence_score_10": None},
            ]
        ),
    )

    row, reason = instrument_detail_view._scoreboard_lookup("NONG")

    assert reason is None
    assert row["final_label"] == "positive_evidence_candidate"
    assert row["evidence_score_10"] == 8.6


def test_score_panel_reads_writer_reason_and_derives_source_dated_freshness() -> None:
    panel = instrument_detail_view._score_panel(
        None,
        {
            "evidence_score_10": 8.6,
            "final_label": "positive_evidence_candidate",
            "reason_short": "Positive evidence from the stored score row.",
            "latest_price_date": "2026-07-08",
        },
        {"crowding": {"status": "unavailable"}},
        {"status": "unavailable"},
    )

    assert panel["status"] == "available"
    assert panel["reason"] == "Positive evidence from the stored score row."
    assert panel["freshness"] == "source_dated"


def test_metric_history_accepts_legacy_rows_without_formula_metadata() -> None:
    columns = set(decision_views._METRIC_HISTORY_DISPLAY_COLUMNS) - {
        "formula_version", "formula_checksum", "source_vintage_hash"
    }
    frame = pd.DataFrame(
        [
            {
                "run_id": "run-1",
                "instrument_id": "VWCE",
                "component_group": "momentum",
                "component_name": "Momentum",
                "source_id": "prices",
                "raw_metric_value": 0.1,
                "normalised_score_10": 7.0,
                "score_available": True,
                "na_reason": None,
                "source_dataset": "features_daily",
                "as_of_date": "2026-07-09",
                "freshness_status": "ok",
                "authority_label": "medium",
                "execution_allowed": False,
            }
        ],
        columns=list(columns),
    )

    projection = decision_views.load_score_metric_history_projection(
        "VWCE", frame=frame, rank_scores={}, cutover_enabled=False
    )

    assert projection["status"] == "partial"
    assert projection["reason_code"] == "legacy_metric_history_metadata_unavailable"
    assert projection["rows"][0]["formula_version"] is None


def test_legacy_forecast_csv_is_loaded_with_cutoff_and_label(monkeypatch, tmp_path: Path) -> None:
    forecasts = tmp_path / "forecasts"
    forecasts.mkdir()
    monkeypatch.setattr(snapshot_builder, "FORECASTS_DIR", forecasts)
    pd.DataFrame(
        [
            {"etf_id": "NONG", "forecast_date": "2026-07-08", "horizon_days": 60, "expected_return": 0.02, "model_name": "baseline", "status": "ok"},
            {"etf_id": "NONG", "forecast_date": "2026-07-10", "horizon_days": 60, "expected_return": 0.03, "model_name": "baseline", "status": "ok"},
        ]
    ).to_csv(forecasts / "forecast_results_yfinance_20260709.csv", index=False)
    older_file = forecasts / "forecast_results_yfinance_20260708.csv"
    pd.DataFrame(
        [
            {"etf_id": "NONG", "forecast_date": "2026-07-08", "horizon_days": 60, "expected_return": 0.01, "model_name": "baseline", "status": "ok"},
        ]
    ).to_csv(older_file, index=False)
    os.utime(older_file, (time.time() + 60, time.time() + 60))

    loaded = snapshot_builder._load_legacy_forecasts(date(2026, 7, 9), allowed_ids={"NONG"})

    assert len(loaded) == 1
    assert loaded.iloc[0]["expected_return"] == 0.02
    assert loaded.iloc[0]["cache_status"] == "legacy_cache"


def test_etf_holdings_panel_reads_legacy_etf_holdings_store(monkeypatch, tmp_path: Path) -> None:
    clean = tmp_path / "data" / "clean"
    clean.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-07-08",
                "etf_id": "VWCE",
                "holding_name": "NVIDIA Corp",
                "holding_id": "NVDA",
                "weight": 0.05,
                "currency": "USD",
                "region": "United States",
                "sector": "Technology",
                "source": "yfinance_top_holdings",
                "staleness_status": "ok",
            }
        ]
    ).to_parquet(clean / "etf_holdings.parquet", index=False)
    monkeypatch.setattr(instrument_detail_view, "load_direct_holdings", lambda: overlap.load_direct_holdings(root=tmp_path))

    panel = instrument_detail_view._etf_disclosure_panel(
        "VWCE",
        document_registry=pd.DataFrame(),
        kid_records=pd.DataFrame(),
        methodology_records=pd.DataFrame(),
        sfdr_records=pd.DataFrame(),
    )

    assert panel["exposure"]["status"] == "available"
    assert panel["exposure"]["rows"][0]["security"] == "NVIDIA Corp"
    assert panel["exposure"]["rows"][0]["authority"] == "manual_unverified"


def test_config_uses_per_listing_exchange_and_universe_theme(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "universe.yaml").write_text(
        "etfs:\n"
        "  - id: AIR\n"
        "    name: Airbus SE\n"
        "    isin: NL0000235190\n"
        "    ticker: AIR.PA\n"
        "    instrument_type: stock\n"
        "    analysis_tier: secondary\n"
        "    currency: EUR\n"
        "    asset_class: equity\n"
        "    exchange: Euronext Paris\n"
        "    sector: Industrials\n"
        "    theme: Aerospace\n",
        encoding="utf-8",
    )

    instrument = next(item for item in _load_universe_config(configs).etfs if item.id == "AIR")

    assert instrument.exchange == "Euronext Paris"
    assert instrument.theme == "Aerospace"


def test_candidate_report_fundamentals_are_exposed_as_partial_vendor_values(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(instrument_detail_view, "REPORTS_DIR", tmp_path)
    pd.DataFrame(
        [
            {
                "instrument_id": "NONG",
                "latest_date": "2026-07-08",
                "trailing_pe": 10.6,
                "price_to_book": 0.88,
                "roe": 0.169,
                "fundamental_source": "yfinance",
                "fundamental_limitations": "Unofficial vendor metrics.",
            }
        ]
    ).to_csv(tmp_path / "yfinance_trade_candidate_analysis_20260709.csv", index=False)

    panel = instrument_detail_view._candidate_report_fundamentals("NONG")

    assert panel is not None
    assert panel["status"] == "partial"
    assert panel["values"]["trailing_pe"] == 10.6
    assert panel["values"]["roe"] == 0.169
    assert panel["score_eligible"] is False
    assert panel["section_metadata"]["growth"]["value"] is None


def test_app_state_assigns_sector_projection_fields(monkeypatch) -> None:
    monkeypatch.setattr(identity_views, "load_classification_projection", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(sector_views, "load_real_asset_projection", lambda instrument_id: {"instrument_id": instrument_id, "status": "unavailable"})
    monkeypatch.setattr(sector_views, "load_cyclical_projection", lambda instrument_id: {"instrument_id": instrument_id, "status": "unavailable"})
    monkeypatch.setattr(sector_views, "load_innovation_projection", lambda instrument_id: {"instrument_id": instrument_id, "status": "unavailable"})
    monkeypatch.setattr(
        financial_institution_views,
        "load_financial_institution_projection",
        lambda instrument_id, **_kwargs: {"instrument_id": instrument_id, "status": "unavailable"},
    )
    state = object.__new__(state_module.AppState)
    state.selected_etf = "NONG"
    state.snapshot = SimpleNamespace(data_report=SimpleNamespace(as_of_date=date(2026, 7, 9)))
    state.financial_projection = None
    state.real_asset_projection = None
    state.cyclical_projection = None
    state.cyclical_source_digest = None
    state.innovation_projection = None
    state.innovation_source_digest = None

    state.assign_sector_projections()

    assert state.financial_projection["instrument_id"] == "NONG"
    assert state.real_asset_projection["instrument_id"] == "NONG"
    assert state.cyclical_projection["instrument_id"] == "NONG"
    assert state.innovation_projection["instrument_id"] == "NONG"


def test_classification_projection_seeds_universe_sector(monkeypatch, tmp_path: Path) -> None:
    config = SimpleNamespace(
        universe=SimpleNamespace(
            etfs=[
                SimpleNamespace(id="NONG", instrument_type="stock", asset_class="equity", sector="Banks", currency="NOK")
            ]
        )
    )
    monkeypatch.setattr(identity_views, "load_config", lambda _config_dir: config)

    projection = identity_views.load_classification_projection("NONG", storage_root=tmp_path)

    classification = projection["classification"]
    assert classification["sector"] == "financials"
    assert projection["sector_adapter_route"]["allowed"] is True
    assert projection["execution_allowed"] is False


def test_refresh_candidate_analysis_retains_candidate_price_history(monkeypatch, tmp_path: Path) -> None:
    forecasts = tmp_path / "forecasts"
    reports = tmp_path / "reports"
    forecasts.mkdir()
    reports.mkdir()
    price_path = forecasts / "yfinance_candidate_prices_current.csv"
    prices = pd.DataFrame(
        {
            "date": ["2026-07-07", "2026-07-08", "2026-07-09"],
            "etf_id": ["NONG"] * 3,
            "adjusted_close": [155.0, 157.2, 158.0],
            "close": [155.0, 157.2, 158.0],
        }
    )
    candidate_data = trade_candidate_analysis.CandidatePriceData(
        candidates=pd.DataFrame([{"instrument_id": "NONG", "yahoo_symbol": "NONG.OL"}]),
        prices=prices,
        effective_as_of=date(2026, 7, 9),
        source_message="local fixture",
    )
    monkeypatch.setattr(trade_candidate_analysis, "CANDIDATE_PRICE_SNAPSHOT_PATH", price_path)
    monkeypatch.setattr(trade_candidate_analysis, "REPORTS_DIR", reports)
    monkeypatch.setattr(trade_candidate_analysis, "fetch_candidate_prices", lambda _config, **_kwargs: candidate_data)
    monkeypatch.setattr(trade_candidate_analysis, "fetch_candidate_fundamentals", lambda _candidates: pd.DataFrame())

    trade_candidate_analysis.refresh_candidate_analysis(SimpleNamespace())
    retained = trade_candidate_analysis.load_candidate_price_snapshot(path=price_path)

    assert len(retained) == 3
    assert retained["etf_id"].astype(str).eq("NONG").all()
    assert retained["adjusted_close"].tolist() == [155.0, 157.2, 158.0]


def test_portfolio_goals_store_without_marker_is_reported_as_uninitialized(tmp_path: Path) -> None:
    path = storage_layout(tmp_path).transactional_path
    path.parent.mkdir(parents=True)
    sqlite3.connect(path).close()

    projection = selection_views.load_portfolio_goals_projection(SimpleNamespace(), root=tmp_path)

    assert projection["store_status"] == "uninitialized"
    assert projection["store_reason"] == "portfolio_goals_store_uninitialized"
