from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from etf_cockpit.data.market_adjustments import (
    CorporateAction,
    CorporateActionStore,
    FXObservation,
    FXObservationStore,
    apply_total_return_adjustments,
    derive_fx_cross,
    reconcile_adjustments,
    reconcile_provider_observations,
    selected_currency_return,
)


ASSET = "US-ETF-001"
KNOWN_ANNOUNCEMENT = "2024-01-02T00:00:00Z"
KNOWN_CORRECTION = "2024-03-02T00:00:00Z"


def _action(
    action_id: str,
    action_type: str,
    *,
    revision: int = 1,
    known_at: str = KNOWN_ANNOUNCEMENT,
    source: str = "fixture:official-actions",
    source_id: str | None = None,
    ratio: float | None = None,
    amount: float | None = None,
    currency: str = "USD",
) -> CorporateAction:
    """Build a fully lined corporate action with deterministic UTC timestamps."""

    return CorporateAction(
        action_id=action_id,
        instrument_id=ASSET,
        action_type=action_type,
        announced_at="2023-12-15T00:00:00Z",
        effective_at="2024-01-10T00:00:00Z",
        ex_date="2024-01-11",
        payable_at="2024-01-31",
        known_at=known_at,
        revision=revision,
        source=source,
        source_id=source_id or f"{source}:{action_id}:r{revision}",
        source_checksum=f"sha256:{action_id}:{revision}",
        ratio=ratio,
        amount=amount,
        currency=currency,
    )


def _fx(
    observation_id: str,
    base: str,
    quote: str,
    rate: float,
    *,
    valid_at: str = "2024-01-10T00:00:00Z",
    known_at: str = KNOWN_ANNOUNCEMENT,
    revision: int = 1,
    source: str = "fixture:ecb-reference",
    is_reference: bool = True,
    executable: bool = False,
) -> FXObservation:
    return FXObservation(
        observation_id=observation_id,
        base_currency=base,
        quote_currency=quote,
        rate=Decimal(str(rate)),
        valid_at=valid_at,
        published_at=valid_at,
        retrieved_at="2024-01-11T00:00:00Z",
        known_at=known_at,
        revision=revision,
        source=source,
        source_id=f"{source}:{observation_id}:r{revision}",
        source_checksum=f"sha256:{observation_id}:{revision}",
        is_reference=is_reference,
        executable=executable,
    )


def test_corporate_actions_are_append_only_and_as_known_replay_preserves_corrections(tmp_path: Path) -> None:
    original = _action("DIV-001", "dividend", amount=2.0)
    correction = replace(original, amount=2.25, known_at=KNOWN_CORRECTION, revision=2)

    with CorporateActionStore(tmp_path) as store:
        store.append(original)
        store.append(correction)

        before_correction = store.as_of(ASSET, known_at=KNOWN_ANNOUNCEMENT)
        after_correction = store.as_of(ASSET, known_at=KNOWN_CORRECTION)
        replay = store.replay(ASSET, effective_at="2024-01-31T00:00:00Z", known_at=KNOWN_ANNOUNCEMENT)
        all_versions = store.query(ASSET)

    assert [item.revision for item in before_correction] == [1]
    assert [item.amount for item in before_correction] == [2.0]
    assert [item.revision for item in after_correction] == [2]
    assert [item.amount for item in after_correction] == [2.25]
    assert [item.revision for item in all_versions] == [1, 2]
    assert replay[0].source_id.endswith(":r1")
    assert replay[0].known_at == KNOWN_ANNOUNCEMENT
    assert all(item.execution_allowed is False for item in all_versions)


def test_conflicting_duplicate_revision_cannot_overwrite_as_known_history(tmp_path: Path) -> None:
    original = _action("SPLIT-001", "split", ratio=2.0)
    conflicting = replace(original, ratio=3.0)

    with CorporateActionStore(tmp_path) as store:
        store.append(original)
        with pytest.raises(ValueError):
            store.append(conflicting)
        retained = store.query(ASSET)

    assert len(retained) == 1
    assert retained[0].ratio == 2.0


def test_future_known_at_revision_is_excluded_from_historical_projection(tmp_path: Path) -> None:
    future = _action("FUTURE-001", "dividend", known_at="2025-01-01T00:00:00Z", amount=3.0)

    with CorporateActionStore(tmp_path) as store:
        store.append(future)
        historical = store.as_of(ASSET, known_at="2024-12-31T23:59:59Z")
        current = store.as_of(ASSET, known_at="2025-01-01T00:00:00Z")

    assert historical == ()
    assert len(current) == 1
    assert current[0].amount == 3.0


@pytest.mark.parametrize(
    ("action_type", "amount", "ratio"),
    (
        ("split", None, 2.0),
        ("dividend", 1.5, None),
        ("coupon", 4.0, None),
        ("redemption", 100.0, None),
        ("call", 101.0, None),
        ("default", None, None),
        ("recovery", 30.0, None),
    ),
)
def test_supported_action_types_retain_terms_and_safe_non_execution(action_type: str, amount: float | None, ratio: float | None, tmp_path: Path) -> None:
    action = _action(f"{action_type}-001", action_type, amount=amount, ratio=ratio)

    with CorporateActionStore(tmp_path) as store:
        store.append(action)
        materialised = store.query(ASSET)

    assert len(materialised) == 1
    assert materialised[0].action_type == action_type
    assert materialised[0].announced_at < materialised[0].effective_at
    assert materialised[0].effective_at[:10] <= materialised[0].ex_date
    assert materialised[0].ex_date <= materialised[0].payable_at
    assert materialised[0].source_id == action.source_id
    assert materialised[0].source_checksum == action.source_checksum
    assert materialised[0].execution_allowed is False


@pytest.mark.parametrize("action_type", ("dividend", "distribution", "coupon", "interest", "recovery"))
def test_income_events_are_investment_income_not_external_flows(action_type: str) -> None:
    action = _action(f"INCOME-{action_type}", action_type, amount=2.0)

    classification = action.cash_flow_classification

    assert classification == "investment_income"
    assert action.external_flow is False


def test_total_return_convention_and_income_price_components_reconcile() -> None:
    dividend = _action("DIV-TR-001", "dividend", amount=2.0)
    result = apply_total_return_adjustments(
        prices=(100.0, 108.0),
        actions=(dividend,),
        convention="price_plus_reinvested_income",
    )

    assert result.available is True
    assert result.execution_allowed is False
    assert result.convention == "price_plus_reinvested_income"
    assert result.price_return == pytest.approx(0.08)
    assert result.income_return == pytest.approx(0.02)
    assert result.total_return == pytest.approx((1.08 * 1.02) - 1.0)


def test_adjustment_round_trip_restores_raw_series_and_reconciles_to_actions() -> None:
    split = _action("SPLIT-RT-001", "split", ratio=2.0)
    raw_prices = (100.0, 110.0)
    adjusted = apply_total_return_adjustments(prices=raw_prices, actions=(split,), convention="split_adjusted")
    reconciliation = reconcile_adjustments(raw_prices, adjusted.adjusted_prices, (split,), tolerance=1e-12)

    assert reconciliation.available is True
    assert reconciliation.reconciled is True
    assert reconciliation.action_ids == ("SPLIT-RT-001",)
    assert adjusted.round_trip(raw_prices) == pytest.approx(raw_prices)


def test_adjustment_discrepancy_is_explicit_and_quarantined_above_tolerance() -> None:
    split = _action("SPLIT-BAD-001", "split", ratio=2.0)
    report = reconcile_adjustments(
        raw_prices=(100.0, 110.0),
        adjusted_prices=(100.0, 55.1),
        actions=(split,),
        tolerance=1e-4,
    )

    assert report.available is False
    assert report.status == "quarantined"
    assert report.reconciled is False
    assert report.discrepancies
    assert report.execution_allowed is False


def test_provider_discrepancy_is_visible_without_silent_winner() -> None:
    primary = _action("PROVIDER-001", "dividend", amount=1.00, source="provider:primary")
    secondary = replace(primary, amount=1.25, source="provider:secondary", source_id="provider:secondary:PROVIDER-001:r1")

    report = reconcile_provider_observations((primary,), (secondary,), tolerance=0.01)

    assert report.status == "quarantined"
    assert report.available is False
    assert report.discrepancies
    assert {item.source for item in report.observations} == {"provider:primary", "provider:secondary"}
    assert report.execution_allowed is False


def test_identical_provider_observations_reconcile_and_retain_lineage() -> None:
    primary = _action("PROVIDER-OK-001", "coupon", amount=4.0, source="provider:primary")
    secondary = replace(primary, source="provider:secondary", source_id="provider:secondary:PROVIDER-OK-001:r1")

    report = reconcile_provider_observations((primary,), (secondary,), tolerance=0.01)

    assert report.available is True
    assert report.status == "reconciled"
    assert report.discrepancies == ()
    assert {item.source for item in report.observations} == {"provider:primary", "provider:secondary"}


def test_fx_observations_are_append_only_and_point_in_time(tmp_path: Path) -> None:
    original = _fx("EURUSD-001", "EUR", "USD", 1.10)
    correction = replace(original, rate=Decimal("1.11"), known_at=KNOWN_CORRECTION, revision=2)

    with FXObservationStore(tmp_path) as store:
        store.append(original)
        store.append(correction)
        before = store.as_of("EUR", "USD", valid_at="2024-01-10T00:00:00Z", known_at=KNOWN_ANNOUNCEMENT)
        after = store.as_of("EUR", "USD", valid_at="2024-01-10T00:00:00Z", known_at=KNOWN_CORRECTION)
        versions = store.query("EUR", "USD")

    assert [item.revision for item in before] == [1]
    assert before[0].rate == Decimal("1.10")
    assert [item.revision for item in after] == [2]
    assert after[0].rate == Decimal("1.11")
    assert [item.revision for item in versions] == [1, 2]
    assert all(item.execution_allowed is False for item in versions)


def test_fx_cross_supports_inverse_and_declared_triangular_path(tmp_path: Path) -> None:
    with FXObservationStore(tmp_path) as store:
        store.append(_fx("EURUSD-001", "EUR", "USD", 1.10))
        store.append(_fx("USDJPY-001", "USD", "JPY", 150.0))

        inverse = derive_fx_cross(store, "USD", "EUR", as_of="2024-01-11T00:00:00Z")
        cross = derive_fx_cross(store, "EUR", "JPY", as_of="2024-01-11T00:00:00Z")

    assert inverse.available is True
    assert inverse.rate == pytest.approx(1.0 / 1.10)
    assert inverse.path == ("USD/EUR",)
    assert cross.available is True
    assert cross.rate == pytest.approx(1.10 * 150.0)
    assert cross.path == ("EUR/USD", "USD/JPY")
    assert cross.execution_allowed is False


def test_fx_cross_rejects_triangular_inconsistency_above_tolerance(tmp_path: Path) -> None:
    with FXObservationStore(tmp_path) as store:
        store.append(_fx("EURUSD-001", "EUR", "USD", 1.10))
        store.append(_fx("USDJPY-001", "USD", "JPY", 150.0))
        store.append(_fx("EURJPY-001", "EUR", "JPY", 200.0, source="fixture:conflicting-reference"))

        report = derive_fx_cross(store, "EUR", "JPY", as_of="2024-01-11T00:00:00Z", tolerance=1e-6)

    assert report.available is False
    assert report.status == "quarantined"
    assert report.discrepancies
    assert report.execution_allowed is False


@pytest.mark.parametrize(
    ("reason", "store_kwargs"),
    (
        ("missing", {}),
        ("stale", {"valid_at": "2020-01-01T00:00:00Z"}),
        ("conflicted", {"source": "fixture:conflict"}),
    ),
)
def test_missing_stale_or_conflicted_fx_fails_closed(reason: str, store_kwargs: dict[str, str], tmp_path: Path) -> None:
    with FXObservationStore(tmp_path) as store:
        if reason != "missing":
            store.append(_fx("EURUSD-001", "EUR", "USD", 1.10, **store_kwargs))
            if reason == "conflicted":
                store.append(_fx("EURUSD-001-alt", "EUR", "USD", 1.12, source="fixture:conflict-alt"))
        result = selected_currency_return(
            local_return=0.10,
            base_currency="USD",
            output_currency="EUR",
            fx_store=store,
            valuation_at="2024-01-11T00:00:00Z",
            max_age_days=3,
        )

    assert result.available is False
    assert result.status == "unavailable"
    assert result.reason_code == f"FX_{reason.upper()}"
    assert result.output_return is None
    assert result.execution_allowed is False


def test_selected_currency_return_uses_exact_multiplicative_formula(tmp_path: Path) -> None:
    with FXObservationStore(tmp_path) as store:
        store.append(_fx("EURUSD-001", "EUR", "USD", 1.10))
        store.append(_fx("EURUSD-002", "EUR", "USD", 1.21, valid_at="2024-01-11T00:00:00Z"))
        result = selected_currency_return(
            local_return=0.10,
            base_currency="USD",
            output_currency="EUR",
            fx_store=store,
            valuation_at="2024-01-11T00:00:00Z",
        )

    assert result.available is True
    assert result.local_return == pytest.approx(0.10)
    assert result.fx_return == pytest.approx((1.10 / 1.21) - 1.0)
    assert result.output_return == pytest.approx((1.10 * (1.10 / 1.21)) - 1.0)
    assert result.execution_allowed is False


def test_positive_local_return_can_be_reversed_by_falling_currency(tmp_path: Path) -> None:
    with FXObservationStore(tmp_path) as store:
        store.append(_fx("EURUSD-001", "EUR", "USD", 1.20))
        store.append(_fx("EURUSD-002", "EUR", "USD", 0.84, valid_at="2024-01-11T00:00:00Z"))
        result = selected_currency_return(
            local_return=0.25,
            base_currency="USD",
            output_currency="EUR",
            fx_store=store,
            valuation_at="2024-01-11T00:00:00Z",
        )

    assert result.available is True
    assert result.output_return == pytest.approx((1.25 * (0.84 / 1.20)) - 1.0)
    assert result.output_return < 0.0


def test_reference_fx_rate_is_never_reported_as_executable(tmp_path: Path) -> None:
    with FXObservationStore(tmp_path) as store:
        store.append(_fx("EURUSD-001", "EUR", "USD", 1.10, is_reference=True, executable=False))
        store.append(_fx("EURUSD-002", "EUR", "USD", 1.11, valid_at="2024-01-11T00:00:00Z", is_reference=True, executable=False))
        result = selected_currency_return(
            local_return=0.05,
            base_currency="USD",
            output_currency="EUR",
            fx_store=store,
            valuation_at="2024-01-11T00:00:00Z",
        )

    assert result.available is True
    assert result.rate_is_reference is True
    assert result.executable is False
    assert result.execution_allowed is False


def test_concurrent_appenders_do_not_drop_corporate_actions(tmp_path: Path) -> None:
    actions = tuple(_action(f"CONCURRENT-{index:03d}", "dividend", amount=1.0) for index in range(12))

    def append(action: CorporateAction) -> None:
        with CorporateActionStore(tmp_path) as store:
            store.append(action)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, actions))

    with CorporateActionStore(tmp_path) as store:
        retained = [item for action in actions for item in store.query(action.instrument_id) if item.action_id == action.action_id]

    assert len(retained) == len(actions)
    assert {item.action_id for item in retained} == {item.action_id for item in actions}


def test_malformed_action_and_fx_observation_are_rejected_without_zero_fill(tmp_path: Path) -> None:
    invalid_action = _action("BAD-001", "split", ratio=0.0)
    invalid_fx = _fx("BAD-FX-001", "EUR", "USD", 0.0)

    with CorporateActionStore(tmp_path) as action_store:
        with pytest.raises(ValueError):
            action_store.append(invalid_action)
    with FXObservationStore(tmp_path / "fx") as fx_store:
        with pytest.raises(ValueError):
            fx_store.append(invalid_fx)
