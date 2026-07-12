from __future__ import annotations

import importlib
import importlib.util
from dataclasses import asdict, is_dataclass

import pytest
from pydantic import ValidationError


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
    from etf_cockpit.core import types as core_types

    assert "buy" not in module.ResearchState._value2member_map_
    assert "sell" not in module.PortfolioReviewState._value2member_map_
    assert not hasattr(core_types, "Action")
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
                "holdings": [{"instrument_id": "VWCE", "weight": 0.5}],
            },
        }
    )

    assert migrated.portfolio_review_state.value == "reduce_exposure_review"
    assert migrated.portfolio_review_allowed is True
    assert migrated.execution_allowed is False


def test_explicit_snapshot_migration_is_byte_equivalent_on_repeat() -> None:
    module = _migration_module()
    source = {
        "action": "hold",
        "schema_version": "1.0",
        "portfolio_snapshot": {
            "as_of_date": "2026-07-10",
            "portfolio_review_state": "reduce_exposure_review",
            "holdings": [{"instrument_id": "VWCE", "weight": 0.5}],
        },
    }

    first = module.migrate_legacy_action(source)
    second = module.migrate_legacy_action(first.model_dump(mode="json"))

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.portfolio_review_allowed is True
    assert first.portfolio_snapshot_validated is True
    assert first.model_dump(mode="json").get("portfolio_snapshot_checksum") not in {None, "unavailable"}


def test_v2_snapshot_authority_requires_integrity_bound_source_evidence() -> None:
    module = _migration_module()
    forged = {
        "schema_version": "2.0",
        "research_state": "hold_review",
        "portfolio_review_state": "reduce_exposure_review",
        "portfolio_snapshot_validated": True,
        "portfolio_snapshot_provenance": "validated_snapshot",
        "portfolio_snapshot_checksum": "0" * 64,
        "portfolio_review_allowed": True,
    }

    migrated = module.migrate_legacy_action(forged)

    assert migrated.portfolio_review_allowed is False
    assert migrated.portfolio_snapshot_validated is False
    assert migrated.portfolio_snapshot_provenance == "unavailable"


@pytest.mark.parametrize(
    "snapshot",
    [
        {"portfolio_review_state": "reduce_exposure_review"},
        {"as_of_date": "not-a-date", "portfolio_review_state": "reduce_exposure_review"},
        {"as_of_date": "2026-07-10", "portfolio_review_state": "invented"},
        {"as_of_date": "2026-07-10", "holdings": "not-a-holdings-list"},
    ],
)
def test_state_only_or_malformed_snapshots_fail_closed(snapshot: dict[str, object]) -> None:
    module = _migration_module()
    migrated = module.migrate_legacy_action(
        {"action": "hold", "schema_version": "1.0", "portfolio_snapshot": snapshot}
    )

    assert migrated.portfolio_review_state.value == "not_applicable"
    assert migrated.portfolio_review_allowed is False
    assert migrated.portfolio_snapshot_validated is False


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


@pytest.mark.parametrize(
    "analysis_status,source_id,expected",
    [
        ("partial", "yfinance:prices", "not_scoreable"),
        ("complete", None, "not_scoreable"),
        ("complete", "model:baseline", "not_scoreable"),
        ("complete", "unmapped:source", "not_scoreable"),
    ],
)
def test_resolver_requires_complete_allow_listed_non_model_evidence(
    analysis_status: str, source_id: str | None, expected: str
) -> None:
    module = importlib.import_module("etf_cockpit.signals.research_states")

    decision = module.AuthorityDecision(
        analysis_status=analysis_status,
        research_state=module.ResearchState.RESEARCH_CANDIDATE,
        research_promotion_allowed=True,
    )
    component = module.ScoreComponent(key="momentum", status="ok", score=0.8, source_id=source_id)

    assert module.resolve_research_state([component], decision).value == expected


def test_resolver_accepts_complete_allow_listed_evidence_only_when_gate_allows() -> None:
    module = importlib.import_module("etf_cockpit.signals.research_states")
    component = module.ScoreComponent(key="momentum", status="ok", score=0.8, source_id="yfinance:prices")

    allowed = module.AuthorityDecision(
        analysis_status="complete",
        research_state=module.ResearchState.RESEARCH_CANDIDATE,
        research_promotion_allowed=True,
    )
    denied = allowed.model_copy(update={"research_promotion_allowed": False})

    assert module.resolve_research_state([component], allowed) is module.ResearchState.RESEARCH_CANDIDATE
    assert module.resolve_research_state([component], denied) is module.ResearchState.NOT_SCOREABLE


def test_model_confirmation_role_is_not_research_evidence() -> None:
    module = importlib.import_module("etf_cockpit.signals.research_states")
    from types import SimpleNamespace

    component = SimpleNamespace(
        key="timesfm",
        status="ok",
        score=0.8,
        source_id="yfinance:prices",
        score_role="model_confirmation",
    )
    decision = module.AuthorityDecision(
        analysis_status="complete",
        research_state=module.ResearchState.RESEARCH_CANDIDATE,
        research_promotion_allowed=True,
    )

    assert module.resolve_research_state([component], decision) is module.ResearchState.NOT_SCOREABLE


def test_v2_migration_does_not_trust_forged_positive_flags() -> None:
    module = _migration_module()
    forged = {
        "schema_version": "2.0",
        "research_state": "research_candidate",
        "portfolio_review_state": "reduce_exposure_review",
        "research_promotion_allowed": True,
        "portfolio_review_allowed": True,
        "execution_allowed": True,
    }

    migrated = module.migrate_legacy_action(forged)

    assert migrated.research_state.value == "research_candidate"
    assert migrated.research_promotion_allowed is False
    assert migrated.portfolio_review_allowed is False
    assert migrated.execution_allowed is False


def test_unsupported_schema_versions_are_rejected_without_mutating_source() -> None:
    module = _migration_module()
    source = {"schema_version": "9.9", "action": "buy"}
    original = dict(source)

    with pytest.raises(ValueError, match="unsupported schema_version"):
        module.migrate_legacy_action(source)

    assert source == original


def test_migration_semantics_is_constrained() -> None:
    module = _migration_module()
    with pytest.raises(Exception):
        module.ResearchStateMigration(research_state="manual_review", migration_semantics="invented")


def test_direct_v2_models_cannot_grant_positive_authority() -> None:
    migration_module = _migration_module()
    migration = migration_module.ResearchStateMigration(
        research_state="research_candidate",
        research_promotion_allowed=True,
        portfolio_review_allowed=True,
    )
    assert migration.research_promotion_allowed is False
    assert migration.portfolio_review_allowed is False
    assert migration.model_dump(mode="json")["research_promotion_allowed"] is False
    assert migration.model_dump(mode="json")["portfolio_review_allowed"] is False

    from etf_cockpit.chatgpt_bridge.schemas import PortfolioReviewAudit

    audit = PortfolioReviewAudit(
        etf_id="VWCE",
        research_state="research_candidate",
        research_promotion_allowed=True,
        portfolio_review_allowed=True,
    )
    assert audit.research_promotion_allowed is False
    assert audit.portfolio_review_allowed is False
    assert audit.model_dump()["research_promotion_allowed"] is False
    assert audit.model_dump()["portfolio_review_allowed"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", "9.9"), ("migration_version", "bogus")],
)
def test_direct_migration_models_reject_non_v2_version_metadata(field: str, value: str) -> None:
    migration_module = _migration_module()

    with pytest.raises(ValidationError, match=field):
        migration_module.ResearchStateMigration(
            research_state="manual_review",
            **{field: value},
        )


def test_chatgpt_bridge_service_preserves_v1_v2_return_type() -> None:
    from typing import get_type_hints

    from etf_cockpit.chatgpt_bridge.schemas import ChatGPTAudit, ChatGPTAuditV2
    from etf_cockpit.services import ChatGPTBridge

    assert get_type_hints(ChatGPTBridge.import_audit_json)["return"] == ChatGPTAudit | ChatGPTAuditV2


def test_dataclass_serialisers_normalise_status_and_force_authority_false() -> None:
    from datetime import date

    from etf_cockpit.core.types import ComponentScores, SignalResult
    from etf_cockpit.signals.simple_scores import SimpleInstrumentScore

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
        analysis_status="invalid",  # type: ignore[arg-type]
        research_promotion_allowed=True,
        portfolio_review_allowed=True,
    )
    signal_payload = signal.to_v2_dict()
    assert signal_payload["analysis_status"] in {"complete", "partial", "unavailable"}
    assert signal_payload["research_promotion_allowed"] is False
    assert signal_payload["portfolio_review_allowed"] is False

    score = SimpleInstrumentScore(
        instrument_key="VWCE",
        display_id="VWCE",
        source_group="ETF",
        asset_type="etf",
        name="World",
        yahoo_symbol="VWCE.DE",
        latest_date="2026-07-10",
        latest_price=100.0,
        final_score_10=7.0,
        decision="review",
        one_line_reason="review",
        components=[],
        warnings=[],
        analysis_status="invalid",  # type: ignore[arg-type]
        research_promotion_allowed=True,
        portfolio_review_allowed=True,
    )
    score_payload = score.to_v2_dict()
    assert score_payload["analysis_status"] in {"complete", "partial", "unavailable"}
    assert score_payload["research_promotion_allowed"] is False
    assert score_payload["portfolio_review_allowed"] is False


def test_v2_chatgpt_models_reject_legacy_action_fields_but_v1_accepts() -> None:
    from etf_cockpit.chatgpt_bridge.schemas import ChatGPTAuditV2

    payload = {
        "schema_version": "2.0",
        "review_date": "2026-07-10",
        "overall_view": "neutral",
        "portfolio_actions": [
            {
                "etf_id": "VWCE",
                "research_state": "watchlist",
                "action": "hold",
            }
        ],
        "model_audit": {
            "toto_usefulness": "unavailable",
            "timesfm_usefulness": "unavailable",
            "baseline_comparison": "baseline",
            "overfitting_concerns": [],
        },
    }

    with pytest.raises(Exception):
        ChatGPTAuditV2.model_validate(payload)
