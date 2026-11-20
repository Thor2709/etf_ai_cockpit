"""SDD C5 and N4: the forward recorder reads the readiness run from the backfill store; other callers record nothing."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.data import score_history_backfill as store
from etf_cockpit.portfolio import paper_bots
from tests._pit_listing import verified_listing_history  # noqa: F401 (autouse)
from tests.test_paper_bots import _rows

pytestmark = pytest.mark.usefixtures("readiness_pass")

FRIDAY = date(2026, 11, 13)
MONDAY_NIGHT = datetime(2026, 11, 16, 21, 35, tzinfo=timezone.utc)
_PRICES = {"AAA": 21.0, "BBB": 22.0, "BAD": 23.0, "VWCE": 100.0}


def _run_frame(session: date, completed: datetime, *, price_shift: float = 0.0) -> pd.DataFrame:
    rows = _rows(completed, run_id=f"backfill_{session:%Y%m%d}_forward")
    for row in rows:
        instrument = str(row["instrument_id"])
        row.update(
            as_of_date=session.isoformat(), price_as_of_date=session.isoformat(), provenance=store.FORWARD_PROVENANCE,
            yahoo_ticker="VWCE.DE" if instrument == "VWCE" else f"{instrument}.X",
            current_price=_PRICES[instrument] + price_shift, instrument_currency="EUR",
            research_promotion_allowed=instrument in {"AAA", "BBB"}, legacy_action=row["final_action"],
        )
    frame = pd.DataFrame(rows).drop(columns=["snapshot_hash"])
    frame["snapshot_hash"] = store.run_content_hash(frame)
    frame["config_fingerprint"] = "f" * 64  # added after the hash, as the backfill writer does
    return frame


def _store(root: Path, *frames: pd.DataFrame) -> list[str]:
    store.write_backfill_store(root, pd.concat(frames, ignore_index=True), pd.DataFrame(), {})
    return [str(frame["snapshot_hash"].iloc[0]) for frame in frames]


def _record(root: Path, cutoff: datetime, session: date, snapshot: str, **kwargs) -> paper_bots.PaperBotRunResult:
    return paper_bots.run_paper_bots(
        cutoff, root=root, config_path=paper_bots.PAPER_BOTS_CONFIG_PATH, now=cutoff,
        decision_session=session, snapshot_hash=snapshot, **kwargs,
    )


def _family(result: paper_bots.PaperBotRunResult, family: str) -> dict:
    return next(item for item in result.records if item["bot_family"] == family)


def test_the_recorder_takes_candidates_and_prices_from_the_stored_run_with_the_readiness_hash(tmp_path: Path) -> None:
    completed = MONDAY_NIGHT - timedelta(minutes=4)
    older = _run_frame(date(2026, 11, 12), completed - timedelta(days=1), price_shift=900.0)
    snapshot, _older = _store(tmp_path, _run_frame(FRIDAY, completed), older)

    result = _record(tmp_path, MONDAY_NIGHT, FRIDAY, snapshot)

    assert result.candidate_snapshot == snapshot, result.reason
    benchmark = _family(result, "B0")
    assert benchmark["status"] == "available" and benchmark["snapshot_hash"] == snapshot
    assert benchmark["prices_used"]["VWCE"]["price"] == 100.0 and benchmark["prices_used"]["VWCE"]["symbol"] == "VWCE.DE"
    top_n = _family(result, "B1")
    assert top_n["status"] == "available" and set(top_n["targets"]) == {"AAA", "BBB"}
    assert {key: value["price"] for key, value in top_n["prices_used"].items()} == {"VWCE": 100.0, "AAA": 21.0, "BBB": 22.0}
    assert not (tmp_path / "data" / "derived" / "scoreboard.parquet").exists()  # no live publication is read


def test_a_stored_run_whose_content_differs_from_its_hash_is_not_used(tmp_path: Path) -> None:
    frame = _run_frame(FRIDAY, MONDAY_NIGHT - timedelta(minutes=4))
    snapshot = str(frame["snapshot_hash"].iloc[0])
    frame.loc[frame["instrument_id"].eq("AAA"), "current_price"] = 99.0
    _store(tmp_path, frame)

    result = _record(tmp_path, MONDAY_NIGHT, FRIDAY, snapshot)

    assert result.status == "unavailable" and result.candidate_snapshot is None
    assert "content hash" in str(result.reason)


def test_the_hash_is_reverified_when_older_historical_rows_lack_the_new_columns(tmp_path: Path) -> None:
    older = _run_frame(date(2026, 11, 12), MONDAY_NIGHT - timedelta(days=2)).drop(columns=["current_price", "instrument_currency"])
    older["provenance"] = store.BACKFILL_PROVENANCE
    snapshot, _older = _store(tmp_path, _run_frame(FRIDAY, MONDAY_NIGHT - timedelta(minutes=4)), older)

    result = _record(tmp_path, MONDAY_NIGHT, FRIDAY, snapshot)

    assert result.candidate_snapshot == snapshot, result.reason


@pytest.mark.parametrize(("age", "fresh"), [(timedelta(minutes=4), True), (timedelta(hours=25), False)])
def test_a_monday_run_for_the_friday_session_is_aged_from_its_completion_time(tmp_path: Path, age, fresh) -> None:
    snapshot, = _store(tmp_path, _run_frame(FRIDAY, MONDAY_NIGHT - age))

    benchmark = _family(_record(tmp_path, MONDAY_NIGHT, FRIDAY, snapshot), "B0")

    assert (benchmark["status"] == "available") is fresh, benchmark["reason"]
    if not fresh:
        assert "stale" in benchmark["reason"]


def test_the_slot_month_is_the_month_of_the_session(tmp_path: Path) -> None:
    session, night = date(2026, 10, 30), datetime(2026, 11, 1, 21, 35, tzinfo=timezone.utc)
    snapshot, = _store(tmp_path, _run_frame(session, night - timedelta(minutes=4)))

    result = _record(tmp_path, night, session, snapshot)

    assert result.candidate_snapshot == snapshot
    assert {item["decision_month"] for item in result.records} == {"2026-10"}


def test_the_readiness_gate_is_evaluated_on_the_decision_session(tmp_path: Path, readiness_pass) -> None:
    snapshot, = _store(tmp_path, _run_frame(FRIDAY, MONDAY_NIGHT - timedelta(minutes=4)))

    _record(tmp_path, MONDAY_NIGHT, FRIDAY, snapshot)

    assert readiness_pass.call_args.args[1:3] == (FRIDAY, FRIDAY)


def test_the_ui_and_mcp_workflow_records_no_forward_decision(monkeypatch) -> None:
    from etf_cockpit.application.workflow_handlers import headless_workflow_handlers

    monkeypatch.setattr(paper_bots, "run_paper_bots", lambda *_args, **_kwargs: pytest.fail("the recorder must not run"))
    handler = headless_workflow_handlers(lambda: pytest.fail("no session is needed"), include_paper=True)["paper_bots_run"]

    result = handler(SimpleNamespace(workflow_id="wf_fixture"))

    assert result["status"] == "unavailable" and result["appended"] == 0
    assert result["reason"] == "forward decisions run only in the nightly job"
    assert result["execution_allowed"] is False


def test_the_report_checks_the_b0_shadow_open_against_the_stored_observation(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_bots_report import build_paper_bots_overview
    from tests.test_morning_fill import _observations, _observed_book
    from tests.test_paper_bots_execution import RUN_AT, _execute, _ready

    _ready(monkeypatch, tmp_path)
    _execute(tmp_path, _observed_book(_observations()))
    revised = _observations()
    revised.loc[revised["instrument_id"].eq("VWCE"), "open"] += 1.0

    overview = build_paper_bots_overview(tmp_path, as_of=RUN_AT, price_book=_observed_book(revised))

    benchmark = next(item for item in overview["forward"]["bots"] if item["family"] == "B0")
    assert "historical_price_revised" in str(benchmark["reason"])
