"""Pure-logic tests for the S&P live acquisition layer (no network)."""
from types import SimpleNamespace
from contextlib import nullcontext
from datetime import datetime, timezone
from email.utils import format_datetime
import io
import json
from pathlib import Path
import time
import urllib.error
from unittest.mock import patch

import pytest
import yaml

from etf_cockpit.data.sp500_history import build_intervals, intervals_from_fja
from scripts import acquire_sp500 as acq
from scripts import ingest_sp500


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("network is forbidden in acquisition tests")
    monkeypatch.setattr(acq.urllib.request, "urlopen", denied)
    monkeypatch.setattr(acq, "user_agent", lambda: "offline-test")
    monkeypatch.setattr(acq.shutil, "disk_usage", lambda _: SimpleNamespace(free=20 * 1024**3))


def small_cover_response(url):
    assert not url.lower().endswith(".txt"), "full submissions must never be requested"
    fixtures = Path(__file__).parent / "fixtures/sec_cover"
    if url.endswith("FilingSummary.xml"):
        return (fixtures / "FilingSummary.xml").read_bytes()
    cik = url.split("/data/")[1].split("/")[0].zfill(10)
    return (fixtures / f"{cik}-R1.htm").read_bytes()


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
        assert draft["announcement_policy"] == "effective_date_conservative"
        assert draft["history_start"] == "2021-10-01"
        with pytest.raises(ValueError, match="announcement"):
            intervals_from_fja(snapshots, draft["announcements"], baseline_known_at=draft["baseline_known_at"])


def test_generated_config_ingests_fixture_end_to_end(monkeypatch, tmp_path):
    from etf_cockpit.data import universe_store
    from etf_cockpit.data.universe_membership import membership_frame

    fixtures = Path(__file__).parent / "fixtures" / "univ1_sp500"
    layout = acq.Layout(tmp_path)
    captured = "2026-11-02T00:00:00+00:00"
    monkeypatch.setattr(acq, "now", lambda: "2026-11-03T00:00:00+00:00")
    manifest = {"files": {name: {"fetched_at": captured} for name in (
        "fja_history.csv", "company_tickers.json", "wikipedia_changes.html", "wikipedia_constituents.html")},
        "fja_commit": "a" * 40, "licence_ref": "synthetic fixture"}
    (layout.sources / "manifest.json").write_text(json.dumps(manifest))
    (layout.sources / "fja_history.csv").write_text(
        'date,tickers\n1996-01-02,"ZZQ"\n2021-09-30,"ZZA"\n2021-10-15,"ZZA,ZZC"\n')
    changes = (fixtures / "changes.html").read_text().replace('id="synthetic-changes"', 'id="changes"')
    changes = changes.replace("July 1, 2020", "October 15, 2021").replace(
        "<td>ZZB</td><td>Synthetic Former Issuer</td>", "<td></td><td></td>")
    (layout.sources / "wikipedia_changes.html").write_text(changes)
    (layout.sources / "wikipedia_constituents.html").write_text(
        '<table id="constituents"><tr><th>Symbol</th><th>Security</th><th>CIK</th></tr>'
        '<tr><td>ZZA</td><td>Synthetic Issuer A</td><td>9000000001</td></tr>'
        '<tr><td>ZZC</td><td>Synthetic Renamed Issuer</td><td>9000000002</td></tr></table>')
    (layout.sources / "company_tickers.json").write_bytes((fixtures / "company_tickers.json").read_bytes())
    history = acq.load_history(layout)
    members = acq.members_table(history)
    resolved = {"members": members, "ciks": {
        "ZZA": {"cik": "9000000001", "evidence": "synthetic identity"},
        "ZZC": {"cik": "9000000002", "evidence": "synthetic identity"}}}
    (layout.raw / "resolve.json").write_text(json.dumps(resolved))
    records = [record("synthetic-instrument-a", "ZZA", "US5949181045"),
               record("synthetic-instrument-c", "ZZC", "US0378331005")]
    monkeypatch.setattr(universe_store, "load_universe", lambda _: SimpleNamespace(
        integrity_errors=[], records=records, revision=1))
    for cik in ("9000000001", "9000000002"):
        (layout.facts / f"CIK{cik}.json").write_bytes((fixtures / f"CIK{cik}.json").read_bytes())
        (layout.subs / f"CIK{cik}.json").write_bytes((fixtures / f"submissions_{cik}.json").read_bytes())
    page = "CIK9000000001-submissions-001.json"
    (layout.subs / page).write_bytes((fixtures / page).read_bytes())
    assert acq.main(["--root", str(tmp_path), "--step", "config"]) == 0
    config_path, report_path = layout.raw / "run_config.yaml", layout.raw / "report.json"
    config = yaml.safe_load(config_path.read_text())
    assert config["history_start"] == "2021-10-01"
    assert config["announcement_policy"] == "effective_date_conservative"
    assert config["announcements"] == []
    assert ingest_sp500.main(["--config", str(config_path), "--root", str(tmp_path),
                              "--workers", "2", "--report", str(report_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report["status"] == "complete" and report["execution_allowed"] is False
    assert report["history_baseline"]["snapshot_date"] == "2021-09-30"
    assert report["history_baseline"]["known_at"] == "2021-09-30T00:00:00+00:00"
    assert report["membership_provenance"] == [{
        "date": "2021-10-15", "action": "add", "ticker": "ZZC", "source": "fja05680",
        "known_at": "2021-10-15T00:00:00+00:00",
        "provenance": "known_at=effective_date (conservative, no announcement evidence)", "announcement_source": None}]
    frame = membership_frame(config["scope"], config["as_of"], root=tmp_path)
    assert set(frame.instrument_id) == {"synthetic-instrument-a", "synthetic-instrument-c"}
    assert frame.valid_from.tolist() == ["2021-10-01", "2021-10-15"]
    # Source timing does not backdate identities observed at acquisition time.
    assert set(frame.known_at) == {"2026-11-02T00:00:00.000000Z"}
    assert (tmp_path / "data/clean/stock_fundamentals.parquet").is_file()


def test_parallel_cover_acquisition_equals_serial_and_preserves_existing_config(monkeypatch, tmp_path):
    from etf_cockpit.data import universe_store

    fixtures = Path(__file__).parent / "fixtures"
    records = [record("synthetic-a", "ZZA", "US5949181045"), record("synthetic-b", "ZZB", "US0378331005"),
               record("synthetic-c", "ZZC", "US0231351067")]
    monkeypatch.setattr(universe_store, "load_universe", lambda _: SimpleNamespace(
        integrity_errors=[], records=records, revision=1))
    monkeypatch.setattr(acq, "now", lambda: "2021-06-01T12:00:00+00:00")
    calls = []

    def get(url, host, **kwargs):
        assert host == "sec"
        calls.append(url)
        if "search-index" in url:
            return 200, json.dumps({"hits": {"hits": [{"_id": "9000000002", "_source": {
                "entity": "Synthetic Former Issuer"}}]}}).encode()
        if "/submissions/" in url:
            cik = url.split("CIK")[-1].removesuffix(".json")
            return 200, json.dumps({"cik": cik, "name": "Synthetic fixture issuer", "tickers": [], "formerNames": [],
                                   "filings": {"files": [], "recent": {
                "accessionNumber": [f"{cik}-19-000001"], "form": ["10-K"],
                "filingDate": ["2019-12-20"], "primaryDocument": ["primary.htm"], "acceptanceDateTime": ["2019-12-20T19:30:00.000Z"]}}}).encode()
        return 200, small_cover_response(url)

    monkeypatch.setattr(acq, "http_get", get)
    outcomes = []
    for lane, workers in (("serial", 1), ("parallel", 2)):
        layout = acq.Layout(tmp_path / lane)
        company = layout.sources / "company_tickers.json"
        company.write_bytes((fixtures / "univ1_sp500/company_tickers.json").read_bytes())
        config = yaml.safe_load((acq.ROOT / "configs/sp500_universe_v1.yaml").read_text())
        config.update({"execution_allowed": False, "company_tickers": str(company),
                  "history_csv": str(fixtures / "univ1_sp500/history.csv"),
                  "wikipedia_html": str(fixtures / "univ1_sp500/changes.html"),
                  "csv_shape": {"date_column": "date", "tickers_column": "tickers"},
                  "wikipedia_table_id": "synthetic-changes", "cross_validation": "report",
                  "baseline_known_at": "2019-12-31", "baseline_names": {},
                  "announcement_policy": "effective_date_conservative", "announcements": [],
                  "baseline_source": "synthetic fixture", "licence_ref": "synthetic fixture",
                  "identity_observed_at": "2026-11-03", "companyfacts": str(layout.facts), "submissions": str(layout.subs)})
        for cik in ("9000000001", "9000000002"):
            (layout.facts / f"CIK{cik}.json").write_bytes((fixtures / f"univ1_sp500/CIK{cik}.json").read_bytes())
        original = yaml.safe_dump(config).encode()
        (layout.raw / "run_config.yaml").write_bytes(original)
        resolved = {"members": {"ZZA": {"current": True}, "ZZB": {"current": False, "name": "Synthetic Former Issuer"},
                                "ZZC": {"current": True}},
                    "ciks": {"ZZA": {"cik": "9000000001"}, "ZZB": {"cik": "9000000002", "candidate_only": True}}}
        (layout.raw / "resolve.json").write_text(json.dumps(resolved))
        result = acq.step_cover(layout, workers)
        assert (layout.raw / "run_config.yaml").read_bytes() == original
        generated = Path(result["config"])
        assert generated.name.startswith("run_config_cover_v1_")
        assert acq.sha256(generated.read_bytes()) in generated.name
        dated = yaml.safe_load(generated.read_text())
        assert dated["identity_policy"] == "sec_cover_v1" and dated["execution_allowed"] is False
        assert {r["ticker"] for r in dated["instrument_bindings"]} == {"ZZA", "ZZB", "ZZC"}
        assert all(r["known_at"] == "2019-12-20T19:30:00+00:00" for r in dated["cik_bindings"])
        for meta in (layout.meta / "covers").rglob("*.meta.json"):
            item = json.loads(meta.read_text())
            assert item["url"].startswith("https://www.sec.gov/Archives/")
            assert item["sha256"] == acq.sha256(Path(item["path"]).read_bytes())
        assert not list((layout.raw / "sec/covers").rglob("*.txt"))
        assert len(list((layout.raw / "sec/covers").rglob("R1.htm"))) == 2
        before = len(calls)
        assert acq.step_cover(layout, workers) == result
        assert len(calls) == before  # All raw responses resume from verified caches.
        report = ingest_sp500.ingest(dated, root=layout.root, workers=1)
        assert report["status"] == "complete", report
        assert report["coverage"]["intervals"] == 3
        facts = acq.pd.read_parquet(layout.root / "data/clean/stock_fundamentals.parquet")
        assert facts.known_at.str.startswith(("2020", "2021")).all()
        assert {"synthetic-a", "synthetic-b", "synthetic-c"} == set(facts.instrument_id)
        outcomes.append({k: dated[k] for k in ("cik_bindings", "instrument_bindings", "identity_unbound", "cover_evidence")})
    assert outcomes[0] == outcomes[1]
    # An unavailable competing current claimant must not let the older CIK win.
    company.write_text(json.dumps({"0": {"ticker": "ZZA", "cik_str": "9000000002", "title": "Synthetic claimant"}}))
    original_fetch = acq.fetch_cover_issuer
    monkeypatch.setattr(acq, "fetch_cover_issuer", lambda task: {
        "cik": task[0], "status": "failed", "evidence": [], "errors": [{"reason": "synthetic failure"}]
    } if task[0] == "9000000002" else original_fetch(task))
    failure = acq.step_cover(layout, workers=2)
    rejected = yaml.safe_load(Path(failure["config"]).read_text())
    assert failure["failed"] == ["9000000002"]
    assert next(r for r in failure["issuer_outcomes"] if r["cik"] == "9000000002")["errors"] == [
        {"reason": "synthetic failure"}]
    assert not rejected["instrument_bindings"]
    assert {r["reason"] for r in rejected["identity_unbound"]} == {"incomplete_cover_scan", "no_cover_identity_for_window"}


def test_cover_scan_missing_acceptance_fails_closed(monkeypatch, tmp_path):
    cik = "9000000001"

    def get(url, host, **kwargs):
        if "submissions" in url:
            return 200, json.dumps({"cik": cik, "filings": {"files": [], "recent": {
                "accessionNumber": [f"{cik}-19-000001"], "form": ["10-K"],
                "filingDate": ["2019-12-20"], "primaryDocument": ["primary.htm"]}}}).encode()
        return 200, small_cover_response(url)

    monkeypatch.setattr(acq, "http_get", get)
    result = acq.fetch_cover_issuer((cik, acq.Layout(tmp_path)))
    assert result["status"] == "failed" and not result["evidence"]
    assert "acceptanceDateTime" in result["errors"][-1]["reason"]


def test_cover_http_requests_share_global_sec_limiter(monkeypatch, clock):
    calls = respond_after_errors(monkeypatch, clock, [])
    for _ in range(3):
        acq.http_get("https://www.sec.gov/Archives/synthetic.txt", "sec")
    assert calls == [0, 1 / 8, 2 / 8]


@pytest.mark.parametrize("failure,expected_type,status", [
    ("not_found", "HTTPError", 404), ("throttled", "HTTPError", 403),
    ("transport", "URLError", None), ("conflict", "ValueError", 200),
    ("user_agent", "ValueError", None),
])
def test_fixture_issuer_failure_records_request_and_reason(monkeypatch, tmp_path, clock, caplog,
                                                          failure, expected_type, status):
    cik, accession = "9000000001", "9000000001-19-000001"
    fixture = Path(__file__).parent / "fixtures/sec_cover" / f"{accession}.txt"
    real_get = acq.http_get

    def get(url, host, **kwargs):
        if "/submissions/" in url:
            return 200, json.dumps({"cik": cik, "filings": {"files": [], "recent": {
                "accessionNumber": [accession], "form": ["10-K"],
                "filingDate": ["2019-12-20"], "primaryDocument": ["primary.htm"],
                "acceptanceDateTime": ["2019-12-20T20:30:00Z"]}}}).encode()
        if failure == "conflict":
            return 200, small_cover_response(url) if url.endswith("FilingSummary.xml") else fixture.read_bytes()
        if failure == "not_found":
            raise http_error(404)
        return real_get(url, host, tries=1, **kwargs)

    error = urllib.error.URLError("offline transport unavailable") if failure == "transport" else http_error(status or 404)
    respond_after_errors(monkeypatch, clock, [error])
    monkeypatch.setattr(acq, "http_get", get)
    if failure == "user_agent":
        def missing_agent():
            raise ValueError("SEC contact required")
        monkeypatch.setattr(acq, "user_agent", missing_agent)
    result = acq.fetch_cover_issuer((cik, acq.Layout(tmp_path)))
    assert result["status"] == "failed" and result["evidence"] == []
    assert len(result["errors"]) == 1
    detail = result["errors"][0]
    assert detail["exception_type"] == expected_type
    assert detail["http_status"] == status
    assert detail["url"] == (f"https://www.sec.gov/Archives/edgar/data/9000000001/{accession.replace('-', '')}/"
                             + ("primary.htm" if failure == "not_found" else
                                "R1.htm" if failure == "conflict" else "FilingSummary.xml"))
    assert detail["accession"] == accession and detail["message"] and detail["reason"]
    assert json.dumps({"cik": cik, **detail}, sort_keys=True) in caplog.text
    # The emitted diagnostic is JSON serialisable, including exhausted HTTP causes.
    assert json.loads(json.dumps(result)) == result


def test_unreadable_fixture_cover_records_reason_and_breaks_continuity(monkeypatch, tmp_path, caplog):
    cik, accession = "9000000001", "9000000001-19-000001"
    def get(url, host, **kwargs):
        if "/submissions/" in url:
            return 200, json.dumps({"cik": cik, "filings": {"recent": {
                "accessionNumber": [accession], "form": ["10-K"],
                "filingDate": ["2019-12-20"], "primaryDocument": ["primary.htm"],
                "acceptanceDateTime": ["2019-12-20T19:30:00.000Z"]}}}).encode()
        return 200, small_cover_response(url).replace(b"dei_TradingSymbol", b"dei_OtherField")

    monkeypatch.setattr(acq, "http_get", get)
    result = acq.fetch_cover_issuer((cik, acq.Layout(tmp_path)))
    assert result["status"] == "ok"
    assert result["evidence"][0]["tickers"] == []
    assert result["evidence"][0]["known_at"] == "2019-12-20T19:30:00+00:00"
    detail = result["errors"][0]
    assert detail["exception_type"] == "ValueError" and detail["http_status"] == 200
    assert detail["url"] == result["evidence"][0]["source"]
    assert detail["message"] == "missing/conflicting CIK or TradingSymbol cover evidence"
    assert detail["message"] in caplog.text


def test_cover_cli_prints_complete_failure_json(monkeypatch, tmp_path, capsys):
    outcomes = [{"cik": f"{i:010d}", "status": "failed", "errors": [{
        "exception_type": "ValueError", "message": "fixture failure", "http_status": None,
        "url": "https://offline.invalid/submissions", "reason": "ValueError: fixture failure"}]} for i in range(80)]
    result = {"failed": [r["cik"] for r in outcomes], "issuer_outcomes": outcomes}
    monkeypatch.setattr(acq, "step_cover", lambda layout, workers: result)
    assert acq.main(["--root", str(tmp_path), "--step", "cover-evidence"]) == 1
    output = capsys.readouterr().out
    assert len(output) > 3000
    assert json.loads(output) == result


def test_live_probe_uses_temp_copy_and_prints_issuer_outcome(monkeypatch, tmp_path, capsys):
    import tools_probe_cover as probe

    cik, accession = "9000000001", "9000000001-19-000001"
    source = acq.Layout(tmp_path / "source")
    payload = json.dumps({"cik": cik, "filings": {"recent": {
        "accessionNumber": [accession], "form": ["10-K"],
                "filingDate": ["2019-12-20"], "primaryDocument": ["primary.htm"],
        "acceptanceDateTime": ["2019-12-20T19:30:00.000Z"]}}}).encode()
    acq.record(source.subs / f"CIK{cik}.json", source.subs_meta, payload,
               url=acq.SUBMISSIONS.format(name=f"CIK{cik}.json"))
    before = {p.relative_to(source.root): p.read_bytes() for p in source.root.rglob("*") if p.is_file()}
    requests = []

    def urlopen(request, **kwargs):
        requests.append(request.full_url)
        response = io.BytesIO(small_cover_response(request.full_url))
        response.status, response.headers = 200, {}
        return response

    monkeypatch.setenv("ETF_COCKPIT_SEC_EDGAR_USER_AGENT", "offline-test test@example.invalid")
    monkeypatch.setattr(acq.urllib.request, "urlopen", urlopen)
    assert probe.main(["--repo", str(acq.ROOT), "--root", str(source.root), cik]) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[0]["execution_allowed"] is False
    assert not Path(output[0]["temporary_root"]).exists()
    assert output[1] == {"cik": cik, "status": "ok", "evidence_count": 1, "identity_count": 1, "errors": [],
                         "bytes_downloaded": sum(len(small_cover_response(url)) for url in requests)}
    assert output[2] == {"requested": 1, "failed": []}
    assert len(requests) == 2 and all("/Archives/" in url for url in requests)
    assert {p.relative_to(source.root): p.read_bytes() for p in source.root.rglob("*") if p.is_file()} == before


def cached_cover_index(layout, *, form="10-K", filed="2019-06-01", primary="primary.htm", files=None):
    cik = "9000000001"
    payload = json.dumps({"cik": cik, "filings": {"files": files or [], "recent": {
        "accessionNumber": [f"{cik}-19-000001"], "form": [form], "filingDate": [filed],
        "primaryDocument": [primary], "acceptanceDateTime": ["2019-12-20T19:30:00.000Z"]}}}).encode()
    acq.record(layout.subs / f"CIK{cik}.json", layout.subs_meta, payload,
               url=acq.SUBMISSIONS.format(name=f"CIK{cik}.json"))
    return cik


@pytest.mark.parametrize("form,filed", [("10-K", "2019-05-31"), ("10-K/A", "1994-01-01"),
                                       ("8-K", "2020-01-01")])
def test_ineligible_cover_filings_and_old_pages_make_no_request(monkeypatch, tmp_path, form, filed):
    layout = acq.Layout(tmp_path)
    cik = cached_cover_index(layout, form=form, filed=filed, primary="full-submission.txt", files=[{
        "name": "CIK9000000001-submissions-001.json", "filingTo": "2019-05-31"}])

    def denied(*args, **kwargs):
        pytest.fail("ineligible cover filing/page requested")

    monkeypatch.setattr(acq, "http_get", denied)
    result = acq.fetch_cover_issuer((cik, layout))
    assert result == {"cik": cik, "status": "ok", "evidence": [], "errors": [], "bytes_downloaded": 0}


@pytest.mark.parametrize("form", sorted(acq.FORMS))
def test_cover_cutoff_inclusive_and_all_supported_amendments(monkeypatch, tmp_path, clock, form):
    layout = acq.Layout(tmp_path)
    cik = cached_cover_index(layout, form=form)
    requested = []

    def urlopen(request, **kwargs):
        requested.append(request.full_url)
        response = io.BytesIO(small_cover_response(request.full_url))
        response.status, response.headers = 200, {}
        return response

    monkeypatch.setattr(acq.urllib.request, "urlopen", urlopen)
    result = acq.fetch_cover_issuer((cik, layout))
    assert result["status"] == "ok" and result["evidence"][0]["tickers"] == ["ZZA"]
    assert [url.rsplit("/", 1)[-1] for url in requested] == ["FilingSummary.xml", "R1.htm"]
    assert result["bytes_downloaded"] == sum(len(small_cover_response(url)) for url in requested)
    assert acq.fetch_cover_issuer((cik, layout))["bytes_downloaded"] == 0
    assert len(requested) == 2


@pytest.mark.parametrize("status", [200, 206])
@pytest.mark.parametrize("fallback", ["missing_summary", "unreadable_report"])
def test_ranged_inline_fallback_is_bounded_even_if_range_ignored(monkeypatch, tmp_path, clock, status, fallback):
    layout = acq.Layout(tmp_path)
    cik = cached_cover_index(layout)
    fixture = (Path(__file__).parent / "fixtures/sec_cover/inline-cover.htm").read_bytes()
    body = fixture + b" " * (4 * acq.COVER_RANGE_BYTES)
    reads, responses, requested = [], [], []

    class BoundedResponse(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def urlopen(request, **kwargs):
        requested.append(request.full_url)
        assert not request.full_url.endswith(".txt")
        if request.full_url.endswith("FilingSummary.xml"):
            if fallback == "missing_summary":
                raise http_error(404)
            response = io.BytesIO(small_cover_response(request.full_url))
            response.status, response.headers = 200, {}
            return response
        if request.full_url.endswith("R1.htm"):
            response = io.BytesIO(b"<html>no DEI facts</html>")
            response.status, response.headers = 200, {}
            return response
        assert request.full_url.endswith("primary.htm")
        assert request.get_header("Range") == f"bytes=0-{acq.COVER_RANGE_BYTES - 1}"
        assert request.get_header("Accept-encoding") == "identity"
        response = BoundedResponse(body)
        response.status = status
        response.headers = {"Content-Range": f"bytes 0-{acq.COVER_RANGE_BYTES - 1}/{len(body)}"} if status == 206 else {}
        responses.append(response)
        return response

    monkeypatch.setattr(acq.urllib.request, "urlopen", urlopen)
    result = acq.fetch_cover_issuer((cik, layout))
    assert result["status"] == "ok" and result["evidence"][0]["tickers"] == ["ZZA"]
    assert result["evidence"][0]["known_at"] == "2019-12-20T19:30:00+00:00"
    assert reads == [acq.COVER_RANGE_BYTES] and all(r.closed for r in responses)
    assert result["bytes_downloaded"] == acq.COVER_RANGE_BYTES + (0 if fallback == "missing_summary" else
        len(small_cover_response(requested[0])) + len(b"<html>no DEI facts</html>"))
    prefix = next((layout.raw / "sec/covers").rglob("*.prefix"))
    meta = json.loads(next((layout.meta / "covers").rglob("*.prefix.meta.json")).read_text())
    assert prefix.read_bytes() == body[:acq.COVER_RANGE_BYTES]
    assert meta["url"].endswith("primary.htm") and meta["sha256"] == acq.sha256(body[:acq.COVER_RANGE_BYTES])
    assert meta["bytes"] == acq.COVER_RANGE_BYTES and meta["range_bytes"] == acq.COVER_RANGE_BYTES


def test_cover_per_file_cap_records_reason_without_caching_oversize(monkeypatch, tmp_path, clock):
    layout = acq.Layout(tmp_path)
    cik = cached_cover_index(layout)
    reads = []

    class Oversize(io.BytesIO):
        status, headers = 200, {}

        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    monkeypatch.setattr(acq.urllib.request, "urlopen", lambda *a, **kw: Oversize(b"x" * (acq.COVER_FILE_CAP + 100)))
    result = acq.fetch_cover_issuer((cik, layout))
    assert result["status"] == "failed" and "per-file cap exceeded" in result["errors"][0]["reason"]
    assert result["bytes_downloaded"] == acq.COVER_FILE_CAP + 1
    assert reads == [acq.COVER_FILE_CAP + 1]
    assert not list((layout.raw / "sec/covers").rglob("*"))


@pytest.mark.parametrize("limit", ["budget", "free_disk"])
def test_cover_cli_storage_abort_is_clean_and_publishes_no_config(monkeypatch, tmp_path, capsys, limit):
    layout = acq.Layout(tmp_path)
    (layout.raw / "run_config.yaml").write_text("execution_allowed: false\n")
    legacy = layout.raw / "sec/covers/legacy.txt"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy full submission")
    if limit == "free_disk":
        monkeypatch.setattr(acq.shutil, "disk_usage", lambda _: SimpleNamespace(free=acq.COVER_FREE_FLOOR - 1))
    args = ["--root", str(tmp_path), "--step", "cover-evidence"]
    if limit == "budget":
        args += ["--cover-cache-budget-bytes", "1"]
    assert acq.main(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "aborted" and ("budget exceeded" if limit == "budget" else "free disk below") in result["reason"]
    assert not list(layout.raw.glob("run_config_cover*.yaml"))
    assert legacy.read_bytes() == b"legacy full submission"


def test_parallel_budget_abort_stops_other_issuers_and_config_publication(monkeypatch, tmp_path):
    layout = acq.Layout(tmp_path)
    cik = cached_cover_index(layout)
    # Leave room for the index but not even one additional payload + sidecar.
    layout.cover_cache_budget = sum(p.stat().st_size for folder in (layout.subs, layout.subs_meta)
                                   for p in folder.iterdir()) + 1
    company = layout.sources / "company_tickers.json"
    company.write_text("{}")
    config = {"execution_allowed": False, "company_tickers": str(company)}
    (layout.raw / "run_config.yaml").write_text(yaml.safe_dump(config))
    (layout.raw / "resolve.json").write_text(json.dumps({"members": {"ZZA": {"current": True}},
        "ciks": {"ZZA": {"cik": cik}, "ZZB": {"cik": "9000000002"}}}))

    def get(url, host, **kwargs):
        if "/submissions/" in url:
            return 200, b'{"cik": "9000000002", "filings": {}}'
        return 200, small_cover_response(url)

    monkeypatch.setattr(acq, "http_get", get)
    result = acq.step_cover(layout, workers=2)
    assert result["status"] == "aborted" and "budget exceeded" in result["reason"]
    assert all(r["status"] == "failed" and "budget exceeded" in r["errors"][-1]["reason"]
               for r in result["issuer_outcomes"])
    assert layout.cover_cache().used <= layout.cover_cache_budget
    assert not list(layout.raw.glob("run_config_cover*.yaml"))
    assert yaml.safe_load((layout.raw / "run_config.yaml").read_text()) == config


def test_free_disk_drop_during_fetch_aborts_before_cache_write(monkeypatch, tmp_path, clock):
    layout = acq.Layout(tmp_path)
    cik = cached_cover_index(layout)

    def urlopen(request, **kwargs):
        monkeypatch.setattr(acq.shutil, "disk_usage", lambda _: SimpleNamespace(free=acq.COVER_FREE_FLOOR - 1))
        response = io.BytesIO(small_cover_response(request.full_url))
        response.status, response.headers = 200, {}
        return response

    monkeypatch.setattr(acq.urllib.request, "urlopen", urlopen)
    result = acq.fetch_cover_issuer((cik, layout))
    assert result["status"] == "failed" and "free disk below" in result["errors"][-1]["reason"]
    assert layout.cover_cache().reason is not None
    assert not list((layout.raw / "sec/covers").rglob("*"))


def test_cover_step_success_and_storage_abort_without_disk_writes():
    """Read-only reproduction for the storage/name-cache collision and publication."""
    fixtures = Path(__file__).parent / "fixtures"
    raw = Path("readonly-cover-fixture")
    config = {"execution_allowed": False, "company_tickers": str(fixtures / "univ1_sp500/company_tickers.json"),
              "history_csv": str(fixtures / "univ1_sp500/history.csv"),
              "wikipedia_html": str(fixtures / "univ1_sp500/changes.html"),
              "csv_shape": {"date_column": "date", "tickers_column": "tickers"},
              "wikipedia_table_id": "synthetic-changes", "cross_validation": "report",
              "baseline_known_at": "2019-12-31", "baseline_names": {}, "announcements": [],
              "announcement_policy": "effective_date_conservative"}
    resolved = {"members": {"ZZA": {"current": True}, "ZZB": {"current": True}, "ZZC": {"current": True}},
                "ciks": {"ZZA": {"cik": "9000000001"}, "ZZB": {"cik": "9000000002"}}}
    storage = acq.CoverCache.__new__(acq.CoverCache)
    storage.lock, storage.reason, storage.used = acq.threading.Lock(), None, 0
    layout = SimpleNamespace(raw=raw, root=acq.ROOT, cover_cache=lambda: storage, cover_cache_budget=acq.COVER_CACHE_BUDGET)
    storage.layout = layout
    original_read = Path.read_text
    writes = {}

    def read(path, *args, **kwargs):
        if path == raw / "run_config.yaml":
            return yaml.safe_dump(config)
        if path == raw / "resolve.json":
            return json.dumps(resolved)
        return original_read(path, *args, **kwargs)

    def issuer(task):
        cik, _ = task
        evidence = acq.parse_cover((fixtures / "sec_cover" / f"{cik}-R1.htm").read_bytes(), cik=cik,
            accession=f"{cik}-19-000001", form="10-K", acceptance="2019-12-20T19:30:00Z", source="fixture")
        return {"cik": cik, "status": "ok", "evidence": [evidence], "errors": [], "bytes_downloaded": 100}

    records = [record("synthetic-a", "ZZA", "US5949181045"), record("synthetic-b", "ZZB", "US0378331005"),
               record("synthetic-c", "ZZC", "US0231351067")]
    with (patch.object(Path, "read_text", read), patch.object(acq, "search_names", return_value={}),
          patch.object(acq, "fetch_cover_issuer", side_effect=issuer) as fetch,
          patch.object(acq.shutil, "disk_usage", return_value=SimpleNamespace(free=20 * 1024**3)) as disk,
          patch.object(acq, "atomic_write_bytes", side_effect=lambda path, payload, validator: writes.update({path: payload})),
          patch("etf_cockpit.data.universe_store.load_universe", return_value=SimpleNamespace(
              integrity_errors=[], records=records, revision=1))):
        serial = acq.step_cover(layout, workers=1)
        parallel = acq.step_cover(layout, workers=2)
        assert serial["cik_bindings"] == parallel["cik_bindings"] == 3
        assert serial["instrument_bindings"] == parallel["instrument_bindings"] == 3
        generated = yaml.safe_load(writes[Path(parallel["config"])])
        assert generated["execution_allowed"] is False and generated["cover_evidence"]["filing_date_start"] == "2019-06-01"
        assert all("bytes_downloaded" not in r for r in generated["cover_evidence"]["issuers"])
        writes.clear()

        def aborting_issuer(task):
            storage.reason = "cover cache budget exceeded (fixture)"
            return {"cik": task[0], "status": "failed", "evidence": [], "errors": [{"reason": storage.reason}]}

        fetch.side_effect = aborting_issuer
        aborted = acq.step_cover(layout, workers=2)
        assert aborted["status"] == "aborted" and "budget exceeded" in aborted["reason"] and not writes
        storage.reason = None

        def late_disk_drop(task):
            outcome = issuer(task)
            disk.return_value = SimpleNamespace(free=acq.COVER_FREE_FLOOR - 1)
            return outcome

        fetch.side_effect = late_disk_drop
        disk.return_value = SimpleNamespace(free=20 * 1024**3)
        aborted = acq.step_cover(layout, workers=2)
        assert aborted["status"] == "aborted" and "free disk below" in aborted["reason"] and not writes


def test_missing_cover_user_agent_does_not_try_inline_fallback():
    cik = "9000000001"
    raw = Path("readonly-cover-fixture")
    cache = SimpleNamespace(check=lambda: None)
    layout = SimpleNamespace(raw=raw, meta=raw / "_meta", subs=raw / "sec/submissions",
                             subs_meta=raw / "_meta/submissions", cover_cache=lambda: cache)
    url = acq.SUBMISSIONS.format(name=f"CIK{cik}.json")
    payload = json.dumps({"cik": cik, "filings": {"recent": {
        "accessionNumber": [f"{cik}-19-000001"], "form": ["10-K"], "filingDate": ["2019-06-01"],
        "primaryDocument": ["primary.htm"], "acceptanceDateTime": ["2019-12-20T19:30:00Z"]}}}).encode()
    with (patch.object(Path, "is_file", return_value=False), patch.object(Path, "read_bytes", return_value=payload),
          patch.object(acq, "recorded", side_effect=lambda path, meta: {"url": url, "http_status": 200}
                       if path.name.startswith("CIK") else None),
          patch.object(acq, "user_agent", side_effect=ValueError("SEC contact required")) as agent,
          patch.object(acq.urllib.request, "urlopen", side_effect=AssertionError("network forbidden")) as network):
        result = acq.fetch_cover_issuer((cik, layout))
        assert result["status"] == "failed" and len(result["errors"]) == 1
        assert result["errors"][0]["url"].endswith("FilingSummary.xml")
        assert result["errors"][0]["message"] == "SEC contact required"
        assert agent.call_count == 1 and network.call_count == 0


def test_probe_byte_reporting_without_temporary_directory_writes():
    import tools_probe_cover as probe

    cik = "9000000001"
    outcome = {"cik": cik, "status": "ok", "evidence": [{"tickers": ["ZZA"]}], "errors": [], "bytes_downloaded": 1234}
    layout = SimpleNamespace(cover_cache=lambda: SimpleNamespace(check=lambda: None))
    module = SimpleNamespace(cik_text=acq.cik_text, LIMITERS={}, Limiter=acq.Limiter,
                             Layout=lambda *a, **kw: layout, fetch_cover_issuer=lambda task: outcome)
    spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None))
    with (patch.object(probe.importlib.util, "spec_from_file_location", return_value=spec),
          patch.object(probe.importlib.util, "module_from_spec", return_value=module),
          patch.object(probe.tempfile, "TemporaryDirectory", return_value=nullcontext("readonly-probe")),
          patch.object(Path, "glob", return_value=iter(())), patch("builtins.print") as output):
        assert probe.main(["--repo", str(acq.ROOT), "--root", "readonly-source", cik]) == 0
        rows = [json.loads(call.args[0]) for call in output.call_args_list]
        assert rows[0]["execution_allowed"] is False
        assert rows[1]["cik"] == cik and rows[1]["bytes_downloaded"] == 1234
        assert rows[2] == {"requested": 1, "failed": []}


def test_cover_summary_uses_named_report_and_rejects_submission_filename():
    payload = (Path(__file__).parent / "fixtures/sec_cover/FilingSummary.xml").read_bytes()
    assert acq.cover_report_name(payload.replace(b"R1.htm", b"R7.htm")) == "R7.htm"
    with pytest.raises(ValueError, match="unsafe/missing"):
        acq.cover_report_name(payload.replace(b"R1.htm", b"submission.txt"))
