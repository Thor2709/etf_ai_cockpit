from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import numpy as np
import pytest

from etf_cockpit.application.overlap import _snapshot_weights, load_direct_holdings
from etf_cockpit.features.overlap import calculate_direct_overlap


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"instrument_id": "ETF-A", "security": "Alpha plc", "isin": "GB0002634946", "weight": 0.60, "as_of": "2026-07-01", "source_id": "a1", "authority": "issuer", "completeness": "full", "freshness": "fresh", "sector": "Technology", "country": "GB", "currency": "GBP"},
            {"instrument_id": "ETF-A", "security": "Beta SA", "isin": "FR0000120271", "weight": 0.40, "as_of": "2026-07-01", "source_id": "a1", "authority": "issuer", "completeness": "full", "freshness": "fresh", "sector": "Financials", "country": "FR", "currency": "EUR"},
            {"instrument_id": "ETF-B", "security": "Alpha renamed", "isin": "GB0002634946", "weight": 0.25, "as_of": "2026-07-02", "source_id": "b1", "authority": "issuer", "completeness": "full", "freshness": "fresh", "sector": "Technology", "country": "GB", "currency": "GBP"},
            {"instrument_id": "ETF-B", "security": "Gamma AG", "isin": "DE0007164600", "weight": 0.75, "as_of": "2026-07-02", "source_id": "b1", "authority": "issuer", "completeness": "full", "freshness": "fresh", "sector": "Industrials", "country": "DE", "currency": "EUR"},
        ]
    )


def test_weighted_min_overlap_is_exact_symmetric_and_order_independent() -> None:
    rows = _rows()
    first = calculate_direct_overlap(rows, ["ETF-B", "ETF-A"], today=date(2026, 7, 18))
    second = calculate_direct_overlap(rows.sample(frac=1, random_state=7), ["ETF-A", "ETF-B"], today=date(2026, 7, 18))

    assert first == second
    assert first.status == "full"
    assert first.pairs[0].observed_overlap_weight == pytest.approx(0.25)
    assert first.pairs[0].current_overlap_weight == pytest.approx(0.25)
    assert first.pairs[0].top_holdings[0].identity == "isin:GB0002634946"
    assert first.execution_allowed is False


def test_names_never_create_identity_matches() -> None:
    rows = _rows().copy()
    rows.loc[rows["instrument_id"].eq("ETF-B"), "isin"] = ["US0378331005", "DE0007164600"]
    rows.loc[rows["instrument_id"].eq("ETF-B"), "security"] = ["Alpha plc", "Gamma AG"]

    report = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))

    assert report.pairs[0].observed_overlap_weight == 0.0
    assert not report.pairs[0].top_holdings


def test_partial_identity_coverage_is_not_renormalised() -> None:
    rows = _rows()
    rows.loc[(rows["instrument_id"] == "ETF-B") & (rows["security"] == "Gamma AG"), "isin"] = ""

    report = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))

    pair = report.pairs[0]
    assert report.status == "dated_lower_bound"
    assert pair.status == "dated_lower_bound"
    assert pair.observed_overlap_weight == pytest.approx(0.25)
    assert pair.current_overlap_weight is None
    assert pair.right_coverage.resolved_weight == pytest.approx(0.25)
    assert pair.right_coverage.unresolved_weight == pytest.approx(0.75)


def test_stale_overlap_is_dated_evidence_not_current_overlap() -> None:
    rows = _rows()
    rows.loc[rows["instrument_id"].eq("ETF-B"), "as_of"] = "2026-01-01"

    report = calculate_direct_overlap(
        rows,
        ["ETF-A", "ETF-B"],
        current_weights={"ETF-A": 0.5, "ETF-B": 0.5},
        today=date(2026, 7, 18),
    )

    assert report.pairs[0].status == "dated_lower_bound"
    assert report.pairs[0].observed_overlap_weight == pytest.approx(0.25)
    assert report.pairs[0].current_overlap_weight is None
    technology = next(item for item in report.concentrations if item.dimension == "sector" and item.bucket == "Technology")
    assert technology.current_weight == pytest.approx(0.3)
    assert report.current_resolved_weight == pytest.approx(0.5)
    assert "current overlap is unavailable" in " ".join(report.warnings).lower()


def test_freshness_is_recomputed_from_snapshot_date() -> None:
    rows = _rows()
    rows["freshness"] = "fresh"

    report = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 12, 18))

    assert report.pairs[0].status == "dated_lower_bound"
    assert report.pairs[0].current_overlap_weight is None
    assert all(item.freshness == "stale" for item in report.coverage)


def test_missing_provenance_cannot_produce_full_current_overlap() -> None:
    rows = _rows().drop(columns=["source_id", "authority"])

    report = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))

    assert report.pairs[0].status == "dated_lower_bound"
    assert report.pairs[0].current_overlap_weight is None
    assert "provenance is incomplete" in " ".join(report.warnings).lower()


def test_snapshot_boolean_and_nonfinite_weights_are_excluded() -> None:
    snapshot = SimpleNamespace(
        holdings=pd.DataFrame(
            {
                "etf_id": ["ETF-A", "ETF-B", "ETF-C"],
                "current_weight": [np.bool_(True), float("nan"), 0.25],
            }
        )
    )

    assert _snapshot_weights(snapshot) == {"ETF-C": 0.25}


def test_invalid_isin_check_digit_remains_unresolved() -> None:
    rows = _rows()
    rows.loc[rows["isin"].eq("GB0002634946"), "isin"] = "US0378331006"

    report = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))

    assert report.pairs[0].observed_overlap_weight == pytest.approx(0.0)
    assert all("US0378331006" not in holding.identity for item in report.coverage for holding in item.holdings)


def test_source_checksum_binds_concentration_metadata() -> None:
    original = calculate_direct_overlap(_rows(), ["ETF-A", "ETF-B"], today=date(2026, 7, 18))
    changed_rows = _rows()
    changed_rows.loc[0, "sector"] = "Industrials"
    changed = calculate_direct_overlap(changed_rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))

    assert original.coverage[0].source_checksum != changed.coverage[0].source_checksum


def test_source_checksum_binds_unresolved_rows() -> None:
    rows = _rows()
    rows.loc[0, "isin"] = ""
    original = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))
    rows.loc[0, "weight"] = 0.5
    changed = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))

    assert original.coverage[0].source_checksum != changed.coverage[0].source_checksum


def test_legacy_reference_store_is_safe_fallback_only(tmp_path) -> None:
    clean = tmp_path / "data" / "clean"
    clean.mkdir(parents=True)
    pd.DataFrame(
        {
            "etf_id": ["ETF-A", "ETF-B"],
            "as_of_date": ["2026-07-01", "2026-07-02"],
            "holding_name": ["Alpha plc", "Beta SA"],
            "holding_id": ["GB0002634946", "FR0000120271"],
            "weight": [0.6, 0.4],
            "source": ["issuer_spoof", "issuer_spoof"],
            "staleness_status": ["ok", "ok"],
        }
    ).to_parquet(clean / "etf_holdings.parquet", index=False)

    loaded = load_direct_holdings(root=tmp_path)

    assert loaded.loc[0, "authority"] == "manual_unverified"
    assert loaded.loc[0, "isin"] == "GB0002634946"
    assert loaded.loc[0, "freshness"] == "fresh"

    canonical = loaded.loc[loaded["instrument_id"].eq("ETF-A")].assign(source_id="canonical")
    canonical.to_parquet(clean / "fund_holdings.parquet", index=False)
    combined = load_direct_holdings(root=tmp_path)
    assert combined.loc[combined["instrument_id"].eq("ETF-A"), "source_id"].tolist() == ["canonical"]
    assert combined.loc[combined["instrument_id"].eq("ETF-B"), "source_id"].tolist() == ["legacy-reference-import"]


@pytest.mark.parametrize("bad_weight", [True, np.bool_(True), float("nan"), float("inf"), -0.1, 1.1])
def test_malformed_canonical_weights_fail_closed(bad_weight: object) -> None:
    rows = _rows()
    rows["weight"] = rows["weight"].astype(object)
    rows.loc[0, "weight"] = bad_weight

    report = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))

    assert report.status == "missing"
    assert report.pairs[0].status == "missing"
    assert report.pairs[0].observed_overlap_weight is None


def test_latest_snapshot_wins_and_equal_authority_conflict_fails_closed() -> None:
    rows = _rows()
    older = rows.loc[rows["instrument_id"].eq("ETF-A")].copy()
    older["as_of"] = "2026-06-01"
    older["source_id"] = "old"
    rows = pd.concat([rows, older], ignore_index=True)
    report = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))
    assert report.pairs[0].left_coverage.source_id == "a1"

    conflict = rows.loc[rows["instrument_id"].eq("ETF-A") & rows["source_id"].eq("a1")].copy()
    conflict["source_id"] = "a2"
    rows = pd.concat([rows, conflict], ignore_index=True)
    report = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))
    assert report.pairs[0].status == "missing"
    assert "conflict" in " ".join(report.pairs[0].left_coverage.warnings).lower()


def test_unnamespaced_tickers_and_provider_ids_remain_unresolved() -> None:
    rows = _rows().drop(columns=["isin"])
    rows["ticker"] = ["AAA", "BBB", "AAA", "CCC"]
    rows["holding_id"] = ["1", "2", "1", "3"]

    report = calculate_direct_overlap(rows, ["ETF-A", "ETF-B"], today=date(2026, 7, 18))

    assert report.status == "missing"
    assert all(item.resolved_weight == 0 for item in report.coverage)


def test_concentrations_reconcile_only_resolved_direct_exposure() -> None:
    report = calculate_direct_overlap(
        _rows(),
        ["ETF-A", "ETF-B"],
        current_weights={"ETF-A": 0.4, "ETF-B": 0.6},
        target_weights={"ETF-A": 0.5, "ETF-B": 0.5},
        today=date(2026, 7, 18),
    )

    technology = next(item for item in report.concentrations if item.dimension == "sector" and item.bucket == "Technology")
    assert technology.current_weight == pytest.approx(0.39)
    assert technology.target_weight == pytest.approx(0.425)
    assert report.current_resolved_weight == pytest.approx(1.0)
    assert report.target_resolved_weight == pytest.approx(1.0)
