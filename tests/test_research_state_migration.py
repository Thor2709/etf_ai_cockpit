from __future__ import annotations

import importlib
import importlib.util
from dataclasses import asdict, is_dataclass


def _migration_module():
    """Load the migration API without turning the RED run into an import error."""
    spec = importlib.util.find_spec("etf_cockpit.governance.migrations")
    assert spec is not None, "governance migration contract is not implemented"
    return importlib.import_module("etf_cockpit.governance.migrations")


def _payload(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    return dict(value)


def test_v1_trim_migrates_lossily_and_preserves_original_value() -> None:
    module = _migration_module()
    migrated = module.migrate_legacy_action({"action": "trim", "schema_version": "1.0"})

    assert migrated.research_state.value == "hold_review"
    assert migrated.legacy_action == "trim"
    assert migrated.migration_semantics == "lossy"
    assert migrated.portfolio_review_state.value == "not_applicable"


def test_legacy_mapping_and_unknown_values_fail_closed() -> None:
    module = _migration_module()
    expected = {
        "buy": "research_candidate",
        "add": "research_candidate",
        "add_candidate": "research_candidate",
        "hold": "hold_review",
        "trim": "hold_review",
        "trim_candidate": "hold_review",
        "sell": "avoid",
        "no_trade": "needs_evidence",
        "manual_review": "manual_review",
    }

    for legacy, state in expected.items():
        migrated = module.migrate_legacy_action({"action": legacy, "schema_version": "1.0"})
        assert migrated.research_state.value == state
        assert migrated.legacy_action == legacy
        assert migrated.execution_allowed is False

    unknown = module.migrate_legacy_action({"action": "invented_positive", "schema_version": "1.0"})
    assert unknown.research_state.value == "manual_review"
    assert unknown.legacy_action == "invented_positive"
    assert unknown.research_promotion_allowed is False


def test_migration_is_idempotent_and_v2_exports_have_no_legacy_action_field() -> None:
    module = _migration_module()
    first = module.migrate_legacy_action({"action": "add", "schema_version": "1.0"})
    second = module.migrate_legacy_action(_payload(first))

    assert _payload(first) == _payload(second)
    payload = _payload(second)
    assert payload["schema_version"] == "2.0"
    assert payload["migration_version"] == "2.0"
    assert payload["execution_allowed"] is False
    assert "action" not in payload
    assert "final_action" not in payload
    assert payload["legacy_action"] == "add"


def test_public_state_enums_do_not_expose_legacy_action_verbs() -> None:
    module = importlib.import_module("etf_cockpit.signals.research_states")

    assert "buy" not in module.ResearchState._value2member_map_
    assert "sell" not in module.PortfolioReviewState._value2member_map_
    assert set(module.InternalSignalIntent._value2member_map_) == {
        "increase",
        "maintain",
        "decrease",
        "exit",
        "none",
    }


def test_portfolio_review_requires_explicit_snapshot_context() -> None:
    module = _migration_module()
    without_context = module.migrate_legacy_action({"action": "add", "schema_version": "1.0"})
    with_unrelated_context = module.migrate_legacy_action(
        {"action": "add", "schema_version": "1.0", "portfolio": {"notes": "not a snapshot"}}
    )

    assert without_context.portfolio_review_state.value == "not_applicable"
    assert with_unrelated_context.portfolio_review_state.value == "not_applicable"
    assert without_context.portfolio_review_allowed is False
    assert with_unrelated_context.portfolio_review_allowed is False


def test_explicit_snapshot_is_the_only_portfolio_review_context() -> None:
    module = _migration_module()
    migrated = module.migrate_legacy_action(
        {
            "action": "hold",
            "schema_version": "1.0",
            "portfolio_snapshot": {
                "as_of_date": "2026-07-10",
                "portfolio_review_state": "reduce_exposure_review",
            },
        }
    )

    assert migrated.portfolio_review_state.value == "reduce_exposure_review"
    assert migrated.portfolio_review_allowed is True
    assert migrated.execution_allowed is False


def test_v2_public_signal_serialisation_has_typed_authority_fields_only() -> None:
    from datetime import date

    from etf_cockpit.core.types import ComponentScores, SignalResult

    signal = SignalResult(
        run_id="run",
        signal_date=date(2026, 7, 10),
        etf_id="VWCE",
        action="add_candidate",
        confidence=0.5,
        total_score=0.4,
        components=ComponentScores(*(0.0 for _ in range(12))),
        blocked_by=[],
        warnings=[],
        reason_short="review",
        reason_long="review",
        horizon_primary="1-3 months",
    )

    payload = signal.to_v2_dict()
    assert payload["research_state"] == "research_candidate"
    assert payload["execution_allowed"] is False
    assert "action" not in payload
    assert "final_action" not in payload


def test_resolve_research_state_fails_closed_when_components_are_unavailable() -> None:
    module = importlib.import_module("etf_cockpit.signals.research_states")

    decision = module.AuthorityDecision(
        analysis_status="complete",
        research_state=module.ResearchState.RESEARCH_CANDIDATE,
        portfolio_review_state=module.PortfolioReviewState.NOT_APPLICABLE,
        research_promotion_allowed=True,
    )
    component = module.ScoreComponent(key="momentum", status="unavailable", score=None)

    assert module.resolve_research_state([component], decision) is module.ResearchState.NOT_SCOREABLE
