from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import zipfile

import pandas as pd
import pytest

from etf_cockpit.application.sec_bulk_import import (
    SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE,
    SEC_COMPANYFACTS_BULK_URL,
    import_sec_companyfacts_bulk,
)
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.data.bulk_cache import BulkCacheError
from etf_cockpit.parsers.contracts import RawDocument


def _identity(cik: str = "1", instrument_id: str = "ONE") -> CanonicalIdentity:
    return CanonicalIdentity(instrument_id, instrument_id, None, "needs_verification", "", None, None, "stock", {}, "manual_review", (), cik)


def _facts(cik: int = 1, value: int = 10) -> bytes:
    return json.dumps({"cik": cik, "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": value, "end": "2024-12-31", "form": "10-K", "filed": "2025-01-01"}]}}}}}).encode()


def _facts_many(cik: int = 1) -> bytes:
    payload = json.loads(_facts(cik))
    payload["facts"]["us-gaap"]["Assets"]["units"]["USD"].append({"val": 20, "end": "2023-12-31", "form": "10-K", "filed": "2024-01-01"})
    return json.dumps(payload).encode()


def _archive(tmp_path: Path, members: dict[str, bytes]) -> Path:
    path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, payload in members.items():
            package.writestr(name, payload)
    return path


def _run(archive: Path, tmp_path: Path, identities=(_identity(),), **kwargs):
    return import_sec_companyfacts_bulk(
        archive,
        identities,
        cache_dir=tmp_path / "cache",
        facts_destination=tmp_path / "facts.parquet",
        inventory_destination=tmp_path / "inventory.parquet",
        **kwargs,
    )


def test_clean_local_bulk_import_publishes_manual_review_lineage(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})

    result = _run(archive, tmp_path)

    assert result.overall_status == "complete"
    assert result.execution_allowed is False
    assert result.per_cik[0].status == "imported"
    facts = pd.read_parquet(tmp_path / "facts.parquet")
    inventory = pd.read_parquet(tmp_path / "inventory.parquet")
    assert facts["source_id"].astype(str).str.startswith("sec_local_import:").all()
    assert facts["manual_review_required"].eq(True).all()
    assert facts["authority_selection"].eq("manual_review").all()
    assert inventory["document_type"].eq(SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE).all()
    assert inventory["source_authority"].eq("manual_review").all()
    assert Path(result.checkpoint_path).is_file()


def test_checked_official_companyfacts_fixture_imports_from_selected_zip(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "official" / "sec_companyfacts" / "microsoft-companyfacts.json"
    archive = _archive(tmp_path, {"CIK0000789019.json": fixture.read_bytes()})

    result = _run(archive, tmp_path, identities=(_identity("789019", "MSFT"),))

    assert result.per_cik[0].status == "imported"
    assert pd.read_parquet(tmp_path / "facts.parquet")["instrument_id"].eq("MSFT").all()
    assert pd.read_parquet(tmp_path / "inventory.parquet")["checksum"].notna().all()


@pytest.mark.parametrize("status", [200, 206, 304])
def test_public_provenance_remains_manual_with_member_lineage(tmp_path: Path, status: int) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    provenance = RawDocument(archive, SEC_COMPANYFACTS_BULK_URL, datetime(2026, 9, 3, tzinfo=timezone.utc), archive_sha256, "sec_edgar", SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE, "application/zip", status)

    result = _run(archive, tmp_path, provenance=provenance)

    assert result.per_cik[0].status == "imported"
    assert pd.read_parquet(tmp_path / "facts.parquet")["source_id"].astype(str).str.startswith("sec_local_import:").all()
    row = pd.read_parquet(tmp_path / "inventory.parquet").iloc[0]
    assert row["source_url"].startswith("file:")
    assert row["source_authority"] == "manual_review"
    assert row["ingested_at"] != provenance.retrieved_at.isoformat()
    assert set(pd.read_parquet(tmp_path / "facts.parquet")["authority_selection"]) == {"manual_review"}
    assert row["checksum"] == hashlib.sha256((tmp_path / "cache" / "sec_companyfacts_bulk" / "members" / archive_sha256 / "CIK0000000001.json").read_bytes()).hexdigest()


def test_bulk_resume_validates_checkpoint_and_skips_completed_cik(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})

    first = _run(archive, tmp_path)
    second = _run(archive, tmp_path)

    assert first.per_cik[0].status == "imported"
    assert second.per_cik[0].status == "skipped"
    assert len(pd.read_parquet(tmp_path / "inventory.parquet")) == 1


def test_changed_archive_member_invalidates_prior_checkpoint(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts(value=10)})
    first = _run(archive, tmp_path)
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts(value=11)})

    second = _run(archive, tmp_path)

    assert first.archive_sha256 != second.archive_sha256
    assert second.per_cik[0].status == "imported"
    assert len(pd.read_parquet(tmp_path / "inventory.parquet")) == 2


def test_missing_or_wrong_cik_member_is_explicit(tmp_path: Path) -> None:
    missing = _run(_archive(tmp_path, {"CIK0000000002.json": _facts(2)}), tmp_path)
    wrong = _run(_archive(tmp_path, {"CIK0000000001.json": _facts(2)}), tmp_path / "wrong")

    assert missing.per_cik[0].status == "missing"
    assert wrong.per_cik[0].status == "failed"
    assert not (tmp_path / "wrong" / "facts.parquet").exists()


@pytest.mark.parametrize(
    "provenance_factory",
    [
        lambda archive, digest: RawDocument(archive, SEC_COMPANYFACTS_BULK_URL, datetime(2026, 9, 3), digest, "sec_edgar", SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE, "application/zip", 200),
        lambda archive, digest: RawDocument(archive, "https://example.org/companyfacts.zip", datetime(2026, 9, 3, tzinfo=timezone.utc), digest, "sec_edgar", SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE, "application/zip", 200),
        lambda archive, digest: RawDocument(archive, SEC_COMPANYFACTS_BULK_URL, datetime(2026, 9, 3, tzinfo=timezone.utc), "0" * 64, "sec_edgar", SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE, "application/zip", 200),
        lambda archive, digest: RawDocument(archive.with_name("other.zip"), SEC_COMPANYFACTS_BULK_URL, datetime(2026, 9, 3, tzinfo=timezone.utc), digest, "sec_edgar", SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE, "application/zip", 200),
        lambda archive, digest: RawDocument(archive, SEC_COMPANYFACTS_BULK_URL, datetime(2026, 9, 3, tzinfo=timezone.utc), digest, "sec_edgar", SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE, "application/zip", True),
    ],
)
def test_invalid_official_provenance_fails_before_publication(tmp_path: Path, provenance_factory) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    result = _run(archive, tmp_path, provenance=provenance_factory(archive, digest))

    assert result.overall_status == "failed"
    assert result.per_cik[0].status == "failed"
    assert not (tmp_path / "facts.parquet").exists()


def test_corrupt_checkpoint_reimports_and_repairs_state(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    first = _run(archive, tmp_path)
    Path(first.checkpoint_path).write_text("not-json", encoding="utf-8")

    result = _run(archive, tmp_path)

    assert result.per_cik[0].status == "imported"
    assert len(pd.read_parquet(tmp_path / "inventory.parquet")) == 1


def test_malformed_selected_member_preserves_existing_published_state(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    _run(archive, tmp_path)
    facts_before = (tmp_path / "facts.parquet").read_bytes()
    inventory_before = (tmp_path / "inventory.parquet").read_bytes()
    malformed = _archive(tmp_path, {"CIK0000000001.json": b"{not-json"})

    result = _run(malformed, tmp_path)

    assert result.per_cik[0].status == "failed"
    assert (tmp_path / "facts.parquet").read_bytes() == facts_before
    assert (tmp_path / "inventory.parquet").read_bytes() == inventory_before


def test_failed_atomic_publication_does_not_publish_or_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import sec_bulk_import as bulk_module

    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    monkeypatch.setattr(bulk_module, "write_statement_evidence", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected")))

    result = _run(archive, tmp_path)

    assert result.per_cik[0].status == "failed"
    assert not (tmp_path / "facts.parquet").exists()
    assert not list((tmp_path / "cache" / "sec_companyfacts_bulk" / "checkpoints").glob("*.json"))


def test_archive_safety_rejects_traversal_duplicate_and_encrypted_members(tmp_path: Path) -> None:
    traversal = _archive(tmp_path, {"../escape.json": _facts()})
    duplicate = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(duplicate, "w") as package:
        package.writestr("CIK0000000001.json", _facts())
        package.writestr("CIK0000000001.json", _facts())
    encrypted = tmp_path / "encrypted.zip"
    info = zipfile.ZipInfo("CIK0000000001.json")
    info.flag_bits = 1
    with zipfile.ZipFile(encrypted, "w") as package:
        package.writestr(info, _facts())
    encrypted_bytes = bytearray(encrypted.read_bytes())
    for signature, flags_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        offset = 0
        while True:
            offset = encrypted_bytes.find(signature, offset)
            if offset < 0:
                break
            flags = struct.unpack_from("<H", encrypted_bytes, offset + flags_offset)[0]
            struct.pack_into("<H", encrypted_bytes, offset + flags_offset, flags | 1)
            offset += len(signature)
    encrypted.write_bytes(encrypted_bytes)

    assert _run(traversal, tmp_path / "traversal").overall_status == "failed"
    assert _run(duplicate, tmp_path / "duplicate").overall_status == "failed"
    assert _run(encrypted, tmp_path / "encrypted").overall_status == "failed"


def test_bulk_import_never_uses_network_and_cancellation_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.core.workflow import WorkflowTransitionError

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network")))
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})

    with pytest.raises(WorkflowTransitionError):
        _run(archive, tmp_path, publish_guard=lambda: (_ for _ in ()).throw(WorkflowTransitionError("cancelled")))


def test_resume_cannot_upgrade_local_evidence_with_public_provenance(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    local = _run(archive, tmp_path)
    official = RawDocument(archive, SEC_COMPANYFACTS_BULK_URL, datetime(2026, 9, 3, tzinfo=timezone.utc), hashlib.sha256(archive.read_bytes()).hexdigest(), "sec_edgar", SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE, "application/zip", 200)
    promoted = _run(archive, tmp_path, provenance=official)
    demoted = _run(archive, tmp_path)

    assert local.per_cik[0].status == "imported"
    assert promoted.per_cik[0].status == "skipped"
    assert demoted.per_cik[0].status == "skipped"
    assert set(pd.read_parquet(tmp_path / "inventory.parquet")["source_authority"]) == {"manual_review"}


def test_public_changed_acquisition_timestamp_does_not_rewrite_local_capture(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    first = _run(archive, tmp_path, provenance=RawDocument(archive, SEC_COMPANYFACTS_BULK_URL, datetime(2026, 9, 3, 1, tzinfo=timezone.utc), digest, "sec_edgar", SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE, "application/zip", 200))
    second = _run(archive, tmp_path, provenance=RawDocument(archive, SEC_COMPANYFACTS_BULK_URL, datetime(2026, 9, 3, 2, tzinfo=timezone.utc), digest, "sec_edgar", SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE, "application/zip", 200))

    assert first.per_cik[0].status == "imported"
    assert second.per_cik[0].status == "skipped"
    assert not pd.read_parquet(tmp_path / "inventory.parquet").iloc[-1]["ingested_at"].startswith("2026-09-03T02:00:00")


def test_resume_reimports_when_one_fact_or_inventory_is_tampered(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts_many()})
    first = _run(archive, tmp_path)
    facts_path = tmp_path / "facts.parquet"
    facts = pd.read_parquet(facts_path)
    facts.iloc[:1].to_parquet(facts_path, index=False)
    assert _run(archive, tmp_path).per_cik[0].status == "imported"
    inventory_path = tmp_path / "inventory.parquet"
    inventory = pd.read_parquet(inventory_path)
    inventory.loc[0, "path"] = "tampered"
    inventory.to_parquet(inventory_path, index=False)

    result = _run(archive, tmp_path)

    assert first.per_cik[0].status == "imported"
    assert result.per_cik[0].status == "imported"
    assert len(pd.read_parquet(facts_path)) >= 2


def test_resume_detects_actual_parser_identity_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace
    from etf_cockpit.application import sec_bulk_import as bulk_module

    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    _run(archive, tmp_path)
    original = bulk_module.parse_companyfacts
    monkeypatch.setattr(bulk_module, "parse_companyfacts", lambda path, identity: replace(original(path, identity), parser_version="changed"))

    result = _run(archive, tmp_path)

    assert result.per_cik[0].status == "imported"


def test_successful_warning_is_partial_and_replayed_on_resume(tmp_path: Path) -> None:
    payload = json.loads(_facts())
    payload["facts"]["us-gaap"]["Revenues"] = {"units": {}}
    archive = _archive(tmp_path, {"CIK0000000001.json": json.dumps(payload).encode()})

    first = _run(archive, tmp_path)
    second = _run(archive, tmp_path)
    checkpoint = json.loads(Path(first.checkpoint_path).read_text(encoding="utf-8"))

    assert first.overall_status == second.overall_status == "partial"
    assert first.per_cik[0].coverage_status == second.per_cik[0].coverage_status == "partial"
    assert first.per_cik[0].warnings == second.per_cik[0].warnings
    assert checkpoint["entries"]["0000000001"]["warnings"] == list(first.per_cik[0].warnings)


def test_three_cik_member_failure_preserves_later_success(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts(), "CIK0000000002.json": b"{broken", "CIK0000000003.json": _facts(3)})

    result = _run(archive, tmp_path, identities=(_identity("1", "ONE"), _identity("2", "TWO"), _identity("3", "THREE")))

    assert [item.status for item in result.per_cik] == ["imported", "failed", "imported"]
    assert result.overall_status == "partial"
    assert set(pd.read_parquet(tmp_path / "facts.parquet")["instrument_id"]) == {"ONE", "THREE"}


def test_checkpoint_subset_and_concurrent_merge_retain_all_ciks(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts(), "CIK0000000002.json": _facts(2)})
    all_identities = (_identity("1", "ONE"), _identity("2", "TWO"))
    assert _run(archive, tmp_path, identities=all_identities).overall_status == "complete"
    subset = _run(archive, tmp_path, identities=(_identity("2", "TWO"),))
    entries = json.loads(Path(subset.checkpoint_path).read_text(encoding="utf-8"))["entries"]

    assert set(entries) == {"0000000001", "0000000002"}


def test_concurrent_subset_imports_merge_checkpoint_and_statement_stores(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts(), "CIK0000000002.json": _facts(2)})

    def run(identity: CanonicalIdentity):
        return _run(archive, tmp_path, identities=(identity,))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, (_identity("1", "ONE"), _identity("2", "TWO"))))

    checkpoint = json.loads(Path(results[0].checkpoint_path).read_text(encoding="utf-8"))
    assert {item.per_cik[0].status for item in results} == {"imported"}
    assert set(checkpoint["entries"]) == {"0000000001", "0000000002"}
    assert set(pd.read_parquet(tmp_path / "facts.parquet")["instrument_id"]) == {"ONE", "TWO"}


def test_checkpoint_failure_reports_published_but_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import sec_bulk_import as bulk_module

    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    monkeypatch.setattr(bulk_module, "_write_checkpoint", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("checkpoint unavailable")))

    result = _run(archive, tmp_path)

    assert result.per_cik[0].status == "imported"
    assert result.per_cik[0].coverage_status == "pending"
    assert "published" in result.per_cik[0].detail
    assert (tmp_path / "facts.parquet").is_file()


def test_identity_validation_rejects_empty_and_duplicate_instruments(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts(), "CIK0000000002.json": _facts(2)})

    empty = _run(archive, tmp_path / "empty", identities=(_identity("1", ""),))
    duplicate = _run(archive, tmp_path / "duplicate", identities=(_identity("1", "SAME"), _identity("2", "SAME")))

    assert empty.overall_status == duplicate.overall_status == "failed"
    assert "instrument_id" in empty.per_cik[0].detail
    assert "duplicated" in duplicate.per_cik[1].detail or "duplicated" in duplicate.per_cik[0].detail


def test_cancellation_before_cache_and_after_publication_propagates(tmp_path: Path) -> None:
    from etf_cockpit.core.workflow import WorkflowTransitionError

    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    calls = 0

    def cancel_on_first_scope():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise WorkflowTransitionError("cancelled before cache")
        return __import__("contextlib").nullcontext()

    with pytest.raises(WorkflowTransitionError):
        _run(archive, tmp_path / "before", publish_guard=cancel_on_first_scope)
    calls = 0

    def cancel_at_checkpoint():
        nonlocal calls
        calls += 1
        if calls == 4:
            raise WorkflowTransitionError("cancelled at checkpoint")
        return __import__("contextlib").nullcontext()

    with pytest.raises(WorkflowTransitionError):
        _run(archive, tmp_path / "after", publish_guard=cancel_at_checkpoint)
    assert (tmp_path / "after" / "facts.parquet").is_file()
    assert not list((tmp_path / "after" / "cache" / "sec_companyfacts_bulk" / "checkpoints").glob("*.json"))


def test_cache_capacity_failure_is_controlled_archive_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import sec_bulk_import as bulk_module

    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    monkeypatch.setattr(bulk_module.ContentAddressedCache, "store_local_file", lambda *_args, **_kwargs: (_ for _ in ()).throw(BulkCacheError("capacity")))

    result = _run(archive, tmp_path)

    assert result.overall_status == "failed"
    assert result.per_cik[0].status == "failed"
    assert "BulkCacheError" in result.per_cik[0].detail

@pytest.mark.parametrize("zip64", [False, True])
@pytest.mark.parametrize("limit", ["MAX_BULK_MEMBERS", "MAX_CENTRAL_DIRECTORY_BYTES"])
def test_import_bounds_directory_before_zipfile_allocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, zip64: bool, limit: str) -> None:
    from etf_cockpit.data import sec_edgar_bulk

    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    if zip64:
        payload = archive.read_bytes()
        eocd = payload[-22:]
        size, offset = struct.unpack_from("<II", eocd, 12)
        record = struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, 1, 1, size, offset)
        locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, len(payload) - 22, 1)
        archive.write_bytes(payload[:-22] + record + locator + eocd)
    monkeypatch.setattr(sec_edgar_bulk, limit, 0)
    monkeypatch.setattr(zipfile, "ZipFile", lambda *_args, **_kwargs: pytest.fail("allocated member table before bounded admission"))
    result = _run(archive, tmp_path)
    assert result.overall_status == "failed"
    assert not (tmp_path / "facts.parquet").exists()


def test_import_accepts_valid_zip64_before_member_selection(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    payload = archive.read_bytes()
    eocd = payload[-22:]
    size, offset = struct.unpack_from("<II", eocd, 12)
    record = struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, 1, 1, size, offset)
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, len(payload) - 22, 1)
    archive.write_bytes(payload[:-22] + record + locator + eocd)
    assert _run(archive, tmp_path).per_cik[0].status == "imported"
