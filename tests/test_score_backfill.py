"""Historical score backfill: point-in-time scoring into a separate store, and the optional replay from it."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application import score_backfill
from etf_cockpit.data.replay_membership import MEMBERSHIP_POLICY, ListingHistory
from etf_cockpit.core.config import load_config
from etf_cockpit.data import score_history_backfill as store
from etf_cockpit.portfolio import paper_bots, paper_bots_execution as execution
from tests._pit_listing import verified_listing_history  # noqa: F401 (autouse)
from tests.test_paper_bots import _rows
from tests.test_paper_bots_execution import _allow, _book, _exec_config, _history_with_columns, _records

AS_OF = date(2022, 6, 30)
CALENDAR = list(pd.bdate_range("2021-01-04", "2022-12-30"))


def _config():
    return load_config()


def _fingerprint(config, root=None) -> tuple[str, dict]:
    """The run fingerprint exactly as backfill_score_history derives it (historical config + membership)."""

    membership = ListingHistory.from_root(root)
    return score_backfill.config_fingerprint(score_backfill._historical_config(config, membership), None, membership)


def _eur_ids(config, kind: str, count: int) -> list[str]:
    ids = [
        item.id for item in config.universe.etfs
        if item.id in config.universe.enabled_ids and item.currency == "EUR" and item.instrument_type == kind and item.id != "VWCE"
    ]
    assert len(ids) >= count
    return ids[:count]


def _series(instrument: str, days: list[pd.Timestamp], seed: int, *, volume: float = 1000.0, currency: str = "EUR") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    level = 50.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(days))))
    return pd.DataFrame(
        {
            "date": [day.date() for day in days], "etf_id": instrument, "open": level, "high": level * 1.004, "low": level * 0.996,
            "close": level, "adjusted_close": level, "volume": volume, "currency": currency, "provider_symbol": instrument,
            "source": "yfinance", "is_adjusted": True, "dividends": 0.0, "stock_splits": 0.0, "capital_gains": 0.0,
        }
    )


def _prices(config, *, young: str | None = None) -> pd.DataFrame:
    ids = ["VWCE", *_eur_ids(config, "etf", 2), *_eur_ids(config, "stock", 2)]
    frames = [_series(instrument, CALENDAR, seed) for seed, instrument in enumerate(ids)]
    if young is not None:  # lists late: only the last 120 sessions exist at AS_OF
        late = [day for day in CALENDAR if pd.Timestamp("2022-01-10") <= day <= pd.Timestamp("2022-12-30")]
        frames.append(_series(young, late, 99))
    return pd.concat(frames, ignore_index=True)


def _run(config, prices: pd.DataFrame, as_of: date = AS_OF):
    return score_backfill.score_as_of(config, prices, as_of, fx_rates=pd.DataFrame())


def test_backfill_quality_gate_resolves_configured_exchange_without_identity_column(monkeypatch) -> None:
    import exchange_calendars as xcals

    config = _config()
    next(item for item in config.universe.etfs if item.id == "VWCE").exchange = "XETRA"
    prices = _prices(config)
    sessions = xcals.get_calendar("XETR").sessions_in_range("2021-01-04", "2022-12-30")
    prices = prices.loc[~prices["etf_id"].eq("VWCE") | pd.to_datetime(prices["date"]).isin(sessions)]
    assert "calendar_identity" not in prices
    original = score_backfill.validate_prices
    reports = []

    def validate(frame, **kwargs):
        # The historical view only restores retained delisted identities; the exchange mapping is the config's own.
        by_id = kwargs["config"].universe.by_id()
        assert by_id and all(item.exchange == config.universe.by_id()[key].exchange for key, item in by_id.items())
        report = original(frame, **kwargs)
        reports.append(report)
        return report

    monkeypatch.setattr(score_backfill, "validate_prices", validate)
    run, _ = _run(config, prices)
    assert run is not None and len(reports) == 1
    assert not [issue for issue in reports[0].issues if issue.etf_id == "VWCE" and issue.code == "missing_trading_days"]


def test_backfill_reads_nothing_after_the_as_of_date() -> None:
    config = _config()
    prices = _prices(config)
    run, _log = _run(config, prices)
    assert run is not None and len(run) >= 3
    future = prices.copy()
    last = future[future["date"] > AS_OF].copy()
    future.loc[last.index, ["open", "high", "low", "close", "adjusted_close"]] = last[["open", "high", "low", "close", "adjusted_close"]] * 25.0
    extra = future[future["date"] == date(2022, 12, 30)].copy()
    extra["date"] = date(2023, 3, 1)
    later, _later_log = _run(config, pd.concat([future, extra], ignore_index=True))
    pd.testing.assert_frame_equal(run, later)  # same rows, same inputs hash, same snapshot hash
    assert run["snapshot_hash"].nunique() == 1 and run["as_of_inputs_hash"].iloc[0] == later["as_of_inputs_hash"].iloc[0]
    changed = prices.copy()
    changed.loc[(changed["etf_id"] == "VWCE") & (changed["date"] == AS_OF), "adjusted_close"] *= 1.1
    assert _run(config, changed)[0]["as_of_inputs_hash"].iloc[0] != run["as_of_inputs_hash"].iloc[0]  # a known row does change it


def test_terms_without_point_in_time_data_are_unavailable_with_a_reason(monkeypatch) -> None:
    from etf_cockpit.signals import simple_scores

    config = _config()
    seen: dict[str, object] = {}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a non point-in-time source was read for a historical score")

    original = simple_scores.get_universe_evidence

    def recording(records, prices, decision_time):
        seen["decision_time"] = decision_time
        return original(records, prices, decision_time)

    for name in ("_kid_record_lookup", "_etf_product_quality_lookup", "_news_inventory_lookup"):
        monkeypatch.setattr(simple_scores, name, forbidden)
    monkeypatch.setattr(simple_scores, "get_universe_evidence", recording)
    run, log = _run(config, _prices(config))
    assert run is not None
    assert seen["decision_time"] == datetime(2022, 6, 30, 23, 59, 59, tzinfo=timezone.utc)  # fundamentals gated by their own known-at
    coverage = json.loads(run["pit_coverage"].iloc[0])
    for term in ("stock_value", "stock_quality", "etf_exposure", "etf_product_quality", "baseline"):
        entry = coverage["terms"][term]
        assert entry["available"] == 0 and entry["unavailable"] > 0 and entry["reasons"], term
    assert "etf_holdings_exposure" in coverage["withheld_sources"] and "stored_forecasts_and_calibration" in coverage["withheld_sources"]
    etf_row = run[run["asset_type"].eq("ETF")].iloc[0]
    assert "etf_exposure" in etf_row["pit_terms_unavailable"].split("|") and "momentum" not in etf_row["pit_terms_unavailable"].split("|")
    assert not run["research_promotion_allowed"].any() and run["execution_allowed"].eq(False).all()  # never filled, never promoted


def test_every_run_carries_snapshot_lineage_and_the_replay_accepts_it() -> None:
    config = _config()
    run, _log = _run(config, _prices(config))
    assert run is not None
    row = run.iloc[0]
    assert row["provenance"] == store.BACKFILL_PROVENANCE and row["as_of_date"] == "2022-06-30"
    assert row["run_completed_at"] == "2022-06-30T23:59:59+00:00"  # the as-of session close
    assert row["run_id"].startswith("backfill_20220630_") and row["run_id"].endswith(row["as_of_inputs_hash"][:8])
    for column in ("snapshot_hash", "as_of_inputs_hash", "formula_checksum", "gate_policy_checksum"):
        assert len(str(row[column])) == 64 and set(str(row[column])) <= set("0123456789abcdef"), column
    for column in ("formula_version", "score_schema_version", "gate_policy_version", "pit_policy_version", "pit_coverage", "survivorship_caveat"):
        assert str(row[column]).strip() and str(row[column]) != "unavailable", column
    assert run["formula_version"].ne("unavailable").all() and run["formula_checksum"].ne("unavailable").all()  # no lineage-less row
    assert run["snapshot_hash"].nunique() == 1 and run["run_id"].nunique() == 1 and run["rank"].tolist() == list(range(1, len(run) + 1))
    group, error = paper_bots._validate_run(row["run_id"], run.to_dict(orient="records"), datetime(2022, 7, 1, tzinfo=timezone.utc))
    assert error is None and group is not None and group.known_at == datetime(2022, 6, 30, 23, 59, 59, tzinfo=timezone.utc)


def test_eligibility_uses_only_the_engine_gate_at_each_date_and_instruments_enter_when_they_qualify(tmp_path: Path) -> None:
    config = _config()
    young = _eur_ids(config, "etf", 4)[3]
    prices = _prices(config, young=young)
    early, early_log = _run(config, prices, date(2022, 6, 30))  # ~120 sessions of history
    assert young not in set(early["instrument_id"])
    reason = early_log.loc[early_log["instrument_id"].eq(young), "reasons"].iloc[0]
    assert "insufficient_history" in reason
    absent = early_log.loc[early_log["instrument_id"].eq("TKMS"), "reasons"].iloc[0] if (early_log["instrument_id"] == "TKMS").any() else "no_price_history_yet"
    assert absent == "no_price_history_yet"  # unknown pre-listing = absent, never filled
    late, late_log = _run(config, prices, date(2022, 12, 30))  # 252+ rows by now
    qualified = late_log.loc[late_log["instrument_id"].eq(young)].iloc[0]
    assert bool(qualified["eligible"]) == (young in set(late["instrument_id"]))
    result = score_backfill.backfill_score_history(
        tmp_path, date(2022, 6, 1), date(2022, 12, 30), every=60, config=config, prices=prices, fx_rates=pd.DataFrame()
    )
    assert result.status == "available"
    by_year = score_backfill.eligible_counts_by_year(result.eligibility)
    assert "2022" in by_year.index and int(by_year.loc["2022"].sum()) >= 3
    assert "SURVIVORSHIP" in score_backfill.SURVIVORSHIP_CAVEAT and isinstance(score_backfill.never_eligible(result.eligibility), pd.DataFrame)


def test_backfill_writes_only_its_own_store_and_never_the_live_history(tmp_path: Path) -> None:
    config = _config()
    live = tmp_path / "data" / "derived" / "score_history.parquet"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"live history bytes")
    prices = _prices(config)
    first = score_backfill.backfill_score_history(
        tmp_path, date(2022, 6, 1), date(2022, 6, 30), every=10, config=config, prices=prices, fx_rates=pd.DataFrame()
    )
    assert first.status == "available" and first.runs_written >= 2
    assert live.read_bytes() == b"live history bytes"  # untouched
    history = store.load_backfill_score_history(tmp_path)
    assert set(history["provenance"]) == {store.BACKFILL_PROVENANCE} and history["run_id"].nunique() == first.runs_written
    manifest = json.loads((tmp_path / store.BACKFILL_MANIFEST_RELATIVE_PATH).read_text(encoding="utf-8"))
    assert manifest["execution_allowed"] is False and "SURVIVORSHIP" in manifest["survivorship_caveat"]
    second = score_backfill.backfill_score_history(
        tmp_path, date(2022, 6, 1), date(2022, 6, 30), every=10, config=config, prices=prices, fx_rates=pd.DataFrame()
    )
    assert second.runs_written == 0 and second.runs_kept == first.runs_written  # resumable, nothing recomputed


def test_the_replay_reads_the_backfill_store_on_request_and_trades_through_normal_paper_execution(monkeypatch, tmp_path: Path, readiness_pass) -> None:
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay

    october = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    november = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    rows = _history_with_columns(_rows(october) + _rows(november, run_id="score-run-nov", snapshot="b"))
    history = pd.DataFrame(rows)
    history["provenance"] = store.BACKFILL_PROVENANCE
    history["membership_policy"] = MEMBERSHIP_POLICY  # stamped by score_as_of on every real backfill row
    history["as_of_date"] = [str(value)[:10] for value in history["run_completed_at"]]
    store.write_backfill_store(tmp_path, history, pd.DataFrame(), {})
    as_of = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
    book = _book(known_at=as_of)
    replay_track = execution.replay_track(tmp_path, _exec_config())
    _allow(tmp_path, replay_track)

    default = run_historical_replay(as_of, root=tmp_path, price_book=book, now=as_of)  # default source: the live published history
    assert default.status == "unavailable" and _records(tmp_path, replay_track) == []
    result = run_historical_replay(as_of, root=tmp_path, price_book=book, now=as_of, history_source="backfill")
    assert result.label == "conditional historical simulation" and result.status in {"available", "partial"}, (result.reason, result.warnings)
    assert any("Historical score backfill" in warning for warning in result.warnings)
    filled = [item for item in _records(tmp_path, replay_track) if item["status"] == "filled"]
    assert filled and {item["bot_family"] for item in filled} >= {"B1"}
    assert all(item["track"] == "replay" for item in filled)
    assert _records(tmp_path) == []  # the forward record is untouched
    foreign = history.assign(provenance="live")
    store.write_backfill_store(tmp_path, foreign, pd.DataFrame(), {})
    assert store.load_backfill_score_history(tmp_path).empty  # rows without the backfill provenance are never replayed
    assert run_historical_replay(as_of, root=tmp_path, price_book=book, now=as_of, history_source="backfill").appended == 0


def test_replay_universe_rules_exclusions_and_liquidity_gate() -> None:
    config = _config()
    prices = _prices(config)
    illiquid_stock = _eur_ids(config, "stock", 2)[0]
    illiquid_etf = _eur_ids(config, "etf", 2)[0]
    low = prices["etf_id"].isin([illiquid_stock, illiquid_etf])
    prices.loc[low, "volume"] = 1.0  # EUR traded value of a few tens of euro per day
    excluded_id = _eur_ids(config, "etf", 2)[1]
    run, log = score_backfill.score_as_of(config, prices, AS_OF, fx_rates=pd.DataFrame(), excluded={excluded_id: "duplicate listing"})
    reasons = dict(zip(log["instrument_id"], log["reasons"]))
    assert "liquidity_gate: median traded value" in reasons[illiquid_stock] and illiquid_stock not in set(run["instrument_id"])
    assert reasons[illiquid_etf] == "" and illiquid_etf in set(run["instrument_id"])  # ETFs are not liquidity-gated
    assert reasons[excluded_id] == "excluded: duplicate listing" and excluded_id not in set(run["instrument_id"])


def _fx(rate: float) -> pd.DataFrame:
    from etf_cockpit.data.fx_data import stamp_fx_availability

    days = pd.bdate_range("2020-12-01", "2023-01-31")
    quotes = pd.DataFrame(
        {"as_of_date": [day.date() for day in days], "base_currency": "NOK", "quote_currency": "EUR", "pair": "NOK/EUR", "rate": rate, "source": "test"}
    )
    return stamp_fx_availability(quotes, ingested_at=datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc))


def test_liquidity_gate_converts_a_foreign_listing_to_eur_exactly_once() -> None:
    config = _config()
    nok = next(item.id for item in config.universe.etfs if item.currency == "NOK" and item.instrument_type == "stock" and item.id in config.universe.enabled_ids)
    rate = 0.1
    base = _series(nok, CALENDAR, 7, currency="NOK")
    tail_close = base[base["date"] <= AS_OF]["close"].tail(score_backfill.LIQUIDITY_WINDOW_SESSIONS)
    per_unit_eur = float(tail_close.median()) * rate  # close is NOK; the EUR value of one traded unit
    for factor, passes in ((1.5, True), (0.5, False)):
        volume = factor * score_backfill.LIQUIDITY_MIN_MEDIAN_VALUE_EUR / per_unit_eur
        frame = base.assign(volume=volume)
        known = frame[frame["date"] <= AS_OF]
        failures = score_backfill._liquidity_gate(config, known, _fx(rate), AS_OF)
        # a missing conversion would pass both cases, a doubled one would fail both
        assert (nok not in failures) == passes, (factor, failures.get(nok))
        if not passes:
            median = float((known["close"] * known["volume"] * rate).tail(score_backfill.LIQUIDITY_WINDOW_SESSIONS).median())
            assert f"EUR {median:,.0f}" in failures[nok]


def test_a_stored_session_is_recomputed_when_the_run_configuration_changes(tmp_path: Path) -> None:
    config = _config()
    prices = _prices(config)
    victim = _eur_ids(config, "etf", 2)[0]
    window = (date(2022, 6, 1), date(2022, 6, 30))
    first = score_backfill.backfill_score_history(tmp_path, *window, every=10, config=config, prices=prices, fx_rates=pd.DataFrame())
    assert first.status == "available" and victim in set(store.load_backfill_score_history(tmp_path)["instrument_id"])
    again = score_backfill.backfill_score_history(tmp_path, *window, every=10, config=config, prices=prices, fx_rates=pd.DataFrame())
    assert again.runs_written == 0  # same configuration: kept
    second = score_backfill.backfill_score_history(
        tmp_path, *window, every=10, config=config, prices=prices, fx_rates=pd.DataFrame(), excluded={victim: "duplicate listing"}
    )
    assert second.runs_written == first.runs_written  # no --force needed: the fingerprint differs
    history = store.load_backfill_score_history(tmp_path)
    assert victim not in set(history["instrument_id"]) and history["config_fingerprint"].nunique() == 1
    manifest = store.load_backfill_manifest(tmp_path)
    assert manifest["excluded_instruments"] == {victim: "duplicate listing"} and manifest["mixed_configuration"] is False
    log = store.load_backfill_eligibility(tmp_path)
    assert (log.loc[log["instrument_id"].eq(victim), "reasons"].str.startswith("excluded")).all()


def test_the_store_is_written_as_one_group_and_a_noop_rerun_keeps_unavailable_dates(monkeypatch, tmp_path: Path) -> None:
    config = _config()
    prices = _prices(config)
    window = (date(2022, 6, 1), date(2022, 6, 30))
    score_backfill.backfill_score_history(tmp_path, *window, every=10, config=config, prices=prices, fx_rates=pd.DataFrame())
    manifest_path = tmp_path / store.BACKFILL_MANIFEST_RELATIVE_PATH
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["unavailable_dates"] = {"2022-05-02": "earlier failure"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    score_backfill.backfill_score_history(tmp_path, *window, every=10, config=config, prices=prices, fx_rates=pd.DataFrame())
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["unavailable_dates"] == {"2022-05-02": "earlier failure"}

    history_path = tmp_path / store.BACKFILL_HISTORY_RELATIVE_PATH
    before = {path: path.read_bytes() for path in (history_path, tmp_path / store.BACKFILL_ELIGIBILITY_RELATIVE_PATH, manifest_path)}
    monkeypatch.setattr(store, "_validate_manifest", lambda _path: (_ for _ in ()).throw(ValueError("manifest invalid")))
    with pytest.raises(Exception):
        store.write_backfill_store(tmp_path, pd.DataFrame({"x": [1]}), pd.DataFrame({"y": [2]}), {"a": 1})
    assert {path: path.read_bytes() for path in before} == before  # a failed group leaves all three files as they were


def test_an_unmarked_position_is_never_valued_as_zero() -> None:
    import importlib.util
    from decimal import Decimal

    spec = importlib.util.spec_from_file_location("export_replay_ledger", Path(__file__).resolve().parents[1] / "scripts" / "export_replay_ledger.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    held = {"VWCE": Decimal(10), "STALE": Decimal(5)}
    fx = {"VWCE": Decimal(1), "STALE": Decimal(1)}
    values, invested, total, missing = module.value_positions(Decimal(100), held, fx, lambda key: 50.0 if key == "VWCE" else None)
    assert missing == ["STALE"] and values["STALE"] is None and invested is None and total is None  # no partial total, no weights
    values, invested, total, missing = module.value_positions(Decimal(100), held, fx, lambda key: 50.0 if key == "VWCE" else 20.0)
    assert missing == [] and invested == 600.0 and total == 700.0


def test_parallel_backfill_equals_serial_backfill(tmp_path: Path) -> None:
    config = _config()
    prices = _prices(config)
    window = (date(2022, 5, 2), date(2022, 6, 30))
    serial_root, parallel_root = tmp_path / "serial", tmp_path / "parallel"
    serial = score_backfill.backfill_score_history(serial_root, *window, every=5, config=config, prices=prices, fx_rates=pd.DataFrame())
    parallel = score_backfill.backfill_score_history(
        parallel_root, *window, every=5, config=config, prices=prices, fx_rates=pd.DataFrame(), workers=3
    )
    assert serial.status == parallel.status == "available" and serial.runs_written == parallel.runs_written >= 2
    assert serial.unavailable_dates == parallel.unavailable_dates
    left = store.load_backfill_score_history(serial_root)
    right = store.load_backfill_score_history(parallel_root)
    pd.testing.assert_frame_equal(left.reset_index(drop=True), right.reset_index(drop=True))
    pd.testing.assert_frame_equal(
        store.load_backfill_eligibility(serial_root).reset_index(drop=True), store.load_backfill_eligibility(parallel_root).reset_index(drop=True)
    )


def test_fingerprint_changes_when_engine_hash_changes(monkeypatch, tmp_path: Path) -> None:
    config = _config()
    prices = _prices(config)
    monkeypatch.setattr(score_backfill, "_score_engine_hash", lambda: "a" * 64)
    first_hash, material = _fingerprint(config)
    assert material["score_engine_hash"] == "a" * 64
    first = score_backfill.backfill_score_history(tmp_path, AS_OF, AS_OF, config=config, prices=prices, fx_rates=pd.DataFrame())
    monkeypatch.setattr(score_backfill, "_score_engine_hash", lambda: "b" * 64)
    assert _fingerprint(config)[0] != first_hash
    second = score_backfill.backfill_score_history(tmp_path, AS_OF, AS_OF, config=config, prices=prices, fx_rates=pd.DataFrame())
    assert first.runs_written == second.runs_written == 1 and second.runs_kept == 0
    assert set(store.load_backfill_score_history(tmp_path)["config_fingerprint"]) == {_fingerprint(config)[0]}


@pytest.mark.parametrize("source", ["signals/simple_scores.py", "analysis/formula_registry.py", "data/etf_economics.py"])
def test_engine_hash_covers_score_code_and_formula_registry(monkeypatch, source) -> None:
    original = Path.read_bytes
    before = score_backfill._score_engine_hash()
    target = Path(score_backfill.__file__).resolve().parents[1] / source

    def changed(path):
        content = original(path)
        return content + b"\n# synthetic engine change\n" if path == target else content

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert score_backfill._score_engine_hash() != before


@pytest.mark.parametrize("force", [False, True])
def test_pool_failure_finally_persists_completed_sessions(monkeypatch, tmp_path: Path, force) -> None:
    from concurrent.futures import Future
    from concurrent.futures.process import BrokenProcessPool
    import concurrent.futures

    config = _config()
    prices = _prices(config)
    start, end = date(2022, 6, 29), AS_OF
    if force:
        score_backfill.backfill_score_history(tmp_path, start, end, every=1, config=config, prices=prices, fx_rates=pd.DataFrame())
    before = store.load_backfill_score_history(tmp_path)

    class Pool:
        def __init__(self, **_kwargs):
            self.count = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, _function, session):
            future = Future()
            self.count += 1
            if self.count == 1:
                future.set_result(score_backfill.score_as_of(config, prices, session, fx_rates=pd.DataFrame()))
            else:
                future.set_exception(BrokenProcessPool("synthetic dead worker"))
            return future

    writes = []
    original = score_backfill.write_backfill_store

    def write(*args):
        writes.append(args[1].copy())
        return original(*args)

    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", Pool)
    monkeypatch.setattr(score_backfill, "write_backfill_store", write)
    with pytest.raises(BrokenProcessPool, match="synthetic dead worker"):
        score_backfill.backfill_score_history(
            tmp_path, start, end, every=1, config=config, prices=prices, fx_rates=pd.DataFrame(), workers=2, force=force,
        )
    assert len(writes) == 1  # fewer than CHECKPOINT_RUNS: only the final persist can save it
    saved = store.load_backfill_score_history(tmp_path)
    assert start.isoformat() in set(saved["as_of_date"])
    if force:
        pd.testing.assert_frame_equal(
            saved.loc[saved["as_of_date"].eq(end.isoformat())].reset_index(drop=True),
            before.loc[before["as_of_date"].eq(end.isoformat())].reset_index(drop=True),
        )  # an unprocessed prior session survives an interrupted --force run
    else:
        assert set(saved["as_of_date"]) == {start.isoformat()}


def test_worker_init_overrides_inherited_cuda_devices(monkeypatch) -> None:
    import os

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    monkeypatch.setattr(score_backfill, "_WORKER_STATE", {})
    score_backfill._worker_init(_config(), pd.DataFrame(), None, "test", None, ListingHistory())
    assert os.environ["CUDA_VISIBLE_DEVICES"] == ""


@pytest.mark.parametrize("supports_holdings,has_known_at", [(False, True), (True, True), (True, False)])
def test_pit_holdings_are_passed_only_when_the_contract_and_knowledge_column_exist(monkeypatch, supports_holdings, has_known_at) -> None:
    from dataclasses import field, make_dataclass
    from etf_cockpit.signals import simple_scores

    legacy = make_dataclass("LegacySources", [
        ("decision_time", datetime),
        ("expected_return_distributions", object, field(default=None)),
        ("reference_order_value_eur", object, field(default=None)),
    ], frozen=True)
    contract = make_dataclass("HoldingsSources", [("etf_holdings", object, field(default=None))], bases=(legacy,), frozen=True) if supports_holdings else legacy
    monkeypatch.setattr(score_backfill, "AsOfScoreSources", contract)
    holdings = pd.DataFrame({"etf_id": ["VWCE", "VWCE"], "as_of_date": ["2022-06-01", "2023-01-01"], "known_at": ["2022-06-02", "2023-01-02"]})
    if not has_known_at:
        holdings = holdings.drop(columns="known_at")
    reads, seen = [], []

    def load(dataset):
        reads.append(dataset)
        return holdings

    original = score_backfill.build_universe_simple_scores

    def build(*args, **kwargs):
        supplied = kwargs["as_of_sources"]
        seen.append(supplied)
        # Keep the real engine's currently installed contract in this merge-order test.
        kwargs["as_of_sources"] = simple_scores.AsOfScoreSources(
            decision_time=supplied.decision_time,
            expected_return_distributions=supplied.expected_return_distributions,
            reference_order_value_eur=supplied.reference_order_value_eur,
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(score_backfill, "load_reference_dataset", load)
    monkeypatch.setattr(score_backfill, "build_universe_simple_scores", build)
    assert _run(_config(), _prices(_config()))[0] is not None
    assert reads == (["etf_holdings"] if supports_holdings else [])
    assert len(seen) == 1
    if supports_holdings:
        if has_known_at:
            pd.testing.assert_frame_equal(seen[0].etf_holdings, holdings)  # the engine owns date filtering
        else:
            assert seen[0].etf_holdings.empty
    else:
        assert not hasattr(seen[0], "etf_holdings")


def test_forecast_status_is_partial_for_baseline_only_rows_and_unavailable_without_a_baseline() -> None:
    config = _config()
    run, _log = _run(config, _prices(config))
    assert run is not None
    with_baseline = run["forecast_provenance"].eq("baseline_only_non_calibrated")
    assert with_baseline.any()
    assert run.loc[with_baseline, "forecast_status"].eq("partial").all()  # baseline only: no TimesFM/Toto, never "available"
    assert run.loc[~with_baseline, "forecast_status"].eq("unavailable").all()
