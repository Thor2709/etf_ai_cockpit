from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from etf_cockpit.analysis import fixed_income_analytics
from etf_cockpit.portfolio import ledger_projection
from etf_cockpit.portfolio.ledger import Ledger, LedgerPosting
from etf_cockpit.trading.pre_trade_controls import PreTradeControls, PreTradeDecision
from mutation_harness import MutationProbe, load_mutation_thresholds, run_critical_mutants
from test_golden_financial import _assert_bond_matches_golden
from test_pre_trade_controls import _known_broker_state, _proposal
from test_properties_financial import _memory_ledger_connection


_UTC = timezone.utc
_THRESHOLDS = Path(__file__).resolve().parents[1] / "configs" / "mutation_thresholds_v1.yaml"
_CONTROL_TIME = datetime(2026, 9, 30, tzinfo=_UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(_UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _mutant_hidden_bond_calculation():
    original = fixed_income_analytics.clean_price_from_yield

    def divergent_calculation(valuation, yield_value):
        return original(valuation, yield_value) + Decimal("0.01")

    return patch.object(
        fixed_income_analytics,
        "clean_price_from_yield",
        side_effect=divergent_calculation,
    )


def _mutant_kill_switch_removed():
    return patch.object(
        PreTradeControls,
        "_kill_switch_active",
        new=staticmethod(lambda _events: False),
    )


def _mutant_order_limit_removed():
    original = PreTradeControls.load_limits

    def widened_limit(self):
        return replace(original(self), max_order_value=Decimal("1000000000000"))

    return patch.object(PreTradeControls, "load_limits", new=widened_limit)


def _mutant_replay_cutoff_shifted():
    original = ledger_projection.replay_ledger

    def shifted_cutoff(connection, *, authority, as_of, known_at=None, **kwargs):
        parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00")) - timedelta(microseconds=1)
        shifted = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
        return original(
            connection,
            authority=authority,
            as_of=shifted,
            known_at=known_at,
            **kwargs,
        )

    return patch.object(ledger_projection, "replay_ledger", side_effect=shifted_cutoff)


def _exact_cutoff_invariant() -> None:
    cutoff = datetime.now(_UTC).replace(microsecond=0)
    with closing(_memory_ledger_connection()) as connection:
        ledger = Ledger(connection)
        ledger.create_account("cash", name="Cash", account_type="asset", authority="paper", account_role="cash")
        ledger.create_account("equity", name="Equity", account_type="equity", authority="paper")
        ledger.post(
            "event-at-cutoff",
            authority="paper",
            effective_at=_utc_text(cutoff),
            settlement_at=_utc_text(cutoff),
            postings=(
                LedgerPosting("cash", "EUR", debit=Decimal("5")),
                LedgerPosting("equity", "EUR", credit=Decimal("5")),
            ),
        )
        known_at = datetime.now(_UTC) + timedelta(seconds=10)
        projection = ledger_projection.replay_ledger(
            connection,
            authority="paper",
            as_of=_utc_text(cutoff),
            known_at=_utc_text(known_at),
        )
    assert projection.cash
    assert projection.cash[0].book_balance == Decimal("5")


def _evaluate_with_events(proposal, events):
    controls = PreTradeControls(Path(__file__).resolve().parents[1])

    def block_without_audit(control, reason, *_args, **_kwargs):
        return PreTradeDecision(False, control, reason)

    with (
        patch.object(controls, "_read_events", return_value=events),
        patch.object(controls, "_block", new=block_without_audit),
    ):
        return controls.evaluate_order(
            proposal,
            execution_price=10,
            quantity_delta=float(proposal["quantity_delta"]),
            fx_rate=1,
            positions={},
            open_orders={},
            paper_events=[],
            broker_state=_known_broker_state(),
            daily_turnover=0,
            path="paper",
            who="mutation-operator",
            occurred_at=_CONTROL_TIME,
        )


def _kill_switch_invariant() -> None:
    decision = _evaluate_with_events(
        _proposal(quantity_delta=1, source="kill-switch-mutation"),
        [{"event_type": "kill_switch_activated"}],
    )
    assert decision.allowed is False
    assert decision.control == "kill_switch"


def _order_limit_invariant() -> None:
    decision = _evaluate_with_events(
        _proposal(quantity_delta=1_001, source="order-limit-mutation"),
        [],
    )
    assert decision.allowed is False
    assert decision.control == "max_order_value"


def test_every_configured_critical_mutant_is_killed() -> None:
    thresholds = load_mutation_thresholds(_THRESHOLDS)
    probes = {
        "hidden_bond_second_calculation": MutationProbe(
            _mutant_hidden_bond_calculation, _assert_bond_matches_golden
        ),
        "kill_switch_check_removed": MutationProbe(
            _mutant_kill_switch_removed, _kill_switch_invariant
        ),
        "pretrade_order_limit_removed": MutationProbe(
            _mutant_order_limit_removed, _order_limit_invariant
        ),
        "ledger_replay_cutoff_shifted": MutationProbe(
            _mutant_replay_cutoff_shifted, _exact_cutoff_invariant
        ),
    }

    assert thresholds.required_kill_rate == 1.0
    results, kill_rate = run_critical_mutants(_THRESHOLDS, probes)
    assert results == {mutant: "mutant killed" for mutant in thresholds.critical_mutants}
    assert kill_rate == 1.0
