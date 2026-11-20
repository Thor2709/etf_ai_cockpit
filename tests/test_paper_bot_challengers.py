"""PR-E: challenger inputs B2-o and B1-r, and feature vintages (SDD C6, C9). Fixtures only; no network."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from etf_cockpit.data.universe_membership import record_listing_capture
from etf_cockpit.features.feature_store import BUILTIN_FEATURES, FeatureDefinition, LocalFeatureStore
from etf_cockpit.features import panel as panel_module
from etf_cockpit.features.panel import PITPanelInputs, build_pit_panel
from etf_cockpit.portfolio import paper_bots
from etf_cockpit.validation.protocol import ValidationSpec

PRICES = Path("data/validated/prices/prices_daily.parquet")
FX = Path("data/clean/fx.parquet")
VINTAGES = Path("data/derived/feature_vintages")
SCOPE = "listing:sp500:all"
FEATURE_IDS = tuple(item.feature_id for item in BUILTIN_FEATURES)


def _write(root: Path, relative: Path, frame: pd.DataFrame) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _at(day: pd.Timestamp, clock: str) -> datetime:
    return datetime.fromisoformat(f"{pd.Timestamp(day).date().isoformat()}T{clock}+00:00")


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _bars(instrument: str, days, closes, *, currency: str = "EUR") -> pd.DataFrame:
    return pd.DataFrame({
        "etf_id": instrument, "date": pd.DatetimeIndex(days).date, "adjusted_close": closes, "close": closes,
        "volume": 1000.0, "currency": currency, "is_adjusted": True,
        "known_at": [_iso(_at(day, "18:00:00")) for day in days],
    })


def _vintage(root: Path, day, known_at: datetime, values: dict[str, list[float]]) -> None:
    rows = [
        {"instrument_id": instrument, "etf_id": instrument, "date": pd.Timestamp(day).date(),
         **dict(zip(FEATURE_IDS, features)), "known_at": _iso(known_at), "available_at": _iso(known_at),
         "pit_grade": "observed"}
        for instrument, features in values.items()
    ]
    _write(root, VINTAGES / f"{pd.Timestamp(day).date().isoformat()}.parquet", pd.DataFrame(rows))


def test_b2o_weights_equal_a_manual_eur_conversion_and_skip_unusable_rows(tmp_path: Path) -> None:
    pytest.importorskip("skfolio")
    from etf_cockpit.portfolio import paper_bot_challengers as challengers

    days = pd.bdate_range("2025-01-01", periods=205)
    good_days, extra_days = days[:200], days[200:]
    cutoff = _at(days[-1], "21:00:00") + timedelta(days=3)
    rng = np.random.default_rng(7)
    good = pd.concat([
        _bars(name, good_days, 100.0 * np.cumprod(1.0 + rng.normal(0.0004, 0.006 + 0.002 * index, len(good_days))), currency=currency)
        for index, (name, currency) in enumerate((("AAA", "USD"), ("BBB", "USD"), ("CCC", "EUR")))
    ], ignore_index=True)
    # Excluded rows: not adjusted (AAA), known after the cut-off (BBB). The first 10 USD sessions have no FX rate.
    unadjusted = _bars("AAA", extra_days, np.full(len(extra_days), 900.0), currency="USD").assign(is_adjusted=False)
    late = _bars("BBB", extra_days, np.full(len(extra_days), 900.0), currency="USD").assign(known_at=_iso(cutoff + timedelta(hours=1)))
    fx_days = days[10:]
    rates = 0.9 + 0.05 * np.sin(np.arange(len(fx_days)) / 9.0)
    _write(tmp_path, PRICES, pd.concat([good, unadjusted, late], ignore_index=True))
    _write(tmp_path, FX, pd.DataFrame({
        "as_of_date": fx_days.date, "base_currency": "USD", "quote_currency": "EUR", "rate": rates,
        "source": "fixture", "ingested_at": [_iso(_at(day, "17:00:00")) for day in fx_days],
    }))

    manual = good.copy()
    usd = manual["currency"].eq("USD")
    manual.loc[usd, "adjusted_close"] *= manual.loc[usd, "date"].map(dict(zip(fx_days.date, rates)))
    manual = manual.dropna(subset=["adjusted_close"])
    ids = ["AAA", "BBB", "CCC"]
    expected = paper_bots.optimiser_challenger_engine(manual)(ids, cutoff)

    engines, report = challengers.build_challenger_engines(tmp_path, cutoff)
    actual = engines["sk_min_cvar"](ids, cutoff)

    assert expected is not None and actual is not None
    assert actual.keys() == expected.keys()
    assert [actual[key] for key in ids] == pytest.approx([expected[key] for key in ids], abs=1e-9)
    assert report["sk_min_cvar"]["status"] == "available"

    # A price store without per-bar known_at admits no row: the engine has no weights.
    _write(tmp_path, PRICES, good.drop(columns=["known_at"]))
    engines, _ = challengers.build_challenger_engines(tmp_path, cutoff)
    assert engines["sk_min_cvar"](ids, cutoff) is None


def test_b2o_key_is_absent_without_skfolio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.portfolio import paper_bot_challengers as challengers

    real = challengers.find_spec
    monkeypatch.setattr(challengers, "find_spec", lambda name: None if name == "skfolio" else real(name))
    engines, report = challengers.build_challenger_engines(tmp_path, datetime(2026, 11, 20, 22, 0, tzinfo=timezone.utc))

    assert "sk_min_cvar" not in engines
    assert engines["gbdt_rank_63"] == {}
    assert report["sk_min_cvar"]["status"] == "unavailable"


def test_b1r_short_history_gives_no_scores_and_lists_the_failed_preflight(tmp_path: Path) -> None:
    pytest.importorskip("lightgbm")
    from etf_cockpit.portfolio import paper_bot_challengers as challengers

    days = pd.bdate_range("2026-10-01", periods=30)
    _write(tmp_path, PRICES, pd.concat([_bars(name, days, np.linspace(100.0, 110.0, len(days))) for name in ("AAA", "BBB", "VWCE")]))
    decision = _at(days[-1], "21:40:00")
    record_listing_capture([{"instrument_id": "AAA"}, {"instrument_id": "BBB"}], "fixture", SCOPE,
                           _iso(decision - timedelta(minutes=9)), root=tmp_path)
    _vintage(tmp_path, days[-1], decision, {"AAA": [0.1] * 6, "BBB": [0.2] * 6})

    engines, report = challengers.build_challenger_engines(tmp_path, decision + timedelta(minutes=1))

    assert engines["gbdt_rank_63"] == {}
    assert report["gbdt_rank_63"]["status"] == "insufficient_evidence"
    # The ranker's fold check runs before its minima: one decision date cannot hold the walk-forward split.
    assert report["gbdt_rank_63"]["preflight"] == [
        "at least 248 observations are required for this validation spec, including two post-purge training observations"
    ]


def test_b1r_gives_no_scores_when_the_latest_vintage_is_not_from_the_cutoff_night(tmp_path: Path) -> None:
    pytest.importorskip("lightgbm")
    from etf_cockpit.portfolio import paper_bot_challengers as challengers

    days = pd.bdate_range("2026-10-01", periods=30)
    _write(tmp_path, PRICES, pd.concat([_bars(name, days, np.linspace(100.0, 110.0, len(days))) for name in ("AAA", "BBB", "VWCE")]))
    previous = _at(days[-2], "21:40:00")  # tonight (days[-1]) wrote no vintage: only last night's exists
    record_listing_capture([{"instrument_id": "AAA"}, {"instrument_id": "BBB"}], "fixture", SCOPE,
                           _iso(previous - timedelta(minutes=9)), root=tmp_path)
    _vintage(tmp_path, days[-2], previous, {"AAA": [0.1] * 6, "BBB": [0.2] * 6})
    tonight = _at(days[-1], "21:41:00")

    engines, report = challengers.build_challenger_engines(tmp_path, tonight)

    assert engines["gbdt_rank_63"] == {}
    assert report["gbdt_rank_63"]["decision_time"] == pd.Timestamp(previous).isoformat()
    assert report["gbdt_rank_63"]["preflight"] == [
        f"latest decision {days[-2].date()} is not on the cut-off day {days[-1].date()}"
    ]


def test_b1r_fits_and_scores_on_a_vintage_fixture_that_meets_the_minima(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("lightgbm")
    from etf_cockpit.portfolio import paper_bot_challengers as challengers

    # One decision every 5 sessions; the split counts decision dates, so its purge (13 dates) covers 63 sessions.
    monkeypatch.setattr(challengers, "_RANKER_SPEC", ValidationSpec(
        n_splits=2, test_size=15, horizon=13, final_test_size=20, embargo=0, bootstrap_repetitions=1,
    ))
    sessions = xcals.get_calendar("XETR").sessions_in_range("2023-01-02", "2026-01-01")[:700]
    members = [f"S{number:02d}" for number in range(20)]
    rng = np.random.default_rng(3)
    _write(tmp_path, PRICES, pd.concat([
        _bars(name, sessions, 100.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.01, len(sessions))))
        for name in [*members, "VWCE"]
    ], ignore_index=True))
    decisions = []
    for day in sessions[0:650:5]:
        decision = _at(day, "21:40:00")
        _vintage(tmp_path, day, decision, {name: list(rng.normal(size=6)) for name in members})
        decisions.append(decision)
    # S19 has no row in tonight's vintage: its older vintage must not be carried forward into a score.
    _vintage(tmp_path, sessions[645], decisions[-1], {name: list(rng.normal(size=6)) for name in members[:-1]})

    def ledger(scope: str, cutoff, *, root: Path) -> pd.DataFrame:
        # Stands in for 130 nightly ledger captures (about 0.8 s each); the real ledger read is in the short-history test.
        assert scope == SCOPE and root == tmp_path.resolve()
        day = pd.Timestamp(cutoff).date().isoformat()
        return pd.DataFrame({"instrument_id": members, "valid_from": day, "valid_to": None, "snapshot_date": day,
                             "snapshot_complete": True, "known_at": _iso(pd.Timestamp(cutoff) - timedelta(minutes=9))})

    monkeypatch.setattr(panel_module, "membership_frame", ledger)

    engines, report = challengers.build_challenger_engines(tmp_path, decisions[-1] + timedelta(minutes=1))

    assert report["gbdt_rank_63"]["status"] == "fitted", report
    assert report["gbdt_rank_63"]["decision_time"] == pd.Timestamp(decisions[-1]).isoformat()
    scores = engines["gbdt_rank_63"]
    assert set(scores) == set(members[:-1])
    assert all(np.isfinite(value) for value in scores.values())


def test_feature_vintage_is_written_once_and_the_panel_accepts_it(tmp_path: Path) -> None:
    from etf_cockpit.application.feature_observations import record_feature_observations

    days = pd.bdate_range("2026-07-01", periods=80)
    session = days[-1].date()
    known_at = _at(days[-1], "21:40:00")
    late = _bars("LATE", days, np.linspace(50.0, 60.0, len(days)))
    late.loc[late.index[-1], "known_at"] = _iso(known_at + timedelta(minutes=1))  # this session's bar is known too late
    vwce = _bars("VWCE", days, np.linspace(100.0, 120.0, len(days)))
    _write(tmp_path, PRICES, pd.concat([_bars("AAA", days, np.linspace(10.0, 14.0, len(days)), currency="USD"), vwce, late]))
    _write(tmp_path, FX, pd.DataFrame({
        "as_of_date": days.date, "base_currency": "USD", "quote_currency": "EUR", "rate": 0.9,
        "source": "fixture", "ingested_at": [_iso(_at(day, "17:00:00")) for day in days],
    }))

    path = record_feature_observations(tmp_path, session, known_at)

    assert path == tmp_path / VINTAGES / f"{session.isoformat()}.parquet"
    vintage = pd.read_parquet(path)
    assert sorted(vintage["instrument_id"]) == ["AAA", "VWCE"]
    assert vintage["pit_grade"].eq("observed").all()
    assert vintage["known_at"].eq(_iso(known_at)).all() and vintage["available_at"].eq(_iso(known_at)).all()
    assert pd.to_datetime(vintage["date"]).dt.date.eq(session).all()
    written = path.read_bytes()
    assert record_feature_observations(tmp_path, session, known_at + timedelta(hours=1)) is None
    assert path.read_bytes() == written

    membership = pd.DataFrame([{
        "instrument_id": "AAA", "snapshot_date": session.isoformat(), "snapshot_complete": True,
        "valid_from": session.isoformat(), "valid_to": None, "known_at": _iso(known_at - timedelta(minutes=9)),
        "pit_grade": "observed",
    }])
    benchmark = vwce.rename(columns={"etf_id": "instrument_id"})
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("vintage.momentum_60d", "momentum_60d", source_dataset="feature_vintages"))
    panel = build_pit_panel(
        [known_at], membership, ["vintage.momentum_60d"], horizons=(1,),
        inputs=PITPanelInputs(store, vintage, benchmark, benchmark),
    )
    assert panel["instrument_id"].tolist() == ["AAA"]
    assert panel["vintage.momentum_60d"].notna().all()


def test_feature_vintage_ignores_fx_ingested_after_its_known_at(tmp_path: Path) -> None:
    from etf_cockpit.application.feature_observations import record_feature_observations

    days = pd.bdate_range("2026-07-01", periods=80)
    known_at = _at(days[-1], "21:40:00")
    closes = np.linspace(10.0, 14.0, len(days))
    _write(tmp_path, PRICES, pd.concat([_bars("AAA", days, closes, currency="USD"), _bars("VWCE", days, closes)]))
    ingested = [_iso(_at(day, "17:00:00")) for day in days]
    ingested[-1] = _iso(known_at + timedelta(minutes=20))  # after t_S, before the session end 23:59:59
    _write(tmp_path, FX, pd.DataFrame({
        "as_of_date": days.date, "base_currency": "USD", "quote_currency": "EUR",
        "rate": [0.9] * (len(days) - 1) + [2.0], "source": "fixture", "ingested_at": ingested,
    }))

    vintage = pd.read_parquet(record_feature_observations(tmp_path, days[-1].date(), known_at)).set_index("instrument_id")

    # The late 2.0 rate is unseen; the session keeps the last known 0.9 rate, so the EUR return is the local return.
    assert vintage.loc["AAA", "return_1d_log"] == pytest.approx(np.log(closes[-1] / closes[-2]))
