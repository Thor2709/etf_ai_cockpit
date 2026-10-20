"""Issue #945 stage B: paper execution, performance, the read-only Bots view data and the historical replay."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
import yaml

from etf_cockpit.data.local_storage import StorageSchemaError, TransactionalStore
from etf_cockpit.portfolio import paper_bots, paper_bots_execution as execution
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError
from tests.test_paper_bots import _NOW, _rows, _run_fixture, _scoreboard

DECISION_DAY = date(2026, 10, 14)  # _NOW is 12:00 UTC on this Wednesday; the recorder only accepts the current day
SESSIONS = [day.date() for day in pd.bdate_range("2026-10-01", "2026-12-31")]
RUN_AT = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _vwce_columns() -> dict[str, object]:
    return {"provider_symbol": "VWCE.DE", "source": "yfinance", "is_adjusted": True, "stock_splits": 0.0,
            "dividends": 0.0, "capital_gains": 0.0}


def _book(
    *, opens: dict[str, dict[date, float]] | None = None, volume: dict[tuple[str, date], float] | None = None,
    missing: set[tuple[str, date]] | None = None, sessions: list[date] | None = None, known_at: datetime | None = None,
    base: dict[str, float] | None = None,
) -> execution.PriceBook:
    base = base or {"VWCE": 100.0, "AAA": 21.0, "BBB": 22.0, "BAD": 23.0}
    rows = []
    for instrument, level in base.items():
        for index, day in enumerate(sessions or SESSIONS):
            if (instrument, day) in (missing or set()):
                continue
            open_price = (opens or {}).get(instrument, {}).get(day, level * (1 + 0.001 * index))
            row = {"etf_id": instrument, "date": pd.Timestamp(day), "open": open_price, "high": open_price * 1.01,
                   "low": open_price * 0.99, "close": open_price * 1.002, "adjusted_close": open_price * 1.002,
                   "volume": (volume or {}).get((instrument, day), 1000.0), "currency": "EUR"}
            if instrument == "VWCE":
                row.update(_vwce_columns())
            rows.append(row)
    return execution.PriceBook(pd.DataFrame(rows), known_at=known_at or RUN_AT)


def _decisions(monkeypatch, tmp_path: Path, *, eur: bool = True, mutate=None) -> paper_bots.PaperBotRunResult:
    known_at = _NOW - timedelta(minutes=5)
    rows = _rows(known_at)
    board = _scoreboard(rows, known_at)
    if eur:
        board["instrument_currency"] = "EUR"
    if mutate is not None:
        mutate(board)
    return _run_fixture(monkeypatch, tmp_path, rows, board, _NOW + timedelta(seconds=1))


def _execute(tmp_path: Path, book: execution.PriceBook, *, as_of: datetime = RUN_AT, config_path: Path | None = None) -> execution.ExecutionRunResult:
    return execution.run_paper_bot_execution(as_of, root=tmp_path, price_book=book, now=as_of, config_path=config_path)


def _records(tmp_path: Path, track=None) -> list[dict]:
    track = track or execution.forward_track(tmp_path)
    try:
        with TransactionalStore(track.store_root, read_only=True) as store:
            return [dict(item.payload) for item in store.list(track.record_type)]
    except StorageSchemaError:  # nothing was ever stored
        return []


def _bot(result: paper_bots.PaperBotRunResult, family: str) -> dict:
    return next(item for item in result.records if item["bot_family"] == family)


def _allow(tmp_path: Path, track=None, extra: tuple[str, ...] = ("AAA", "BBB", "BAD")) -> None:
    """The test universe has no AAA/BBB: give the bot ledger root the same allowlist a real universe would give."""

    track = track or execution.forward_track(tmp_path)
    limits = yaml.safe_load((execution.CONFIG_DIR / "pre_trade_limits_v1.yaml").read_text(encoding="utf-8"))
    limits["allowed_instruments"] = sorted({"VWCE", *extra})
    target = track.ledger_root / "configs" / "pre_trade_limits_v1.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(limits), encoding="utf-8")


def _ready(monkeypatch, tmp_path: Path, **book_options) -> execution.PriceBook:
    """Stage A decisions recorded for 2026-10-14 and the bot ledger allowlist that a real universe would give."""

    assert _decisions(monkeypatch, tmp_path).status == "available"
    _allow(tmp_path)
    return _book(**book_options)


def _by(records: list[dict], family: str, instrument: str | None = None, status: str | None = None) -> list[dict]:
    return [
        item for item in records
        if item["bot_family"] == family and (instrument is None or item["instrument_id"] == instrument)
        and (status is None or item["status"] == status)
    ]


def _plans(tmp_path: Path, track=None) -> list[dict]:
    track = track or execution.forward_track(tmp_path)
    with TransactionalStore(track.store_root, read_only=True) as store:
        return sorted((dict(item.payload) for item in store.list(track.plan_type)), key=lambda item: item["bot_id"])


def test_fills_happen_at_the_next_session_open_never_the_decision_close(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path, opens={"BBB": {date(2026, 10, 15): 40.0, date(2026, 10, 14): 22.0}})
    run = _execute(tmp_path, book)
    assert run.status == "available", (run.reason, run.warnings)
    filled = _by(_records(tmp_path), "B1", "BBB", "filled")
    assert filled
    for item in filled:
        assert item["session"] == "2026-10-15" > DECISION_DAY.isoformat()
        assert Decimal(item["reference_open"]) == Decimal("40.0")  # the open, not the 22.0 decision-day figure
        assert Decimal(item["fill_price"]) > Decimal(item["reference_open"])  # spread and slippage against the order
        assert Decimal(item["fee"]) > 0  # the costs.py commission


def test_no_session_after_the_decision_means_no_fill_and_no_account(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path, sessions=[day for day in SESSIONS if day <= DECISION_DAY])
    run = _execute(tmp_path, book, as_of=datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc))
    assert _records(tmp_path) == []
    assert run.appended == 0
    assert not (execution.forward_track(tmp_path).ledger_root / "data").exists()  # not even funded: the order is pending


def test_the_session_of_the_run_itself_is_never_used(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path)
    _execute(tmp_path, book, as_of=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc))
    assert _records(tmp_path) == []  # 2026-10-15 is the run day: its bar is not complete, so nothing fills yet
    _execute(tmp_path, book, as_of=datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc))
    assert {item["session"] for item in _records(tmp_path)} == {"2026-10-15"}


def test_a_decision_known_after_as_of_is_never_executed(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path)
    early = datetime(2026, 10, 14, 11, 0, tzinfo=timezone.utc)  # the snapshot became known at 11:55
    run = _execute(tmp_path, book, as_of=early)
    assert run.status == "unavailable" and run.appended == 0
    assert _records(tmp_path) == []


def test_execution_is_idempotent_and_records_stay_immutable(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path)
    first = _execute(tmp_path, book)
    before = sorted(_records(tmp_path), key=lambda item: item["record_id"])
    assert first.appended == len(before) > 0
    again = _execute(tmp_path, book)
    assert again.appended == 0
    assert sorted(_records(tmp_path), key=lambda item: item["record_id"]) == before
    track = execution.forward_track(tmp_path)
    with TransactionalStore(track.store_root) as store:
        with pytest.raises(Exception):
            store.put_many([(track.record_type, before[0]["record_id"], {**before[0], "status": "missed"})], immutable=True)
    assert all(item["execution_allowed"] is False for item in before)
    ledger = PaperLedger(track.ledger_root, account_id=execution.account_id_for(before[0]["bot_id"]))
    assert ledger.snapshot().reconciliation_status


def test_a_new_score_lineage_is_a_new_bot_with_its_own_account_and_the_old_record_is_untouched(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path)
    _execute(tmp_path, book)
    old = sorted(_records(tmp_path), key=lambda item: item["record_id"])
    other = paper_bots._bot_identity({"family_id": "B1", "name": "x"}, "c" * 64, "d" * 64)
    assert other != old[0]["bot_id"]
    assert execution.account_id_for(other) != execution.account_id_for(old[0]["bot_id"])
    assert execution.shadow_id_for(other) != execution.account_id_for(other)
    _execute(tmp_path, book)
    assert sorted(_records(tmp_path), key=lambda item: item["record_id"]) == old


def test_b0_is_the_vwce_shadow_account_so_its_relative_wealth_is_zero(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_bots_report import build_paper_bots_overview

    book = _ready(monkeypatch, tmp_path)
    _execute(tmp_path, book)
    overview = build_paper_bots_overview(tmp_path, as_of=RUN_AT, price_book=book)
    b0 = next(bot for bot in overview["forward"]["bots"] if bot["family"] == "B0")
    assert b0["status"] == "available", b0["reason"]
    assert b0["metrics"]["compounded_relative_wealth"] == 0.0
    assert b0["metrics"]["period_excess_return"] == 0.0
    assert b0["wealth"] == b0["benchmark_wealth"]
    assert all(value == 0.0 for value in b0["relative_wealth"])
    assert b0["trade_log"] and b0["trade_log"][0]["instrument_id"] == "VWCE" and b0["trade_log"][0]["status"] == "filled"
    # B0 never has a proposal or order of its own: the shadow account accepts none.
    ledger = PaperLedger(execution.forward_track(tmp_path).ledger_root, account_id=execution.shadow_id_for(b0["bot_id"]))
    assert ledger.orders() == ()


def test_a_missed_fill_is_logged_and_lowers_the_invested_share(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_bots_report import build_paper_bots_overview

    normal_root, missed_root = tmp_path / "normal", tmp_path / "missed"
    normal_book = _ready(monkeypatch, normal_root)
    missed_book = _ready(monkeypatch, missed_root, missing={("AAA", date(2026, 10, 15))})
    _execute(normal_root, normal_book)
    _execute(missed_root, missed_book)
    missed = _by(_records(missed_root), "B1", "AAA")
    assert [item["status"] for item in missed] == ["missed"]
    assert "no_session_data" in missed[0]["reason"] and missed[0]["quantity"] == "0"
    normal = build_paper_bots_overview(normal_root, as_of=RUN_AT, price_book=normal_book)["forward"]
    broken = build_paper_bots_overview(missed_root, as_of=RUN_AT, price_book=missed_book)["forward"]
    b1_normal = next(bot for bot in normal["bots"] if bot["family"] == "B1")
    b1_missed = next(bot for bot in broken["bots"] if bot["family"] == "B1")
    assert b1_missed["missed_fills"] == 1 and b1_missed["metrics"]["missed_orders"] == 1
    assert any(row["status"] == "missed" and row["instrument_id"] == "AAA" for row in b1_missed["trade_log"])
    assert b1_missed["metrics"]["traded_notional_eur"] < b1_normal["metrics"]["traded_notional_eur"]
    assert b1_missed["metrics"]["final_value_eur"] != b1_normal["metrics"]["final_value_eur"]  # the idle cash changes wealth
    ledger = PaperLedger(execution.forward_track(missed_root).ledger_root, account_id=execution.account_id_for(b1_missed["bot_id"]))
    assert ledger.snapshot().cash > 4_000  # the unspent half stays in the account


@pytest.mark.parametrize(
    ("book_options", "reason"),
    [
        ({"volume": {("AAA", date(2026, 10, 15)): 0.0}}, "zero_volume_session"),
        ({"opens": {"AAA": {date(2026, 10, 15): float("nan")}}}, "invalid_open_price"),
        ({"missing": {("AAA", date(2026, 10, 15))}}, "no_session_data"),
    ],
    ids=["zero-volume", "invalid-open", "provider-outage"],
)
def test_unfillable_sessions_are_logged_as_missed_with_a_reason(monkeypatch, tmp_path: Path, book_options, reason) -> None:
    book = _ready(monkeypatch, tmp_path, **book_options)
    _execute(tmp_path, book)
    item = _by(_records(tmp_path), "B1", "AAA")[0]
    assert item["status"] == "missed" and reason in item["reason"] and item["fill_id"] is None
    assert _by(_records(tmp_path), "B1", "BBB", "filled")  # the other order is unaffected


def test_no_session_data_after_the_grace_period_is_a_provider_outage_for_every_order(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path, sessions=[day for day in SESSIONS if day <= DECISION_DAY])
    run = _execute(tmp_path, book, as_of=datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc))
    records = _records(tmp_path)
    assert records and all(item["status"] == "missed" and "provider_outage" in item["reason"] for item in records)
    assert run.status in {"available", "partial"}


def test_a_gate_failed_instrument_is_never_bought(monkeypatch, tmp_path: Path) -> None:
    def fail_gate(board: pd.DataFrame) -> None:
        board.loc[board["instrument_id"] == "AAA", "research_promotion_allowed"] = False

    assert _decisions(monkeypatch, tmp_path, mutate=fail_gate).status == "available"
    _allow(tmp_path)
    _execute(tmp_path, _book())
    traded = {(item["bot_family"], item["instrument_id"]) for item in _records(tmp_path)}
    assert not any(instrument in {"AAA", "BAD"} for _family, instrument in traded)
    assert ("B1", "BBB") in traded
    assert _by(_records(tmp_path), "B1", "BBB", "filled")  # missed records alone must not satisfy this test
    track = execution.forward_track(tmp_path)
    for record in _records(tmp_path):
        ledger = PaperLedger(track.ledger_root, account_id=execution.account_id_for(record["bot_id"]))
        assert {position.instrument_id for position in ledger.snapshot().positions} <= {"BBB", "VWCE"}


def test_an_order_above_the_owner_hard_limit_is_reduced_to_fit_it_not_missed(monkeypatch, tmp_path: Path) -> None:
    def fail_gate(board: pd.DataFrame) -> None:
        board.loc[board["instrument_id"] == "AAA", "research_promotion_allowed"] = False

    assert _decisions(monkeypatch, tmp_path, mutate=fail_gate).status == "available"  # B1 then puts 100% into BBB
    _allow(tmp_path)
    _execute(tmp_path, _book())
    track = execution.forward_track(tmp_path)
    limit = Decimal(str(yaml.safe_load((track.ledger_root / "configs" / "pre_trade_limits_v1.yaml").read_text(encoding="utf-8"))["max_order_value"]))
    filled = _by(_records(tmp_path), "B1", "BBB", "filled")
    assert filled and not _by(_records(tmp_path), "B1", "BBB", "missed")
    for item in filled:
        assert Decimal(item["quantity"]) * Decimal(item["fill_price"]) <= limit
        assert Decimal(item["quantity"]) < Decimal(item["planned_quantity"])
        assert "order-value limit" in item["reason"]


def test_the_independent_allowlist_still_blocks_an_instrument_outside_the_universe(monkeypatch, tmp_path: Path) -> None:
    assert _decisions(monkeypatch, tmp_path).status == "available"  # no _allow(): AAA and BBB are not in the configured universe
    _execute(tmp_path, _book())
    blocked = _by(_records(tmp_path), "B1", "BBB")
    assert blocked and blocked[0]["status"] == "missed" and "allowlist" in blocked[0]["reason"]
    path = execution.forward_track(tmp_path).ledger_root / "configs" / "pre_trade_limits_v1.yaml"
    limits = yaml.safe_load(path.read_text(encoding="utf-8"))
    owner = yaml.safe_load((execution.CONFIG_DIR / "pre_trade_limits_v1.yaml").read_text(encoding="utf-8"))
    for key in ("max_order_value", "max_position_exposure", "max_daily_turnover"):
        assert limits[key] == owner[key]  # the numeric limits are the owner's, unchanged


def test_a_non_eur_quote_is_logged_not_traded(monkeypatch, tmp_path: Path) -> None:
    assert _decisions(monkeypatch, tmp_path, eur=False).status == "available"  # AAA is quoted in USD in the fixture
    _allow(tmp_path)
    _execute(tmp_path, _book())
    usd = _by(_records(tmp_path), "B1", "AAA")[0]
    assert usd["status"] == "missed" and "non_eur_quote" in usd["reason"]
    assert _by(_records(tmp_path), "B1", "BBB", "filled")


def test_orders_are_sized_from_decision_time_prices_not_from_the_fill_session(monkeypatch, tmp_path: Path) -> None:
    quiet_root, gap_root = tmp_path / "quiet", tmp_path / "gap"
    quiet = _ready(monkeypatch, quiet_root)
    gap = _ready(monkeypatch, gap_root, opens={"AAA": {date(2026, 10, 15): 30.0}})  # +40% gap at the fill session
    _execute(quiet_root, quiet)
    _execute(gap_root, gap)
    for left, right in zip(_plans(quiet_root), _plans(gap_root), strict=True):
        assert [(i["instrument_id"], i["planned_quantity"]) for i in left["intents"]] == [
            (i["instrument_id"], i["planned_quantity"]) for i in right["intents"]
        ]


def test_the_sizing_fallback_never_uses_the_decision_day_close() -> None:
    from types import SimpleNamespace

    def price(decision_day_close: float | None) -> tuple[Decimal, str] | None:
        days = [date(2026, 10, 12), date(2026, 10, 13)] + ([DECISION_DAY] if decision_day_close else [])
        rows = [{"etf_id": "AAA", "date": pd.Timestamp(day), "open": 20.0, "high": 21.0, "low": 19.0, "close": 20.5,
                 "adjusted_close": 20.5, "volume": 1000.0, "currency": "EUR"} for day in days]
        if decision_day_close:
            rows[-1]["close"] = decision_day_close
        context = SimpleNamespace(book=execution.PriceBook(pd.DataFrame(rows), known_at=RUN_AT), config={"sizing_price_max_age_days": 7})
        return execution._sizing_price(context, {"prices_used": {}}, "AAA", DECISION_DAY)

    assert price(None) == price(99.0) == (Decimal("20.5"), "2026-10-13")  # an injected decision-day close changes nothing


def test_a_lost_record_write_is_recovered_from_the_ledger_not_ordered_twice(monkeypatch, tmp_path: Path) -> None:
    clean_root, faulty_root = tmp_path / "clean", tmp_path / "faulty"
    clean_book = _ready(monkeypatch, clean_root)
    faulty_book = _ready(monkeypatch, faulty_root)
    assert _execute(clean_root, clean_book).status == "available"
    real_store = execution._store_record
    failures = []

    def flaky(context, record):
        if record["status"] == "filled" and not failures:
            failures.append(record["intent_id"])
            raise OSError("record store write lost after the ledger fill")
        real_store(context, record)

    monkeypatch.setattr(execution, "_store_record", flaky)
    _execute(faulty_root, faulty_book)
    assert failures
    monkeypatch.setattr(execution, "_store_record", real_store)
    _execute(faulty_root, faulty_book)

    def view(root: Path) -> tuple[list, list]:
        track = execution.forward_track(root)
        records = sorted((r["bot_id"], r["instrument_id"], r["side"], r["status"], r["quantity"], r["fill_id"]) for r in _records(root, track))
        fills = sorted(
            (account, row["paper_trade_id"], row["quantity"])
            for account in {execution.account_id_for(r["bot_id"]) for r in _records(root, track)}
            for row in PaperLedger(track.ledger_root, account_id=account).trade_rows()
        )
        return records, fills

    assert view(faulty_root) == view(clean_root)  # one fill per intent, the lost record rebuilt from the ledger
    fills = view(faulty_root)[1]
    assert len({fill_id for _, fill_id, _ in fills}) == len(fills)


def test_the_expiry_reference_lets_a_simulated_session_accept_a_proposal(tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_trading import _digest
    from tests.test_paper_trading import _proposal

    def expired(source: str) -> dict:
        proposal = _proposal(source=source)
        proposal["expires_at"] = "2020-01-02T00:00:00+00:00"
        proposal["decision_checksum"] = _digest({key: value for key, value in proposal.items() if key != "decision_checksum"})
        return proposal

    ledger = PaperLedger(tmp_path)
    ledger.open_account(initial_cash=10_000, occurred_at=datetime(2019, 12, 1, tzinfo=timezone.utc))
    with pytest.raises(PaperLedgerError, match="expired"):
        ledger.accept_proposal(expired("real clock"), execution_price=10)
    order = ledger.accept_proposal(
        expired("simulated clock"), execution_price=10, occurred_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expiry_reference=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    assert order["status"] == "accepted"
    with pytest.raises(PaperLedgerError, match="timezone"):
        ledger.accept_proposal(expired("naive clock"), execution_price=10, expiry_reference=datetime(2020, 1, 1))


def test_bars_after_the_run_cutoff_change_nothing(monkeypatch, tmp_path: Path) -> None:
    short_root, long_root = tmp_path / "short", tmp_path / "long"
    short = _ready(monkeypatch, short_root, sessions=[day for day in SESSIONS if day < date(2026, 10, 30)])
    longer = _ready(monkeypatch, long_root)
    _execute(short_root, short)
    _execute(long_root, longer)
    key = lambda item: (item["bot_family"], item["instrument_id"], item["side"], item["session"], item["status"])  # noqa: E731
    left = sorted(_records(short_root), key=key)
    right = sorted(_records(long_root), key=key)
    assert [(key(i), i["fill_price"], i["quantity"]) for i in left] == [(key(i), i["fill_price"], i["quantity"]) for i in right]


def _record_month(
    monkeypatch, root: Path, history: list[dict], board: pd.DataFrame, now: datetime, config_path: Path | None = None
) -> paper_bots.PaperBotRunResult:
    """Run the stage A recorder at an injected clock (the shared fixture helper is pinned to the October day)."""

    import hashlib
    import json

    derived = root / "data" / "derived"
    derived.mkdir(parents=True, exist_ok=True)
    payload = board.to_parquet(index=False)
    (derived / "scoreboard.parquet").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    with TransactionalStore(root) as store:
        for row in history:
            binding = {
                "schema_version": "scoreboard_publication_binding.v1", "run_id": str(row["run_id"]),
                "score_snapshot_hash": str(row["snapshot_hash"]), "score_completed_at": str(row["run_completed_at"]),
                "known_at": str(row["run_completed_at"]), "scoreboard_sha256": digest, "execution_allowed": False,
            }
            identity = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            store.put_many([(paper_bots.PUBLICATION_BINDING_ENTITY_TYPE, identity, binding)], immutable=True)
    monkeypatch.setattr(paper_bots, "_load_published_score_history", lambda _root: pd.DataFrame(history))
    monkeypatch.setattr(paper_bots, "project_classification_score_frame", lambda frame, *, root: frame)
    return paper_bots.run_paper_bots(
        now + timedelta(seconds=1), root=root, config_path=config_path or paper_bots.PAPER_BOTS_CONFIG_PATH, now=now
    )


def test_a_rebalance_sells_first_and_waits_for_settled_cash_before_buying(monkeypatch, tmp_path: Path) -> None:
    october = _NOW - timedelta(minutes=5)
    rows_october = _rows(october)
    board_october = _scoreboard(rows_october, october)
    board_october["instrument_currency"] = "EUR"
    assert _record_month(monkeypatch, tmp_path, rows_october, board_october, _NOW).status == "available"
    _allow(tmp_path)
    # The fixture instruments are not in the configured universe: give them the venue a real universe entry has.
    monkeypatch.setattr(PaperLedger, "_order_market_terms", lambda self, proposal, instrument_id: ("XETRA", "etf"))
    book = _book(known_at=datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc))
    _execute(tmp_path, book)

    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    november = now - timedelta(minutes=5)
    rows_november = _rows(november, run_id="score-run-nov", snapshot="b")
    board_november = _scoreboard(rows_november, november)
    board_november["instrument_currency"] = "EUR"
    board_november.loc[board_november["instrument_id"] == "AAA", "research_promotion_allowed"] = False  # AAA fails its gate
    assert _record_month(monkeypatch, tmp_path, rows_october + rows_november, board_november, now).status == "available"
    _execute(tmp_path, book, as_of=datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc))

    november_log = [item for item in _records(tmp_path) if item["decision_month"] == "2026-11" and item["bot_family"] == "B1"]
    sale = next(item for item in november_log if item["instrument_id"] == "AAA")
    assert sale["side"] == "sell" and sale["status"] == "filled" and sale["session"] == "2026-11-11"
    assert "exit" in sale["trade_reason"]
    buys = sorted((item for item in november_log if item["instrument_id"] == "BBB"), key=lambda item: (item["session"], item["status"]))
    assert [item["status"] for item in buys][-1] == "filled", [(i["session"], i["status"], i["reason"]) for i in buys]
    assert any(item["status"] == "deferred" for item in buys)  # the sale proceeds were not settled on the first sessions
    assert buys[-1]["session"] > sale["session"]
    assert Decimal(buys[-1]["quantity"]) > 0
    # Nothing was reweighted into other instruments while waiting.
    assert {item["instrument_id"] for item in november_log} == {"AAA", "BBB"}


def _daily(returns: list[float]) -> pd.DataFrame:
    days = pd.bdate_range("2026-01-01", periods=len(returns))
    return pd.DataFrame({"date": days, "period_return": returns})


def _excess_series(monthly_excess: list[float]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily snapshots whose paired monthly relative returns equal ``monthly_excess`` (one calendar month each)."""

    benchmark: list[float] = []
    strategy: list[float] = []
    index = pd.bdate_range("2026-01-01", "2026-12-31")
    months = sorted({day.to_period("M") for day in index})
    for month, excess in zip(months, [0.0, *monthly_excess, 0.0], strict=False):
        days = [day for day in index if day.to_period("M") == month]
        daily = (1.0 + excess) ** (1.0 / len(days)) - 1.0
        benchmark.extend([0.0] * len(days))
        strategy.extend([daily] * len(days))
    frame_b = _daily(benchmark)
    frame_s = _daily(strategy)
    return frame_s.iloc[: len(frame_b)], frame_b


def _exec_config() -> dict:
    return execution.load_execution_config()[1]


def test_an_advantage_is_confirmed_only_when_the_clustered_interval_excludes_zero() -> None:
    from etf_cockpit.portfolio.paper_bots_report import UNCONFIRMED_LABEL, _uncertainty

    consistent = [0.004, 0.0045, 0.0035, 0.005, 0.004, 0.0042, 0.0038, 0.0046, 0.0041, 0.0043]
    strategy, benchmark = _excess_series(consistent)
    confirmed = _uncertainty(strategy, benchmark, _exec_config())
    assert confirmed["status"] == "available" and confirmed["months"] == len(consistent)
    assert confirmed["lower"] > 0 and confirmed["verdict"] != UNCONFIRMED_LABEL
    assert confirmed["bands"] and confirmed["bands"][-1]["lower"] < confirmed["bands"][-1]["relative_wealth"] < confirmed["bands"][-1]["upper"]

    noisy = [0.02, -0.02, 0.015, -0.018, 0.02, -0.015, 0.01, -0.012, 0.02, -0.02]
    strategy, benchmark = _excess_series(noisy)
    unconfirmed = _uncertainty(strategy, benchmark, _exec_config())
    assert unconfirmed["status"] == "available" and unconfirmed["lower"] < 0 < unconfirmed["upper"]
    assert unconfirmed["verdict"] == UNCONFIRMED_LABEL

    strategy, benchmark = _excess_series([0.01, 0.012, 0.011])
    short = _uncertainty(strategy, benchmark, _exec_config())
    assert short["status"] == "unavailable" and short["verdict"] == UNCONFIRMED_LABEL and short["lower"] is None
    assert _uncertainty(None, None, _exec_config())["verdict"] == UNCONFIRMED_LABEL


def _history_with_columns(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        enriched = dict(row)
        enriched["yahoo_ticker"] = "VWCE.DE" if row["instrument_id"] == "VWCE" else f"{row['instrument_id']}.X"
        enriched["research_promotion_allowed"] = row["instrument_id"] in {"AAA", "BBB"}
        enriched["legacy_action"] = row["final_action"]
        result.append(enriched)
    return result


def test_the_historical_replay_is_labelled_stored_separately_and_never_mixed_with_forward(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay
    from etf_cockpit.portfolio.paper_bots_report import REPLAY_LABEL, build_paper_bots_overview

    october = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    november = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    history = _history_with_columns(_rows(october) + _rows(november, run_id="score-run-nov", snapshot="b"))
    as_of = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
    book = _book(known_at=as_of)
    config = _exec_config()
    replay_track = execution.replay_track(tmp_path, config)
    _allow(tmp_path, replay_track)
    result = run_historical_replay(as_of, root=tmp_path, history=pd.DataFrame(history), price_book=book, now=as_of)
    assert result.label == REPLAY_LABEL == "conditional historical simulation"
    assert result.status in {"available", "partial"}, (result.reason, result.warnings)

    # Its own store, entity types and ledgers: the forward record holds nothing from the replay.
    assert replay_track.store_root != execution.forward_track(tmp_path).store_root
    assert replay_track.ledger_root != execution.forward_track(tmp_path).ledger_root
    assert {replay_track.decision_type, replay_track.plan_type, replay_track.record_type}.isdisjoint(
        {paper_bots.DECISION_ENTITY_TYPE, execution.FORWARD_PLAN_TYPE, execution.FORWARD_RECORD_TYPE}
    )
    assert _records(tmp_path) == []
    with TransactionalStore(replay_track.store_root, read_only=True) as store:
        decisions = [dict(item.payload) for item in store.list(replay_track.decision_type)]
    assert {item["decision_month"] for item in decisions} == {"2026-10", "2026-11"}
    assert all(item["track"] == "replay" and item["label"] == REPLAY_LABEL and item["caveat"] for item in decisions)
    replay_records = _records(tmp_path, replay_track)
    assert replay_records and all(item["label"] == REPLAY_LABEL and item["track"] == "replay" for item in replay_records)
    assert {item["session"] for item in replay_records if item["decision_month"] == "2026-10"} <= {"2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"}

    overview = build_paper_bots_overview(tmp_path, as_of=as_of, price_book=book)
    assert overview["forward"]["bots"] == []  # nothing forward was recorded
    replay = overview["replay"]
    assert replay["label"] == REPLAY_LABEL and "point-in-time" in replay["caveat"]
    assert {bot["family"] for bot in replay["bots"]} >= {"B0", "B1", "B2"}
    b1 = next(bot for bot in replay["bots"] if bot["family"] == "B1")
    assert b1["status"] in {"available", "partial"} and b1["wealth"]

    # A second replay run adds nothing (immutable, idempotent).
    again = run_historical_replay(as_of, root=tmp_path, history=pd.DataFrame(history), price_book=book, now=as_of)
    assert again.appended == 0


def test_the_replay_needs_lineage_and_fails_closed_without_history(tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay

    as_of = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
    empty = run_historical_replay(as_of, root=tmp_path, history=pd.DataFrame(), price_book=_book(known_at=as_of), now=as_of)
    assert empty.status == "unavailable" and empty.label == "conditional historical simulation"
    future = run_historical_replay(as_of + timedelta(days=3), root=tmp_path, history=pd.DataFrame(), price_book=_book(), now=as_of)
    assert future.status == "unavailable" and "future" in (future.reason or "")


def test_the_bots_view_reads_both_records_and_labels_the_advantage(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.application.paper_bots_view import load_paper_bots_view
    from etf_cockpit.portfolio.paper_bots_report import UNCONFIRMED_LABEL

    unavailable = load_paper_bots_view(tmp_path, as_of=RUN_AT)
    assert unavailable["forward"]["status"] == "unavailable" and unavailable["forward"]["bots"] == []
    assert unavailable["replay"] is None and unavailable["execution_allowed"] is False
    assert any("60 years" in text for text in unavailable["expectations"])

    book = _ready(monkeypatch, tmp_path)
    _execute(tmp_path, book)
    monkeypatch.setattr(execution.PriceBook, "from_root", classmethod(lambda cls, root, **kwargs: book))
    view = load_paper_bots_view(tmp_path, as_of=RUN_AT)
    forward = view["forward"]
    assert forward["status"] in {"available", "partial"} and {bot["family"] for bot in forward["bots"]} == {"B0", "B1", "B2"}
    for bot in forward["bots"]:
        assert bot["uncertainty"]["verdict"] == UNCONFIRMED_LABEL  # one month of history can never confirm an advantage
        assert bot["execution_allowed"] is False
    assert view["replay"] is None


def test_the_bots_page_builds_read_only_and_shows_the_labels(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.app.pages import paper_bots as page_module
    from etf_cockpit.app.router import PAGES
    from etf_cockpit.app.state import AppState

    def walk(control):
        yield control
        body = getattr(control, "body", None)
        if body is not None and body is not control:
            yield from walk(body)
        for child in getattr(control, "controls", []) or []:
            yield from walk(child)
        content = getattr(control, "content", None)
        if content is not None:
            yield from walk(content)

    report = {
        "status": "available", "track": "forward", "label": None, "caveat": None, "as_of": "2026-10-30T12:00:00Z", "reason": None,
        "bots": [{
            "bot_id": "B1-x", "family": "B1", "name": "Top 10", "score_lineage_version": "v@x", "decisions": 1, "latest_targets": {"BBB": 1.0},
            "status": "available", "reason": None, "dates": ["2026-10-15", "2026-10-16"], "wealth": [10000.0, 10050.0],
            "benchmark_wealth": [10000.0, 10020.0], "relative_wealth": [0.0, 0.003], "drawdown": [0.0, 0.0],
            "metrics": {"final_value_eur": 10050.0, "compounded_relative_wealth": 0.003, "period_excess_return": 0.003,
                        "compounded_relative_wealth_label": "Compounded relative wealth", "max_drawdown": 0.0, "turnover": 1.0, "costs_eur": 12.0},
            "uncertainty": {"status": "unavailable", "verdict": "Unconfirmed advantage", "reason": "Only 0 complete calendar months", "bands": []},
            "trade_log": [{"session": "2026-10-15", "side": "buy", "instrument_id": "BBB", "status": "filled", "quantity": "10",
                           "fill_price": "22.1", "fee": "1", "reason": "enter target weight 100.0%", "outcome_reason": None}],
            "missed_fills": 0, "execution_allowed": False,
        }],
        "execution_allowed": False,
    }
    replay = {**report, "track": "replay", "label": "conditional historical simulation", "caveat": "Fundamentals are not point-in-time."}
    monkeypatch.setattr(
        page_module, "load_paper_bots_view",
        lambda: {"forward": report, "replay": replay, "expectations": ["60 years for a 2% edge"], "execution_allowed": False},
    )
    view = page_module.paper_bots_page(None, AppState(snapshot=None, selected_etf=""))
    texts = [str(getattr(item, "value", "") or "") for item in walk(view)]
    joined = "\n".join(texts)
    assert PAGES["/paper-bots"][0] == "Bots"
    assert "execution_allowed=false" in joined
    assert "conditional historical simulation" in joined and "Never mixed with the forward record" in joined
    assert "Unconfirmed advantage" in joined
    assert not [item for item in walk(view) if getattr(item, "on_click", None) and getattr(item, "key", "")]  # read-only: no action control

    monkeypatch.setattr(page_module, "load_paper_bots_view", lambda: {"forward": {"status": "unavailable", "reason": "none yet", "bots": []}, "replay": None, "expectations": []})
    empty = "\n".join(str(getattr(item, "value", "") or "") for item in walk(page_module.paper_bots_page(None, AppState(snapshot=None, selected_etf=""))))
    assert "none yet" in empty and "No replay stored" in empty


def test_the_pipeline_runs_the_execution_after_the_recorder_only_on_success(monkeypatch, tmp_path: Path) -> None:
    import importlib

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    root = tmp_path / "application-root"
    (root / "configs").mkdir(parents=True)
    (root / "configs" / "universe.yaml").write_text("{}", encoding="utf-8")
    (root / "data").mkdir()
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(root))
    cli = importlib.import_module("run_pipeline_cli")
    calls: list[str] = []
    monkeypatch.setattr(
        paper_bots, "run_paper_bots",
        lambda as_of, **kwargs: calls.append("record") or type("R", (), {"status": "available", "reason": None, "warnings": ()})(),
    )
    monkeypatch.setattr(
        execution, "run_paper_bot_execution",
        lambda as_of, **kwargs: calls.append(f"execute:{kwargs.get('root')}")
        or execution.ExecutionRunResult("available", "forward", None, warnings=("one warning",)),
    )
    assert cli.run_cli(lambda: 1, record_paper_bots=True) == 1
    assert calls == []
    assert cli.run_cli(lambda: 0, record_paper_bots=True) == 0
    assert calls == ["record", f"execute:{root.resolve()}"]


def test_prerequisite_guards_hold_on_the_stage_b_path(monkeypatch, tmp_path: Path) -> None:
    """PL1 (as_of cash, explicit FX, event-log anchor), OL1 (lifecycle agrees with the ledger), PC1 (pre-trade controls)."""

    book = _ready(monkeypatch, tmp_path)
    _execute(tmp_path, book)
    track = execution.forward_track(tmp_path)
    for record in {item["bot_id"]: item for item in _records(tmp_path)}.values():
        ledger = PaperLedger(track.ledger_root, account_id=execution.account_id_for(record["bot_id"]))
        reconciled = ledger.reconcile()
        assert reconciled["status"] not in {"unavailable", "mismatch"} and reconciled["execution_allowed"] is False
        # PL1: cash is read as of a time; before the account existed there is no balance to read (fail closed).
        before = datetime(2026, 10, 13, tzinfo=timezone.utc)
        with pytest.raises(PaperLedgerError):
            ledger.cash_balance(account_id=ledger.account_id, currency="EUR", as_of=before)
        assert ledger.cash_balance(account_id=ledger.account_id, currency="EUR", as_of=RUN_AT) >= 0
        # OL1: every filled order is also a committed lifecycle fill, and the ledger sees all of them.
        assert ledger.cash_includes_unsettled_trades is True
        assert all(order["status"] in {"filled", "cancelled"} for order in ledger.orders())
        # PC1: the independent controls guard this account (limits from the bot root) and the kill switch is a live input.
        from etf_cockpit.trading.pre_trade_controls import PreTradeControls

        controls = PreTradeControls(track.ledger_root, account_id=ledger.account_id)
        assert controls.load_limits().allowed_instruments >= {"VWCE", "AAA", "BBB"}
        assert controls.kill_switch_active() is False
        assert all(order.get("execution_allowed") is False for order in ledger.orders())
        assert ledger.snapshot().base_currency == "EUR"


def test_the_event_log_anchor_detects_a_tampered_bot_ledger(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path)
    _execute(tmp_path, book)
    record = _by(_records(tmp_path), "B1", "BBB", "filled")[0]
    ledger = PaperLedger(execution.forward_track(tmp_path).ledger_root, account_id=execution.account_id_for(record["bot_id"]))
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    ledger.path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")  # drop the last event: the head anchor must object
    with pytest.raises(PaperLedgerError):
        ledger.snapshot()


def test_the_script_runs_the_execution_and_the_replay_flag_selects_the_replay(monkeypatch, capsys) -> None:
    import importlib

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    module = importlib.import_module("run_paper_bots")
    calls: list[str] = []
    monkeypatch.setattr(
        module, "run_paper_bots",
        lambda as_of: calls.append("record") or paper_bots.PaperBotRunResult("available", "2026-10-30T00:00:00Z", None, ()),
    )
    monkeypatch.setattr(
        module, "run_paper_bot_execution",
        lambda as_of: calls.append("execute") or execution.ExecutionRunResult("available", "forward", "2026-10-30T00:00:00Z"),
    )
    monkeypatch.setattr(
        module, "run_historical_replay",
        lambda as_of: calls.append("replay") or execution.ExecutionRunResult("partial", "replay", "x", label="conditional historical simulation"),
    )
    assert module.main(["--as-of", "2026-10-30T12:00:00+00:00"]) == 0
    assert calls == ["record", "execute"]
    calls.clear()
    assert module.main(["--replay"]) == 0
    assert calls == ["replay"]
    assert "conditional historical simulation" in capsys.readouterr().out


def test_monthly_contributions_are_mirrored_into_the_shadow_and_never_paid_twice(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_bots_report import build_paper_bots_overview

    config = tmp_path / "paper_bots_with_contribution.yaml"
    config.write_text(paper_bots.PAPER_BOTS_CONFIG_PATH.read_text(encoding="utf-8").replace("monthly_contribution_eur: 0.0", "monthly_contribution_eur: 500.0"), encoding="utf-8")
    root = tmp_path / "root"
    october = _NOW - timedelta(minutes=5)
    rows_october = _rows(october)
    board_october = _scoreboard(rows_october, october)
    board_october["instrument_currency"] = "EUR"
    assert _record_month(monkeypatch, root, rows_october, board_october, _NOW, config).status == "available"
    _allow(root)
    book = _book(known_at=datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc))
    _execute(root, book, config_path=config)
    _execute(root, book, config_path=config)  # a rerun must not fund the first month again
    track = execution.forward_track(root)
    bot_id = _by(_records(root), "B1")[0]["bot_id"]
    ledger = PaperLedger(track.ledger_root, account_id=execution.account_id_for(bot_id))
    assert [Decimal(flow["amount"]) for flow in ledger.external_flows()] == [Decimal("10000.0")]

    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    november = now - timedelta(minutes=5)
    rows_november = _rows(november, run_id="score-run-nov", snapshot="b")
    board_november = _scoreboard(rows_november, november)
    board_november["instrument_currency"] = "EUR"
    assert _record_month(monkeypatch, root, rows_october + rows_november, board_november, now, config).status == "available"
    november_run = datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc)
    _execute(root, book, as_of=november_run, config_path=config)
    _execute(root, book, as_of=november_run, config_path=config)
    flows = ledger.external_flows()
    assert [Decimal(flow["amount"]) for flow in flows] == [Decimal("10000.0"), Decimal("500.0")]
    assert flows[1]["flow_at"].startswith("2026-11-10")

    overview = build_paper_bots_overview(root, as_of=november_run, price_book=book, config_path=None)
    b1 = next(bot for bot in overview["forward"]["bots"] if bot["family"] == "B1")
    assert b1["status"] == "available", b1["reason"]
    assert b1["metrics"]["net_contributions_eur"] == pytest.approx(10_500.0)
    assert b1["relative_wealth"] and b1["metrics"]["compounded_relative_wealth"] is not None  # flows matched with the shadow
    assert b1["dates"][-1] == "2026-11-27"
