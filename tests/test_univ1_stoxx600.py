"""Synthetic offline acceptance and adversarial evidence for UNIV1."""
from dataclasses import replace
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml
from unittest.mock import patch
import zipfile

from etf_cockpit.data.esef_provider import FilingsXbrlOrgProvider, extract_issuer_shares
from etf_cockpit.data.lei_isin_map import load_mapping
from etf_cockpit.data.stoxx600_history import load_history, membership_rows, SCOPE
from etf_cockpit.data.universe_membership import membership_frame
from scripts.ingest_stoxx600 import (_LocalTransport, _import_memberships, run_issuers,
                                     persist_results, main, _parse_shares_package)

FIXTURES = Path(__file__).parent / "fixtures" / "univ1_stoxx600"
LEI = "529900D6BF99LW9R2E68"
OTHER_LEI = "7245003GZ2696Y0W1X57"
SAP = "DE0007164600"
RETAINED = "DE0005810055"
DELETED = "DE0007500001"


def history(**kwargs):
    args = dict(snapshot_known_at="2024-04-02T00:00:00Z", history_start="2024-01-01", complete_history=True)
    args.update(kwargs)
    return load_history(FIXTURES / "snapshot.csv", FIXTURES / "changes.csv", **args)


def settings(tmp_path):
    return dict(cache_dir=str(tmp_path), fixtures=str(FIXTURES), request_interval=0,
                error_limit=0, page_size=1, mapping_known_at="2024-01-01T00:00:00+00:00",
                parse_package=_parse_fixture_package)


def _parse_fixture_package(path):
    # These tests exercise extraction/orchestration with the canonical offline
    # parser; optional Arelle itself uses IPC unavailable in the worker sandbox.
    # Production parsing and validation remain unchanged.
    with patch("etf_cockpit.parsers.esef_ixbrl._arelle_available", return_value=False):
        return _parse_shares_package(path)


def provider(tmp_path, payload=None):
    if payload is None:
        transport = _LocalTransport(FIXTURES / f"{LEI}.json")
    else:
        transport = lambda *_: json.dumps(payload).encode()
    return FilingsXbrlOrgProvider(cache_dir=tmp_path, transport=transport, request_interval=0)


def filing_and_facts(lei=LEI, seq=0):
    payload = json.loads((FIXTURES / f"{lei}.json").read_text())
    raw = next(row for page in payload["pages"] for row in page["data"] if row["id"].endswith(f"-{seq}"))
    filing = {**raw["attributes"], "id": raw["id"], "known_at": raw["attributes"]["date_added"]}
    result = _parse_fixture_package(FIXTURES / f"{lei}-{seq}.xbri")
    assert result.success
    return filing, result.records


def test_rollback_add_delete_and_known_at():
    rows = history()
    earlier = rows[(rows.valid_from <= "2024-02-01") & (rows.valid_to.isna() | (rows.valid_to > "2024-02-01"))]
    assert set(earlier.ISIN) == {RETAINED, DELETED}
    deleted = earlier[earlier.ISIN == DELETED].iloc[0]
    assert deleted.valid_to == "2024-03-18"
    assert deleted.known_at == "2024-03-01T23:59:59.999999+00:00"
    added = rows[rows.ISIN == SAP].iloc[0]
    assert added.valid_from == "2024-03-18"
    assert added.known_at == deleted.known_at
    assert earlier[earlier.ISIN == RETAINED].iloc[0].known_at == "2024-04-02T00:00:00+00:00"


@pytest.mark.parametrize("name", ["snapshot", "changes"])
def test_missing_isin_rejected(tmp_path, name):
    target = tmp_path / "missing.csv"
    text = (FIXTURES / f"{name}.csv").read_text().replace(SAP, "")
    target.write_text(text)
    with pytest.raises(ValueError, match="ISIN"):
        load_history(target if name == "snapshot" else FIXTURES / "snapshot.csv",
                     target if name == "changes" else FIXTURES / "changes.csv",
                     snapshot_known_at="2024-04-02T00:00:00Z", history_start="2024-01-01", complete_history=True)


def test_history_requires_provenance_and_complete_coverage():
    with pytest.raises(ValueError, match="attested"):
        history(complete_history=False)
    with pytest.raises(ValueError, match="timezone"):
        history(snapshot_known_at="2024-04-02T00:00:00")
    with pytest.raises(ValueError, match="NEEDS_OPUS_DECISION"):
        membership_rows(history(), {})


def test_unmapped_and_immutable_gleif_store(tmp_path):
    kwargs = dict(source="synthetic GLEIF fixture", file_date="2024-01-01", store_dir=tmp_path)
    mapping, unmapped, path = load_mapping(FIXTURES / "gleif.csv", **kwargs)
    assert mapping[SAP] == LEI
    assert unmapped == (RETAINED,)
    with pytest.raises(TypeError):
        mapping[SAP] = OTHER_LEI
    assert load_mapping(FIXTURES / "gleif.csv", **kwargs)[2] == path
    stored = json.loads(path.read_text())
    assert stored["file_date"] == "2024-01-01" and stored["source"] == kwargs["source"]
    path.write_text("corruption")
    with pytest.raises(ValueError, match="checksum"):
        load_mapping(FIXTURES / "gleif.csv", **kwargs)


def test_gleif_shape_and_conflicts_fail_closed(tmp_path):
    path = tmp_path / "mapping.csv"
    path.write_text(f"ISIN,LEI\n{SAP},{LEI}\n{SAP},{OTHER_LEI}\n")
    kwargs = dict(source="synthetic", file_date="2024-01-01", store_dir=tmp_path)
    with pytest.raises(ValueError, match="conflicting"):
        load_mapping(path, **kwargs)
    with pytest.raises(ValueError, match="shape"):
        load_mapping(path, isin_column="unknown", **kwargs)


def test_latest_valid_sequence_full_pagination_and_history(tmp_path):
    instance = provider(tmp_path)
    latest = instance.list_issuer_filings(LEI)
    assert latest.status == "ok"
    assert list(latest.data.sequence) == [1]  # sequence 2 exceeds error limit
    historical = instance.list_issuer_filings(LEI, history=True)
    assert list(historical.data.sequence) == [0, 1]
    assert historical.data.known_at.tolist() == ["2024-03-01T12:00:00+00:00", "2024-03-02T12:00:00+00:00"]
    assert provider(tmp_path).list_issuer_filings(LEI, error_limit=3).data.sequence.tolist() == [2]


@pytest.mark.parametrize("change", ["entity", "next", "date", "errors", "sequence"])
def test_discovery_rejects_unproven_records(tmp_path, change):
    page = json.loads((FIXTURES / f"{LEI}.json").read_text())["pages"][0]
    page["links"]["next"] = None
    row = page["data"][0]
    if change == "entity":
        page["included"][0]["attributes"]["identifier"] = OTHER_LEI
    elif change == "next":
        page["links"]["next"] = "https://example.invalid/api/filings"
    elif change == "date":
        row["attributes"]["date_added"] = "2024-03-01 12:00:00"
    elif change == "errors":
        row["attributes"].pop("error_count")
    else:
        row["attributes"]["package_url"] = "/report.zip"
    result = provider(tmp_path, page).list_issuer_filings(LEI)
    assert result.status == "error" and result.data.empty


def test_related_entity_link_and_configured_timestamp_timezone(tmp_path):
    page = json.loads((FIXTURES / f"{LEI}.json").read_text())["pages"][0]
    page["links"]["next"] = None
    page["data"][0]["relationships"]["entity"] = {"links": {"related": f"/api/entities/{LEI}"}}
    page["data"][0]["attributes"]["date_added"] = "2024-03-01 12:00:00"
    assert provider(tmp_path, page).list_issuer_filings(LEI).status == "error"
    assert provider(tmp_path, page).list_issuer_filings(LEI, date_added_timezone="UTC").status == "ok"


def test_ifrs_fallback_subtracts_treasury_and_records_source():
    filing, facts = filing_and_facts()
    row = extract_issuer_shares(facts, lei=LEI, filing=filing)
    assert row["shares_outstanding"] == 100
    assert row["known_at"] == "2024-03-01T12:00:00+00:00"
    assert json.loads(row["source_ref"])["concept"] == "ifrs-full:NumberOfSharesOutstanding-ifrs-full:TreasuryShares"
    assert extract_issuer_shares(facts[:1], lei=LEI, filing=filing) is None


def test_dei_preferred_and_share_classes_sum_once():
    filing, facts = filing_and_facts()
    _, dei_facts = filing_and_facts(OTHER_LEI)
    dei = replace(dei_facts[0], entity_lei=LEI)
    assert extract_issuer_shares([*facts, dei], lei=LEI, filing=filing)["shares_outstanding"] == 200
    classes = {"synthetic:ShareAxis": ["synthetic:A", "synthetic:B"]}
    dimensional = [replace(fact, value=str(int(fact.value) // 2), context_dimensions=(("synthetic:ShareAxis", member),))
                   for member in classes["synthetic:ShareAxis"] for fact in facts]
    row = extract_issuer_shares(dimensional, lei=LEI, filing=filing, share_class_members=classes)
    assert row["shares_outstanding"] == 100
    assert json.loads(row["source_ref"])["share_class_members"] == classes
    assert extract_issuer_shares(dimensional[:-1], lei=LEI, filing=filing, share_class_members=classes) is None
    assert extract_issuer_shares([*facts, *dimensional], lei=LEI, filing=filing, share_class_members=classes) is None


@pytest.mark.parametrize("change", ["duration", "entity", "scope", "namespace", "unit", "negative", "conflict"])
def test_share_extraction_fails_closed(change):
    filing, facts = filing_and_facts()
    changes = {"duration": {"period_start": "2023-01-01"}, "entity": {"entity_lei": OTHER_LEI},
               "scope": {"consolidation_scope": "separate"}, "namespace": {"namespace": "urn:synthetic:extension"},
               "unit": {"unit": "EUR"}, "negative": {"value": "-1"}}
    bad = [*facts, replace(facts[0], value="111")] if change == "conflict" else [replace(f, **changes[change]) for f in facts]
    assert extract_issuer_shares(bad, lei=LEI, filing=filing) is None


def test_parallel_equals_serial_ingestion_and_resume(tmp_path):
    serial = run_issuers([LEI, OTHER_LEI], settings(tmp_path / "serial"), workers=1)
    parallel = run_issuers([LEI, OTHER_LEI], settings(tmp_path / "parallel"), workers=2)
    assert parallel == serial
    assert [r["status"] for r in serial] == ["ok", "ok"]
    assert [row["shares_outstanding"] for row in serial[0]["rows"]] == [100, 110]
    assert run_issuers([LEI, OTHER_LEI], settings(tmp_path / "parallel"), workers=2) == parallel
    identities, mapping = {SAP: "synthetic-sap", DELETED: "synthetic-other"}, {SAP: LEI, DELETED: OTHER_LEI}
    for label, results in (("serial", serial), ("parallel", parallel)):
        root = tmp_path / label
        assert persist_results(results, identities, mapping, root=root) == 3
        assert persist_results(results, identities, mapping, root=root) == 0
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "serial/data/clean/stock_fundamentals.parquet"),
                                  pd.read_parquet(tmp_path / "parallel/data/clean/stock_fundamentals.parquet"))


def test_membership_store_point_in_time_and_resume(tmp_path):
    identities = {SAP: "synthetic-sap", RETAINED: "synthetic-retained", DELETED: "synthetic-deleted"}
    rows = membership_rows(history(), identities)
    _import_memberships(rows, source="synthetic", licence_ref="synthetic internal research", root=tmp_path)
    before = membership_frame(SCOPE, "2024-03-01T12:00:00Z", root=tmp_path)
    assert before.empty
    at_announcement = membership_frame(SCOPE, "2024-03-02T00:00:00Z", root=tmp_path)
    assert set(at_announcement.instrument_id) == {"synthetic-sap", "synthetic-deleted"}
    assert at_announcement.loc[at_announcement.instrument_id == "synthetic-deleted", "valid_to"].iloc[0] == "2024-03-18"
    _import_memberships(rows, source="synthetic", licence_ref="synthetic internal research", root=tmp_path)
    pd.testing.assert_frame_equal(at_announcement, membership_frame(SCOPE, "2024-03-02T00:00:00Z", root=tmp_path))


def test_complete_snapshots_keep_stricter_contract_than_partial_announcements(tmp_path):
    from etf_cockpit.data.universe_membership import MembershipCaptureError, import_licensed_history

    identities = {SAP: "synthetic-sap", RETAINED: "synthetic-retained", DELETED: "synthetic-deleted"}
    rows = membership_rows(history(), identities)
    announced_exit = next(row for row in rows if row["valid_to"] is not None)
    assert announced_exit["valid_to"] > announced_exit["known_at"][:10]
    # A11-F2: announcements are not complete observed snapshots.
    with pytest.raises(MembershipCaptureError, match="after known_at"):
        import_licensed_history([{**announced_exit, "snapshot_complete": True}],
                                source="synthetic", licence_ref="synthetic", root=tmp_path)
    _import_memberships(rows, source="synthetic", licence_ref="synthetic", root=tmp_path)
    before = membership_frame(SCOPE, "2024-03-02T00:00:00Z", root=tmp_path)
    assert set(before.instrument_id) == {"synthetic-sap", "synthetic-deleted"}
    # A complete revision replaces the entire day's partial history atomically.
    complete = {**announced_exit, "instrument_id": "synthetic-retained", "valid_to": None,
                "known_at": "2024-04-02T00:00:00Z", "snapshot_complete": True}
    import_licensed_history([complete], source="synthetic", licence_ref="synthetic", root=tmp_path)
    after = membership_frame(SCOPE, complete["known_at"], root=tmp_path)
    same_day = after[after.snapshot_date == complete["snapshot_date"]]
    assert set(same_day.instrument_id) == {"synthetic-retained"}
    pd.testing.assert_frame_equal(before, membership_frame(SCOPE, "2024-03-02T00:00:00Z", root=tmp_path))


def test_config_is_research_only():
    config = yaml.safe_load(Path("configs/stoxx600_universe_v1.yaml").read_text())
    assert config["execution_allowed"] is False
    assert config["request_interval"] == 1
    assert config["date_added_timezone"] is None
    assert config["scope"] == SCOPE


def test_serial_ingestion_persistence_and_resume(tmp_path):
    results = run_issuers([LEI, OTHER_LEI], settings(tmp_path / "packages"), workers=1)
    assert [r["status"] for r in results] == ["ok", "ok"]
    assert [row["shares_outstanding"] for row in results[0]["rows"]] == [100, 110]
    assert run_issuers([LEI, OTHER_LEI], settings(tmp_path / "packages"), workers=1) == results
    identities, mapping = {SAP: "synthetic-sap", DELETED: "synthetic-other"}, {SAP: LEI, DELETED: OTHER_LEI}
    assert persist_results(results, identities, mapping, root=tmp_path) == 3
    assert persist_results(results, identities, mapping, root=tmp_path) == 0


def test_issuer_statuses_without_filings_or_shares(tmp_path):
    cfg = settings(tmp_path / "packages")
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    payload = {"pages": [{"data": [], "links": {"next": None}}], "packages": {}}
    (fixtures / f"{LEI}.json").write_text(json.dumps(payload))
    cfg["fixtures"] = str(fixtures)
    assert run_issuers([LEI], cfg, workers=1)[0]["status"] == "no_filings"
    payload = json.loads((FIXTURES / f"{LEI}.json").read_text())
    for url, name in payload["packages"].items():
        (fixtures / name).write_bytes((FIXTURES / name).read_bytes())
    (fixtures / f"{LEI}.json").write_text(json.dumps(payload))
    cfg["share_class_members"] = {LEI: {"synthetic:Axis": ["synthetic:Class"]}}
    # A parser returning no eligible counts is a visible no_shares outcome.
    cfg["parse_package"] = lambda p: replace(_parse_fixture_package(p), records=())
    result = run_issuers([LEI], cfg, workers=1)[0]
    assert result["status"] == "no_shares" and result["rows"] == []


def test_default_request_throttle(tmp_path, monkeypatch):
    import etf_cockpit.data.esef_provider as module
    times = iter([0.0, 0.0, 0.1, 1.0])
    sleeps = []
    monkeypatch.setattr(module.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(module.time, "sleep", sleeps.append)
    instance = FilingsXbrlOrgProvider(cache_dir=tmp_path, transport=lambda *_: b'{"data": []}')
    assert instance.list_filings("DE").status == "ok"
    assert instance.list_filings("DE").status == "ok"
    assert sleeps == [pytest.approx(0.9)]


def test_exit_revision_is_not_visible_before_announcement(tmp_path):
    snapshot = tmp_path / "snapshot.csv"
    changes = tmp_path / "changes.csv"
    snapshot.write_text(f"ISIN,name,country,as_of\n{RETAINED},Synthetic retained,DE,2024-04-01\n")
    changes.write_text(f"effective_date,announced_date,action,ISIN,name\n2024-02-01,2024-01-15,add,{SAP},Synthetic\n2024-03-18,2024-03-01,delete,{SAP},Synthetic\n")
    frame = load_history(snapshot, changes, history_start="2024-01-01", complete_history=True,
                         snapshot_known_at="2024-04-02T00:00:00Z")
    rows = membership_rows(frame, {SAP: "synthetic-sap", RETAINED: "synthetic-retained"})
    _import_memberships(rows, source="synthetic", licence_ref="synthetic", root=tmp_path)
    before = membership_frame(SCOPE, "2024-02-10T00:00:00Z", root=tmp_path)
    assert before.iloc[0].valid_to is None
    after = membership_frame(SCOPE, "2024-03-02T00:00:00Z", root=tmp_path)
    assert after.iloc[0].valid_to == "2024-03-18"
    _import_memberships(rows, source="synthetic", licence_ref="synthetic", root=tmp_path)


def test_conflicting_dei_does_not_fall_back_to_ifrs():
    filing, facts = filing_and_facts()
    _, dei_facts = filing_and_facts(OTHER_LEI)
    dei = replace(dei_facts[0], entity_lei=LEI)
    assert extract_issuer_shares([*facts, dei, replace(dei, value="201")], lei=LEI, filing=filing) is None


def test_cli_serial_report_and_resume(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import scripts.ingest_stoxx600 as script
    monkeypatch.setattr("etf_cockpit.parsers.esef_ixbrl._arelle_available", lambda: False)
    records = [SimpleNamespace(isin=isin, instrument_id="synthetic-" + isin, isin_status="verified")
               for isin in (SAP, RETAINED, DELETED)]
    monkeypatch.setattr(script, "load_universe", lambda _: SimpleNamespace(integrity_errors=(), records=records))
    config = yaml.safe_load(Path("configs/stoxx600_universe_v1.yaml").read_text())
    config["request_interval"] = 0
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    args = ["--root", str(tmp_path), "--config", str(config_path),
            "--snapshot", str(FIXTURES / "snapshot.csv"), "--changes", str(FIXTURES / "changes.csv"),
            "--gleif", str(FIXTURES / "gleif.csv"), "--snapshot-known-at", "2024-04-02T00:00:00Z",
            "--history-start", "2024-01-01", "--mapping-known-at", "2024-01-01T00:00:00Z",
            "--mapping-file-date", "2024-01-01", "--mapping-source", "synthetic GLEIF",
            "--membership-source", "synthetic STOXX", "--licence-ref", "synthetic",
            "--complete-history", "--workers", "1", "--fixtures", str(FIXTURES)]
    assert main(args) == 1  # explicitly reports the two unmapped constituents
    report_path = tmp_path / "data/raw/stoxx600/status.json"
    report = json.loads(report_path.read_text())
    assert report["execution_allowed"] is False
    assert report["unmapped_isins"] == sorted([RETAINED, DELETED])
    assert report["issuers"][0]["status"] == "ok"
    captured = membership_frame(SCOPE, "2024-04-03T00:00:00Z", root=tmp_path)
    seed = captured[captured.snapshot_date == "2024-04-01"]
    assert set(seed.instrument_id) == {"synthetic-" + SAP, "synthetic-" + RETAINED}
    assert seed.snapshot_complete.all()
    assert main(args) == 1
    assert json.loads(report_path.read_text()) == report


def test_missing_instant_is_never_filled_from_package_metadata(tmp_path):
    path = tmp_path / "no-instant.xbri"
    with zipfile.ZipFile(FIXTURES / f"{LEI}-0.xbri") as original, zipfile.ZipFile(path, "w") as target:
        for name in original.namelist():
            payload = original.read(name)
            if name.endswith(".xhtml"):
                payload = payload.replace(b"<xbrli:instant>2023-12-31</xbrli:instant>", b"")
            target.writestr(name, payload)
    parsed = _parse_fixture_package(path)
    assert parsed.success
    assert not parsed.records
