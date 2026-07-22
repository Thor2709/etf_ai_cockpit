from __future__ import annotations

import pandas as pd

from etf_cockpit.data.classification import (
    ClassificationOverride,
    ClassificationStore,
    classification_score_state,
)
from etf_cockpit.data.score_history import append_score_run, score_history_frame, score_history_v2_payload


def test_score_history_append_is_idempotent_by_run_and_snapshot(tmp_path) -> None:
    scores = pd.DataFrame({"instrument_id": ["A"], "final_combined_score_10": [7.0], "final_action": ["watchlist"], "component": ["momentum"]})
    first = append_score_run(scores, "run-1", "2026-07-10", root=tmp_path)
    second = append_score_run(scores, "run-1", "2026-07-10", root=tmp_path)
    history = score_history_frame(root=tmp_path)
    assert first.rows_written == 1
    assert second.rows_written == 0
    assert len(history) == 1


def test_invalid_history_rows_are_dropped_without_crashing(tmp_path) -> None:
    scores = pd.DataFrame({"instrument_id": ["A", "B"], "final_combined_score_10": [7.0, "bad"], "final_action": ["watchlist", "manual_review"]})
    append_score_run(scores, "run-1", "2026-07-10", root=tmp_path)
    assert len(score_history_frame(root=tmp_path)) == 1


def test_legacy_review_states_never_infer_portfolio_authority_without_snapshot() -> None:
    for state in (
        "maintain_review",
        "increase_exposure_review",
        "reduce_exposure_review",
        "exit_thesis_review",
        "constraints_blocked",
    ):
        payload = score_history_v2_payload(
            {
                "instrument_id": "A",
                "final_combined_score_10": 7.0,
                "final_action": "hold",
                "portfolio_review_state": state,
            }
        )
        assert payload["portfolio_review_allowed"] is False
        assert payload["portfolio_snapshot_validated"] is False


def test_score_history_accepts_portfolio_review_only_with_validated_snapshot() -> None:
    payload = score_history_v2_payload(
        {
            "instrument_id": "A",
            "final_combined_score_10": 7.0,
            "final_action": "hold",
            "portfolio_snapshot": {
                "as_of_date": "2026-07-10",
                "portfolio_review_state": "reduce_exposure_review",
                "holdings": [{"instrument_id": "A", "weight": 0.5}],
            },
        }
    )
    assert payload["portfolio_review_state"] == "reduce_exposure_review"
    assert payload["portfolio_review_allowed"] is True
    assert payload["portfolio_snapshot_validated"] is True


def test_score_history_rejects_forged_snapshot_marker_without_source_evidence() -> None:
    payload = score_history_v2_payload(
        {
            "instrument_id": "A",
            "research_state": "hold_review",
            "portfolio_review_state": "reduce_exposure_review",
            "portfolio_snapshot_validated": True,
            "portfolio_snapshot_provenance": "validated_snapshot",
            "portfolio_snapshot_checksum": "0" * 64,
            "portfolio_review_allowed": True,
        }
    )

    assert payload["portfolio_review_allowed"] is False
    assert payload["portfolio_snapshot_validated"] is False
    assert payload["portfolio_snapshot_provenance"] == "unavailable"


def test_score_history_preserves_run_dimensions_and_never_grants_execution_authority(tmp_path) -> None:
    scores = pd.DataFrame(
        [
            {
                "instrument_id": "A",
                "final_combined_score_10": 7.0,
                "final_action": "watchlist",
                "rank": 2,
                "warnings": "partial_data|stale_prices",
                "freshness_status": "stale",
                "model_available": False,
                "forecast_status": "unavailable",
                "news_inventory": 0,
                "backtest_trust": "not_evaluated",
                "portfolio_risk": "review",
                "execution_allowed": True,
            }
        ]
    )
    append_score_run(scores, "run-dimensions", "2026-07-10", root=tmp_path)
    row = score_history_frame(root=tmp_path).iloc[0]

    assert {"run_started_at", "display_name", "yahoo_ticker", "data_as_of_date", "source_snapshot_hash"} <= set(score_history_frame(root=tmp_path).columns)
    assert row["rank"] == 2
    assert row["warnings"] == "partial_data|stale_prices"
    assert row["freshness_status"] == "stale"
    assert bool(row["execution_allowed"]) is False


def test_score_history_replaces_changed_snapshot_for_same_run_without_duplicate_instruments(tmp_path) -> None:
    first = pd.DataFrame({"instrument_id": ["A"], "final_combined_score_10": [5.0], "final_action": ["watchlist"]})
    changed = pd.DataFrame({"instrument_id": ["A"], "final_combined_score_10": [6.0], "final_action": ["watchlist"]})
    append_score_run(first, "run-replace", "2026-07-10", root=tmp_path)
    result = append_score_run(changed, "run-replace", "2026-07-10", root=tmp_path)
    history = score_history_frame(root=tmp_path)

    assert result.rows_written == 1
    assert len(history) == 1
    assert float(history.iloc[0]["final_combined_score_10"]) == 6.0


def test_score_history_append_normalises_legacy_store_before_duplicate_detection(tmp_path) -> None:
    path = tmp_path / "data" / "derived" / "score_history.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": "legacy-run",
                "run_completed_at": "2026-07-10",
                "instrument_id": "A",
                "final_combined_score_10": 7.0,
                "final_action": "watchlist",
                "blocked_by": "",
            }
        ]
    ).to_parquet(path, index=False)

    first = append_score_run(
        pd.DataFrame(
            {
                "instrument_id": ["A"],
                "final_combined_score_10": [7.0],
                "final_action": ["watchlist"],
            }
        ),
        "legacy-run",
        "2026-07-10",
        root=tmp_path,
    )
    second = append_score_run(
        pd.DataFrame(
            {
                "instrument_id": ["A"],
                "final_combined_score_10": [7.0],
                "final_action": ["watchlist"],
            }
        ),
        "legacy-run",
        "2026-07-10",
        root=tmp_path,
    )

    history = score_history_frame(root=tmp_path)
    assert first.rows_written == 1
    assert second.rows_written == 0
    assert len(history) == 1
    assert history.iloc[0]["snapshot_hash"] == first.snapshot_hash


def test_score_history_reader_drops_malformed_rows(tmp_path) -> None:
    path = tmp_path / "data" / "derived" / "score_history.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {"run_id": "good", "instrument_id": "A", "final_combined_score_10": 8.0},
            {"run_id": "bad", "instrument_id": None, "final_combined_score_10": None},
        ]
    ).to_parquet(path, index=False)

    history = score_history_frame(root=tmp_path)

    assert len(history) == 1
    assert history.iloc[0]["instrument_id"] == "A"


def test_empty_complete_run_replaces_only_supplied_run_rows(tmp_path) -> None:
    append_score_run(
        pd.DataFrame({"instrument_id": ["A"], "final_combined_score_10": [7.0]}),
        "run-empty",
        "2026-07-10",
        root=tmp_path,
    )
    append_score_run(
        pd.DataFrame({"instrument_id": ["B"], "final_combined_score_10": [6.0]}),
        "run-other",
        "2026-07-10",
        root=tmp_path,
    )

    result = append_score_run(
        pd.DataFrame(columns=["instrument_id", "final_combined_score_10"]),
        "run-empty",
        "2026-07-10",
        root=tmp_path,
    )

    history = score_history_frame(root=tmp_path)
    assert result.rows_written == 0
    assert set(history["run_id"]) == {"run-other"}
    assert set(history["instrument_id"]) == {"B"}


def test_score_history_publishes_paired_csv_and_rolls_back_on_group_failure(tmp_path, monkeypatch) -> None:
    scores = pd.DataFrame({"instrument_id": ["A"], "final_combined_score_10": [7.0]})
    append_score_run(scores, "run-atomic", "2026-07-10", root=tmp_path)
    parquet_path = tmp_path / "data" / "derived" / "score_history.parquet"
    csv_path = parquet_path.with_suffix(".csv")
    before = parquet_path.read_bytes()
    assert csv_path.exists()
    assert len(pd.read_csv(csv_path)) == 1

    def fail_group(_requests):
        raise RuntimeError("injected grouped write failure")

    monkeypatch.setattr("etf_cockpit.data.score_history.atomic_write_group", fail_group)
    try:
        append_score_run(
            pd.DataFrame({"instrument_id": ["A"], "final_combined_score_10": [8.0]}),
            "run-atomic",
            "2026-07-10",
            root=tmp_path,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("failure injection did not reach grouped persistence")
    assert parquet_path.read_bytes() == before
    assert len(pd.read_csv(csv_path)) == 1


def test_classification_override_invalidates_canonical_history_read_but_preserves_raw_audit_row(tmp_path) -> None:
    before = classification_score_state(tmp_path, "A")
    append_score_run(
        pd.DataFrame(
            {
                "instrument_id": ["A"],
                "final_combined_score_10": [7.0],
                "classification_version_id": [before["version_id"]],
                "classification_invalidation_hash": [before["invalidation_token"]],
                "classification_dependency_status": ["current"],
            }
        ),
        "run-before-override",
        "2026-07-10",
        root=tmp_path,
    )
    with ClassificationStore(tmp_path) as store:
        store.append_overrides(
            (
                ClassificationOverride(
                    override_id="override:A:sector:1",
                    instrument_id="A",
                    field="sector",
                    value="financials",
                    reason="reviewed issuer activity",
                    reviewer="local_user",
                    valid_from="2026-07-11T00:00:00Z",
                    available_at="2026-07-11T00:00:00Z",
                    dependent_score_keys=("classification:A:*",),
                ),
            )
        )

    parquet_path = tmp_path / "data" / "derived" / "score_history.parquet"
    raw = pd.read_parquet(parquet_path)
    projected = score_history_frame(root=tmp_path)

    assert raw.iloc[0]["final_combined_score_10"] == 7.0
    assert pd.isna(projected.iloc[0]["final_combined_score_10"])
    assert projected.iloc[0]["classification_dependency_status"] == "classification_override_invalidated"
    assert projected.iloc[0]["analysis_status"] == "unavailable"
    assert projected.iloc[0]["execution_allowed"] is False or not bool(projected.iloc[0]["execution_allowed"])
    assert "classification_override_invalidated" in projected.iloc[0]["blocked_by"]

    current = classification_score_state(tmp_path, "A")
    append_score_run(
        pd.DataFrame(
            {
                "instrument_id": ["A"],
                "final_combined_score_10": [8.0],
                "classification_version_id": [current["version_id"]],
                "classification_invalidation_hash": [current["invalidation_token"]],
                "classification_dependency_status": ["current"],
            }
        ),
        "run-after-recompute",
        "2026-07-12",
        root=tmp_path,
    )
    refreshed = score_history_frame(root=tmp_path).set_index("run_id")
    assert refreshed.loc["run-after-recompute", "final_combined_score_10"] == 8.0
    assert refreshed.loc["run-after-recompute", "classification_dependency_status"] == "current"
