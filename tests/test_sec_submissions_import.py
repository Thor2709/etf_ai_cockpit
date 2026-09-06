from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import inspect
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
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
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
    assert result.records[0].source_id.startswith("sec_local_import:")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    snapshot = manifest["snapshots"][0]
    assert Path(snapshot["source_document"]["path"]).read_bytes() == source.read_bytes()
    retained_filing = Path(snapshot["filing_documents"]["0000789019-26-000001"]["path"])
    assert retained_filing.read_bytes() == filing.read_bytes()
    assert snapshot["records"][0]["raw_row"]["rawExtra"] == "retained"


def test_provider_fused_import_keeps_official_session_generation_ephemeral(tmp_path: Path) -> None:
    payload = _payload()
    provider = SecEdgarProvider(
        "SEC fused import tests research@company.org",
        cache_dir=tmp_path / "provider-cache",
        transport=lambda _url, _headers: (json.dumps(payload).encode(), 200, {}),
        rate_limit_seconds=0,
    )

    result = provider.import_submissions(_identity(), import_cache_dir=tmp_path / "import-cache")

    assert result.status == "partial"
    assert result.raw_documents[0].provider_id == "sec_edgar"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    persisted = manifest["snapshots"][0]["source_document"]
    assert persisted["provider_id"] == "sec_local_import"
    assert persisted["source_url"].startswith("file:")
    public_parameters = set(inspect.signature(import_sec_submissions).parameters)
    provider_parameters = set(inspect.signature(provider.import_submissions).parameters)
    assert public_parameters == {
        "source", "identity", "cache_dir", "history_paths", "filing_documents",
        "provenance", "history_provenance", "identity_registry", "publish_guard",
    }
    assert provider_parameters == {"identity", "import_cache_dir", "kwargs"}


def test_fused_304_rejects_sidecar_timestamp_and_reacquires_full_200(tmp_path: Path) -> None:
    payload = json.dumps(_payload()).encode()
    responses = [(payload, 200, {"ETag": '"stable"'}), (b"", 304, {}), (payload, 200, {})]
    requests: list[dict[str, str]] = []

    def transport(_url: str, headers: dict[str, str]) -> tuple[bytes, int, dict[str, str]]:
        requests.append(dict(headers))
        return responses.pop(0)

    provider = SecEdgarProvider(
        "SEC fused timestamp tests research@company.org",
        cache_dir=tmp_path / "provider-cache",
        transport=transport,
        rate_limit_seconds=0,
    )
    original = provider.fetch_submissions("789019")
    metadata_path = tmp_path / "provider-cache" / "submissions_0000789019.json.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    forged_time = original.retrieved_at + timedelta(hours=1)
    metadata["retrieved_at"] = forged_time.isoformat()
    metadata["status"] = 304
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    result = provider.import_submissions(_identity(), import_cache_dir=tmp_path / "import-cache")

    assert result.status == "partial"
    assert result.raw_documents[0].retrieved_at != forged_time
    assert "If-None-Match" not in requests[1]
    assert "If-Modified-Since" not in requests[1]


def test_official_fixture_retains_full_snapshot_with_explicit_provenance(tmp_path: Path) -> None:
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    provenance = RawDocument(FIXTURE, SUBMISSIONS_URL.format(cik="0000789019"), datetime(2026, 9, 3, 5, tzinfo=timezone.utc), digest, "sec_edgar", "sec_submissions", "application/json", 200)
    result = import_sec_submissions(FIXTURE, _identity(), cache_dir=tmp_path / "cache", provenance=provenance)

    assert result.status == "partial"
    assert len(result.records) == 1004
    assert result.raw_documents[0].provider_id == "sec_local_import"
    assert any(warning["code"] == "provenance_unattested" for warning in result.warnings)
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


def test_result_to_dict_is_json_safe_for_raw_documents(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache")
    encoded = json.dumps(result.to_dict())
    assert "raw_documents" in encoded
    assert "+00:00" in encoded


def test_same_source_changed_history_appends_complete_evidence_bundle(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    source = _write(tmp_path / "submissions.json", _payload([{"name": name, "filingCount": 1}]))
    history = _write(tmp_path / name, _payload(columns=_columns("0000789019-25-000001", "10-Q")))
    cache = tmp_path / "cache"
    first = import_sec_submissions(source, _identity(), cache_dir=cache, history_paths={name: history})
    first_manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    first_path = Path(first_manifest["snapshots"][0]["history_documents"][name]["path"])
    history.write_text(json.dumps(_payload(columns=_columns("0000789019-25-000002", "10-Q"))), encoding="utf-8")
    second = import_sec_submissions(source, _identity(), cache_dir=cache, history_paths={name: history})
    manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert second.status == "partial"
    assert len(manifest["snapshots"]) == 2
    assert first_path.read_bytes() != Path(manifest["snapshots"][1]["history_documents"][name]["path"]).read_bytes()


def test_changed_filing_bytes_append_revision_without_overwrite(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    filing = tmp_path / "annual.htm"
    filing.write_bytes(b"revision one")
    cache = tmp_path / "cache"
    first = import_sec_submissions(source, _identity(), cache_dir=cache, filing_documents={"0000789019-26-000001": filing})
    first_manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    first_path = Path(first_manifest["snapshots"][0]["filing_documents"]["0000789019-26-000001"]["path"])
    filing.write_bytes(b"revision two")
    second = import_sec_submissions(source, _identity(), cache_dir=cache, filing_documents={"0000789019-26-000001": filing})
    manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["snapshots"]) == 2
    assert first_path.read_bytes() == b"revision one"
    assert Path(manifest["snapshots"][1]["filing_documents"]["0000789019-26-000001"]["path"]).read_bytes() == b"revision two"


@pytest.mark.parametrize("status", [200, 206, 304])
def test_unbound_filing_provenance_is_local_sec_filing(tmp_path: Path, status: int) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    filing = tmp_path / "annual.htm"
    filing.write_text("<html>filing</html>", encoding="utf-8")
    document = RawDocument(
        filing,
        "https://www.sec.gov/Archives/edgar/data/0000789019/000078901926000001/annual.htm",
        datetime(2026, 9, 3, tzinfo=timezone.utc),
        hashlib.sha256(filing.read_bytes()).hexdigest(),
        "sec_edgar",
        "sec_filing",
        "text/html",
        status,
    )
    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache", filing_documents={"0000789019-26-000001": document})
    assert result.status == "complete"
    assert result.raw_documents[-1].provider_id == "sec_local_import"
    assert result.raw_documents[-1].document_type == "sec_filing"
    assert result.raw_documents[-1].media_type == "text/html"
    assert result.raw_documents[-1].source_url.startswith("file:")


def test_official_filing_foreign_url_is_rejected_without_cache(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    filing = tmp_path / "annual.htm"
    filing.write_text("<html>filing</html>", encoding="utf-8")
    document = RawDocument(
        filing,
        "https://example.invalid/annual.htm",
        datetime(2026, 9, 3, tzinfo=timezone.utc),
        hashlib.sha256(filing.read_bytes()).hexdigest(),
        "sec_edgar",
        "sec_filing",
        "application/json",
        200,
    )
    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache", filing_documents={"0000789019-26-000001": document})
    assert result.status == "failed"
    assert not (tmp_path / "cache").exists()


def test_corrupt_retained_object_blocks_restart_and_preserves_manifest(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    cache = tmp_path / "cache"
    first = import_sec_submissions(source, _identity(), cache_dir=cache)
    before_manifest = first.manifest_path.read_bytes()
    source_object = Path(json.loads(before_manifest)["snapshots"][0]["source_document"]["path"])
    source_object.write_bytes(b"corrupt retained evidence")
    result = import_sec_submissions(source, _identity(), cache_dir=cache)
    assert result.status == "failed"
    assert first.manifest_path.read_bytes() == before_manifest


def test_fabricated_snapshot_metadata_is_rejected_without_rewrite(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    cache = tmp_path / "cache"
    first = import_sec_submissions(source, _identity(), cache_dir=cache)
    before = first.manifest_path.read_bytes()
    payload = json.loads(before)
    payload["snapshots"] = [{}]
    first.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    tampered = first.manifest_path.read_bytes()
    result = import_sec_submissions(source, _identity(), cache_dir=cache)
    assert result.status == "failed"
    assert first.manifest_path.read_bytes() == tampered
    assert before != tampered


def test_noncanonical_instrument_identity_is_rejected_before_io(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    invalid = _identity("789019", " MSFT")
    result = import_sec_submissions(source, invalid, cache_dir=tmp_path / "cache")
    assert result.status == "failed"
    assert "instrument_id" in result.detail
    assert not (tmp_path / "cache").exists()


def test_unsafe_zip_member_is_rejected_before_selected_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "submissions.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("CIK0000789019.json", json.dumps(_payload()))
        package.writestr("../outside.json", b"must not extract")
    result = import_sec_submissions(archive, _identity(), cache_dir=tmp_path / "cache")
    assert result.status == "failed"
    assert not (tmp_path / "outside.json").exists()


def test_caller_authored_metadata_cannot_admit_official_submissions(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions_0000789019_abcdef0123456789.json", _payload())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    acquired_at = datetime(2026, 9, 3, 5, tzinfo=timezone.utc)
    (tmp_path / "submissions_0000789019.json.meta.json").write_text(json.dumps({
        "schema_version": 1,
        "source_url": SUBMISSIONS_URL.format(cik="0000789019"),
        "retrieved_at": acquired_at.isoformat(),
        "sha256": digest,
        "raw_path": str(source.absolute()),
        "etag": "",
        "last_modified": "",
    }), encoding="utf-8")
    provenance = RawDocument(source, SUBMISSIONS_URL.format(cik="0000789019"), acquired_at, digest, "sec_edgar", "sec_submissions", "application/json", 200)

    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache", provenance=provenance)

    assert result.status == "partial"
    assert result.raw_documents[0].provider_id == "sec_local_import"
    assert any(warning["code"] == "provenance_unattested" for warning in result.warnings)


def test_caller_authored_metadata_downgrades_parent_and_detached_history(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    source = _write(tmp_path / "submissions_0000789019_abcdef0123456789.json", _payload([{"name": name, "filingCount": 1}]))
    history = _write(tmp_path / name, _payload(columns=_columns("0000789019-25-000001", "10-Q")))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    acquired_at = datetime(2025, 12, 31, tzinfo=timezone.utc)
    (tmp_path / "submissions_0000789019.json.meta.json").write_text(json.dumps({
        "schema_version": 1,
        "source_url": SUBMISSIONS_URL.format(cik="0000789019"),
        "retrieved_at": acquired_at.isoformat(),
        "sha256": digest,
        "raw_path": str(source.absolute()),
        "etag": "",
        "last_modified": "",
    }), encoding="utf-8")
    provenance = RawDocument(source, SUBMISSIONS_URL.format(cik="0000789019"), acquired_at, digest, "sec_edgar", "sec_submissions", "application/json", 200)

    result = import_sec_submissions(
        source,
        _identity(),
        cache_dir=tmp_path / "cache",
        history_paths={name: history},
        provenance=provenance,
    )

    assert result.status == "partial"
    assert result.records[0].source_id.startswith("sec_local_import:")
    assert result.records[1].source_id.startswith("sec_local_import:")


def test_missing_filings_files_stays_partial_even_with_filing_bytes(tmp_path: Path) -> None:
    payload = _payload()
    del payload["filings"]["files"]
    source = _write(tmp_path / "submissions.json", payload)
    filing = _write(tmp_path / "annual.htm", "<html>filing</html>")

    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache", filing_documents={"0000789019-26-000001": filing})

    assert result.status == "partial"
    assert any(warning["code"] == "history_advertisement_missing" for warning in result.warnings)


def test_detached_history_has_independent_capture_time(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    source = _write(tmp_path / "submissions.json", _payload([{"name": name, "filingCount": 1}]))
    history = _write(tmp_path / name, _payload(columns=_columns("0000789019-25-000001", "10-Q")))

    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache", history_paths={name: history})
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    snapshot = manifest["snapshots"][0]

    assert snapshot["history_documents"][name]["retrieved_at"] != snapshot["source_document"]["retrieved_at"]
    assert result.records[1].available_at == result.records[1].accepted_at


@pytest.mark.parametrize("status", [206, 304])
def test_unbound_partial_or_revalidated_provenance_is_downgraded(tmp_path: Path, status: int) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    provenance = RawDocument(source, SUBMISSIONS_URL.format(cik="0000789019"), datetime(2026, 9, 3, 5, tzinfo=timezone.utc), digest, "sec_edgar", "sec_submissions", "application/json", status)

    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache", provenance=provenance)

    assert result.status == "partial"
    assert result.raw_documents[0].provider_id == "sec_local_import"
    assert any(warning["code"] == "provenance_unattested" for warning in result.warnings)


@pytest.mark.parametrize("field", ["filing_documents", "history_provenance"])
def test_malformed_mapping_inputs_return_controlled_failure(tmp_path: Path, field: str) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    kwargs: dict[str, object] = {field: []}

    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache", **kwargs)  # type: ignore[arg-type]

    assert result.status == "failed"
    assert "mapping" in result.detail

@pytest.mark.parametrize("bulk", [False, True])
def test_fused_cancel_preserves_acquisition_and_import_cache(tmp_path: Path, bulk: bool) -> None:
    from io import BytesIO

    payload = json.dumps(_payload()).encode()
    if bulk:
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("CIK0000789019.json", payload)
        payload = output.getvalue()
    provider = SecEdgarProvider(
        "SEC cancellation tests research@company.org", cache_dir=tmp_path / "raw",
        transport=lambda *_: (payload, 200, {}), rate_limit_seconds=0, max_retries=0,
    )
    acquire_import = provider.import_submissions_bulk if bulk else provider.import_submissions
    acquire_import(_identity(), import_cache_dir=tmp_path / "import")
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    def cancel():
        raise WorkflowTransitionError("cancelled")

    with pytest.raises(WorkflowTransitionError):
        acquire_import(_identity(), import_cache_dir=tmp_path / "import", publish_guard=cancel)
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before
