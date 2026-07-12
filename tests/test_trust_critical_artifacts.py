from __future__ import annotations

import json
import zipfile
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
from etf_cockpit.signals.simple_scores import SimpleScoreComponent, build_simple_instrument_scores, simple_scoreboard_frame


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

    assert {"instrument_id", "final_combined_score_10", "final_action"} <= set(history.columns)
    assert {"component_name", "score_available", "na_reason"} <= set(metrics.columns)
    assert "source_id" in components.columns
    assert components["source_id"].astype(str).str.strip().ne("").all()
    assert {"source_authority", "score_eligible", "executable_authority"} <= set(ledger.columns)
    assert ledger["executable_authority"].eq(False).all()
    assert {"direction", "driver_text", "freshness_status"} <= set(drivers.columns)
    assert "VWCE" in set(history["instrument_id"])


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
    expected_ids = set(state.snapshot.config.universe.enabled_ids)
    actual_ids = [str(item["etf_id"]) for item in portfolio_summary["holdings"]]
    assert set(actual_ids) == expected_ids
    assert len(actual_ids) == len(set(actual_ids))
    assert {"etf_id", "name", "current_weight", "target_weight", "drift", "role"} <= set(portfolio_summary["holdings"][0])
    assert len(actual_ids) == len(expected_ids)
    assert "evidence_export/trust_critical_manifest.json" in names
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
    required = {item["path"]: item for item in manifest["required"]}
    assert required["evidence_export/candle_context.csv"]["unavailable_marker"] == "evidence_export/candle_context_unavailable.txt"
    assert required["evidence_export/source_conflicts.csv"]["allow_unavailable"] is True
    assert required["01_portfolio_summary.json"]["allow_unavailable"] is False
    assert "combined_review_packet.md" in manifest["checksums"]
