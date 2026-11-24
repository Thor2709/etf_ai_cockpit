"""D8: VWCE benchmark history before 2019-07-29 from VWRL.AS (OD-2 b), labelled proxy."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data.providers import ProviderResult
from etf_cockpit.data.provenance import metadata_from_frame, sha256_dataframe
from etf_cockpit.portfolio.benchmark_reference import (
    VWCE_SPLICE_DATE,
    validate_vwce_proxy_series,
    vwce_benchmark_series,
)

KNOWN = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
SPLICE = pd.Timestamp(VWCE_SPLICE_DATE)
# 2019-07-24 is a VWRL.AS gap: no row, so no return and no level that day.
PROXY_DAYS = ["2019-07-22", "2019-07-23", "2019-07-25", "2019-07-26", "2019-07-29"]
PROXY_ADJ = [80.0, 80.8, 79.6, 80.4, 81.2]


def _proxy(**changes: object) -> pd.DataFrame:
    frame = pd.DataFrame({
        "date": [date.fromisoformat(day) for day in PROXY_DAYS], "etf_id": "VWRL.AS",
        "open": PROXY_ADJ, "high": [a + 1 for a in PROXY_ADJ], "low": PROXY_ADJ, "close": [a + 1 for a in PROXY_ADJ],
        "adjusted_close": PROXY_ADJ, "volume": 1000.0, "currency": "EUR", "provider_symbol": "VWRL.AS",
        "source": "yfinance", "is_adjusted": True, "dividends": [0.0, 0.0, 0.35, 0.0, 0.0], "stock_splits": 0.0,
        "capital_gains": 0.0, "actions_evidenced": True,
    })
    return frame.assign(**changes)


def _metadata(frame: pd.DataFrame):
    meta = metadata_from_frame(frame, source_name="yfinance", source_type="prices", as_of_date=None, currency="EUR")
    return dataclasses.replace(meta, ingested_at=KNOWN)


def _vwce(days: tuple[str, ...] = ("2019-07-25", "2019-07-29", "2019-07-30", "2019-07-31")) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(list(days)), "etf_id": "VWCE", "close": 70.0 + pd.Series(range(len(days)), dtype=float),
        "adjusted_close": 70.0 + pd.Series(range(len(days)), dtype=float), "currency": "EUR", "volume": 5,
        "known_at": pd.Timestamp("2026-11-03 12:20", tz="UTC"),
    })


def _stored_proxy() -> pd.DataFrame:
    return _proxy().assign(known_at=KNOWN, ingested_at=KNOWN)


def test_proxy_series_passes_its_own_check_and_fails_closed() -> None:
    frame = _proxy()
    assert validate_vwce_proxy_series(frame, known_at=KNOWN, provider_metadata=_metadata(frame)).status == "available"
    for bad, reason in (
        (_proxy(provider_symbol="VWRL.L"), "provider_identity_unverified:provider_symbol"),
        (_proxy(actions_evidenced=False), "corporate_action_evidence_missing"),
        (_proxy().iloc[:-1], "splice_anchor_missing"),
        (_proxy(adjusted_close=[80.0, 80.8, 40.0, 80.4, 81.2]), "split_or_adjustment_discontinuity:adjusted_close"),
    ):
        check = validate_vwce_proxy_series(bad, known_at=KNOWN, provider_metadata=_metadata(bad))
        assert check.status == "unavailable" and reason in check.reasons, (reason, check.reasons)
    tampered = validate_vwce_proxy_series(_proxy(volume=1.0), known_at=KNOWN, provider_metadata=_metadata(frame))
    assert "provider_provenance_unverified" in tampered.reasons


def test_own_rows_stay_byte_equal_and_earlier_vwce_rows_are_not_used() -> None:
    vwce = _vwce()
    series = vwce_benchmark_series(vwce, _stored_proxy())
    own = series.loc[series["benchmark_basis"].eq("own"), ["date", "etf_id", "adjusted_close", "currency", "known_at"]]
    expected = vwce.loc[vwce["date"].ge(SPLICE), ["date", "etf_id", "adjusted_close", "currency", "known_at"]]
    assert own.reset_index(drop=True).equals(expected.reset_index(drop=True))
    assert not series.loc[series["date"].lt(SPLICE), "benchmark_basis"].eq("own").any()


def test_rows_before_the_splice_are_labelled_proxy_and_known_at_their_session_close() -> None:
    series = vwce_benchmark_series(_vwce(), _stored_proxy())
    before = series.loc[series["date"].lt(SPLICE)]
    assert list(before["date"].dt.strftime("%Y-%m-%d")) == PROXY_DAYS[:-1]
    assert before["benchmark_basis"].eq("proxy").all() and before["proxy_source_id"].eq("VWRL.AS").all()
    assert before["pit_basis"].eq("reconstructed").all() and before["etf_id"].eq("VWCE").all()
    closes = before["date"].dt.tz_localize("UTC") + pd.Timedelta(hours=23, minutes=59, seconds=59)
    assert list(before["known_at"]) == list(closes)
    assert series.loc[series["date"].ge(SPLICE), "benchmark_basis"].eq("own").all()


def test_chained_level_is_continuous_at_the_splice_and_a_gap_stays_a_gap() -> None:
    series = vwce_benchmark_series(_vwce(), _stored_proxy()).set_index("date")["adjusted_close"]
    anchor = series.loc[SPLICE]
    assert anchor == 71.0  # VWCE's own first close from the splice date
    assert series.loc[pd.Timestamp("2019-07-26")] / anchor == pytest.approx(80.4 / 81.2, rel=1e-12)
    assert series.loc[pd.Timestamp("2019-07-25")] / series.loc[pd.Timestamp("2019-07-23")] == pytest.approx(79.6 / 80.8)
    assert pd.Timestamp("2019-07-24") not in series.index and series.notna().all()


def test_splice_without_a_vwce_row_on_the_splice_date_is_unavailable() -> None:
    assert vwce_benchmark_series(_vwce(("2019-07-30", "2019-07-31")), _stored_proxy()) is None
    assert vwce_benchmark_series(_vwce(), _stored_proxy().iloc[:-1]) is None


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "import_vwce_proxy.py"
    spec = importlib.util.spec_from_file_location("import_vwce_proxy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Provider:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame, self.calls = frame, []

    def fetch_prices(self, symbols, start_date, end_date):
        self.calls.append((list(symbols), start_date, end_date))
        return ProviderResult("yfinance", "prices", "ok", "fixture", self.frame, _metadata(self.frame))


def test_import_writes_only_the_reference_files_and_no_price_or_settings_file(tmp_path: Path) -> None:
    from etf_cockpit.core.versioning import current_settings_revision

    revision = current_settings_revision()
    provider = _Provider(_proxy())
    written = _script().import_vwce_proxy(tmp_path, provider=provider, known_at=KNOWN)
    assert provider.calls == [(["VWRL.AS"], date(2012, 5, 22), date(2019, 7, 30))]
    reference = tmp_path / "data" / "reference"
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")
                  if p.is_file() and not p.name.startswith(".atomic")) == [
        "data/reference/vwce_proxy_vwrl_as.json", "data/reference/vwce_proxy_vwrl_as.parquet"]
    assert written == reference / "vwce_proxy_vwrl_as.parquet"
    stored = pd.read_parquet(written)
    manifest = json.loads((reference / "vwce_proxy_vwrl_as.json").read_text(encoding="utf-8"))
    assert manifest["source_hash"] == sha256_dataframe(stored) and manifest["splice_date"] == "2019-07-29"
    assert manifest["provider_symbol"] == "VWRL.AS" and manifest["execution_allowed"] is False
    assert current_settings_revision() == revision


def test_import_writes_nothing_when_the_proxy_check_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="splice_anchor_missing"):
        _script().import_vwce_proxy(tmp_path, provider=_Provider(_proxy().iloc[:-1]), known_at=KNOWN)
    assert not any(tmp_path.rglob("*"))


def test_proxy_check_rejects_a_bar_not_final_at_known_at() -> None:
    frame = _proxy()
    early = datetime(2019, 7, 29, 10, tzinfo=timezone.utc)
    check = validate_vwce_proxy_series(frame, known_at=early, provider_metadata=_metadata(frame))
    assert check.status == "unavailable" and "observation_after_known_at" in check.reasons


def test_proxy_dates_take_the_date_type_of_loaded_own_rows_and_output_is_sorted() -> None:
    own = _vwce().assign(date=lambda frame: frame["date"].dt.date).iloc[::-1]  # load_prices() gives datetime.date
    series = vwce_benchmark_series(own, _stored_proxy())
    assert all(type(day) is date for day in series["date"])
    assert list(series["date"]) == sorted(series["date"])
    assert series.loc[series["benchmark_basis"].eq("proxy"), "date"].max() < VWCE_SPLICE_DATE


@pytest.mark.parametrize("own_adj, proxy_adj", [
    ([70.0, 0.0, 72.0, 73.0], PROXY_ADJ),
    ([70.0, 71.0, float("nan"), 73.0], PROXY_ADJ),
    ([70.0, 71.0, 72.0, 73.0], [80.0, float("nan"), 79.6, 80.4, 81.2]),
    ([70.0, 71.0, 72.0, 73.0], [80.0, 80.8, 79.6, 80.4, -1.0]),
])
def test_splice_fails_closed_on_a_non_finite_or_non_positive_used_price(own_adj, proxy_adj) -> None:
    proxy = _stored_proxy().assign(adjusted_close=proxy_adj)
    assert vwce_benchmark_series(_vwce().assign(adjusted_close=own_adj), proxy) is None


def _real_pattern() -> pd.DataFrame:
    """The 2013-06-11..13 VWRL.AS pattern (flat volume-0 print between two trades) plus an invalid-OHLC row."""

    rows = [  # date, open, high, low, close, volume
        ("2013-06-11", 45.9, 46.0, 45.7, 45.80, 1200.0),
        ("2013-06-12", 60.36, 60.36, 60.36, 60.36, 0.0),
        ("2013-06-13", 45.5, 45.6, 45.2, 45.27, 900.0),
        ("2017-09-07", 48.0, 48.2, 47.9, 48.0, 800.0),
        ("2017-09-08", 48.0, 47.5, 48.5, 48.1, 700.0),
        ("2019-07-26", 49.0, 49.2, 48.9, 49.0, 1000.0),
        ("2019-07-29", 50.0, 50.1, 49.8, 50.0, 1100.0),
    ]
    frame = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    return frame.assign(
        date=[date.fromisoformat(day) for day in frame["date"]], etf_id="VWRL.AS", adjusted_close=frame["close"],
        currency="EUR", provider_symbol="VWRL.AS", source="yfinance", is_adjusted=True, dividends=0.0,
        stock_splits=0.0, capital_gains=0.0, actions_evidenced=True,
    )


def test_import_quarantines_no_trade_and_invalid_ohlc_rows_and_counts_them(tmp_path: Path) -> None:
    written = _script().import_vwce_proxy(tmp_path, provider=_Provider(_real_pattern()), known_at=KNOWN)
    stored = pd.read_parquet(written)
    kept = {str(day)[:10] for day in stored["date"]}
    assert "2013-06-12" not in kept and "2017-09-08" not in kept and "2013-06-13" in kept
    reference = tmp_path / "data" / "reference"
    manifest = json.loads((reference / "vwce_proxy_vwrl_as.json").read_text(encoding="utf-8"))
    assert manifest["quarantined_rows"] == {"invalid_ohlc": 1, "no_trade": 1}
    assert manifest["source_hash"] == sha256_dataframe(stored)
    quarantined = pd.read_parquet(reference / "vwce_proxy_vwrl_as_quarantine.parquet")
    assert sorted(quarantined["quarantine_reason"]) == ["invalid_ohlc", "no_trade"]


def _rank_inputs(tmp_path: Path, vwce_id: str = "VWCE", own_known: str | None = None) -> dict[str, Path]:
    """Five members from 2018-04-02, VWCE (as ``vwce_id``) only from the splice date, all to 2020-01-31.

    ``own_known``: one late fetch stamp for every own VWCE row (as the real store), else the session close."""

    days = [day.date().isoformat() for day in pd.bdate_range("2018-04-02", "2020-01-31")]
    rows = [
        {"instrument_id": f"I{i}", "date": day, "adjusted_close": 100.0 + i + 0.1 * t * (1 + i % 3) + (t % (5 + i)),
         "known_at": f"{day}T23:59:59Z"}
        for i in range(5) for t, day in enumerate(days)
    ]
    rows += [
        {"instrument_id": vwce_id, "date": day, "adjusted_close": 70.0 + 0.05 * t,
         "known_at": own_known or f"{day}T23:59:59Z"}
        for t, day in enumerate(day for day in days if day >= "2019-07-29")
    ]
    prices, members = tmp_path / f"prices_{vwce_id}_{bool(own_known)}.parquet", tmp_path / "members.csv"
    pd.DataFrame(rows).to_parquet(prices)
    pd.DataFrame([{"instrument_id": f"I{i}"} for i in range(5)]).to_csv(members, index=False)
    return {"prices_path": prices, "membership_path": members}


def _proxy_history() -> pd.DataFrame:
    days = [day.date() for day in pd.bdate_range("2018-04-02", "2019-07-29")]
    adjusted = [80.0 + 0.02 * t + (t % 7) * 0.1 for t in range(len(days))]
    return _proxy().iloc[:1].reindex([0] * len(days)).reset_index(drop=True).assign(
        date=days, open=adjusted, low=adjusted, adjusted_close=adjusted, high=[a + 1 for a in adjusted],
        close=[a + 1 for a in adjusted], dividends=0.0,
    )


def _rank_report(root: Path, benchmark_id: str, inputs: dict[str, Path]) -> dict[str, object]:
    from etf_cockpit.application.rank_validation_service import build_rank_validation_report

    return build_rank_validation_report(root=root, years=(1,), benchmark_id=benchmark_id, **inputs)


def _text(report: dict[str, object]) -> str:
    return json.dumps(report, sort_keys=True, default=str)


def test_rank_validation_vwce_comparator_uses_the_proxy_and_fails_closed_to_stored_rows(tmp_path: Path) -> None:
    from etf_cockpit.analysis.decision.rank_validation import window_decision_times

    with_proxy, without, tampered = tmp_path / "with_proxy", tmp_path / "without", tmp_path / "tampered"
    for root in (with_proxy, tampered):
        _script().import_vwce_proxy(root, provider=_Provider(_proxy_history()), known_at=KNOWN)
    without.mkdir()
    bad = tampered / "data" / "reference" / "vwce_proxy_vwrl_as.parquet"
    pd.read_parquet(bad).assign(adjusted_close=lambda frame: frame["adjusted_close"] * 1.01).to_parquet(bad)
    vwce, other = _rank_inputs(tmp_path), _rank_inputs(tmp_path, "VWCX")

    used = _rank_report(with_proxy, "VWCE", vwce)  # check 1: decision dates before the splice get proxy returns
    times, _ = window_decision_times(pd.read_parquet(vwce["prices_path"]), 1, step_sessions=21, holding_period_sessions=21)
    before = sum(text[:10] < "2019-07-29" for text in times)
    assert before > 0 and used["benchmark_proxy"]["status"] == "used"
    assert used["windows"][0]["benchmark_proxy"] == {"proxy_source_id": "VWRL.AS", "proxy_decision_dates": before}

    baseline = _text(_rank_report(with_proxy, "VWCX", other)).replace("VWCX", "VWCE")  # stored rows only
    assert _text(_rank_report(without, "VWCX", other)).replace("VWCX", "VWCE") == baseline  # check 3: other ids unchanged
    for root, reason in ((without, "proxy_file_missing"), (tampered, "proxy_hash_mismatch")):  # check 2
        report = _rank_report(root, "VWCE", vwce)
        assert report.pop("benchmark_proxy") == {"status": "unavailable", "reason": reason, "proxy_source_id": "VWRL.AS"}
        assert _text(report) == baseline

    import pyarrow

    from etf_cockpit.application import rank_validation_service as service

    prices = pd.read_parquet(vwce["prices_path"])
    assert service._vwce_comparator_prices(with_proxy, prices.loc[prices["date"].ne("2019-07-29")])[1] == "splice_unavailable"
    no_known = tmp_path / "no_known" / "data" / "reference"
    no_known.mkdir(parents=True)
    stripped = pd.read_parquet(with_proxy / "data" / "reference" / "vwce_proxy_vwrl_as.parquet").drop(columns="known_at")
    stripped.to_parquet(no_known / "vwce_proxy_vwrl_as.parquet")
    (no_known / "vwce_proxy_vwrl_as.json").write_text(json.dumps({"source_hash": sha256_dataframe(stripped)}), encoding="utf-8")
    assert service._vwce_comparator_prices(tmp_path / "no_known", prices)[1] == "proxy_file_unreadable"

    def arrow_error(*args, **kwargs):
        raise pyarrow.lib.ArrowNotImplementedError("unsupported parquet feature")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pd, "read_parquet", arrow_error)
        assert service._vwce_comparator_prices(with_proxy, prices)[1] == "proxy_file_unreadable"


def test_rank_validation_proxy_keeps_the_stored_calendar_and_serves_only_pre_splice_dates(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.application import rank_validation_service as service

    root = tmp_path / "with_proxy"
    _script().import_vwce_proxy(root, provider=_Provider(_proxy_history()), known_at=KNOWN)
    prices = pd.read_parquet(_rank_inputs(tmp_path)["prices_path"])
    stored = prices.loc[prices["date"].ne("2019-05-17")]  # a proxy (Euronext) session no stored instrument has
    spliced, _ = service._vwce_comparator_prices(root, stored)
    sessions = set(pd.to_datetime(stored["date"]))
    assert set(pd.to_datetime(spliced["date"])) <= sessions  # the comparator holding window keeps the replay sessions

    seen: list[pd.DataFrame] = []
    original = service.run_stored_rank_validation

    def capture(evidence, memberships, prices, costs, benchmark, *args, **kwargs):
        seen.append(benchmark)
        return original(evidence, memberships, prices, costs, benchmark, *args, **kwargs)

    monkeypatch.setattr(service, "run_stored_rank_validation", capture)
    late = _rank_inputs(tmp_path, own_known="2026-11-03T12:20:00Z")  # own rows fetched long after their sessions
    report = _rank_report(root, "VWCE", late)
    dates = seen[0]["decision_date"]
    assert dates.lt("2019-07-29").all()  # no post-splice date takes a stale proxy row as its entry
    assert report["windows"][0]["benchmark_proxy"]["proxy_decision_dates"] == len(dates) > 0
