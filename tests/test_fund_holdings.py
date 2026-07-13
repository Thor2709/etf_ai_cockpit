from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data.fund_holdings import normalise_holdings, write_holdings_records
from etf_cockpit.app.pages import risk as risk_page_module


def test_full_holdings_are_normalised_and_partial_data_is_explicit() -> None:
    full = normalise_holdings(pd.DataFrame({"security": ["A", "B"], "weight": [0.6, 0.4]}), "VWCE", "2026-07-10", "issuer")
    partial = normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [0.4]}), "VWCE", "2026-07-10", "vendor")
    invalid = normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [-1.0]}), "VWCE", "2026-07-10", "issuer")
    assert full.completeness == "full"
    assert partial.completeness == "partial"
    assert invalid.completeness == "invalid"
    assert full.frame.iloc[0]["instrument_id"] == "VWCE"


@pytest.mark.parametrize("total", [0.99, 1.01])
def test_full_holdings_accept_boundary_tolerance(total: float) -> None:
    result = normalise_holdings(pd.DataFrame({"security": ["A", "B"], "ticker": ["A", "B"], "weight": [total - 0.4, 0.4]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "full"
    assert result.score_eligible is True
    assert result.authority == "issuer"


def test_vendor_top_holdings_remain_partial_even_when_weights_sum_to_one() -> None:
    result = normalise_holdings(pd.DataFrame({"security": ["A", "B"], "weight": [0.6, 0.4]}), "VWCE", "2026-07-10", "yfinance", today="2026-07-11")
    assert result.completeness == "partial"
    assert result.authority == "vendor"
    assert result.score_eligible is False


def test_stale_holdings_are_explicit_and_capped_for_current_exposure() -> None:
    result = normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [1.0]}), "VWCE", "2025-01-01", "issuer", today="2026-07-11")
    assert result.completeness == "stale"
    assert result.freshness == "stale"
    assert result.confidence <= 0.25
    assert result.score_eligible is False


def test_future_holdings_are_invalid_and_never_score_eligible() -> None:
    result = normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [1.0]}), "VWCE", "2026-07-12", "issuer", today="2026-07-11")
    assert result.completeness == "invalid"
    assert result.freshness == "invalid"
    assert result.score_eligible is False
    assert result.frame.empty
    assert "future_holdings" in result.warnings


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame({"security": ["A"], "weight": [-0.1]}),
        pd.DataFrame({"security": ["A", "B"], "weight": [0.8, 0.3]}),
        pd.DataFrame({"security": [""], "weight": [1.0]}),
    ],
)
def test_invalid_weights_or_empty_security_block_exposure(frame: pd.DataFrame) -> None:
    result = normalise_holdings(frame, "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "invalid"
    assert result.score_eligible is False


def test_exact_duplicate_rows_do_not_change_source_id_or_weight_sum() -> None:
    frame = pd.DataFrame({"security": ["A", "A", "B"], "ticker": ["A", "A", "B"], "weight": [0.6, 0.6, 0.4]})
    result = normalise_holdings(frame, "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "full"
    assert len(result.frame) == 2
    assert result.warnings == ("exact_duplicate_rows_removed",)


def test_holdings_are_persisted_with_provenance_columns(tmp_path: Path) -> None:
    result = normalise_holdings(pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    destination = tmp_path / "fund_holdings.parquet"
    written = write_holdings_records(result, destination=destination)
    stored = pd.read_parquet(written)
    assert {"source_id", "completeness", "freshness", "confidence", "authority", "score_eligible"} <= set(stored.columns)


def test_risk_adapts_legacy_reference_holdings_without_dropping_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(risk_page_module, "FUND_HOLDINGS_PATH", tmp_path / "missing.parquet")
    monkeypatch.setattr(
        risk_page_module,
        "load_reference_dataset",
        lambda _dataset: pd.DataFrame({
            "etf_id": ["VWCE", "VWCE"],
            "as_of_date": ["2026-07-10", "2026-07-10"],
            "holding_name": ["A", "B"],
            "weight": [0.6, 0.4],
            "source": ["yfinance", "yfinance"],
            "sector": ["Technology", "Healthcare"],
            "region": ["US", "EU"],
            "currency": ["USD", "EUR"],
        }),
    )
    adapted = risk_page_module._load_holdings_evidence()
    assert not adapted.empty
    assert adapted["completeness"].eq("partial").all()
    assert adapted["score_eligible"].eq(False).all()


@pytest.mark.parametrize("missing", ["score_eligible", "authority", "freshness", "completeness"])
def test_risk_exposure_fails_closed_when_holdings_metadata_is_missing(missing: str) -> None:
    frame = pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "security": ["A"],
            "weight": [1.0],
            "score_eligible": [True],
            "authority": ["issuer"],
            "freshness": ["fresh"],
            "completeness": ["full"],
        }
    ).drop(columns=[missing])
    eligible = risk_page_module._exposure_eligible_holdings(frame)
    assert eligible.empty


def test_missing_security_identity_is_invalid_and_requires_manual_review() -> None:
    result = normalise_holdings(pd.DataFrame({"weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "invalid"
    assert result.score_eligible is False
    assert "missing_security_or_weight" in result.warnings


def test_name_only_holdings_without_isin_or_ticker_are_context_only() -> None:
    result = normalise_holdings(pd.DataFrame({"holding_name": ["A"], "weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "full"
    assert result.score_eligible is False
    assert result.confidence <= 0.55
    assert "missing_isin_or_ticker_manual_review" in result.warnings


@pytest.mark.parametrize("identity_column", ["security", "holding_name", "security_name", "name"])
def test_all_name_only_holdings_identities_are_context_only(identity_column: str) -> None:
    result = normalise_holdings(pd.DataFrame({identity_column: ["A"], "weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "full"
    assert result.score_eligible is False
    assert result.confidence <= 0.55
    assert "missing_isin_or_ticker_manual_review" in result.warnings


@pytest.mark.parametrize("identity_column", ["isin", "ticker", "holding_id", "security_id"])
def test_explicit_holdings_identity_allows_issuer_score_eligibility(identity_column: str) -> None:
    result = normalise_holdings(
        pd.DataFrame({"security": ["A"], identity_column: ["ID-A"], "weight": [1.0]}),
        "VWCE",
        "2026-07-10",
        "issuer",
        today="2026-07-11",
    )
    assert result.score_eligible is True


def test_mixed_name_only_row_keeps_entire_holdings_set_context_only() -> None:
    result = normalise_holdings(
        pd.DataFrame({"security": ["A", "B"], "ticker": ["A", ""], "weight": [0.5, 0.5]}),
        "VWCE",
        "2026-07-10",
        "issuer",
        today="2026-07-11",
    )
    assert result.score_eligible is False
    assert "missing_isin_or_ticker_manual_review" in result.warnings


@pytest.mark.parametrize(
    "result_factory",
    [
        lambda: normalise_holdings(pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [-1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11"),
        lambda: normalise_holdings(pd.DataFrame(), "VWCE", "2026-07-10", "issuer", today="2026-07-11"),
        lambda: normalise_holdings(pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [0.4]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11"),
        lambda: normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11"),
    ],
)
def test_write_rejects_invalid_empty_and_ineligible_results_without_replacing_store(tmp_path: Path, result_factory) -> None:
    destination = tmp_path / "fund_holdings.parquet"
    valid = normalise_holdings(pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    write_holdings_records(valid, destination=destination)
    prior_bytes = destination.read_bytes()
    prior_csv_bytes = destination.with_suffix(".csv").read_bytes()
    prior_data = pd.read_parquet(destination)

    with pytest.raises(ValueError, match="score-eligible"):
        write_holdings_records(result_factory(), destination=destination)

    assert destination.read_bytes() == prior_bytes
    assert destination.with_suffix(".csv").read_bytes() == prior_csv_bytes
    pd.testing.assert_frame_equal(pd.read_parquet(destination), prior_data)


def test_write_rejects_mutated_frame_without_replacing_store(tmp_path: Path) -> None:
    destination = tmp_path / "fund_holdings.parquet"
    result = normalise_holdings(
        pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}),
        "VWCE",
        "2026-07-10",
        "issuer",
        today="2026-07-11",
    )
    write_holdings_records(result, destination=destination)
    prior_bytes = destination.read_bytes()
    prior_csv_bytes = destination.with_suffix(".csv").read_bytes()

    result.frame.loc[0, "weight"] = 0.2

    with pytest.raises(ValueError, match="score-eligible"):
        write_holdings_records(result, destination=destination)

    assert destination.read_bytes() == prior_bytes
    assert destination.with_suffix(".csv").read_bytes() == prior_csv_bytes
