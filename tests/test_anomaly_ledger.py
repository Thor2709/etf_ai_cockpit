from __future__ import annotations

from dataclasses import replace

import pytest

from etf_cockpit.data.anomaly_ledger import (
    AnomalyLedger,
    AnomalyLedgerError,
    CorrectionEvent,
    default_quality_rules,
    evaluate_record,
    project_conflicts,
    validate_rules,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.source_conflicts import MetricClaim, resolve_conflicts


def _record(**updates):
    record = {
        "asset_type": "bond",
        "required_fields": ("instrument_id",),
        "instrument_id": "BOND-1",
        "unit": "percent_of_par",
        "currency": "AUD",
        "dates": ("2025-01-01", "2025-01-02"),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1000,
        "quantity": 10,
        "duplicate_ids": (),
        "duplicate_actions": (),
        "clean_price": 99.0,
        "dirty_price": 100.0,
        "accrued": 1.0,
        "par": 100.0,
        "coupon": 0.04,
        "notional": 1000.0,
        "yield": 0.05,
        "day_count": "ACT/365",
        "schedule_dates": ("2025-06-01", "2025-12-01"),
        "age_days": 1,
        "liquidity": "liquid",
        "holding_total": 100.0,
        "holding_components": (60.0, 40.0),
    }
    record.update(updates)
    return record


def test_rule_registry_is_versioned_typed_and_deterministic() -> None:
    rules = default_quality_rules()

    assert validate_rules(reversed(rules)) == tuple(
        sorted(rules, key=lambda item: (item.rule_id, item.version))
    )
    assert all(rule.expected_units and rule.severity for rule in rules)
    assert all(rule.execution_allowed is False for rule in rules)
    assert len({rule.sha256 for rule in rules}) == len(rules)
    with pytest.raises(AnomalyLedgerError, match="duplicate"):
        validate_rules((rules[0], rules[0]))
    with pytest.raises(AnomalyLedgerError, match="invalid quality rule"):
        validate_rules((replace(rules[0], severity="pass"),))


def test_equity_record_does_not_receive_bond_or_portfolio_findings() -> None:
    result = evaluate_record(
        "EQUITY-1",
        {
            **_record(),
            "asset_type": "equity",
            "data_scopes": ("price", "time_series", "volume"),
        },
        available_at="2026-01-01T00:00:00Z",
        source_id="fixture",
        source_checksum="1" * 64,
    )
    rule_ids = {item.rule_id for item in result.findings}

    assert "market.ohlc" in rule_ids
    assert "fixed_income.price_invariant" not in rule_ids
    assert "fixed_income.schedule" not in rule_ids
    assert "holding.balance" not in rule_ids


def test_invariants_units_staleness_negative_quantity_schedule_and_balance_fail_closed() -> None:
    result = evaluate_record(
        "BOND-1",
        _record(
            dirty_price=120.0,
            quantity=-1,
            unit="",
            schedule_dates=("2025-12-01", "2025-06-01"),
            age_days=6,
            liquidity="illiquid",
            holding_total=99,
        ),
        available_at="2026-01-01T00:00:00Z",
        source_id="local-fixture",
        source_checksum="a" * 64,
    )
    by_rule = {item.rule_id: item for item in result.findings}

    assert by_rule["fixed_income.price_invariant"].state == "quarantine"
    assert by_rule["quantity.nonnegative"].state == "block"
    assert by_rule["context.unit_currency"].state == "block"
    assert by_rule["fixed_income.schedule"].state == "block"
    assert by_rule["freshness.asset_liquidity"].state == "quarantine"
    assert result.canonical_eligible is False
    assert all(item.execution_allowed is False for item in result.findings)
    portfolio = evaluate_record(
        "PORTFOLIO-1",
        {
            "asset_type": "portfolio",
            "required_fields": ("holding_total",),
            "holding_total": 99,
            "holding_components": (60, 40),
            "unit": "currency",
            "currency": "AUD",
        },
        available_at="2026-01-01T00:00:00Z",
        source_id="local-fixture",
        source_checksum="a" * 64,
    )
    assert next(
        item for item in portfolio.findings if item.rule_id == "holding.balance"
    ).state == "block"


def test_ambiguous_input_and_ohlc_duplicate_fixtures_are_explicit() -> None:
    with pytest.raises(AnomalyLedgerError, match="non-empty record"):
        evaluate_record(
            "X",
            {},
            available_at="2026-01-01T00:00:00Z",
            source_id="fixture",
            source_checksum="a" * 64,
        )
    missing_context = evaluate_record(
        "X",
        {"unit": "currency", "currency": "AUD"},
        available_at="2026-01-01T00:00:00Z",
        source_id="fixture",
        source_checksum="a" * 64,
    )
    assert next(
        item
        for item in missing_context.findings
        if item.rule_id == "schema.required"
    ).state == "block"
    with pytest.raises(AnomalyLedgerError, match="source identity"):
        evaluate_record(
            "X",
            _record(),
            available_at="2026-01-01T00:00:00Z",
            source_id="",
            source_checksum="a" * 64,
        )
    result = evaluate_record(
        "X",
        _record(asset_type="equity", high=98, duplicate_ids=("X",)),
        available_at="2026-01-01T00:00:00Z",
        source_id="fixture",
        source_checksum="b" * 64,
    )
    states = {item.rule_id: item.state for item in result.findings}
    assert states["market.ohlc"] == "quarantine"
    assert states["identity.duplicates_actions"] == "quarantine"

    scope_cannot_bypass = evaluate_record(
        "X",
        _record(asset_type="equity", high=98, data_scopes=("volume",)),
        available_at="2026-01-01T00:00:00Z",
        source_id="fixture",
        source_checksum="3" * 64,
    )
    assert next(
        item
        for item in scope_cannot_bypass.findings
        if item.rule_id == "market.ohlc"
    ).state == "quarantine"
    malformed_scope = evaluate_record(
        "X",
        _record(asset_type="equity", high=98, data_scopes={"unexpected": True}),
        available_at="2026-01-01T00:00:00Z",
        source_id="fixture",
        source_checksum="4" * 64,
    )
    assert next(
        item for item in malformed_scope.findings if item.rule_id == "market.ohlc"
    ).state == "quarantine"

    malformed = evaluate_record(
        "X",
        _record(quantity="not-a-number", dirty_price="bad", dates=("not-a-date",)),
        available_at="2026-01-01T00:00:00Z",
        source_id="fixture",
        source_checksum="2" * 64,
    )
    malformed_by_rule = {item.rule_id: item for item in malformed.findings}
    assert malformed_by_rule["quantity.nonnegative"].state == "block"
    assert malformed_by_rule["fixed_income.price_invariant"].state == "quarantine"
    assert malformed_by_rule["date.continuity"].state == "warn"
    assert all(
        "malformed input" in malformed_by_rule[rule_id].message
        for rule_id in (
            "quantity.nonnegative",
            "fixed_income.price_invariant",
            "date.continuity",
        )
    )
    unsafe_ohlc = evaluate_record(
        "X",
        _record(asset_type="equity", high=float("inf")),
        available_at="2026-01-01T00:00:00Z",
        source_id="fixture",
        source_checksum="5" * 64,
    )
    assert next(
        item for item in unsafe_ohlc.findings if item.rule_id == "market.ohlc"
    ).state == "quarantine"
    unsafe_bond = evaluate_record(
        "X",
        _record(
            clean_price=float("nan"),
            schedule_dates=("not-a-date",),
            age_days=-1,
        ),
        available_at="2026-01-01T00:00:00Z",
        source_id="fixture",
        source_checksum="6" * 64,
    )
    unsafe_by_rule = {item.rule_id: item for item in unsafe_bond.findings}
    assert unsafe_by_rule["fixed_income.price_invariant"].state == "quarantine"
    assert unsafe_by_rule["fixed_income.schedule"].state == "block"
    assert unsafe_by_rule["freshness.asset_liquidity"].state == "quarantine"


def test_source_conflict_projection_retains_material_decision_evidence() -> None:
    resolution = resolve_conflicts(
        (
            MetricClaim("X", "revenue", 100, "vendor", SourceAuthority.VENDOR, "vendor"),
            MetricClaim("X", "revenue", 120, "official", SourceAuthority.OFFICIAL, "official"),
        )
    )
    projected = project_conflicts(
        resolution,
        available_at="2026-01-01T00:00:00Z",
        source_checksum="c" * 64,
    )

    assert projected.canonical_eligible is False
    assert projected.findings[0].state == "quarantine"
    assert projected.findings[0].observed["conflict_id"] == resolution.conflicts[0].conflict_id
    assert projected.findings[0].observed["source_ids"] == ("official", "vendor")
    with pytest.raises(AnomalyLedgerError, match="SHA-256"):
        project_conflicts(
            resolution,
            available_at="2026-01-01T00:00:00Z",
            source_checksum="bad",
        )


def test_append_only_correction_vintage_replay_and_invalidation(tmp_path) -> None:
    evaluation = evaluate_record(
        "BOND-1",
        _record(quantity=-1),
        available_at="2026-01-01T00:00:00Z",
        source_id="fixture",
        source_checksum="d" * 64,
    )
    ledger = AnomalyLedger()
    ledger.append_findings(evaluation, root=tmp_path)
    before = ledger.summary(
        root=tmp_path, decision_time="2026-01-15T00:00:00Z"
    )
    finding = next(
        item for item in evaluation.findings if item.rule_id == "quantity.nonnegative"
    )
    ledger.append_correction(
        CorrectionEvent(
            finding.finding_id,
            "corrected",
            "reviewer-1",
            "Source quantity corrected; original evidence retained",
            "2026-02-01T00:00:00Z",
            "e" * 64,
        ),
        root=tmp_path,
    )
    historical = ledger.summary(
        root=tmp_path, decision_time="2026-01-15T00:00:00Z"
    )
    current = ledger.summary(
        root=tmp_path, decision_time="2026-03-01T00:00:00Z"
    )

    assert before == historical
    assert historical["correction_count"] == 0
    assert current["correction_count"] == 1
    assert current["finding_count"] == historical["finding_count"]
    assert current["invalidation_token"] != historical["invalidation_token"]
    assert current["unresolved_count"] == historical["unresolved_count"] - 1
    assert current["canonical_eligible"] is True
    assert current["execution_allowed"] is False

    second = replace(
        CorrectionEvent(
            finding.finding_id,
            "reviewed",
            "reviewer-2",
            "Independent review",
            "2026-03-02T00:00:00Z",
            "f" * 64,
        ),
        revision=2,
    )
    ledger.append_correction(second, root=tmp_path)
    reviewed = ledger.summary(
        root=tmp_path, decision_time="2026-04-01T00:00:00Z"
    )
    assert reviewed["review_states"] == ["reviewed"]
    assert reviewed["unresolved_count"] == historical["unresolved_count"]
    assert reviewed["canonical_eligible"] is False


def test_empty_ledger_is_unavailable_and_canonical_ineligible(tmp_path) -> None:
    summary = AnomalyLedger().summary(
        root=tmp_path, decision_time="2026-01-01T00:00:00Z"
    )

    assert summary["status"] == "unavailable"
    assert summary["canonical_eligible"] is False
    assert not (tmp_path / "data" / "storage" / "cockpit.sqlite3").exists()
