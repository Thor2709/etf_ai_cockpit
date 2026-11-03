"""Pure-logic tests for the S&P live acquisition layer (no network)."""
from types import SimpleNamespace
from datetime import datetime, timezone
from email.utils import format_datetime
import io
import json
import time
import urllib.error

import pytest
import yaml

from etf_cockpit.data.sp500_history import build_intervals, intervals_from_fja
from scripts import acquire_sp500 as acq


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("network is forbidden in acquisition tests")
    monkeypatch.setattr(acq.urllib.request, "urlopen", denied)
    monkeypatch.setattr(acq, "user_agent", lambda: "offline-test")


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        elapsed = 0.0
        epoch = datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp()

        def sleep(self, seconds):
            assert seconds >= 0
            self.elapsed += seconds

    fake = Clock()
    monkeypatch.setattr(acq.time, "monotonic", lambda: fake.elapsed)
    monkeypatch.setattr(acq.time, "time", lambda: fake.epoch + fake.elapsed)
    monkeypatch.setattr(acq.time, "sleep", fake.sleep)
    monkeypatch.setitem(acq.LIMITERS, "sec", acq.Limiter(acq.SEC_RATE))
    return fake


def respond_after_errors(monkeypatch, clock, errors):
    calls = []
    pending = iter(errors)

    def urlopen(*args, **kwargs):
        calls.append(clock.elapsed)
        error = next(pending, None)
        if error is not None:
            raise error
        response = io.BytesIO(b"{}")
        response.status, response.headers = 200, {}
        return response

    monkeypatch.setattr(acq.urllib.request, "urlopen", urlopen)
    return calls


def http_error(code, retry=None):
    headers = {} if retry is None else {"Retry-After": retry}
    return urllib.error.HTTPError("https://offline.invalid", code, "offline", headers, io.BytesIO())


def test_retry_after_seconds_honoured(monkeypatch, clock):
    calls = respond_after_errors(monkeypatch, clock, [http_error(429, "60")])
    assert acq.http_get("https://offline.invalid", "sec") == (200, b"{}")
    assert calls == [0, 60]


def test_retry_after_http_date_honoured(monkeypatch, clock):
    retry = format_datetime(datetime.fromtimestamp(clock.epoch + 120, timezone.utc), usegmt=True)
    calls = respond_after_errors(monkeypatch, clock, [http_error(503, retry)])
    assert acq.http_get("https://offline.invalid", "sec") == (200, b"{}")
    assert calls == [0, 120]  # Provider delay exceeds the exponential cap.


@pytest.mark.parametrize("code", [403, 429, 500, 501, 502, 503, 504, 599])
def test_bounded_attempts_fail_closed(monkeypatch, clock, code):
    errors = [http_error(code) for _ in range(5)]
    calls = respond_after_errors(monkeypatch, clock, errors)
    with pytest.raises(RuntimeError, match=rf"sec: HTTP {code}; exhausted 5 attempts; acquisition stopped"):
        acq.http_get("https://offline.invalid", "sec")
    assert calls == ([0, 60, 120, 180, 240] if code in {403, 429} else [0, 5, 15, 35, 75])
    assert all(error.fp.closed for error in errors)


def test_backoff_caps_and_transport_attempts_are_bounded(monkeypatch, clock):
    calls = respond_after_errors(monkeypatch, clock, [TimeoutError() for _ in range(7)])
    with pytest.raises(RuntimeError, match="TimeoutError; exhausted 7 attempts"):
        acq.http_get("https://offline.invalid", "sec", tries=7)
    assert calls == [0, 5, 15, 35, 75, 135, 195]


def test_cooldown_rechecked_by_already_waiting_worker(monkeypatch, clock):
    limiter = acq.LIMITERS["sec"]
    limiter.wait()
    original_sleep = clock.sleep
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 1:
            limiter.defer(60)  # Simulate another worker receiving a throttle.
        original_sleep(seconds)

    monkeypatch.setattr(acq.time, "sleep", sleep)
    limiter.wait()
    assert clock.elapsed == 60
    limiter.wait()
    assert clock.elapsed >= 60 + 1 / acq.SEC_RATE


@pytest.mark.parametrize("header", [None, "garbage", "-10", "0", "Sun, 01 Nov 2026 00:00:00 GMT"])
def test_invalid_or_past_retry_after_uses_backoff(monkeypatch, clock, header):
    calls = respond_after_errors(monkeypatch, clock, [http_error(503, header)])
    acq.http_get("https://offline.invalid", "sec")
    assert calls == [0, 5]


def test_404_is_only_allowed_when_requested(monkeypatch, clock):
    calls = respond_after_errors(monkeypatch, clock, [http_error(404), http_error(404)])
    assert acq.http_get("https://offline.invalid", "sec", allow_404=True) == (404, b"")
    with pytest.raises(urllib.error.HTTPError):
        acq.http_get("https://offline.invalid", "sec")
    assert len(calls) == 2


def test_invalid_attempt_budget_never_requests(monkeypatch, clock):
    calls = respond_after_errors(monkeypatch, clock, [])
    with pytest.raises(ValueError, match="tries must be positive"):
        acq.http_get("https://offline.invalid", "sec", tries=0)
    assert calls == []


def event(date, action, ticker, name=None):
    return {"date": date, "action": action, "ticker": ticker, "name": name or ticker}


def test_reverse_baseline_round_trips_through_build_intervals_with_conservative_announcements():
    events = [event("2020-03-01", "add", "ZZC"), event("2020-03-01", "remove", "ZZB"), event("2021-01-05", "remove", "ZZA")]
    baseline, issues = acq.reverse_baseline({"ZZC"}, events, "2019-12-31")
    assert baseline == ["ZZA", "ZZB"] and issues == []
    intervals = build_intervals({"date": "2019-12-31", "known_at": "2019-12-31", "tickers": baseline}, events,
                                acq.conservative_announcements(events), source="wikipedia")
    removed = [row for row in intervals if row["ticker"] == "ZZA" and row["valid_to"]]
    # Knowledge is the END of the effective day: never earlier than the change itself.
    assert removed[0]["known_at"] == "2021-01-05T23:59:59.999999+00:00"
    # A change that cannot be undone is reported, not silently absorbed.
    assert acq.reverse_baseline({"ZZC"}, [event("2020-03-01", "add", "ZZQ")], "2019-12-31")[1]


def record(instrument_id, ticker, isin, status="verified", kind="stock"):
    return SimpleNamespace(instrument_id=instrument_id, ticker=ticker, isin=isin, isin_status=status, asset_type=kind)


def test_instrument_bindings_come_only_from_verified_us_stock_records_with_exact_ticker():
    members = {t: {"current": True, "open_from": "2010-02-16"} for t in ("BRK.B", "LR", "BA", "XXX")}
    ciks = {t: {"cik": "0000000001"} for t in members}
    records = [record("BRK_B", "BRK-B", "US0846707026"), record("LEGRAND", "LR", "FR0010307819"),
               record("BOEING", "BA", "US0970231058", status="needs_verification"), record("MSFT", "MSFT", "US5949181045")]
    bindings, rejected = acq.select_instrument_bindings(members, records, ciks, known_at="2026-10-22T00:00:00+00:00", revision="r1")
    assert [(b["ticker"], b["instrument_id"]) for b in bindings] == [("BRK.B", "BRK_B")]
    assert bindings[0]["valid_to"] is None and bindings[0]["source"] and rejected == []


def test_name_key_requires_exact_normalised_equality():
    assert acq.name_key("Anheuser-Busch Companies, Inc. (BUD)") == acq.name_key("ANHEUSER BUSCH COMPANIES")
    assert acq.name_key("Alcoa") != acq.name_key("Alcoa Arconic")


def test_resume_accepts_only_checksum_matching_files(tmp_path):
    target, meta = tmp_path / "a.json", tmp_path / "meta"
    acq.record(target, meta, b"{}", url="u")
    assert acq.recorded(target, meta)["sha256"] == acq.sha256(b"{}")
    target.write_bytes(b"[]")
    assert acq.recorded(target, meta) is None


def test_limiter_spaces_calls_across_threads():
    limiter = acq.Limiter(20.0)
    from concurrent.futures import ThreadPoolExecutor
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: limiter.wait(), range(6)))
    # Six calls need five full 50 ms gaps however the threads interleave.
    assert time.monotonic() - started >= 0.24


def test_windows_and_members_table_keep_removed_names():
    snaps = [{"date": "2020-01-01", "tickers": ["A", "B"]}, {"date": "2020-06-01", "tickers": ["A", "C"]}]
    assert acq.windows(snaps) == {"A": [["2020-01-01", None]], "B": [["2020-01-01", "2020-06-01"]], "C": [["2020-06-01", None]]}
    history = {"snapshots": snaps, "wiki_events": [event("2020-06-01", "remove", "B", "Bee Corp")],
               "current": [{"ticker": "A", "name": "Alpha", "cik": "0000000001"}]}
    table = acq.members_table(history)
    assert table["B"]["current"] is False and table["B"]["name"] == "Bee Corp"
    assert table["A"]["current"] is True and table["A"]["open_from"] == "2020-01-01"


def test_former_name_candidate_cannot_bind_a_reused_ticker():
    members = {"OLD": {"current": False, "open_from": None, "windows": [["2020-01-01", "2021-01-01"]]}}
    bindings, _ = acq.select_instrument_bindings(
        members, [record("NEW_ID", "OLD", "US5949181045")],
        {"OLD": {"cik": "0000000001", "candidate_only": True}}, known_at="2026-11-02", revision="r1")
    assert bindings == []


def test_sources_resume_without_discovery_or_payload_requests(monkeypatch, tmp_path):
    layout = acq.Layout(tmp_path)
    calls = []

    def get(url, host):
        calls.append(url)
        if "api.github.com" in url:
            return 200, json.dumps([{"sha": "a" * 40, "commit": {"committer": {"date": "2026-11-02"}}}]).encode()
        if "wikipedia" in url:
            return 200, b'"wgRevisionId":123'
        return 200, b"cached source"

    monkeypatch.setattr(acq, "http_get", get)
    manifest = acq.step_sources(layout)
    assert len(calls) == 6
    assert acq.step_sources(layout) == manifest
    assert len(calls) == 6
    # A corrupted source is reacquired without rediscovering a newer commit.
    (layout.sources / "fja_LICENSE.txt").write_bytes(b"corrupt")
    acq.step_sources(layout)
    assert len(calls) == 7 and "/" + "a" * 40 + "/LICENSE" in calls[-1]


def test_sec_failure_returns_nonzero(monkeypatch, tmp_path, capsys):
    layout = acq.Layout(tmp_path)
    (layout.raw / "resolve.json").write_text(json.dumps({"ciks": {"A": {"cik": "0000000001"}}}))
    monkeypatch.setattr(acq, "fetch_issuer", lambda task: {
        "cik": task[0], "submissions": "failed", "companyfacts": "ok", "reason": "exhausted 5 attempts"})
    assert acq.main(["--root", str(tmp_path), "--step", "sec", "--workers", "2"]) == 1
    assert "exhausted 5 attempts" in capsys.readouterr().out
    assert json.loads((layout.raw / "sec_status.json").read_text())["failed"]


@pytest.mark.parametrize("legacy", [False, True])
def test_sec_payloads_with_same_filename_resume_independently(monkeypatch, tmp_path, legacy):
    layout, cik = acq.Layout(tmp_path), "0000000001"
    calls = []

    def get(url, host, **kwargs):
        calls.append(url)
        return 200, json.dumps({"cik": cik, "facts": {}} if "companyfacts" in url else
                              {"cik": cik, "filings": {"files": []}}).encode()

    monkeypatch.setattr(acq, "http_get", get)
    if legacy:
        # The old common sidecar could certify only the last payload (companyfacts).
        acq.record(layout.facts / f"CIK{cik}.json", layout.meta, get(acq.COMPANYFACTS.format(cik=cik), "sec")[1], url="legacy")
        calls.clear()
    first = acq.fetch_issuer((cik, layout))
    assert first["submissions"] == "ok" and first["companyfacts"] == "ok"
    assert len(calls) == (1 if legacy else 2)
    second = acq.fetch_issuer((cik, layout))
    assert second == first and len(calls) == (1 if legacy else 2)


def test_generated_baselines_keep_capture_times(monkeypatch, tmp_path):
    from etf_cockpit.data import universe_store

    layout = acq.Layout(tmp_path)
    captures = {"fja_history.csv": "2026-11-02T00:00:00+00:00", "company_tickers.json": "2026-11-02T01:00:00+00:00",
                "wikipedia_changes.html": "2026-11-02T02:00:00+00:00",
                "wikipedia_constituents.html": "2026-11-02T03:00:00+00:00"}
    manifest = {"files": {name: {"fetched_at": stamp} for name, stamp in captures.items()},
                "fja_commit": "a" * 40, "licence_ref": "synthetic"}
    (layout.sources / "manifest.json").write_text(json.dumps(manifest))
    (layout.raw / "resolve.json").write_text(json.dumps({"members": {}, "ciks": {}}))
    monkeypatch.setattr(universe_store, "load_universe", lambda _: SimpleNamespace(integrity_errors=[], records=[], revision=1))
    snapshots = [{"date": "1996-01-01", "tickers": ["ZZZ"]}, {"date": "1997-01-01", "tickers": ["YYY"]}]
    monkeypatch.setattr(acq, "load_history", lambda _: {"snapshots": snapshots,
                                                     "wiki_events": [], "fja_events": acq.fja_events(snapshots), "current": []})
    acq.step_config(layout)
    config = yaml.safe_load((layout.raw / "run_config_block.yaml").read_text())
    assert config["baseline_known_at"] == captures["fja_history.csv"]
    assert config["wikipedia_baseline"]["known_at"] == captures["wikipedia_constituents.html"]
    assert config["execution_allowed"] is False
    for name in ("run_config.yaml", "run_config_block.yaml"):
        draft = yaml.safe_load((layout.raw / name).read_text())
        assert draft["announcements"] == []
        with pytest.raises(ValueError, match="announcement"):
            intervals_from_fja(snapshots, draft["announcements"], baseline_known_at=draft["baseline_known_at"])
