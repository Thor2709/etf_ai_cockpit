from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from typing import Iterator
import zipfile

import pytest

from etf_cockpit.application import sec_submissions_import as submissions_module
from etf_cockpit.application.sec_submissions_import import (
    SUBMISSIONS_BULK_URL,
    SUBMISSIONS_URL,
    import_sec_submissions,
)
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers.contracts import RawDocument


def _identity(cik: str = "789019", instrument: str = "MSFT") -> CanonicalIdentity:
    return CanonicalIdentity(
        instrument,
        "Microsoft",
        None,
        "needs_verification",
        "",
        None,
        None,
        "stock",
        {},
        "manual_review",
        (),
        cik,
    )


def _columns(accession: str = "0000789019-26-000001", form: str = "10-K", primary: str = "annual.htm") -> dict[str, list[object]]:
    return {
        "accessionNumber": [accession],
        "filingDate": ["2026-01-02"],
        "reportDate": ["2025-12-31"],
        "acceptanceDateTime": ["2026-01-02T03:04:05.000Z"],
        "form": [form],
        "primaryDocument": [primary],
        "rawExtra": ["retained"],
    }


def _payload(
    files: list[dict[str, object]] | None = None,
    columns: dict[str, list[object]] | None = None,
) -> dict[str, object]:
    return {
        "cik": "0000789019",
        "name": "MICROSOFT CORP",
        "filings": {"recent": columns or _columns(), "files": files or []},
    }


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _archive(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        for name, payload in members.items():
            package.writestr(name, payload)
    return path


def _official(path: Path, url: str, document_type: str, media_type: str) -> RawDocument:
    return RawDocument(
        path,
        url,
        datetime(2026, 9, 3, 5, tzinfo=timezone.utc),
        hashlib.sha256(path.read_bytes()).hexdigest(),
        "sec_edgar",
        document_type,
        media_type,
        200,
    )


def _manifest(result: object) -> tuple[Path, dict[str, object]]:
    path = result.manifest_path
    assert isinstance(path, Path)
    return path, json.loads(path.read_text(encoding="utf-8"))


def _rewrite_manifest(path: Path, payload: dict[str, object], snapshot: dict[str, object]) -> None:
    snapshot["bundle_sha256"] = submissions_module._bundle_sha256(
        {key: value for key, value in snapshot.items() if key != "bundle_sha256"}
    )
    payload["latest_source_sha256"] = snapshot["source_sha256"]
    payload["latest_bundle_sha256"] = snapshot["bundle_sha256"]
    path.write_text(json.dumps(payload), encoding="utf-8")


def _directory_alias_or_skip(alias: Path, target: Path) -> None:
    target.mkdir(parents=True)
    alias.parent.mkdir(parents=True, exist_ok=True)
    try:
        alias.symlink_to(target, target_is_directory=True)
        return
    except (OSError, NotImplementedError) as exc:
        if os.name != "nt":
            pytest.skip(f"directory symlink creation is unsupported: {type(exc).__name__}: {exc}")
    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(alias), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        pytest.skip(
            "directory junction creation is unsupported: "
            f"{detail or f'returncode={result.returncode}'}"
        )


def test_manifest_link_is_rejected_before_external_manifest_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    cache = tmp_path / "cache"
    records = cache / "sec_submissions_import" / "records"
    external = tmp_path / "external-records"
    _directory_alias_or_skip(records, external)
    manifest = external / "CIK0000789019.json"
    manifest.write_text('{"tampered": true}', encoding="utf-8")
    reads: list[Path] = []
    original_read_text = Path.read_text

    def probe_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path.resolve() == manifest.resolve():
            reads.append(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", probe_read_text)
    result = import_sec_submissions(source, _identity(), cache_dir=cache)

    assert result.status == "failed"
    assert reads == []
    assert manifest.read_text(encoding="utf-8") == '{"tampered": true}'


def test_actual_digest_prefix_link_is_rejected_before_external_mutation(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest.startswith("00"):
        source = _write(tmp_path / "submissions.json", {**_payload(), "name": "MICROSOFT CORP 2"})
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
    namespace = tmp_path / "cache" / "sec_submissions_import"
    prefix = namespace / "objects" / "sha256" / digest[:2]
    external = tmp_path / "external-objects"
    _directory_alias_or_skip(prefix, external)
    marker = external / "marker.txt"
    marker.write_bytes(b"keep")

    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache")

    assert result.status == "failed"
    assert marker.read_bytes() == b"keep"
    assert sorted(path.name for path in external.iterdir()) == ["marker.txt"]


def test_unsafe_import_guard_is_rejected_before_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    cache = tmp_path / "cache"
    guard_path = cache / "sec_submissions_import" / "import.guard"
    original_guard = submissions_module.persistent_file_guard
    original_is_reparse = submissions_module._is_reparse
    opened: list[Path] = []

    def guard_is_reparse(path: Path) -> bool:
        # Simulate only the platform reparse attribute; admission and the real
        # guard implementation remain unchanged on all supported platforms.
        return Path(path).absolute() == guard_path.absolute() or original_is_reparse(path)

    @contextmanager
    def observed_guard(path: Path, **kwargs: object) -> Iterator[object]:
        if Path(path).absolute() == guard_path.absolute():
            opened.append(Path(path))
        with original_guard(path, **kwargs) as guard:
            yield guard

    monkeypatch.setattr(submissions_module, "persistent_file_guard", observed_guard)
    monkeypatch.setattr(submissions_module, "_is_reparse", guard_is_reparse)

    result = import_sec_submissions(source, _identity(), cache_dir=cache)

    assert result.status == "failed"
    assert opened == []


def test_persisted_history_key_cannot_escape_replay_root(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    source = _write(tmp_path / "submissions.json", _payload([{"name": name, "filingCount": 1}]))
    history = _write(tmp_path / name, _payload(columns=_columns("0000789019-25-000001", "10-Q")))
    cache = tmp_path / "cache"
    first = import_sec_submissions(source, _identity(), cache_dir=cache, history_paths={name: history})
    manifest_path, payload = _manifest(first)
    snapshot = payload["snapshots"][0]
    history_item = snapshot["history_documents"].pop(name)
    outside = tmp_path / "outside-history.json"
    outside.write_bytes(b"keep")
    snapshot["history_documents"][str(outside)] = history_item
    _rewrite_manifest(manifest_path, payload, snapshot)

    result = import_sec_submissions(source, _identity(), cache_dir=cache, history_paths={name: history})

    assert result.status == "failed"
    assert outside.read_bytes() == b"keep"
    assert manifest_path.read_bytes() == json.dumps(payload).encode()


def test_official_history_metadata_stays_bound_to_advertised_source(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    current = json.dumps(_payload([{"name": name, "filingCount": 1}])).encode()
    history = json.dumps(_payload(columns=_columns("0000789019-25-000001", "10-Q"))).encode()
    archive = _archive(tmp_path / "submissions.zip", {
        "CIK0000789019.json": current,
        name: history,
    })
    provenance = _official(archive, SUBMISSIONS_BULK_URL, "sec_submissions_bulk", "application/zip")
    cache = tmp_path / "cache"
    first = import_sec_submissions(archive, _identity(), cache_dir=cache, provenance=provenance)
    manifest_path, payload = _manifest(first)
    snapshot = payload["snapshots"][0]
    snapshot["history_documents"][name]["source_url"] = SUBMISSIONS_URL.format(cik="0000789019")
    _rewrite_manifest(manifest_path, payload, snapshot)
    before = manifest_path.read_bytes()

    result = import_sec_submissions(archive, _identity(), cache_dir=cache, provenance=provenance)

    assert result.status == "failed"
    assert manifest_path.read_bytes() == before


def test_complete_snapshot_requires_filing_objects_and_consistent_coverage(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    filing = tmp_path / "annual.htm"
    filing.write_text("<html>filing</html>", encoding="utf-8")
    cache = tmp_path / "cache"
    first = import_sec_submissions(
        source,
        _identity(),
        cache_dir=cache,
        filing_documents={"0000789019-26-000001": filing},
    )
    manifest_path, payload = _manifest(first)
    snapshot = payload["snapshots"][0]
    snapshot["filing_documents"] = {}
    snapshot["warnings"] = []
    snapshot["coverage_status"] = "complete"
    _rewrite_manifest(manifest_path, payload, snapshot)
    before = manifest_path.read_bytes()

    result = import_sec_submissions(
        source,
        _identity(),
        cache_dir=cache,
        filing_documents={"0000789019-26-000001": filing},
    )

    assert result.status == "failed"
    assert manifest_path.read_bytes() == before


def test_restart_rejects_detached_provenance_acquisition_timestamp(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    filing = tmp_path / "annual.htm"
    filing.write_text("<html>filing</html>", encoding="utf-8")
    cache = tmp_path / "cache"
    first = import_sec_submissions(
        source,
        _identity(),
        cache_dir=cache,
        filing_documents={"0000789019-26-000001": filing},
    )
    manifest_path, payload = _manifest(first)
    snapshot = payload["snapshots"][0]
    timestamp = datetime.fromisoformat(snapshot["provenance"]["retrieved_at"])
    snapshot["provenance"]["retrieved_at"] = (timestamp + timedelta(hours=1)).isoformat()
    _rewrite_manifest(manifest_path, payload, snapshot)
    before = manifest_path.read_bytes()

    result = import_sec_submissions(
        source,
        _identity(),
        cache_dir=cache,
        filing_documents={"0000789019-26-000001": filing},
    )

    assert result.status == "failed"
    assert manifest_path.read_bytes() == before


def test_a_to_b_to_a_restart_keeps_latest_snapshot_consistent(tmp_path: Path) -> None:
    source_a = _write(tmp_path / "a.json", _payload())
    source_b = _write(
        tmp_path / "b.json",
        _payload(columns=_columns("0000789019-26-000002", "10-K/A")),
    )
    provenance_a = _official(source_a, SUBMISSIONS_URL.format(cik="0000789019"), "sec_submissions", "application/json")
    provenance_b = _official(source_b, SUBMISSIONS_URL.format(cik="0000789019"), "sec_submissions", "application/json")
    cache = tmp_path / "cache"
    first = import_sec_submissions(source_a, _identity(), cache_dir=cache, provenance=provenance_a)
    second = import_sec_submissions(source_b, _identity(), cache_dir=cache, provenance=provenance_b)
    third = import_sec_submissions(source_a, _identity(), cache_dir=cache, provenance=provenance_a)
    assert first.status == second.status == third.status == "partial"
    manifest_path, payload = _manifest(third)
    assert len(payload["snapshots"]) == 2

    restart = import_sec_submissions(source_a, _identity(), cache_dir=cache, provenance=provenance_a)

    assert restart.status == "partial"
    assert manifest_path.is_file()
    assert len(json.loads(manifest_path.read_text(encoding="utf-8"))["snapshots"]) == 2


def test_same_cik_publication_rechecks_differing_instrument_under_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    barrier = threading.Barrier(2)
    original_publish = submissions_module._publish_manifest

    def synchronized_publish(*args: object, **kwargs: object):
        barrier.wait(timeout=5)
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(submissions_module, "_publish_manifest", synchronized_publish)

    def run(instrument: str):
        return import_sec_submissions(source, _identity(instrument=instrument), cache_dir=tmp_path / "cache")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(run, instrument) for instrument in ("MSFT", "OTHER")]
        values = [future.result(timeout=10) for future in results]

    assert {value.status for value in values} == {"partial", "failed"}


def test_manifest_size_bound_is_enforced_before_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    columns = _columns()
    columns["rawExtra"] = ["x" * 4_000]
    source = _write(tmp_path / "submissions.json", _payload(columns=columns))
    monkeypatch.setattr(submissions_module, "MAX_MANIFEST_BYTES", 1_024)

    result = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "cache")

    assert result.status == "failed"
    manifest = tmp_path / "cache" / "sec_submissions_import" / "records" / "CIK0000789019.json"
    assert not manifest.exists()


def test_named_history_endpoint_is_supported(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    source = _write(tmp_path / "submissions.json", _payload([{"name": name, "filingCount": 1}]))
    history = _write(tmp_path / name, _payload(columns=_columns("0000789019-25-000001", "10-Q")))
    history_url = f"https://data.sec.gov/submissions/{name}"
    history_document = _official(history, history_url, "sec_submissions", "application/json")
    history_result = import_sec_submissions(
        source,
        _identity(),
        cache_dir=tmp_path / "history-cache",
        history_paths={name: history},
        history_provenance={name: history_document},
    )
    assert history_result.status == "partial"


def test_third_party_accession_and_unpadded_company_cik_filing_url_are_supported(tmp_path: Path) -> None:
    columns = _columns("0001193125-26-323660", "10-Q", "msft-20260630.htm")
    filing_source = _write(tmp_path / "filing-source.json", _payload(columns=columns))
    filing = tmp_path / "msft-20260630.htm"
    filing.write_text("<html>filing</html>", encoding="utf-8")
    filing_url = "https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm"
    filing_document = _official(filing, filing_url, "sec_filing", "text/html")
    filing_result = import_sec_submissions(
        filing_source,
        _identity(),
        cache_dir=tmp_path / "filing-cache",
        filing_documents={"0001193125-26-323660": filing_document},
    )

    assert filing_result.status == "complete"


def test_current_snapshot_endpoint_cannot_be_reused_for_named_history(tmp_path: Path) -> None:
    name = "CIK0000789019-submissions-001.json"
    source = _write(tmp_path / "submissions.json", _payload([{"name": name, "filingCount": 1}]))
    history = _write(tmp_path / name, _payload(columns=_columns("0000789019-25-000001", "10-Q")))
    history_document = _official(history, SUBMISSIONS_URL.format(cik="0000789019"), "sec_submissions", "application/json")

    result = import_sec_submissions(
        source,
        _identity(),
        cache_dir=tmp_path / "cache",
        history_paths={name: history},
        history_provenance={name: history_document},
    )

    assert result.status == "failed"


def test_zip_selected_and_external_history_share_one_aggregate_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "CIK0000789019-submissions-001.json"
    current_payload = _payload([{"name": name, "filingCount": 1}], _columns())
    current_payload["padding"] = "c" * 500
    history_payload = _payload(columns=_columns("0000789019-25-000001", "10-Q"))
    history_payload["padding"] = "h" * 500
    current = json.dumps(current_payload).encode()
    history = _write(tmp_path / name, history_payload)
    archive = _archive(tmp_path / "submissions.zip", {"CIK0000789019.json": current})
    monkeypatch.setattr(submissions_module, "MAX_SELECTED_BYTES", 1_000)

    result = import_sec_submissions(
        archive,
        _identity(),
        cache_dir=tmp_path / "cache",
        history_paths={name: history},
    )

    assert result.status == "failed"


def test_identical_official_json_restart_reuses_one_generation_and_fixed_lineage(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    provenance = _official(
        source,
        SUBMISSIONS_URL.format(cik="0000789019"),
        "sec_submissions",
        "application/json",
    )
    cache = tmp_path / "cache"

    first = import_sec_submissions(source, _identity(), cache_dir=cache, provenance=provenance)
    second = import_sec_submissions(source, _identity(), cache_dir=cache, provenance=provenance)

    manifest_path, payload = _manifest(second)
    assert first.status == second.status == "partial"
    assert len(payload["snapshots"]) == 1
    snapshot = payload["snapshots"][0]
    assert snapshot["source_document"]["source_url"] == provenance.source_url
    assert snapshot["source_document"]["retrieved_at"] == provenance.retrieved_at.isoformat()
    assert snapshot["provenance"]["retrieved_at"] == provenance.retrieved_at.isoformat()
    assert Path(snapshot["source_document"]["path"]).is_file()
    assert manifest_path.is_file()


def test_identical_official_zip_restart_reuses_one_generation_and_retains_member_lineage(tmp_path: Path) -> None:
    source_bytes = json.dumps(_payload()).encode()
    archive = _archive(tmp_path / "submissions.zip", {"CIK0000789019.json": source_bytes})
    provenance = _official(archive, SUBMISSIONS_BULK_URL, "sec_submissions_bulk", "application/zip")
    cache = tmp_path / "cache"

    first = import_sec_submissions(archive, _identity(), cache_dir=cache, provenance=provenance)
    second = import_sec_submissions(archive, _identity(), cache_dir=cache, provenance=provenance)

    _, payload = _manifest(second)
    assert first.status == second.status == "partial"
    assert len(payload["snapshots"]) == 1
    snapshot = payload["snapshots"][0]
    source_document = snapshot["source_document"]
    member = snapshot["snapshot_member"]
    assert source_document["source_url"] == provenance.source_url
    assert source_document["retrieved_at"] == provenance.retrieved_at.isoformat()
    assert snapshot["provenance"]["retrieved_at"] == provenance.retrieved_at.isoformat()
    assert member["source_url"] == provenance.source_url
    assert member["retrieved_at"] == provenance.retrieved_at.isoformat()
    assert Path(source_document["path"]).is_file()
    assert Path(member["path"]).is_file()
    assert Path(member["path"]).read_bytes() == source_bytes


def test_zip_snapshot_member_bytes_remain_bound_to_the_retained_archive(tmp_path: Path) -> None:
    source_a = json.dumps(_payload()).encode()
    source_b = json.dumps(_payload(columns=_columns("0000789019-26-000002", "10-K/A"))).encode()
    archive_a = _archive(tmp_path / "a.zip", {"CIK0000789019.json": source_a})
    archive_b = _archive(tmp_path / "b.zip", {"CIK0000789019.json": source_b})
    provenance_a = _official(archive_a, SUBMISSIONS_BULK_URL, "sec_submissions_bulk", "application/zip")
    provenance_b = _official(archive_b, SUBMISSIONS_BULK_URL, "sec_submissions_bulk", "application/zip")
    cache = tmp_path / "cache"

    first = import_sec_submissions(archive_a, _identity(), cache_dir=cache, provenance=provenance_a)
    second = import_sec_submissions(archive_b, _identity(), cache_dir=cache, provenance=provenance_b)
    assert first.status == second.status == "partial"
    manifest_path, payload = _manifest(second)
    snapshots = payload["snapshots"]
    snapshot_a = snapshots[0]
    snapshot_b = snapshots[1]
    member_a = snapshot_a["snapshot_member"]
    member_b = snapshot_b["snapshot_member"]
    assert Path(snapshot_a["source_document"]["path"]).read_bytes() != Path(member_b["path"]).read_bytes()
    assert Path(member_a["path"]).read_bytes() != Path(member_b["path"]).read_bytes()

    snapshot_a["snapshot_member"] = dict(member_b)
    snapshot_a["records"] = snapshot_b["records"]
    snapshot_a["bundle_sha256"] = submissions_module._bundle_sha256(
        {key: value for key, value in snapshot_a.items() if key != "bundle_sha256"}
    )
    payload["snapshots"] = snapshots
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    before = manifest_path.read_bytes()

    result = import_sec_submissions(archive_a, _identity(), cache_dir=cache, provenance=provenance_a)

    assert result.status == "failed"
    assert manifest_path.read_bytes() == before


@pytest.mark.parametrize("source_kind", ["json", "zip"])
def test_identical_local_restart_preserves_generation_and_admitted_lineage(tmp_path: Path, source_kind: str) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    if source_kind == "zip":
        source = _archive(tmp_path / "submissions.zip", {"CIK0000789019.json": source.read_bytes()})
    cache = tmp_path / "cache"
    first = import_sec_submissions(source, _identity(), cache_dir=cache)
    _, first_manifest = _manifest(first)
    second = import_sec_submissions(source, _identity(), cache_dir=cache)
    _, second_manifest = _manifest(second)

    assert first.status == second.status == "partial"
    assert len(first_manifest["snapshots"]) == len(second_manifest["snapshots"]) == 1
    assert first_manifest == second_manifest
    assert [(item.source_url, item.retrieved_at, item.sha256) for item in first.raw_documents] == [
        (item.source_url, item.retrieved_at, item.sha256) for item in second.raw_documents
    ]
    assert all(item.path.is_file() for item in second.raw_documents)
    assert all("sec-submissions-import-" not in item.source_url for item in second.raw_documents)


def test_local_generation_lineage_remains_meaningful_across_json_and_zip(tmp_path: Path) -> None:
    source = _write(tmp_path / "submissions.json", _payload())
    first = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "json-cache")
    second = import_sec_submissions(source, _identity(), cache_dir=tmp_path / "json-cache")
    archive = _archive(tmp_path / "submissions.zip", {"CIK0000789019.json": source.read_bytes()})
    zipped = import_sec_submissions(archive, _identity(), cache_dir=tmp_path / "zip-cache")

    assert first.status == second.status == zipped.status == "partial"
    assert first.raw_documents and second.raw_documents and zipped.raw_documents
    assert all(document.source_url.startswith("file:") for document in first.raw_documents + second.raw_documents + zipped.raw_documents)
    assert all(document.retrieved_at.tzinfo is not None for document in first.raw_documents + second.raw_documents + zipped.raw_documents)
