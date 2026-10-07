from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.components.shell.page_view import PageView
from etf_cockpit.app.pages.feature_catalogue import feature_catalogue_page
from tests.ui._p4_helpers import all_text, card_titles

TITLES = {"Feature definitions", "Feature coverage", "Training data preview", "Targets and leakage controls"}


def _state(features):
    return SimpleNamespace(snapshot=SimpleNamespace(features=features), last_message="")


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-07-08", "2026-07-09"],
            "etf_id": ["VWCE", "VWCE"],
            "return_1d_log": [0.01, None],
            "momentum_60d": [0.1, 0.2],
        }
    )


def test_sample_data_renders_every_card_and_returns_page_view() -> None:
    view = feature_catalogue_page(None, _state(_features()))
    assert isinstance(view, PageView)
    assert view.chrome.title == "Feature Catalogue"
    assert TITLES <= set(card_titles(view.body))
    text = all_text(view.body)
    assert "features registered" in text
    assert "return_1d_log" in text
    assert "Traceback" not in text


def test_empty_features_show_unavailable_states_not_zeros() -> None:
    view = feature_catalogue_page(None, _state(pd.DataFrame()))
    text = all_text(view.body)
    assert "Unavailable" in text
    assert "Coverage unavailable" in text
    assert "No preview rows" in text


def test_lowest_coverage_insight_names_the_feature() -> None:
    view = feature_catalogue_page(None, _state(_features()))
    assert "has the lowest coverage" in all_text(view.body)
