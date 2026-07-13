from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages.backtests import _news_validation_warning
from etf_cockpit.app.pages.dashboard import _news_digest


def _text_values(node: object) -> list[str]:
    values: list[str] = []
    for attribute in ("value", "text"):
        value = getattr(node, attribute, None)
        if value:
            values.append(str(value))
    for attribute in ("controls", "content", "rows", "cells"):
        children = getattr(node, attribute, None)
        if children is None:
            continue
        if isinstance(children, (list, tuple)):
            for child in children:
                values.extend(_text_values(child))
        else:
            values.extend(_text_values(children))
    return values


def test_dashboard_news_digest_shows_unavailable_or_canonical_context(monkeypatch) -> None:
    import etf_cockpit.app.pages.dashboard as dashboard

    monkeypatch.setattr(dashboard, "load_news_items", lambda _path: pd.DataFrame([
        {"headline": "Headline", "provider_name": "Provider", "published_at": "2026-07-10T10:00:00+00:00", "timestamp_status": "valid_context"},
    ]))
    rendered = "\n".join(_text_values(_news_digest(None, SimpleNamespace())))
    assert "News & context digest" in rendered
    assert "Headline" in rendered
    assert "context_only=true" in rendered
    assert "executable_authority=false" in rendered


def test_backtests_news_warning_surfaces_rejected_rows(tmp_path, monkeypatch) -> None:
    import etf_cockpit.app.pages.backtests as backtests

    path = tmp_path / "news_timestamp_validation.parquet"
    pd.DataFrame([{"timestamp_status": "current_only_revised", "backtest_eligible": False}]).to_parquet(path, index=False)
    monkeypatch.setattr(backtests, "NEWS_TIMESTAMP_VALIDATION_PATH", path)
    rendered = "\n".join(_text_values(_news_validation_warning()))
    assert "excluded from backtests" in rendered
    assert "current_only_revised" in rendered
