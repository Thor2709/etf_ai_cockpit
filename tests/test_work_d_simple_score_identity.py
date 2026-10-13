from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.core.config import load_config
from etf_cockpit.signals import simple_scores as scores_module


@pytest.fixture
def local_scores(monkeypatch):
    config = load_config()
    identities = [item for item in config.universe.etfs if item.id == "AURG"]
    assert len(identities) == 1
    config = config.model_copy(update={"universe": config.universe.model_copy(update={"etfs": identities})})
    monkeypatch.setattr(scores_module, "load_latest_candidate_report", lambda: (pd.DataFrame(), None))
    monkeypatch.setattr(scores_module, "_latest_candidate_input_frame", lambda: pd.DataFrame())
    monkeypatch.setattr(scores_module, "load_forecast_history", lambda: pd.DataFrame())
    monkeypatch.setattr(scores_module, "_native_sparebank_score", lambda _: (None, "Scorecard pending"))
    return config


def candidate(instrument_id="AURG"):
    return {
        "instrument_id": instrument_id,
        "name": "Aurskog Sparebank",
        "isin": "needs_verification",
        "yahoo_symbol": "AURG.OL",
        "currency": "NOK",
        "analysis_tier": "sparebanken",
        "instrument_type": "equity_certificate",
        "data_policy": "yfinance_only",
    }


def build(config):
    return scores_module.build_simple_instrument_scores(config, [], pd.DataFrame(), pd.DataFrame())


def test_upgraded_owner_raw_candidate_cannot_duplicate_verified_config(local_scores, monkeypatch):
    # The owner keeps the old CSV; no refresh or migration is required.
    monkeypatch.setattr(scores_module, "_latest_candidate_input_frame", lambda: pd.DataFrame([candidate("aurg")]))
    scores = build(local_scores)
    assert [(score.instrument_key, score.isin) for score in scores] == [("configured:AURG", "NO0006001601")]


def test_report_overlap_is_unique_across_groups_and_preserves_config(local_scores, monkeypatch):
    row = candidate()
    row.update(instrument_type="stock", analysis_tier="secondary")
    monkeypatch.setattr(scores_module, "_latest_candidate_input_frame", lambda: pd.DataFrame([row]))
    monkeypatch.setattr(scores_module, "load_latest_candidate_report", lambda: (pd.DataFrame([row]), None))
    grouped = scores_module.group_simple_scores(build(local_scores))
    records = [score for group in grouped for score in group.scores]
    assert len(records) == 1
    assert records[0].source_group == "Sparebanken"
    assert records[0].isin == "NO0006001601"


def test_unknown_config_isin_stays_unverified(local_scores, monkeypatch):
    identity = local_scores.universe.etfs[0].model_copy(update={"isin": None, "isin_status": "needs_verification"})
    config = local_scores.model_copy(update={"universe": local_scores.universe.model_copy(update={"etfs": [identity]})})
    monkeypatch.setattr(scores_module, "_latest_candidate_input_frame", lambda: pd.DataFrame([candidate()]))
    scores = build(config)
    assert len(scores) == 1
    assert scores[0].isin == "needs_verification"
    assert scores_module.simple_scoreboard_frame(scores).iloc[0]["isin_status"] == "needs_verification"


def test_candidate_only_repeated_id_is_shown_once_without_inventing_isin(local_scores):
    scores = scores_module.build_candidate_simple_scores(pd.DataFrame([candidate(), candidate("aurg")]), pd.DataFrame())
    assert len(scores) == 1
    assert scores[0].instrument_key == "candidate:AURG"
    assert scores[0].isin == "needs_verification"


def test_repeated_signals_do_not_duplicate_configured_score(local_scores, monkeypatch):
    monkeypatch.setattr(scores_module, "_native_sparebank_score", lambda _: (7.0, "Stored scorecard"))
    signal = SimpleNamespace(etf_id="AURG")
    scores = scores_module.build_universe_simple_scores(local_scores, [signal, signal], pd.DataFrame(), pd.DataFrame())
    assert len(scores) == 1
    assert scores[0].isin == "NO0006001601"
