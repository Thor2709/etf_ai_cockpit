"""BOT2: the paper bots follow the owner spec of 2026-10-22 (cadence per bot, caps as percent of NAV)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.portfolio import paper_bots, paper_bots_execution as execution
from etf_cockpit.portfolio.paper_trading import PaperLedger
from tests import test_paper_bots as stage_a
from tests.test_paper_bots_execution import _allow, _book, _by, _execute, _plans, _ready, _records

NAV = Decimal("40000")
LOT = Decimal("1")


def _config() -> dict:
    return yaml.safe_load(paper_bots.PAPER_BOTS_CONFIG_PATH.read_text(encoding="utf-8"))


def _write_config(tmp_path: Path, payload: dict, name: str = "bots.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _limits() -> dict[str, float]:
    return execution.load_execution_config()[1]["position_limits"]


def _universe(**entries: dict) -> SimpleNamespace:
    universe = {key.upper(): SimpleNamespace(**value) for key, value in entries.items()}
    return SimpleNamespace(universe_index=universe, app_config=SimpleNamespace(universe=SimpleNamespace(by_id=lambda: {})))


def _month_runs(monkeypatch, tmp_path: Path, months: int) -> list[paper_bots.PaperBotRunResult]:
    """Record the stage A decisions of ``months`` consecutive calendar months (the 14th of each, from October 2026)."""

    results = []
    for index in range(months):
        year, month = divmod(2026 * 12 + 9 + index, 12)
        now = datetime(year, month + 1, 14, 12, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(stage_a, "_NOW", now)
        known_at = now - timedelta(minutes=5)
        rows = stage_a._rows(known_at, run_id=f"run-{index}", snapshot="0123456789abcdef"[index])
        board = stage_a._scoreboard(rows, known_at)
        board["instrument_currency"] = "EUR"
        results.append(stage_a._run_fixture(monkeypatch, tmp_path, rows, board, now + timedelta(seconds=1)))
    return results


def _decision_months(tmp_path: Path) -> dict[str, list[str]]:
    with TransactionalStore(tmp_path, read_only=True) as store:
        payloads = [dict(item.payload) for item in store.list(paper_bots.DECISION_ENTITY_TYPE)]
    months: dict[str, list[str]] = {}
    for payload in payloads:
        if payload["status"] == "available":
            months.setdefault(payload["bot_family"], []).append(payload["decision_month"])
    return {family: sorted(items) for family, items in months.items()}


# (1) cadence month gating for B1/B2/B3 and (2) B0 decides once ---------------------------------------------------------


def test_each_bot_decides_only_in_its_cadence_months(monkeypatch, tmp_path: Path) -> None:
    results = _month_runs(monkeypatch, tmp_path, 7)  # October 2026 .. April 2027 = month offsets 0..6
    assert all(item.status == "available" for item in results), [item.reason for item in results]
    months = _decision_months(tmp_path)
    all_months = ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04"]
    assert months["B1"] == all_months  # monthly
    assert months["B2"] == ["2026-10", "2027-01", "2027-04"]  # quarterly
    assert months["B3"] == ["2026-10", "2027-04"]  # half-yearly
    assert months["B0"] == ["2026-10"]  # buy and hold: decided once on day one
    assert [{item["bot_family"] for item in run.records} for run in results[1:3]] == [{"B1"}, {"B1"}]  # off months record only B1


def test_cadence_is_counted_from_the_first_available_decision_month() -> None:
    spec = {"strategy": "core_sleeve", "rebalance_every_months": 3}
    assert paper_bots._cadence_due(spec, "2026-10", None)  # no decision yet: due
    assert [paper_bots._cadence_due(spec, f"2026-{m:02d}", "2026-08") for m in (8, 9, 10, 11, 12)] == [True, False, False, True, False]
    assert not paper_bots._cadence_due(spec, "2026-07", "2026-08")  # never before the first month
    assert paper_bots._cadence_due(spec, "2026-10", "2026-10")  # the first decision month itself (offset 0) is always due
    assert not paper_bots._cadence_due({"strategy": "core_sleeve"}, "2026-10", "2026-10")  # no cadence stated: fail closed
    assert not paper_bots._cadence_due({"strategy": "core_sleeve"}, "2026-11", "2026-10")  # also for a later month
    assert paper_bots._cadence_due({"strategy": "benchmark"}, "2026-10", "2026-10")  # B0 decides in its first month only
    assert not paper_bots._cadence_due({"strategy": "benchmark"}, "2026-11", "2026-10")


def test_b0_never_trades_after_day_one(monkeypatch, tmp_path: Path) -> None:
    _month_runs(monkeypatch, tmp_path, 2)
    _allow(tmp_path)
    run = _execute(tmp_path, _book(), as_of=datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc))
    assert run.status in {"available", "partial"}
    assert _by(_records(tmp_path), "B0") == []  # B0 has no paper orders at all: its shadow account holds the day-one VWCE buy
    b0_decisions = [item for item in _decision_records(tmp_path) if item["bot_family"] == "B0"]
    assert [item["decision_month"] for item in b0_decisions] == ["2026-10"]
    b0 = paper_bots_bot_id(b0_decisions)
    assert len(PaperLedger(execution.forward_track(tmp_path).ledger_root, account_id=execution.account_id_for(b0)).orders()) == 0


def _decision_records(tmp_path: Path) -> list[dict]:
    with TransactionalStore(tmp_path, read_only=True) as store:
        return [dict(item.payload) for item in store.list(paper_bots.DECISION_ENTITY_TYPE) if item.payload["status"] == "available"]


def paper_bots_bot_id(decisions: list[dict]) -> str:
    return str(decisions[0]["bot_id"])


# (7) config validation ---------------------------------------------------------------------------------------------------


def test_config_validation_accepts_exactly_b0_to_b3(tmp_path: Path) -> None:
    payload = _config()
    _raw, loaded = paper_bots._load_config(_write_config(tmp_path, payload))
    assert {item["family_id"] for item in loaded["bots"]} == {"B0", "B1", "B2", "B3"}
    assert {item["family_id"]: item.get("rebalance_every_months") for item in loaded["bots"]} == {"B0": None, "B1": 1, "B2": 3, "B3": 6}
    assert loaded["initial_virtual_cash_eur"] == 40000.0 and loaded["monthly_contribution_eur"] == 0.0
    missing = {**payload, "bots": [item for item in payload["bots"] if item["family_id"] != "B3"]}
    with pytest.raises(ValueError, match="B0, B1, B2 and B3"):
        paper_bots._load_config(_write_config(tmp_path, missing, "missing.yaml"))
    extra = {**payload, "bots": [*payload["bots"], {**payload["bots"][1], "family_id": "B4"}]}
    with pytest.raises(ValueError, match="B0, B1, B2 and B3"):
        paper_bots._load_config(_write_config(tmp_path, extra, "extra.yaml"))
    duplicate = {**payload, "bots": [*payload["bots"], dict(payload["bots"][3])]}
    with pytest.raises(ValueError, match="unique|exactly once"):
        paper_bots._load_config(_write_config(tmp_path, duplicate, "duplicate.yaml"))


@pytest.mark.parametrize("mutate", [
    lambda bot: bot.pop("rebalance_every_months"),
    lambda bot: bot.update(rebalance_every_months=0),
    lambda bot: bot.update(rebalance_every_months=13),
    lambda bot: bot.pop("horizon_months"),
    lambda bot: bot.update(horizon_months=[6, 3]),
])
def test_a_rebalancing_bot_needs_a_valid_cadence_and_horizon(tmp_path: Path, mutate) -> None:
    payload = _config()
    mutate(next(item for item in payload["bots"] if item["family_id"] == "B3"))
    with pytest.raises(ValueError, match="rebalance_every_months|horizon_months"):
        paper_bots._load_config(_write_config(tmp_path, payload))


def test_the_owner_horizons_and_cadences_are_configured() -> None:
    bots = {item["family_id"]: item for item in _config()["bots"]}
    assert (bots["B1"]["horizon_months"], bots["B1"]["rebalance_every_months"]) == ([3, 6], 1)
    assert (bots["B2"]["horizon_months"], bots["B2"]["rebalance_every_months"]) == ([6, 12], 3)
    assert bots["B3"]["rebalance_every_months"] == 6 and bots["B3"]["horizon_months"][0] >= 12
    assert (bots["B3"]["core_weight"], bots["B3"]["sleeve_top_n"], bots["B3"]["sleeve_action"]) == (0.8, 5, "CANDIDATE_BUY")


# (3)(4) per-instrument caps ----------------------------------------------------------------------------------------------


def _cap(kind: str, raw_weight: str, have_weight: str = "0", price: str = "20") -> tuple[Decimal, Decimal | None, str | None]:
    price_value = Decimal(price)
    return execution._apply_position_cap(
        {"kind": kind}, _limits(), Decimal(raw_weight) * NAV / price_value // 1, Decimal(have_weight) * NAV / price_value // 1,
        price_value, price_value, NAV, LOT,
    )


def _weight(quantity: Decimal, price: str = "20") -> Decimal:
    return quantity * Decimal(price) / NAV


def test_a_stock_buy_is_capped_at_eight_percent_and_trimmed_above_twelve() -> None:
    target, cap, note = _cap("stock", "0.20")
    assert _weight(target) == Decimal("0.08") and cap == Decimal("0.08") and "8%" in note  # entry cap
    target, _cap_weight, _note = _cap("stock", "0.05")
    assert _weight(target) == Decimal("0.05")  # a smaller target is not raised to the cap
    held_target, _cap_weight, note = _cap("stock", "0.20", have_weight="0.10")
    assert _weight(held_target) == Decimal("0.10") and note  # between 8 and 12 percent: held, neither bought nor sold
    target, _cap_weight, note = _cap("stock", "0.20", have_weight="0.13")
    assert _weight(target) == Decimal("0.08") and "trim" in note  # above 12 percent: sold back to 8
    target, _cap_weight, note = _cap("stock", "0.20", have_weight="0.12")
    assert _weight(target) == Decimal("0.12")  # exactly at the trigger is not above it


def test_narrow_etf_is_capped_at_twenty_percent_broad_etf_is_not_capped_and_unknown_is_narrow() -> None:
    target, cap, _note = _cap("narrow_etf", "0.50")
    assert _weight(target) == Decimal("0.20") and cap == Decimal("0.20")
    target, cap, note = _cap("broad_etf", "0.80")
    assert _weight(target) == Decimal("0.80") and cap is None and note is None  # no cap beyond its core weight
    target, cap, _note = _cap("unknown", "0.50")
    assert _weight(target) == Decimal("0.20") and cap == Decimal("0.20")  # unknown class fails closed to the narrow cap


def test_classification_uses_the_universe_and_fails_closed_to_unknown() -> None:
    context = _universe(
        BROAD={"instrument_type": "etf", "sector": "Broad", "region": "World"},
        TECH={"instrument_type": "etf", "sector": "Technology", "region": "Europe"},
        BANKX={"instrument_type": "stock", "sector": "Banks", "region": "Norway"},
        CERT={"instrument_type": "equity_certificate", "sector": "Banks", "region": "Norway"},
        NOSECTOR={"instrument_type": "etf", "sector": None, "region": "World"},
    )
    decision = {"instrument_asset_types": {"FROZENSTOCK": "STOCK", "FROZENETF": "ETF"}}
    kinds = {name: execution._classify(context, decision, name) for name in ("BROAD", "TECH", "BANKX", "CERT", "NOSECTOR", "FROZENSTOCK", "FROZENETF", "ABSENT")}
    assert {name: item["kind"] for name, item in kinds.items()} == {
        "BROAD": "broad_etf", "TECH": "narrow_etf", "BANKX": "stock", "CERT": "stock", "NOSECTOR": "unknown",
        "FROZENSTOCK": "stock", "FROZENETF": "unknown", "ABSENT": "unknown",
    }
    assert (kinds["TECH"]["sector"], kinds["TECH"]["country"]) == ("Technology", None)  # Europe spans countries
    assert (kinds["BANKX"]["sector"], kinds["BANKX"]["country"]) == ("Banks", "Norway")
    assert (kinds["BROAD"]["sector"], kinds["BROAD"]["country"]) == (None, None)


# (5) sector and country caps ---------------------------------------------------------------------------------------------


def _row(weight: str, have: str = "0", price: str = "20") -> dict:
    quantity = Decimal(weight) * NAV / Decimal(price) // 1
    return {
        "weight": Decimal(weight), "have": Decimal(have) * NAV / Decimal(price) // 1, "price": Decimal(price), "target": quantity,
        "ordered": quantity, "notes": [], "refusal": None,
    }


def test_a_sector_is_capped_at_thirty_percent_by_cutting_the_lowest_weight_buys() -> None:
    rows = {name: _row(weight) for name, weight in (("T1", "0.20"), ("T2", "0.15"), ("T3", "0.10"), ("OTHER", "0.20"))}
    info = {name: {"sector": "Technology", "country": None} for name in ("T1", "T2", "T3")} | {"OTHER": {"sector": "Banks", "country": None}}
    execution._apply_group_caps(rows, info, {}, _limits(), NAV, LOT)
    tech = sum(_weight(rows[name]["target"]) for name in ("T1", "T2", "T3"))
    assert tech <= Decimal("0.30") and tech > Decimal("0.29")  # reduced to the cap, not below it
    assert _weight(rows["T1"]["target"]) == Decimal("0.20")  # the highest target weight keeps its full buy
    assert rows["T3"]["refusal"] is not None and rows["T3"]["refusal"].startswith("sector_cap_reached: Technology")  # nothing fits: named
    assert rows["T2"]["notes"] and rows["T2"]["refusal"] is None  # partly reduced
    assert _weight(rows["OTHER"]["target"]) == Decimal("0.20") and not rows["OTHER"]["notes"]  # another sector is untouched


def test_a_country_is_capped_at_thirty_percent_and_held_positions_are_not_sold() -> None:
    rows = {"N1": _row("0.25", have="0.25"), "N2": _row("0.20"), "N3": _row("0.20")}
    info = {name: {"sector": None, "country": "Norway"} for name in rows}
    execution._apply_group_caps(rows, info, {}, _limits(), NAV, LOT)
    assert rows["N1"]["target"] == rows["N1"]["have"] and rows["N1"]["refusal"] is None  # a held position is never sold for a group cap
    assert rows["N3"]["target"] == rows["N3"]["have"] and rows["N3"]["refusal"].startswith("country_cap_reached: Norway")  # nothing fits
    norway = sum(_weight(rows[name]["target"]) for name in rows)
    assert Decimal("0.29") < norway <= Decimal("0.30")  # N2 takes only the 5 percent that still fits
    assert rows["N2"]["refusal"] is None and rows["N2"]["notes"]


# end to end through the planner and the fills ----------------------------------------------------------------------------


def _plan_for(tmp_path: Path, family: str) -> dict:
    return next(item for item in _plans(tmp_path) if item["intents"] and item["intents"][0]["reason"].endswith(f"({family}") or f"({family}, " in item["intents"][0]["reason"])


def _intents(plan: dict, instrument: str) -> list[dict]:
    return [item for item in plan["intents"] if item["instrument_id"] == instrument]


def test_the_planner_caps_stock_narrow_etf_and_leaves_the_broad_core_uncapped(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path)
    assert _execute(tmp_path, book).status in {"available", "partial"}
    nav = Decimal("40000")
    b1, b2 = _plan_for(tmp_path, "B1"), _plan_for(tmp_path, "B2")
    assert Decimal(b1["portfolio_value_before"]) == nav
    (stock,), (etf,) = _intents(b1, "AAA"), _intents(b1, "BBB")  # AAA is a STOCK row and BBB an ETF the universe does not know
    assert Decimal(stock["planned_quantity"]) * Decimal(stock["sizing_price"]) <= Decimal("0.08") * nav
    assert Decimal(etf["planned_quantity"]) * Decimal(etf["sizing_price"]) <= Decimal("0.20") * nav
    assert "8%" in stock["reason"] and "20%" in etf["reason"]
    assert b1["classification"]["AAA"]["kind"] == "stock" and b1["classification"]["BBB"]["kind"] == "unknown"
    (core,) = _intents(b2, "VWCE")
    assert b2["classification"]["VWCE"]["kind"] == "broad_etf" and core["max_after_position_value_eur"] is None
    assert Decimal(core["planned_quantity"]) * Decimal(core["sizing_price"]) > Decimal("0.75") * nav  # the 80 percent core is not capped


def test_a_gap_up_at_the_fill_cannot_push_a_buy_past_the_percent_cap(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path, opens={"AAA": {date(2026, 10, 15): 30.0}})  # +40 percent at the fill session
    _execute(tmp_path, book)
    filled = _by(_records(tmp_path), "B1", "AAA", "filled")
    assert filled
    for item in filled:
        assert Decimal(item["quantity"]) * Decimal(item["fill_price"]) <= Decimal("0.08") * Decimal("40000")
        assert "percent-of-NAV position limit" in item["reason"]


def test_the_concentration_gate_is_a_real_backstop_and_the_absolute_exposure_check_is_replaced(monkeypatch, tmp_path: Path) -> None:
    ready = _ready(monkeypatch, tmp_path)
    monkeypatch.setattr(execution, "_cap_room", lambda *args, **kwargs: Decimal("1000000"))  # sizing fails to hold the cap
    _execute(tmp_path, ready)
    refused = _by(_records(tmp_path), "B1", "AAA")
    assert refused and refused[0]["status"] == "missed" and "proposal_policy_refused" in refused[0]["reason"]
    assert not _by(_records(tmp_path), "B1", "AAA", "filled")


def test_the_bot_ledger_root_drops_the_absolute_exposure_limit_but_the_live_limits_stay(monkeypatch, tmp_path: Path) -> None:
    _ready(monkeypatch, tmp_path)
    live_before = (execution.CONFIG_DIR / "pre_trade_limits_v1.yaml").read_bytes()
    _execute(tmp_path, _book())
    ledger_limits = yaml.safe_load((execution.forward_track(tmp_path).ledger_root / "configs" / "pre_trade_limits_v1.yaml").read_text(encoding="utf-8"))
    ceiling = execution.load_execution_config()[1]["position_limits"]["ledger_absolute_exposure_ceiling_eur"]
    assert ledger_limits["max_position_exposure"] == ceiling
    live = yaml.safe_load(live_before.decode("utf-8"))
    assert live["max_position_exposure"] == 25000  # configs/pre_trade_limits_v1.yaml is untouched
    assert (execution.CONFIG_DIR / "pre_trade_limits_v1.yaml").read_bytes() == live_before


def test_the_b2_core_fills_above_the_old_absolute_exposure_limit(monkeypatch, tmp_path: Path) -> None:
    ready = _ready(monkeypatch, tmp_path)
    path = execution.forward_track(tmp_path).ledger_root / "configs" / "pre_trade_limits_v1.yaml"
    limits = yaml.safe_load(path.read_text(encoding="utf-8"))
    limits["max_order_value"] = 1_000_000  # leave only the position rule under test
    path.write_text(yaml.safe_dump(limits), encoding="utf-8")
    _execute(tmp_path, ready)
    (core,) = _by(_records(tmp_path), "B2", "VWCE", "filled")
    assert Decimal(core["quantity"]) * Decimal(core["fill_price"]) > Decimal("25000")  # EUR 32000 core: the old absolute check blocked it


# (6) minimum trade EUR 500 -----------------------------------------------------------------------------------------------


def test_the_minimum_trade_is_five_hundred_euro_and_smaller_orders_are_skipped(monkeypatch, tmp_path: Path) -> None:
    assert execution.load_execution_config()[1]["min_trade_value_eur"] == 500.0
    payload = _config()
    payload["initial_virtual_cash_eur"] = 5000.0  # AAA at 8 percent = EUR 400 (below the minimum), BBB at 20 percent = EUR 1000
    config_path = _write_config(tmp_path, payload, "small.yaml")
    known_at = stage_a._NOW - timedelta(minutes=5)
    rows = stage_a._rows(known_at)
    board = stage_a._scoreboard(rows, known_at)
    board["instrument_currency"] = "EUR"
    result = stage_a._run_fixture(monkeypatch, tmp_path, rows, board, stage_a._NOW + timedelta(seconds=1), config_path=config_path)
    assert result.status == "available"
    _allow(tmp_path)
    _execute(tmp_path, _book(), config_path=config_path)
    plan = _plan_for(tmp_path, "B1")
    assert not _intents(plan, "AAA") and any(item["instrument_id"] == "AAA" for item in plan["within_tolerance"])
    (etf,) = _intents(plan, "BBB")
    assert Decimal(etf["planned_quantity"]) * Decimal(etf["sizing_price"]) >= Decimal("500")
    assert not _by(_records(tmp_path), "B1", "AAA")
