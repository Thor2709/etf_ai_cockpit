from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from etf_cockpit.analysis.decision.contracts import DecisionDriver, DomainSlot
from etf_cockpit.analysis.decision.opportunity import (
    _benchmark_scores,
    build_opportunity_results,
)
from etf_cockpit.analysis.decision.shadow_run import (
    _compose_universe,
    run_decision_shadow,
)
from etf_cockpit.application.ui_facade import load_opportunity_assessment
from etf_cockpit.app.pages.instrument_detail import _render_opportunity_card


DECISION_TIME = "2026-09-30T23:59:59Z"


def _candidate(
    instrument: str,
    underwriting_z: float,
    valuation_z: float,
    momentum: float,
    *,
    risk: float = 5.0,
    v3: float = 0.0,
    growth: float | None = None,
    peer_id: str = "sector:technology",
    domain_status: str = "AVAILABLE",
    gate_results: tuple[object, ...] = (),
) -> dict[str, object]:
    underwriting = DomainSlot(
        "Underwriting",
        domain_status,
        underwriting_z if domain_status == "AVAILABLE" else None,
        underwriting_z if domain_status == "AVAILABLE" else None,
        1.0 if domain_status == "AVAILABLE" else 0.0,
        0.8 if domain_status == "AVAILABLE" else 0.0,
        "AVAILABLE" if domain_status == "AVAILABLE" else "INSUFFICIENT_SUPPORT",
    )
    valuation = DomainSlot(
        "Valuation", "AVAILABLE", valuation_z, valuation_z, 1.0, 0.8, "AVAILABLE"
    )
    assessment = SimpleNamespace(
        eligibility_results=(),
        gate_results=gate_results,
        drivers=(
            DecisionDriver("quality_metric", "AVAILABLE", 1.0, "ratio", underwriting_z, "AVAILABLE"),
            DecisionDriver("valuation_metric", "AVAILABLE", 1.0, "ratio", valuation_z, "AVAILABLE"),
        ),
        source_vintage_hash=f"source:{instrument}",
    )
    components = [
        SimpleNamespace(key="momentum", raw_metric=momentum, score_eligible=True),
        SimpleNamespace(key="risk", raw_metric=risk, score_eligible=True),
    ]
    if growth is not None:
        components.append(
            SimpleNamespace(key="growth", raw_metric=growth, score_eligible=True)
        )
    return {
        "instrument": instrument,
        "asset_type": "stock",
        "assessment": assessment,
        "underwriting_domains": (underwriting,),
        "valuation_domain": valuation,
        "underwriting_z_score": underwriting_z if domain_status == "AVAILABLE" else None,
        "valuation_z_score": valuation_z,
        "critical_domains": ("Underwriting",),
        "peer_id": peer_id,
        "signal": SimpleNamespace(
            canonical_score=SimpleNamespace(
                legacy_composite_raw=v3, components=tuple(components)
            )
        ),
        "confidence": 0.8,
        "coverage": 1.0,
    }


def _three_candidates() -> list[dict[str, object]]:
    return [
        _candidate("ACME", 2.0, 0.0, 9.0, v3=0.5, growth=0.4),
        _candidate("BETA", 0.0, 0.0, 5.0, v3=0.1, growth=0.2),
        _candidate("CYAN", -2.0, 0.0, 1.0, v3=-0.4, growth=-0.2),
    ]


def test_qv_baseline_and_universe_percentile() -> None:
    results = build_opportunity_results(
        _three_candidates(), decision_time=DECISION_TIME
    )

    assert results["ACME"].baseline_z == 1.0
    assert results["ACME"].percentile == 100.0 * 2.5 / 3.0
    assert results["ACME"].universe_rank == 1
    assert results["ACME"].universe_support == 3
    assert results["ACME"].status == "Attractive"


def test_blocked_and_critical_insufficient_gates_are_never_neutral() -> None:
    blocked = _candidate(
        "BLOCKED",
        0.0,
        0.0,
        1.0,
        gate_results=(
            SimpleNamespace(status="BLOCKED", passed=False, reason_code="GATE_FAILED"),
        ),
    )
    insufficient = _candidate(
        "MISSING", 0.0, 0.0, 1.0, domain_status="UNAVAILABLE"
    )
    results = build_opportunity_results(
        [blocked, insufficient, *_three_candidates()],
        decision_time=DECISION_TIME,
    )

    assert results["BLOCKED"].status == "Blocked"
    assert results["MISSING"].status == "Insufficient Evidence"
    assert results["BLOCKED"].percentile is None
    assert results["MISSING"].percentile is None


def test_universe_hash_and_sector_peer_identity_are_stored() -> None:
    results = build_opportunity_results(
        _three_candidates(), decision_time=DECISION_TIME
    )

    assert len(results["ACME"].universe_hash) == 64
    assert results["ACME"].universe_hash == results["BETA"].universe_hash
    assert results["ACME"].peer_id == "sector:technology"
    assert results["ACME"].peer_percentile == results["ACME"].percentile
    assert results["ACME"].peer_rank == 1


def test_tactical_evidence_changes_timing_without_changing_opportunity_rank() -> None:
    initial_candidates = _three_candidates()
    changed_candidates = [
        _candidate("ACME", 2.0, 0.0, 1.0, v3=0.5, growth=0.4),
        _candidate("BETA", 0.0, 0.0, 5.0, v3=0.1, growth=0.2),
        _candidate("CYAN", -2.0, 0.0, 9.0, v3=-0.4, growth=-0.2),
    ]
    initial = build_opportunity_results(
        initial_candidates, decision_time=DECISION_TIME
    )["ACME"]
    changed = build_opportunity_results(
        changed_candidates, decision_time=DECISION_TIME
    )["ACME"]

    assert (changed.baseline_z, changed.percentile) == (
        initial.baseline_z,
        initial.percentile,
    )
    assert initial.timing == "Supportive"
    assert changed.timing == "Adverse"


def test_benchmark_rankers_are_reproducible() -> None:
    candidates = _three_candidates()
    first = build_opportunity_results(
        candidates, decision_time=DECISION_TIME
    )
    second = build_opportunity_results(
        candidates, decision_time=DECISION_TIME
    )

    assert first["ACME"].benchmark_rankers == second["ACME"].benchmark_rankers
    rankers = {item.ranker: item for item in first["ACME"].benchmark_rankers}
    assert rankers["QV"].score == 1.0
    assert rankers["five_factor"].status == "AVAILABLE"


def test_replay_membership_is_unavailable_and_later_additions_do_not_change_hash() -> None:
    cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)
    earlier = SimpleNamespace(
        universe=SimpleNamespace(
            etfs=(SimpleNamespace(id="ETF_OLD", instrument_type="ETF"),),
            enabled_ids=("ETF_OLD",),
        )
    )
    later = SimpleNamespace(
        universe=SimpleNamespace(
            etfs=(
                SimpleNamespace(id="ETF_OLD", instrument_type="ETF"),
                SimpleNamespace(id="ETF_ADDED_LATER", instrument_type="ETF"),
            ),
            enabled_ids=("ETF_OLD", "ETF_ADDED_LATER"),
        )
    )

    first = _compose_universe(earlier, (), cutoff, latest_features=None)
    second = _compose_universe(later, (), cutoff, latest_features=None)
    first_result = build_opportunity_results(first, decision_time=cutoff.isoformat())
    second_result = build_opportunity_results(second, decision_time=cutoff.isoformat())

    assert first == second
    assert first[0]["failure_reason"] == "UNIVERSE_MEMBERSHIP_UNKNOWN_AT_CUTOFF"
    assert "ETF_ADDED_LATER" not in {item["instrument"] for item in first}
    assert first_result["universe"].universe_hash == second_result["universe"].universe_hash


def test_benchmark_rankers_use_scored_components_and_preserve_missing_scores() -> None:
    signal = SimpleNamespace(
        components=SimpleNamespace(momentum=0.3, risk=-0.4),
        canonical_score=SimpleNamespace(
            legacy_composite_raw=0.2,
            components=(
                SimpleNamespace(key="momentum", raw_metric=0.9, eligible=True),
                SimpleNamespace(key="risk", raw_metric=0.8, eligible=True),
                SimpleNamespace(key="growth", raw_metric=0.5, eligible=True),
            ),
        ),
    )
    state = {
        "asset_type": "stock",
        "candidate": {
            "asset_type": "stock",
            "underwriting_z_score": 2.0,
            "valuation_z_score": 1.0,
            "signal": signal,
        },
        "assessment": None,
    }

    scores = _benchmark_scores(state)
    assert scores["M"] == 0.3
    assert scores["R"] == -0.4
    assert scores["QVM"] == (2.0 + 1.0 + 0.3) / 3
    assert scores["five_factor"] == (1.0 + 0.5 + 2.0 + 0.3 - 0.4) / 5

    signal.components.momentum = None
    missing = _benchmark_scores(state)
    assert missing["M"] is None
    assert missing["QVM"] is None


def test_shadow_artifact_keeps_hashes_and_does_not_mutate_v3(tmp_path: Path) -> None:
    signal = SimpleNamespace(
        run_id="signals-da004-test",
        canonical_score=SimpleNamespace(legacy_composite_raw=0.25, components=()),
    )
    before = copy.deepcopy(signal.__dict__)
    config = SimpleNamespace(universe=SimpleNamespace(etfs=(), enabled_ids=()))
    path = run_decision_shadow(
        config,
        [signal],
        decision_time=DECISION_TIME,
        output_directory=tmp_path,
        candidates=_three_candidates(),
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["artifact_version"] == "decision-opportunity-shadow-v1"
    assert set(payload["config_hashes"]) == {
        "decision_opportunity_v1",
        "decision_domains_v1",
        "score_engine_v3",
    }
    assert all(len(value) == 64 for value in payload["config_hashes"].values())
    assert signal.__dict__ == before
    assert len(payload["results"]) == 3


def test_opportunity_card_renders_facade_assessment(tmp_path: Path) -> None:
    config = SimpleNamespace(universe=SimpleNamespace(etfs=(), enabled_ids=()))
    run_decision_shadow(
        config,
        (),
        decision_time=DECISION_TIME,
        output_directory=tmp_path,
        candidates=_three_candidates(),
    )
    opportunity = load_opportunity_assessment(
        "ACME",
        decision_time=DECISION_TIME,
        artifact_directory=tmp_path,
    )

    card = _render_opportunity_card(opportunity)

    assert opportunity["status"] == "Attractive"
    assert card.content.key == "instrument-detail.opportunity"
