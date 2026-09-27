from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages import what_changed
from etf_cockpit.application import run_change_context
from etf_cockpit.application.run_change_context import upstream_run_context
from etf_cockpit.core.versioning import sign_run_manifest
from etf_cockpit.data.run_changes import UPSTREAM_CHANGE_DIMENSIONS, compare_runs, select_comparison_runs


def _row(run_id: str, completed_at: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "run_id": run_id,
        "run_completed_at": completed_at,
        "instrument_id": "A",
        "final_combined_score_10": 5.0,
        "final_action": "watchlist",
        "source_snapshot_hash": "src-1",
        "source_vintage_hash": "vin-1",
        "classification_version_id": "cls-1",
        "classification_invalidation_hash": "inv-1",
        "classification_dependency_status": "current",
        "formula_version": "score-engine-v3.0.0",
        "formula_checksum": "f-1",
        "gate_policy_version": "gate-1",
        "gate_policy_checksum": "g-1",
        "score_schema_version": "2.0",
        "portfolio_snapshot_checksum": "p-1",
    }
    row.update(overrides)
    return row


def _history(**new_overrides: object) -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("old", "2026-09-01T10:00:00+00:00"),
            _row("new", "2026-09-02T10:00:00+00:00", **new_overrides),
        ]
    )


def test_upstream_dimensions_are_unchanged_when_recorded_inputs_match() -> None:
    change = compare_runs(_history(), "new", "old").changes[0]

    assert set(change.upstream_changes) == set(UPSTREAM_CHANGE_DIMENSIONS)
    assert not any(changed for _current, _previous, changed in change.upstream_changes.values())
    assert change.causal_paths == ()
    assert change.summary == "No tracked changes."


def test_each_upstream_change_is_explained_with_a_causal_path() -> None:
    change = compare_runs(
        _history(
            source_vintage_hash="vin-2",
            classification_version_id="cls-2",
            gate_policy_checksum="g-2",
            portfolio_snapshot_checksum="p-2",
        ),
        "new",
        "old",
    ).changes[0]

    assert change.dimension_changes["source_revisions"] is True
    assert change.dimension_changes["classification"] is True
    assert change.dimension_changes["policy_versions"] is True
    assert change.dimension_statuses["portfolio_targets"] == "unavailable"
    assert change.causal_paths == ()
    assert change.causal_paths_status == "unavailable"


def test_unrecorded_upstream_inputs_stay_explicitly_unavailable() -> None:
    legacy = pd.DataFrame(
        [
            {"run_id": "old", "instrument_id": "A", "final_combined_score_10": 5.0},
            {"run_id": "new", "instrument_id": "A", "final_combined_score_10": 5.0},
        ]
    )

    change = compare_runs(legacy, "new", "old").changes[0]

    assert change.upstream_changes["classification"] == ("unavailable", "unavailable", None)
    assert change.upstream_changes["portfolio_targets"] == ("unavailable", "unavailable", None)
    assert change.causal_paths == ()


def test_corrections_are_read_point_in_time_at_each_run(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def summary(self, *, root, decision_time):
        calls.append(decision_time)
        later = decision_time.startswith("2026-09-02")
        return {
            "status": "available",
            "finding_count": 1,
            "invalidation_token": "t-2" if later else "t-1",
            "correction_count": 2 if later else 1,
            "unresolved_count": 0 if later else 1,
        }

    monkeypatch.setattr(run_change_context.AnomalyLedger, "summary", summary)

    context = upstream_run_context(_history(), "new", "old", root=tmp_path)

    assert calls == ["2026-09-02T10:00:00+00:00", "2026-09-01T10:00:00+00:00"]
    corrections = context["corrections"]
    assert corrections["changed"] is True
    assert (corrections["previous_corrections"], corrections["current_corrections"]) == (1, 2)
    assert context["execution_allowed"] is False


def test_corrections_without_completion_times_are_unavailable(tmp_path) -> None:
    history = _history().drop(columns=["run_completed_at"])

    corrections = upstream_run_context(history, "new", "old", root=tmp_path)["corrections"]

    assert corrections["status"] == "unavailable"
    assert corrections["changed"] is False


def _manifest(root, run_id: str, dependencies: list[dict[str, object]]) -> None:
    path = root / "data" / "derived" / "run_manifests" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_id": run_id, "dependencies": dependencies}), encoding="utf-8")


def test_dependency_changes_are_diffed_from_run_manifests(tmp_path) -> None:
    _manifest(
        tmp_path,
        "old",
        [
            {"artifact_id": "dataset:prices", "version": "1", "content_hash": "a"},
            {"artifact_id": "formula:score-engine-v3", "version": "3.0.0", "content_hash": "f"},
            {"artifact_id": "model:toto", "version": "1", "content_hash": "t"},
        ],
    )
    _manifest(
        tmp_path,
        "new",
        [
            {"artifact_id": "dataset:prices", "version": "1", "content_hash": "b"},
            {"artifact_id": "formula:score-engine-v3", "version": "3.1.0", "content_hash": "g"},
            {"artifact_id": "policy:gate", "version": "2", "content_hash": "p"},
        ],
    )

    dependencies = upstream_run_context(_history(), "new", "old", root=tmp_path)["dependencies"]

    assert dependencies["status"] == "unavailable"
    assert dependencies["changed_artifacts"] == ()


def test_missing_manifest_and_paper_ledger_are_explicitly_unavailable(tmp_path) -> None:
    _manifest(tmp_path, "new", [])

    context = upstream_run_context(_history(), "new", "old", root=tmp_path)

    assert context["dependencies"]["status"] == "unavailable"
    assert context["dependencies"]["changed_artifacts"] == ()
    assert context["paper_state"]["status"] == "unavailable"
    assert context["paper_state"]["comparison"] == "unavailable"


def _texts(control: object) -> list[str]:
    found: list[str] = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        found.append(value)
    for name in ("controls", "rows", "cells", "columns"):
        children = getattr(control, name, None)
        for child in children if isinstance(children, (list, tuple)) else ():
            found.extend(_texts(child))
    for name in ("content", "label"):
        child = getattr(control, name, None)
        if child is not None and not isinstance(child, str):
            found.extend(_texts(child))
    return found


def test_what_changed_page_renders_upstream_reasons_and_context(monkeypatch) -> None:
    history = _history(classification_version_id="cls-2")
    monkeypatch.setattr(what_changed, "score_history_frame", lambda: history)
    monkeypatch.setattr(
        what_changed,
        "upstream_run_context",
        lambda *_args, **_kwargs: {
            "corrections": {"status": "unavailable", "reason": "no anomaly findings were recorded at either run", "changed": False},
            "dependencies": {"status": "available", "changed_artifacts": ("policy:gate: version 1 -> 2",)},
                "paper_state": {
                    "status": "unavailable",
                    "comparison": "unavailable",
                    "reason": "run completion timestamps are unavailable",
                },
            "execution_allowed": False,
        },
    )

    text = "\n".join(_texts(what_changed.what_changed_page(None, SimpleNamespace())))

    for expected in (
        "Upstream context",
        "Data corrections: unavailable",
        "policy:gate: version 1 -> 2",
        "Paper/order state: unavailable",
        "Classification",
    ):
        assert expected in text


def test_legacy_history_defaults_are_not_mistaken_for_recorded_upstream_inputs() -> None:
    from etf_cockpit.data.score_history import _normalise_history_frame as normalise

    legacy = normalise(pd.DataFrame([{"run_id": "old", "instrument_id": "A", "final_combined_score_10": 5.0}]))
    modern = pd.DataFrame([_row("new", "2026-09-02T10:00:00+00:00")])
    history = pd.concat([legacy, modern], ignore_index=True)

    change = compare_runs(history, "new", "old").changes[0]

    assert change.upstream_changes["classification"][1] == "unavailable"
    assert not any(changed for _current, _previous, changed in change.upstream_changes.values())
    assert change.causal_paths == ()


def test_removed_instruments_carry_no_upstream_reasons() -> None:
    history = pd.DataFrame([_row("old", "2026-09-01T10:00:00+00:00"), _row("new", "2026-09-02T10:00:00+00:00", instrument_id="B")])

    removed = next(change for change in compare_runs(history, "new", "old").changes if change.instrument_id == "A")

    assert removed.current_action == "unavailable"
    assert removed.causal_paths == ()
    assert "upstream changed" not in removed.summary


def test_empty_readable_anomaly_ledger_reports_zero_not_unavailable(tmp_path) -> None:
    from etf_cockpit.data.local_storage import TransactionalStore

    TransactionalStore(tmp_path).close()

    corrections = upstream_run_context(_history(), "new", "old", root=tmp_path)["corrections"]

    assert corrections["status"] == "available"
    assert corrections["changed"] is False
    assert (corrections["previous_corrections"], corrections["current_corrections"]) == (0, 0)


def test_naive_completion_time_is_not_used_as_a_knowledge_cutoff(tmp_path) -> None:
    history = _history()
    history["run_completed_at"] = ["2026-09-01", "2026-09-02"]

    corrections = upstream_run_context(history, "new", "old", root=tmp_path)["corrections"]

    assert corrections["status"] == "unavailable"
    assert "timezone" in corrections["reason"]


def test_storage_errors_fail_closed_instead_of_breaking_the_page(monkeypatch, tmp_path) -> None:
    import sqlite3

    def locked(self, *, root, decision_time):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(run_change_context.AnomalyLedger, "summary", locked)

    context = upstream_run_context(_history(), "new", "old", root=tmp_path)

    assert context["corrections"]["status"] == "unavailable"
    assert "OperationalError" in context["corrections"]["reason"]
    assert context["execution_allowed"] is False


def test_source_vintage_change_without_manifest_edges_has_no_causal_path(tmp_path) -> None:
    for run_id, vintage in (("old", "v1"), ("new", "v2")):
        payload = {
            "schema_version": "1.1",
            "manifest_version": "1.1.0",
            "run_id": run_id,
            "dependencies": [{"artifact_id": "dataset:prices", "version": "1", "content_hash": vintage}],
        }
        path = tmp_path / "data" / "derived" / "run_manifests" / f"{run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sign_run_manifest(payload)), encoding="utf-8")
    report = compare_runs(_history(source_vintage_hash="v2"), "new", "old", root=tmp_path)
    assert report.changes[0].causal_paths == ()
    assert report.changes[0].causal_paths_status == "unavailable"


def test_checksum_only_portfolio_rows_are_unavailable() -> None:
    change = compare_runs(_history(portfolio_snapshot_checksum="old"), "new", "old").changes[0]
    assert change.dimension_statuses["portfolio_targets"] == "unavailable"
    assert change.upstream_changes["portfolio_targets"][2] is None


def test_one_sided_metadata_renders_na() -> None:
    assert what_changed._upstream_cell(("new", "unavailable", None))[0] == "N/A"


def test_formula_checksum_on_one_side_is_not_changed() -> None:
    history = _history()
    history.loc[history["run_id"].eq("old"), "formula_checksum"] = None
    change = compare_runs(history, "new", "old").changes[0]
    assert change.dimension_statuses["policy_versions"] == "unavailable"
    assert change.upstream_changes["policy_versions"][2] is None


def test_timezone_offsets_are_ordered_in_utc() -> None:
    history = _history()
    history.loc[history["run_id"].eq("old"), "run_completed_at"] = "2026-09-02T00:30:00+00:00"
    history.loc[history["run_id"].eq("new"), "run_completed_at"] = "2026-09-02T01:00:00+02:00"
    assert select_comparison_runs(history) == ("old", "new")


def test_tampered_manifest_is_unavailable(tmp_path) -> None:
    payload = sign_run_manifest({"schema_version": "1.1", "run_id": "new", "dependencies": []})
    payload["dependencies"] = [{"artifact_id": "tampered"}]
    path = tmp_path / "data" / "derived" / "run_manifests" / "new.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    context = upstream_run_context(_history(), "new", "old", root=tmp_path)
    assert context["dependencies"]["status"] == "unavailable"


def test_paper_order_after_both_runs_is_not_shown(monkeypatch, tmp_path) -> None:
    class FakeLedger:
        path = tmp_path / "ledger.jsonl"

        def __init__(self, _root):
            self.path.touch()

        def _read_events(self):
            return [
                {"occurred_at": "2026-09-03T00:00:00+00:00", "event_type": "order_accepted"},
            ]

        def _replay(self, events):
            return {"orders": {"late": {"instrument_id": "LATE", "status": "accepted"}} if events else {}}

    monkeypatch.setattr("etf_cockpit.portfolio.paper_trading.PaperLedger", FakeLedger)
    context = upstream_run_context(_history(), "new", "old", root=tmp_path)
    paper = context["paper_state"]
    assert paper["status"] == "unavailable"
    assert "trustworthy recorded_at" in paper["reason"]
