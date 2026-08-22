from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.app.pages import backtests, data_models, portfolio
import etf_cockpit.application.monthly_decision_template as monthly_decision
from etf_cockpit.application.monthly_decision_template import (
    build_monthly_decision_template,
    monthly_decision_template_lines,
)
from etf_cockpit.core.config import load_config
from etf_cockpit.portfolio.benchmark_reference_contract import CanonicalBenchmarkRegistry
from etf_cockpit.signals.strategy_templates import strategy_template_frame


_TEST_REGISTRY = CanonicalBenchmarkRegistry()
_SOURCE_DIGEST = "a" * 64


@pytest.fixture(autouse=True)
def _validated_reference_dependency(monkeypatch) -> None:
    """Keep ISSUE-0046 tests focused on composition; ISSUE-0112 owns registry semantics."""

    def validate(reference, benchmark_data_id, *, registry=None):
        if registry is not _TEST_REGISTRY:
            return None
        return str(benchmark_data_id) if isinstance(reference, dict) else None

    monkeypatch.setattr(monthly_decision, "validate_benchmark_reference", validate)


def _reference() -> dict[str, object]:
    return {
        "status": "available", "execution_allowed": False,
        "benchmark_data_id": "VWCE", "registry_hash": "registry-hash",
        "selected_records": {"benchmark": "benchmark-hash", "cash": "cash-hash", "peer_set": "peer-hash"},
        "provenance": {"registry_hash": "registry-hash", "selected_records": {"benchmark": "benchmark-hash", "cash": "cash-hash", "peer_set": "peer-hash"}},
        "analysis": {"decision_time": "2026-08-21T23:59:59Z"},
        "benchmark": {"status": "available", "id": "benchmark:global", "version": "1.0.0", "content_hash": "benchmark-hash"},
        "cash": {"status": "available", "id": "cash:EUR", "version": "1.0.0", "content_hash": "cash-hash"},
        "references": [{"status": "available", "id": "reference:no-trade", "version": "1.0.0", "content_hash": "no-trade-hash", "method": "no_trade", "constituent_instrument_ids": ["VWCE"], "current_weights": {"VWCE": 1.0}}],
    }


def _full_evidence() -> dict[str, object]:
    evidence = {
        "alternatives": {
            "basket": {"status": "available", "version": "returns.v3", "source_id": "candidate:42", "source_dataset": "forward:2026-08", "source_digest": _SOURCE_DIGEST, "as_of": "2026-08-21", "known_at": "2026-08-21T12:00:00Z", "horizon_days": 21, "period_return": 0.07, "benchmark_relative_return": 0.02, "cash_relative_return": 0.04, "no_action_relative_return": 0.03, "execution_allowed": False},
            "benchmark": {"status": "available", "version": "returns.v3", "source_id": "benchmark:42", "source_dataset": "forward:2026-08", "source_digest": _SOURCE_DIGEST, "as_of": "2026-08-21", "known_at": "2026-08-21T12:00:00Z", "horizon_days": 21, "reference_id": "benchmark:global", "reference_version": "1.0.0", "reference_content_hash": "benchmark-hash", "period_return": 0.05, "execution_allowed": False},
            "cash": {"status": "available", "version": "returns.v3", "source_id": "cash:42", "source_dataset": "forward:2026-08", "source_digest": _SOURCE_DIGEST, "as_of": "2026-08-21", "known_at": "2026-08-21T12:00:00Z", "horizon_days": 21, "reference_id": "cash:EUR", "reference_version": "1.0.0", "reference_content_hash": "cash-hash", "period_return": 0.03, "execution_allowed": False},
            "no_action": {"status": "available", "version": "returns.v3", "source_id": "no-trade:42", "source_dataset": "forward:2026-08", "source_digest": _SOURCE_DIGEST, "as_of": "2026-08-21", "known_at": "2026-08-21T12:00:00Z", "horizon_days": 21, "reference_id": "reference:no-trade", "reference_version": "1.0.0", "reference_content_hash": "no-trade-hash", "reference_method": "no_trade", "period_return": 0.04, "execution_allowed": False},
        },
        "expected_returns": {
            "status": "available", "version": "distribution.v2", "source_id": "score:42", "source_dataset": "features:2026-08", "source_digest": _SOURCE_DIGEST, "as_of": "2026-08-21", "known_at": "2026-08-21T12:00:00Z", "horizon_days": 21,
            "gross": {"q10": -0.03, "q50": 0.06, "q90": 0.14},
            "net": {"q10": -0.035, "q50": 0.055, "q90": 0.135}, "execution_allowed": False,
        },
        "optimiser": {
            "status": "available", "model_version": "optimiser.v4", "method": "robust_mean_variance", "source_id": "solution:42",
            "constraints": {"status": "available", "values": {"max_weight": 0.25, "turnover_limit": 0.15}, "execution_allowed": False},
            "solution": {"status": "success", "feasible": True, "weights": {"VWCE": 0.25}, "diagnostics": {"status": "available", "binding_constraints": ["max_weight"], "execution_allowed": False}, "execution_allowed": False},
            "execution_allowed": False,
        },
        "costs": {
            "status": "available", "model_id": "cost-model.v2", "source_id": "portfolio-cost:42",
            "components": [{"estimate_id": "estimate:VWCE", "instrument_id": "VWCE", "order_value_eur": 10_000.0, "cost_eur": 12.5, "cost_bps": 12.5, "commission_eur": 2.5, "spread_bps": 4.0, "slippage_bps": 3.0, "market_impact_bps": 3.0, "execution_allowed": False}],
            "total": {"order_value_eur": 10_000.0, "cost_eur": 12.5, "cost_bps": 12.5},
            "capacity": {"status": "available", "amount_eur": 75_000.0},
            "assumptions": ["caller-supplied canonical cost estimate"], "execution_allowed": False,
        },
        "events": {
            "status": "available", "version": "event-replay.v1", "source_id": "replay:42",
            "replay": {"status": "available", "event_count": 8, "execution_allowed": False},
            "next_session": {"status": "available", "execution_delay_sessions": 1, "same_bar_execution_avoided": True, "arrival_price_assumption": "next_adjusted_close", "execution_allowed": False},
            "execution_allowed": False,
        },
        "forward_evidence": {"status": "available", "version": "forward-evidence.v1", "source_id": "forward:42", "snapshot": {"snapshot_id": "forward:42", "as_of": "2026-08-21", "execution_allowed": False}, "outcomes": [{"horizon_days": 21, "status": "matured", "net_return": 0.055}], "execution_allowed": False},
        "paper_outcomes": {"status": "available", "version": "paper-account.v1", "source_id": "paper:42", "account_id": "paper:local", "ledger_hash": "ledger-hash", "reconciliation_status": "reconciled", "matured_outcomes": 4, "outcomes": [{"decision_id": "decision:1", "status": "matured"}], "execution_allowed": False},
        "concentration": {"status": "available", "sector": {"status": "available", "max_weight": 0.32, "execution_allowed": False}, "theme": {"status": "available", "max_weight": 0.18, "execution_allowed": False}, "execution_allowed": False},
        "assumptions": {"status": "available", "version": "assumptions.v1", "source_id": "policy:42", "values": {"rebalance_cadence": "monthly", "execution_assumption": "next_session"}, "execution_allowed": False},
    }
    _bind_available_evidence(evidence)
    return evidence


def _bind_available_evidence(value: object) -> None:
    if isinstance(value, dict):
        if value.get("as_of") == "2026-08-21":
            value["as_of"] = "2026-08-21T00:00:00Z"
        if value.get("status") == "available":
            value.setdefault("version", "evidence.v1")
            value.setdefault("source_id", "evidence:test")
            value.setdefault("source_dataset", "local:test")
            value.setdefault("source_digest", _SOURCE_DIGEST)
            value.setdefault("as_of", "2026-08-21T00:00:00Z")
            value.setdefault("known_at", "2026-08-21T12:00:00Z")
            value.setdefault("trust", True)
            value.setdefault("source_bound", True)
        for item in value.values():
            _bind_available_evidence(item)
    elif isinstance(value, list):
        for item in value:
            _bind_available_evidence(item)


def _build(evidence: dict[str, object] | None = None):
    values = evidence or _full_evidence()
    return build_monthly_decision_template(
        benchmark_reference=_reference(), alternatives=values["alternatives"],
        expected_returns=values["expected_returns"], optimiser=values["optimiser"],
        costs=values["costs"], events=values["events"],
        forward_evidence=values["forward_evidence"], paper_outcomes=values["paper_outcomes"],
        concentration=values["concentration"], assumptions=values["assumptions"],
        benchmark_registry=_TEST_REGISTRY, evidence_maturity="mature", sample_size=4,
    )


def _walk(control):
    if control is None:
        return
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    for row in getattr(control, "rows", ()) or ():
        for cell in getattr(row, "cells", ()) or ():
            yield from _walk(getattr(cell, "content", None))


def _text(control) -> str:
    return "\n".join(str(item.value) for item in _walk(control) if isinstance(item, ft.Text))


def _assert_execution_disabled(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "execution_allowed":
                assert item is False
            _assert_execution_disabled(item)
    elif isinstance(value, list):
        for item in value:
            _assert_execution_disabled(item)


def test_full_projection_preserves_canonical_evidence_without_calculation() -> None:
    result = _build()
    projection = result.projection()

    assert result.status == "available"
    assert projection["alternatives"]["basket"]["benchmark_relative_return"] == 0.02
    assert projection["alternatives"]["basket"]["cash_relative_return"] == 0.04
    assert projection["expected_returns"]["gross"] == {"q10": -0.03, "q50": 0.06, "q90": 0.14}
    assert projection["expected_returns"]["net"]["q50"] == 0.055
    assert projection["expected_returns"]["version"] == "distribution.v2"
    assert projection["optimiser"]["constraints"]["values"]["turnover_limit"] == 0.15
    assert projection["optimiser"]["solution"]["diagnostics"]["binding_constraints"] == ["max_weight"]
    assert projection["costs"]["components"][0]["market_impact_bps"] == 3.0
    assert projection["costs"]["capacity"]["amount_eur"] == 75_000.0
    assert projection["events"]["next_session"]["execution_delay_sessions"] == 1
    assert projection["forward_evidence"]["snapshot"]["snapshot_id"] == "forward:42"
    assert projection["paper_outcomes"]["matured_outcomes"] == 4
    assert set(projection["alternatives"]) == {"basket", "benchmark", "cash", "no_action"}
    _assert_execution_disabled(projection)
    rendered = "\n".join(monthly_decision_template_lines(result)).casefold()
    assert "gross=" in rendered and "net=" in rendered and "vs no-action=" in rendered
    assert "buy" not in rendered and "sell" not in rendered


def test_missing_producers_are_explicitly_unavailable_and_warn_as_young() -> None:
    result = build_monthly_decision_template(
        benchmark_reference=_reference(),
        benchmark_registry=_TEST_REGISTRY,
        evidence_maturity="young/noisy",
        sample_size=1,
    )
    projection = result.projection()

    assert result.status == "partial"
    assert all(value["status"] == "unavailable" for value in projection["alternatives"].values())
    for name in ("expected_returns", "optimiser", "costs", "events", "forward_evidence", "paper_outcomes", "concentration", "assumptions"):
        assert projection[name]["status"] == "unavailable"
    assert any("Young/noisy live/paper warning" in item for item in result.warnings)
    _assert_execution_disabled(projection)


@pytest.mark.parametrize(
    ("section", "mutation"),
    [
        ("expected_returns", lambda value: value["gross"].update(q50="not-a-number")),
        ("optimiser", lambda value: value["solution"]["diagnostics"].update(binding_constraints="max_weight")),
        ("costs", lambda value: value["capacity"].update(amount_eur=float("nan"))),
        ("events", lambda value: value["next_session"].update(execution_delay_sessions=0)),
        ("forward_evidence", lambda value: value.update(snapshot=[])),
        ("paper_outcomes", lambda value: value.update(outcomes="matured")),
        ("concentration", lambda value: value["sector"].update(max_weight=1.2)),
        ("assumptions", lambda value: value["values"].update(rebalance_cadence="weekly")),
    ],
)
def test_malformed_nested_evidence_fails_closed(section: str, mutation) -> None:
    evidence = deepcopy(_full_evidence())
    mutation(evidence[section])
    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()[section]["status"] == "unavailable"
    assert any(
        blocker in {f"{section}_invalid", f"{section}_malformed"}
        for blocker in result.blockers
    )
    _assert_execution_disabled(result.projection())


@pytest.mark.parametrize(
    "path",
    [
        ("alternatives", "basket"), ("expected_returns", "gross"),
        ("optimiser", "solution", "diagnostics"), ("costs", "components", 0),
        ("events", "next_session"), ("forward_evidence", "snapshot"),
        ("paper_outcomes", "outcomes", 0), ("concentration", "sector"),
        ("assumptions", "values"),
    ],
)
def test_nested_execution_authority_injection_fails_closed(path: tuple[object, ...]) -> None:
    evidence = deepcopy(_full_evidence())
    target: object = evidence
    for part in path:
        target = target[part]  # type: ignore[index]
    assert isinstance(target, dict)
    target["execution_allowed"] = True

    result = _build(evidence)
    assert result.status == "unavailable"
    assert any("authority_invalid" in blocker for blocker in result.blockers)
    _assert_execution_disabled(result.projection())


def test_reference_execution_authority_injection_fails_closed() -> None:
    reference = _reference()
    reference["references"][0]["execution_allowed"] = True  # type: ignore[index]
    evidence = _full_evidence()
    result = build_monthly_decision_template(
        benchmark_reference=reference,
        benchmark_registry=_TEST_REGISTRY,
        **evidence,
    )

    assert result.status == "unavailable"
    assert "canonical_reference_authority_invalid" in result.blockers
    _assert_execution_disabled(result.projection())


def test_explicitly_unavailable_canonical_no_action_reference_fails_closed() -> None:
    reference = _reference()
    reference["references"][0]["status"] = "unavailable"  # type: ignore[index]

    result = build_monthly_decision_template(
        benchmark_reference=reference,
        benchmark_registry=_TEST_REGISTRY,
        **_full_evidence(),
    )

    assert result.status == "unavailable"
    assert "canonical_reference_invalid" in result.blockers


def test_omitted_canonical_no_action_status_remains_compatible() -> None:
    reference = _reference()
    del reference["references"][0]["status"]  # type: ignore[index]

    result = build_monthly_decision_template(
        benchmark_reference=reference,
        benchmark_registry=_TEST_REGISTRY,
        **_full_evidence(),
    )

    assert result.status == "available"


@pytest.mark.parametrize("location", ["alternative", "reference", "section"])
def test_timezone_naive_known_decision_and_knowledge_timestamps_fail_closed(location: str) -> None:
    evidence = _full_evidence()
    reference = _reference()
    if location == "alternative":
        evidence["alternatives"]["basket"]["known_at"] = "2026-08-21T12:00:00"  # type: ignore[index]
    elif location == "reference":
        reference["analysis"]["decision_time"] = "2026-08-21T23:59:59"  # type: ignore[index]
    else:
        evidence["events"]["knowledge_cutoff"] = "2026-08-21T23:59:59"  # type: ignore[index]

    result = build_monthly_decision_template(
        benchmark_reference=reference,
        benchmark_registry=_TEST_REGISTRY,
        **evidence,
    )

    assert result.status == "unavailable"
    _assert_execution_disabled(result.projection())


def test_known_at_must_not_exceed_any_supplied_cutoff() -> None:
    evidence = deepcopy(_full_evidence())
    expected_returns = evidence["expected_returns"]
    assert isinstance(expected_returns, dict)
    expected_returns.update(
        known_at="2026-08-21T12:00:00Z",
        decision_time="2026-08-21T23:00:00Z",
        knowledge_cutoff="2026-08-21T10:00:00Z",
    )

    result = _build(evidence)

    assert result.status == "unavailable"
    assert any("future_known" in blocker for blocker in result.blockers)


def test_available_reference_without_authoritative_registry_fails_closed() -> None:
    evidence = _full_evidence()

    result = build_monthly_decision_template(benchmark_reference=_reference(), **evidence)
    rendered = "\n".join(monthly_decision_template_lines(result))

    assert result.status == "unavailable"
    assert result.benchmark_reference == {
        "status": "unavailable",
        "reason": "canonical_reference_validation_failed",
        "execution_allowed": False,
    }
    assert "canonical_reference_invalid" in result.blockers
    assert all(item["status"] == "unavailable" for item in result.projection()["alternatives"].values())
    assert "return=+" not in rendered


def test_recursive_reference_and_section_evidence_fail_closed() -> None:
    recursive_reference = _reference()
    recursive_reference["nested"] = recursive_reference

    reference_result = build_monthly_decision_template(
        benchmark_reference=recursive_reference,
        benchmark_registry=_TEST_REGISTRY,
    )

    assert reference_result.status == "unavailable"
    assert "canonical_reference_authority_invalid" in reference_result.blockers

    recursive_section: dict[str, object] = {"status": "partial", "reason": "recursive"}
    recursive_section["nested"] = recursive_section
    evidence = _full_evidence()
    evidence["forward_evidence"] = recursive_section

    section_result = _build(evidence)

    assert section_result.status == "unavailable"
    assert "forward_evidence_authority_invalid" in section_result.blockers


def test_nested_result_evidence_is_immutable_and_projection_is_isolated() -> None:
    result = _build()

    with pytest.raises(TypeError):
        result.alternatives["basket"]["period_return"] = 0.99  # type: ignore[index]
    with pytest.raises(TypeError):
        result.expected_returns["gross"]["q50"] = 0.99  # type: ignore[index]

    projection = result.projection()
    projection["alternatives"]["basket"]["period_return"] = 0.99  # type: ignore[index]
    assert result.projection()["alternatives"]["basket"]["period_return"] == 0.07
    _assert_execution_disabled(result.projection())


@pytest.mark.parametrize(
    ("section", "updates"),
    [
        ("costs", {"capacity": {"amount_eur": -1.0}}),
        ("costs", {"total": {"cost_eur": -1.0}}),
        ("optimiser", {"solution": {"weights": {"VWCE": -0.1}}}),
        ("forward_evidence", {"as_of": "2026-08-22", "known_at": "2026-08-23T00:00:00Z"}),
        ("paper_outcomes", {"trust_status": "untrusted"}),
        ("events", {"source_bound": False}),
    ],
)
def test_temporal_trust_binding_and_financial_signs_fail_closed(section: str, updates: dict[str, object]) -> None:
    evidence = deepcopy(_full_evidence())
    target = evidence[section]
    assert isinstance(target, dict)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key].update(value)  # type: ignore[index]
        else:
            target[key] = value

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()[section]["status"] == "unavailable"
    _assert_execution_disabled(result.projection())


def test_horizon_mismatch_fails_closed() -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["cash"]["horizon_days"] = 20  # type: ignore[index]
    evidence["alternatives"]["benchmark"]["horizon_days"] = 21  # type: ignore[index]

    result = _build(evidence)

    assert result.status == "unavailable"
    assert "monthly_horizon_mismatch" in result.blockers
    _assert_execution_disabled(result.projection())


@pytest.mark.parametrize("field", ["as_of", "known_at"])
def test_alternatives_require_one_exact_normalized_window(field: str) -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["cash"][field] = "2026-08-20T00:00:00Z" if field == "as_of" else "2026-08-21T13:00:00Z"  # type: ignore[index]

    result = _build(evidence)

    assert result.status == "unavailable"
    assert "monthly_horizon_mismatch" in result.blockers
    assert result.projection()["alternatives"]["basket"]["status"] == "unavailable"


@pytest.mark.parametrize("field", ["version", "source_dataset", "source_digest"])
def test_alternatives_require_one_exact_source_bundle(field: str) -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["cash"][field] = "b" * 64 if field == "source_digest" else "different"  # type: ignore[index]

    result = _build(evidence)

    assert result.status == "unavailable"
    assert "monthly_comparison_bundle_invalid" in result.blockers


def test_known_at_cannot_precede_as_of() -> None:
    evidence = deepcopy(_full_evidence())
    for alternative in evidence["alternatives"].values():  # type: ignore[union-attr]
        alternative["as_of"] = "2026-08-21T12:00:00Z"
        alternative["known_at"] = "2026-08-21T11:59:59Z"

    result = _build(evidence)

    assert result.status == "unavailable"
    assert any("temporal_invalid" in blocker for blocker in result.blockers)


def test_partial_alternative_rejects_malformed_supplied_financial_value() -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["basket"] = {
        "status": "partial",
        "reason": "incomplete",
        "period_return": "not-a-number",
        "execution_allowed": False,
    }

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["basket"]["status"] == "unavailable"


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("version", ""),
        ("source_id", ""),
        ("source_dataset", ""),
        ("trust", False),
        ("source_bound", False),
    ],
)
def test_partial_financial_alternative_requires_complete_positive_binding(field: str, invalid: object) -> None:
    evidence = deepcopy(_full_evidence())
    basket = evidence["alternatives"]["basket"]  # type: ignore[index]
    basket["status"] = "partial"
    basket["reason"] = "incomplete"
    basket[field] = invalid

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["basket"]["status"] == "unavailable"
    assert "return=+7.00%" not in "\n".join(monthly_decision_template_lines(result))


def test_partial_no_action_financial_value_requires_no_trade_method() -> None:
    evidence = deepcopy(_full_evidence())
    no_action = evidence["alternatives"]["no_action"]  # type: ignore[index]
    no_action["status"] = "partial"
    no_action["reason"] = "incomplete"
    no_action["reference_method"] = "buy_and_hold"

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["no_action"]["status"] == "unavailable"


def test_partial_financial_leg_is_rejected_before_bundle_comparison() -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["no_action"].update(status="partial", reason="incomplete")  # type: ignore[index]
    evidence["alternatives"]["cash"]["source_digest"] = "b" * 64  # type: ignore[index]

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["no_action"]["status"] == "unavailable"


def test_partial_relative_returns_are_never_rendered() -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["basket"] = {
        "status": "partial",
        "reason": "incomplete",
        "benchmark_relative_return": 0.02,
        "cash_relative_return": 0.04,
        "no_action_relative_return": 0.03,
        "execution_allowed": False,
    }

    result = _build(evidence)
    rendered = "\n".join(monthly_decision_template_lines(result))

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["basket"]["status"] == "unavailable"
    assert "vs benchmark=+2.00%" not in rendered


@pytest.mark.parametrize("field", ["return", "relative_return", "net_return"])
def test_nested_partial_financial_return_keys_fail_closed(field: str) -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["basket"] = {  # type: ignore[index]
        "status": "partial",
        "reason": "incomplete",
        "context": {"nested": {field: 0.07}},
        "execution_allowed": False,
    }

    result = _build(evidence)
    rendered = "\n".join(monthly_decision_template_lines(result))

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["basket"]["status"] == "unavailable"
    assert "Basket: unavailable | return=unavailable" in rendered
    assert field not in result.projection()["alternatives"]["basket"]


@pytest.mark.parametrize("section", ["expected_returns", "optimiser", "costs", "forward_evidence", "paper_outcomes", "events"])
@pytest.mark.parametrize("status", ["unavailable", "partial"])
def test_nested_return_keys_in_non_available_sections_fail_closed(section: str, status: str) -> None:
    evidence = deepcopy(_full_evidence())
    evidence[section] = {
        "status": status,
        "reason": "not_produced",
        "context": {"deep": {"net_return": 0.42}},
        "execution_allowed": False,
    }

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()[section] == {
        "status": "unavailable",
        "reason": f"{section}_evidence_invalid",
        "execution_allowed": False,
    }


@pytest.mark.parametrize("location", ["section", "alternative"])
def test_nested_non_available_mapping_cannot_retain_return_under_available_parent(location: str) -> None:
    evidence = deepcopy(_full_evidence())
    nested = {
        "status": "unavailable",
        "reason": "not_produced",
        "net_return": 0.42,
        "execution_allowed": False,
    }
    if location == "section":
        evidence["events"]["replay"] = nested  # type: ignore[index]
    else:
        evidence["alternatives"]["basket"]["context"] = {"deep": nested}  # type: ignore[index]

    result = _build(evidence)

    assert result.status == "unavailable"
    target = result.projection()["events" if location == "section" else "alternatives"]
    if location == "section":
        assert target["status"] == "unavailable"
    else:
        assert target["basket"]["status"] == "unavailable"


@pytest.mark.parametrize("field", ["source_id", "source_dataset", "backtest_version"])
@pytest.mark.parametrize("invalid", [{"malformed": True}, ["malformed"]])
def test_backtest_adapter_does_not_stringify_malformed_source_identity(field: str, invalid: object) -> None:
    curves = pd.DataFrame(
        {name: [1.0, value] for name, value in {"basket": 1.07, "benchmark": 1.05, "cash": 1.03, "no_action": 1.04}.items()},
        index=pd.to_datetime(["2026-07-31", "2026-08-21"]),
    )
    metadata: dict[str, object] = {
        "input_checksum": _SOURCE_DIGEST,
        "source_id": "backtest:42",
        "source_dataset": "backtest:2026-07-31:2026-08-21",
        "backtest_version": "backtest.equity.v1",
        "known_at": "2026-08-21T12:00:00Z",
        "trust": True,
        "source_bound": True,
    }
    metadata[field] = invalid

    alternatives = backtests._monthly_backtest_alternatives(
        SimpleNamespace(equity_curves=curves), metadata, reference=_reference()
    )

    assert all(item["status"] == "unavailable" for item in alternatives.values())  # type: ignore[union-attr]
    assert all(item["reason"] == "backtest_monthly_source_identity_invalid" for item in alternatives.values())  # type: ignore[union-attr]


def test_backtest_adapter_does_not_coerce_forged_checksum_identity() -> None:
    class ForgedChecksum(dict):
        def __str__(self) -> str:
            return "a" * 64

    curves = pd.DataFrame(
        {name: [1.0, value] for name, value in {"basket": 1.07, "benchmark": 1.05, "cash": 1.03, "no_action": 1.04}.items()},
        index=pd.to_datetime(["2026-07-31", "2026-08-21"]),
    )
    metadata = {
        "input_checksum": ForgedChecksum(),
        "source_id": "backtest:42",
        "source_dataset": "backtest:2026-07-31:2026-08-21",
        "backtest_version": "backtest.equity.v1",
        "known_at": "2026-08-21T12:00:00Z",
        "trust": True,
        "source_bound": True,
    }

    alternatives = backtests._monthly_backtest_alternatives(
        SimpleNamespace(equity_curves=curves), metadata, reference=_reference()
    )
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"] = alternatives
    result = _build(evidence)
    rendered = "\n".join(monthly_decision_template_lines(result))

    assert all(item["status"] == "unavailable" for item in alternatives.values())  # type: ignore[union-attr]
    assert result.status != "available"
    assert "return=+" not in rendered


@pytest.mark.parametrize("suffix", ["replay", "next-session"])
@pytest.mark.parametrize("field", ["backtest_version", "source_id", "source_dataset"])
@pytest.mark.parametrize("invalid", [{"malformed": True}, ["malformed"]])
def test_nested_backtest_evidence_does_not_stringify_malformed_identity(
    suffix: str, field: str, invalid: object
) -> None:
    field_prefix = suffix.replace("-", "_")
    metadata: dict[str, object] = {
        "input_checksum": _SOURCE_DIGEST,
        "source_id": "backtest:42",
        "source_dataset": "backtest:2026-07-31:2026-08-21",
        "backtest_version": "backtest.equity.v1",
        "date_range_end": "2026-08-21",
        "known_at": "2026-08-21T12:00:00Z",
        "trust": True,
        "source_bound": True,
        f"{field_prefix}_source_id": f"{suffix}:42",
        f"{field_prefix}_source_dataset": "backtest:2026-07-31:2026-08-21",
    }
    metadata[field if field == "backtest_version" else f"{field_prefix}_{field}"] = invalid

    assert backtests._backtest_evidence_fields(metadata, suffix) == {}

    evidence = deepcopy(_full_evidence())
    evidence["events"][field_prefix] = {  # type: ignore[index]
        "status": "available",
        **backtests._backtest_evidence_fields(metadata, suffix),
        "execution_allowed": False,
    }
    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["events"]["status"] == "unavailable"


@pytest.mark.parametrize("field", ["version", "source_id", "source_dataset"])
@pytest.mark.parametrize("invalid", [{"malformed": True}, ["malformed"]])
def test_available_alternative_identity_must_be_non_empty_text(field: str, invalid: object) -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["basket"][field] = invalid  # type: ignore[index]

    result = _build(evidence)
    rendered = "\n".join(monthly_decision_template_lines(result))

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["basket"]["status"] == "unavailable"
    assert "Basket: available" not in rendered


def test_partial_no_action_return_with_fabricated_identity_is_never_rendered() -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["no_action"] = {
        "status": "partial",
        "reason": "incomplete",
        "period_return": 0.04,
        "reference_id": "fabricated",
        "reference_version": "9.9.9",
        "reference_content_hash": "fabricated-hash",
        "execution_allowed": False,
    }

    result = _build(evidence)
    rendered = "\n".join(monthly_decision_template_lines(result))

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["no_action"]["status"] == "unavailable"
    assert "return=+4.00%" not in rendered


def test_nested_partial_return_is_never_preserved() -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["basket"] = {
        "status": "partial",
        "reason": "incomplete",
        "detail": {"period_return": 0.07, "execution_allowed": False},
        "execution_allowed": False,
    }

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["basket"]["status"] == "unavailable"


def test_available_basket_requires_every_comparator_before_rendering_relatives() -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["no_action"] = {
        "status": "unavailable",
        "reason": "no_action_unavailable",
        "execution_allowed": False,
    }

    result = _build(evidence)
    rendered = "\n".join(monthly_decision_template_lines(result))

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["basket"]["status"] == "unavailable"
    assert "vs no-action=+3.00%" not in rendered


def test_partial_forward_evidence_validates_malformed_nested_outcomes() -> None:
    evidence = deepcopy(_full_evidence())
    evidence["forward_evidence"]["status"] = "partial"  # type: ignore[index]
    evidence["forward_evidence"]["outcomes"] = [{"status": "available", "horizon_days": "not-a-number"}]  # type: ignore[index]

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["forward_evidence"]["status"] == "unavailable"
    assert "forward_evidence_invalid" in result.blockers


def test_basket_relative_returns_must_reconcile_with_period_returns() -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["basket"]["cash_relative_return"] = 0.041  # type: ignore[index]

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["basket"]["status"] == "unavailable"
    assert "basket_relative_invalid" in result.blockers


@pytest.mark.parametrize("path", [("expected_returns",), ("optimiser", "solution", "diagnostics")])
def test_available_evidence_requires_positive_trust_and_source_binding(path: tuple[str, ...]) -> None:
    evidence = deepcopy(_full_evidence())
    target: object = evidence
    for part in path:
        target = target[part]  # type: ignore[index]
    assert isinstance(target, dict)
    del target["trust"]

    result = _build(evidence)

    assert result.status == "unavailable"
    _assert_execution_disabled(result.projection())


@pytest.mark.parametrize("field", ["horizon_days", "source_digest", "as_of", "known_at"])
def test_available_alternative_requires_complete_bound_evidence(field: str) -> None:
    evidence = deepcopy(_full_evidence())
    del evidence["alternatives"]["basket"][field]  # type: ignore[index]

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["basket"]["status"] == "unavailable"


@pytest.mark.parametrize("field", ["source_digest", "as_of", "known_at"])
def test_available_distribution_requires_complete_bound_evidence(field: str) -> None:
    evidence = deepcopy(_full_evidence())
    del evidence["expected_returns"][field]  # type: ignore[index]

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["expected_returns"]["status"] == "unavailable"


@pytest.mark.parametrize("field", ["reference_version", "reference_content_hash"])
def test_alternative_requires_exact_canonical_reference_identity(field: str) -> None:
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"]["benchmark"][field] = "mismatch"  # type: ignore[index]

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["benchmark"]["status"] == "unavailable"


def test_basket_requires_no_action_comparison() -> None:
    evidence = deepcopy(_full_evidence())
    del evidence["alternatives"]["basket"]["no_action_relative_return"]  # type: ignore[index]

    result = _build(evidence)

    assert result.status == "unavailable"
    assert result.projection()["alternatives"]["basket"]["status"] == "unavailable"


def test_strategy_template_frame_retains_required_projection_inputs() -> None:
    frame = strategy_template_frame(pd.DataFrame([{"instrument_id": "VWCE", "q10_expected_return": -0.03, "q50_expected_return": 0.06, "q90_expected_return": 0.14, "net_q10_expected_return": -0.035, "net_expected_return": 0.055, "net_q90_expected_return": 0.135, "expected_return_distribution_version": "distribution.v2", "expected_return_source_dataset": "features:2026-08", "expected_return_cost_bps": 12.5, "expected_return_cost_eur": 12.5, "expected_return_cost_ratio": 0.00125, "execution_allowed": False}]))

    assert {"q10_expected_return", "q50_expected_return", "q90_expected_return", "net_q10_expected_return", "net_expected_return", "net_q90_expected_return", "expected_return_distribution_version", "expected_return_source_dataset", "expected_return_cost_bps", "expected_return_cost_eur", "expected_return_cost_ratio", "execution_allowed"} <= set(frame.columns)
    assert frame.iloc[0]["execution_allowed"] == False  # noqa: E712


@pytest.mark.parametrize("invalid", [True, False, float("inf"), float("-inf")])
def test_strategy_distribution_component_rejects_non_financial_numbers(invalid: object) -> None:
    row = {
        "instrument_id": "VWCE",
        "q10_expected_return": invalid,
        "q50_expected_return": 0.06,
        "q90_expected_return": 0.14,
        "net_q10_expected_return": -0.035,
        "net_expected_return": 0.055,
        "net_q90_expected_return": 0.135,
        "expected_return_horizon_days": 21,
        "expected_return_distribution_version": "distribution.v2",
        "expected_return_source_dataset": "features:2026-08",
    }

    projection = data_models._strategy_distribution_component(row)

    assert projection == {
        "instrument_id": "VWCE",
        "status": "unavailable",
        "reason": "complete_gross_net_distribution_unavailable",
        "execution_allowed": False,
    }


def test_backtest_alternative_writer_is_accepted_by_generic_composer() -> None:
    curves = pd.DataFrame(
        {
            "basket": [1.0, 1.07],
            "benchmark": [1.0, 1.05],
            "cash": [1.0, 1.03],
            "no_action": [1.0, 1.04],
        },
        index=pd.to_datetime(["2026-07-31", "2026-08-21"]),
    )
    metadata = {
        "input_checksum": _SOURCE_DIGEST,
        "source_id": "backtest:42",
        "source_dataset": "backtest:2026-07-31:2026-08-21",
        "backtest_version": "backtest.equity.v1",
        "date_range_start": "2026-07-31",
        "date_range_end": "2026-08-21",
        "known_at": "2026-08-21T12:00:00Z",
        "trust": True,
        "source_bound": True,
        "monthly_benchmark_reference_id": "benchmark:global",
        "monthly_benchmark_reference_version": "1.0.0",
        "monthly_benchmark_reference_content_hash": "benchmark-hash",
        "monthly_cash_reference_id": "cash:EUR",
        "monthly_cash_reference_version": "1.0.0",
        "monthly_cash_reference_content_hash": "cash-hash",
        "monthly_no_action_reference_id": "reference:no-trade",
        "monthly_no_action_reference_version": "1.0.0",
        "monthly_no_action_reference_content_hash": "no-trade-hash",
        "no_action_constituents": ["VWCE"],
        "no_action_weights": {"VWCE": 1.0},
    }
    alternatives = backtests._monthly_backtest_alternatives(
        SimpleNamespace(equity_curves=curves), metadata, reference=_reference()
    )
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"] = alternatives

    result = _build(evidence)

    assert result.status == "available"
    assert result.projection()["alternatives"]["basket"]["no_action_relative_return"] == pytest.approx(0.03)


def test_backtest_no_action_does_not_synthesize_current_registry_identity() -> None:
    curves = pd.DataFrame(
        {
            "basket": [1.0, 1.07],
            "benchmark": [1.0, 1.05],
            "cash": [1.0, 1.03],
            "no_action": [1.0, 1.04],
        },
        index=pd.to_datetime(["2026-07-31", "2026-08-21"]),
    )
    metadata = {
        "input_checksum": _SOURCE_DIGEST,
        "source_id": "backtest:42",
        "source_dataset": "backtest:2026-07-31:2026-08-21",
        "backtest_version": "backtest.equity.v1",
        "known_at": "2026-08-21T12:00:00Z",
        "trust": True,
        "source_bound": True,
        "monthly_benchmark_reference_id": "benchmark:global",
        "monthly_benchmark_reference_version": "1.0.0",
        "monthly_benchmark_reference_content_hash": "benchmark-hash",
        "monthly_cash_reference_id": "cash:EUR",
        "monthly_cash_reference_version": "1.0.0",
        "monthly_cash_reference_content_hash": "cash-hash",
    }

    alternatives = backtests._monthly_backtest_alternatives(
        SimpleNamespace(equity_curves=curves), metadata, reference=_reference()
    )

    assert alternatives["no_action"]["status"] == "unavailable"  # type: ignore[index]
    assert alternatives["no_action"]["reason"] == "backtest_monthly_no_action_binding_unavailable"  # type: ignore[index]


def test_backtest_no_action_binding_must_match_canonical_constituents_and_weights() -> None:
    curves = pd.DataFrame(
        {name: [1.0, value] for name, value in {"basket": 1.07, "benchmark": 1.05, "cash": 1.03, "no_action": 1.04}.items()},
        index=pd.to_datetime(["2026-07-31", "2026-08-21"]),
    )
    metadata = {
        "input_checksum": _SOURCE_DIGEST,
        "source_id": "backtest:42",
        "source_dataset": "backtest:2026-07-31:2026-08-21",
        "backtest_version": "backtest.equity.v1",
        "known_at": "2026-08-21T12:00:00Z",
        "trust": True,
        "source_bound": True,
        "monthly_no_action_reference_id": "reference:no-trade",
        "monthly_no_action_reference_version": "1.0.0",
        "monthly_no_action_reference_content_hash": "no-trade-hash",
        "no_action_constituents": ["VWCE"],
        "no_action_weights": {"VWCE": 0.5},
    }

    alternatives = backtests._monthly_backtest_alternatives(
        SimpleNamespace(equity_curves=curves), metadata, reference=_reference()
    )

    assert alternatives["no_action"]["status"] == "unavailable"  # type: ignore[index]
    assert alternatives["no_action"]["reason"] == "backtest_monthly_no_action_binding_unavailable"  # type: ignore[index]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda reference: reference["references"][0].update(current_weights={"VWCE": "invalid"}),
        lambda reference: reference["references"][0].update(constituent_instrument_ids=[["VWCE"]]),
        lambda reference: reference["references"][0].update(constituent_instrument_ids=["VWCE", "VWCE"]),
        lambda reference: reference["references"][0].update(current_weights={"VWCE": 1.0, "EXTRA": 0.0}),
    ],
)
def test_malformed_canonical_no_action_binding_fails_closed(mutation) -> None:
    reference = _reference()
    mutation(reference)
    curves = pd.DataFrame(
        {name: [1.0, value] for name, value in {"basket": 1.07, "benchmark": 1.05, "cash": 1.03, "no_action": 1.04}.items()},
        index=pd.to_datetime(["2026-07-31", "2026-08-21"]),
    )
    metadata = {
        "monthly_no_action_reference_id": "reference:no-trade",
        "monthly_no_action_reference_version": "1.0.0",
        "monthly_no_action_reference_content_hash": "no-trade-hash",
        "no_action_constituents": ["VWCE"],
        "no_action_weights": {"VWCE": 1.0},
    }

    alternatives = backtests._monthly_backtest_alternatives(
        SimpleNamespace(equity_curves=curves), metadata, reference=reference
    )

    assert alternatives["no_action"]["status"] == "unavailable"  # type: ignore[index]


def test_malformed_canonical_reference_collection_fails_closed() -> None:
    reference = _reference()
    reference["references"] = None
    curves = pd.DataFrame(
        {name: [1.0, value] for name, value in {"basket": 1.07, "benchmark": 1.05, "cash": 1.03, "no_action": 1.04}.items()},
        index=pd.to_datetime(["2026-07-31", "2026-08-21"]),
    )
    metadata = {
        "input_checksum": _SOURCE_DIGEST,
        "source_id": "backtest:42",
        "source_dataset": "backtest:2026-07-31:2026-08-21",
        "backtest_version": "backtest.equity.v1",
        "known_at": "2026-08-21T12:00:00Z",
        "trust": True,
        "source_bound": True,
        "monthly_no_action_reference_id": "reference:no-trade",
        "monthly_no_action_reference_version": "1.0.0",
        "monthly_no_action_reference_content_hash": "no-trade-hash",
        "no_action_constituents": ["VWCE"],
        "no_action_weights": {"VWCE": 1.0},
    }

    alternatives = backtests._monthly_backtest_alternatives(
        SimpleNamespace(equity_curves=curves), metadata, reference=reference
    )

    assert alternatives["no_action"]["status"] == "unavailable"  # type: ignore[index]
    assert alternatives["basket"]["status"] == "unavailable"  # type: ignore[index]


def test_backtest_comparisons_require_sorted_shared_non_null_endpoints() -> None:
    curves = pd.DataFrame(
        {
            "basket": [1.0, 1.07, 1.08],
            "benchmark": [float("nan"), 1.02, float("nan")],
            "cash": [1.0, 1.03, 1.04],
            "no_action": [1.0, 1.04, 1.05],
        },
        index=pd.to_datetime(["2026-07-31", "2026-08-10", "2026-08-21"]),
    )

    alternatives = backtests._monthly_backtest_alternatives(SimpleNamespace(equity_curves=curves), {})

    assert all(value["status"] == "unavailable" for value in alternatives.values())  # type: ignore[index]
    assert all("comparison_window" in value["reason"] for value in alternatives.values())  # type: ignore[index]


def test_backtest_comparison_columns_must_be_distinct() -> None:
    curves = pd.DataFrame(
        {"basket": [1.0, 1.07], "cash": [1.0, 1.03], "no_action": [1.0, 1.04]},
        index=pd.to_datetime(["2026-07-31", "2026-08-21"]),
    )

    alternatives = backtests._monthly_backtest_alternatives(
        SimpleNamespace(equity_curves=curves), {"benchmark_data_id": "basket"}
    )

    assert all(value["status"] == "unavailable" for value in alternatives.values())  # type: ignore[index]
    assert all(value["reason"] == "backtest_monthly_comparison_identity_ambiguous" for value in alternatives.values())  # type: ignore[index]


def test_strategy_alternative_writer_is_accepted_by_generic_composer() -> None:
    row: dict[str, object] = {"instrument_id": "VWCE"}
    for name, period_return in {"basket": 0.07, "benchmark": 0.05, "cash": 0.03, "no_action": 0.04}.items():
        row.update(
            {
                f"monthly_{name}_return": period_return,
                f"monthly_{name}_version": "returns.v3",
                f"monthly_{name}_source_id": f"{name}:42",
                f"monthly_{name}_source_dataset": "forward:2026-08",
                f"monthly_{name}_source_digest": _SOURCE_DIGEST,
                f"monthly_{name}_as_of": "2026-08-21T00:00:00Z",
                f"monthly_{name}_known_at": "2026-08-21T12:00:00Z",
                f"monthly_{name}_horizon_days": 21,
                f"monthly_{name}_trust": True,
                f"monthly_{name}_source_bound": True,
                f"monthly_{name}_reference_id": {
                    "benchmark": "benchmark:global",
                    "cash": "cash:EUR",
                    "no_action": "reference:no-trade",
                }.get(name),
                f"monthly_{name}_reference_version": "1.0.0" if name != "basket" else None,
                f"monthly_{name}_reference_content_hash": {
                    "benchmark": "benchmark-hash",
                    "cash": "cash-hash",
                    "no_action": "no-trade-hash",
                }.get(name),
            }
        )
    alternatives = data_models._monthly_strategy_alternatives(pd.DataFrame([row]), _reference())
    evidence = deepcopy(_full_evidence())
    evidence["alternatives"] = alternatives

    result = _build(evidence)

    assert result.status == "available"
    assert result.projection()["alternatives"]["benchmark"]["reference_content_hash"] == "benchmark-hash"


def test_strategy_contributing_rows_must_agree_on_evidence_identity() -> None:
    row: dict[str, object] = {"instrument_id": "VWCE"}
    for name, period_return in {"basket": 0.07, "benchmark": 0.05, "cash": 0.03, "no_action": 0.04}.items():
        row.update(
            {
                f"monthly_{name}_return": period_return,
                f"monthly_{name}_version": "returns.v3",
                f"monthly_{name}_source_id": f"{name}:42",
                f"monthly_{name}_source_dataset": "forward:2026-08",
                f"monthly_{name}_source_digest": _SOURCE_DIGEST,
                f"monthly_{name}_as_of": "2026-08-21T00:00:00Z",
                f"monthly_{name}_known_at": "2026-08-21T12:00:00Z",
                f"monthly_{name}_horizon_days": 21,
                f"monthly_{name}_trust": True,
                f"monthly_{name}_source_bound": True,
                f"monthly_{name}_reference_id": {
                    "benchmark": "benchmark:global",
                    "cash": "cash:EUR",
                    "no_action": "reference:no-trade",
                }.get(name),
                f"monthly_{name}_reference_version": "1.0.0" if name != "basket" else None,
                f"monthly_{name}_reference_content_hash": {
                    "benchmark": "benchmark-hash",
                    "cash": "cash-hash",
                    "no_action": "no-trade-hash",
                }.get(name),
            }
        )
    second = deepcopy(row)
    second["instrument_id"] = "LYP6"
    second["monthly_basket_source_digest"] = "b" * 64

    alternatives = data_models._monthly_strategy_alternatives(pd.DataFrame([row, second]), _reference())

    assert alternatives["basket"]["status"] == "unavailable"  # type: ignore[index]
    assert alternatives["benchmark"]["status"] == "available"  # type: ignore[index]


def test_actual_ui_consumers_render_the_monthly_projection(monkeypatch, tmp_path) -> None:
    frame = pd.DataFrame([
        {"instrument_id": instrument_id, "q10_expected_return": -0.03, "q50_expected_return": 0.06, "q90_expected_return": 0.14, "net_q10_expected_return": -0.035, "net_expected_return": 0.055, "net_q90_expected_return": 0.135, "expected_return_horizon_days": 21, "expected_return_distribution_version": "distribution.v2", "expected_return_source_dataset": "features:2026-08", "expected_return_source_digest": _SOURCE_DIGEST, "expected_return_as_of": "2026-08-21", "expected_return_known_at": "2026-08-21T12:00:00Z", "sector_theme_warning": "partial", "crowding_top_ranked_theme_concentration": 0.18}
        for instrument_id in ("VWCE", "LYP6")
    ])
    frame.to_csv(tmp_path / "strategy_templates.csv", index=False)
    monkeypatch.setattr(data_models, "DERIVED_DIR", tmp_path)
    monkeypatch.setattr(data_models, "context_from_snapshot", lambda *_args, **_kwargs: SimpleNamespace(projection=_reference(), registry=_TEST_REGISTRY))
    strategy_text = data_models._monthly_decision_text(SimpleNamespace(snapshot=SimpleNamespace(universe_revision="revision:42")))
    assert "Expected-return distributions: partial" in strategy_text
    assert "components=2" in strategy_text
    assert "No-action context" in strategy_text

    report = SimpleNamespace(metadata={"execution_delay_sessions": 1, "same_bar_execution_avoided": True, "input_checksum": "backtest-input-hash", "price_field": "adjusted_close", "lookahead_protection": "enabled", "walk_forward_periods": 4}, quality_label="mature")
    backtest_panel = backtests._monthly_decision_panel(SimpleNamespace(projection=_reference(), registry=None), report=report, config=load_config())
    backtest_text = _text(backtest_panel)
    assert "Monthly decision template" in backtest_text
    assert "Events/next-session evidence: partial" in backtest_text
    assert "Basket: unavailable" in backtest_text

    snapshot = SimpleNamespace(
        config=load_config(),
        holdings=pd.DataFrame([{"etf_id": "VWCE", "current_weight": 1.0, "market_value_eur": 40_000.0, "as_of_date": "2026-08-21", "known_at": "2026-08-21T12:00:00Z"}]),
        universe_revision="revision:42", data_report=SimpleNamespace(as_of_date="2026-08-21"),
    )
    registry = CanonicalBenchmarkRegistry()
    snapshot.benchmark_reference_registry = registry
    captured_registries: list[object] = []
    original_builder = portfolio.build_monthly_decision_template

    def capture_builder(**kwargs):
        captured_registries.append(kwargs.get("benchmark_registry"))
        return original_builder(**kwargs)

    monkeypatch.setattr(portfolio, "build_monthly_decision_template", capture_builder)
    portfolio_text = _text(portfolio.portfolio_page(None, SimpleNamespace(snapshot=snapshot)))
    assert "Monthly decision template" in portfolio_text
    assert "No-action context: unavailable" in portfolio_text
    assert "execution_allowed=false" in portfolio_text
    assert any(item is registry for item in captured_registries)
