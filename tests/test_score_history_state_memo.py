from __future__ import annotations

import pandas as pd

from etf_cockpit.data import score_history


def test_classification_state_read_once_per_instrument(monkeypatch, tmp_path):
    calls: list[str] = []

    def fake_state(root, instrument_id):
        calls.append(instrument_id)
        return {"status": "available", "invalidation_token": "tok", "invalidated_score_keys": ()}

    monkeypatch.setattr(score_history, "classification_score_state", fake_state)
    frame = pd.DataFrame({"instrument_id": ["A", "B", "A", "A", "B"], "classification_invalidation_hash": ["tok"] * 5})
    result = score_history.project_classification_score_frame(frame, root=tmp_path)
    assert sorted(calls) == ["A", "B"]
    assert list(result["classification_dependency_status"]) == ["current"] * 5
