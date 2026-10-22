"""Lane E: bounded, point-in-time children of hard-order-limit-capped buys."""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.portfolio import paper_bots_execution as execution
from etf_cockpit.portfolio.paper_trading import PaperLedger
from tests.test_paper_bots_execution import _book, _by, _execute, _plans, _ready, _records


def _at(day: int) -> datetime:
    return datetime(2026, 10, day, 12, tzinfo=timezone.utc)


def _core(root: Path, status: str | None = None) -> list[dict]:
    return sorted(_by(_records(root), "B2", "VWCE", status), key=lambda item: (item["session"], item["status"]))


def _core_intent(root: Path) -> dict:
    return next(intent for plan in _plans(root) for intent in plan["intents"]
                if intent["instrument_id"] == "VWCE" and intent["side"] == "buy" and "(B2," in intent["reason"])


def _change_limits(root: Path, **changes) -> None:
    path = execution.forward_track(root).ledger_root / "configs" / "pre_trade_limits_v1.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload.update(changes)
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def test_remainder_is_split_across_sessions_with_the_original_hard_limit(monkeypatch, tmp_path: Path) -> None:
    # A lower child-session price varies the quote without exhausting cash reserved for the sleeve.
    book = _ready(monkeypatch, tmp_path, opens={"VWCE": {date(2026, 10, 16): 90.0}})
    assert _execute(tmp_path, book, as_of=_at(16)).status == "available"
    first, = _core(tmp_path, "filled")
    assert first["session"] == "2026-10-15" and Decimal(first["remaining_quantity"]) > 0
    assert _execute(tmp_path, book, as_of=_at(22)).status == "available"
    fills = _core(tmp_path, "filled")
    assert [item["session"] for item in fills] == ["2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20"]
    intent = _core_intent(tmp_path)
    assert sum(Decimal(item["quantity"]) for item in fills) == Decimal(intent["planned_quantity"])
    assert all(Decimal(item["quantity"]) * Decimal(item["fill_price"]) <= 10000 for item in fills)
    assert all(item["parent_intent_id"] == intent["intent_id"] for item in fills[1:])
    assert len({item["order_id"] for item in fills}) == len(fills)
    assert fills[1]["reference_open"] == "90.0"  # child's own session quote
    assert not _core(tmp_path, "missed")
    ledger = PaperLedger(execution.forward_track(tmp_path).ledger_root, account_id=execution.account_id_for(first["bot_id"]))
    orders = {item["order_id"]: item for item in ledger.orders()}
    for child in fills[1:]:
        proposal = orders[child["order_id"]]["proposal_snapshot"]
        assert proposal["as_of"].startswith(child["session"])
        assert all(gate["passed"] for gate in proposal["gates"])
        assert proposal["execution_allowed"] is False
    assert _execute(tmp_path, book, as_of=_at(30)).appended == 0
    assert _core(tmp_path, "filled") == fills
    limits = yaml.safe_load((execution.forward_track(tmp_path).ledger_root / "configs" / "pre_trade_limits_v1.yaml").read_text(encoding="utf-8"))
    assert limits["max_order_value"] == 10000


def test_after_five_sessions_the_unfilled_remainder_is_recorded_as_missed(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path)
    _change_limits(tmp_path, max_order_value=1000)  # tighten the existing gate to need more than five orders
    assert _execute(tmp_path, book, as_of=_at(22)).status == "available"
    fills = _core(tmp_path, "filled")
    missed, = _core(tmp_path, "missed")
    assert [item["session"] for item in fills] == ["2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21"]
    assert all(Decimal(item["quantity"]) * Decimal(item["fill_price"]) <= 1000 for item in fills)
    assert missed["session"] == "2026-10-21" and missed["reason"] == "max_order_split_sessions_exhausted"
    assert Decimal(missed["planned_quantity"]) == Decimal(fills[-1]["remaining_quantity"]) > 0
    assert sum(Decimal(item["quantity"]) for item in fills) + Decimal(missed["planned_quantity"]) == Decimal(_core_intent(tmp_path)["planned_quantity"])
    assert _execute(tmp_path, book, as_of=_at(30)).appended == 0


@pytest.mark.parametrize(("hour", "expected_buys"), [(8, 1), (12, 2)])
def test_new_decision_supersedes_pending_children_at_its_own_time(monkeypatch, tmp_path: Path, hour: int, expected_buys: int) -> None:
    book = _ready(monkeypatch, tmp_path)
    assert _execute(tmp_path, book, as_of=_at(16)).status == "available"
    track = execution.forward_track(tmp_path)
    with TransactionalStore(track.store_root) as store:
        old = next(dict(item.payload) for item in store.list(track.decision_type) if item.payload["bot_family"] == "B2")
        timestamp = datetime(2026, 10, 16, hour, tzinfo=timezone.utc).isoformat()
        replacement = {**old, "decision_id": execution._record_id(old["decision_id"], "replacement"),
                       "as_of": timestamp, "known_at": timestamp, "targets": {"cash_weight": 1.0}}
        store.put_many([(track.decision_type, replacement["decision_id"], replacement)], immutable=True)
    assert _execute(tmp_path, book, as_of=_at(22)).status == "available"
    old_records = [item for item in _core(tmp_path) if item["decision_id"] == old["decision_id"]]
    fills = [item for item in old_records if item["status"] == "filled"]
    missed, = [item for item in old_records if item["status"] == "missed"]
    assert len(fills) == expected_buys
    assert missed["reason"] == "superseded_by_new_decision"
    assert sum(Decimal(item["quantity"]) for item in fills) + Decimal(missed["planned_quantity"]) == Decimal(_core_intent(tmp_path)["planned_quantity"])
    sells = [item for item in _core(tmp_path, "filled") if item["side"] == "sell"]
    assert len(sells) == 1 and sells[0]["session"] == "2026-10-19"  # sells still attempt once
    assert "parent_intent_id" not in sells[0]
    assert _execute(tmp_path, book, as_of=_at(30)).appended == 0


@pytest.mark.parametrize("block", ["volume", "allowlist", "turnover", "friction", "expiry"])
def test_children_fail_closed_through_the_normal_session_checks(monkeypatch, tmp_path: Path, block: str) -> None:
    book = _ready(monkeypatch, tmp_path)
    assert _execute(tmp_path, book, as_of=_at(16)).status == "available"
    options = {}
    if block == "volume":
        book = _book(volume={("VWCE", date(2026, 10, 16)): 0})
        reason = "zero_volume_session"
    elif block == "allowlist":
        _change_limits(tmp_path, allowed_instruments=["AAA", "BBB", "BAD"])
        reason = "allowlist"
    elif block == "turnover":
        _change_limits(tmp_path, max_daily_turnover=100)
        reason = "Daily turnover"
    else:
        payload = yaml.safe_load(execution.EXECUTION_CONFIG_PATH.read_text(encoding="utf-8"))
        payload.update({"rule_expected_benefit_bps": None} if block == "friction" else {"proposal_validity_days": 1})
        path = tmp_path / "execution.yaml"
        path.write_text(yaml.safe_dump(payload), encoding="utf-8")
        options["execution_config_path"] = path
        reason = "benefit_unavailable" if block == "friction" else "proposal_expired"
    result = execution.run_paper_bot_execution(_at(22), root=tmp_path, price_book=book, now=_at(22), **options)
    assert result.status == "available"
    missed, = _core(tmp_path, "missed")
    assert missed["session"] == "2026-10-16" and reason in missed["reason"]
    assert len(_core(tmp_path, "filled")) == 1


def test_future_quotes_cannot_change_a_child_fill(monkeypatch, tmp_path: Path) -> None:
    fills = []
    for name, future_open in [("ordinary", 101.0), ("future_shock", 10000.0)]:
        root = tmp_path / name
        book = _ready(monkeypatch, root, opens={"VWCE": {date(2026, 10, 19): future_open}})
        assert _execute(root, book, as_of=_at(17)).status == "available"
        fills.append(_core(root, "filled"))
    assert fills[0] == fills[1]
    assert len(fills[0]) == 2


def test_a_split_child_recovers_a_lost_store_write_without_a_duplicate_order(monkeypatch, tmp_path: Path) -> None:
    book = _ready(monkeypatch, tmp_path)
    assert _execute(tmp_path, book, as_of=_at(16)).status == "available"
    real_store = execution._store_record

    def fail_on_child(context, record):
        if record["bot_family"] == "B2" and record["instrument_id"] == "VWCE" and record["status"] == "filled":
            raise OSError("simulated lost child record")
        real_store(context, record)

    monkeypatch.setattr(execution, "_store_record", fail_on_child)
    result = _execute(tmp_path, book, as_of=_at(17))
    assert result.status == "partial" and result.warnings
    monkeypatch.setattr(execution, "_store_record", real_store)
    assert _execute(tmp_path, book, as_of=_at(22)).status == "available"
    fills = _core(tmp_path, "filled")
    assert len(fills) == 4
    assert sum(Decimal(item["quantity"]) for item in fills) == Decimal(_core_intent(tmp_path)["planned_quantity"])
    assert "recovered" in fills[1]["reason"]
    ledger = PaperLedger(execution.forward_track(tmp_path).ledger_root, account_id=execution.account_id_for(fills[0]["bot_id"]))
    assert len([item for item in ledger.trade_rows() if item["instrument_id"] == "VWCE"]) == 4
    assert _execute(tmp_path, book, as_of=_at(30)).appended == 0


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "5", None])
def test_split_session_configuration_rejects_invalid_values(tmp_path: Path, value) -> None:
    payload = yaml.safe_load(execution.EXECUTION_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["max_order_split_sessions"] = value
    path = tmp_path / "execution.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="max_order_split_sessions"):
        execution.load_execution_config(path)


def test_split_session_configuration_defaults_to_five(tmp_path: Path) -> None:
    payload = yaml.safe_load(execution.EXECUTION_CONFIG_PATH.read_text(encoding="utf-8"))
    payload.pop("max_order_split_sessions")
    path = tmp_path / "execution.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    assert execution.load_execution_config(path)[1]["max_order_split_sessions"] == 5
