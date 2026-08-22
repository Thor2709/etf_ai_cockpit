from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages.instrument_detail import _driver_table
from etf_cockpit.app.selectors.instrument_detail import _feature_driver_panel
from etf_cockpit.app.selectors.instrument_detail import _normalise_feature_driver_frame
from etf_cockpit.data import trust_artifacts as trust
from etf_cockpit.signals.feature_drivers import build_feature_drivers


def test_feature_driver_delta_is_descriptive_and_traceable() -> None:
    scores = pd.DataFrame(
        [
            {
                "instrument_id": "A",
                "component": "momentum",
                "normalised_score_10": 8.0,
                "peer_group": "equity-growth",
                "historical_contribution": 0.12,
                "coverage": 0.8,
                "uncertainty": "medium",
                "interaction": "momentum × trend: observed co-movement",
                "counterfactual_sensitivity": -0.04,
                "source_id": "prices:adjusted",
                "source_authority": "vendor_unofficial",
                "source_span": "prices.parquet#2026-07-10",
                "conflict": "no_known_conflict",
                "contribution": 0.45,
                "why": "descriptive momentum evidence",
            },
            {
                "instrument_id": "B",
                "component": "momentum",
                "normalised_score_10": 4.0,
                "peer_group": "equity-growth",
                "source_id": "prices:adjusted",
                "source_authority": "vendor_unofficial",
                "source_span": "prices.parquet#2026-07-10",
            },
        ]
    )

    drivers = build_feature_drivers(scores)
    row = drivers.loc[drivers["instrument_id"].eq("A")].iloc[0]

    assert row["peer_percentile"] == 100.0
    assert row["historical_contribution"] == 0.12
    assert row["coverage"] == 0.8
    assert row["uncertainty"] == "medium"
    assert row["interaction"] == "momentum × trend: observed co-movement"
    assert row["counterfactual_sensitivity"] == -0.04
    assert row["source_span"] == "prices.parquet#2026-07-10"
    assert row["source_authority"] == "vendor_unofficial"
    assert row["missingness"] == "not_missing"
    assert row["conflict"] == "no_known_conflict"
    assert row["contribution"] == 0.45
    assert bool(row["execution_allowed"]) is False
    assert "causal" not in str(row["driver_text"]).casefold()


def test_feature_driver_writer_readback_preserves_canonical_evidence(tmp_path, monkeypatch) -> None:
    output = tmp_path / "feature_drivers.parquet"
    monkeypatch.setattr(trust, "FEATURE_DRIVERS_PATH", output)
    score = SimpleNamespace(
        display_id="A",
        latest_date="2026-07-10",
        components=[
            SimpleNamespace(
                key="momentum",
                raw_score=0.8,
                score_10=8.0,
                authority="high",
                why="descriptive evidence",
                source_id="prices:adjusted",
                source_authority="vendor_unofficial",
                as_of_date="2026-07-10",
                freshness_status="ok",
                conflict_id=None,
            )
        ],
        canonical_score=SimpleNamespace(
            coverage=0.75,
            components=(
                {
                    "key": "momentum",
                    "peer_group": "equity-growth",
                    "source_authority": "vendor_unofficial",
                    "uncertainty": "low",
                    "contribution_raw": 0.31,
                    "conflict_id": None,
                },
            ),
        ),
    )

    path = trust.write_feature_drivers([score])
    persisted = pd.read_parquet(path)

    assert persisted.loc[0, "peer_group"] == "equity-growth"
    assert persisted.loc[0, "coverage"] == 0.75
    assert persisted.loc[0, "uncertainty"] == "low"
    assert persisted.loc[0, "contribution"] == 0.31
    assert persisted.loc[0, "source_span"] == "unavailable"
    assert persisted["execution_allowed"].eq(False).all()


def test_selector_fail_closes_malformed_evidence_and_ui_exposes_traceability(monkeypatch, tmp_path) -> None:
    path = tmp_path / "feature_drivers.parquet"
    pd.DataFrame(
        [
            {
                "instrument_id": "A",
                "component": "quality",
                "normalised_score": "not-a-score",
                "execution_allowed": True,
                "source_span": "",
            }
        ]
    ).to_parquet(path)
    monkeypatch.setattr("etf_cockpit.app.selectors.instrument_detail.FEATURE_DRIVERS_PATH", path)

    panel = _feature_driver_panel("A")
    row = panel["rows"][0]
    assert panel["execution_allowed"] is False
    assert row["execution_allowed"] is False
    assert row["direction"] == "missing"
    assert row["missingness"] == "missing"
    assert row["source_span"] == "unavailable"
    assert row["conflict"] == "unavailable"
    assert row["peer_percentile"] == "unavailable"

    table = _driver_table("Missing / N/A", [row])
    data_table = table.controls[1]
    labels = [column.label.value for column in data_table.columns]
    assert {"Peer group", "Peer percentile", "Historical contribution", "Coverage", "Uncertainty", "Interaction", "Counterfactual sensitivity", "Source authority", "Source span", "Missingness", "Conflict", "Contribution"} <= set(labels)


def test_selector_legacy_rows_receive_unavailable_delta_fields() -> None:
    normalised = _normalise_feature_driver_frame(
        pd.DataFrame([{"instrument_id": "A", "component": "quality", "normalised_score": 7.0}])
    )

    row = normalised.iloc[0]
    assert row["missingness"] == "not_missing"
    assert row["source_span"] == "unavailable"
    assert row["source_authority"] == "unavailable"
    assert row["conflict"] == "unavailable"
    assert row["contribution"] == "unavailable"
    assert bool(row["execution_allowed"]) is False


def test_mixed_numeric_evidence_fails_closed_and_zero_survives_write_readback_and_ui(
    tmp_path,
    monkeypatch,
) -> None:
    source = pd.DataFrame(
        [
            {
                "instrument_id": "A",
                "component": "valid-zero",
                "normalised_score": 7.0,
                "peer_group": "explicit-cohort",
                "peer_percentile": 0,
                "historical_contribution": 0,
                "coverage": 0,
                "uncertainty": 0,
                "counterfactual_sensitivity": 0,
                "contribution": 0,
                "execution_allowed": True,
            },
            {
                "instrument_id": "A",
                "component": "malformed",
                "normalised_score": 5.0,
                "peer_group": "unavailable",
                "peer_percentile": 101,
                "historical_contribution": float("inf"),
                "coverage": -0.1,
                "uncertainty": float("-inf"),
                "counterfactual_sensitivity": "not-a-number",
                "contribution": "arbitrary",
                "execution_allowed": True,
            },
            {
                "instrument_id": "A",
                "component": "missing",
                "normalised_score": 3.0,
                "peer_group": "unavailable",
                "peer_percentile": None,
                "historical_contribution": None,
                "coverage": None,
                "uncertainty": None,
                "counterfactual_sensitivity": None,
                "contribution": None,
                "execution_allowed": True,
            },
        ]
    )

    generated = build_feature_drivers(source).set_index("component")
    for column in (
        "peer_percentile",
        "historical_contribution",
        "coverage",
        "counterfactual_sensitivity",
        "contribution",
    ):
        assert generated.loc["valid-zero", column] == 0.0
        assert pd.isna(generated.loc["malformed", column])
        assert pd.isna(generated.loc["missing", column])
    assert generated.loc["valid-zero", "uncertainty"] == "0.0"
    assert generated.loc["malformed", "uncertainty"] == "unavailable"
    assert generated.loc["missing", "uncertainty"] == "unavailable"
    assert generated["execution_allowed"].eq(False).all()

    output = tmp_path / "feature_drivers.parquet"
    monkeypatch.setattr(trust, "FEATURE_DRIVERS_PATH", output)
    monkeypatch.setattr("etf_cockpit.app.selectors.instrument_detail.FEATURE_DRIVERS_PATH", output)
    trust.write_feature_drivers(source)
    persisted = pd.read_parquet(output).set_index("component")
    assert persisted.loc["valid-zero", "counterfactual_sensitivity"] == 0.0
    assert pd.isna(persisted.loc["malformed", "peer_percentile"])
    assert pd.isna(persisted.loc["missing", "coverage"])
    assert persisted["execution_allowed"].eq(False).all()

    panel = _feature_driver_panel("A")
    rows = {row["component"]: row for row in panel["rows"]}
    assert panel["execution_allowed"] is False
    for column in (
        "peer_percentile",
        "historical_contribution",
        "coverage",
        "counterfactual_sensitivity",
        "contribution",
    ):
        assert rows["valid-zero"][column] == 0.0
        assert rows["malformed"][column] == "unavailable"
        assert rows["missing"][column] == "unavailable"
    assert rows["valid-zero"]["uncertainty"] == "0.0"
    assert rows["malformed"]["uncertainty"] == "unavailable"
    assert rows["missing"]["uncertainty"] == "unavailable"
    assert all(row["execution_allowed"] is False for row in rows.values())

    table = _driver_table("Mixed evidence", [rows["valid-zero"], rows["malformed"]])
    data_table = table.controls[1]
    labels = [column.label.value for column in data_table.columns]
    first = dict(zip(labels, (cell.content.value for cell in data_table.rows[0].cells), strict=True))
    second = dict(zip(labels, (cell.content.value for cell in data_table.rows[1].cells), strict=True))
    for label in (
        "Peer percentile",
        "Historical contribution",
        "Coverage",
        "Uncertainty",
        "Counterfactual sensitivity",
        "Contribution",
    ):
        assert first[label] == "0.0"
        assert second[label] == "unavailable"
