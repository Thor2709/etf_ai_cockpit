from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from etf_cockpit.app.pages.instrument_detail import _driver_table
from etf_cockpit.app.pages.trust_evidence import FEATURE_DRIVER_EVIDENCE_COLUMNS
from etf_cockpit.app.pages.trust_evidence import _table_panel
from etf_cockpit.app.selectors.instrument_detail import _feature_driver_panel
from etf_cockpit.app.selectors.instrument_detail import _normalise_feature_driver_frame
from etf_cockpit.app.selectors.instrument_detail import normalise_feature_driver_frame
from etf_cockpit.data import trust_artifacts as trust
from etf_cockpit.signals.feature_drivers import build_feature_drivers
from etf_cockpit.signals.feature_drivers import claim_binding_hash
from etf_cockpit.signals.feature_drivers import deterministic_driver_claim
from etf_cockpit.signals.feature_drivers import FEATURE_DRIVER_COLUMNS


VALID_VINTAGE = "a" * 64


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
                "source_vintage_hash": VALID_VINTAGE,
                "as_of_date": "2026-07-10",
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
                "source_vintage_hash": VALID_VINTAGE,
                "as_of_date": "2026-07-10",
            },
        ]
    )

    drivers = build_feature_drivers(scores)
    row = drivers.loc[drivers["instrument_id"].eq("A")].iloc[0]

    assert row["peer_percentile"] == 100.0
    assert row["historical_contribution"] == 0.12
    assert row["coverage"] == 0.8
    assert row["uncertainty"] == "medium"
    assert row["interaction"] == "unavailable"
    assert row["counterfactual_sensitivity"] == -0.04
    assert row["source_span"] == "prices.parquet#2026-07-10"
    assert row["source_authority"] == "vendor_unofficial"
    assert row["missingness"] == "not_missing"
    assert row["conflict"] == "no_known_conflict"
    assert row["contribution"] == 0.45
    assert bool(row["execution_allowed"]) is False
    assert "causal" not in str(row["driver_text"]).casefold()
    claim = deterministic_driver_claim("momentum", 8.0)
    assert row["driver_text"] == claim
    assert row["claim_hash"] == claim_binding_hash(
        claim,
        VALID_VINTAGE,
        "prices.parquet#2026-07-10",
        "vendor_unofficial",
    )


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
            source_vintage_hash=VALID_VINTAGE,
        ),
    )

    path = trust.write_feature_drivers([score])
    persisted = pd.read_parquet(path)

    assert persisted.loc[0, "peer_group"] == "equity-growth"
    assert persisted.loc[0, "coverage"] == 0.75
    assert persisted.loc[0, "uncertainty"] == "low"
    assert persisted.loc[0, "contribution"] == 0.31
    assert persisted.loc[0, "source_vintage_hash"] == VALID_VINTAGE
    assert persisted.loc[0, "source_span"] == "unavailable"
    assert persisted.loc[0, "driver_text"] == (
        "unavailable (non-traceable claim; source provenance unavailable)."
    )
    assert persisted.loc[0, "claim_hash"] == "unavailable"
    assert persisted["execution_allowed"].eq(False).all()


def test_selector_fail_closes_malformed_evidence_and_ui_exposes_traceability(monkeypatch, tmp_path) -> None:
    path = tmp_path / "feature_drivers.parquet"
    pd.DataFrame(
        [
            {
                "instrument_id": "A",
                "component": "quality",
                "normalised_score": "not-a-score",
                "direction": "positive",
                "missingness": "not_missing",
                "execution_allowed": True,
                "source_authority": 123,
                "source_span": True,
                "source_vintage_hash": [VALID_VINTAGE],
                "driver_text": "quality causes returns",
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
    assert row["normalised_score"] == "unavailable"
    assert row["source_authority"] == "unavailable"
    assert row["source_span"] == "unavailable"
    assert row["source_vintage_hash"] == "unavailable"
    assert row["driver_text"].startswith("unavailable (non-traceable claim;")
    assert row["claim_hash"] == "unavailable"
    assert row["conflict"] == "unavailable"
    assert row["peer_percentile"] == "unavailable"

    table = _driver_table("Missing / N/A", [row])
    data_table = table.controls[1]
    labels = [column.label.value for column in data_table.columns]
    assert {"Peer group", "Peer percentile", "Historical contribution", "Coverage", "Uncertainty", "Interaction", "Counterfactual sensitivity", "Source authority", "Source span", "Source vintage hash", "Claim hash", "Missingness", "Conflict", "Contribution"} <= set(labels)


def test_selector_rejects_claim_content_inconsistent_with_its_binding() -> None:
    claim = deterministic_driver_claim("quality", 7.0)
    normalised = _normalise_feature_driver_frame(
        pd.DataFrame(
            [
                {
                    "instrument_id": "A",
                    "component": "quality",
                    "normalised_score": 7.0,
                    "source_authority": "official",
                    "source_span": "quality.parquet#2026-07-10",
                    "source_vintage_hash": VALID_VINTAGE,
                    "as_of_date": "2026-07-10",
                    "driver_text": "tampered claim text",
                    "claim_hash": claim_binding_hash(
                        claim,
                        VALID_VINTAGE,
                        "quality.parquet#2026-07-10",
                        "official",
                    ),
                }
            ]
        )
    )

    row = normalised.iloc[0]
    assert row["driver_text"] == (
        "unavailable (non-traceable claim; claim content inconsistent)."
    )
    assert row["claim_hash"] == "unavailable"


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
        "historical_contribution",
        "coverage",
        "counterfactual_sensitivity",
        "contribution",
    ):
        assert generated.loc["valid-zero", column] == 0.0
        assert pd.isna(generated.loc["malformed", column])
        assert pd.isna(generated.loc["missing", column])
    assert generated.loc["valid-zero", "peer_percentile"] == 0.0
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
    assert persisted.loc["valid-zero", "peer_percentile"] == 0.0
    assert pd.isna(persisted.loc["malformed", "peer_percentile"])
    assert pd.isna(persisted.loc["missing", "coverage"])
    assert persisted["execution_allowed"].eq(False).all()

    panel = _feature_driver_panel("A")
    rows = {row["component"]: row for row in panel["rows"]}
    assert panel["execution_allowed"] is False
    for column in (
        "historical_contribution",
        "coverage",
        "counterfactual_sensitivity",
        "contribution",
    ):
        assert rows["valid-zero"][column] == 0.0
        assert rows["malformed"][column] == "unavailable"
        assert rows["missing"][column] == "unavailable"
    assert rows["valid-zero"]["peer_percentile"] == 0.0
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
        "Historical contribution",
        "Coverage",
        "Uncertainty",
        "Counterfactual sensitivity",
        "Contribution",
    ):
        assert first[label] == "0.0"
        assert second[label] == "unavailable"
    assert first["Peer percentile"] == "0.0"


def test_object_path_replaces_causal_claims_with_deterministic_bound_claim() -> None:
    score = SimpleNamespace(
        display_id="A",
        latest_date="2026-07-10",
        components=[
            SimpleNamespace(
                key="momentum",
                raw_score=0.8,
                score_10=8.0,
                authority="high",
                why="momentum causes returns",
                source_id="prices:adjusted",
                source_authority="vendor_unofficial",
                source_span="prices.parquet#2026-07-10",
            )
        ],
        canonical_score=SimpleNamespace(source_vintage_hash=VALID_VINTAGE, components=()),
    )

    row = build_feature_drivers([score]).iloc[0]

    claim = deterministic_driver_claim("momentum", 8.0)
    assert row["driver_text"] == claim
    assert row["claim_hash"] == claim_binding_hash(
        claim,
        VALID_VINTAGE,
        "prices.parquet#2026-07-10",
        "vendor_unofficial",
    )
    assert row["source_vintage_hash"] == VALID_VINTAGE


def test_peer_percentile_does_not_mix_vintages() -> None:
    source = pd.DataFrame(
        [
            {"instrument_id": "A", "component": "momentum", "normalised_score": 8.0, "peer_group": "growth", "as_of_date": "2026-07-10", "source_vintage_hash": VALID_VINTAGE},
            {"instrument_id": "B", "component": "momentum", "normalised_score": 4.0, "peer_group": "growth", "as_of_date": "2026-07-10", "source_vintage_hash": VALID_VINTAGE},
            {"instrument_id": "C", "component": "momentum", "normalised_score": 10.0, "peer_group": "growth", "as_of_date": "2026-07-10", "source_vintage_hash": "b" * 64},
        ]
    )

    rows = build_feature_drivers(source).set_index("instrument_id")

    assert rows.loc["A", "peer_percentile"] == 100.0
    assert rows.loc["B", "peer_percentile"] == 50.0
    assert pd.isna(rows.loc["C", "peer_percentile"])


def test_peer_percentile_rejects_malformed_dates_and_normalises_timestamps() -> None:
    source = pd.DataFrame(
        [
            {"instrument_id": "A", "component": "momentum", "normalised_score": 8.0, "peer_group": "growth", "as_of_date": "not-a-date", "source_vintage_hash": VALID_VINTAGE},
            {"instrument_id": "B", "component": "momentum", "normalised_score": 4.0, "peer_group": "growth", "as_of_date": ["2026-07-10"], "source_vintage_hash": VALID_VINTAGE},
            {"instrument_id": "C", "component": "momentum", "normalised_score": 8.0, "peer_group": "growth", "as_of_date": "2026-07-10T01:00:00+01:00", "source_vintage_hash": "b" * 64},
            {"instrument_id": "D", "component": "momentum", "normalised_score": 4.0, "peer_group": "growth", "as_of_date": pd.Timestamp("2026-07-10T00:00:00Z"), "source_vintage_hash": "b" * 64},
        ]
    )

    rows = build_feature_drivers(source).set_index("instrument_id")

    assert pd.isna(rows.loc["A", "peer_percentile"])
    assert pd.isna(rows.loc["B", "peer_percentile"])
    assert rows.loc["A", "as_of_date"] == "unavailable"
    assert rows.loc["B", "as_of_date"] == "unavailable"
    assert rows.loc["C", "as_of_date"] == "2026-07-10T00:00:00Z"
    assert rows.loc["D", "as_of_date"] == "2026-07-10T00:00:00Z"
    assert rows.loc["C", "peer_percentile"] == 100.0
    assert rows.loc["D", "peer_percentile"] == 50.0


def test_ledger_selects_latest_eligible_evidence_independent_of_row_order() -> None:
    scores = pd.DataFrame(
        [{"instrument_id": "A", "component": "quality", "normalised_score": 7.0, "as_of_date": "2026-01-01"}]
    )
    old = {
        "instrument_id": "A",
        "component": "quality",
        "as_of_date": "2025-12-31",
        "known_at": "2025-12-31T12:00:00Z",
        "available_at": "2025-12-31T13:00:00Z",
        "source_id": "fundamentals:old",
        "source_authority": "official_filing",
        "source_span": "old.parquet#quality",
        "source_vintage_hash": "b" * 64,
    }
    future = {
        "instrument_id": "A",
        "component": "quality",
        "as_of_date": "2026-01-02",
        "known_at": "2026-01-02T12:00:00Z",
        "available_at": "2026-01-02T13:00:00Z",
        "source_id": "fundamentals:future",
        "source_authority": "official_filing",
        "source_span": "future.parquet#quality",
        "source_vintage_hash": "c" * 64,
    }

    forward = build_feature_drivers(scores, pd.DataFrame([old, future])).iloc[0]
    reversed_rows = build_feature_drivers(scores, pd.DataFrame([future, old])).iloc[0]

    for row in (forward, reversed_rows):
        assert row["source_id"] == "fundamentals:old"
        assert row["source_span"] == "old.parquet#quality"
        assert row["source_vintage_hash"] == "b" * 64
        assert not str(row["driver_text"]).startswith("unavailable")
    assert forward["claim_hash"] == reversed_rows["claim_hash"]


def test_ledger_same_time_incompatible_provenance_fails_closed() -> None:
    scores = pd.DataFrame(
        [{"instrument_id": "A", "component": "quality", "normalised_score": 7.0, "as_of_date": "2026-01-01"}]
    )
    ledger = pd.DataFrame(
        [
            {"instrument_id": "A", "component": "quality", "as_of_date": "2025-12-31", "source_id": "fundamentals:first", "source_authority": "official_filing", "source_span": "first.parquet#quality", "source_vintage_hash": "b" * 64},
            {"instrument_id": "A", "component": "quality", "as_of_date": "2025-12-31", "source_id": "fundamentals:second", "source_authority": "official_filing", "source_span": "second.parquet#quality", "source_vintage_hash": "c" * 64},
        ]
    )

    row = build_feature_drivers(scores, ledger).iloc[0]

    assert row["source_id"] == ""
    assert row["source_span"] == "unavailable"
    assert row["source_vintage_hash"] == "unavailable"
    assert row["driver_text"] == "unavailable (non-traceable claim; source provenance unavailable)."
    assert row["claim_hash"] == "unavailable"


def test_ledger_same_time_same_provenance_with_conflicting_evidence_fails_closed() -> None:
    scores = pd.DataFrame(
        [{"instrument_id": "A", "component": "quality", "normalised_score": 7.0, "as_of_date": "2026-01-01"}]
    )
    shared = {
        "instrument_id": "A",
        "component": "quality",
        "as_of_date": "2025-12-31",
        "source_id": "fundamentals:first",
        "source_authority": "official_filing",
        "source_span": "first.parquet#quality",
        "source_vintage_hash": "b" * 64,
    }
    ledger = pd.DataFrame([{**shared, "coverage": 0.8}, {**shared, "coverage": 0.9}])

    row = build_feature_drivers(scores, ledger).iloc[0]

    assert row["source_id"] == ""
    assert row["source_span"] == "unavailable"
    assert row["coverage"] is pd.NA or pd.isna(row["coverage"])
    assert row["driver_text"] == "unavailable (non-traceable claim; source provenance unavailable)."
    assert row["claim_hash"] == "unavailable"


def test_selector_rederives_claim_authority_classifications_and_flags(monkeypatch, tmp_path) -> None:
    claim = deterministic_driver_claim("quality", 7.0)
    source_span = "quality.parquet#2026-07-10"
    bound_hash = claim_binding_hash(claim, VALID_VINTAGE, source_span, "official")
    source = pd.DataFrame(
        [
            {
                "instrument_id": "A",
                "component": "quality",
                "normalised_score": 7.0,
                "authority": "unknown",
                "source_authority": "vendor_unofficial",
                "source_span": source_span,
                "source_vintage_hash": VALID_VINTAGE,
                "as_of_date": "2026-07-10",
                "freshness_status": "stale",
                "driver_text": claim,
                "claim_hash": bound_hash,
                "authority_classification": "authoritative",
                "freshness_classification": "fresh",
                "classification": "positive",
                "flags": "none",
            }
        ]
    )

    row = _normalise_feature_driver_frame(source).iloc[0]

    assert row["driver_text"].startswith("unavailable (non-traceable claim;")
    assert row["claim_hash"] == "unavailable"
    assert row["authority_classification"] == "low_authority"
    assert row["freshness_classification"] == "stale"
    assert row["classification"] == "low_authority"
    assert row["flags"] == "low_authority|stale"

    path = tmp_path / "feature_drivers.parquet"
    source.to_parquet(path, index=False)
    monkeypatch.setattr(
        "etf_cockpit.app.selectors.instrument_detail.FEATURE_DRIVERS_PATH", path
    )
    panel = _feature_driver_panel("A")
    assert panel["top_positive"] == []
    assert panel["low_authority"][0]["component"] == "quality"
    assert panel["stale_or_partial"][0]["component"] == "quality"


def test_strict_pit_rejects_future_naive_and_ambiguous_score_evidence() -> None:
    common = {
        "component": "quality",
        "normalised_score": 7.0,
        "source_authority": "official",
        "source_span": "quality.parquet#row-1",
        "source_vintage_hash": VALID_VINTAGE,
    }
    rows = build_feature_drivers(
        pd.DataFrame(
            [
                {"instrument_id": "future", "as_of_date": "2026-07-11", "decision_at": "2026-07-10T23:59:59Z", **common},
                {"instrument_id": "naive", "as_of_date": "2026-07-10T12:00:00", **common},
                {"instrument_id": "ambiguous", "as_of_date": "07/10/2026", **common},
            ]
        )
    ).set_index("instrument_id")

    for instrument_id in ("future", "naive", "ambiguous"):
        assert str(rows.loc[instrument_id, "driver_text"]).startswith("unavailable (non-traceable claim;")
        assert rows.loc[instrument_id, "claim_hash"] == "unavailable"
    assert rows.loc["naive", "as_of_date"] == "unavailable"
    assert rows.loc["ambiguous", "as_of_date"] == "unavailable"


def test_ledger_rejects_impossible_chronology() -> None:
    scores = pd.DataFrame(
        [{"instrument_id": "A", "component": "quality", "normalised_score": 7.0, "as_of_date": "2026-01-02"}]
    )
    ledger = pd.DataFrame(
        [
            {
                "instrument_id": "A",
                "component": "quality",
                "as_of_date": "2026-01-01",
                "known_at": "2026-01-01T13:00:00Z",
                "available_at": "2026-01-01T12:00:00Z",
                "source_authority": "official",
                "source_span": "quality.parquet#row-1",
                "source_vintage_hash": VALID_VINTAGE,
            }
        ]
    )

    row = build_feature_drivers(scores, ledger).iloc[0]

    assert row["source_span"] == "unavailable"
    assert row["source_authority"] == "unavailable"
    assert row["claim_hash"] == "unavailable"


def test_peer_percentile_fraction_alias_scales_in_producer_and_selector() -> None:
    source = pd.DataFrame(
        [{"instrument_id": "A", "component": "quality", "normalised_score": 7.0, "peer_percentile_0_1": 0.8}]
    )

    assert build_feature_drivers(source).iloc[0]["peer_percentile"] == 80.0
    assert _normalise_feature_driver_frame(source).iloc[0]["peer_percentile"] == 80.0


def test_trust_evidence_requests_complete_feature_driver_projection(tmp_path) -> None:
    assert set(FEATURE_DRIVER_COLUMNS) - {"instrument"} <= set(FEATURE_DRIVER_EVIDENCE_COLUMNS)
    path = tmp_path / "feature_drivers.parquet"
    pd.DataFrame(
        [
            {
                **{column: "evidence" for column in FEATURE_DRIVER_EVIDENCE_COLUMNS},
                "instrument_id": "A",
                "component": "quality",
                "normalised_score": 7.0,
                "driver_text": "quality causes returns",
                "source_span": True,
                "source_authority": ["official"],
                "source_vintage_hash": "unavailable",
                "execution_allowed": True,
            }
        ]
    ).to_parquet(path)

    table = _table_panel(
        "Feature drivers",
        path,
        FEATURE_DRIVER_EVIDENCE_COLUMNS,
        normaliser=normalise_feature_driver_frame,
    ).content.controls[1]
    labels = [column.label.value for column in table.columns]
    values = {label: cell.content.value for label, cell in zip(labels, table.rows[0].cells)}

    assert labels == FEATURE_DRIVER_EVIDENCE_COLUMNS
    assert "causes" not in values["driver_text"]
    assert values["source_span"] == "unavailable"
    assert values["source_authority"] == "unavailable"
    assert values["source_vintage_hash"] == "unavailable"
    assert values["claim_hash"] == "unavailable"
    assert values["execution_allowed"] == "False"


def test_missing_vintage_and_low_source_authority_cannot_enter_trusted_top_lists(
    monkeypatch, tmp_path
) -> None:
    common = {
        "instrument_id": "A",
        "component": "quality",
        "normalised_score": 7.0,
        "authority": "high",
        "source_span": "quality.parquet#row-1",
        "as_of_date": "2026-07-10",
    }
    missing_vintage = build_feature_drivers(
        pd.DataFrame([{**common, "source_authority": "official"}])
    ).iloc[0]
    low_source = build_feature_drivers(
        pd.DataFrame(
            [
                {
                    **common,
                    "source_authority": "manual_context",
                    "source_vintage_hash": VALID_VINTAGE,
                }
            ]
        )
    ).iloc[0]

    assert missing_vintage["driver_text"].startswith("unavailable (non-traceable claim;")
    assert missing_vintage["claim_hash"] == "unavailable"
    assert low_source["authority_classification"] == "low_authority"
    assert low_source["classification"] == "low_authority"
    assert "low_authority" in low_source["flags"]

    path = tmp_path / "feature_drivers.parquet"
    pd.DataFrame([missing_vintage, low_source]).to_parquet(path, index=False)
    monkeypatch.setattr(
        "etf_cockpit.app.selectors.instrument_detail.FEATURE_DRIVERS_PATH", path
    )
    panel = _feature_driver_panel("A")
    assert panel["top_positive"] == []
    assert panel["low_authority"][0]["component"] == "quality"


def test_canonical_context_authorities_and_causal_component_labels_fail_closed(
    monkeypatch, tmp_path
) -> None:
    common = {
        "instrument_id": "A",
        "normalised_score": 7.0,
        "authority": "high",
        "source_span": "quality.parquet#row-1",
        "source_vintage_hash": VALID_VINTAGE,
        "as_of_date": "2026-07-10",
    }
    rows = build_feature_drivers(
        pd.DataFrame(
            [
                {**common, "component": "quality", "source_authority": "manual"},
                {**common, "component": "value", "source_authority": "community"},
                {
                    **common,
                    "component": "quality causes future returns",
                    "source_authority": "official",
                },
                {**common, "component": True, "source_authority": "official"},
                {**common, "component": ["quality"], "source_authority": "official"},
                {**common, "component": "official-lookalike", "source_authority": "officially_unverified"},
                {**common, "component": "vendor-lookalike", "source_authority": "vendorish"},
            ]
        )
    ).set_index("component")

    for component in ("quality", "value"):
        assert rows.loc[component, "authority_classification"] == "low_authority"
        assert rows.loc[component, "classification"] == "low_authority"
        assert "low_authority" in rows.loc[component, "flags"]
    malformed = rows.loc[""]
    assert malformed["driver_text"].str.startswith(
        "unavailable (non-traceable claim;"
    ).all()
    assert malformed["claim_hash"].eq("unavailable").all()
    for component in ("official-lookalike", "vendor-lookalike"):
        assert rows.loc[component, "authority_classification"] == "low_authority"
        assert rows.loc[component, "classification"] == "low_authority"

    path = tmp_path / "feature_drivers.parquet"
    rows.reset_index().to_parquet(path, index=False)
    monkeypatch.setattr(
        "etf_cockpit.app.selectors.instrument_detail.FEATURE_DRIVERS_PATH", path
    )
    panel = _feature_driver_panel("A")
    assert panel["top_positive"] == []
    assert len(panel["low_authority"]) == 4
    assert all("causes" not in str(row["driver_text"]) for row in panel["rows"])


def test_ledger_rejects_conflicting_populated_evidence_time_aliases() -> None:
    scores = pd.DataFrame(
        [{"instrument_id": "A", "component": "quality", "normalised_score": 7.0, "as_of_date": "2026-01-01"}]
    )
    ledger = pd.DataFrame(
        [
            {
                "instrument_id": "A",
                "component": "quality",
                "evidence_at": "2025-12-31",
                "as_of_date": "2026-01-02",
                "source_authority": "official",
                "source_span": "quality.parquet#row-1",
                "source_vintage_hash": VALID_VINTAGE,
            }
        ]
    )

    row = build_feature_drivers(scores, ledger).iloc[0]

    assert row["source_span"] == "unavailable"
    assert row["source_authority"] == "unavailable"
    assert row["source_vintage_hash"] == "unavailable"
    assert row["claim_hash"] == "unavailable"


def test_persisted_readback_rejects_raw_malformed_component_values() -> None:
    source = pd.DataFrame(
        [
            {
                "instrument_id": "A",
                "component": component,
                "normalised_score": 7.0,
                "authority": "high",
                "source_authority": "official",
                "source_span": "quality.parquet#row-1",
                "source_vintage_hash": VALID_VINTAGE,
                "as_of_date": "2026-07-10",
            }
            for component in (True, ["quality"], 7)
        ]
    )

    rows = normalise_feature_driver_frame(source)

    assert rows["component"].eq("").all()
    assert rows["normalised_score"].eq("unavailable").all()
    assert rows["direction"].eq("missing").all()
    assert rows["classification"].eq("missing").all()
    assert rows["claim_hash"].eq("unavailable").all()
