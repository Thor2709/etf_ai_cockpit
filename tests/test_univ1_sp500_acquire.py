"""Pure-logic tests for the S&P live acquisition layer (no network)."""
from types import SimpleNamespace
from datetime import datetime, timezone
from email.utils import format_datetime
import io
import json
from pathlib import Path
import time
import urllib.error

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

    def get(url, host):
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
                "filingDate": ["2019-12-20"], "acceptanceDateTime": ["2019-12-20T19:30:00.000Z"]}}}).encode()
        return 200, (fixtures / "sec_cover" / url.rsplit("/", 1)[-1]).read_bytes()

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
        assert len(list((layout.raw / "sec/covers").rglob("*.txt"))) == 2
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


def test_cover_scan_missing_acceptance_uses_filing_header(monkeypatch, tmp_path):
    layout = acq.Layout(tmp_path)
    cik = "9000000001"
    fixture = Path(__file__).parent / "fixtures/sec_cover/9000000001-19-000001.txt"

    def get(url, host):
        if "submissions" in url:
            return 200, json.dumps({"cik": cik, "filings": {"files": [], "recent": {
                "accessionNumber": [f"{cik}-19-000001"], "form": ["10-K"]}}}).encode()
        return 200, fixture.read_bytes()

    monkeypatch.setattr(acq, "http_get", get)
    result = acq.fetch_cover_issuer((cik, layout))
    assert result["status"] == "ok" and result["evidence"][0]["known_at"] == "2019-12-20T19:30:00+00:00"


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

    def get(url, host):
        if "/submissions/" in url:
            return 200, json.dumps({"cik": cik, "filings": {"files": [], "recent": {
                "accessionNumber": [accession], "form": ["10-K"],
                "acceptanceDateTime": ["2019-12-20T20:30:00Z"]}}}).encode()
        if failure == "conflict":
            return 200, fixture.read_bytes()
        return real_get(url, host, tries=1)

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
    assert detail["url"] == f"https://www.sec.gov/Archives/edgar/data/9000000001/{accession.replace('-', '')}/{accession}.txt"
    assert detail["accession"] == accession and detail["message"] and detail["reason"]
    assert json.dumps({"cik": cik, **detail}, sort_keys=True) in caplog.text
    # The emitted diagnostic is JSON serialisable, including exhausted HTTP causes.
    assert json.loads(json.dumps(result)) == result


def test_unreadable_fixture_cover_records_reason_and_breaks_continuity(monkeypatch, tmp_path, caplog):
    cik, accession = "9000000001", "9000000001-19-000001"
    fixture = Path(__file__).parent / "fixtures/sec_cover" / f"{accession}.txt"

    def get(url, host):
        if "/submissions/" in url:
            return 200, json.dumps({"cik": cik, "filings": {"recent": {
                "accessionNumber": [accession], "form": ["10-K"],
                "acceptanceDateTime": ["2019-12-20T19:30:00.000Z"]}}}).encode()
        return 200, fixture.read_bytes().replace(b"dei:TradingSymbol", b"dei:OtherField")

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
        "acceptanceDateTime": ["2019-12-20T19:30:00.000Z"]}}}).encode()
    acq.record(source.subs / f"CIK{cik}.json", source.subs_meta, payload,
               url=acq.SUBMISSIONS.format(name=f"CIK{cik}.json"))
    before = {p.relative_to(source.root): p.read_bytes() for p in source.root.rglob("*") if p.is_file()}
    fixture = Path(__file__).parent / "fixtures/sec_cover" / f"{accession}.txt"
    requests = []

    def urlopen(request, **kwargs):
        requests.append(request.full_url)
        response = io.BytesIO(fixture.read_bytes())
        response.status, response.headers = 200, {}
        return response

    monkeypatch.setenv("ETF_COCKPIT_SEC_EDGAR_USER_AGENT", "offline-test test@example.invalid")
    monkeypatch.setattr(acq.urllib.request, "urlopen", urlopen)
    assert probe.main(["--repo", str(acq.ROOT), "--root", str(source.root), cik]) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[0]["execution_allowed"] is False
    assert not Path(output[0]["temporary_root"]).exists()
    assert output[1] == {"cik": cik, "status": "ok", "evidence_count": 1, "identity_count": 1, "errors": []}
    assert output[2] == {"requested": 1, "failed": []}
    assert len(requests) == 1 and "/Archives/" in requests[0]
    assert {p.relative_to(source.root): p.read_bytes() for p in source.root.rglob("*") if p.is_file()} == before
