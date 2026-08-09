from __future__ import annotations

import json
import zipfile
from datetime import date, timedelta

import pandas as pd
import yaml

from etf_cockpit.app.state import AppState
from etf_cockpit.chatgpt_bridge import export_pack as export_module
from etf_cockpit.chatgpt_bridge import import_audit as import_module
from etf_cockpit.core.config import ModelRuntimeConfig, ProviderSection, load_config, save_provider_settings
from etf_cockpit.data.fx_data import commit_fx_import
from etf_cockpit.data.import_pipeline import commit_price_import, rollback_latest_price_import
from etf_cockpit.data.manual_notes import commit_manual_news_import
from etf_cockpit.data.providers import ManualLocalFileProvider
from etf_cockpit.data.reference_data import commit_reference_import
from etf_cockpit.data.sample_data import generate_sample_prices
from etf_cockpit.data.validation import validate_holdings, validate_prices
from etf_cockpit.models.timesfm_adapter import TimesFMAdapter
from etf_cockpit.models.toto_adapter import TotoAdapter
from etf_cockpit.models.forecast_scores import forecast_component_maps
from etf_cockpit.services import DataService, ForecastService


def test_provider_config_loads_and_redacts_secrets() -> None:
    section = ProviderSection(active_provider="generic", api_key="secret-token", base_url="https://example.invalid")
    assert section.redacted()["api_key"] == "***redacted***"


def test_provider_config_loads_env_overrides_and_redacts_secret(monkeypatch) -> None:
    monkeypatch.setenv("ETF_COCKPIT_PRICES_PROVIDER", "generic")
    monkeypatch.setenv("ETF_COCKPIT_PRICES_BASE_URL", "https://prices.example.invalid")
    monkeypatch.setenv("ETF_COCKPIT_PRICES_API_KEY", "secret-token")

    section = load_config().data_providers.section("prices")

    assert section.active_provider == "generic"
    assert section.base_url == "https://prices.example.invalid"
    assert section.api_key == "secret-token"
    assert section.redacted()["api_key"] == "***redacted***"


def test_save_provider_settings_keeps_api_key_out_of_yaml(tmp_path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "data_providers.yaml").write_text(
        yaml.safe_dump({"providers": {"prices": {"active_provider": "none", "api_key": "", "base_url": "", "symbols_map": {}}}}),
        encoding="utf-8",
    )

    save_provider_settings(
        "prices",
        active_provider="generic",
        base_url="https://prices.example.invalid",
        api_key="secret-token",
        config_dir=config_dir,
    )
    saved_yaml = yaml.safe_load((config_dir / "data_providers.yaml").read_text(encoding="utf-8"))
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")

    assert saved_yaml["providers"]["prices"]["active_provider"] == "generic"
    assert saved_yaml["providers"]["prices"]["base_url"] == "https://prices.example.invalid"
    assert saved_yaml["providers"]["prices"]["api_key"] == ""
    assert "secret-token" not in (config_dir / "data_providers.yaml").read_text(encoding="utf-8")
    assert 'ETF_COCKPIT_PRICES_API_KEY="secret-token"' in env_text


def test_no_provider_api_update_returns_safe_message() -> None:
    config = load_config()
    config.data_providers.providers["prices"] = ProviderSection()
    message = DataService(config).api_update_status()
    assert "No API provider configured" in message


def test_local_file_provider_imports_csv_without_replacing_data(tmp_path) -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=260, end_date=pd.Timestamp("2026-06-26").date())
    path = tmp_path / "prices.csv"
    prices.to_csv(path, index=False)

    result = DataService(config).import_local_file(path, "prices")

    assert result.ok
    assert result.metadata is not None
    assert result.metadata.checksum


def test_validated_price_import_writes_raw_clean_and_snapshot_files(tmp_path) -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=260, end_date=pd.Timestamp("2026-06-26").date())
    source_path = tmp_path / "prices.csv"
    prices.to_csv(source_path, index=False)
    result = ManualLocalFileProvider().import_file(source_path, "prices")
    compatibility_path = tmp_path / "validated" / "prices_daily.parquet"
    clean_path = tmp_path / "clean" / "prices.parquet"
    raw_dir = tmp_path / "raw" / "prices"
    snapshots_dir = tmp_path / "snapshots" / "prices"

    first_commit = commit_price_import(
        result,
        compatibility_path=compatibility_path,
        clean_path=clean_path,
        raw_dir=raw_dir,
        snapshots_dir=snapshots_dir,
    )
    second_commit = commit_price_import(
        result,
        compatibility_path=compatibility_path,
        clean_path=clean_path,
        raw_dir=raw_dir,
        snapshots_dir=snapshots_dir,
    )

    assert first_commit.raw_path.exists()
    assert first_commit.clean_path.exists()
    assert first_commit.compatibility_path.exists()
    assert first_commit.metadata_path.exists()
    assert first_commit.previous_snapshot_path is None
    assert second_commit.previous_snapshot_path is not None
    assert second_commit.previous_snapshot_path.exists()


def test_three_rapid_price_imports_keep_unique_audit_and_snapshot_files(tmp_path) -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=260, end_date=pd.Timestamp("2026-06-26").date())
    source_path = tmp_path / "prices.csv"
    prices.to_csv(source_path, index=False)
    result = ManualLocalFileProvider().import_file(source_path, "prices")
    kwargs = {
        "compatibility_path": tmp_path / "validated" / "prices_daily.parquet",
        "clean_path": tmp_path / "clean" / "prices.parquet",
        "raw_dir": tmp_path / "raw" / "prices",
        "snapshots_dir": tmp_path / "snapshots" / "prices",
    }

    commits = [commit_price_import(result, **kwargs) for _ in range(3)]

    assert len({commit.raw_path for commit in commits}) == 3
    assert len({commit.metadata_path for commit in commits}) == 3
    assert len({commit.previous_snapshot_path for commit in commits[1:]}) == 2


def test_price_import_rollback_restores_previous_snapshot(tmp_path) -> None:
    config = load_config()
    original = generate_sample_prices(config, periods=260, end_date=pd.Timestamp("2026-06-26").date())
    modified = original.copy()
    for column in ["open", "high", "low", "close", "adjusted_close"]:
        modified[column] = modified[column] * 1.02
    original_path = tmp_path / "original_prices.csv"
    modified_path = tmp_path / "modified_prices.csv"
    original.to_csv(original_path, index=False)
    modified.to_csv(modified_path, index=False)
    provider = ManualLocalFileProvider()
    compatibility_path = tmp_path / "validated" / "prices_daily.parquet"
    clean_path = tmp_path / "clean" / "prices.parquet"
    raw_dir = tmp_path / "raw" / "prices"
    snapshots_dir = tmp_path / "snapshots" / "prices"

    commit_price_import(
        provider.import_file(original_path, "prices"),
        compatibility_path=compatibility_path,
        clean_path=clean_path,
        raw_dir=raw_dir,
        snapshots_dir=snapshots_dir,
    )
    commit_price_import(
        provider.import_file(modified_path, "prices"),
        compatibility_path=compatibility_path,
        clean_path=clean_path,
        raw_dir=raw_dir,
        snapshots_dir=snapshots_dir,
    )
    rollback = rollback_latest_price_import(
        compatibility_path=compatibility_path,
        clean_path=clean_path,
        snapshots_dir=snapshots_dir,
    )
    restored = pd.read_parquet(compatibility_path)

    assert rollback.current_snapshot_path is not None
    assert rollback.current_snapshot_path.exists()
    assert restored["adjusted_close"].round(8).tolist() == original["adjusted_close"].round(8).tolist()


def test_manual_news_import_writes_clean_snapshot_and_forces_non_executable(tmp_path) -> None:
    source_path = tmp_path / "manual_notes.csv"
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-06-25",
                "etf_id": "WORLD_CORE",
                "title": "Factsheet review",
                "note": "Underlying exposure is consistent with the manual thesis.",
                "source": "manual_test",
                "executable_authority": True,
            }
        ]
    ).to_csv(source_path, index=False)
    result = ManualLocalFileProvider().import_file(source_path, "manual_news")
    clean_path = tmp_path / "clean" / "manual_news.parquet"
    raw_dir = tmp_path / "raw" / "manual_news"
    snapshots_dir = tmp_path / "snapshots" / "manual_news"

    first_commit = commit_manual_news_import(
        result,
        known_etfs={"WORLD_CORE"},
        clean_path=clean_path,
        raw_dir=raw_dir,
        snapshots_dir=snapshots_dir,
    )
    second_commit = commit_manual_news_import(
        result,
        known_etfs={"WORLD_CORE"},
        clean_path=clean_path,
        raw_dir=raw_dir,
        snapshots_dir=snapshots_dir,
    )
    saved = pd.read_parquet(clean_path)

    assert first_commit.raw_path.exists()
    assert first_commit.metadata_path.exists()
    assert second_commit.previous_snapshot_path is not None
    assert second_commit.previous_snapshot_path.exists()
    assert saved["executable_authority"].eq(False).all()
    assert saved["staleness_status"].eq("dated_only").all()
    assert {"source_credibility", "promotional_risk", "reproducibility", "claim_quality"} <= set(saved.columns)
    assert first_commit.metadata.staleness_status == "dated_only"
    assert any("forced to false" in warning for warning in first_commit.warnings)


def test_manual_news_import_rejects_missing_date(tmp_path) -> None:
    source_path = tmp_path / "manual_notes.csv"
    pd.DataFrame([{"etf_id": "WORLD_CORE", "note": "Missing a dated evidence field."}]).to_csv(source_path, index=False)

    result = DataService(load_config()).import_local_file(source_path, "manual_news")

    assert not result.ok
    assert "require one dated column" in result.message


def test_manual_news_source_credibility_labels_reddit_and_official_sources(tmp_path) -> None:
    source_path = tmp_path / "manual_notes.csv"
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-06-26",
                "etf_id": "WORLD_CORE",
                "title": "10% return in 9 days screenshot",
                "note": "Reddit post with performance screenshot and win rate claim.",
                "source": "reddit",
                "source_url": "https://www.reddit.com/r/ai_trading/example",
            },
            {
                "as_of_date": "2026-06-26",
                "etf_id": "WORLD_CORE",
                "title": "Issuer factsheet",
                "note": "Official issuer factsheet context.",
                "source": "official issuer",
                "source_url": "https://issuer.example/factsheet.pdf",
            },
        ]
    ).to_csv(source_path, index=False)
    result = ManualLocalFileProvider().import_file(source_path, "manual_news")
    commit = commit_manual_news_import(
        result,
        known_etfs={"WORLD_CORE"},
        clean_path=tmp_path / "clean" / "manual_news.parquet",
        raw_dir=tmp_path / "raw" / "manual_news",
        snapshots_dir=tmp_path / "snapshots" / "manual_news",
    )
    saved = pd.read_parquet(commit.clean_path)

    reddit = saved[saved["source"].eq("reddit")].iloc[0]
    official = saved[saved["source"].eq("official issuer")].iloc[0]
    assert reddit["source_credibility"] == "anecdotal"
    assert reddit["evidence_grade"] == "low"
    assert reddit["reproducibility"] == "low"
    assert official["source_credibility"] == "provider_documentation"
    assert official["evidence_grade"] == "moderate"
    assert saved["executable_authority"].eq(False).all()


def test_etf_metadata_import_writes_clean_snapshot_and_staleness(tmp_path) -> None:
    source_path = tmp_path / "factsheets.csv"
    pd.DataFrame(
        [
            {
                "as_of_date": date.today().isoformat(),
                "isin": "IE00B4L5Y983",
                "ticker": "IWDA",
                "name": "World Equity Core ETF",
                "currency": "EUR",
                "ter": 0.002,
                "provider": "manual_test",
            }
        ]
    ).to_csv(source_path, index=False)
    result = ManualLocalFileProvider().import_file(source_path, "etf_metadata")
    clean_path = tmp_path / "clean" / "etf_metadata.parquet"
    raw_dir = tmp_path / "raw" / "etf_factsheets"
    snapshots_dir = tmp_path / "snapshots" / "etf_metadata"

    commit = commit_reference_import(
        result,
        "etf_metadata",
        known_etfs={"WORLD_CORE"},
        isin_to_etf_id={"IE00B4L5Y983": "WORLD_CORE"},
        ticker_to_etf_id={"IWDA": "WORLD_CORE"},
        clean_path=clean_path,
        raw_dir=raw_dir,
        snapshots_dir=snapshots_dir,
    )
    saved = pd.read_parquet(clean_path)

    assert commit.raw_path.exists()
    assert commit.metadata_path.exists()
    assert commit.metadata.source_type == "etf_metadata"
    assert commit.metadata.staleness_status == "ok"
    assert saved["etf_id"].tolist() == ["WORLD_CORE"]


def test_etf_holdings_import_normalises_weight_percent_and_snapshots(tmp_path) -> None:
    source_path = tmp_path / "holdings.csv"
    pd.DataFrame(
        [
            {
                "as_of_date": date.today().isoformat(),
                "etf_id": "WORLD_CORE",
                "holding_name": "Example Holding A",
                "weight_percent": 60.0,
                "sector": "Technology",
                "region": "United States",
            },
            {
                "as_of_date": date.today().isoformat(),
                "etf_id": "WORLD_CORE",
                "holding_name": "Example Holding B",
                "weight_percent": 40.0,
                "sector": "Healthcare",
                "region": "Europe",
            },
        ]
    ).to_csv(source_path, index=False)
    result = ManualLocalFileProvider().import_file(source_path, "etf_holdings")
    clean_path = tmp_path / "clean" / "etf_holdings.parquet"
    raw_dir = tmp_path / "raw" / "etf_holdings"
    snapshots_dir = tmp_path / "snapshots" / "etf_holdings"

    first_commit = commit_reference_import(
        result,
        "etf_holdings",
        known_etfs={"WORLD_CORE"},
        clean_path=clean_path,
        raw_dir=raw_dir,
        snapshots_dir=snapshots_dir,
    )
    second_commit = commit_reference_import(
        result,
        "etf_holdings",
        known_etfs={"WORLD_CORE"},
        clean_path=clean_path,
        raw_dir=raw_dir,
        snapshots_dir=snapshots_dir,
    )
    saved = pd.read_parquet(clean_path)

    assert first_commit.metadata.source_type == "etf_holdings"
    assert second_commit.previous_snapshot_path is not None
    assert second_commit.previous_snapshot_path.exists()
    assert round(float(saved["weight"].sum()), 6) == 1.0


def test_etf_holdings_import_rejects_decimal_weight_above_one(tmp_path) -> None:
    source_path = tmp_path / "holdings.csv"
    pd.DataFrame(
        [
            {
                "as_of_date": date.today().isoformat(),
                "etf_id": "WORLD_CORE",
                "holding_name": "Example Holding A",
                "weight": 60.0,
            }
        ]
    ).to_csv(source_path, index=False)

    result = DataService(load_config()).import_local_file(source_path, "etf_holdings")

    assert not result.ok
    assert "use weight_percent" in result.message


def test_stale_etf_metadata_import_reports_block_staleness(tmp_path) -> None:
    source_path = tmp_path / "factsheets.csv"
    old_date = (date.today() - timedelta(days=180)).isoformat()
    pd.DataFrame(
        [
            {
                "as_of_date": old_date,
                "etf_id": "WORLD_CORE",
                "name": "World Equity Core ETF",
                "currency": "EUR",
            }
        ]
    ).to_csv(source_path, index=False)

    result = DataService(load_config()).import_local_file(source_path, "etf_metadata")

    assert result.ok
    assert result.metadata is not None
    assert result.metadata.staleness_status == "block"


def test_fx_import_writes_clean_snapshot_and_metadata(tmp_path) -> None:
    source_path = tmp_path / "fx.csv"
    pd.DataFrame(
        [
            {"as_of_date": date.today().isoformat(), "pair": "USD/EUR", "rate": 0.93, "source": "manual_test"},
            {"as_of_date": date.today().isoformat(), "pair": "GBP/EUR", "rate": 1.17, "source": "manual_test"},
        ]
    ).to_csv(source_path, index=False)
    result = ManualLocalFileProvider().import_file(source_path, "fx")
    clean_path = tmp_path / "clean" / "fx.parquet"
    raw_dir = tmp_path / "raw" / "fx"
    snapshots_dir = tmp_path / "snapshots" / "fx"

    first_commit = commit_fx_import(result, clean_path=clean_path, raw_dir=raw_dir, snapshots_dir=snapshots_dir)
    second_commit = commit_fx_import(result, clean_path=clean_path, raw_dir=raw_dir, snapshots_dir=snapshots_dir)
    saved = pd.read_parquet(clean_path)

    assert first_commit.raw_path.exists()
    assert first_commit.metadata_path.exists()
    assert first_commit.metadata.source_type == "fx"
    assert first_commit.metadata.staleness_status == "ok"
    assert second_commit.previous_snapshot_path is not None
    assert second_commit.previous_snapshot_path.exists()
    assert set(saved["pair"]) == {"USD/EUR", "GBP/EUR"}


def test_fx_import_rejects_invalid_pair(tmp_path) -> None:
    source_path = tmp_path / "fx.csv"
    pd.DataFrame([{"as_of_date": date.today().isoformat(), "pair": "USDE", "rate": 0.93}]).to_csv(source_path, index=False)

    result = DataService(load_config()).import_local_file(source_path, "fx")

    assert not result.ok
    assert "invalid currency codes" in result.message


def test_non_eur_holding_requires_dated_fx_rate() -> None:
    config = load_config()
    holdings = pd.DataFrame(
        [
            {
                "as_of_date": "2026-06-26",
                "etf_id": "VWCE",
                "units": 10,
                "market_price": 100,
                "market_value_eur": 930,
                "current_weight": 0.10,
                "currency": "USD",
                "source": "test",
            }
        ]
    )

    report = validate_holdings(config, holdings, as_of_date=pd.Timestamp("2026-06-26").date(), fx_rates=pd.DataFrame())

    assert "missing_fx_rate" in {issue.code for issue in report.issues if issue.severity == "block"}
    assert not report.analysis_allowed


def test_non_eur_holding_reconciles_with_explicit_dated_fx_rate() -> None:
    config = load_config()
    holdings = pd.DataFrame(
        [
            {
                "as_of_date": "2026-06-26",
                "etf_id": "VWCE",
                "units": 10,
                "market_price": 100,
                "market_value_eur": 930,
                "current_weight": 0.10,
                "currency": "USD",
                "source": "test",
            }
        ]
    )
    fx_rates = pd.DataFrame(
        [
            {
                "as_of_date": "2026-06-26",
                "base_currency": "USD",
                "quote_currency": "EUR",
                "pair": "USD/EUR",
                "rate": 0.93,
                "source": "test",
                "staleness_status": "ok",
            }
        ]
    )

    report = validate_holdings(config, holdings, as_of_date=pd.Timestamp("2026-06-26").date(), fx_rates=fx_rates)

    issue_codes = {issue.code for issue in report.issues}
    assert "missing_fx_rate" not in issue_codes
    assert "holding_fx_value_mismatch" not in issue_codes
    assert report.analysis_allowed


def test_stale_fx_rate_blocks_non_eur_holding_reconciliation() -> None:
    config = load_config()
    holdings = pd.DataFrame(
        [
            {
                "as_of_date": "2026-06-26",
                "etf_id": "VWCE",
                "units": 10,
                "market_price": 100,
                "market_value_eur": 930,
                "current_weight": 0.10,
                "currency": "USD",
                "source": "test",
            }
        ]
    )
    fx_rates = pd.DataFrame(
        [
            {
                "as_of_date": "2026-06-01",
                "base_currency": "USD",
                "quote_currency": "EUR",
                "pair": "USD/EUR",
                "rate": 0.93,
                "source": "test",
                "staleness_status": "block",
            }
        ]
    )

    report = validate_holdings(config, holdings, as_of_date=pd.Timestamp("2026-06-26").date(), fx_rates=fx_rates)

    assert "stale_fx_rate" in {issue.code for issue in report.issues if issue.severity == "block"}
    assert not report.analysis_allowed


def test_price_rollback_without_snapshot_returns_safe_message(tmp_path, monkeypatch) -> None:
    config = load_config()
    empty_snapshot_dir = tmp_path / "snapshots" / "prices"
    monkeypatch.setattr("etf_cockpit.services.rollback_price_store", lambda: rollback_latest_price_import(snapshots_dir=empty_snapshot_dir))

    message = DataService(config).rollback_latest_price_import()

    assert "No previous clean price snapshot" in message


def test_price_freshness_uses_warning_and_block_tiers() -> None:
    config = load_config()
    warning_prices = generate_sample_prices(config, periods=300, end_date=pd.Timestamp("2026-06-19").date())
    warning_report = validate_prices(warning_prices, as_of_date=pd.Timestamp("2026-06-26").date())
    assert "stale_data_warning" in {issue.code for issue in warning_report.issues}
    assert "stale_data" not in {issue.code for issue in warning_report.issues if issue.severity == "block"}

    blocked_prices = generate_sample_prices(config, periods=300, end_date=pd.Timestamp("2026-06-01").date())
    blocked_report = validate_prices(blocked_prices, as_of_date=pd.Timestamp("2026-06-26").date())
    assert "stale_data" in {issue.code for issue in blocked_report.issues if issue.severity == "block"}


def test_target_policy_violation_is_visible_context_not_analysis_block() -> None:
    config = load_config()
    config.targets.positions["VWCE"].target_weight = 0.42
    config.targets.cash_target_weight = 0.58
    report = DataService(config).validate_prices(
        generate_sample_prices(config, periods=300, end_date=pd.Timestamp("2026-06-26").date()),
        as_of_date=pd.Timestamp("2026-06-26").date(),
    )
    target_issues = [issue for issue in report.issues if issue.code == "target_policy_violation"]

    assert report.analysis_allowed
    assert target_issues
    assert {issue.severity for issue in target_issues} == {"warning"}


def test_current_holdings_concentration_violation_is_visible_context() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=300, end_date=pd.Timestamp("2026-06-26").date())
    holdings = _synthetic_holdings_from_weights(prices, {"VWCE": 0.40})
    report = DataService(config).validate_prices(prices, as_of_date=pd.Timestamp("2026-06-26").date(), holdings=holdings)
    issues = [issue for issue in report.issues if issue.code == "current_concentration_violation"]
    metadata_types = {metadata.source_type for metadata in report.dataset_metadata}

    assert issues
    assert {issue.severity for issue in issues} == {"warning"}
    assert "portfolio_holdings" in metadata_types
    assert report.analysis_allowed


def test_holdings_cash_minimum_breach_is_visible_context() -> None:
    config = load_config()
    prices = generate_sample_prices(config, periods=300, end_date=pd.Timestamp("2026-06-26").date())
    holdings = _synthetic_holdings_from_weights(prices, {"VWCE": 0.60, "LYP6": 0.39})

    report = DataService(config).validate_prices(
        prices,
        as_of_date=pd.Timestamp("2026-06-26").date(),
        holdings=holdings,
    )

    cash_issues = [issue for issue in report.issues if issue.code == "cash_minimum_breached"]
    assert cash_issues
    assert {issue.severity for issue in cash_issues} == {"warning"}
    assert report.analysis_allowed


def test_unavailable_models_are_not_allowed_in_score() -> None:
    timesfm = TimesFMAdapter(ModelRuntimeConfig(enabled=False, mode="disabled")).forecast_series(
        pd.Series([1.0, 1.1, 1.2]),
        [5],
        etf_id="VWCE",
    )[0]
    toto = TotoAdapter(ModelRuntimeConfig(enabled=False, mode="disabled")).forecast_etf(
        "VWCE",
        pd.Timestamp("2026-06-26").date(),
        [5],
    )[0]

    for result in (timesfm, toto):
        assert result.status == "unavailable"
        assert result.expected_return is None
        assert result.q10_return is None
        assert result.q50_return is None
        assert result.q90_return is None
        assert result.model_allowed_in_score is False
        assert result.reason_unavailable


def test_forecast_service_runs_optional_model_rows_when_enabled(tmp_path) -> None:
    config = load_config()
    config.models.models["timesfm"] = {"enabled": True, "mode": "mock"}
    config.models.models["toto"] = {"enabled": True, "mode": "mock", "context_length": 128}
    prices = generate_sample_prices(config, periods=260, end_date=pd.Timestamp("2026-06-26").date())
    etf_id = config.universe.enabled_ids[0]

    forecasts = ForecastService(config).run_forecasts(
        pd.Timestamp("2026-06-26").date(),
        [etf_id],
        prices,
        output_path=tmp_path / "forecasts.csv",
    )
    model_names = {forecast.model_name for forecast in forecasts}

    assert {"baseline", "timesfm", "toto"} <= model_names
    assert all(forecast.status == "ok" for forecast in forecasts)


def test_valid_forecast_rows_become_model_score_inputs() -> None:
    forecasts = pd.DataFrame(
        [
            {
                "model_name": "toto",
                "etf_id": "VWCE",
                "horizon_days": 60,
                "expected_return": 0.06,
                "status": "ok",
                "model_allowed_in_score": True,
            },
            {
                "model_name": "timesfm",
                "etf_id": "VWCE",
                "horizon_days": 60,
                "expected_return": None,
                "status": "skipped",
                "model_allowed_in_score": False,
            },
        ]
    )

    scores = forecast_component_maps(forecasts)

    assert scores["toto"]["VWCE"] > 0
    assert scores["timesfm"] == {}


def test_audit_export_contains_validation_and_risk_gate_reports(tmp_path, monkeypatch) -> None:
    state = AppState.load()
    canonical_path = export_module.AUDIT_PACKETS_DIR / (
        f"audit_packet_{state.snapshot.data_report.as_of_date:%Y-%m-%d}.zip"
    )
    canonical_before = canonical_path.read_bytes() if canonical_path.exists() else None
    monkeypatch.setattr(export_module, "CHATGPT_EXPORTS_DIR", tmp_path / "audit_packets")
    zip_path = state.export_audit_packet()

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        signal_table = pd.read_csv(archive.open("02_signal_table.csv"))

    assert zip_path.parent == tmp_path / "audit_packets"
    assert zip_path.stem.startswith("audit_packet_")
    assert "10_validation_report.json" in names
    assert "11_risk_gate_report.json" in names
    assert "12_reference_data_inventory.json" in names
    assert "13_fx_inventory.json" in names
    assert {
        "cost_low_bps",
        "cost_base_bps",
        "cost_high_bps",
        "edge_to_cost_low",
        "edge_to_cost_base",
        "edge_to_cost_high",
        "cost_stress_warning",
        "cost_stress_assumptions",
    } <= set(signal_table.columns)
    assert (canonical_path.read_bytes() if canonical_path.exists() else None) == canonical_before


def test_audit_export_includes_imported_manual_news_notes(tmp_path, monkeypatch) -> None:
    manual_news_path = tmp_path / "manual_news.parquet"
    pd.DataFrame(
        [
            {
                "as_of_date": "2026-06-25",
                "etf_id": "VWCE",
                "title": "Manual thesis note",
                "note": "This is evidence only and cannot trigger a trade.",
                "source": "manual_test",
                "confidence": "medium",
                "imported_at": "2026-06-26T00:00:00+00:00",
                "executable_authority": False,
                "staleness_status": "dated_only",
                "authority_note": "Manual news/thesis notes are dated audit evidence only.",
                "source_type_category": "community_anecdote",
                "evidence_grade": "low",
                "source_credibility": "anecdotal",
                "promotional_risk": "medium",
                "reproducibility": "low",
                "claim_quality": "community_context_only",
            }
        ]
    ).to_parquet(manual_news_path, index=False)
    monkeypatch.setattr(export_module, "CHATGPT_EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(export_module, "MANUAL_NEWS_CLEAN_PATH", manual_news_path)
    state = AppState.load()

    zip_path = state.export_audit_packet()

    with zipfile.ZipFile(zip_path) as archive:
        news_text = archive.read("06_recent_news_events.md").decode("utf-8")

    assert "Manual thesis note" in news_text
    assert "executable_authority=false" in news_text
    assert "evidence_grade=low" in news_text
    assert "credibility=anecdotal" in news_text
    assert "cannot trigger a trade" in news_text


def test_audit_export_orders_unordered_canonical_news_and_fundamentals_before_tail(tmp_path, monkeypatch) -> None:
    news_path = tmp_path / "news_context.parquet"
    news_rows = [
        {
            "news_id": "canonical-news-newest",
            "instrument_id": "VWCE",
            "published_at": "2026-07-21T00:00:00+00:00",
            "ingested_at": "2026-07-21T00:00:00+00:00",
            "provider_name": "test-provider",
            "source_url": "https://example.invalid/news-newest",
            "timestamp_status": "validated",
        }
    ] + [
        {
            "news_id": f"canonical-news-{day:02d}",
            "instrument_id": "VWCE",
            "published_at": f"2026-07-{day:02d}T00:00:00+00:00",
            "ingested_at": f"2026-07-{day:02d}T00:00:00+00:00",
            "provider_name": "test-provider",
            "source_url": f"https://example.invalid/news-{day:02d}",
            "timestamp_status": "validated",
        }
        for day in range(1, 21)
    ]
    pd.DataFrame(news_rows).to_parquet(news_path, index=False)

    fundamentals_path = tmp_path / "fundamentals.parquet"
    fundamental_rows = [
        {
            "instrument_id": "VWCE",
            "as_of_date": "2026-07-21",
            "eligibility": "newest_fundamental_evidence",
            "source": "test-source",
            "missing_fields": "",
        }
    ] + [
        {
            "instrument_id": "VWCE",
            "as_of_date": f"2026-07-{day:02d}",
            "eligibility": "old_fundamental_evidence",
            "source": "test-source",
            "missing_fields": "",
        }
        for day in range(1, 21)
    ]
    pd.DataFrame(fundamental_rows).to_parquet(fundamentals_path, index=False)

    monkeypatch.setattr(export_module, "CHATGPT_EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(export_module, "NEWS_CONTEXT_PATH", news_path)
    monkeypatch.setattr(export_module, "FUNDAMENTAL_CLEAN_PATH", fundamentals_path)
    state = AppState.load()

    zip_path = export_module.export_review_pack(
        state.snapshot.config,
        state.snapshot.holdings,
        state.snapshot.features,
        state.snapshot.signals,
        state.snapshot.backtest,
        as_of_date=state.snapshot.data_report.as_of_date,
        data_report=state.snapshot.data_report,
    )

    with zipfile.ZipFile(zip_path) as archive:
        news_text = archive.read("06_recent_news_events.md").decode("utf-8")

    assert "source_url=https://example.invalid/news-newest" in news_text
    assert "2026-07-21" in news_text
    assert "newest_fundamental_evidence" in news_text
    assert "executable_authority=false" in news_text
    assert "source_url=https://example.invalid/news-01" not in news_text


def test_external_audit_import_is_saved_as_non_executable_note(tmp_path, monkeypatch) -> None:
    payload = {
        "schema_version": "1.0",
        "review_date": "2026-06-26",
        "overall_view": "neutral",
        "portfolio_actions": [
            {
                "etf_id": "VWCE",
                "action": "manual_review",
                "conviction": 0.6,
                "reason_short": "Policy violation requires review.",
                "main_supporting_metrics": ["target_policy_violation"],
                "main_risks": ["concentration"],
                "blocked_by": ["target_policy_violation"],
                "manual_checks": ["lower target or change policy limit"],
            }
        ],
        "ignored_signals": [],
        "risk_flags": [],
        "model_audit": {
            "toto_usefulness": "unavailable",
            "timesfm_usefulness": "unavailable",
            "baseline_comparison": "baseline only",
            "overfitting_concerns": [],
        },
        "dashboard_notes": ["Audit commentary only."],
    }
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(import_module, "CHATGPT_IMPORTS_DIR", tmp_path)

    audit = import_module.import_audit_json(path, load_config())
    saved = json.loads((tmp_path / f"chatgpt_audit_{audit.review_date}.json").read_text(encoding="utf-8"))

    assert saved["executable_authority"] is False
    assert saved["source"] == str(path)


def _synthetic_holdings_from_weights(prices: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    latest = prices.sort_values("date").groupby("etf_id").tail(1).set_index("etf_id")
    rows: list[dict[str, object]] = []
    for etf_id, weight in weights.items():
        price = float(latest.loc[etf_id, "adjusted_close"])
        market_value = 10_000.0 * float(weight)
        rows.append(
            {
                "as_of_date": pd.Timestamp("2026-06-26").date(),
                "etf_id": etf_id,
                "units": market_value / price,
                "market_price": price,
                "market_value_eur": market_value,
                "current_weight": float(weight),
                "source": "test",
            }
        )
    return pd.DataFrame(rows)
