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
