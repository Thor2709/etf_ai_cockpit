"""LC1: isolate missing canonical scores without accepting inconsistent runs."""

from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.portfolio import paper_bots as bots
from etf_cockpit.portfolio import paper_bots_execution as execution
from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay
from tests.test_paper_bots import _NOW, _rows, _run_fixture, _scoreboard
from tests.test_paper_bots_execution import _allow, _book, _exec_config, _history_with_columns


def _decide(monkeypatch, root: Path, rows: list[dict], lane: str, board=None):
    if lane == "live":
        if board is None:
            board = _scoreboard(rows, _NOW)
            board["instrument_id"] = board["instrument_id"].str.strip()
            board["research_promotion_allowed"] = board["instrument_id"].isin({"AAA", "BBB"})
        result = _run_fixture(monkeypatch, root, rows, board, _NOW)
        return result, list(result.records)
    track = execution.replay_track(root, _exec_config())
    _allow(root, track)
    result = run_historical_replay(
        _NOW, root=root, history=pd.DataFrame(_history_with_columns(rows)),
        price_book=_book(known_at=_NOW), now=_NOW,
    )
    with TransactionalStore(track.store_root, read_only=True) as store:
        decisions = [dict(item.payload) for item in store.list(track.decision_type)]
    return result, decisions


@pytest.mark.parametrize("lane", ["live", "replay"])
@pytest.mark.parametrize("instrument_id,asset_type", [("AAA", "CERTIFICATE"), (" AAA ", "STOCK")])
def test_mixed_run_excludes_certificate_through_shared_validator(monkeypatch, tmp_path, lane, instrument_id, asset_type):
    rows = _rows(_NOW - timedelta(minutes=5))
    rows[0].update(
        instrument_id=instrument_id, asset_type=asset_type,
        formula_version="unavailable", formula_checksum="unavailable",
    )
    original = bots._validate_run
    calls = []

    def validate(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(bots, "_validate_run", validate)
    result, decisions = _decide(monkeypatch, tmp_path, rows, lane)
    assert calls == ["score-run"]
    assert result.status in {"available", "partial"}, (result.reason, result.warnings)
    assert {item["bot_family"] for item in decisions} == {"B0", "B1", "B2"}
    for item in decisions:
        assert item["status"] == "available"
        assert "AAA" not in item["targets"]
        assert {"instrument_id": "AAA", "reason": "no_canonical_score"} in item["skipped_instruments"]
        assert item["execution_allowed"] is False
    assert "BBB" in next(item for item in decisions if item["bot_family"] == "B1")["targets"]
    group, error = original("score-run", rows, _NOW)
    canonical, _ = original("score-run", rows[1:], _NOW)
    assert error is None and group.lineage_hash == canonical.lineage_hash
    assert rows[0]["formula_version"] == "unavailable"


@pytest.mark.parametrize("lane", ["live", "replay"])
def test_all_noncanonical_rows_fail_closed(monkeypatch, tmp_path, lane):
    rows = _rows(_NOW - timedelta(minutes=5))
    for row in rows:
        row.update(formula_version="unavailable", formula_checksum="unavailable")
    result, decisions = _decide(monkeypatch, tmp_path, rows, lane)
    assert result.status == "unavailable"
    assert not decisions or all(item["status"] == "unavailable" and not item["targets"] for item in decisions)
    assert result.reason or result.warnings


@pytest.mark.parametrize("lane", ["live", "replay"])
@pytest.mark.parametrize("field,value", [
    ("run_id", "zz-different-run"),
    ("snapshot_hash", "b" * 64),
    ("run_completed_at", "2026-10-14T11:54:00Z"),
    ("formula_version", "conflicting-version"),
    ("formula_checksum", "1" * 64),
])
def test_inconsistent_run_lineage_fails_closed(monkeypatch, tmp_path, lane, field, value):
    rows = _rows(_NOW - timedelta(minutes=5))
    rows[0][field] = value
    result, decisions = _decide(monkeypatch, tmp_path, rows, lane)
    assert result.status == "unavailable"
    assert not decisions or all(item["status"] == "unavailable" and not item["targets"] for item in decisions)


@pytest.mark.parametrize("field,value", [
    ("run_id", "different-run"), ("run_id", None),
    ("snapshot_hash", "b" * 64), ("snapshot_hash", None),
    ("run_completed_at", None),
])
def test_noncanonical_rows_still_require_run_identity(field, value):
    rows = _rows(_NOW - timedelta(minutes=5))
    rows[0].update(formula_version="unavailable", formula_checksum="unavailable")
    rows[0][field] = value
    group, error = bots._validate_run("score-run", rows, _NOW)
    assert group is None and error


@pytest.mark.parametrize("lane", ["live", "replay"])
def test_noncanonical_eligibility_inputs_are_not_used(monkeypatch, tmp_path, lane):
    rows = _rows(_NOW - timedelta(minutes=5))
    rows[0].update(formula_version="unavailable", formula_checksum=None)
    board = _scoreboard(rows, _NOW).astype(object)
    for field in ("asset_type", "rank", "analysis_status", "price_as_of_date", "freshness_status"):
        rows[0][field] = None
    for field in ("asset_type", "rank", "analysis_status", "latest_price_date", "research_promotion_allowed"):
        board.loc[board["instrument_id"] == "AAA", field] = None
    result, decisions = _decide(monkeypatch, tmp_path, rows, lane, board)
    assert result.status in {"available", "partial"}
    assert decisions and all("AAA" not in item["targets"] for item in decisions)


@pytest.mark.parametrize("lane", ["live", "replay"])
def test_noncanonical_benchmark_only_blocks_fixed_benchmark_allocations(monkeypatch, tmp_path, lane):
    rows = _rows(_NOW - timedelta(minutes=5))
    rows[-1].update(formula_version="unavailable", formula_checksum="unavailable")
    result, decisions = _decide(monkeypatch, tmp_path, rows, lane)
    assert result.status in {"available", "partial"}
    top_n = next(item for item in decisions if item["bot_family"] == "B1")
    assert top_n["status"] == "available" and "VWCE" not in top_n["targets"]
    assert {"instrument_id": "VWCE", "reason": "no_canonical_score"} in top_n["skipped_instruments"]
    assert "VWCE" in top_n["prices_used"]  # Comparator price remains independent of score eligibility.
    for item in decisions:
        if item["bot_family"] in {"B0", "B2"}:
            assert item["status"] == "unavailable" and not item["targets"]
            assert "no_canonical_score" in item["reason"]


@pytest.mark.parametrize("lane", ["live", "replay"])
def test_future_history_cannot_invalidate_an_earlier_valid_run(monkeypatch, tmp_path, lane):
    rows = _rows(_NOW - timedelta(minutes=5))
    future = _rows(_NOW + timedelta(hours=1), run_id="future-run")  # Same snapshot hash, known after the cutoff.
    later_unverifiable = _rows(_NOW - timedelta(minutes=1), run_id="unverifiable-run")
    for row in later_unverifiable:
        row["run_completed_at"] = None
    history = [*rows, *future, *later_unverifiable]
    assert bots._snapshot_run_identities(history, _NOW) == {"a" * 64: {"score-run"}}
    group, error = bots._validate_run(
        "score-run", rows, _NOW, snapshot_run_ids=bots._snapshot_run_identities(history, _NOW),
    )
    assert error is None and group is not None
    if lane == "live":
        board = _scoreboard(rows, _NOW)
        board["instrument_id"] = board["instrument_id"].str.strip()
        board["research_promotion_allowed"] = board["instrument_id"].isin({"AAA", "BBB"})
        result = _run_fixture(monkeypatch, tmp_path, history, board, _NOW, binding_rows=rows)
        decisions = list(result.records)
    else:
        track = execution.replay_track(tmp_path, _exec_config())
        _allow(tmp_path, track)
        result = run_historical_replay(
            _NOW, root=tmp_path, history=pd.DataFrame(_history_with_columns(history)),
            price_book=_book(known_at=_NOW), now=_NOW,
        )
        with TransactionalStore(track.store_root, read_only=True) as store:
            decisions = [dict(item.payload) for item in store.list(track.decision_type)]
    assert result.status in {"available", "partial"}, (result.reason, result.warnings)
    assert decisions and all(item["status"] == "available" for item in decisions)
    # A conflicting owner that is already known by the cutoff still fails closed.
    prior = _rows(_NOW - timedelta(minutes=2), run_id="prior-run")
    assert bots._snapshot_run_identities([*rows, *prior], _NOW)["a" * 64] == {"score-run", "prior-run"}
