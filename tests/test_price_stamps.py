"""C1 per-bar price stamps (docs/architecture/forward-paper-path.md, contract C1)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from etf_cockpit.application import universe_fetch as fetch
from etf_cockpit.data import import_pipeline
from etf_cockpit.data.providers import ManualLocalFileProvider, ProviderResult
from etf_cockpit.portfolio import paper_bots
from etf_cockpit.portfolio.paper_bots_execution import PRICE_FILE_RELATIVE, PriceBook
from tests.application.test_incremental_price_refresh import _bar, _price_frame, _result
from tests.test_fetch_full_universe import FakeProvider, _options, _prices, _root

_UTC = timezone.utc
_T0 = datetime(2026, 11, 2, 1, 0, tzinfo=_UTC)
_T1 = datetime(2026, 11, 9, 1, 0, tzinfo=_UTC)
_DAYS = (date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30))
_STAMPS = ["ingested_at", "known_at", "available_at", "actions_evidenced"]


def _stamp(stored, incoming, retrieved_at):
    return import_pipeline.stamp_price_availability(stored, incoming, retrieved_at=retrieved_at)


def _frame(closes=(100.0, 101.0, 102.0), adjusted=None, **columns):
    adjusted = closes if adjusted is None else adjusted
    frame = _price_frame("AAA", [_bar(day, close, adj) for day, close, adj in zip(_DAYS, closes, adjusted)])
    return frame.assign(**columns)


def _ts(value):
    return pd.Timestamp(value).tz_convert("UTC")


def _commit(result, root):
    return import_pipeline.commit_price_import(
        result,
        clean_path=root / "data" / "clean" / "prices.parquet",
        compatibility_path=root / PRICE_FILE_RELATIVE,
        raw_dir=root / "data" / "raw" / "prices",
        snapshots_dir=root / "data" / "snapshots" / "prices",
    )


def test_new_bar_gets_fetch_time_and_close_bound():
    today = date(2026, 11, 8)
    incoming = _price_frame("AAA", [_bar(_DAYS[2]), _bar(today)])
    fetched = datetime(2026, 11, 8, 15, 0, tzinfo=_UTC)

    stamped = _stamp(None, incoming, fetched)

    assert stamped["ingested_at"].map(_ts).eq(_ts(fetched)).all()
    assert stamped["known_at"].map(_ts).eq(_ts(fetched)).all()
    assert _ts(stamped["available_at"].iloc[0]) == pd.Timestamp("2026-10-30T23:59:59Z")
    assert _ts(stamped["available_at"].iloc[1]) == _ts(fetched)
    assert stamped["actions_evidenced"].tolist() == [True, True]


def test_unchanged_bar_keeps_stamps():
    stored = _stamp(None, _frame(), _T0)

    stamped = _stamp(stored, _frame(), _T1)

    pd.testing.assert_frame_equal(stamped[_STAMPS], stored[_STAMPS])


def test_raw_and_adjusted_revisions_restamp_but_uniform_rebase_does_not():
    stored = _stamp(None, _frame(), _T0)

    raw = _stamp(stored, _frame(closes=(100.0, 101.5, 102.0)), _T1)
    adjusted_only = _stamp(stored, _frame(adjusted=(100.0, 100.5, 102.0)), _T1)
    rebased = _stamp(stored, _frame(adjusted=(98.0, 98.98, 99.96)), _T1)
    dividend = _stamp(stored, _frame(dividends=[0.0, 0.25, 0.0]), _T1)

    for revised in (raw, adjusted_only, dividend):
        assert _ts(revised["known_at"].iloc[1]) == _ts(_T1)
        assert _ts(revised["available_at"].iloc[1]) == _ts(_T1)
        assert _ts(revised["known_at"].iloc[0]) == _ts(_T0)
    assert rebased["known_at"].map(_ts).eq(_ts(_T0)).all()
    assert rebased["adjusted_close"].tolist() == [98.0, 98.98, 99.96]


def test_local_file_import_has_no_action_evidence(tmp_path):
    source = tmp_path / "prices.csv"
    _frame().drop(columns=["actions_evidenced", "fetched_at", "ingested_at", "available_at"]).to_csv(source, index=False)

    _commit(ManualLocalFileProvider().import_file(source, "prices"), tmp_path)

    stored = pd.read_parquet(tmp_path / PRICE_FILE_RELATIVE)
    assert stored["actions_evidenced"].dtype == bool
    assert not stored["actions_evidenced"].any()


def test_local_file_claiming_action_evidence_stores_false(tmp_path):
    source = tmp_path / "prices.csv"
    _frame().drop(columns=["fetched_at", "ingested_at", "available_at"]).to_csv(source, index=False)

    _commit(ManualLocalFileProvider().import_file(source, "prices"), tmp_path)

    assert not pd.read_parquet(tmp_path / PRICE_FILE_RELATIVE)["actions_evidenced"].any()


def test_instrument_id_only_file_commits_twice_and_keeps_stamps(tmp_path):
    frame = _frame().drop(columns=["actions_evidenced", "fetched_at", "ingested_at", "available_at"])
    frame = frame.rename(columns={"etf_id": "instrument_id"})
    result = ProviderResult("manual_local_file", "prices", "ok", "local file", frame)

    _commit(result, tmp_path)
    first = pd.read_parquet(tmp_path / PRICE_FILE_RELATIVE)
    _commit(result, tmp_path)

    second = pd.read_parquet(tmp_path / PRICE_FILE_RELATIVE)
    assert second["known_at"].tolist() == first["known_at"].tolist()


def test_staging_keeps_the_provider_per_row_action_evidence(tmp_path):
    class PartlyEvidenced(FakeProvider):
        def fetch(self, item, start, end):
            frame = super().fetch(item, start, end)
            return frame.assign(actions_evidenced=[index != 0 for index in range(len(frame))])

    options = _options(_root(tmp_path / "root"))
    options.staging.mkdir()
    result_path = options.staging / "worker.json"

    fetch._worker([fetch.FetchItem("prices", "B", "B", "EUR")], options, options.start, options.end,
                  result_path, PartlyEvidenced)

    row, = json.loads(result_path.read_text())
    staged = pd.read_parquet(row["path"])
    assert staged["actions_evidenced"].tolist() == [False, True, True, True]


def test_recovery_copies_ingested_at_and_leaves_null_stamps_null():
    legacy = _frame().drop(columns=["actions_evidenced"])
    legacy["ingested_at"] = legacy["ingested_at"].astype(object)
    legacy.loc[2, ["ingested_at", "available_at"]] = None

    stamped = _stamp(legacy, _frame(), _T1)

    assert _ts(stamped["known_at"].iloc[0]) == _ts(legacy["ingested_at"].iloc[0])
    assert _ts(stamped["available_at"].iloc[0]) == _ts(legacy["available_at"].iloc[0])
    assert stamped.loc[2, ["ingested_at", "known_at", "available_at"]].isna().all()
    assert stamped["actions_evidenced"].all()  # the action-requesting fetch returned the same bars (W2-F item 5)


def test_promote_staging_uses_the_same_stamps_as_commit(tmp_path):
    root = _root(tmp_path / "root")

    report = fetch.fetch_full_universe(_options(root, promote=True), provider_factory=FakeProvider)

    assert report["promotion"] == "committed"
    promoted = _prices(root)
    retrieved = promoted["known_at"].iloc[0].to_pydatetime()
    assert retrieved > datetime(2024, 2, 1, 12, tzinfo=_UTC)
    expected = _stamp(None, promoted.drop(columns=_STAMPS[:3]), retrieved)
    pd.testing.assert_frame_equal(promoted[_STAMPS], expected[_STAMPS], check_dtype=False)


def test_price_book_loads_after_one_commit(tmp_path):
    _commit(_result(_frame()), tmp_path)

    book = PriceBook.from_root(tmp_path, benchmark_id="AAA")

    assert book.error is None
    assert book.sessions == list(_DAYS)


def test_no_bar_known_after_the_cutoff_reaches_price_book_or_optimiser(tmp_path, monkeypatch):
    stored = _stamp(None, _frame(), _T0)
    current = _stamp(stored, _frame(closes=(100.0, 101.0, 105.0)), _T1)
    path = tmp_path / PRICE_FILE_RELATIVE
    path.parent.mkdir(parents=True)
    current.to_parquet(path, index=False)
    cut = _T0 + timedelta(days=1)

    book = PriceBook.from_root(tmp_path, benchmark_id="AAA")
    seen = []
    monkeypatch.setattr(paper_bots, "returns_from_adjusted_prices", lambda frame, **_: seen.append(frame) or pd.DataFrame())
    paper_bots.optimiser_challenger_engine(pd.read_parquet(path))(["AAA"], cut)

    assert book.bar("AAA", _DAYS[1], known_by=cut) is not None
    assert book.bar("AAA", _DAYS[2], known_by=cut) is None
    assert seen and seen[0]["known"].le(cut).all()
    assert _DAYS[2] not in set(seen[0]["date"].dt.date)


def test_rollback_restamps_bars_that_differ_from_the_current_store(tmp_path):
    _commit(_result(_frame()), tmp_path)
    first = pd.read_parquet(tmp_path / PRICE_FILE_RELATIVE)
    _commit(_result(_frame(closes=(100.0, 101.0, 105.0))), tmp_path)
    started = pd.Timestamp.now(tz="UTC")

    import_pipeline.rollback_latest_price_import(
        clean_path=tmp_path / "data" / "clean" / "prices.parquet",
        compatibility_path=tmp_path / PRICE_FILE_RELATIVE,
        snapshots_dir=tmp_path / "data" / "snapshots" / "prices",
    )

    restored = pd.read_parquet(tmp_path / PRICE_FILE_RELATIVE)
    assert restored["close"].tolist() == [100.0, 101.0, 102.0]
    assert restored["known_at"].iloc[:2].tolist() == first["known_at"].iloc[:2].tolist()
    assert _ts(restored["known_at"].iloc[2]) >= started


def test_metadata_checksum_changes_when_stamps_change(tmp_path):
    fresh = _commit(_result(_frame()), tmp_path / "fresh")
    seeded = tmp_path / "seeded"
    (seeded / "data" / "clean").mkdir(parents=True)
    _stamp(None, _frame(), _T0).to_parquet(seeded / "data" / "clean" / "prices.parquet", index=False)

    kept = _commit(_result(_frame()), seeded)

    assert fresh.checksum != kept.checksum
    assert json.loads(kept.metadata_path.read_text(encoding="utf-8"))["checksum"] == kept.checksum
