"""SDD C7: the session-opens job and the fills that use its observed opens (forward track only)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import exchange_calendars as xcals
import pandas as pd
import pytest

from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.data.providers import ProviderResult
from etf_cockpit.portfolio import paper_bots_execution as execution
from etf_cockpit.portfolio.paper_trading import PaperLedger, ShadowCostPolicy
from tests._pit_listing import verified_listing_history  # noqa: F401 (autouse)
from tests.test_paper_bots_corporate_actions import _ledger, _sync
from tests.test_paper_bots_execution import (
    RUN_AT, SESSIONS, _book, _by, _execute, _ready, _records, _write_fx,
)
from tests.test_paper_trading import _proposal

pytestmark = pytest.mark.usefixtures("readiness_pass")

FILL_DAY = date(2026, 10, 15)  # first session after the 2026-10-14 decisions (CEST: the job observes at 13:45 UTC)
JOB_AT = datetime(2026, 10, 15, 13, 45, tzinfo=timezone.utc)
BASE = {"VWCE": 100.0, "AAA": 21.0, "BBB": 22.0, "BAD": 23.0}
OBSERVED = Decimal("1.05")  # observed opens differ from the nightly daily opens, so the test can tell them apart


def _daily_open(instrument: str, day: date) -> float:
    return BASE[instrument] * (1 + 0.001 * SESSIONS.index(day))


def _observation(instrument: str, day: date, **overrides) -> dict:
    row = {"instrument_id": instrument, "session_date": day, "open": float(Decimal(str(_daily_open(instrument, day))) * OBSERVED),
           "volume": 500.0, "currency": "EUR", "dividends": 0.0, "stock_splits": 0.0, "actions_evidenced": True,
           "provider_symbol": instrument, "source": "yfinance", "provider": "yfinance",
           "known_at": datetime.combine(day, time(13, 45), tzinfo=timezone.utc).isoformat()}
    row.update(overrides)
    return row


def _observations(*, drop: set[tuple[str, date]] = frozenset(), overrides: dict | None = None) -> pd.DataFrame:
    rows = [
        _observation(instrument, day, **(overrides or {}).get((instrument, day), {}))
        for instrument in BASE for day in SESSIONS if FILL_DAY <= day < RUN_AT.date() and (instrument, day) not in drop
    ]
    return pd.DataFrame(rows)


def _observed_book(observations: pd.DataFrame, **book_options) -> execution.PriceBook:
    daily = _book(**book_options)._frame.drop(columns=["_instrument"])
    return execution.PriceBook(daily, known_at=RUN_AT, observations=observations)


def _fill_events(root: Path) -> list[dict]:
    ledger_root = execution.forward_track(root).ledger_root
    events = []
    for path in sorted((ledger_root / "data" / "operations" / "paper" / "accounts").iterdir()):
        events += [item for item in PaperLedger(ledger_root, account_id=path.name)._read_events()
                   if item["event_type"] == "fill_recorded"]
    return events


class _FakeProvider:
    """Records the requested ids; returns the bar of the day before (dropped) and the observed bar of the session."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], date, date]] = []

    def fetch_prices(self, symbols, start_date, end_date):
        self.calls.append((tuple(symbols), start_date, end_date))
        rows = []
        for instrument in symbols:
            for day in (start_date - timedelta(days=1), start_date):
                observed = _observation(instrument, FILL_DAY)
                rows.append({"date": day, "etf_id": instrument, "open": observed["open"] if day == start_date else 1.0,
                             "high": 1.0, "low": 1.0, "close": 1.0, "adjusted_close": 1.0, "volume": 500.0,
                             "currency": "EUR", "provider_symbol": instrument, "source": "yfinance", "is_adjusted": True,
                             "dividends": 0.0, "stock_splits": 0.0, "capital_gains": 0.0})
        return ProviderResult("yfinance", "prices", "ok", "fake", pd.DataFrame(rows))


@pytest.fixture
def job(monkeypatch):
    from etf_cockpit.application import morning_fill

    provider = _FakeProvider()
    monkeypatch.setattr(morning_fill, "_provider", lambda root: provider)
    enabled = SimpleNamespace(controls=SimpleNamespace(paper=SimpleNamespace(enabled=True)))
    monkeypatch.setattr(morning_fill, "load_settings_bundle", lambda root: enabled)
    monkeypatch.setattr(morning_fill, "load_paper_controls_status",
                        lambda root, account: {"status": "available", "kill_switch_active": False})
    return SimpleNamespace(module=morning_fill, provider=provider)


def _stored(root: Path) -> pd.DataFrame:
    return pd.read_parquet(root / "data" / "validated" / "prices" / "session_opens.parquet")


def test_the_fill_uses_the_open_the_job_observed_before_the_fill_time(monkeypatch, tmp_path: Path, job) -> None:
    _ready(monkeypatch, tmp_path)
    daily = _book()._frame.drop(columns=["_instrument"])
    # The nightly refresh stamps each daily bar hours after the 15:20 UTC fill time of its session.
    daily["known_at"] = [(day + pd.Timedelta(hours=22)).isoformat() + "Z" for day in daily["date"]]
    prices = tmp_path / "data" / "validated" / "prices" / "prices_daily.parquet"
    prices.parent.mkdir(parents=True, exist_ok=True)
    daily.to_parquet(prices)

    result = job.module.run_morning_fill(tmp_path, now=JOB_AT)
    assert result["status"] == "available", result
    assert job.provider.calls == [(("AAA", "BBB", "VWCE"), FILL_DAY, FILL_DAY + timedelta(days=1))]
    stored = _stored(tmp_path)
    assert set(stored["session_date"].astype(str)) == {FILL_DAY.isoformat()}  # the bar of the day before is dropped
    assert set(pd.to_datetime(stored["known_at"], utc=True)) == {pd.Timestamp(JOB_AT)}

    run = execution.run_paper_bot_execution(RUN_AT, root=tmp_path, now=RUN_AT)
    filled = _by(_records(tmp_path), "B1", status="filled")
    assert {item["instrument_id"] for item in filled} == {"AAA", "BBB"}, (run.reason, run.warnings)
    for item in filled:
        assert item["session"] == FILL_DAY.isoformat()
        assert float(item["reference_open"]) == pytest.approx(_observation(item["instrument_id"], FILL_DAY)["open"])
    assert {event["payload"].get("price_source") for event in _fill_events(tmp_path)} == {"session_open_observation"}

    before = sorted(_records(tmp_path), key=lambda item: item["record_id"])
    daily["open"] = daily["open"] * 2  # a later nightly restamp revises the daily bars
    daily["known_at"] = (RUN_AT + timedelta(hours=1)).isoformat()
    daily.to_parquet(prices)
    again = execution.run_paper_bot_execution(RUN_AT + timedelta(hours=2), root=tmp_path, now=RUN_AT + timedelta(hours=2))
    assert again.appended == 0
    assert sorted(_records(tmp_path), key=lambda item: item["record_id"]) == before


@pytest.mark.parametrize("late", [True, False], ids=["observed-after-fill-time", "no-observation"])
def test_without_an_observation_known_at_the_fill_time_the_order_misses_for_good(monkeypatch, tmp_path: Path, late) -> None:
    _ready(monkeypatch, tmp_path)
    after_fill = datetime(2026, 10, 15, 15, 30, tzinfo=timezone.utc).isoformat()
    observations = (_observations(overrides={("AAA", FILL_DAY): {"known_at": after_fill}}) if late
                    else _observations(drop={("AAA", FILL_DAY)}))
    _execute(tmp_path, _observed_book(observations))
    aaa = _by(_records(tmp_path), "B1", "AAA")
    assert [(item["status"], item["reason"], item["session"]) for item in aaa] == [
        ("missed", "price_not_known_at_fill_time", FILL_DAY.isoformat()),
    ]  # terminal: the valid observation of the next session is never used for it
    assert _by(_records(tmp_path), "B1", "BBB", "filled")


def test_a_split_observed_on_the_fill_session_is_a_per_order_miss(monkeypatch, tmp_path: Path) -> None:
    _ready(monkeypatch, tmp_path)
    _execute(tmp_path, _observed_book(_observations(overrides={("AAA", FILL_DAY): {"stock_splits": 2.0}})))
    records = _records(tmp_path)
    assert [item["reason"] for item in _by(records, "B1", "AAA")] == ["split_on_fill_session"]
    assert _by(records, "B1", "BBB", "filled")
    assert not [item for item in records if item["status"] == "failed"]


def test_a_split_not_known_at_the_fill_time_is_a_per_order_miss_not_a_stage_failure(monkeypatch) -> None:
    days = [date(2026, 10, 14), date(2026, 10, 15)]
    rows = [{"instrument_id": "VWCE", "date": day, "open": 50.0, "close": 50.0, "adjusted_close": 50.0, "currency": "EUR",
             "volume": 1000.0, "dividends": 0.0, "stock_splits": 2.0 if day == days[1] else 0.0, "actions_evidenced": True,
             "available_at": f"{day}T22:00:00Z"} for day in days]
    book = execution.PriceBook(pd.DataFrame(rows), known_at=RUN_AT)
    context = SimpleNamespace(book=book, config={"_fill_time": time(15, 20)}, policy=ShadowCostPolicy(),
                              track=SimpleNamespace(ledger_root=Path(".")), warnings=[], fx_cache={})
    ledger = SimpleNamespace(trade_rows=lambda: [], snapshot=lambda: SimpleNamespace(positions=[]))
    monkeypatch.setattr(execution, "_record", lambda *args, **kwargs: {"status": args[4], "reason": args[5]})
    intent = {"instrument_id": "VWCE", "intent_id": "split-order", "sizing_price": "100", "side": "buy",
              "planned_quantity": "10", "currency": "EUR", "quantity_basis_date": days[0].isoformat()}
    record = execution._attempt(context, ledger, {}, intent, days[1], final_session=True, awaits_settlement=False)
    assert record == {"status": "missed", "reason": "split_on_fill_session"}


def test_the_b0_shadow_buys_at_the_observed_open_and_its_valuation_does_not_flag_a_revision(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_bots_report import build_paper_bots_overview

    _ready(monkeypatch, tmp_path)
    book = _observed_book(_observations())
    _execute(tmp_path, book)
    overview = build_paper_bots_overview(tmp_path, as_of=RUN_AT, price_book=book)
    bot = next(item for item in overview["forward"]["bots"] if item["family"] == "B0")
    assert bot["status"] == "available", bot["reason"]
    shadow = PaperLedger(execution.forward_track(tmp_path).ledger_root, account_id=execution.shadow_id_for(bot["bot_id"]))
    flows = [item["payload"] for item in shadow._read_events() if item["event_type"] == "shadow_flow_executed"]
    assert flows
    assert Decimal(flows[0]["executed_open"]) == Decimal(str(_observation("VWCE", date.fromisoformat(flows[0]["executed_session"]))["open"]))
    assert flows[0]["open_source"] == "session_open_observation"


def test_the_legacy_fill_basis_check_skips_a_fill_priced_from_an_observation(tmp_path: Path) -> None:
    from tests.test_paper_bots_corporate_actions import DAYS, _actions, _at, _book as _action_book
    from etf_cockpit.portfolio.paper_trading import _digest

    ledger = _ledger(tmp_path)
    proposal = _proposal(quantity_delta=5, source="observed-open-buy")
    proposal["instrument_id"] = proposal["input_material"]["instrument_id"] = "VWCE"
    proposal["input_checksum"] = _digest(proposal["input_material"])
    proposal["proposal_id"] = "proposal_" + proposal["input_checksum"][:20]
    proposal.pop("decision_checksum")
    proposal["decision_checksum"] = _digest(proposal)
    order = ledger.accept_proposal(proposal, execution_price=97, quote_currency="EUR", occurred_at=_at(DAYS[1], 15))
    # The observed open (97) differs from the daily open of the session; the fill names its price source.
    ledger.record_fill(str(order["order_id"]), quantity=5, price=97, reference_price=97, occurred_at=_at(DAYS[1], 15),
                       price_source="session_open_observation")
    book = _action_book(dividend=0, split=2)
    _sync(tmp_path, ledger, book)
    assert [item["payload"]["split_ratio"] for item in _actions(ledger)] == [2.0]


@pytest.mark.parametrize("day", [date(2026, 1, 15), date(2026, 7, 15)], ids=["winter", "summer"])
def test_the_fill_time_is_after_every_open_and_before_the_xetra_close(day: date) -> None:
    _, config = execution.load_execution_config()
    fill = pd.Timestamp(execution._fill_datetime(config, day))
    for exchange in ("XNYS", "XETR"):
        assert xcals.get_calendar(exchange).session_open(day) < fill, exchange
    assert fill < xcals.get_calendar("XETR").session_close(day)


def test_the_fill_fx_rate_is_the_one_known_at_the_fill_time(monkeypatch, tmp_path: Path) -> None:
    from tests.test_paper_bots_execution import _decisions, _allow

    assert _decisions(monkeypatch, tmp_path, eur=False).status == "available"  # AAA is quoted in USD
    _allow(tmp_path)
    _write_fx(tmp_path, usd_per_eur=1.25)
    fx = pd.read_parquet(tmp_path / "data" / "clean" / "fx.parquet")
    late = {"as_of_date": FILL_DAY.isoformat(), "base_currency": "EUR", "quote_currency": "USD", "rate": 2.0,
            "source": "ECB", "ingested_at": f"{FILL_DAY}T16:00:00Z"}  # published after the 15:20 UTC fill
    fx = pd.concat([fx.loc[fx["as_of_date"] != FILL_DAY.isoformat()], pd.DataFrame([late])], ignore_index=True)
    fx.to_parquet(tmp_path / "data" / "clean" / "fx.parquet")
    observations = _observations(overrides={("AAA", FILL_DAY): {"currency": "USD"}})
    _execute(tmp_path, _observed_book(observations, currencies={"AAA": "USD"}))
    filled = _by(_records(tmp_path), "B1", "AAA", "filled")
    assert filled and Decimal(filled[0]["fx_rate"]) == Decimal("0.8")


@pytest.mark.parametrize(
    ("now", "reason"),
    [
        (datetime(2026, 10, 17, 13, 45, tzinfo=timezone.utc), "not_a_session"),  # Saturday
        (datetime(2026, 10, 15, 15, 20, tzinfo=timezone.utc), "fill_time_passed"),
        (datetime(2026, 10, 15, 18, 0, tzinfo=timezone.utc), "fill_time_passed"),
    ],
)
def test_the_job_observes_only_on_a_session_before_the_fill_time(tmp_path: Path, job, now, reason) -> None:
    result = job.module.run_morning_fill(tmp_path, now=now)
    assert (result["status"], result["reason"]) == ("skipped", reason)
    assert job.provider.calls == []
    assert not (tmp_path / "data" / "validated" / "prices" / "session_opens.parquet").exists()


@pytest.mark.parametrize(
    ("enabled", "controls", "reason"),
    [
        (False, {"status": "available", "kill_switch_active": False}, "paper_disabled"),
        (True, {"status": "available", "kill_switch_active": True}, "paper_kill_switch_active"),
        (True, {"status": "unavailable", "kill_switch_active": None}, "paper_controls_unavailable"),
    ],
)
def test_paper_disabled_or_the_kill_switch_means_no_fetch(monkeypatch, tmp_path: Path, job, enabled, controls, reason) -> None:
    settings = SimpleNamespace(controls=SimpleNamespace(paper=SimpleNamespace(enabled=enabled)))
    monkeypatch.setattr(job.module, "load_settings_bundle", lambda root: settings)
    monkeypatch.setattr(job.module, "load_paper_controls_status", lambda root, account: controls)
    result = job.module.run_morning_fill(tmp_path, now=JOB_AT)
    assert (result["status"], result["reason"], result["execution_allowed"]) == ("skipped", reason, False)
    assert job.provider.calls == []


def test_the_job_requests_the_latest_targets_and_the_held_positions_and_only_appends(monkeypatch, tmp_path: Path, job) -> None:
    _ready(monkeypatch, tmp_path)
    _execute(tmp_path, _observed_book(_observations()))  # the bots now hold AAA, BBB and VWCE
    track = execution.forward_track(tmp_path)
    later = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)
    with TransactionalStore(track.store_root) as store:
        newer = []
        for item in store.list(track.decision_type):
            payload = {**item.payload, "decision_id": "next-" + item.payload["decision_id"][:20],
                       "as_of": later.isoformat(), "known_at": later.isoformat(), "targets": {"VWCE": 1.0}}
            newer.append((track.decision_type, payload["decision_id"], payload))
        store.put_many(newer, immutable=True)
    assert execution.pending_fill_instruments(tmp_path, later + timedelta(minutes=1)) == ["AAA", "BBB", "VWCE"]

    session = date(2026, 11, 2)
    first = job.module.run_morning_fill(tmp_path, now=datetime(2026, 11, 2, 14, 45, tzinfo=timezone.utc))
    second = job.module.run_morning_fill(tmp_path, now=datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc))
    assert first["status"] == second["status"] == "available"
    assert [call[0] for call in job.provider.calls] == [("AAA", "BBB", "VWCE")] * 2
    stored = _stored(tmp_path)
    assert len(stored) == 6 and set(stored["session_date"].astype(str)) == {session.isoformat()}
    assert stored["known_at"].nunique() == 2  # both observations are kept; nothing is replaced


def test_the_script_prints_json_and_exits_zero_only_on_available_or_skipped(monkeypatch, tmp_path: Path, capsys) -> None:
    import importlib
    import json

    from etf_cockpit.application import morning_fill

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    module = importlib.import_module("run_morning_fill")
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(tmp_path))  # restored after the test; the script sets it
    for status, code in (("available", 0), ("skipped", 0), ("failed", 1)):
        monkeypatch.setattr(morning_fill, "run_morning_fill", lambda root, status=status: {"status": status})
        assert module.main(["--root", str(tmp_path)]) == code
        assert json.loads(capsys.readouterr().out)["status"] == status
