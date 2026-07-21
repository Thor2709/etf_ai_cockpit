from __future__ import annotations

from datetime import date
import json
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.models import forecast_scores
from etf_cockpit.models.forecast_scores import filter_forecasts_for_universe, latest_forecast_file, load_latest_forecasts
from etf_cockpit.core.config import load_config
from etf_cockpit import services


def test_feature_output_is_published_only_after_settings_bound_manifest_reservation(monkeypatch) -> None:
    events: list[tuple[str, str]] = []
    identity = {"settings_revision": "a" * 64}
    monkeypatch.setattr(services, "current_settings_identity", lambda: identity)
    monkeypatch.setattr(services, "settings_bound_run_id", lambda run_id, *, settings_identity: f"{run_id}__s{settings_identity['settings_revision'][:8]}")
    monkeypatch.setattr(services, "ensure_run_manifest", lambda run_id, _dependencies, *, settings_identity: events.append(("manifest", f"{run_id}:{settings_identity['settings_revision'][:8]}")))
    monkeypatch.setattr(services, "compute_features", lambda _frame, benchmark_etf_id=None: pd.DataFrame({"value": [1]}))
    monkeypatch.setattr(services, "write_features", lambda _frame: events.append(("output", "features")))

    services.FeatureService(load_config()).compute_features(prices=pd.DataFrame())

    assert events == [("manifest", "features_latest__saaaaaaaa:aaaaaaaa"), ("output", "features")]


def test_forecast_output_is_published_only_after_settings_bound_manifest_reservation(monkeypatch) -> None:
    events: list[tuple[str, str]] = []
    service = services.ForecastService(load_config())
    identity = {"settings_revision": "b" * 64}
    monkeypatch.setattr(services, "current_settings_identity", lambda: identity)
    monkeypatch.setattr(services, "settings_bound_run_id", lambda run_id, *, settings_identity: f"{run_id}__s{settings_identity['settings_revision'][:8]}")
    monkeypatch.setattr(services, "ensure_run_manifest", lambda run_id, _dependencies, *, settings_identity: events.append(("manifest", f"{run_id}:{settings_identity['settings_revision'][:8]}")))
    monkeypatch.setattr(services, "baseline_forecast", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "_run_timesfm_forecasts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "_run_toto_forecasts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "_write_forecasts", lambda *_args, settings_revision, **_kwargs: events.append(("output", f"forecasts:{settings_revision[:8]}")))
    prices = pd.DataFrame({"date": ["2026-07-21"], "etf_id": ["VWCE"], "adjusted_close": [100.0]})

    service.run_forecasts(date(2026, 7, 21), ["VWCE"], prices=prices)

    assert events == [("manifest", "forecast_20260721__sbbbbbbbb:bbbbbbbb"), ("output", "forecasts:bbbbbbbb")]


def test_backtest_output_is_published_only_after_settings_bound_manifest_reservation(tmp_path, monkeypatch) -> None:
    events: list[tuple[str, str]] = []
    report = SimpleNamespace(
        results=pd.DataFrame({"strategy_name": ["quality_momentum"]}),
        equity_curves=pd.DataFrame({"value": [1.0]}),
        trade_log=pd.DataFrame(),
        signal_log=pd.DataFrame(),
        quality_momentum_evidence=pd.DataFrame(),
        metadata={},
        ai_added_value=False,
    )
    monkeypatch.setattr(services, "BACKTESTS_DIR", tmp_path)
    monkeypatch.setattr(services, "load_prices", lambda: pd.DataFrame())
    monkeypatch.setattr(services, "load_fundamental_evidence", lambda: pd.DataFrame())
    monkeypatch.setattr(services, "run_backtest", lambda *_args, **_kwargs: report)
    identity = {"settings_revision": "c" * 64}
    monkeypatch.setattr(services, "current_settings_identity", lambda: identity)
    monkeypatch.setattr(services, "settings_bound_run_id", lambda run_id, *, settings_identity: f"{run_id}__s{settings_identity['settings_revision'][:8]}")
    monkeypatch.setattr(services, "ensure_run_manifest", lambda run_id, _dependencies, *, settings_identity: events.append(("manifest", f"{run_id}:{settings_identity['settings_revision'][:8]}")))
    monkeypatch.setattr(services, "atomic_write_group", lambda _requests: events.append(("output", "backtest")))
    monkeypatch.setattr(services, "_write_universe_cache_metadata", lambda _path, _universe, settings_revision: events.append(("metadata", settings_revision[:8])))
    monkeypatch.setattr(services, "append_jsonl", lambda *_args, **_kwargs: None)

    services.BacktestService(load_config(), universe_revision="revision").run_backtest()

    assert events[:2] == [("manifest", "backtest__scccccccc:cccccccc"), ("output", "backtest")]
    assert {event for event in events if event[0] == "metadata"} == {("metadata", "cccccccc")}


def test_feature_run_threads_one_identity_when_settings_change_between_id_and_manifest(monkeypatch) -> None:
    captured = {"settings_revision": "d" * 64}
    current = {"settings_revision": "e" * 64}
    seen: list[object] = []
    monkeypatch.setattr(services, "current_settings_identity", lambda: captured)

    def allocate(run_id, *, settings_identity):
        seen.append(settings_identity)
        captured["external_current_after_allocation"] = current["settings_revision"]
        return f"{run_id}__s{settings_identity['settings_revision'][:8]}"

    def reserve(_run_id, _dependencies, *, settings_identity):
        seen.append(settings_identity)

    monkeypatch.setattr(services, "settings_bound_run_id", allocate)
    monkeypatch.setattr(services, "ensure_run_manifest", reserve)
    monkeypatch.setattr(services, "compute_features", lambda _frame, benchmark_etf_id=None: pd.DataFrame({"value": [1]}))
    monkeypatch.setattr(services, "write_features", lambda _frame: None)

    services.FeatureService(load_config()).compute_features(prices=pd.DataFrame())

    assert seen[0] is seen[1] is captured
    assert seen[1]["settings_revision"] == "d" * 64


def test_forecast_cache_rejects_a_prior_settings_revision(tmp_path) -> None:
    output = tmp_path / "forecast_results_20260721.csv"
    output.write_text("etf_id,expected_return\nVWCE,0.01\n", encoding="utf-8")
    output.with_name(f"{output.name}.meta.json").write_text(
        '{"schema_version":2,"settings_revision":"old-settings","universe_revision":"universe-1"}',
        encoding="utf-8",
    )

    matching = load_latest_forecasts(
        directory=tmp_path,
        universe_revision="universe-1",
        settings_revision="old-settings",
    )
    stale = load_latest_forecasts(
        directory=tmp_path,
        universe_revision="universe-1",
        settings_revision="new-settings",
    )

    assert not matching.empty
    assert stale.empty


def test_forecast_file_selection_captures_one_settings_revision(tmp_path, monkeypatch) -> None:
    old = tmp_path / "forecast_results_old.csv"
    new = tmp_path / "forecast_results_new.csv"
    old.write_text("etf_id\nOLD\n", encoding="utf-8")
    new.write_text("etf_id\nNEW\n", encoding="utf-8")
    old.with_name(f"{old.name}.meta.json").write_text(
        '{"settings_revision":"revision-a","universe_revision":"universe-1"}',
        encoding="utf-8",
    )
    new.with_name(f"{new.name}.meta.json").write_text(
        '{"settings_revision":"revision-b","universe_revision":"universe-1"}',
        encoding="utf-8",
    )
    old.touch()
    revisions = iter(("revision-a", "revision-b"))
    calls: list[str] = []

    def changing_revision() -> str:
        value = next(revisions)
        calls.append(value)
        return value

    monkeypatch.setattr(forecast_scores, "current_settings_revision", changing_revision)

    selected = latest_forecast_file(directory=tmp_path, universe_revision="universe-1")

    assert selected == old
    assert calls == ["revision-a"]


def test_forecast_row_filter_captures_one_settings_revision(tmp_path, monkeypatch) -> None:
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    for path, revision in ((first, "revision-a"), (second, "revision-b")):
        path.write_text("etf_id\nA\n", encoding="utf-8")
        path.with_name(f"{path.name}.meta.json").write_text(
            json.dumps({"settings_revision": revision, "universe_revision": "universe-1"}),
            encoding="utf-8",
        )
    revisions = iter(("revision-a", "revision-b"))
    calls: list[str] = []

    def changing_revision() -> str:
        value = next(revisions)
        calls.append(value)
        return value

    monkeypatch.setattr(forecast_scores, "current_settings_revision", changing_revision)
    rows = pd.DataFrame({"source_file": [str(first), str(second)], "etf_id": ["A", "B"]})

    filtered = filter_forecasts_for_universe(rows, "universe-1")

    assert filtered["source_file"].tolist() == [str(first)]
    assert calls == ["revision-a"]
