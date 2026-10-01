from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3

import numpy as np
import pandas as pd
from hypothesis import given, settings, strategies as st
import pytest

from etf_cockpit.data.local_storage import _apply_migrations, _register_ledger_sql_functions
from etf_cockpit.models.distribution_store import QUANTILE_FIELDS, normalise_quantiles
from etf_cockpit.portfolio.exposure_cube import build_portfolio_exposure_cube
from etf_cockpit.portfolio.ledger import Ledger, LedgerPosting
from etf_cockpit.portfolio.ledger_projection import replay_ledger
from etf_cockpit.portfolio.robust_risk import covariance_estimators


_PROPERTY_SETTINGS = settings(max_examples=12, derandomize=True, deadline=None)
_UTC = timezone.utc


def _utc_text(value: datetime) -> str:
    return value.astimezone(_UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _memory_ledger_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _register_ledger_sql_functions(connection)
    connection.execute("PRAGMA foreign_keys = ON")
    _apply_migrations(connection)
    return connection


def _post_cash_actions(
    connection: sqlite3.Connection, actions: list[tuple[int, bool]]
) -> tuple[Decimal, datetime, datetime]:
    observed_at = datetime.now(_UTC).replace(microsecond=0)
    as_of = observed_at + timedelta(seconds=1)
    ledger = Ledger(connection)
    ledger.create_account("cash", name="Cash", account_type="asset", authority="paper", account_role="cash")
    ledger.create_account("equity", name="Equity", account_type="equity", authority="paper")
    expected_cash = Decimal("0")
    for index, (cents, deposit) in enumerate(actions):
        amount = Decimal(cents) / Decimal("100")
        cash_posting = LedgerPosting(
            "cash",
            "EUR",
            debit=amount if deposit else Decimal("0"),
            credit=Decimal("0") if deposit else amount,
        )
        equity_posting = LedgerPosting(
            "equity",
            "EUR",
            debit=Decimal("0") if deposit else amount,
            credit=amount if deposit else Decimal("0"),
        )
        entry = ledger.post(
            f"generated-entry-{index}",
            authority="paper",
            effective_at=_utc_text(observed_at),
            settlement_at=_utc_text(observed_at),
            postings=(cash_posting, equity_posting),
        )
        debits = sum((line.debit for line in entry.postings), Decimal("0"))
        credits = sum((line.credit for line in entry.postings), Decimal("0"))
        assert debits == credits
        expected_cash += amount if deposit else -amount
    return expected_cash, as_of, datetime.now(_UTC) + timedelta(minutes=1)


@_PROPERTY_SETTINGS
@given(actions=st.lists(st.tuples(st.integers(min_value=1, max_value=100_000), st.booleans()), min_size=1, max_size=12))
def test_ledger_balance_and_cash_conservation_over_transaction_sequences(
    actions: list[tuple[int, bool]],
) -> None:
    with closing(_memory_ledger_connection()) as connection:
        expected_cash, as_of, known_at = _post_cash_actions(connection, actions)
        ledger_balance = Ledger(connection).cash_balance(
            account_id="cash", currency="EUR", as_of=as_of, authority="paper"
        )
        replay = replay_ledger(
            connection,
            authority="paper",
            as_of=_utc_text(as_of),
            known_at=_utc_text(known_at),
        )

    assert ledger_balance == expected_cash
    assert replay.trial_balance_balanced is True
    assert replay.cash[0].book_balance == expected_cash


@_PROPERTY_SETTINGS
@given(actions=st.lists(st.tuples(st.integers(min_value=1, max_value=100_000), st.booleans()), min_size=1, max_size=12))
def test_replaying_the_same_ledger_events_is_idempotent(
    actions: list[tuple[int, bool]],
) -> None:
    with closing(_memory_ledger_connection()) as connection:
        _expected_cash, as_of, known_at = _post_cash_actions(connection, actions)
        changes_before_replay = connection.total_changes
        first = replay_ledger(
            connection,
            authority="paper",
            as_of=_utc_text(as_of),
            known_at=_utc_text(known_at),
        )
        second = replay_ledger(
            connection,
            authority="paper",
            as_of=_utc_text(as_of),
            known_at=_utc_text(known_at),
        )
        changes_after_replay = connection.total_changes

    assert second == first
    assert changes_after_replay == changes_before_replay


@_PROPERTY_SETTINGS
@given(raw_weights=st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=8))
def test_every_exposure_dimension_conserves_random_portfolio_weights(raw_weights: list[int]) -> None:
    denominator = sum(raw_weights)
    weights = {f"position-{index}": value / denominator for index, value in enumerate(raw_weights)}
    cube = build_portfolio_exposure_cube(
        pd.DataFrame(),
        weights,
        decision_time=datetime(2026, 9, 30, tzinfo=_UTC),
        reporting_currency="EUR",
    )

    assert cube.dimensions
    for dimension in cube.dimensions:
        assert sum(segment.percentage for segment in dimension.segments) == pytest.approx(100.0, abs=1e-7)
        assert sum(segment.amount for segment in dimension.segments) == pytest.approx(cube.total_weight, abs=1e-9)


@_PROPERTY_SETTINGS
@given(
    ordered=st.lists(st.integers(min_value=-100_000, max_value=100_000), min_size=len(QUANTILE_FIELDS), max_size=len(QUANTILE_FIELDS)).map(sorted),
    scale=st.integers(min_value=1, max_value=20),
    shift=st.integers(min_value=-1000, max_value=1000),
)
def test_quantile_order_survives_monotone_affine_transform(ordered: list[int], scale: int, shift: int) -> None:
    values = dict(zip(QUANTILE_FIELDS, ordered, strict=True))
    normalised = normalise_quantiles(values)
    assert normalised is not None
    assert list(normalised.values()) == sorted(normalised.values())

    transformed = {field: value * scale + shift for field, value in values.items()}
    transformed_result = normalise_quantiles(transformed)
    assert transformed_result is not None
    assert list(transformed_result.values()) == sorted(transformed_result.values())


@_PROPERTY_SETTINGS
@given(
    rows=st.lists(
        st.tuples(
            st.floats(min_value=-0.05, max_value=0.05, allow_nan=False, allow_infinity=False),
            st.floats(min_value=-0.05, max_value=0.05, allow_nan=False, allow_infinity=False),
            st.floats(min_value=-0.05, max_value=0.05, allow_nan=False, allow_infinity=False),
        ),
        min_size=2,
        max_size=24,
    )
)
def test_covariance_estimators_are_positive_semidefinite_for_random_returns(
    rows: list[tuple[float, float, float]],
) -> None:
    returns = pd.DataFrame(rows, columns=("asset-a", "asset-b", "asset-c"))
    estimates = covariance_estimators(returns)

    assert estimates
    for estimator, covariance in estimates.items():
        if covariance.empty:
            continue
        matrix = covariance.to_numpy(dtype=float)
        eigenvalues = np.linalg.eigvalsh((matrix + matrix.T) / 2.0)
        assert float(eigenvalues.min()) >= -1e-10, estimator
