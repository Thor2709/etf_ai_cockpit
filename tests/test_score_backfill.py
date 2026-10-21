"""Historical score backfill: point-in-time scoring into a separate store, and the optional replay from it."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application import score_backfill
from etf_cockpit.core.config import load_config
from etf_cockpit.data import score_history_backfill as store
from etf_cockpit.portfolio import paper_bots, paper_bots_execution as execution
from tests.test_paper_bots import _rows
from tests.test_paper_bots_execution import _allow, _book, _exec_config, _history_with_columns, _records

AS_OF = date(2022, 6, 30)
CALENDAR = list(pd.bdate_range("2021-01-04", "2022-12-30"))


def _config():
    return load_config()


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

    for name in ("_etf_exposure_lookup", "_kid_record_lookup", "_etf_product_quality_lookup", "_news_inventory_lookup"):
        monkeypatch.setattr(simple_scores, name, forbidden)
    monkeypatch.setattr(simple_scores, "get_universe_evidence", recording)
    run, log = _run(config, _prices(config))
    assert run is not None
    assert seen["decision_time"] == datetime(2022, 6, 30, 23, 59, 59, tzinfo=timezone.utc)  # fundamentals gated by their own known-at
    coverage = json.loads(run["pit_coverage"].iloc[0])
    for term in ("stock_value", "stock_quality", "etf_exposure", "etf_product_quality", "baseline"):
        entry = coverage["terms"][term]
        assert entry["available"] == 0 and entry["unavailable"] > 0 and entry["reasons"], term
    assert "etf_holdings_exposure" in coverage["withheld_sources"] and "forecasts_and_calibration" in coverage["withheld_sources"]
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


def test_the_replay_reads_the_backfill_store_on_request_and_trades_through_normal_paper_execution(monkeypatch, tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay

    october = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    november = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    rows = _history_with_columns(_rows(october) + _rows(november, run_id="score-run-nov", snapshot="b"))
    history = pd.DataFrame(rows)
    history["provenance"] = store.BACKFILL_PROVENANCE
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
    assert any("historical_backfill" in warning for warning in result.warnings)
    filled = [item for item in _records(tmp_path, replay_track) if item["status"] == "filled"]
    assert filled and {item["bot_family"] for item in filled} >= {"B1"}
    assert all(item["track"] == "replay" for item in filled)
    assert _records(tmp_path) == []  # the forward record is untouched
    foreign = history.assign(provenance="live")
    store.write_backfill_store(tmp_path, foreign, pd.DataFrame(), {})
    assert store.load_backfill_score_history(tmp_path).empty  # rows without the backfill provenance are never replayed
    assert run_historical_replay(as_of, root=tmp_path, price_book=book, now=as_of, history_source="backfill").appended == 0


def test_replay_universe_rules_exclusions_liquidity_gate_and_fx_policy() -> None:
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

    nok = next(item.id for item in config.universe.etfs if item.currency == "NOK" and item.id in config.universe.enabled_ids)
    foreign = pd.concat([prices, _series(nok, CALENDAR, 7, volume=1e6, currency="NOK")], ignore_index=True)
    days = pd.bdate_range("2020-12-01", "2023-01-31")
    fx = pd.DataFrame(
        {"as_of_date": [day.date().isoformat() for day in days], "base_currency": "NOK", "quote_currency": "EUR", "pair": "NOK/EUR",
         "rate": 0.1, "source": "test", "ingested_at": pd.Timestamp("2023-02-01", tz="UTC"), "staleness_status": "ok"}
    )
    strict = score_backfill.score_as_of(config, foreign, AS_OF, fx_rates=fx)[1]
    assert "fx_unavailable" in strict.loc[strict["instrument_id"].eq(nok), "reasons"].iloc[0]  # ingested after the date: not known
    relaxed_fx = score_backfill._apply_fx_known_policy(fx, "rate_date")
    relaxed = score_backfill.score_as_of(config, foreign, AS_OF, fx_rates=relaxed_fx)[1]
    assert relaxed.loc[relaxed["instrument_id"].eq(nok), "reasons"].iloc[0] == ""  # rate known at the end of its own date
    with pytest.raises(ValueError):
        score_backfill._apply_fx_known_policy(fx, "anything")  # type: ignore[arg-type]
