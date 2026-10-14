"""Issue #944: source-backed VWCE reference, cash-flow-matched shadow account, relative wealth."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
import yaml

from etf_cockpit.portfolio.benchmark_reference import (
    load_passive_default_policy,
    validate_vwce_reference_series,
    vwce_reference_status,
    vwce_series_source_hash,
)
from etf_cockpit.portfolio.benchmark_reference_contract import (
    BenchmarkReferenceError,
    CanonicalBenchmarkRegistry,
    load_canonical_benchmark_registry,
)
from etf_cockpit.portfolio.benchmark_relative_diagnostics import (
    PERIOD_EXCESS_LABEL,
    RELATIVE_WEALTH_LABEL,
    build_relative_performance,
)
from etf_cockpit.portfolio.currency import session_fx_rate
from etf_cockpit.portfolio.paper_trading import (
    PaperLedger,
    PaperLedgerError,
    ShadowCostPolicy,
)
from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series

KNOWN_AT = "2025-03-20T12:00:00+00:00"
SESSIONS = pd.bdate_range("2025-03-03", "2025-03-14")  # no NYSE or Xetra holiday
VWCE_CLOSES = [100.0, 100.0, 104.0, 107.0, 110.0, 110.0, 106.0, 103.0, 101.0, 100.0]
ACTIVE_CLOSES = [100.0, 100.0, 103.0, 109.0, 112.0, 113.0, 111.0, 109.0, 108.0, 107.0]


def _series(closes: list[float] = VWCE_CLOSES, **extra: object) -> pd.DataFrame:
    frame = pd.DataFrame({"date": SESSIONS, "close": closes, "adjusted_close": closes,
                          "provider_symbol": "VWCE.DE", "source": "yfinance", "currency": "EUR",
                          "is_adjusted": True, "stock_splits": 0, "dividends": 0, "capital_gains": 0})
    for name, value in extra.items():
        frame[name] = value
    return frame


def _metadata(frame):
    from etf_cockpit.data.provenance import metadata_from_frame

    return replace(metadata_from_frame(frame, source_name="yfinance", source_type="prices", as_of_date=date(2025, 3, 14), currency="EUR"), ingested_at=datetime.fromisoformat(KNOWN_AT))


def _check(frame: pd.DataFrame):
    return validate_vwce_reference_series(frame, known_at=KNOWN_AT, provider_metadata=_metadata(frame) if isinstance(frame, pd.DataFrame) else None)


def _at(day: str, hour: int = 9) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00")


def _active(tmp_path: Path, name: str, policy: ShadowCostPolicy) -> PaperLedger:
    ledger = PaperLedger(tmp_path, account_id=name)
    ledger.open_account(initial_cash=0, cost_policy=policy, occurred_at=_at("2025-03-01"))
    return ledger


def _ledger(tmp_path: Path, name: str, policy: ShadowCostPolicy, instrument_id: str = "VWCE") -> PaperLedger:
    if instrument_id == "STRATEGY":
        return _active(tmp_path, name, policy)
    active = _active(tmp_path, name + "-active", policy)
    ledger = PaperLedger(tmp_path, account_id=name)
    ledger.open_benchmark_shadow_account(cost_policy=policy, active_account=active, instrument_id=instrument_id)
    return ledger


def _active_flow(active, frame, policy, flow_id, kind, flow_at, amount):
    from tests.test_paper_trading import _proposal

    state = active._replay(active._read_events())
    if flow_id in state["external_flows"]:
        return
    sessions = pd.to_datetime(frame["date"])
    eligible = sessions[sessions > pd.Timestamp(flow_at.date())]
    if eligible.empty:
        return
    executed = eligible.min()
    raw = Decimal(str(frame.loc[sessions == executed, "close"].iloc[0]))
    price = raw * (1 + policy.adverse_bps / Decimal(10000) * (1 if kind == "contribution" else -1))
    if kind == "contribution":
        active.record_external_flow(flow_id=flow_id, kind=kind, amount=amount, flow_at=flow_at,
                                    source_authority="test-flow", source_checksum="a" * 64)
        quantity = max(Decimal(0), ((Decimal(amount) - policy.commission) / price / policy.lot_size).to_integral_value(rounding="ROUND_FLOOR") * policy.lot_size)
    else:
        needed = Decimal(amount) - state["cash"]
        quantity = max(Decimal(0), ((needed + policy.commission) / price / policy.lot_size).to_integral_value(rounding="ROUND_CEILING") * policy.lot_size) if needed > 0 else Decimal(0)
        if quantity > Decimal(str(sum(item["quantity"] for item in state["positions"].values()))):
            return
    if quantity:
        proposal = _proposal(quantity_delta=float(quantity) * (1 if kind == "contribution" else -1), source=active.account_id + flow_id)
        trade_at = _at(executed.date().isoformat(), 17)
        order = active.accept_proposal(proposal, execution_price=float(price), fee=float(policy.commission), occurred_at=trade_at)
        active.record_fill(order["order_id"], quantity=float(quantity), price=float(price), fee=float(policy.commission),
                           reference_price=raw, occurred_at=trade_at)
    if kind == "withdrawal":
        active.record_external_flow(flow_id=flow_id, kind=kind, amount=amount, flow_at=flow_at,
                                    effective_at=_at(executed.date().isoformat(), 18),
                                    source_authority="test-flow", source_checksum="a" * 64)


def _record(ledger, **kwargs):
    state = ledger._replay(ledger._read_events())
    policy = kwargs["cost_policy"]
    active = PaperLedger(ledger.root, account_id=state["shadow"]["active_account_id"])
    # Prepare canonical active evidence only for valid new requests; negative cases exercise shadow validation.
    if (state["shadow"]["cost_policy_digest"] == policy.digest()
            and kwargs["series_check"].status == "available"
            and kwargs["series_check"].source_hash == vwce_series_source_hash(kwargs["prices"])):
        _active_flow(active, kwargs["prices"], policy, kwargs["flow_id"], kwargs["kind"], kwargs["flow_at"], kwargs["amount"])
    return ledger.record_shadow_flow(**kwargs, decision_time=_at("2025-03-21"))


def _fund(ledger: PaperLedger, frame: pd.DataFrame, policy: ShadowCostPolicy, flows: list[tuple[str, str, str, int]]) -> None:
    check = _check(frame)
    for flow_id, kind, day, amount in flows:
        if ledger._replay(ledger._read_events())["shadow"] is None:
            _active_flow(ledger, frame, policy, flow_id, kind, _at(day), amount)
        else:
            _record(ledger, flow_id=flow_id, kind=kind, amount=amount, flow_at=_at(day),
                    prices=frame, series_check=check, cost_policy=policy)


def _snapshots(ledger: PaperLedger, frame: pd.DataFrame) -> pd.DataFrame:
    if ledger._replay(ledger._read_events())["shadow"] is not None:
        return ledger.shadow_daily_snapshots(frame, series_check=_check(frame), through=date(2025, 3, 14), decision_time=_at("2025-03-21"))
    from etf_cockpit.portfolio.valuation import build_daily_portfolio_snapshots

    events = ledger._read_events()
    flows = [e for e in events if e["event_type"] == "external_flow_recorded"]
    fills = [e for e in events if e["event_type"] == "fill_recorded"]
    holdings, prices, cash, movements = [], [], [], []
    start = min(pd.Timestamp(e["payload"]["effective_at"]).date() for e in flows)
    for row in frame.itertuples():
        day = pd.Timestamp(row.date).date()
        if day < start:
            continue
        quantity, balance = Decimal(0), Decimal(0)
        for event in flows:
            payload = event["payload"]
            if pd.Timestamp(payload["effective_at"]).date() <= day:
                balance += Decimal(payload["amount"]) * (1 if payload["flow_kind"] == "contribution" else -1)
        for event in fills:
            if pd.Timestamp(event["occurred_at"]).date() <= day:
                payload = event["payload"]
                units = Decimal(payload["quantity"]) * (1 if payload["side"] == "buy" else -1)
                quantity += units
                balance -= units * Decimal(payload["price"]) + Decimal(payload["fee"])
        holdings.append(dict(date=day, instrument_id="VWCE", quantity=float(quantity)))
        prices.append(dict(date=day, instrument_id="VWCE", price=row.close))
        cash.append(dict(date=day, cash_value=float(balance)))
    for event in flows:
        payload = event["payload"]
        movements.append(dict(date=pd.Timestamp(payload["effective_at"]).date(), event_type=payload["flow_kind"], amount=float(payload["amount"])))
    for event in fills:
        movements.append(dict(date=pd.Timestamp(event["occurred_at"]).date(), event_type="fee", amount=float(event["payload"]["fee"])))
    inputs = [pd.DataFrame(rows) for rows in (holdings, prices, cash, movements)]
    for item in inputs:
        item["available_at"] = KNOWN_AT
    result = build_daily_portfolio_snapshots(*inputs, decision_time=_at("2025-03-21"), calendar="XETR")
    result.attrs.update(account_id=ledger.account_id, calendar="XETR")
    return result


FLOWS = [("f1", "contribution", "2025-03-03", 1000), ("f2", "contribution", "2025-03-07", 9000)]
POLICY = ShadowCostPolicy()


def test_artificial_extra_distribution_on_accumulating_vwce_fails() -> None:
    assert _check(_series()).status == "available"
    with_cash_dividend = _series(dividends=[0, 0, 0, 0.35, 0, 0, 0, 0, 0, 0])
    assert "distribution_on_accumulating_share_class" in _check(with_cash_dividend).reasons
    # An adjusted close that embeds a distribution drifts away from the raw close of an accumulating class.
    adjusted = list(VWCE_CLOSES)
    adjusted[:4] = [value * 0.99 for value in adjusted[:4]]
    drifted = _series()
    drifted["adjusted_close"] = adjusted
    result = _check(drifted)
    assert result.status == "unavailable" and "adjusted_price_embeds_distribution" in result.reasons
    assert result.source_hash is None
    assert "distribution_policy_not_accumulating" in validate_vwce_reference_series(
        _series(), known_at=KNOWN_AT, accumulating=False
    ).reasons


def test_vwce_only_active_account_with_identical_flows_has_zero_relative_wealth(tmp_path: Path) -> None:
    frame = _series()
    active = _active(tmp_path, "active-vwce", POLICY)
    shadow = PaperLedger(tmp_path, account_id="shadow-vwce")
    shadow.open_benchmark_shadow_account(cost_policy=POLICY, active_account=active)
    for ledger in (active, shadow):
        _fund(ledger, frame, POLICY, FLOWS)
    relative = build_relative_performance(_snapshots(active, frame), _snapshots(shadow, frame))
    assert relative.status == "available"
    assert relative.compounded_relative_wealth == 0.0
    assert relative.period_excess_return == 0.0
    assert relative.strategy_twr == relative.benchmark_twr
    # The shadow account follows the next-session rule: flow 1 buys at the 04 Mar close, never the 03 Mar close.
    flow = _record(shadow,
        flow_id="f1", kind="contribution", amount=1000, flow_at=_at("2025-03-03"),
        prices=frame, series_check=_check(frame), cost_policy=POLICY,
    )
    assert flow["executed_session"] == "2025-03-04" and flow["entry_session"] == "2025-03-03"
    assert shadow.snapshot().cash == pytest.approx(0.0, abs=1e-5)  # lot-rounding residue only


def test_twr_and_xirr_diverge_on_a_late_contribution_and_relative_fields_are_separate(tmp_path: Path) -> None:
    benchmark_frame, active_frame = _series(), _series(ACTIVE_CLOSES)
    shadow = _ledger(tmp_path, "shadow-vwce", POLICY)
    active = _ledger(tmp_path, "active-strategy", POLICY, instrument_id="STRATEGY")
    _fund(shadow, benchmark_frame, POLICY, FLOWS)
    _fund(active, active_frame, POLICY, FLOWS)
    relative = build_relative_performance(_snapshots(active, active_frame), _snapshots(shadow, benchmark_frame))
    assert relative.status == "available"
    # VWCE: +10% then -9.09% on the large late contribution: TWR is flat, the investor's XIRR is negative.
    assert relative.benchmark_twr == pytest.approx(0.0, abs=1e-9)
    assert relative.benchmark_mwr is not None and relative.benchmark_mwr < -0.05
    assert relative.investor_timing_gap is not None
    # MWR and TWR are both period returns over the same window: the gap is their exact difference, and the MWR is
    # the de-annualised XIRR (annualised rate compounded over the elapsed days), not the annualised rate itself.
    from etf_cockpit.portfolio.valuation import calculate_money_weighted_return

    shadow_snapshots = _snapshots(shadow, benchmark_frame)
    mwr = calculate_money_weighted_return(shadow_snapshots)
    assert mwr["method"] == "xirr_deannualized_period_return"
    expected_period = (1 + mwr["annualized_xirr"]) ** (mwr["period_days"] / 365.0) - 1
    assert relative.benchmark_mwr == pytest.approx(expected_period, abs=1e-12)
    assert relative.benchmark_mwr != pytest.approx(mwr["annualized_xirr"], abs=1e-6)
    assert relative.investor_timing_gap == pytest.approx(relative.strategy_mwr - relative.strategy_twr, abs=1e-12)
    # Excess return (R_p - R_b) and compounded relative wealth (W_p / W_b - 1) are different, labelled numbers.
    assert relative.period_excess_return == pytest.approx(relative.strategy_twr - relative.benchmark_twr)
    assert relative.compounded_relative_wealth != pytest.approx(relative.period_excess_return, abs=1e-6)
    assert relative.period_excess_return_label == PERIOD_EXCESS_LABEL
    assert relative.compounded_relative_wealth_label == RELATIVE_WEALTH_LABEL
    # Different flows break the cash-flow match: relative wealth fails closed, the TWR difference remains.
    other = _ledger(tmp_path, "other-strategy", POLICY, instrument_id="STRATEGY")
    _fund(other, active_frame, POLICY, FLOWS[:1] + [("f2", "contribution", "2025-03-07", 8000)])
    unmatched = build_relative_performance(_snapshots(other, active_frame), _snapshots(shadow, benchmark_frame))
    assert unmatched.compounded_relative_wealth is None
    assert any("cash_flows_not_matched" in reason for reason in unmatched.reasons)
    assert unmatched.period_excess_return is not None


def test_registry_without_a_passing_contract_stays_unavailable() -> None:
    frame = _series()
    check = _check(frame)
    shipped = load_canonical_benchmark_registry()
    assert shipped.benchmarks[0].status == "unavailable"
    assert vwce_reference_status(shipped, check)["status"] == "unavailable"
    # An "available" record needs source hashes; the registry refuses to construct otherwise.
    with pytest.raises(BenchmarkReferenceError):
        replace(shipped.benchmarks[0], status="available", content_hash="")
    unsigned = replace(shipped.benchmarks[0], status="available", source_hashes=(check.source_hash,), content_hash="")
    # The registry tolerates an unsigned record; the reference gate must not.
    unverified = vwce_reference_status(CanonicalBenchmarkRegistry(benchmarks=[unsigned]), check)
    assert unverified["status"] == "unavailable" and str(unverified["reason"]).startswith("registry_record_unverified")
    bound = replace(unsigned, content_hash=unsigned.digest())
    registry = CanonicalBenchmarkRegistry(benchmarks=[bound])
    assert vwce_reference_status(registry, check)["status"] == "available"  # positive control
    later = replace(unsigned, known_at="2025-04-01T00:00:00+00:00")
    later = replace(later, content_hash=later.digest())
    assert "known_at" in str(vwce_reference_status(CanonicalBenchmarkRegistry(benchmarks=[later]), check)["reason"])
    usd = replace(unsigned, currency="USD")
    usd = replace(usd, content_hash=usd.digest())
    assert "currency" in str(vwce_reference_status(CanonicalBenchmarkRegistry(benchmarks=[usd]), check)["reason"])
    other = replace(bound, source_hashes=("a" * 64,), content_hash="")
    assert vwce_reference_status(CanonicalBenchmarkRegistry(benchmarks=[other]), check)["reason"] == "series_hash_not_in_registry"
    failing = _check(_series(dividends=[0, 0, 0, 0.35, 0, 0, 0, 0, 0, 0]))
    status = vwce_reference_status(registry, failing)
    assert status["status"] == "unavailable" and str(status["reason"]).startswith("series_contract_failed")
    # The performance series' benchmark metric stays unavailable without an available reference.
    snapshots = _ledger_snapshots_for_metric()
    unavailable = build_portfolio_performance_series(
        snapshots, metric="benchmark", benchmark_snapshots=snapshots, benchmark_reference=vwce_reference_status(shipped, check)
    )
    assert unavailable.status == "unavailable" and not unavailable.points
    active_snapshots = snapshots.copy()
    active_snapshots.attrs["account_id"] = snapshots.attrs["active_account_id"]
    available = build_portfolio_performance_series(
        active_snapshots, metric="benchmark", benchmark_snapshots=snapshots, benchmark_reference=vwce_reference_status(registry, check)
    )
    assert available.metric == "benchmark" and available.status != "unavailable"


def _ledger_snapshots_for_metric() -> pd.DataFrame:
    import tempfile

    frame = _series()
    with tempfile.TemporaryDirectory() as root:
        shadow = _ledger(Path(root), "shadow-vwce", POLICY)
        _fund(shadow, frame, POLICY, FLOWS)
        return _snapshots(shadow, frame)


def test_split_or_adjusted_price_discontinuity_is_detected() -> None:
    split = [100.0, 101.0, 102.0, 51.0, 51.5, 52.0, 52.5, 53.0, 53.5, 54.0]  # an unadjusted 2:1 split
    result = _check(_series(split))
    assert result.status == "unavailable"
    assert "split_or_adjustment_discontinuity:close" in result.reasons
    assert "split_or_adjustment_discontinuity:adjusted_close" in result.reasons
    only_adjusted = _series()
    only_adjusted["adjusted_close"] = [value if index < 4 else value / 2 for index, value in enumerate(VWCE_CLOSES)]
    assert "split_or_adjustment_discontinuity:adjusted_close" in _check(only_adjusted).reasons


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"isin": "IE00B3RBWM25"}, "identity_isin_mismatch"),
        ({"ticker": "VWRL.AS"}, "identity_listing_mismatch"),
        ({"currency": "USD"}, "quote_currency_not_eur"),
        ({"fx_converted": True}, "double_fx_conversion"),
        ({"known_at": "2025-03-10T00:00:00"}, "known_at_not_timezone_aware"),
        ({"known_at": "2025-03-10T00:00:00+00:00"}, "observation_after_known_at"),
        ({"declared_source_hash": "0" * 64}, "source_hash_mismatch"),
    ],
)
def test_series_contract_fails_closed_on_identity_currency_and_time(override: dict[str, object], reason: str) -> None:
    options = {"known_at": KNOWN_AT, **override}
    result = validate_vwce_reference_series(_series(), **options)  # type: ignore[arg-type]
    assert result.status == "unavailable" and reason in result.reasons and result.source_hash is None


def test_partial_bar_series_is_not_known_and_shadow_valuation_stops_before_the_decision_day(tmp_path: Path) -> None:
    frame = _series()  # last bar 2025-03-14
    for known_at, status in (("2025-03-14T09:00:00+00:00", "unavailable"),  # in-progress bar
                             ("2025-03-14T15:00:00+00:00", "unavailable"),  # 16:00 Berlin, before the close
                             ("2025-03-14T17:00:00+00:00", "available"),    # after the Xetra close
                             ("2025-03-15T00:00:00+00:00", "available")):
        meta = replace(_metadata(frame), ingested_at=datetime.fromisoformat(known_at))
        result = validate_vwce_reference_series(frame, known_at=known_at, provider_metadata=meta)
        assert result.status == status
        assert status == "available" or "observation_after_known_at" in result.reasons
    shadow = _ledger(tmp_path, "shadow-vwce", POLICY)
    _fund(shadow, frame, POLICY, FLOWS)
    with pytest.raises(PaperLedgerError, match="decision cutoff"):
        shadow.shadow_daily_snapshots(frame, series_check=_check(frame), through=date(2025, 3, 14),
                                      decision_time=_at("2025-03-14", 20))
    assert not shadow.shadow_daily_snapshots(frame, series_check=_check(frame), through=date(2025, 3, 14),
                                             decision_time=_at("2025-03-21")).empty


def test_series_contract_rejects_structural_defects() -> None:
    frame = _series()
    assert validate_vwce_reference_series(frame, known_at=KNOWN_AT, provider_metadata=_metadata(frame), declared_source_hash=vwce_series_source_hash(frame)).status == "available"
    duplicated = pd.concat([frame, frame.iloc[[3]]], ignore_index=True)
    assert "duplicate_dates" in _check(duplicated).reasons
    broken = frame.copy()
    broken.loc[2, "close"] = float("nan")
    assert "prices_missing_or_non_positive" in _check(broken).reasons
    assert "series_columns_missing" in _check(frame[["date", "close"]]).reasons
    assert _check(None).status == "unavailable"  # type: ignore[arg-type]


def test_shadow_account_uses_shared_costs_lot_policy_and_next_session_price(tmp_path: Path) -> None:
    frame = _series()
    policy = ShadowCostPolicy(commission=Decimal("1"), adverse_bps=Decimal("10"), lot_size=Decimal("1"))
    shadow = _ledger(tmp_path, "shadow-vwce", policy)
    check = _check(frame)
    with pytest.raises(PaperLedgerError, match="policy"):
        _record(shadow,
            flow_id="x", kind="contribution", amount=1000, flow_at=_at("2025-03-03"),
            prices=frame, series_check=check, cost_policy=ShadowCostPolicy(commission=Decimal("2"), lot_size=Decimal("1")),
        )
    buy = _record(shadow,
        flow_id="f1", kind="contribution", amount=1000, flow_at=_at("2025-03-07"),
        prices=frame, series_check=check, cost_policy=policy,
    )
    # Friday flow -> entered Friday, executed at the next session (Monday 10 Mar) close 110 plus 10 bps.
    assert buy["entry_session"] == "2025-03-07" and buy["executed_session"] == "2025-03-10"
    assert Decimal(buy["price"]) == Decimal("110") * Decimal("1.001")
    assert Decimal(buy["quantity"]) == Decimal(int((Decimal(999) / Decimal(buy["price"]))))  # whole lots, fee deducted
    assert Decimal(buy["fee"]) == Decimal("1")
    assert _record(shadow,   # same flow id and terms is idempotent
        flow_id="f1", kind="contribution", amount=1000, flow_at=_at("2025-03-07"),
        prices=frame, series_check=check, cost_policy=policy,
    ) == buy
    with pytest.raises(PaperLedgerError, match="different terms"):
        _record(shadow,
            flow_id="f1", kind="contribution", amount=2000, flow_at=_at("2025-03-07"),
            prices=frame, series_check=check, cost_policy=policy,
        )
    sale = _record(shadow,
        flow_id="w1", kind="withdrawal", amount=300, flow_at=_at("2025-03-11"),
        prices=frame, series_check=check, cost_policy=policy,
    )
    assert sale["side"] == "sell" and sale["executed_session"] == "2025-03-12"
    assert Decimal(sale["price"]) == Decimal("103") * Decimal("0.999")
    with pytest.raises(PaperLedgerError, match="exceeds|evidence"):
        _record(shadow,
            flow_id="w2", kind="withdrawal", amount=10_000, flow_at=_at("2025-03-11"),
            prices=frame, series_check=check, cost_policy=policy,
        )
    # No later session yet: nothing is recorded.
    with pytest.raises(PaperLedgerError, match="No eligible"):
        _record(shadow,
            flow_id="late", kind="contribution", amount=100, flow_at=_at("2025-03-14"),
            prices=frame, series_check=check, cost_policy=policy,
        )
    snapshots = shadow.shadow_daily_snapshots(frame, series_check=check, through=date(2025, 3, 13), decision_time=_at("2025-03-21"))
    assert list(snapshots["external_flow"].fillna(0)).count(1000.0) == 1
    assert (snapshots["external_flow"] == -300.0).sum() == 1
    assert snapshots["fees"].sum() == pytest.approx(2.0)


def _ready_proposal() -> dict[str, object]:
    from tests.test_paper_trading import _proposal

    return _proposal()


def test_shadow_account_rejects_unverified_series_and_proposals(tmp_path: Path) -> None:
    frame = _series()
    shadow = _ledger(tmp_path, "shadow-vwce", POLICY)
    bad = _check(_series(dividends=[0, 0, 0, 0.35, 0, 0, 0, 0, 0, 0]))
    with pytest.raises(PaperLedgerError, match="source-backed"):
        _record(shadow,
            flow_id="f1", kind="contribution", amount=1000, flow_at=_at("2025-03-03"),
            prices=frame, series_check=bad, cost_policy=POLICY,
        )
    tampered = frame.copy()
    tampered.loc[4, "close"] = tampered.loc[4, "adjusted_close"] = 90.0
    with pytest.raises(PaperLedgerError, match="source hash"):
        _record(shadow,
            flow_id="f1", kind="contribution", amount=1000, flow_at=_at("2025-03-03"),
            prices=tampered, series_check=_check(frame), cost_policy=POLICY,
        )
    with pytest.raises(PaperLedgerError, match="shadow account cannot accept proposals"):
        shadow.accept_proposal(_ready_proposal(), execution_price=100.0)
    # A shadow ledger replays after restart with the same cash and units.
    _fund(shadow, frame, POLICY, FLOWS[:1])
    reopened = PaperLedger(tmp_path, account_id="shadow-vwce")
    assert reopened.snapshot().ledger_hash == shadow.snapshot().ledger_hash
    assert reopened.snapshot().positions[0].quantity == pytest.approx(10.0)
    with pytest.raises(PaperLedgerError, match="policy|opening terms"):
        reopened.open_benchmark_shadow_account(cost_policy=ShadowCostPolicy(commission=Decimal("1")), active_account=PaperLedger(tmp_path, account_id="shadow-vwce-active"))


def _extended(frame: pd.DataFrame, closes: list[float]) -> pd.DataFrame:
    days = pd.bdate_range("2025-03-17", periods=len(closes))
    more = pd.DataFrame({"date": days, "close": closes, "adjusted_close": closes})
    for name in ("provider_symbol", "source", "currency", "is_adjusted", "stock_splits", "dividends", "capital_gains"):
        more[name] = frame[name].iloc[0]
    return pd.concat([frame, more], ignore_index=True)


def test_shadow_flows_bind_history_to_their_session_not_the_whole_series(tmp_path: Path) -> None:
    frame = _series()
    shadow = _ledger(tmp_path, "shadow-vwce", POLICY)
    _fund(shadow, frame, POLICY, FLOWS)
    base = shadow.shadow_daily_snapshots(frame, series_check=_check(frame), through=date(2025, 3, 14), decision_time=_at("2025-03-21"))
    # (a) Appending newer sessions leaves every older flow valid (sequential flows share one prefix-bound lineage).
    longer = _extended(frame, [101.0, 102.0])
    grown = shadow.shadow_daily_snapshots(longer, series_check=_check(longer), through=date(2025, 3, 14), decision_time=_at("2025-03-21"))
    pd.testing.assert_frame_equal(base.reset_index(drop=True), grown.reset_index(drop=True))
    assert len(shadow.shadow_daily_snapshots(longer, series_check=_check(longer), through=date(2025, 3, 18), decision_time=_at("2025-03-21"))) > len(base)
    # (b) A revised close at or before a flow's execution session fails closed, even with a valid check for it.
    for row in (0, 1, 5):
        revised = frame.copy()
        revised.loc[row, ["close", "adjusted_close"]] = revised.loc[row, "close"] + 0.5
        with pytest.raises(PaperLedgerError, match="historical_price_revised:f"):
            shadow.shadow_daily_snapshots(revised, series_check=_check(revised), through=date(2025, 3, 14), decision_time=_at("2025-03-21"))


def test_session_fx_rate_never_reconverts_a_same_currency_quote() -> None:
    assert session_fx_rate(None, "2025-03-10", from_currency="EUR", to_currency="EUR") == (Decimal("1"), None)
    rate, reason = session_fx_rate(None, "2025-03-10", from_currency="USD", to_currency="EUR")
    assert rate is None and reason
    rate, reason = session_fx_rate(pd.DataFrame(), "2025-03-10", from_currency="USD", to_currency="EUR")
    assert rate is None and reason
    assert session_fx_rate(None, "2025-03-10", from_currency="US", to_currency="EUR")[0] is None


def test_passive_default_policy_is_versioned_pending_and_leaves_targets_untouched(tmp_path: Path) -> None:
    path = Path(__file__).resolve().parents[1] / "configs" / "portfolio_policy_v1.yaml"
    policy = load_passive_default_policy(path)
    assert policy["status"] == "unavailable" and policy["reason"] == "owner_approval_pending"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["version"] == "1.0.0" and payload["execution_allowed"] is False
    assert payload["historical_targets"]["modified_by_policy"] is False
    approved = {**payload, "approval": {"status": "approved", "approved_by": "owner", "approved_at": "2026-10-13T00:00:00+00:00"}}
    approved_path = tmp_path / "policy.yaml"
    approved_path.write_text(yaml.safe_dump(approved), encoding="utf-8")
    result = load_passive_default_policy(approved_path)
    assert result["status"] == "available" and result["default_instrument_id"] == "VWCE"
    approved_path.write_text(yaml.safe_dump({**approved, "execution_allowed": True}), encoding="utf-8")
    assert load_passive_default_policy(approved_path)["status"] == "unavailable"
    assert load_passive_default_policy(tmp_path / "missing.yaml")["status"] == "unavailable"
    targets = yaml.safe_load((path.parent / "portfolio_targets.yaml").read_text(encoding="utf-8"))
    assert targets["positions"]["VWCE"]["target_weight"] == 0.0
