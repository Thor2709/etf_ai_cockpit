from __future__ import annotations

from datetime import date
import json

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.data.fundamentals import (
    FUNDAMENTAL_SCHEMA_VERSION,
    assess_fundamental_row,
    build_fundamental_evidence,
    load_fundamental_evidence,
    latest_fundamental_rows,
    merge_fundamental_sources,
)


def _complete_claims() -> dict[str, object]:
    return {
        "valuation": 7.0,
        "profitability": 6.0,
        "leverage": 5.0,
        "growth": 8.0,
        "shareholder_return": 4.0,
    }


def test_missing_and_weak_fundamentals_are_not_confused() -> None:
    missing = build_fundamental_evidence({}, "MSFT", "2026-07-10")
    weak = build_fundamental_evidence({"valuation": -1, "profitability": 2}, "MSFT", "2026-07-10")
    assert missing.eligibility == "not_score_eligible"
    assert "valuation" in missing.missing_fields
    assert weak.eligibility == "not_score_eligible"
    assert weak.score_eligible is False
    assert weak.values["valuation"] == -1


def test_complete_five_section_negative_evidence_remains_score_eligible() -> None:
    claims = _complete_claims()
    claims["valuation"] = -1.0
    evidence = build_fundamental_evidence(claims, "MSFT", "2026-07-10")
    assert evidence.eligibility == "eligible_negative_evidence"
    assert evidence.score_eligible is True


def test_strict_fundamentals_require_all_five_sections_for_score() -> None:
    claims = _complete_claims()
    claims.pop("growth")
    evidence = build_fundamental_evidence(claims, "MSFT", "2026-07-10")
    assert evidence.eligibility == "not_score_eligible"
    assert "growth" in evidence.missing_fields
    assert evidence.executable_authority is False


def test_fundamentals_report_staleness_sector_and_vendor_limitations() -> None:
    evidence = build_fundamental_evidence(
        _complete_claims(),
        "MSFT",
        "2020-01-01",
        source_authority="vendor",
        today=date(2026, 7, 18),
    )
    assert "stale_fundamentals" in evidence.warnings
    assert evidence.eligibility == "not_score_eligible"
    assert evidence.score_eligible is False
    assert set(evidence.stale_fields) == set(_complete_claims())
    assert evidence.sector_relative_status == "unavailable"
    assert evidence.source == "vendor"
    assert evidence.limitations


@pytest.mark.parametrize(("as_of", "warning"), [("not-a-date", "ambiguous_as_of"), ("2026-07-19", "future_as_of")])
def test_invalid_or_future_fundamental_dates_fail_closed(as_of: str, warning: str) -> None:
    evidence = build_fundamental_evidence(
        _complete_claims(),
        "MSFT",
        as_of,
        today=date(2026, 7, 18),
    )

    assert warning in evidence.warnings
    assert evidence.eligibility == "not_score_eligible"
    assert evidence.score_eligible is False


@pytest.mark.parametrize("invalid_value", [True, np.bool_(True)])
def test_boolean_fundamental_values_are_not_treated_as_measurements(invalid_value: object) -> None:
    evidence = build_fundamental_evidence(
        {**_complete_claims(), "valuation": invalid_value},
        "MSFT",
        "2026-07-18",
        today=date(2026, 7, 18),
    )

    assert "valuation" in evidence.missing_fields
    assert evidence.score_eligible is False


def test_source_merge_requires_matching_identity_and_period_and_cannot_grant_authority() -> None:
    merged = merge_fundamental_sources(
        {
            "instrument_id": "MSFT",
            "as_of_date": "2026-06-30",
            "source_authority": "vendor",
            "valuation": 4.0,
            "executable_authority": True,
        },
        {
            "instrument_id": "AAPL",
            "as_of_date": "2026-06-30",
            "source_authority": "sec_edgar",
            "valuation": 9.0,
        },
        {
            "instrument_id": "MSFT",
            "as_of_date": "2026-03-31",
            "source_authority": "sec_edgar",
            "valuation": 8.0,
        },
        {
            "instrument_id": "MSFT",
            "as_of_date": "2026-06-30",
            "source_authority": "sec_edgar",
            "profitability": 7.0,
            "executable_authority": True,
        },
    )

    assert merged["instrument_id"] == "MSFT"
    assert merged["as_of_date"] == "2026-06-30"
    assert merged["valuation"] == 4.0
    assert merged["profitability"] == 7.0
    assert merged["source_authority"] == "mixed"
    assert merged["sections"]["valuation"]["source_authority"] == "vendor"
    assert merged["sections"]["profitability"]["source_authority"] == "sec_edgar"
    assert merged["rejected_source_count"] == 2
    assert merged["merge_status"] == "manual_review"
    assert merged["executable_authority"] is False


def test_non_contributing_official_source_cannot_upgrade_vendor_authority() -> None:
    merged = merge_fundamental_sources(
        {
            "instrument_id": "MSFT",
            "as_of_date": "2026-06-30",
            "source_authority": "vendor",
            "source_id": "vendor-record",
            **_complete_claims(),
        },
        {
            "instrument_id": "MSFT",
            "as_of_date": "2026-06-30",
            "source_authority": "sec_edgar",
            "source_id": "sec-empty-stub",
        },
    )

    assert merged["source_authority"] == "vendor"
    assert merged["source_id"] == "vendor-record"
    assert {section["source_id"] for section in merged["sections"].values()} == {"vendor-record"}


def test_merge_manual_review_state_survives_build_and_assessment() -> None:
    merged = merge_fundamental_sources(
        {
            "instrument_id": "MSFT",
            "as_of_date": "2026-06-30",
            "source_authority": "vendor",
            "source_id": "vendor-record",
            **_complete_claims(),
        },
        {
            "instrument_id": "AAPL",
            "as_of_date": "2026-06-30",
            "source_authority": "sec_edgar",
            "source_id": "wrong-instrument",
            "valuation": 9.0,
        },
    )

    evidence = build_fundamental_evidence(merged, "MSFT", "2026-06-30", today=date(2026, 7, 18))
    row = {
        **evidence.values,
        "as_of_date": evidence.as_of,
        "eligibility": evidence.eligibility,
        "score_eligible": evidence.score_eligible,
        "source_authority": evidence.source_authority,
        "source_id": evidence.source_id,
        "manual_review": evidence.manual_review,
        "merge_status": evidence.merge_status,
        "rejected_source_count": evidence.rejected_source_count,
        "warnings": "|".join(evidence.warnings),
        "sections_json": json.dumps(evidence.sections, sort_keys=True),
    }
    assessment = assess_fundamental_row(row, today=date(2026, 7, 18))

    assert evidence.manual_review is True
    assert evidence.merge_status == "manual_review"
    assert evidence.rejected_source_count == 1
    assert evidence.score_eligible is False
    assert assessment.score_eligible is False
    assert "manual_review_required" in assessment.reasons


def test_source_merge_without_anchor_identity_or_period_fails_closed() -> None:
    merged = merge_fundamental_sources(
        {"source_authority": "vendor", "valuation": 4.0},
        {"instrument_id": "MSFT", "as_of_date": "2026-06-30", "source_authority": "sec_edgar", "valuation": 9.0},
    )

    assert "valuation" not in merged
    assert merged["merge_status"] == "unavailable"
    assert merged["manual_review"] is True
    assert merged["executable_authority"] is False


def test_sector_relative_comparison_preserves_peer_benchmark_delta_and_limitation() -> None:
    evidence = build_fundamental_evidence(
        _complete_claims(),
        "MSFT",
        "2026-07-10",
        sector_relative={
            "value": 8.2,
            "peer": "Technology large-cap peers",
            "benchmark": "MSCI World Information Technology",
            "delta": 1.4,
            "limitation": "Peer set is provider-defined.",
        },
    )

    assert evidence.sector_relative_status == "available"
    assert evidence.sector_relative_value == 8.2
    assert evidence.sector_relative_peer == "Technology large-cap peers"
    assert evidence.sector_relative_benchmark == "MSCI World Information Technology"
    assert evidence.sector_relative_delta == 1.4
    assert evidence.sector_relative_limitation == "Peer set is provider-defined."


def test_fundamentals_persistence_is_idempotent_and_raw_immutable(tmp_path) -> None:
    from etf_cockpit.data.fundamentals import persist_fundamental_evidence

    evidence = build_fundamental_evidence(_complete_claims(), "MSFT", "2026-07-10")
    first = persist_fundamental_evidence(evidence, raw_dir=tmp_path / "raw", clean_path=tmp_path / "clean.parquet")
    original_raw = first.raw_path.read_bytes()
    second = persist_fundamental_evidence(evidence, raw_dir=tmp_path / "raw", clean_path=tmp_path / "clean.parquet")
    assert second.clean_path == first.clean_path
    assert first.raw_path.read_bytes() == original_raw
    assert second.rows == 1


def test_fundamental_persistence_preserves_section_provenance(tmp_path) -> None:
    from etf_cockpit.data.fundamentals import persist_fundamental_evidence

    evidence = build_fundamental_evidence(
        {
            "sections": {
                field: {
                    "value": value,
                    "period_end": "2026-06-30",
                    "source_id": "sec-filing-2026-q2",
                }
                for field, value in _complete_claims().items()
            }
        },
        "MSFT",
        "2026-07-10",
        source_authority="sec_edgar",
    )
    clean_path = tmp_path / "clean.parquet"

    persist_fundamental_evidence(evidence, raw_dir=tmp_path / "raw", clean_path=clean_path)
    row = load_fundamental_evidence(clean_path).iloc[0]
    assessment = assess_fundamental_row(row, today=date(2026, 7, 18))

    assert '"period_end":"2026-06-30"' in row["sections_json"]
    assert '"source_id":"sec-filing-2026-q2"' in row["sections_json"]
    assert '"source_authority":"sec_edgar"' in row["sections_json"]
    assert assessment.score_eligible is True
    assert row["schema_version"] == FUNDAMENTAL_SCHEMA_VERSION == "fundamental_evidence.v4"
    assert bool(row["executable_authority"]) is False


def test_fundamental_atomic_failure_preserves_existing_clean_generation(tmp_path, monkeypatch) -> None:
    import etf_cockpit.data.fundamentals as module

    evidence = build_fundamental_evidence(_complete_claims(), "MSFT", "2026-07-10")
    clean_path = tmp_path / "clean.parquet"
    module.persist_fundamental_evidence(evidence, raw_dir=tmp_path / "raw", clean_path=clean_path)
    before = clean_path.read_bytes()
    audit_path = clean_path.with_name("clean_audit.json")
    audit_before = audit_path.read_bytes()
    raw_before = {path.name: path.read_bytes() for path in (tmp_path / "raw").glob("*.json")}
    real_atomic_write_group = module.atomic_write_group

    def fail_before_commit(requests):
        def inject_failure(state, _journal):
            if state == "committing":
                raise RuntimeError("injected failure")

        return real_atomic_write_group(requests, lifecycle_hook=inject_failure)

    monkeypatch.setattr(module, "atomic_write_group", fail_before_commit)
    with pytest.raises(RuntimeError, match="injected failure"):
        module.persist_fundamental_evidence(
            build_fundamental_evidence({**_complete_claims(), "growth": 9.0}, "MSFT", "2026-07-11"),
            raw_dir=tmp_path / "raw",
            clean_path=clean_path,
        )
    assert clean_path.read_bytes() == before
    assert audit_path.read_bytes() == audit_before
    assert {path.name: path.read_bytes() for path in (tmp_path / "raw").glob("*.json")} == raw_before


def test_fundamental_persistence_orders_generations_by_as_of_date(tmp_path) -> None:
    from etf_cockpit.data.fundamentals import load_fundamental_evidence, persist_fundamental_evidence

    clean_path = tmp_path / "clean.parquet"
    persist_fundamental_evidence(
        build_fundamental_evidence({**_complete_claims(), "growth": 9.0}, "MSFT", "2026-07-12"),
        raw_dir=tmp_path / "raw",
        clean_path=clean_path,
    )
    persist_fundamental_evidence(
        build_fundamental_evidence({**_complete_claims(), "growth": 8.0}, "MSFT", "2026-07-11"),
        raw_dir=tmp_path / "raw",
        clean_path=clean_path,
    )

    assert list(load_fundamental_evidence(clean_path)["as_of_date"]) == ["2026-07-11", "2026-07-12"]


def test_latest_fundamental_rows_break_equal_date_ties_deterministically() -> None:
    frame = pd.DataFrame(
        [
            {"instrument_id": "MSFT", "as_of_date": "2026-07-18", "valuation": 2.0},
            {"instrument_id": "MSFT", "as_of_date": "2026-07-18", "valuation": 8.0},
        ]
    )

    first = latest_fundamental_rows(frame).iloc[0].to_dict()
    second = latest_fundamental_rows(frame.iloc[::-1].reset_index(drop=True)).iloc[0].to_dict()

    assert first == second
