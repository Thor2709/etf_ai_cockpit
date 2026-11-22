from __future__ import annotations

import pandas as pd

from etf_cockpit.models import forecast_scores


def test_forecast_row_filter_checks_each_source_file_once(monkeypatch) -> None:
    calls: list[str] = []

    def fake_match(path, *_args) -> bool:
        calls.append(str(path))
        return str(path) == "a.csv"

    monkeypatch.setattr(forecast_scores, "_forecast_cache_matches", fake_match)
    rows = pd.DataFrame({"source_file": ["a.csv", "b.csv", "a.csv", "b.csv", "a.csv"], "etf_id": list("ABCDE")})

    filtered = forecast_scores.filter_forecasts_for_universe(rows, "universe-1", "settings-1")

    assert filtered.equals(rows.loc[[0, 2, 4]])
    assert sorted(calls) == ["a.csv", "b.csv"]
