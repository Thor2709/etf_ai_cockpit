"""Focused evidence and leakage tests for ISSUE-0182's PIT panel."""

from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.data.universe_membership import record_listing_capture
from etf_cockpit.features.feature_store import FeatureDefinition, LocalFeatureStore
from etf_cockpit.features.panel import (
    PITPanelInputs,
    PanelContractError,
    build_pit_panel,
    canonical_panel_rows,
    date_grouped_folds,
    panel_evidence_inventory,
)
from etf_cockpit.validation.protocol import ValidationSpec


def _case(tmp_path):
    store = LocalFeatureStore(tmp_path)
    for identifier in ("quality_score", "value_score"):
        store.register_feature(
            FeatureDefinition(identifier, identifier, source_dataset="fundamentals")
        )
    instruments = ("A", "B")
    source = []
    for instrument, quality in (("A", 1.0), ("B", 2.0)):
        source.extend([
            {
                "instrument_id": instrument, "date": "2026-01-05",
                "available_at": "2026-01-05T10:00:00Z", "pit_grade": "observed",
                "quality_score": quality, "value_score": 3.0 - quality,
            },
            {
                "instrument_id": instrument, "date": "2026-01-05",
                "available_at": "2026-01-06T10:00:00Z", "pit_grade": "observed",
                "quality_score": 999.0, "value_score": 999.0,
            },
            {
                "instrument_id": instrument, "date": "2026-01-05",
                "available_at": "2026-01-05T09:00:00Z", "pit_grade": "approximated",
                "quality_score": 888.0, "value_score": 888.0,
            },
        ])
    membership = pd.DataFrame([
        {
            "instrument_id": instrument, "snapshot_date": "2026-01-05",
            "snapshot_complete": True, "valid_from": "2025-01-01",
            "valid_to": None, "known_at": "2026-01-05T08:00:00Z",
            "pit_grade": "observed", "source": "snapshot-test",
        } for instrument in instruments
    ])
    prices, vwce = [], []
    for day, index in (("2026-01-05", 0), ("2026-01-06", 1), ("2026-01-07", 2)):
        for instrument, initial in (("A", 100.0), ("B", 200.0)):
            prices.append({
                "instrument_id": instrument, "date": day,
                "known_at": day + "T16:00:00Z",
                "adjusted_close": initial + 2 * index,
                "is_adjusted": True, "currency": "EUR",
            })
        vwce.append({
            "instrument_id": "VWCE", "date": day,
            "known_at": day + "T16:00:00Z",
            "adjusted_close": 100.0 + index,
            "session_open_at": day + "T08:00:00Z",
            "is_adjusted": True, "currency": "EUR",
        })
    return store, pd.DataFrame(source), membership, pd.DataFrame(prices), pd.DataFrame(vwce)


def test_panel_excludes_late_and_approximated_feature_revisions(tmp_path):
    store, features, membership, prices, benchmark = _case(tmp_path)
    data = PITPanelInputs(store, features, prices, benchmark)
    panel = build_pit_panel(
        ["2026-01-05T17:00:00Z"], membership,
        ["quality_score", "value_score"], horizons=(1,), inputs=data,
    )
    assert len(panel) == 2
    assert panel["instrument_id"].tolist() == ["A", "B"]
    assert panel["quality_score"].tolist() == [1.0, 2.0]
    assert panel["fwd_total_1"].tolist() == pytest.approx([0.02, 0.01])
    assert panel["fwd_excess_1"].tolist() == pytest.approx([0.01, 0.0])
    assert panel["label_available_at_1"].tolist() == [
        "2026-01-07T08:00:00+00:00"
    ] * 2
    assert panel["label_start"].tolist() == ["2026-01-05"] * 2
    assert panel["label_end"].tolist() == ["2026-01-06"] * 2
    assert not panel["execution_allowed"].any()
    assert panel["fundamentals_available_at"].notna().all()
    pd.testing.assert_frame_equal(
        panel,
        build_pit_panel(
            ["2026-01-05T17:00:00Z"],
            membership.sample(frac=1, random_state=1),
            ["quality_score", "value_score"],
            horizons=(1,),
            inputs=PITPanelInputs(store, features.sample(frac=1, random_state=4), prices, benchmark),
        ),
    )


def test_membership_snapshot_after_decision_is_not_used(tmp_path):
    store, features, membership, prices, benchmark = _case(tmp_path)
    membership["known_at"] = "2026-01-06T10:00:00Z"
    with pytest.raises(PanelContractError, match="no complete observed membership"):
        build_pit_panel(
            ["2026-01-05T17:00:00Z"], membership,
            ["quality_score"], horizons=(1,),
            inputs=PITPanelInputs(store, features, prices, benchmark),
        )


def test_panel_uses_local_captured_membership_as_known_and_roundtrips_versions(tmp_path):
    store, features, _, prices, benchmark = _case(tmp_path)
    scope = "listing:euronext_oslo:all"
    record_listing_capture([{"instrument_id": "A"}, {"instrument_id": "B"}], "fixture", scope,
                           "2026-01-04T08:00:00Z", root=tmp_path)
    record_listing_capture([{"instrument_id": "A"}, {"instrument_id": "B"}], "fixture", scope,
                           "2026-01-05T08:00:00Z", root=tmp_path)
    record_listing_capture([{"instrument_id": "B"}], "fixture", scope,
                           "2026-01-05T19:00:00Z", root=tmp_path)
    panel = build_pit_panel(
        ["2026-01-05T17:00:00Z"], scope, ["quality_score"],
        horizons=(1,), inputs=PITPanelInputs(store, features, prices, benchmark),
    )
    assert panel["instrument_id"].tolist() == ["A", "B"]
    assert panel.attrs["membership_source"] == f"universe_membership:{scope}"
    artifact = tmp_path / "panel.parquet"
    panel.to_parquet(artifact, index=False)
    restored = pd.read_parquet(artifact)
    for version in ("panel_version", "feature_set_version", "label_version"):
        assert restored[version].tolist() == panel[version].tolist()


def test_panel_purges_late_label_evidence_and_keeps_observed_delisting(tmp_path):
    store, features, membership, prices, benchmark = _case(tmp_path)
    a_target = prices["instrument_id"].eq("A") & prices["date"].eq("2026-01-06")
    b_target = prices["instrument_id"].eq("B") & prices["date"].eq("2026-01-06")
    prices.loc[a_target, "known_at"] = "2026-01-08T16:00:00Z"
    prices["delisted"] = b_target
    prices.loc[b_target, "delisting_return"] = -1.0
    panel = build_pit_panel(
        ["2026-01-05T17:00:00Z"], membership, ["quality_score"], horizons=(1,),
        inputs=PITPanelInputs(store, features, prices, benchmark),
    ).set_index("instrument_id")
    assert pd.isna(panel.loc["A", "fwd_total_1"])
    assert pd.isna(panel.loc["A", "label_available_at"])
    assert panel.loc["B", "fwd_total_1"] == -1.0
    assert panel.loc["B", "delisted"]
    assert panel.loc["B", "label_available_at"] == "2026-01-07T08:00:00+00:00"


def test_cross_source_feature_dependencies_keep_group_times_and_never_zero_fill(tmp_path):
    store, features, membership, prices, benchmark = _case(tmp_path)
    store.register_feature(FeatureDefinition(
        "momentum_score", "momentum_score", dependencies=("value_score",),
        source_dataset="momentum", missing_policy="zero",
    ))
    features["momentum_score"] = None
    features.loc[features["instrument_id"].eq("A") & features["available_at"].eq(
        "2026-01-05T10:00:00Z"), "momentum_score"] = 0.25
    features["known_at"] = features["available_at"]
    features.loc[features["instrument_id"].eq("B") & features["available_at"].eq(
        "2026-01-05T10:00:00Z"), "known_at"] = "2026-01-06T03:00:00Z"
    panel = build_pit_panel(
        ["2026-01-05T17:00:00Z"], membership, ["value_score", "momentum_score"], horizons=(1,),
        inputs=PITPanelInputs(store, features, prices, benchmark),
    ).set_index("instrument_id")
    assert panel.loc["A", "momentum_available_at"] == "2026-01-05T10:00:00+00:00"
    assert pd.isna(panel.loc["B", "value_score"])
    assert pd.isna(panel.loc["B", "momentum_score"])
    assert pd.isna(panel.loc["B", "momentum_available_at"])


def test_effective_time_is_part_of_the_feature_cutoff(tmp_path):
    store, features, membership, prices, benchmark = _case(tmp_path)
    features.loc[features["instrument_id"].eq("A"), "date"] = "2026-01-05T19:00:00Z"
    panel = build_pit_panel(
        ["2026-01-05T17:00:00Z"], membership, ["quality_score"], horizons=(1,),
        inputs=PITPanelInputs(store, features, prices, benchmark),
    ).set_index("instrument_id")
    assert pd.isna(panel.loc["A", "quality_score"])
    assert panel.loc["B", "quality_score"] == 2.0


def test_fold_splits_are_by_date_with_label_availability_purge():
    rows = []
    start = pd.Timestamp("2026-01-01T17:00:00Z")
    for i in range(18):
        cutoff = start + pd.Timedelta(days=i)
        available = cutoff + pd.Timedelta(days=2)
        for instrument in ("A", "B"):
            rows.append({
                "decision_time": cutoff.isoformat(), "instrument_id": instrument,
                "label_available_at": available.isoformat(),
            })
    panel = pd.DataFrame(rows)
    spec = ValidationSpec(
        n_splits=2, test_size=3, horizon=1, final_test_size=2,
        embargo=0, bootstrap_repetitions=1,
    )
    panel["fwd_total_1"] = 0.002
    panel["label_available_at"] = pd.to_datetime(panel["label_available_at"], utc=True)
    panel["label_available_at_1"] = panel["label_available_at"]
    panel.attrs["as_of"] = (start + pd.Timedelta(days=22)).isoformat()
    original = date_grouped_folds(panel, spec)
    shuffled = date_grouped_folds(panel.sample(frac=1, random_state=2), spec)
    assert original == shuffled
    canonical = canonical_panel_rows(panel)
    for fold in original:
        assert set(
            pd.to_datetime(canonical.iloc[list(fold.train_rows)]["decision_time"], utc=True)
            .dt.date.astype(str)
        ).issubset(set(fold.train_dates))
        assert set(
            pd.to_datetime(canonical.iloc[list(fold.validation_rows)]["decision_time"], utc=True)
            .dt.date.astype(str)
        ) == set(fold.validation_dates)
        assert set(fold.train_dates).isdisjoint(fold.validation_dates)
        assert len(fold.validation_rows) == 6
        assert len(fold.train_rows) % 2 == 0
        assert max(fold.train_dates) < min(fold.validation_dates)
    inventory = panel_evidence_inventory(panel, folds=original)
    for fold in original:
        assert inventory["matured_labels_by_fold"][fold.fold]["1"] == {
            "train": len(fold.train_rows), "validation": len(fold.validation_rows),
        }


def test_inventory_counts_dates_not_instrument_rows():
    panel = pd.DataFrame([
        {
            "decision_time": "2026-01-05T17:00:00Z",
            "instrument_id": symbol,
            "fwd_total_1": 0.01,
            "label_end_1": "2026-01-06",
            "label_available_at_1": "2026-01-07T08:00:00Z",
            "delisted": symbol == "A",
        } for symbol in ("A", "B")
    ])
    panel.attrs.update({
        "as_of": "2026-01-08T17:00:00Z",
        "membership_source": "fixture",
        "membership_pit_grade": "observed",
    })
    report = panel_evidence_inventory(panel)
    assert report["decision_dates"] == 1
    assert report["instruments_per_date"] == {"2026-01-05": 2}
    assert report["matured_labels"] == {"1": 2}
    assert report["non_overlapping_periods"] == {"1": 1}
    assert report["delisted_share"] == 0.5
