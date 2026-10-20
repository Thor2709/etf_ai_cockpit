"""Issue #951 (DQ1): price import and OHLCV validation integrity."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.application import data_service
from etf_cockpit.application.data_service import (
    DataService,
    _carry_forward_failed_instruments,
    _unused_quarantine_path,
)
from etf_cockpit.data.import_pipeline import commit_price_import
from etf_cockpit.data.price_quarantine import quarantine_invalid_ohlc
from etf_cockpit.data.provenance import metadata_from_frame, sha256_dataframe
from etf_cockpit.data.providers import ManualLocalFileProvider, ProviderResult
from etf_cockpit.data.retrieval_batch import BatchRetriever
from etf_cockpit.data.validation import validate_prices
from etf_cockpit.features.feature_pipeline import compute_features
from etf_cockpit.features.synthetic_scenarios import (
    SyntheticScenarioError,
    SyntheticScenarioGenerator,
    SyntheticScenarioSpec,
)

AS_OF = date(2026, 6, 26)


def _rows(etf_id: str, dates, price: float = 100.0) -> pd.DataFrame:
    dates = list(dates)
    return pd.DataFrame(
        {
            "date": dates,
            "etf_id": etf_id,
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
            "adjusted_close": price,
            "volume": 1000.0,
            "currency": "EUR",
        }
    )


def _past(count: int) -> list[date]:
    return [d.date() for d in pd.bdate_range(end=pd.Timestamp(AS_OF), periods=count)]


def _codes(report, severity: str | None = None) -> set[str]:
    return {i.code for i in report.issues if severity is None or i.severity == severity}


# --- C014-N001 / A021: history minimum -------------------------------------------------------------


def test_history_minimum_ignores_rows_after_as_of_and_duplicate_dates():
    past = _past(251)
    future = [date(2026, 6, 29), date(2026, 6, 30)]
    report = validate_prices(_rows("AAA", [*past, *future]), as_of_date=AS_OF)
    assert "insufficient_history" in _codes(report, "block")
    assert "future_dated_rows" in _codes(report)

    padded = pd.concat([_rows("AAA", past), _rows("AAA", past[:5])], ignore_index=True)
    report = validate_prices(padded, as_of_date=AS_OF)
    assert "insufficient_history" in _codes(report, "block")  # 256 rows but 251 unique dates
    assert "duplicate_rows" in _codes(report, "warning")

    enough = validate_prices(_rows("AAA", _past(252)), as_of_date=AS_OF)
    assert "insufficient_history" not in _codes(enough)


def test_conflicting_duplicate_dates_block():
    frame = pd.concat([_rows("AAA", _past(252)), _rows("AAA", _past(252)[-1:], price=105.0)], ignore_index=True)
    assert "conflicting_duplicate_rows" in _codes(validate_prices(frame, as_of_date=AS_OF), "block")


# --- A021 / A116 / A03-C2-N004 / C023-N002: invalid rows block --------------------------------------


def _mutated(**changes) -> pd.DataFrame:
    frame = _rows("AAA", _past(252))
    for column, value in changes.items():
        frame[column] = frame[column].astype(object)
        frame.loc[frame.index[-1], column] = value
    return frame


@pytest.mark.parametrize(
    ("frame", "code"),
    [
        (_mutated(etf_id=None), "missing_etf_id"),
        (_mutated(etf_id="  "), "missing_etf_id"),
        (_mutated(volume=-5.0), "negative_volume"),
        (_mutated(volume="Infinity"), "invalid_price_values"),
        (_mutated(volume="-inf"), "invalid_price_values"),
        (_mutated(close=float("inf")), "invalid_price_values"),
        (_mutated(low=-1.0), "invalid_ohlc"),
        (_mutated(open=-1.0), "invalid_ohlc"),
        (_mutated(high=90.0, low=95.0), "invalid_ohlc"),  # high/low inverted only
    ],
)
def test_invalid_rows_produce_a_block_issue_never_a_silent_drop(frame, code):
    report = validate_prices(frame, as_of_date=AS_OF)
    assert code in _codes(report, "block"), [(i.code, i.severity) for i in report.issues]
    assert report.status == "Blocked"


# --- A002-N001 / A022: checksum after quarantine and atomic publication ------------------------------


def _import_result(frame: pd.DataFrame) -> ProviderResult:
    metadata = metadata_from_frame(
        frame, source_name="t", source_type="prices", as_of_date=AS_OF, provider_or_manual_source="t"
    )
    return ProviderResult("yfinance", "prices", "ok", "test", frame, metadata)


def test_quarantine_recomputes_checksum_and_commit_persists_the_filtered_checksum(tmp_path):
    good = _rows("AAA", _past(2))
    bad = _rows("AAA", _past(3)[-1:]).assign(high=1.0)  # high below open/close
    result = _import_result(pd.concat([good, bad], ignore_index=True))
    original_checksum = result.metadata.checksum
    clean, quarantined = quarantine_invalid_ohlc(result)
    assert len(quarantined) == 1
    assert clean.metadata.checksum == sha256_dataframe(clean.data) != original_checksum

    # Even a stale metadata checksum can never be persisted next to a different frame.
    stale = ProviderResult(clean.provider_name, "prices", "ok", "t", clean.data, result.metadata)
    commit = commit_price_import(
        stale,
        clean_path=tmp_path / "clean" / "prices.parquet",
        compatibility_path=tmp_path / "compat" / "prices.parquet",
        raw_dir=tmp_path / "raw",
        snapshots_dir=tmp_path / "snap",
    )
    persisted = pd.read_parquet(commit.clean_path)
    assert commit.checksum == sha256_dataframe(clean.data)
    meta = pd.read_json(commit.metadata_path, typ="series")
    assert meta["checksum"] == commit.checksum
    assert meta["metadata"]["checksum"] == commit.checksum
    assert len(persisted) == len(clean.data) == 2


def test_prices_and_metadata_are_published_in_one_atomic_group(tmp_path, monkeypatch):
    from etf_cockpit.data import import_pipeline

    seen: list[list[str]] = []
    real = import_pipeline.atomic_write_group

    def spy(requests):
        requests = tuple(requests)
        seen.append([Path(r.destination).name for r in requests])
        return real(requests)

    monkeypatch.setattr(import_pipeline, "atomic_write_group", spy)
    commit_price_import(
        _import_result(_rows("AAA", _past(3))),
        clean_path=tmp_path / "clean" / "prices.parquet",
        compatibility_path=tmp_path / "compat" / "prices.parquet",
        raw_dir=tmp_path / "raw",
        snapshots_dir=tmp_path / "snap",
    )
    assert len(seen) == 1
    assert any(name.endswith("_prices_metadata.json") for name in seen[0])
    assert seen[0].count("prices.parquet") == 2


def test_same_day_quarantine_never_overwrites_an_earlier_one(tmp_path):
    first = _unused_quarantine_path(tmp_path, AS_OF)
    first.write_bytes(b"x")
    second = _unused_quarantine_path(tmp_path, AS_OF)
    second.write_bytes(b"y")
    third = _unused_quarantine_path(tmp_path, AS_OF)
    assert len({first, second, third}) == 3
    assert first.read_bytes() == b"x"


# --- A002-N002 / A022: partial refresh ---------------------------------------------------------------


def _fresh(ids, day="2026-10-08") -> pd.DataFrame:
    return pd.DataFrame({"etf_id": list(ids), "date": [pd.Timestamp(day)] * len(ids), "close": [10.0] * len(ids)})


def test_partial_refresh_with_a_missing_configured_ticker_is_not_ok(tmp_path):
    partial = ProviderResult(
        "yfinance", "prices", "error", "Partial refresh rejected; no incomplete Yahoo Finance price set was committed. BBB/BBB.OL: no rows returned", _fresh(["AAA"])
    )
    for expected in (("AAA", "BBB"), None):  # explicit configured ids, and inferred from the provider message
        result = _carry_forward_failed_instruments(partial, clean_path=tmp_path / "none.parquet", expected_ids=expected)
        assert not result.ok and result.status == "unavailable"
        assert result.missing_ids == ("BBB",)
        assert "BBB" in result.message

    # A ticker with stored history is carried forward (stale, never filled) and the refresh stays ok.
    stored = tmp_path / "prices.parquet"
    _fresh(["AAA", "BBB"], "2026-10-01").to_parquet(stored, index=False)
    assert _carry_forward_failed_instruments(partial, clean_path=stored, expected_ids=("AAA", "BBB")).ok


class _FakeProvider:
    barrier = threading.Barrier(2, timeout=10)
    frames: dict[str, pd.DataFrame] = {}

    def __init__(self, ids: tuple[str, ...]):
        self.ids = ids

    def _symbol_map(self, symbols):
        return {"AAA": "AAA", "BBB": "BBB"}

    def fetch_prices(self, symbols, start, end):
        self.barrier.wait()  # both refreshes fetch before either merges with the stored prices
        data = _fresh(self.ids, "2026-10-08").assign(
            open=10.0, high=11.0, low=9.0, adjusted_close=10.0, volume=1.0, currency="EUR"
        )
        missing = sorted(set(("AAA", "BBB")) - set(self.ids))
        message = "Partial refresh rejected; no incomplete Yahoo Finance price set was committed. " + "; ".join(
            f"{m}/{m}: no rows returned" for m in missing
        )
        return ProviderResult("yfinance", "prices", "error", message, data, metadata_from_frame(data, source_name="y", source_type="prices", as_of_date=date(2026, 10, 8)))


def test_two_concurrent_partial_refreshes_keep_both_updates(tmp_path, monkeypatch):
    clean = tmp_path / "clean" / "prices.parquet"
    seed = _fresh(["AAA", "BBB"], "2026-10-01").assign(open=10.0, high=11.0, low=9.0, adjusted_close=10.0, volume=1.0, currency="EUR")
    clean.parent.mkdir(parents=True)
    seed.to_parquet(clean, index=False)
    monkeypatch.setattr(data_service, "CLEAN_DIR", clean.parent)
    monkeypatch.setattr(data_service, "ROOT", tmp_path)
    monkeypatch.setattr(data_service, "_refresh_stock_fundamentals", lambda *_: "")
    # Freeze the refresh clock one day after the fake provider's last bar: against the real date the
    # staleness gate would (correctly) block these fixed 2026-10-08 prices once they age.
    class _FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 9)

    monkeypatch.setattr(data_service, "date", _FrozenDate)
    real_commit = data_service.commit_price_import
    monkeypatch.setattr(
        data_service,
        "commit_price_import",
        lambda result: real_commit(
            result,
            clean_path=clean,
            compatibility_path=tmp_path / "compat" / "prices.parquet",
            raw_dir=tmp_path / "raw",
            snapshots_dir=tmp_path / "snap",
        ),
    )
    providers = {"AAA": _FakeProvider(("AAA",)), "BBB": _FakeProvider(("BBB",))}
    pending = list(providers.values())
    monkeypatch.setattr(data_service.YFinanceProvider, "from_config", classmethod(lambda cls, config: pending.pop()))
    monkeypatch.setattr(data_service, "validate_prices", lambda *a, **k: validate_prices(*a, **{**k, "min_history_days": 1}))

    errors: list[BaseException] = []

    def run() -> None:
        try:
            DataService(config=None).refresh_yfinance_data(include_reference_data=False)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not errors, errors
    final = pd.read_parquet(clean)
    latest = final.groupby("etf_id")["date"].max()
    assert latest["AAA"] == pd.Timestamp("2026-10-08") and latest["BBB"] == pd.Timestamp("2026-10-08")


def test_checkpoint_write_failure_is_not_a_provider_retry(tmp_path, monkeypatch):
    calls: list[str] = []

    def downloader(symbol: str) -> dict:
        calls.append(symbol)
        return {"v": 1}

    retriever = BatchRetriever[dict](
        provider="t", cache_dir=tmp_path / "c", checkpoint_path=tmp_path / "cp.json", max_retries=2, sleep=lambda _s: None
    )

    def broken_cache(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(retriever, "_write_cache", broken_cache)
    result = retriever.retrieve(["AAA"], start=AS_OF, end=AS_OF, downloader=downloader)
    item = result.symbols["AAA"]
    assert calls == ["AAA"]  # the provider is not called again for a local persistence fault
    assert item.status == "failed" and item.error.startswith("checkpoint_failure")


# --- A101-N004: manual CSV dates ---------------------------------------------------------------------


def test_manual_csv_with_an_unparseable_date_is_a_row_error_not_ok(tmp_path):
    path = tmp_path / "prices.csv"
    path.write_text(
        "date,etf_id,open,high,low,close,adjusted_close,volume,currency\n"
        "2026-06-25,AAA,1,2,1,1,1,10,EUR\nnot-a-date,AAA,1,2,1,1,1,10,EUR\n",
        encoding="utf-8",
    )
    result = ManualLocalFileProvider().import_file(path, "prices")
    assert result.status == "error" and "rows 3" in result.message
    path.write_text(path.read_text(encoding="utf-8").replace("not-a-date", "2026-06-26"), encoding="utf-8")
    assert ManualLocalFileProvider().import_file(path, "prices").ok


# --- C101-N001 / C023: duplicates and synthetic generator --------------------------------------------


def test_equal_duplicate_rows_do_not_change_momentum():
    dates = _past(200)
    base = _rows("AAA", dates)
    base["adjusted_close"] = 100.0 * np.exp(np.cumsum(np.full(len(dates), 0.001)))
    duplicated = pd.concat([base, base.iloc[[150]]], ignore_index=True)
    clean = compute_features(base).set_index("date")["momentum_60d"]
    again = compute_features(duplicated).set_index("date")["momentum_60d"]
    pd.testing.assert_series_equal(clean, again)


def test_synthetic_dataset_hash_is_content_derived_and_specs_are_checked():
    generator = SyntheticScenarioGenerator()
    spec = SyntheticScenarioSpec(periods=30)
    first = generator.generate(spec)
    assert first.metadata["dataset_hash"] == generator.generate(spec).metadata["dataset_hash"]
    tampered = first.prices.copy()
    tampered.loc[tampered.index[3], "close"] = 1.0
    assert generator._metadata(spec, tampered, first.corporate_actions, first.data_quality, first.provider_conflicts, first.execution_events)["dataset_hash"] != first.metadata["dataset_hash"]

    for bad in (float("nan"), float("inf")):
        with pytest.raises(SyntheticScenarioError):
            SyntheticScenarioSpec(start_price=bad)
        with pytest.raises(SyntheticScenarioError):
            SyntheticScenarioSpec(annual_volatility=bad)
    with pytest.raises(SyntheticScenarioError):
        SyntheticScenarioSpec(start_date="nonsense")

    assert generator.validate(first)["status"] == "pass"
    invalid = first.prices.copy()
    invalid.loc[invalid.index[1], "adjusted_close"] = -5.0
    broken = type(first)(invalid, first.data_quality, first.corporate_actions, first.provider_conflicts, first.execution_events, first.metadata)
    assert generator.validate(broken)["status"] == "fail"
