from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.router import PAGES
from etf_cockpit.app.state import AppState
from etf_cockpit.chatgpt_bridge import export_pack as export_module
from etf_cockpit.chatgpt_bridge.audit_packet import validate_audit_archive
from etf_cockpit.core.config import load_config
from etf_cockpit.core import session_log
from etf_cockpit.data import trust_artifacts as trust
from etf_cockpit.services import build_snapshot
from etf_cockpit import services as services_module
from etf_cockpit.signals.simple_scores import SimpleScoreComponent, build_simple_instrument_scores, simple_scoreboard_frame


def test_audit_allocation_includes_enabled_manual_review_instruments() -> None:
    normal = SimpleNamespace(
        id="NORMAL",
        name="Normal instrument",
        role="watchlist",
        region="Europe",
        sector="Technology",
        currency="EUR",
    )
    manual = SimpleNamespace(
        id="MANUAL",
        name="Manual review instrument",
        role="watchlist",
        region="Europe",
        sector="Derivatives",
        currency="EUR",
    )
    config = SimpleNamespace(
        universe=SimpleNamespace(
            etfs=[normal, manual],
            enabled_ids=["NORMAL"],
            configured_enabled_ids=["NORMAL", "MANUAL"],
            by_id=lambda: {"NORMAL": normal, "MANUAL": manual},
        ),
        targets=SimpleNamespace(base_currency="EUR"),
    )
    allocation = pd.DataFrame(
        [{
            "etf_id": "NORMAL",
            "name": "Normal instrument",
            "current_weight": 0.2,
            "target_weight": 0.2,
            "drift": 0.0,
            "role": "watchlist",
            "region": "Europe",
            "sector": "Technology",
            "currency": "EUR",
        }]
    )

    rows = export_module._audit_portfolio_holdings(config, allocation)

    assert [row["etf_id"] for row in rows] == ["NORMAL", "MANUAL"]
    assert rows[1]["current_weight"] == 0.0
    assert rows[1]["target_weight"] == 0.0


def test_audit_allocation_preserves_untargeted_enabled_holding_weight() -> None:
    manual = SimpleNamespace(
        id="MANUAL",
        name="Manual review instrument",
        role="watchlist",
        region="Europe",
        sector="Derivatives",
        currency="EUR",
    )
    config = SimpleNamespace(
        universe=SimpleNamespace(
            etfs=[manual],
            enabled_ids=[],
            configured_enabled_ids=["MANUAL"],
            by_id=lambda: {"MANUAL": manual},
        ),
        targets=SimpleNamespace(base_currency="EUR"),
    )
    allocation = pd.DataFrame(columns=["etf_id", "current_weight", "target_weight", "drift"])
    holdings = pd.DataFrame([{"etf_id": "MANUAL", "current_weight": 0.35}])

    rows = export_module._audit_portfolio_holdings(config, allocation, holdings)

    assert rows == [{
        "etf_id": "MANUAL",
        "name": "Manual review instrument",
        "current_weight": 0.35,
        "target_weight": 0.0,
        "drift": 0.35,
        "role": "watchlist",
        "region": "Europe",
        "sector": "Derivatives",
        "currency": "EUR",
    }]


def test_snapshot_retains_configured_manual_holdings_for_audit_export(monkeypatch) -> None:
    config = SimpleNamespace(
        universe=SimpleNamespace(
            enabled_ids=[],
            configured_enabled_ids=["MANUAL"],
        )
    )
    holdings = pd.DataFrame([{"etf_id": "MANUAL", "current_weight": 0.35}])

    class FakeDataService:
        def __init__(self, _config):
            pass

        def update_prices(self, force_sample=False):
            return None

        def load_prices(self):
            return pd.DataFrame(columns=["etf_id", "date"])

        def validate_prices(self, prices, holdings=None):
            return SimpleNamespace(as_of_date=None, issues=[])

    monkeypatch.setattr(services_module, "configure_logging", lambda: None)
    monkeypatch.setattr(services_module, "ensure_project_dirs", lambda: None)
    monkeypatch.setattr(services_module, "load_config", lambda: config)
    monkeypatch.setattr(services_module, "DataService", FakeDataService)
    monkeypatch.setattr(services_module, "load_holdings", lambda: holdings.copy())
    monkeypatch.setattr(services_module, "_current_universe_revision", lambda: "revision")
    monkeypatch.setattr(services_module, "model_availability", lambda _config: {"timesfm": False, "toto": False})
    monkeypatch.setattr(services_module, "model_diagnostics", lambda _config: [])
    monkeypatch.setattr(services_module, "load_latest_forecasts", lambda **_kwargs: pd.DataFrame())

    snapshot = services_module._build_snapshot()

    assert snapshot.holdings.to_dict(orient="records") == [{"etf_id": "MANUAL", "current_weight": 0.35}]


def test_correlation_cluster_writer_preserves_nominal_window_and_observed_sample(tmp_path, monkeypatch) -> None:
    from etf_cockpit.data import trust_artifacts as trust
    import numpy as np

    monkeypatch.setattr(trust, "CORRELATION_CLUSTERS_PATH", tmp_path / "correlation_clusters.parquet")
    index = pd.date_range("2026-01-01", periods=120, freq="D")
    prices = pd.DataFrame({"A": 100.0 * np.exp(np.linspace(0.0, 0.2, len(index))), "B": 100.0 * np.exp(np.linspace(0.0, -0.1, len(index)))}, index=index)

    trust.write_correlation_clusters(
        prices,
        {"A": {"theme": "AI"}, "B": {"theme": "Bonds"}},
        window=120,
        ranked_instruments=["A", "B"],
        weights={"A": 1.0, "B": 1.0},
    )
    persisted = pd.read_parquet(trust.CORRELATION_CLUSTERS_PATH)

    assert not persisted.empty
    assert set(persisted["calculation_window_days"]) == {120}
    assert set(persisted["sample_size"]) == {119}
    assert set(persisted["top_ranked_theme_concentration"]) == {0.5}
    assert set(persisted["top_ranked_theme_warning"]) == {"theme_concentration_warning"}


def test_session_log_clears_records_start_and_redacts_secrets(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "session.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)

    session_log.init_session_log(clear=True, port=8550, route="/")
    session_log.log_event(
        event_type="button_click",
        button_label="Secret test",
        input_summary={"api_key": "SHOULD_NOT_APPEAR", "normal": "ok"},
        user_message="token=SHOULD_NOT_APPEAR",
    )

    text = log_path.read_text(encoding="utf-8")
    events = session_log.read_session_events(limit=10)

    assert "session_start" in text
    assert "button_click" in text
    assert "SHOULD_NOT_APPEAR" not in text
    assert "***redacted***" in text
    assert events[0]["event_type"] == "session_start"


def test_session_log_redacts_nested_secret_values_without_dropping_event(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "session.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)

    session_log.init_session_log(clear=True, port=8550, route="/")
    session_log.log_event(event_type="nested_secret", input_summary={"api_key": {"nested": "secret"}, "ok": True})

    events = session_log.read_session_events(limit=10)
    nested = next(event for event in events if event["event_type"] == "nested_secret")
    assert nested["input_summary"]["api_key"] == "***redacted***"


def test_session_log_redacts_env_access_and_bearer_secret_forms(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "session.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)

    session_log.init_session_log(clear=True, port=8550, route="/")
    session_log.log_event(
        event_type="secret_forms",
        input_summary={
            "OPENAI_API_KEY": "SHOULD_NOT_APPEAR",
            "authorization": "Bearer SHOULD_NOT_APPEAR",
        },
        user_message="OPENAI_API_KEY=SHOULD_NOT_APPEAR access_token=SHOULD_NOT_APPEAR client_secret=SHOULD_NOT_APPEAR",
    )

    text = log_path.read_text(encoding="utf-8")

    assert "SHOULD_NOT_APPEAR" not in text
    assert text.count("***redacted***") >= 4


def test_session_log_redacts_json_string_secret_forms(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "session.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)

    session_log.init_session_log(clear=True, port=8550, route="/")
    session_log.log_event(
        event_type="json_secret_forms",
        user_message=(
            '{"authorization":"Bearer SHOULD_NOT_APPEAR",'
            '"OPENAI_API_KEY":"SHOULD_NOT_APPEAR",'
            '"access_token":"SHOULD_NOT_APPEAR",'
            '"client_secret":"SHOULD_NOT_APPEAR"}'
        ),
    )

    text = log_path.read_text(encoding="utf-8")

    assert "SHOULD_NOT_APPEAR" not in text
    assert "Bearer ***redacted***" in text


def test_diagnostics_ui_displays_redacted_exception_fingerprint(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app.pages.diagnostics import diagnostics_page

    log_path = tmp_path / "session.jsonl"
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log_path)
    session_log.init_session_log(clear=True, port=8550, route="/diagnostics")
    try:
        raise RuntimeError("api_key=SHOULD_NOT_APPEAR")
    except RuntimeError as exc:
        session_log.log_exception(
            event_type="activity_failed",
            exc=exc,
            operation="test_failure",
            user_message="Controlled failure",
        )
    failure = next(event for event in session_log.read_session_events(limit=10) if event["event_type"] == "activity_failed")
    assert failure["exception_type"] == "RuntimeError"
    assert failure["traceback_fingerprint"]
    assert "SHOULD_NOT_APPEAR" not in log_path.read_text(encoding="utf-8")

    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = type("Page", (), {})()

    def text_values(control):
        value = getattr(control, "value", None)
        if value:
            yield str(value)
        for attribute in ("controls", "content"):
            child = getattr(control, attribute, None)
            children = child if isinstance(child, (list, tuple)) else (child,) if child is not None else ()
            for item in children:
                yield from text_values(item)

    rendered_text = "\n".join(text_values(diagnostics_page(page, state)))
    assert "fingerprint=" in rendered_text
    assert "exception=" in rendered_text
    assert "SHOULD_NOT_APPEAR" not in rendered_text


def test_static_trust_artifacts_cover_providers_and_identity() -> None:
    config = load_config()
    trust.refresh_static_trust_artifacts(config)

    providers = pd.read_parquet(trust.PROVIDER_PROBE_PATH)
    identity = pd.read_parquet(trust.IDENTITY_PATH)
    conflicts = pd.read_parquet(trust.SOURCE_CONFLICTS_PATH)

    assert {"provider_name", "source_authority", "status", "executable_authority"} <= set(providers.columns)
    assert {"yfinance", "sec_edgar", "fred", "stooq", "rss"} <= set(providers["provider_name"])
    assert providers["executable_authority"].eq(False).all()
    yfinance_rows = providers[providers["provider_name"] == "yfinance"]
    assert not yfinance_rows.empty
    assert yfinance_rows["status"].ne("ok").all()
    assert identity.shape[0] >= 45
    assert {"VWCE", "UCG", "AIR", "MSFT", "RABO"} <= set(identity["instrument_id"])
    assert identity["executable_authority"].eq(False).all()
    assert {"field_name", "resolution_status", "requires_manual_review"} <= set(conflicts.columns)


def test_news_inventory_refresh_preserves_canonical_clean_evidence(tmp_path, monkeypatch) -> None:
    news_path = tmp_path / "news_context.parquet"
    canonical = pd.DataFrame([{
        "news_id": "news-1",
        "instrument_id": "MSFT",
        "headline": "MSFT shares rise after results",
        "source_url": "https://example.invalid/news-1",
        "provider_name": "fixture-provider",
        "published_at": "2026-07-10T10:00:00+00:00",
        "ingested_at": "2026-07-10T10:05:00+00:00",
        "credibility": "high",
        "instrument_mapping_method": "ticker",
        "available_at_decision_time": True,
        "timestamp_status": "valid_context",
        "backtest_eligible": True,
        "context_only": True,
        "executable_authority": False,
        "raw_path": "raw/news-1.json",
        "item_checksum": "checksum-1",
    }])
    canonical.to_parquet(news_path, index=False)
    monkeypatch.setattr(trust, "NEWS_CONTEXT_PATH", news_path)

    refreshed = trust._news_context_inventory(pd.DataFrame())
    trust._write_dual(refreshed, news_path)
    persisted = pd.read_parquet(news_path)

    required = {
        "news_id", "instrument_id", "headline", "source_url", "provider_name",
        "published_at", "ingested_at", "credibility", "instrument_mapping_method",
        "available_at_decision_time", "timestamp_status", "backtest_eligible",
        "context_only", "executable_authority", "raw_path", "path",
    }
    assert required <= set(persisted.columns)
    row = persisted.iloc[0]
    assert row["headline"] == "MSFT shares rise after results"
    assert row["credibility"] == "high"
    assert row["instrument_mapping_method"] == "ticker"
    assert bool(row["available_at_decision_time"]) is True
    assert row["timestamp_status"] == "valid_context"
    assert bool(row["backtest_eligible"]) is True
    assert bool(row["context_only"]) is True
    assert bool(row["executable_authority"]) is False
    assert row["path"] == row["raw_path"] == "raw/news-1.json"


def test_score_artifacts_write_history_components_and_drivers() -> None:
    snapshot = build_snapshot()
    scores = build_simple_instrument_scores(snapshot.config, snapshot.signals, snapshot.forecasts, snapshot.prices)
    scoreboard = simple_scoreboard_frame(scores)

    paths = trust.write_trust_artifacts_for_scores(snapshot.config, scores, scoreboard, snapshot.prices)

    history = pd.read_parquet(paths["score_history"])
    metrics = pd.read_parquet(paths["score_metric_history"])
    ledger = pd.read_parquet(paths["evidence_ledger"])
    components = pd.read_parquet(paths["score_components"])
    drivers = pd.read_parquet(paths["feature_drivers"])

    assert {
        "instrument_id",
        "final_combined_score_10",
        "final_action",
        "q10_expected_return",
        "q50_expected_return",
        "q90_expected_return",
        "net_expected_return",
        "expected_return_order_value_eur",
        "expected_return_cost_bps",
        "expected_return_cost_eur",
        "expected_return_distribution_version",
        "expected_return_source_dataset",
    } <= set(history.columns)
    assert {"component_name", "score_available", "na_reason"} <= set(metrics.columns)
    assert "source_id" in components.columns
    assert components["source_id"].astype(str).str.strip().ne("").all()
    assert {"source_authority", "score_eligible", "executable_authority"} <= set(ledger.columns)
    assert ledger["executable_authority"].eq(False).all()
    assert {"direction", "driver_text", "freshness_status"} <= set(drivers.columns)
    assert "VWCE" in set(history["instrument_id"])


def test_score_history_preserves_friction_adjusted_return_audit_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trust, "SCORE_HISTORY_PATH", tmp_path / "score_history.parquet")
    score = SimpleNamespace(
        display_id="VWCE",
        name="Vanguard FTSE All-World",
        final_score_10=7.0,
        warnings=[],
        components=[],
        q10_expected_return=-0.03,
        q50_expected_return=0.05,
        q90_expected_return=0.12,
        gross_expected_return=0.05,
        expected_return_horizon_days=60,
        net_q10_expected_return=-0.032,
        net_expected_return=0.048,
        net_q90_expected_return=0.118,
        expected_return_order_value_eur=1_000.0,
        expected_return_cost_bps=20.0,
        expected_return_cost_eur=2.0,
        expected_return_cost_ratio=24.0,
        expected_return_distribution_version="expected-return-distribution.v1",
        expected_return_source_dataset="forecast_return_distribution",
    )

    path = trust.append_score_history(
        [score],
        run_id="run-friction-return",
        created_at="2026-07-20T00:00:00Z",
        version_registry_signature="test-registry",
    )

    row = pd.read_parquet(path).iloc[0]
    assert row["q10_expected_return"] == -0.03
    assert row["q50_expected_return"] == 0.05
    assert row["q90_expected_return"] == 0.12
    assert row["net_expected_return"] == 0.048
    assert row["expected_return_order_value_eur"] == 1_000.0
    assert row["expected_return_cost_bps"] == 20.0
    assert row["expected_return_cost_eur"] == 2.0
    assert row["expected_return_cost_ratio"] == 24.0
    assert row["expected_return_distribution_version"] == "expected-return-distribution.v1"
    assert row["expected_return_source_dataset"] == "forecast_return_distribution"


def test_score_trust_writer_uses_same_top_ten_theme_cohort_as_scores(tmp_path, monkeypatch) -> None:
    import numpy as np

    from etf_cockpit.features.crowding import build_correlation_clusters

    output_names = (
        "EVIDENCE_LEDGER_PATH",
        "SCORE_COMPONENTS_PATH",
        "SCORE_HISTORY_PATH",
        "SCORE_METRIC_HISTORY_PATH",
        "FEATURE_DRIVERS_PATH",
        "CORRELATION_CLUSTERS_PATH",
        "BENCHMARK_ATTRIBUTION_PATH",
    )
    for name in output_names:
        monkeypatch.setattr(trust, name, tmp_path / f"{name.lower()}.parquet")
    monkeypatch.setattr(trust, "refresh_static_trust_artifacts", lambda config: {})
    monkeypatch.setattr(trust, "log_event", lambda **kwargs: None)

    instrument_ids = [f"AI_{index:02d}" for index in range(10)] + [f"BOND_{index:02d}" for index in range(10)]
    metadata = {
        instrument_id: {"sector": "Technology" if instrument_id.startswith("AI_") else "Defensive", "theme": "AI" if instrument_id.startswith("AI_") else "Bonds"}
        for instrument_id in instrument_ids
    }
    config = SimpleNamespace(
        universe=SimpleNamespace(
            etfs=[SimpleNamespace(id=instrument_id, **metadata[instrument_id]) for instrument_id in instrument_ids],
            enabled_ids=instrument_ids,
        )
    )
    index = pd.date_range("2026-01-01", periods=150, freq="D")
    rng = np.random.default_rng(18)
    returns = rng.normal(0.0005, 0.01, size=(len(index), len(instrument_ids)))
    prices = pd.DataFrame(100.0 * np.exp(np.cumsum(returns, axis=0)), index=index, columns=instrument_ids)
    scores = [
        SimpleNamespace(
            display_id=instrument_id,
            final_score_10=float(20 - rank),
            latest_date="2026-05-30",
            components=[],
            warnings=[],
        )
        for rank, instrument_id in enumerate(instrument_ids)
    ]

    expected = build_correlation_clusters(
        prices,
        metadata,
        ranked_instruments=instrument_ids[:10],
        weights={instrument_id: 1.0 for instrument_id in instrument_ids[:10]},
    )
    paths = trust.write_trust_artifacts_for_scores(config, scores, pd.DataFrame(), prices)
    persisted = pd.read_parquet(paths["correlation_clusters"])

    assert expected.top_ranked_theme_concentration == 1.0
    assert expected.top_ranked_theme_warning == "theme_concentration_warning"
    assert set(persisted["top_ranked_theme_concentration"]) == {expected.top_ranked_theme_concentration}
    assert set(persisted["top_ranked_theme_warning"]) == {expected.top_ranked_theme_warning}
    assert set(persisted["execution_allowed"]) == {False}


def test_production_score_history_replaces_complete_run_snapshot_when_scope_narrows(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trust, "SCORE_HISTORY_PATH", tmp_path / "score_history.parquet")
    first = [
        SimpleNamespace(display_id="A", final_score_10=7.0, latest_date="2026-07-10", components=[], warnings=[]),
        SimpleNamespace(display_id="B", final_score_10=6.0, latest_date="2026-07-10", components=[], warnings=[]),
    ]
    narrowed = [
        SimpleNamespace(display_id="A", final_score_10=8.0, latest_date="2026-07-10", components=[], warnings=[]),
    ]

    trust.append_score_history(first, run_id="run-scope", created_at="2026-07-10T00:00:00Z")
    trust.append_score_history(narrowed, run_id="run-scope", created_at="2026-07-10T00:00:00Z")

    history = pd.read_parquet(trust.SCORE_HISTORY_PATH)
    assert set(history["instrument_id"]) == {"A"}
    assert history["snapshot_hash"].nunique() == 1
    assert float(history.iloc[0]["final_combined_score_10"]) == 8.0


def test_production_wrapper_empty_snapshot_removes_supplied_run_only(tmp_path, monkeypatch) -> None:
    history_path = tmp_path / "score_history.parquet"
    metric_history_path = tmp_path / "score_metric_history.parquet"
    monkeypatch.setattr(trust, "SCORE_HISTORY_PATH", history_path)
    monkeypatch.setattr(trust, "SCORE_METRIC_HISTORY_PATH", metric_history_path)
    monkeypatch.setattr(trust, "EVIDENCE_LEDGER_PATH", tmp_path / "evidence_ledger.parquet")
    monkeypatch.setattr(trust, "SCORE_COMPONENTS_PATH", tmp_path / "score_components.parquet")
    monkeypatch.setattr(trust, "FEATURE_DRIVERS_PATH", tmp_path / "feature_drivers.parquet")
    monkeypatch.setattr(trust, "CORRELATION_CLUSTERS_PATH", tmp_path / "correlation_clusters.parquet")
    monkeypatch.setattr(trust, "BENCHMARK_ATTRIBUTION_PATH", tmp_path / "benchmark_attribution.parquet")
    monkeypatch.setattr(trust, "refresh_static_trust_artifacts", lambda config: {})

    fixed_now = datetime(2026, 7, 13, 12, 34, 56, tzinfo=timezone.utc)

    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(trust, "datetime", FixedDateTime)
    monkeypatch.setattr(trust.uuid, "uuid4", lambda: SimpleNamespace(hex="emptyrun"))

    generated_run_id = "score_20260713T123456_emptyrun"
    legacy_columns = ["run_id", "instrument_id", "final_action"]
    existing = pd.DataFrame(
        [
            {"run_id": generated_run_id, "instrument_id": "STALE", "final_action": "BUY"},
            {"run_id": "unrelated-run", "instrument_id": "KEEP", "final_action": "HOLD"},
        ],
        columns=legacy_columns,
    )
    trust._write_dual(existing, history_path)

    trust.write_trust_artifacts_for_scores(None, [], pd.DataFrame(), None)

    history = pd.read_parquet(history_path)
    assert list(history.columns) == legacy_columns
    assert set(history["run_id"]) == {"unrelated-run"}
    assert set(history["instrument_id"]) == {"KEEP"}
    assert set(pd.read_csv(history_path.with_suffix(".csv"))["run_id"]) == {"unrelated-run"}


def test_production_score_history_persists_real_dimensions_and_explicit_unavailable_values(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trust, "SCORE_HISTORY_PATH", tmp_path / "score_history.parquet")
    snapshot = build_snapshot()
    scores = build_simple_instrument_scores(snapshot.config, snapshot.signals, snapshot.forecasts, snapshot.prices)
    scoreboard = simple_scoreboard_frame(scores)

    paths = trust.write_trust_artifacts_for_scores(snapshot.config, scores, scoreboard, snapshot.prices)
    history = pd.read_parquet(paths["score_history"])

    assert history["rank"].notna().all()
    assert history["score_rank"].notna().all()
    assert history["warnings"].astype(str).str.strip().ne("").all()
    assert history["freshness_status"].astype(str).str.strip().ne("").all()
    assert history["model_availability"].astype(str).str.strip().ne("").all()
    assert history["forecast_status"].astype(str).str.strip().ne("").all()
    assert history["news_inventory"].notna().all()
    assert history["backtest_trust"].astype(str).str.strip().ne("").all()
    assert history["portfolio_risk"].astype(str).str.strip().ne("").all()
    assert history["execution_allowed"].eq(False).all()


def test_pending_model_label_persists_unavailable_without_model_row_or_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trust, "SCORE_HISTORY_PATH", tmp_path / "score_history.parquet")
    score = SimpleNamespace(
        display_id="PENDING",
        name="Pending instrument",
        final_score_10=5.0,
        latest_date="pending refresh",
        components=[],
        warnings=["pending_refresh"],
        model_authority_label="Model evidence pending",
        model_versions_used=None,
    )

    trust.append_score_history([score], run_id="pending-model", created_at="2026-07-10T00:00:00Z")

    row = pd.read_parquet(trust.SCORE_HISTORY_PATH).iloc[0]
    assert bool(row["model_available"]) is False
    assert row["model_availability"] == "unavailable"


def test_score_components_persist_non_executable_authority(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trust, "SCORE_COMPONENTS_PATH", tmp_path / "score_components.parquet")
    component = SimpleScoreComponent(
        "momentum",
        "Momentum",
        7.0,
        0.4,
        "OK",
        "",
        "",
        "",
        source_id="yfinance:prices",
        as_of_date="2026-07-10",
        freshness_status="ok",
    )
    score = SimpleNamespace(display_id="VWCE", latest_date="2026-07-10", components=[component])

    frame = pd.read_parquet(trust.write_score_components([score], run_id="run-authority", created_at="2026-07-10T00:00:00Z"))

    assert "executable_authority" in frame.columns
    assert frame["executable_authority"].eq(False).all()


def test_score_evidence_distinguishes_official_and_missing_sources(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trust, "EVIDENCE_LEDGER_PATH", tmp_path / "evidence_ledger.parquet")
    official = SimpleNamespace(
        key="filing_metric",
        score_10=8.0,
        status="OK",
        authority="high",
        source_id="sec_edgar:companyfacts",
        explanation="Official filing fact",
        why="Fixture-backed official source",
    )
    missing = SimpleNamespace(
        key="missing_metric",
        score_10=7.0,
        status="OK",
        authority="high",
        source_id="",
        explanation="Missing source fixture",
        why="Source is unavailable",
    )
    score = SimpleNamespace(display_id="MSFT", latest_date="2026-07-10", components=[official, missing])

    frame = pd.read_parquet(trust.write_evidence_ledger([score], run_id="run-source-gates", created_at="2026-07-10T00:00:00Z"))
    official_row = frame.loc[frame["component"] == "filing_metric"].iloc[0]
    missing_row = frame.loc[frame["component"] == "missing_metric"].iloc[0]

    assert official_row["source_authority"] == "official_regulator"
    assert bool(official_row["score_eligible"]) is True
    assert missing_row["source_authority"] == "unknown"
    assert bool(missing_row["score_eligible"]) is False


def test_model_score_evidence_is_advisory_and_not_score_eligible(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(trust, "EVIDENCE_LEDGER_PATH", tmp_path / "evidence_ledger.parquet")
    model = SimpleNamespace(
        key="baseline",
        score_10=7.0,
        status="OK",
        authority="low",
        source_id="model:baseline",
        explanation="Deterministic baseline confirmation",
        why="Advisory model evidence",
    )
    score = SimpleNamespace(display_id="VWCE", latest_date="2026-07-10", components=[model])

    frame = pd.read_parquet(trust.write_evidence_ledger([score], run_id="run-model-policy", created_at="2026-07-10T00:00:00Z"))
    row = frame.iloc[0]

    assert row["source_authority"] == "model_advisory"
    assert bool(row["score_eligible"]) is False


def test_trust_evidence_pages_are_registered() -> None:
    assert PAGES["/providers"][0] == "Provider Status"
    assert PAGES["/evidence"][0] == "Evidence Ledger"
    assert PAGES["/filings"][0] == "Filings & Statements"
    assert PAGES["/etf-disclosures"][0] == "ETF Disclosures"
    assert PAGES["/news-context"][0] == "News & Context"


def test_audit_export_includes_trust_critical_evidence_and_session_log(tmp_path, monkeypatch) -> None:
    session_log.init_session_log(clear=True, port=8550, route="/")
    session_log.log_event(event_type="button_click", button_label="Export audit packet", input_summary={"api_key": "SHOULD_NOT_APPEAR"})
    monkeypatch.setattr(export_module, "CHATGPT_EXPORTS_DIR", tmp_path / "audit_packets")
    statement_facts = tmp_path / "statement_facts.parquet"
    pd.DataFrame([{"instrument_id": "SEC_UNRESOLVED_3", "cik": "3", "source_id": "sec_edgar:3:assets"}]).to_parquet(statement_facts, index=False)
    monkeypatch.setattr(export_module, "STATEMENT_FACTS_PATH", statement_facts)

    state = AppState.load()
    zip_path = state.export_audit_packet()

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        combined_names = "\n".join(sorted(names))
        session_text = archive.read("evidence_export/session.jsonl").decode("utf-8")
        portfolio_summary = json.loads(archive.read("01_portfolio_summary.json"))

    assert "evidence_export/provider_probe_results.csv" in names
    assert "evidence_export/instrument_identity.csv" in names
    assert "evidence_export/evidence_ledger.csv" in names
    assert "evidence_export/score_components.csv" in names
    assert "evidence_export/score_history.csv" in names
    assert "evidence_export/source_conflicts.csv" in names
    assert "evidence_export/source_conflicts.json" in names
    assert "evidence_export/statement_facts.csv" in names
    expected_ids = set(state.snapshot.config.universe.configured_enabled_ids)
    actual_ids = [str(item["etf_id"]) for item in portfolio_summary["holdings"]]
    assert set(actual_ids) == expected_ids
    assert len(actual_ids) == len(set(actual_ids))
    assert {"etf_id", "name", "current_weight", "target_weight", "drift", "role"} <= set(portfolio_summary["holdings"][0])
    assert len(actual_ids) == len(expected_ids)
    assert "evidence_export/trust_critical_manifest.json" in names
    assert "evidence_export/decision_journal_summary.json" in names
    assert "evidence_export/macro_warehouse_summary.json" in names
    assert "evidence_export/data_catalogue_summary.json" in names
    assert "evidence_export/project_docs/plan.md" in names
    assert "evidence_export/project_docs/open.md" in names
    assert any(
        name == "evidence_export/candle_context_unavailable.txt" or name.startswith("evidence_export/candle_context.")
        for name in names
    )
    assert "SHOULD_NOT_APPEAR" not in session_text
    assert "SHOULD_NOT_APPEAR" not in combined_names

    report = validate_audit_archive(zip_path)
    assert report.valid is True
    with zipfile.ZipFile(zip_path) as archive:
        manifest = json.loads(archive.read("audit_manifest.json"))
        evidence_manifest = json.loads(archive.read("evidence_export/trust_critical_manifest.json"))
        statement_facts_bytes = archive.read("evidence_export/statement_facts.csv")
        decision_journal_summary = json.loads(archive.read("evidence_export/decision_journal_summary.json"))
        macro_summary = json.loads(archive.read("evidence_export/macro_warehouse_summary.json"))
        catalogue_summary = json.loads(archive.read("evidence_export/data_catalogue_summary.json"))
    required = {item["path"]: item for item in manifest["required"]}
    assert decision_journal_summary["private_notes_exported"] is False
    assert required["evidence_export/decision_journal_summary.json"]["source_authority"] == "user_record"
    assert macro_summary["execution_allowed"] is False
    assert catalogue_summary["execution_allowed"] is False
    assert required["evidence_export/candle_context.csv"]["unavailable_marker"] == "evidence_export/candle_context_unavailable.txt"
    assert required["evidence_export/source_conflicts.csv"]["allow_unavailable"] is True
    assert required["01_portfolio_summary.json"]["allow_unavailable"] is False
    assert "statement_facts.csv" in evidence_manifest["included"]
    assert evidence_manifest["checksums"]["statement_facts.csv"] == hashlib.sha256(statement_facts_bytes).hexdigest()
    assert "combined_review_packet.md" in manifest["checksums"]


def test_audit_evidence_uses_csv_mirror_when_parquet_is_missing(tmp_path) -> None:
    parquet_path = tmp_path / "fund_holdings.parquet"
    csv_path = tmp_path / "fund_holdings.csv"
    pd.DataFrame([{"instrument_id": "VWCE", "completeness": "partial", "score_eligible": False}]).to_csv(csv_path, index=False)
    evidence_root = tmp_path / "evidence_export"
    manifest = {"included": [], "missing": [], "checksums": {}}

    export_module._copy_evidence_file(parquet_path, evidence_root, manifest)

    assert (evidence_root / "fund_holdings.csv").exists()
    assert "fund_holdings.csv" in manifest["included"]
    assert not any("unavailable" in str(item) for item in manifest["missing"])
