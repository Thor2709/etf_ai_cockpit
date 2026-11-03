from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from etf_cockpit.application import mcp_universe_ops
from etf_cockpit.data.universe_store import UniverseRecord, load_universe, save_universe
from scripts import import_full_universe as importer


def _company(isin: str = "", *, verified: str = "false", ticker: str = "") -> dict[str, str]:
    return {
        "name": "Example Company",
        "holding_isin": isin,
        "issuer_ticker": ticker,
        "issuer_exchange": "XNAS",
        "yfinance_ticker": "",
        "yfinance_status": "unresolved",
        "verified": verified,
        "ticker_source": "",
        "sector": "Technology",
        "country": "United States",
        "kind": "company",
    }


def _candidate(
    instrument_id: str,
    ticker: str,
    isin: str,
    *,
    asset_type: str = "stock",
    isin_status: str = "verified",
    enabled: bool = True,
    **fields: object,
) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "name": instrument_id,
        "isin": isin,
        "isin_status": isin_status,
        "ticker": ticker,
        "asset_type": asset_type,
        "tier": "secondary",
        "enabled": enabled,
        **fields,
    }


def _entry(number: int) -> importer.AuditEntry:
    mapping = {
        "canonical_id": f"ID{number}",
        "name": f"Name {number}",
        "isin": "needs_verification",
        "isin_status": "needs_verification",
        "ticker": f"T{number}",
        "asset_type": "stock",
        "tier": "secondary",
        "enabled": False,
        "data_policy": "daily",
        "currency": "EUR",
        "notes": "DATA-DU: identity_needs_verification",
    }
    return importer.AuditEntry("company", number + 2, f"ID{number}", "", f"T{number}", "disabled", "identity_needs_verification", record=mapping)


def test_stages_preview_then_revision_bound_commit_in_order(tmp_path: Path) -> None:
    class FakeOps:
        ROOT = tmp_path

        def __init__(self) -> None:
            self.events: list[tuple[str, int]] = []
            self.revision = 0

        def preview_universe_import(self, rows, *, source_kind):
            assert source_kind == "provider"
            self.events.append(("preview", len(rows)))
            return {
                "valid": True,
                "source_checksum": importer._source_checksum(rows),
                "expected_revision": f"R{self.revision}",
                "candidates": tuple(rows),
            }

        def commit_universe_import(self, rows, *, source_kind, expected_revision):
            assert source_kind == "provider"
            assert expected_revision == f"R{self.revision}"
            self.events.append(("commit", len(rows)))
            self.revision += 1
            return {"execution_allowed": False}

    ops = FakeOps()
    committed = importer.run_stages(tuple(_entry(index) for index in range(1005)), root=tmp_path, ops=ops)

    assert committed == (100, 900, 5)
    assert ops.events == [
        ("preview", 100),
        ("commit", 100),
        ("preview", 900),
        ("commit", 900),
        ("preview", 5),
        ("commit", 5),
    ]


def test_census_audit_assigns_one_bucket_per_input_and_reconciles_counts(tmp_path: Path) -> None:
    companies = (
        _company("US0378331005", verified="true", ticker="AAPL"),
        _company("US5949181045", verified="false", ticker="MSFT"),
        _company(),
    )
    candidates = (
        _candidate("AAPL", "AAPL", "US0378331005"),
        _candidate("MSFT", "MSFT", "US5949181045", isin_status="needs_verification", enabled=False),
        _candidate("ETFGOOD", "GOOD", "IE00B4L5Y983", asset_type="etf"),
        _candidate(
            "ETFFOF",
            "FOF",
            "IE00BKM4GZ66",
            asset_type="etf",
            fund_of_funds=True,
        ),
    )
    census_path = tmp_path / "companies.csv"
    with census_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(companies[0]))
        writer.writeheader()
        writer.writerows(companies)
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(json.dumps({"records": candidates}), encoding="utf-8")

    loaded_companies = importer.read_companies(census_path)
    loaded_candidates = importer.read_candidate_records(candidates_path)
    entries = importer.classify_census(loaded_companies, loaded_candidates, identity_workers=1)
    audit = tmp_path / "audit.csv"
    importer.write_audit(entries, audit)
    with audit.open("r", encoding="utf-8", newline="") as handle:
        audited = list(csv.DictReader(handle))

    assert len(audited) == len(companies) + 2
    assert sum(row["source"] == "company" for row in audited) == len(companies)
    assert sum(row["source"] == "etf" for row in audited) == 2
    assert all(row["bucket"] in importer.BUCKETS for row in audited)
    assert [row["bucket"] for row in audited] == [entry.bucket for entry in entries]
    assert {row["bucket"] for row in audited} == {"imported", "disabled", "quarantined"}
    assert next(row for row in audited if row["instrument_id"] == "ETFFOF")["reason"] == "fund_of_funds"


@pytest.mark.parametrize("census_verified,candidate_status", [
    ("true", "needs_verification"),
    ("false", "verified"),
])
def test_contradictory_stock_verification_is_quarantined(
    census_verified: str, candidate_status: str,
) -> None:
    entries = importer.classify_census(
        (_company("US0378331005", verified=census_verified, ticker="AAPL"),),
        (_candidate("AAPL", "AAPL", "US0378331005", isin_status=candidate_status, enabled=True),),
        identity_workers=1,
    )

    assert len(entries) == 1
    entry = entries[0]
    assert entry.bucket == "quarantined"
    assert entry.reason == "verification contradictory"
    assert entry.record is None  # No enabled record or upgraded status is emitted.


@pytest.mark.parametrize("missing_evidence", ["field", "candidate", "blank", "malformed", "census"])
def test_missing_or_unparseable_stock_verification_is_quarantined(missing_evidence: str) -> None:
    company = _company("US0378331005", verified="true", ticker="AAPL")
    candidate = _candidate("AAPL", "AAPL", "US0378331005", enabled=True)
    reason = "candidate verification missing"
    if missing_evidence == "field":
        candidate.pop("isin_status")
    elif missing_evidence == "blank":
        candidate["isin_status"] = ""
    elif missing_evidence == "malformed":
        candidate["isin_status"] = "unknown"
        reason = "candidate verification unparseable"
    elif missing_evidence == "census":
        company["verified"] = "unknown"
        reason = "verification_flag_unavailable_or_malformed"
    candidates = () if missing_evidence == "candidate" else (candidate,)

    entries = importer.classify_census((company,), candidates, identity_workers=1)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.bucket == "quarantined"
    assert entry.reason == reason
    assert entry.record is None


def test_stock_verified_by_both_sources_is_enabled() -> None:
    entries = importer.classify_census(
        (_company("US0378331005", verified="true", ticker="AAPL"),),
        (_candidate("AAPL", "AAPL", "US0378331005", enabled=True),),
        identity_workers=1,
    )

    assert len(entries) == 1
    entry = entries[0]
    assert entry.bucket == "imported"
    assert entry.record is not None
    assert entry.record["enabled"] is True
    assert entry.record["isin_status"] == "verified"


def test_unverified_candidate_is_never_enabled() -> None:
    companies = (
        _company("US5949181045", verified="false", ticker="MSFT"),
        _company("US0378331005", verified="true", ticker="AAPL"),
    )
    unresolved_etf = _candidate(
        "ETFUNKNOWN", "UNKNOWN", "IE00B4L5Y983", asset_type="etf", isin_status="needs_verification"
    )
    unresolved_etf.pop("enabled")
    candidates = (
        _candidate("MSFT", "MSFT", "US5949181045", isin_status="needs_verification", enabled=True),
        _candidate("AAPL", "AAPL", "US0378331005", enabled=False),
        unresolved_etf,
    )

    entries = importer.classify_census(companies, candidates, identity_workers=2)

    assert entries
    assert all(entry.bucket != "imported" for entry in entries)
    assert all(entry.record is None or entry.record["enabled"] is False for entry in entries)


def test_revision_change_between_preview_and_commit_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    existing = UniverseRecord(
        "EXISTING",
        "Existing",
        isin="needs_verification",
        isin_status="needs_verification",
        ticker="EXISTING",
    )
    initial = save_universe((existing,), "", root=tmp_path)
    monkeypatch.setattr(mcp_universe_ops, "ROOT", tmp_path)
    original_preview = mcp_universe_ops.preview_universe_import
    store_path = tmp_path / "configs" / "universe_store.json"
    raced_bytes: list[bytes] = []

    def racing_preview(source, **kwargs):
        preview = original_preview(source, **kwargs)
        concurrent = UniverseRecord(
            "CONCURRENT",
            "Concurrent",
            isin="needs_verification",
            isin_status="needs_verification",
            ticker="CONCURRENT",
        )
        save_universe((existing, concurrent), initial.revision, root=tmp_path)
        raced_bytes.append(store_path.read_bytes())
        return preview

    monkeypatch.setattr(mcp_universe_ops, "preview_universe_import", racing_preview)
    entry = importer.AuditEntry(
        "company",
        2,
        "NEW",
        "US0378331005",
        "NEW",
        "imported",
        "verified_isin_stock",
        record={
            "canonical_id": "NEW",
            "name": "New",
            "isin": "US0378331005",
            "isin_status": "verified",
            "ticker": "NEW",
            "asset_type": "stock",
            "tier": "secondary",
            "enabled": True,
            "data_policy": "daily",
            "currency": "EUR",
        },
    )
    audit_path = tmp_path / "audit.csv"

    with pytest.raises(ValueError, match="revision changed"):
        importer.import_census((entry,), root=tmp_path, audit=audit_path, stages="all")

    assert raced_bytes
    assert store_path.read_bytes() == raced_bytes[-1]
    assert load_universe(tmp_path).revision != initial.revision
    assert not audit_path.exists()


def test_parallel_identity_validation_is_byte_identical_to_serial() -> None:
    companies = []
    candidates = []
    for number in range(24):
        isin = f"US{number:09d}0"
        ticker = f"T{number}"
        companies.append(_company(isin, verified="true", ticker=ticker))
        candidates.append(_candidate(ticker, ticker, isin))

    serial = importer.classify_census(companies, candidates, identity_workers=1)
    parallel = importer.classify_census(companies, candidates, identity_workers=4)

    assert importer.audit_bytes(parallel) == importer.audit_bytes(serial)


@pytest.fixture
def yaml_only_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "runtime"
    configs = root / "configs"
    configs.mkdir(parents=True)
    (configs / "universe.yaml").write_text(
        "schema_version: 1\netfs:\n" + "".join(
            f"  - id: CORE{index}\n    name: Core {index}\n    ticker: CORE{index}\n"
            "    isin: needs_verification\n    analysis_tier: primary\n    enabled: false\n"
            for index in range(59)
        ),
        encoding="utf-8",
    )
    assert not (configs / "universe_store.json").exists()
    monkeypatch.setattr(mcp_universe_ops, "ROOT", root)
    return root


def _write_etf_inputs(path: Path, count: int) -> tuple[Path, Path]:
    census = path / "companies.csv"
    census.write_text("name,holding_isin,verified\n", encoding="utf-8")
    candidates = path / "universe_candidates.json"
    candidates.write_text(json.dumps({"records": [
        _candidate(f"ETF{index}", f"ETF{index}", "needs_verification", asset_type="etf",
                   isin_status="needs_verification", enabled=False)
        for index in range(count)
    ]}), encoding="utf-8")
    return census, candidates


def test_all_220_etfs_include_ten_unresolved_in_exactly_one_bucket(
    yaml_only_root: Path, tmp_path: Path,
) -> None:
    census, candidates = _write_etf_inputs(tmp_path, 210)
    unresolved = [{"isin": f"UNRESOLVED{index}", "name": f"Unresolved {index}"} for index in range(10)]
    (tmp_path / "universe_unresolved_etfs.json").write_text(json.dumps(unresolved), encoding="utf-8")
    audit = yaml_only_root / "audit.csv"

    assert importer.main([
        "--root", str(yaml_only_root), "--census", str(census), "--candidates", str(candidates),
        "--expected-company-rows", "0", "--audit", str(audit), "--dry-run",
    ]) == 0  # Deliberately use the default expected ETF count of 220.

    with audit.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 220
    assert all(row["source"] == "etf" and row["bucket"] in importer.BUCKETS for row in rows)
    assert len({row["source_row"] for row in rows}) == 220
    assert sum(row["bucket"] == "disabled" for row in rows) == 210
    quarantined = [row for row in rows if row["bucket"] == "quarantined"]
    assert len(quarantined) == 10
    assert {row["isin"] for row in quarantined} == {row["isin"] for row in unresolved}
    assert all(row["reason"] == "ticker unresolved" for row in quarantined)


def test_yaml_only_root_previews_with_canonical_revision_and_commits_stage_100(yaml_only_root: Path) -> None:
    entries = tuple(_entry(index) for index in range(100))
    yaml_path = yaml_only_root / "configs" / "universe.yaml"
    yaml_before = yaml_path.read_bytes()
    snapshot = mcp_universe_ops.universe_snapshot()
    preview = mcp_universe_ops.preview_universe_import([entry.record for entry in entries], source_kind="provider")

    assert preview["valid"] is True
    # Empty is the canonical optimistic revision for an uninitialized JSON store.
    assert preview["expected_revision"] == snapshot["revision"] == load_universe(yaml_only_root).revision == ""
    assert len(snapshot["records"]) == 59
    assert not (yaml_only_root / "configs" / "universe_store.json").exists()
    assert importer.run_stages(entries, root=yaml_only_root, stages="100,all") == (100,)

    saved = load_universe(yaml_only_root)
    assert saved.revision
    assert not saved.integrity_errors
    assert len(saved.records) == 159
    assert {row.instrument_id for row in saved.records} == (
        {f"CORE{index}" for index in range(59)} | {f"ID{index}" for index in range(100)}
    )
    assert yaml_path.read_bytes() == yaml_before


@pytest.mark.parametrize("initialized", [False, True])
def test_dry_run_previews_every_stage_writes_audit_and_preserves_revision(
    yaml_only_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], initialized: bool,
) -> None:
    if initialized:
        save_universe(mcp_universe_ops.universe_snapshot()["records"], "", root=yaml_only_root)
    before_revision = load_universe(yaml_only_root).revision
    before_files = {path.relative_to(yaml_only_root): path.read_bytes() for path in yaml_only_root.rglob("*") if path.is_file()}
    census, candidates = _write_etf_inputs(tmp_path, 1005)
    audit = yaml_only_root / "audit.csv"
    preview_sizes = []
    original_preview = mcp_universe_ops.preview_universe_import

    def preview(source, **kwargs):
        preview_sizes.append(len(source))
        return original_preview(source, **kwargs)

    def forbidden_commit(*args, **kwargs):
        pytest.fail("dry run called the canonical commit operation")

    monkeypatch.setattr(mcp_universe_ops, "preview_universe_import", preview)
    monkeypatch.setattr(mcp_universe_ops, "commit_universe_import", forbidden_commit)

    assert importer.main([
        "--root", str(yaml_only_root), "--census", str(census), "--candidates", str(candidates),
        "--expected-company-rows", "0", "--expected-etf-rows", "1005", "--stages", "100,1000,all",
        "--audit", str(audit), "--dry-run",
    ]) == 0

    assert preview_sizes == [100, 900, 5]
    assert load_universe(yaml_only_root).revision == before_revision
    after_files = {path.relative_to(yaml_only_root): path.read_bytes() for path in yaml_only_root.rglob("*") if path.is_file() and path != audit}
    assert after_files == before_files
    with audit.open(encoding="utf-8", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 1005
    summary = capsys.readouterr().out
    assert "previewed stage sizes: 100,900,5" in summary
    assert "committed stage sizes: none (dry run)" in summary
