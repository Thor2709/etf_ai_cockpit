from __future__ import annotations

from etf_cockpit.data.fundamentals import build_fundamental_evidence


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
    assert weak.eligibility == "eligible_negative_evidence"
    assert weak.values["valuation"] == -1


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
    )
    assert "stale_fundamentals" in evidence.warnings
    assert evidence.sector_relative_status == "unavailable"
    assert evidence.source == "vendor"
    assert evidence.limitations


def test_fundamentals_persistence_is_idempotent_and_raw_immutable(tmp_path) -> None:
    from etf_cockpit.data.fundamentals import persist_fundamental_evidence

    evidence = build_fundamental_evidence(_complete_claims(), "MSFT", "2026-07-10")
    first = persist_fundamental_evidence(evidence, raw_dir=tmp_path / "raw", clean_path=tmp_path / "clean.parquet")
    original_raw = first.raw_path.read_bytes()
    second = persist_fundamental_evidence(evidence, raw_dir=tmp_path / "raw", clean_path=tmp_path / "clean.parquet")
    assert second.clean_path == first.clean_path
    assert first.raw_path.read_bytes() == original_raw
    assert second.rows == 1


def test_fundamental_atomic_failure_preserves_existing_clean_generation(tmp_path, monkeypatch) -> None:
    import etf_cockpit.data.fundamentals as module

    evidence = build_fundamental_evidence(_complete_claims(), "MSFT", "2026-07-10")
    clean_path = tmp_path / "clean.parquet"
    module.persist_fundamental_evidence(evidence, raw_dir=tmp_path / "raw", clean_path=clean_path)
    before = clean_path.read_bytes()
    monkeypatch.setattr(module, "atomic_write_group", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected failure")))
    try:
        module.persist_fundamental_evidence(
            build_fundamental_evidence({**_complete_claims(), "growth": 9.0}, "MSFT", "2026-07-11"),
            raw_dir=tmp_path / "raw",
            clean_path=clean_path,
        )
    except RuntimeError:
        pass
    assert clean_path.read_bytes() == before
