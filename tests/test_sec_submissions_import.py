from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from etf_cockpit.application.sec_submissions_import import (
    SUBMISSIONS_URL,
    import_sec_submissions,
)
from etf_cockpit.core.workflow import WorkflowTransitionError
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import RawDocument

FIXTURE = Path("tests/fixtures/official/sec_submissions/microsoft-submissions.json")


def _identity(cik: str = "789019", instrument: str = "MSFT") -> CanonicalIdentity:
    return CanonicalIdentity(instrument, "Microsoft", None, "needs_verification", "", None, None, "stock", {}, "manual_review", (), cik)


def _columns(accession: str = "0000789019-26-000001", form: str = "10-K") -> dict[str, list[object]]:
    return {"accessionNumber": [accession], "filingDate": ["2026-01-02"], "reportDate": ["2025-12-31"], "acceptanceDateTime": ["2026-01-02T03:04:05.000Z"], "form": [form], "primaryDocument": ["annual.htm"], "rawExtra": ["retained"]}


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _payload(files: list[dict[str, object]] | None = None, columns: dict[str, list[object]] | None = None) -> dict[str, object]:
    return {"cik": "0000789019", "name": "MICROSOFT CORP", "filings": {"recent": columns or _columns(), "files": files or []}}


def test_local_import_retains_snapshot_and_actual_filing_bytes(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    filing = tmp_path / "annual.htm"
    filing.write_bytes(b"<html>actual filing bytes</html>")
    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache", filing_documents={"0000789019-26-000001": filing})

    assert result.status == "complete"
    assert result.execution_allowed is False
    assert len(result.records) == 1
    assert len(result.raw_documents) == 2
    assert all(document.provider_id == "sec_local_import" for document in result.raw_documents)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    snapshot = manifest["snapshots"][0]
    assert Path(snapshot["source_document"]["path"]).read_bytes() == source.read_bytes()
    retained_filing = Path(snapshot["filing_documents"]["0000789019-26-000001"]["path"])
    assert retained_filing.read_bytes() == filing.read_bytes()
    assert snapshot["records"][0]["raw_row"]["rawExtra"] == "retained"


def test_official_fixture_retains_full_snapshot_with_explicit_provenance(tmp_path: Path) -> None:
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    provenance = RawDocument(FIXTURE, SUBMISSIONS_URL.format(cik="0000789019"), datetime(2026, 9, 3, 5, tzinfo=timezone.utc), digest, "sec_edgar", "sec_submissions", "application/json", 200)
    result = import_sec_submissions(FIXTURE, _identity(), cache_dir=tmp_path / "cache", provenance=provenance)

    assert result.status == "partial"
    assert len(result.records) == 1004
    assert result.raw_documents[0].provider_id == "sec_edgar"
    assert any(warning["code"] == "history_incomplete" for warning in result.warnings)
    assert any(warning["code"] == "filing_documents_missing" for warning in result.warnings)


def test_history_and_missing_filing_are_explicitly_partial(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    current = _write(tmp_path / "current.json", _payload([{"name": name, "filingCount": 1}]))
    history = _write(tmp_path / name, _payload(columns=_columns("0000789019-25-000001", "10-Q")))
    result = import_sec_submissions(current, _identity(), cache_dir=tmp_path / "cache", history_paths={name: history})

    assert result.status == "partial"
    assert len(result.records) == 2
    codes = {str(warning["code"]) for warning in result.warnings}
    assert "filing_documents_missing" in codes
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["snapshots"][0]["coverage_status"] == "partial"
    assert name in manifest["snapshots"][0]["history_documents"]


def test_amendment_filing_bytes_are_retained_as_distinct_accessions(tmp_path: Path) -> None:
    columns = _columns()
    for key in columns:
        columns[key].append(columns[key][0])
    columns["accessionNumber"][1] = "0000789019-26-000002"
    columns["form"][1] = "10-K/A"
    columns["primaryDocument"][1] = "amendment.htm"
    source = _write(tmp_path / "submissions.json", _payload(columns=columns))
    first, amendment = tmp_path / "annual.htm", tmp_path / "amendment.htm"
    first.write_bytes(b"original filing")
    amendment.write_bytes(b"amended filing")
    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache", filing_documents={
        "0000789019-26-000001": first,
        "0000789019-26-000002": amendment,
    })

    assert result.status == "complete"
    assert {record.accession for record in result.records} == {"0000789019-26-000001", "0000789019-26-000002"}
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    retained = manifest["snapshots"][0]["filing_documents"]
    assert Path(retained["0000789019-26-000001"]["path"]).read_bytes() == first.read_bytes()
    assert Path(retained["0000789019-26-000002"]["path"]).read_bytes() == amendment.read_bytes()


def test_restart_revalidates_raw_evidence_and_keeps_changed_revision(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    cache = tmp_path / "cache"
    first = import_sec_submissions(source, _identity(), cache_dir=cache)
    source.write_text(json.dumps(_payload(columns=_columns("0000789019-26-000002", "10-K/A"))), encoding="utf-8")
    second = import_sec_submissions(source, _identity(), cache_dir=cache)

    assert second.status == "partial"
    manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["snapshots"]) == 2
    assert manifest["snapshots"][0]["source_sha256"] != manifest["snapshots"][1]["source_sha256"]
    assert Path(manifest["snapshots"][0]["source_document"]["path"]).is_file()
    assert first.records[0].accession != second.records[0].accession


def test_provenance_and_identity_registry_fail_closed_before_retention(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    wrong = RawDocument(source, SUBMISSIONS_URL.format(cik="0000789019"), datetime.now(timezone.utc), "0" * 64, "sec_edgar", "sec_submissions", "application/json", 200)
    rejected = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "bad-cache", provenance=wrong)
    assert rejected.status == "failed"
    assert not (tmp_path / "bad-cache").exists()

    registry = tmp_path / "identity.parquet"
    pd.DataFrame([{"cik": "0000789019", "instrument_id": "OTHER"}]).to_parquet(registry, index=False)
    rejected_registry = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "registry-cache", identity_registry=registry)
    assert rejected_registry.status == "failed"
    assert "registry" in rejected_registry.detail
    assert digest == hashlib.sha256(source.read_bytes()).hexdigest()


@pytest.mark.parametrize("status,timestamp,url", [(True, datetime.now(timezone.utc), SUBMISSIONS_URL.format(cik="0000789019")), (200, datetime.now(), "https://example.invalid/submissions.json")])
def test_invalid_provenance_metadata_is_rejected_without_cache_mutation(tmp_path: Path, status: object, timestamp: datetime, url: str) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    provenance = RawDocument(source, url, timestamp, digest, "sec_edgar", "sec_submissions", "application/json", status)  # type: ignore[arg-type]

    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache", provenance=provenance)

    assert result.status == "failed"
    assert not (tmp_path / "cache").exists()


def test_bulk_zip_reads_only_selected_snapshot_and_supplied_history(tmp_path: Path) -> None:
    current = json.dumps(_payload([{"name": "CIK0000789019-submissions-001.json", "filingCount": 1}])).encode()
    history = json.dumps(_payload(columns=_columns("0000789019-25-000001", "10-Q"))).encode()
    archive = tmp_path / "submissions.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("CIK0000789019.json", current)
        package.writestr("CIK0000789019-submissions-001.json", history)
        package.writestr("other-cik.json", b"should not be read")
    result = import_sec_submissions(archive, _identity(), cache_dir=tmp_path / "cache")

    assert result.status == "partial"
    assert len(result.records) == 2
    assert all(document.path.is_file() for document in result.raw_documents)
    assert not any(document.path.name == "other-cik.json" for document in result.raw_documents)


def test_cancellation_preserves_previous_manifest(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    cache = tmp_path / "cache"
    first = import_sec_submissions(source, _identity(), cache_dir=cache)
    before = first.manifest_path.read_bytes()

    def cancel():
        raise WorkflowTransitionError("cancelled")

    with pytest.raises(WorkflowTransitionError):
        import_sec_submissions(source, _identity(), cache_dir=cache, publish_guard=cancel)
    assert first.manifest_path.read_bytes() == before


def test_tampered_manifest_is_not_overwritten(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    cache = tmp_path / "cache"
    first = import_sec_submissions(source, _identity(), cache_dir=cache)
    first.manifest_path.write_text("{\"tampered\": true}", encoding="utf-8")

    result = import_sec_submissions(source, _identity(), cache_dir=cache)

    assert result.status == "failed"
    assert json.loads(first.manifest_path.read_text(encoding="utf-8")) == {"tampered": True}
