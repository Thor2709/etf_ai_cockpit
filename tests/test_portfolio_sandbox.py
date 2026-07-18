from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application.portfolio_sandbox import (
    PORTFOLIO_SANDBOX_ENTITY,
    analyse_portfolio_candidate,
    build_portfolio_candidate,
    load_portfolio_candidate,
    save_portfolio_candidate,
)
from etf_cockpit.application import portfolio_sandbox as sandbox_store
from etf_cockpit.core.config import load_config
from etf_cockpit.data.local_storage import StorageRevisionConflict, TransactionalStore
from etf_cockpit.portfolio.sandbox import holdings_checksum


def _snapshot(*, revision: str = "universe-1", vwce_weight: float = 0.4):
    return SimpleNamespace(
        config=load_config(),
        holdings=pd.DataFrame(
            [
                {"etf_id": "VWCE", "current_weight": vwce_weight, "market_value_eur": 40_000.0},
                {"etf_id": "LYP6", "current_weight": 0.2, "market_value_eur": 20_000.0},
            ]
        ),
        universe_revision=revision,
        data_report=SimpleNamespace(as_of_date="2026-07-18"),
    )


def _candidate(snapshot=None):
    snapshot = snapshot or _snapshot()
    return build_portfolio_candidate(
        snapshot,
        name=" Core allocation ",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
    )


def test_candidate_analysis_is_deterministic_and_non_executable() -> None:
    snapshot = _snapshot()
    candidate = _candidate(snapshot)

    first = analyse_portfolio_candidate(snapshot, candidate)
    second = analyse_portfolio_candidate(snapshot, candidate)

    assert first == second
    assert candidate.name == "Core allocation"
    assert candidate.execution_allowed is False
    assert first.execution_allowed is False
    assert first.source_stale is False
    assert first.overlap_status == "unavailable_pending_issue_0022"
    rows = {row.instrument_id: row for row in first.allocations}
    assert rows["VWCE"].drift == pytest.approx(0.2)
    assert rows["VWCE"].signed_notional_eur == pytest.approx(20_000)
    assert rows["LYP6"].drift == pytest.approx(0.1)
    assert first.cost.total_order_value_eur == pytest.approx(30_000)
    assert any(row.bucket == "Europe" and row.target_weight == pytest.approx(0.3) for row in first.region_exposure)
    assert any("ISSUE-0022" in warning for warning in first.warnings)


@pytest.mark.parametrize(
    ("target", "cash", "expected"),
    [
        (0.45, 0.55, "inside"),
        (0.50, 0.50, "above_soft_band"),
        (0.500_001, 0.499_999, "above_hard_band"),
    ],
)
def test_drift_band_boundaries_remain_strict(target, cash, expected) -> None:
    snapshot = _snapshot()
    candidate = build_portfolio_candidate(
        snapshot,
        name="Band boundary",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": target},
        cash_weight=cash,
    )
    row = next(item for item in analyse_portfolio_candidate(snapshot, candidate).allocations if item.instrument_id == "VWCE")
    assert row.drift_status == expected


def test_holdings_binding_is_independent_of_row_order() -> None:
    holdings = _snapshot().holdings
    assert holdings_checksum(holdings) == holdings_checksum(holdings.iloc[::-1].reset_index(drop=True))
    split = pd.DataFrame(
        [
            {"etf_id": "VWCE", "current_weight": 0.1, "market_value_eur": 10_000.0},
            {"etf_id": "VWCE", "current_weight": 0.3, "market_value_eur": 30_000.0},
            {"etf_id": "LYP6", "current_weight": 0.2, "market_value_eur": 20_000.0},
        ]
    )
    assert holdings_checksum(holdings) == holdings_checksum(split)


def test_exposure_totals_and_concentration_warnings_reconcile() -> None:
    analysis = analyse_portfolio_candidate(_snapshot(), _candidate())
    eur = next(row for row in analysis.currency_exposure if row.bucket == "EUR")
    broad = next(row for row in analysis.sector_exposure if row.bucket == "Broad")
    assert eur.current_weight == pytest.approx(0.6)
    assert eur.target_weight == pytest.approx(0.9)
    assert broad.current_weight == pytest.approx(0.6)
    assert broad.target_weight == pytest.approx(0.9)
    assert any("Target sector cap exceeded: Broad" in warning for warning in analysis.warnings)


@pytest.mark.parametrize(
    ("targets", "cash", "notional", "message"),
    [
        ({"VWCE": float("nan")}, 1.0, 100_000, "finite number"),
        ({"VWCE": float("inf")}, 1.0, 100_000, "finite number"),
        ({"VWCE": True}, 0.0, 100_000, "finite number"),
        ({"VWCE": -0.1}, 1.1, 100_000, "between 0% and 100%"),
        ({"UNKNOWN": 0.5}, 0.5, 100_000, "unknown or disabled"),
        ({"VWCE": 0.5}, 0.4, 100_000, "must equal 100%"),
        ({"VWCE": 0.5}, float("nan"), 100_000, "finite number"),
        ({"VWCE": 0.5}, 0.5, float("inf"), "finite number"),
        ({"VWCE": 0.5}, 0.5, 0, "greater than zero"),
        ({"VWCE": 0.5}, 0.5, 1_000_000_000_001, "no more than EUR 1 trillion"),
    ],
)
def test_candidate_validation_fails_closed(targets, cash, notional, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_portfolio_candidate(
            _snapshot(),
            name="Candidate",
            analysis_notional_eur=notional,
            target_weights=targets,
            cash_weight=cash,
        )


def test_candidate_persistence_round_trip_revision_conflict_and_stale_re_evaluation(tmp_path) -> None:
    snapshot = _snapshot()
    saved = save_portfolio_candidate(
        snapshot,
        name="Core allocation",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    assert saved.revision == 1
    loaded = load_portfolio_candidate(snapshot, " core allocation ", root=tmp_path)
    assert loaded.candidate == saved.candidate
    assert loaded.source_stale is False
    assert loaded.candidate.execution_allowed is False

    updated = save_portfolio_candidate(
        snapshot,
        name="Core allocation",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.5, "LYP6": 0.4},
        cash_weight=0.1,
        expected_revision=loaded.revision,
        root=tmp_path,
    )
    assert updated.revision == 2
    with pytest.raises(StorageRevisionConflict):
        save_portfolio_candidate(
            snapshot,
            name="Core allocation",
            analysis_notional_eur=100_000,
            target_weights={"VWCE": 0.4, "LYP6": 0.5},
            cash_weight=0.1,
            expected_revision=1,
            root=tmp_path,
        )

    changed = _snapshot(revision="universe-2", vwce_weight=0.5)
    stale = load_portfolio_candidate(changed, "Core allocation", root=tmp_path)
    assert stale.source_stale is True
    analysis = analyse_portfolio_candidate(changed, stale.candidate)
    assert analysis.source_stale is True
    assert any("re-evaluated" in warning for warning in analysis.warnings)


def test_candidate_name_and_missing_record_fail_closed(tmp_path) -> None:
    with pytest.raises(ValueError, match="1 to 80"):
        build_portfolio_candidate(
            _snapshot(),
            name="   ",
            analysis_notional_eur=100_000,
            target_weights={"VWCE": 0.5},
            cash_weight=0.5,
        )
    with pytest.raises(ValueError, match="1 to 80"):
        build_portfolio_candidate(
            _snapshot(),
            name="x" * 81,
            analysis_notional_eur=100_000,
            target_weights={"VWCE": 0.5},
            cash_weight=0.5,
        )
    with pytest.raises(ValueError, match="no saved portfolio"):
        load_portfolio_candidate(_snapshot(), "Missing", root=tmp_path)


def test_malformed_or_execution_enabled_saved_candidate_fails_closed(tmp_path) -> None:
    snapshot = _snapshot()
    saved = save_portfolio_candidate(
        snapshot,
        name="Core allocation",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    with TransactionalStore(tmp_path) as store:
        record = store.get(PORTFOLIO_SANDBOX_ENTITY, saved.candidate.candidate_id)
        payload = dict(record.payload)
        payload["execution_allowed"] = True
        store.put(PORTFOLIO_SANDBOX_ENTITY, saved.candidate.candidate_id, payload, expected_revision=1)

    with pytest.raises(ValueError, match="checksum does not match|no-execution contract"):
        load_portfolio_candidate(snapshot, "Core allocation", root=tmp_path)


def test_rechecks_schema_identity_and_no_execution_even_with_recomputed_checksum(tmp_path) -> None:
    snapshot = _snapshot()
    saved = save_portfolio_candidate(
        snapshot,
        name="Core allocation",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    with TransactionalStore(tmp_path) as store:
        record = store.get(PORTFOLIO_SANDBOX_ENTITY, saved.candidate.candidate_id)
        payload = dict(record.payload)
        payload["execution_allowed"] = True
        body = {key: value for key, value in payload.items() if key != "payload_checksum"}
        payload["payload_checksum"] = sandbox_store._payload_checksum(body)
        store.put(PORTFOLIO_SANDBOX_ENTITY, saved.candidate.candidate_id, payload, expected_revision=1)
    with pytest.raises(ValueError, match="no-execution contract"):
        load_portfolio_candidate(snapshot, "Core allocation", root=tmp_path)


def test_saved_candidate_persists_intent_not_derived_analysis(tmp_path) -> None:
    saved = save_portfolio_candidate(
        _snapshot(),
        name="Core allocation",
        analysis_notional_eur=100_000,
        target_weights={"VWCE": 0.6, "LYP6": 0.3},
        cash_weight=0.1,
        expected_revision=0,
        root=tmp_path,
    )
    with TransactionalStore(tmp_path) as store:
        record = store.get(PORTFOLIO_SANDBOX_ENTITY, saved.candidate.candidate_id)
    assert record is not None
    assert not ({"drift", "cost", "exposures", "allocations"} & set(record.payload))
    assert record.payload["execution_allowed"] is False
