from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.application import scoreboard_publication
from etf_cockpit.portfolio import paper_bots
from etf_cockpit.signals.canonical_scoring import load_score_policy


# Fixed recorder clock: the forward recorder only accepts the current UTC day, so tests that build
# "minutes ago" cutoffs must not depend on the real wall clock (fails within minutes after 00:00 UTC).
_NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def _time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _rows(known_at: datetime, *, run_id: str = "score-run", version: str | None = None, snapshot: str = "a") -> list[dict[str, object]]:
    version = version or load_score_policy().formula_version
    snapshot_hash = snapshot * 64
    instruments = (
        ("AAA", "STOCK", 1, 8.5, "add_candidate", "strong_evidence_candidate", "a" * 64),
        ("BBB", "ETF", 2, 7.2, "add_candidate", "positive_evidence_candidate", "b" * 64),
        ("BAD", "ETF", 3, 6.9, "manual_review", "blocked_data_quality", "c" * 64),
        ("VWCE", "ETF", 4, 6.0, "no_trade", "watchlist", "d" * 64),
    )
    result = []
    for instrument_id, asset_type, rank, score, action, label, source_hash in instruments:
        result.append(
            {
                "run_id": run_id,
                "run_completed_at": _time(known_at),
                "snapshot_hash": snapshot_hash,
                "instrument_id": instrument_id,
                "asset_type": asset_type,
                "rank": rank,
                "score_rank": rank,
                "price_as_of_date": known_at.date().isoformat(),
                "data_as_of_date": known_at.date().isoformat(),
                "final_combined_score_10": score,
                "final_action": action,
                "final_label": label,
                "formula_version": version,
                "formula_checksum": "e" * 64,
                "score_schema_version": "simple_scores_v3_groups",
                "source_vintage_hash": "f" * 64,
                "source_snapshot_hash": source_hash,
                "classification_version_id": "classification-v1",
                "classification_invalidation_hash": "9" * 64,
                "classification_dependency_status": "current",
                "gate_policy_version": "gate-policy-v1",
                "gate_policy_checksum": "8" * 64,
                "analysis_status": "complete",
                "execution_allowed": False,
                "freshness_status": "fresh",
                "blocked_by": "",
            }
        )
    return result


def _scoreboard(rows: list[dict[str, object]], known_at: datetime) -> pd.DataFrame:
    board_rows = []
    for row in rows:
        instrument_id = str(row["instrument_id"])
        board_rows.append(
            {
                "instrument_id": instrument_id,
                "symbol": "VWCE.DE" if instrument_id == "VWCE" else f"{instrument_id}.X",
                "asset_type": row["asset_type"],
                "instrument_currency": "EUR" if instrument_id in {"VWCE", "BBB", "BAD"} else "USD",
                "current_price": 100.0 if instrument_id == "VWCE" else 20.0 + int(row["rank"]),
                "latest_price_date": known_at.date().isoformat(),
                "final_combined_score_10": row["final_combined_score_10"],
                "final_label": row["final_label"],
                "legacy_action": row["final_action"],
                "rank": row["rank"],
                "formula_version": row["formula_version"],
                "formula_checksum": row["formula_checksum"],
                "score_schema_version": row["score_schema_version"],
                "source_vintage_hash": row["source_vintage_hash"],
                "classification_version_id": row["classification_version_id"],
                "classification_invalidation_hash": row["classification_invalidation_hash"],
                "classification_dependency_status": row["classification_dependency_status"],
                "gate_policy_version": row["gate_policy_version"],
                "gate_policy_checksum": row["gate_policy_checksum"],
                "analysis_status": row["analysis_status"],
                "research_promotion_allowed": instrument_id in {"AAA", "BBB"},
                "execution_allowed": False,
            }
        )
    return pd.DataFrame(board_rows)


def _run_fixture(
    monkeypatch,
    tmp_path: Path,
    history: list[dict[str, object]],
    board: pd.DataFrame,
    cutoff: datetime,
    *,
    config_path: Path | None = None,
    binding_rows: list[dict[str, object]] | None = None,
):
    derived = tmp_path / "data" / "derived"
    derived.mkdir(parents=True, exist_ok=True)
    scoreboard_path = derived / "scoreboard.parquet"
    scoreboard_bytes = board.to_parquet(index=False)
    scoreboard_path.write_bytes(scoreboard_bytes)
    digest = hashlib.sha256(scoreboard_bytes).hexdigest()
    by_run: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in history if binding_rows is None else binding_rows:
        run_id = str(row["run_id"])
        snapshot_hash = str(row["snapshot_hash"])
        completed_at = str(row["run_completed_at"])
        by_run[(run_id, snapshot_hash, completed_at)] = {
            "schema_version": "scoreboard_publication_binding.v1",
            "run_id": run_id,
            "score_snapshot_hash": snapshot_hash,
            "score_completed_at": completed_at,
            "known_at": completed_at,
            "scoreboard_sha256": digest,
            "execution_allowed": False,
        }
    with TransactionalStore(tmp_path) as store:
        for payload in by_run.values():
            identity = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            store.put_many(
                [(paper_bots.PUBLICATION_BINDING_ENTITY_TYPE, identity, payload)],
                immutable=True,
            )

    monkeypatch.setattr(paper_bots, "_load_published_score_history", lambda root: pd.DataFrame(history))
    monkeypatch.setattr(paper_bots, "project_classification_score_frame", lambda frame, *, root: frame)
    return paper_bots.run_paper_bots(
        cutoff,
        root=tmp_path,
        config_path=config_path or paper_bots.PAPER_BOTS_CONFIG_PATH,
        now=_NOW,
    )


def test_publication_binding_records_exact_board_bytes_and_history_identity(tmp_path: Path) -> None:
    derived = tmp_path / "data" / "derived"
    derived.mkdir(parents=True)
    board_path = derived / "scoreboard.parquet"
    expected_board = pd.DataFrame({"instrument_id": ["AAA"], "current_price": [42.0]})
    expected_board.to_parquet(board_path, index=False)
    now = _NOW
    history_path = derived / "score_history.parquet"
    pd.DataFrame(
        [{
            "run_id": "run-1",
            "run_completed_at": _time(now),
            "snapshot_hash": "a" * 64,
        }]
    ).to_parquet(history_path, index=False)

    binding = scoreboard_publication._record_scoreboard_publication_binding(
        board_path, history_path, expected_board
    )

    assert binding["scoreboard_sha256"] == hashlib.sha256(board_path.read_bytes()).hexdigest()
    assert binding["run_id"] == "run-1"
    assert binding["score_snapshot_hash"] == "a" * 64
    assert binding["execution_allowed"] is False
    with TransactionalStore(tmp_path, read_only=True) as store:
        records = store.list(paper_bots.PUBLICATION_BINDING_ENTITY_TYPE)
    assert len(records) == 1
    assert records[0].payload == binding


def test_publication_binding_accepts_nested_empty_model_readiness_arrays(tmp_path: Path) -> None:
    derived = tmp_path / "data" / "derived"
    derived.mkdir(parents=True)
    board_path = derived / "scoreboard.parquet"
    expected_board = pd.DataFrame(
        {
            "instrument_id": ["AAA"],
            "model_readiness": [
                {
                    "status": "unavailable",
                    "available_models": [],
                    "reason": "Model evidence unavailable.",
                }
            ],
        }
    )
    expected_board.to_parquet(board_path, index=False)
    now = _NOW
    history_path = derived / "score_history.parquet"
    pd.DataFrame(
        [
            {
                "run_id": "run-1",
                "run_completed_at": _time(now),
                "snapshot_hash": "a" * 64,
            }
        ]
    ).to_parquet(history_path, index=False)

    binding = scoreboard_publication._record_scoreboard_publication_binding(
        board_path, history_path, expected_board
    )

    assert binding["run_id"] == "run-1"
    assert binding["scoreboard_sha256"] == hashlib.sha256(board_path.read_bytes()).hexdigest()


@pytest.mark.parametrize("boundary", ["consumer", "producer"])
def test_publication_uses_one_immutable_scoreboard_buffer(monkeypatch, tmp_path: Path, boundary: str) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at)
    board.loc[board["instrument_id"] == "AAA", "research_promotion_allowed"] = False
    replacement = board.copy()
    replacement.loc[replacement["instrument_id"] == "AAA", "research_promotion_allowed"] = True
    replacement.loc[replacement["instrument_id"] == "VWCE", "current_price"] = 999.0
    board_path = tmp_path / "data" / "derived" / "scoreboard.parquet"
    replacement_bytes = replacement.to_parquet(index=False)

    if boundary == "consumer":
        original_read = Path.read_bytes

        def replace_after_read(path):
            payload = original_read(path)
            if path == board_path:
                path.write_bytes(replacement_bytes)
            return payload

        monkeypatch.setattr(Path, "read_bytes", replace_after_read)
        result = _run_fixture(monkeypatch, tmp_path, rows, board, now)
        assert result.status == "available"
        benchmark = next(record for record in result.records if record["bot_family"] == "B0")
        top_n = next(record for record in result.records if record["bot_family"] == "B1")
        assert benchmark["prices_used"]["VWCE"]["price"] == 100.0
        assert "AAA" not in top_n["targets"]
        assert all(record["execution_allowed"] is False for record in result.records)
    else:
        board_path.parent.mkdir(parents=True)
        board.to_parquet(board_path, index=False)
        history_path = board_path.with_name("score_history.parquet")
        pd.DataFrame(rows).to_parquet(history_path, index=False)
        with TransactionalStore(tmp_path):
            pass
        original_compare = pd.testing.assert_frame_equal

        def replace_after_comparison(*args, **kwargs):
            original_compare(*args, **kwargs)
            board_path.write_bytes(replacement_bytes)

        monkeypatch.setattr(pd.testing, "assert_frame_equal", replace_after_comparison)
        with pytest.raises(RuntimeError, match="Scoreboard changed"):
            scoreboard_publication._record_scoreboard_publication_binding(board_path, history_path, board)
        with TransactionalStore(tmp_path, read_only=True) as store:
            assert not store.list(paper_bots.PUBLICATION_BINDING_ENTITY_TYPE)


@pytest.mark.parametrize("field,invalid", [
    ("formula_version", None),
    ("formula_checksum", None),
    ("formula_checksum", "not-a-checksum"),
    ("score_schema_version", None),
    ("gate_policy_version", None),
    ("gate_policy_checksum", None),
    ("gate_policy_checksum", "g" * 64),
])
def test_every_history_row_requires_valid_lineage(monkeypatch, tmp_path: Path, field: str, invalid) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    rows[0][field] = invalid
    board = _scoreboard(rows, known_at)
    assert bool(board.loc[board["instrument_id"] == "AAA", "research_promotion_allowed"].iloc[0])

    result = _run_fixture(monkeypatch, tmp_path, rows, board, now)

    assert result.status == "unavailable"
    assert result.records
    assert all(record["status"] == "unavailable" and not record["targets"] for record in result.records)
    assert all("lineage" in str(record["reason"]) for record in result.records)


@pytest.mark.parametrize("duplicate_rank", [1, 9])
def test_duplicate_history_instruments_reject_publication(monkeypatch, tmp_path: Path, duplicate_rank: int) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at).drop(columns=["rank"])
    rows.append({**rows[0], "rank": duplicate_rank})

    result = _run_fixture(monkeypatch, tmp_path, rows, board, now)

    assert result.status == "unavailable"
    assert result.records
    assert all(record["status"] == "unavailable" and not record["targets"] for record in result.records)
    assert all("duplicate instrument" in str(record["reason"]) for record in result.records)


def test_changed_scoreboard_bytes_cannot_reuse_an_older_publication_binding(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    original = _scoreboard(rows, known_at)
    first = _run_fixture(monkeypatch, tmp_path, rows, original, now)
    assert first.status == "available"

    changed = original.copy()
    changed.loc[changed["instrument_id"] == "AAA", "current_price"] += 1.0
    changed.loc[changed["instrument_id"] == "AAA", "research_promotion_allowed"] = False
    (tmp_path / "data" / "derived" / "scoreboard.parquet").write_bytes(
        changed.to_parquet(index=False)
    )

    result = paper_bots.run_paper_bots(now, root=tmp_path, config_path=paper_bots.PAPER_BOTS_CONFIG_PATH, now=_NOW)

    assert result.status == "unavailable"
    assert all(record["status"] == "unavailable" for record in result.records)
    assert all(not record["targets"] for record in result.records)


def test_saved_month_slot_is_not_returned_before_its_as_of_cutoff(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=20)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at)
    later_cutoff = now - timedelta(minutes=5)
    earlier_cutoff = now - timedelta(minutes=10)

    first = _run_fixture(monkeypatch, tmp_path, rows, board, later_cutoff)
    assert first.status == "available"
    repeated_earlier = _run_fixture(monkeypatch, tmp_path, rows, board, earlier_cutoff)

    b0 = next(record for record in repeated_earlier.records if record["bot_family"] == "B0")
    assert b0["status"] == "unavailable"
    assert "newer than as_of" in str(b0["reason"])


def test_unknown_gate_rank_or_freshness_fails_closed_without_reweighting(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at)
    board.loc[board["instrument_id"] == "AAA", "research_promotion_allowed"] = True
    board.loc[board["instrument_id"] == "BBB", "research_promotion_allowed"] = True
    cases = ("gate", "rank", "freshness")

    for case in cases:
        case_root = tmp_path / case
        case_rows = [dict(row) for row in rows]
        case_board = board.copy()
        if case == "gate":
            case_board["research_promotion_allowed"] = case_board["research_promotion_allowed"].astype(object)
            case_board.loc[case_board["instrument_id"] == "BBB", "research_promotion_allowed"] = None
        elif case == "rank":
            for row in case_rows:
                if row["instrument_id"] == "BBB":
                    row["rank"] = None
            case_board.loc[case_board["instrument_id"] == "BBB", "rank"] = None
        else:
            for row in case_rows:
                if row["instrument_id"] == "BBB":
                    row["freshness_status"] = "not_checked"

        result = _run_fixture(monkeypatch, case_root, case_rows, case_board, now)
        top_n = next(record for record in result.records if record["bot_family"] == "B1")
        assert top_n["status"] == "unavailable", case
        assert not top_n["targets"], case


def test_first_eligible_snapshot_can_follow_an_earlier_stale_publication(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    stale_time = now - timedelta(hours=25)
    fresh_time = now - timedelta(minutes=5)
    stale_rows = _rows(stale_time, run_id="stale-run", snapshot="a")
    fresh_rows = _rows(fresh_time, run_id="fresh-run", snapshot="b")
    for row in stale_rows:
        row["price_as_of_date"] = fresh_time.date().isoformat()
        row["data_as_of_date"] = fresh_time.date().isoformat()
    board = _scoreboard(fresh_rows, fresh_time)

    result = _run_fixture(monkeypatch, tmp_path, stale_rows + fresh_rows, board, now)

    assert result.status == "available"
    assert all(record["status"] == "available" for record in result.records)
    assert all(record["snapshot_hash"] == "b" * 64 for record in result.records)


def test_b1_top_n_includes_vwce_when_it_is_an_eligible_ranked_etf(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at)
    board.loc[board["instrument_id"] == "VWCE", "research_promotion_allowed"] = True

    result = _run_fixture(monkeypatch, tmp_path, rows, board, now)

    top_n = next(record for record in result.records if record["bot_family"] == "B1")
    assert top_n["status"] == "available"
    assert top_n["targets"] == {"AAA": 1 / 3, "BBB": 1 / 3, "VWCE": 1 / 3}


def test_configuration_changes_create_a_new_bot_identity_and_invalid_allocations_are_rejected(
    monkeypatch, tmp_path: Path
) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at)
    base_config = paper_bots.PAPER_BOTS_CONFIG_PATH.read_text(encoding="utf-8")
    config_path = tmp_path / "paper_bots.yaml"
    config_path.write_text(base_config, encoding="utf-8")
    first = _run_fixture(monkeypatch, tmp_path / "first", rows, board, now, config_path=config_path)
    first_b1 = next(record for record in first.records if record["bot_family"] == "B1")

    changed_config = base_config.replace("top_n: 10", "top_n: 9")
    config_path.write_text(changed_config, encoding="utf-8")
    second = _run_fixture(monkeypatch, tmp_path / "second", rows, board, now, config_path=config_path)
    second_b1 = next(record for record in second.records if record["bot_family"] == "B1")
    assert second_b1["bot_id"] != first_b1["bot_id"]
    assert second_b1["spec_hash"] != first_b1["spec_hash"]

    invalid = changed_config.replace("top_n: 9", "top_n: 0")
    config_path.write_text(invalid, encoding="utf-8")
    rejected = _run_fixture(monkeypatch, tmp_path / "invalid", rows, board, now, config_path=config_path)
    assert rejected.status == "unavailable"
    assert "specification unavailable" in str(rejected.records or rejected.reason).casefold()


def test_spec_hash_is_stable_when_a_decision_recovers_from_unavailable(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    unknown = _scoreboard(rows, known_at)
    unknown["research_promotion_allowed"] = unknown["research_promotion_allowed"].astype(object)
    unknown.loc[unknown["instrument_id"] == "BBB", "research_promotion_allowed"] = None
    unavailable = _run_fixture(monkeypatch, tmp_path, rows, unknown, now)
    unavailable_b1 = next(record for record in unavailable.records if record["bot_family"] == "B1")
    assert unavailable_b1["status"] == "unavailable"

    available = _run_fixture(monkeypatch, tmp_path, rows, _scoreboard(rows, known_at), now + timedelta(seconds=1))
    available_b1 = next(record for record in available.records if record["bot_family"] == "B1")

    assert available_b1["status"] == "available"
    assert available_b1["bot_id"] == unavailable_b1["bot_id"]
    assert available_b1["spec_hash"] == unavailable_b1["spec_hash"]


def test_decisions_use_only_published_rows_known_at_the_cutoff(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=10)
    cutoff = now + timedelta(seconds=1)
    past_rows = _rows(known_at)
    future_rows = _rows(now + timedelta(hours=1), run_id="future-run", version="score-engine-v4.0.0", snapshot="b")

    result = _run_fixture(
        monkeypatch,
        tmp_path,
        past_rows + future_rows,
        _scoreboard(past_rows, known_at),
        cutoff,
    )

    assert result.status == "available"
    assert result.snapshot_hash == "a" * 64
    assert all(record["snapshot_hash"] == "a" * 64 for record in result.records)
    assert not any(record.get("score_version") == "score-engine-v4.0.0" for record in result.records)
    repeated = _run_fixture(
        monkeypatch,
        tmp_path,
        past_rows + future_rows,
        _scoreboard(past_rows, known_at),
        cutoff,
    )
    assert repeated.snapshot_hash == result.snapshot_hash
    assert repeated.appended == 0


def test_score_version_creates_new_challenger_identity_and_preserves_old_records(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    first_time = now - timedelta(minutes=20)
    first_rows = _rows(first_time)
    first = _run_fixture(
        monkeypatch, tmp_path, first_rows, _scoreboard(first_rows, first_time), now - timedelta(minutes=10)
    )
    baseline_record = next(record for record in first.records if record["bot_family"] == "B1")
    baseline_identity = baseline_record["bot_id"]

    second_time = now - timedelta(minutes=5)
    second_rows = _rows(second_time, run_id="score-run-v4", version="score-engine-v4.0.0", snapshot="b")
    second = _run_fixture(
        monkeypatch,
        tmp_path,
        first_rows + second_rows,
        _scoreboard(second_rows, second_time),
        now + timedelta(seconds=1),
    )
    challenger = next(record for record in second.records if str(record["bot_family"]).startswith("B3-b1"))

    assert challenger["bot_id"] != baseline_identity
    with TransactionalStore(tmp_path, read_only=True) as store:
        saved = store.get(paper_bots.DECISION_ENTITY_TYPE, str(baseline_record["decision_id"]))
    assert saved is not None
    assert saved.payload == baseline_record


def test_failed_gate_never_enters_a_top_n_or_candidate_sleeve(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at)
    board.loc[board["instrument_id"] == "AAA", "research_promotion_allowed"] = False
    board.loc[board["instrument_id"] == "BAD", "research_promotion_allowed"] = False

    result = _run_fixture(monkeypatch, tmp_path, rows, board, now + timedelta(seconds=1))
    top_n = next(record for record in result.records if record["bot_family"] == "B1")
    core_sleeve = next(record for record in result.records if record["bot_family"] == "B2")

    assert "AAA" not in top_n["targets"]
    assert "BAD" not in top_n["targets"]
    assert top_n["targets"] == {"BBB": 1.0}
    assert core_sleeve["targets"] == {"VWCE": 0.8, "BBB": 0.2}
    assert all(
        skipped["reason"] in {"research_promotion_not_allowed", "candidate_buy_not_present"}
        for record in (top_n, core_sleeve)
        for skipped in record["skipped_instruments"]
    )

    no_candidates = board.copy()
    no_candidates["research_promotion_allowed"] = False
    cash_result = _run_fixture(
        monkeypatch, tmp_path / "cash-only", rows, no_candidates, now + timedelta(seconds=1)
    )
    cash_top_n = next(record for record in cash_result.records if record["bot_family"] == "B1")
    assert cash_top_n["targets"] == {"cash_weight": 1.0}


def test_b0_stage_a_target_is_vwce_only_and_captures_price(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    result = _run_fixture(monkeypatch, tmp_path, rows, _scoreboard(rows, known_at), now + timedelta(seconds=1))

    benchmark = next(record for record in result.records if record["bot_family"] == "B0")

    assert benchmark["targets"] == {"VWCE": 1.0}
    assert benchmark["prices_used"]["VWCE"]["symbol"] == "VWCE.DE"
    assert benchmark["prices_used"]["VWCE"]["price"] == 100.0
    assert benchmark["execution_allowed"] is False


def test_missing_or_mismatched_published_snapshot_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at)
    board.loc[board["instrument_id"] == "AAA", "formula_checksum"] = "0" * 64

    result = _run_fixture(monkeypatch, tmp_path, rows, board, now + timedelta(seconds=1))

    assert result.status == "unavailable"
    assert result.records
    assert all(record["status"] == "unavailable" for record in result.records)
    assert all("match" in str(record["reason"]).casefold() for record in result.records)
    assert all(record["targets"] == {} for record in result.records)


def test_missing_published_snapshot_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    result = _run_fixture(monkeypatch, tmp_path, [], pd.DataFrame(), now)

    assert result.status == "unavailable"
    assert result.records
    assert all(record["status"] == "unavailable" for record in result.records)
    assert all(record["targets"] == {} for record in result.records)
    assert all(record["reason"] for record in result.records)


def test_stale_published_snapshot_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=1)
    rows = _rows(known_at)
    config_text = paper_bots.PAPER_BOTS_CONFIG_PATH.read_text(encoding="utf-8")
    stale_config = tmp_path / "paper_bots_stale.yaml"
    stale_config.write_text(config_text.replace("max_snapshot_age_hours: 24", "max_snapshot_age_hours: 0"), encoding="utf-8")

    result = _run_fixture(
        monkeypatch,
        tmp_path,
        rows,
        _scoreboard(rows, known_at),
        now + timedelta(seconds=1),
        config_path=stale_config,
    )

    assert result.status == "unavailable"
    assert result.records
    assert all(record["status"] == "unavailable" for record in result.records)
    assert all("stale" in str(record["reason"]).casefold() for record in result.records)


def _application_root(tmp_path: Path) -> Path:
    root = tmp_path / "application-root"
    (root / "configs").mkdir(parents=True)
    (root / "configs" / "universe.yaml").write_text("{}", encoding="utf-8")
    (root / "data").mkdir()
    return root


def test_pipeline_cli_runs_the_recorder_only_after_success(monkeypatch, tmp_path: Path) -> None:
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    root = _application_root(tmp_path)
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(root))
    cli = importlib.import_module("run_pipeline_cli")
    calls: list[tuple[datetime, Path | None]] = []
    monkeypatch.setattr(
        paper_bots,
        "run_paper_bots",
        lambda as_of, **kwargs: calls.append((as_of, kwargs.get("root")))
        or SimpleNamespace(status="available", reason=None, warnings=("older run skipped",)),
    )

    assert cli.run_cli(lambda: 1, record_paper_bots=True) == 1
    assert calls == []
    assert cli.run_cli(lambda: 0, record_paper_bots=True) == 0
    assert len(calls) == 1
    assert calls[0][0].tzinfo is not None
    assert calls[0][1] == root.resolve()


def test_other_run_cli_scripts_never_run_the_recorder(monkeypatch, tmp_path: Path) -> None:
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(_application_root(tmp_path)))
    cli = importlib.import_module("run_pipeline_cli")
    calls: list[object] = []
    monkeypatch.setattr(paper_bots, "run_paper_bots", lambda *args, **kwargs: calls.append(args))

    assert cli.run_cli(lambda: 0) == 0
    assert calls == []
    for name in ("run_signals", "run_forecasts", "run_backtest", "run_yfinance_candidate_forecasts"):
        text = (scripts / f"{name}.py").read_text(encoding="utf-8")
        assert "record_paper_bots" not in text
    assert "record_paper_bots=True" in (scripts / "run_yfinance_analysis.py").read_text(encoding="utf-8")


def test_pipeline_cli_swallows_recorder_import_failure_after_success(monkeypatch, capsys, tmp_path: Path) -> None:
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(_application_root(tmp_path)))
    cli = importlib.import_module("run_pipeline_cli")
    monkeypatch.setitem(sys.modules, "etf_cockpit.portfolio.paper_bots", None)

    assert cli.run_cli(lambda: 0, record_paper_bots=True) == 0
    assert "Paper bots unavailable: ModuleNotFoundError." in capsys.readouterr().out


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rows: [dict(row, run_completed_at="2026-01-01T00:00:00") for row in rows],
        lambda rows: [dict(row, run_completed_at=None) for row in rows],
        lambda rows: [dict(row, formula_checksum=None) for row in rows],
        lambda rows: [dict(row, gate_policy_checksum=None) for row in rows],
        lambda rows: rows + rows[:1],
        lambda rows: [dict(row, run_id=None) for row in rows],
    ],
    ids=["naive-time", "null-time", "null-checksum", "null-lineage", "duplicate-instrument", "no-run-id"],
)
def test_dirty_older_run_does_not_block_the_clean_bound_run(monkeypatch, tmp_path: Path, mutate) -> None:
    now = _NOW
    bound_time = now - timedelta(minutes=5)
    old_rows = mutate(_rows(bound_time - timedelta(days=40), run_id="old-run", snapshot="b"))
    bound_rows = _rows(bound_time, run_id="bound-run", snapshot="a")
    board = _scoreboard(bound_rows, bound_time)

    result = _run_fixture(monkeypatch, tmp_path, old_rows + bound_rows, board, now, binding_rows=bound_rows)

    assert result.status == "available"
    assert result.appended == 3
    assert all(record["status"] == "available" for record in result.records)
    assert result.snapshot_hash == "a" * 64
    assert result.warnings


def test_dirty_bound_run_is_unavailable_with_a_reason(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    bound_time = now - timedelta(minutes=5)
    old_rows = _rows(bound_time - timedelta(days=40), run_id="old-run", snapshot="b")
    bound_rows = _rows(bound_time, run_id="bound-run", snapshot="a")
    board = _scoreboard(bound_rows, bound_time)
    dirty_history = old_rows + [dict(row, run_completed_at=None) for row in bound_rows]

    result = _run_fixture(monkeypatch, tmp_path, dirty_history, board, now, binding_rows=bound_rows)

    assert result.status == "unavailable"
    assert "bound-run" in str(result.reason)
    assert "known_at" in str(result.reason)
    assert all(record["status"] == "unavailable" for record in result.records)


def test_real_score_history_read_path_uses_the_configured_location(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at)
    derived = tmp_path / "data" / "derived"
    derived.mkdir(parents=True)
    history_path = tmp_path / paper_bots.SCORE_HISTORY_PATH.resolve().relative_to(paper_bots.ROOT.resolve())
    history_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(history_path, index=False)
    board_bytes = board.to_parquet(index=False)
    (derived / "scoreboard.parquet").write_bytes(board_bytes)
    payload = {
        "schema_version": "scoreboard_publication_binding.v1",
        "run_id": "score-run",
        "score_snapshot_hash": "a" * 64,
        "score_completed_at": _time(known_at),
        "known_at": _time(known_at),
        "scoreboard_sha256": hashlib.sha256(board_bytes).hexdigest(),
        "execution_allowed": False,
    }
    with TransactionalStore(tmp_path) as store:
        store.put_many([(paper_bots.PUBLICATION_BINDING_ENTITY_TYPE, "binding-1", payload)], immutable=True)
    monkeypatch.setattr(paper_bots, "project_classification_score_frame", lambda frame, *, root: frame)

    result = paper_bots.run_paper_bots(now, root=tmp_path, config_path=paper_bots.PAPER_BOTS_CONFIG_PATH, now=_NOW)

    assert result.status == "available"
    assert result.snapshot_hash == "a" * 64


@pytest.mark.parametrize("value", ["2026-10-13", date(2026, 10, 13)])
def test_date_only_as_of_is_rejected_with_a_clear_message(tmp_path: Path, value) -> None:
    result = paper_bots.run_paper_bots(value, root=tmp_path, config_path=paper_bots.PAPER_BOTS_CONFIG_PATH)

    assert result.status == "unavailable"
    assert result.appended == 0
    assert "date-only" in str(result.reason)


def test_add_candidate_action_maps_to_the_candidate_buy_sleeve(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at)

    result = _run_fixture(monkeypatch, tmp_path, rows, board, now)

    sleeve = next(record for record in result.records if record["bot_family"] == "B2")
    assert sleeve["status"] == "available"
    assert sleeve["targets"] == pytest.approx({"VWCE": 0.8, "AAA": 0.1, "BBB": 0.1})
    assert "cash_weight" not in sleeve["targets"]


def test_top_n_with_fewer_eligible_is_equal_weight_with_a_recorded_reason(monkeypatch, tmp_path: Path) -> None:
    now = _NOW
    known_at = now - timedelta(minutes=5)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at)

    result = _run_fixture(monkeypatch, tmp_path, rows, board, now)

    top_n = next(record for record in result.records if record["bot_family"] == "B1")
    assert top_n["targets"] == pytest.approx({"AAA": 0.5, "BBB": 0.5})
    assert "fewer_than_top_n_eligible" in str(top_n["reason"])
    benchmark = next(record for record in result.records if record["bot_family"] == "B0")
    assert benchmark["reason"] is None


def test_the_shipped_baseline_version_is_read_from_the_score_policy_and_a_literal_conflict_is_rejected(tmp_path: Path) -> None:
    _, config = paper_bots._load_config(paper_bots.PAPER_BOTS_CONFIG_PATH)
    assert "score-engine" in config["baseline_score_version"]
    assert config["baseline_score_version"] == load_score_policy().formula_version
    text = paper_bots.PAPER_BOTS_CONFIG_PATH.read_text(encoding="utf-8")
    conflicting = tmp_path / "conflict.yaml"
    conflicting.write_text(text + "baseline_score_version: score-engine-v0.0.0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        paper_bots._load_config(conflicting)
    unknown = tmp_path / "unknown.yaml"
    unknown.write_text(text.replace("score_engine_v3.formula_version", "other.thing"), encoding="utf-8")
    with pytest.raises(ValueError):
        paper_bots._load_config(unknown)
