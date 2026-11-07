"""Report-only ``--ciks`` subset mode of the cover-evidence step (offline)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import acquire_sp500 as acq

FIXTURES = Path(__file__).parent / "fixtures"
CANDIDATE_A, CANDIDATE_B, STRANGER = "9000000001", "9000000002", "9000000009"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    from etf_cockpit.data import universe_store

    monkeypatch.setitem(acq.LIMITERS, "sec", acq.LIMITERS["sec"])  # main() replaces it; restore afterwards

    def denied(*args, **kwargs):
        raise AssertionError("network is forbidden in acquisition tests")
    rows = [SimpleNamespace(instrument_id=i, ticker=t, isin=n, isin_status="verified", asset_type="stock")
            for i, t, n in (("synthetic-a", "ZZA", "US5949181045"), ("synthetic-b", "ZZB", "US0378331005"),
                            ("synthetic-c", "ZZC", "US0231351067"))]
    monkeypatch.setattr(acq.urllib.request, "urlopen", denied)
    monkeypatch.setattr(acq, "user_agent", lambda: "offline-test")
    monkeypatch.setattr(acq.shutil, "disk_usage", lambda _: SimpleNamespace(free=20 * 1024**3))
    monkeypatch.setattr(acq, "now", lambda: "2021-06-01T12:00:00+00:00")
    monkeypatch.setattr(universe_store, "load_universe", lambda _: SimpleNamespace(
        integrity_errors=[], records=rows, revision=1))

    def get(url, host, **kwargs):
        assert host == "sec"
        if "search-index" in url:
            return 200, json.dumps({"hits": {"hits": [{"_id": CANDIDATE_B, "_source": {
                "entity": "Synthetic Former Issuer"}}]}}).encode()
        if "/submissions/" in url:
            cik = url.split("CIK")[-1].removesuffix(".json")
            return 200, json.dumps({"cik": cik, "filings": {"files": [], "recent": {
                "accessionNumber": [f"{cik}-19-000001"], "form": ["10-K"], "filingDate": ["2019-12-20"],
                "primaryDocument": ["primary.htm"], "acceptanceDateTime": ["2019-12-20T19:30:00.000Z"]}}}).encode()
        if url.endswith("FilingSummary.xml"):
            return 200, (FIXTURES / "sec_cover/FilingSummary.xml").read_bytes()
        cik = url.split("/data/")[1].split("/")[0].zfill(10)
        return 200, (FIXTURES / f"sec_cover/{cik}-R1.htm").read_bytes()
    monkeypatch.setattr(acq, "http_get", get)


def make_root(root: Path) -> acq.Layout:
    layout = acq.Layout(root)
    company = layout.sources / "company_tickers.json"
    company.write_bytes((FIXTURES / "univ1_sp500/company_tickers.json").read_bytes())
    config = yaml.safe_load((acq.ROOT / "configs/sp500_universe_v1.yaml").read_text())
    config.update({"execution_allowed": False, "company_tickers": str(company),
                   "history_csv": str(FIXTURES / "univ1_sp500/history.csv"),
                   "wikipedia_html": str(FIXTURES / "univ1_sp500/changes.html"),
                   "csv_shape": {"date_column": "date", "tickers_column": "tickers"},
                   "wikipedia_table_id": "synthetic-changes", "cross_validation": "report",
                   "baseline_known_at": "2019-12-31", "baseline_names": {},
                   "announcement_policy": "effective_date_conservative", "announcements": [],
                   "baseline_source": "synthetic fixture", "licence_ref": "synthetic fixture",
                   "identity_observed_at": "2026-11-03", "companyfacts": str(layout.facts),
                   "submissions": str(layout.subs)})
    (layout.raw / "run_config.yaml").write_bytes(yaml.safe_dump(config).encode())
    resolved = {"members": {"ZZA": {"current": True}, "ZZB": {"current": False, "name": "Synthetic Former Issuer"},
                            "ZZC": {"current": True}},
                "ciks": {"ZZA": {"cik": CANDIDATE_A}, "ZZB": {"cik": CANDIDATE_B, "candidate_only": True}}}
    (layout.raw / "resolve.json").write_text(json.dumps(resolved))
    return layout


def files_under(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


def test_subset_equals_full_run_per_cik_and_publishes_nothing(tmp_path):
    full = make_root(tmp_path / "full")
    dated = yaml.safe_load(Path(acq.step_cover(full, 2)["config"]).read_text())
    expected = {row["cik"]: row for row in dated["cover_evidence"]["issuers"]}
    assert set(expected) == {CANDIDATE_A, CANDIDATE_B}

    subset = make_root(tmp_path / "subset")
    before, config_before = files_under(subset.root), (subset.raw / "run_config.yaml").read_bytes()
    listing = tmp_path / "ciks.txt"
    listing.write_text(f"# hard cases\n\n{CANDIDATE_B}   # ZZB\n{STRANGER}\n{CANDIDATE_B}\n{CANDIDATE_A}\n", "utf-8")
    report_path = tmp_path / "out" / "subset.json"
    assert acq.main(["--root", str(subset.root), "--step", "cover-evidence", "--workers", "2",
                     "--ciks", str(listing), "--subset-report", str(report_path)]) == 1  # STRANGER: not checked
    report = json.loads(report_path.read_text())
    assert report["scope"] == "evidence_only_binding_not_evaluated"
    assert {row["scope"] for row in report["issuers"]} == {report["scope"]}
    got = {row["cik"]: row for row in report["issuers"]}
    assert set(got) == {CANDIDATE_A, CANDIDATE_B, STRANGER}
    assert got[STRANGER] == {"cik": STRANGER, "status": "not_a_candidate", "scope": report["scope"]}
    for cik in (CANDIDATE_A, CANDIDATE_B):
        row = {k: v for k, v in got[cik].items() if k not in {"bytes_downloaded", "scope"}}
        assert row == expected[cik]
    assert report["not_a_candidate"] == [STRANGER] and report["failed"] == []
    created = files_under(subset.root) - before
    caches = {"sec", "_meta", "name_search_cache.json"}  # fetched-response caches only
    assert created and all(p.parts[:3] == ("data", "raw", "univ1_sp500") and p.parts[3] in caches for p in created), created
    assert not list(subset.raw.glob("run_config_cover*"))
    assert (subset.raw / "run_config.yaml").read_bytes() == config_before


def test_warm_cache_subset_after_full_run_gives_same_evidence(monkeypatch, tmp_path):
    layout = make_root(tmp_path / "root")
    dated = yaml.safe_load(Path(acq.step_cover(layout, 2)["config"]).read_text())
    expected = {row["cik"]: row for row in dated["cover_evidence"]["issuers"]}
    urls, fetch = [], acq.http_get
    monkeypatch.setattr(acq, "http_get", lambda url, host, **kw: (urls.append(url), fetch(url, host, **kw))[1])
    listing, report_path = tmp_path / "ciks.txt", tmp_path / "subset.json"
    listing.write_text(f"{CANDIDATE_A}\n{CANDIDATE_B}\n")
    assert acq.main(["--root", str(layout.root), "--step", "cover-evidence", "--ciks", str(listing),
                     "--subset-report", str(report_path)]) == 0
    got = {row["cik"]: row for row in json.loads(report_path.read_text())["issuers"]}
    for cik, row in expected.items():
        assert {k: v for k, v in got[cik].items() if k not in {"bytes_downloaded", "scope"}} == row
        assert got[cik]["bytes_downloaded"] == 0
    assert all("/submissions/" in url for url in urls), urls  # covers resume from the shared cache


def test_subset_failure_returns_nonzero_and_reports_reason(monkeypatch, tmp_path):
    layout = make_root(tmp_path / "root")
    original = acq.fetch_cover_issuer
    monkeypatch.setattr(acq, "fetch_cover_issuer", lambda task: {
        "cik": task[0], "status": "failed", "evidence": [], "errors": [{"reason": "synthetic failure"}],
        "bytes_downloaded": 0} if task[0] == CANDIDATE_B else original(task))
    listing, report_path = tmp_path / "ciks.txt", tmp_path / "subset.json"
    listing.write_text(f"{CANDIDATE_B}\n")
    assert acq.main(["--root", str(layout.root), "--step", "cover-evidence", "--ciks", str(listing),
                     "--subset-report", str(report_path)]) == 1
    report = json.loads(report_path.read_text())
    assert report["failed"] == [CANDIDATE_B]
    assert report["issuers"][0]["errors"] == [{"reason": "synthetic failure"}]


@pytest.mark.parametrize("step, extra, lines, message", [
    ("cover-evidence", [], f"{CANDIDATE_A}\n", "--subset-report is required with --ciks"),
    ("sec", ["--subset-report", "REPORT"], f"{CANDIDATE_A}\n", "--ciks is only valid with --step cover-evidence"),
    ("cover-evidence", ["--subset-report", "REPORT"], "123\n", "malformed CIK on line 1"),
    ("cover-evidence", ["--subset-report", "REPORT"], f"{CANDIDATE_A}\n{CANDIDATE_B} extra\n", "malformed CIK on line 2"),
    ("cover-evidence", ["--subset-report", "REPORT"], "# only a comment\n\n", "contains no CIK"),
])
def test_subset_option_rejections(tmp_path, capsys, step, extra, lines, message):
    listing, report_path = tmp_path / "ciks.txt", tmp_path / "subset.json"
    listing.write_text(lines)
    args = ["--root", str(tmp_path / "root"), "--step", step, "--ciks", str(listing)]
    args += [str(report_path) if item == "REPORT" else item for item in extra]
    with pytest.raises(SystemExit) as stopped:
        acq.main(args)
    assert stopped.value.code == 2
    assert message in capsys.readouterr().err
    assert not report_path.exists() and not (tmp_path / "root").exists()


def test_subset_report_requires_ciks_and_stays_out_of_root_and_ciks_file(tmp_path, capsys):
    with pytest.raises(SystemExit):
        acq.main(["--root", str(tmp_path), "--step", "cover-evidence", "--subset-report", str(tmp_path / "r.json")])
    assert "--subset-report is only valid with --ciks" in capsys.readouterr().err
    listing = tmp_path / "ciks.txt"
    listing.write_text(f"{CANDIDATE_A}\n")
    for inside in (tmp_path / "data/raw/univ1_sp500/run_config_cover_v1_x.yaml", tmp_path / "report.json"):
        with pytest.raises(SystemExit):
            acq.main(["--root", str(tmp_path), "--step", "cover-evidence", "--ciks", str(listing),
                      "--subset-report", str(inside)])
        assert "--subset-report must be outside --root" in capsys.readouterr().err
        assert not inside.exists()
    with pytest.raises(SystemExit):
        acq.main(["--root", str(tmp_path / "root"), "--step", "cover-evidence", "--ciks", str(listing),
                  "--subset-report", str(listing)])
    assert "--subset-report must differ from --ciks" in capsys.readouterr().err
    assert listing.read_text() == f"{CANDIDATE_A}\n"
