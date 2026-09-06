from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator
import zipfile

import pandas as pd
import pytest

from etf_cockpit.application import sec_bulk_import as bulk_module
from etf_cockpit.application.sec_bulk_import import (
    SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE,
    SEC_COMPANYFACTS_BULK_URL,
    import_sec_companyfacts_bulk,
)
from etf_cockpit.data import trust_artifacts
from etf_cockpit.data.bulk_cache import BulkCacheError
from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.parsers import sec_facts
from etf_cockpit.parsers.contracts import RawDocument
from etf_cockpit.parsers.sec_facts import StatementFact, write_statement_evidence


def _identity(cik: str = "1", instrument_id: str = "ONE") -> CanonicalIdentity:
    return CanonicalIdentity(
        instrument_id,
        instrument_id,
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


def _facts(cik: int = 1, value: int = 10) -> bytes:
    return json.dumps(
        {
            "cik": cik,
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {
                                    "val": value,
                                    "end": "2024-12-31",
                                    "form": "10-K",
                                    "filed": "2025-01-01",
                                }
                            ]
                        }
                    }
                }
            },
        }
    ).encode()


def _archive(tmp_path: Path, members: dict[str, bytes]) -> Path:
    path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, payload in members.items():
            package.writestr(name, payload)
    return path


def _run(archive: Path, tmp_path: Path, identities: tuple[CanonicalIdentity, ...] = (_identity(),), **kwargs):
    return import_sec_companyfacts_bulk(
        archive,
        identities,
        cache_dir=tmp_path / "cache",
        facts_destination=tmp_path / "facts.parquet",
        inventory_destination=tmp_path / "inventory.parquet",
        **kwargs,
    )


def _record(cik: str = "1", value: int = 10) -> StatementFact:
    return StatementFact(
        instrument_id="ONE",
        cik=cik,
        taxonomy="us-gaap",
        concept="Assets",
        unit="USD",
        value=value,
        start=None,
        end="2024-12-31",
        instant="2024-12-31",
        filed="2025-01-01",
        form="10-K",
        accession="0000001-24-000001",
        fiscal_year=2024,
        fiscal_period="FY",
        source_id=f"sec_edgar:{cik}:assets:{value}",
        canonical_metric="assets",
        mapping_status="mapped",
    )


def _source(tmp_path: Path, *, cik: str = "1", value: int = 10) -> RawDocument:
    path = tmp_path / f"{cik}-{value}.json"
    path.write_bytes(_facts(int(cik), value))
    return RawDocument(
        path,
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json",
        datetime.now(timezone.utc),
        hashlib.sha256(path.read_bytes()).hexdigest(),
        "sec_edgar",
        "sec_companyfacts",
        "application/json",
        200,
    )


def _directory_alias_or_skip(alias: Path, target: Path) -> None:
    target.mkdir(parents=True)
    try:
        alias.symlink_to(target, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        if os.name != "nt":
            pytest.skip("directory symlink creation is unsupported")
    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(alias), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("directory junction creation is unsupported")


def _file_alias_or_skip(alias: Path, target: Path) -> None:
    try:
        alias.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("file symlink creation is unsupported on this host")


def _sentinel_snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


def _assert_alias_failure(result: object) -> None:
    assert result.overall_status == "failed"
    detail = result.per_cik[0].detail.lower()
    assert "symlink" in detail or "reparse" in detail or "cache" in detail


def test_resume_parquet_reads_hold_both_canonical_statement_store_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resume validation read must share the writer's two-store critical section."""

    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    assert _run(archive, tmp_path).per_cik[0].status == "imported"

    facts_path = (tmp_path / "facts.parquet").resolve()
    inventory_path = (tmp_path / "inventory.parquet").resolve()
    required = {
        facts_path.with_name(f"{facts_path.name}.guard"),
        inventory_path.with_name(f"{inventory_path.name}.guard"),
    }
    held: set[Path] = set()
    violations: list[tuple[Path, tuple[Path, ...]]] = []

    @contextmanager
    def probe_guard(path: Path, **_kwargs: object) -> Iterator[object]:
        normalized = Path(path).resolve()
        held.add(normalized)
        try:
            yield object()
        finally:
            held.remove(normalized)

    original_read = pd.read_parquet

    def probe_read(path: object, *args: object, **kwargs: object):
        normalized = Path(path).resolve()
        if normalized in {facts_path, inventory_path} and not required.issubset(held):
            violations.append((normalized, tuple(sorted(held))))
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(sec_facts, "persistent_file_guard", probe_guard)
    monkeypatch.setattr(pd, "read_parquet", probe_read)

    resumed = _run(archive, tmp_path)

    assert resumed.per_cik[0].status == "skipped"
    assert violations == []


def test_trust_refresh_and_canonical_statement_writer_serialize_on_same_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trust refresh guard must exclude a canonical writer until refresh completes."""

    filings_path = tmp_path / "filings_statements.parquet"
    raw_filings = tmp_path / "raw" / "filings"
    raw_filings.mkdir(parents=True)
    (raw_filings / "ONE-filing.txt").write_text("filing", encoding="utf-8")
    identity = pd.DataFrame({"instrument_id": ["ONE"]})
    writer_source = _source(tmp_path, value=11)
    facts_path = tmp_path / "facts.parquet"
    guard_path = filings_path.resolve().with_name(f"{filings_path.name}.guard")
    trust_holding = threading.Event()
    writer_attempted = threading.Event()
    release_trust = threading.Event()
    writer_done = threading.Event()
    errors: list[BaseException] = []

    original_trust_guard = trust_artifacts.persistent_file_guard
    original_facts_guard = sec_facts.persistent_file_guard
    original_append = trust_artifacts._append_parquet

    @contextmanager
    def trust_guard(path: Path, **kwargs: object) -> Iterator[object]:
        with original_trust_guard(path, **kwargs) as guard:
            if Path(path).resolve() == guard_path:
                trust_holding.set()
            yield guard

    @contextmanager
    def writer_guard(path: Path, **kwargs: object) -> Iterator[object]:
        if Path(path).resolve() == guard_path:
            writer_attempted.set()
        with original_facts_guard(path, **kwargs) as guard:
            yield guard

    def controlled_append(*args: object, **kwargs: object):
        assert trust_holding.is_set()
        assert release_trust.wait(timeout=5)
        return original_append(*args, **kwargs)

    def refresh() -> None:
        try:
            trust_artifacts._append_filings_statement_inventory(identity)
        except BaseException as exc:
            errors.append(exc)

    def write() -> None:
        try:
            write_statement_evidence(
                writer_source,
                (_record(value=11),),
                facts_path,
                filings_path,
                instrument_id="ONE",
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            writer_done.set()

    monkeypatch.setattr(trust_artifacts, "FILINGS_STATEMENTS_PATH", filings_path)
    monkeypatch.setattr(trust_artifacts, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(trust_artifacts, "persistent_file_guard", trust_guard)
    monkeypatch.setattr(sec_facts, "persistent_file_guard", writer_guard)
    monkeypatch.setattr(trust_artifacts, "_append_parquet", controlled_append)

    with ThreadPoolExecutor(max_workers=2) as executor:
        refresh_future = executor.submit(refresh)
        assert trust_holding.wait(timeout=5)
        writer_future = executor.submit(write)
        assert writer_attempted.wait(timeout=5)
        assert not writer_done.is_set()
        release_trust.set()
        refresh_future.result(timeout=5)
        writer_future.result(timeout=5)

    assert errors == []
    assert filings_path.is_file()
    assert facts_path.is_file()


def test_resume_matches_provider_specific_inventory_rows_and_preserves_both_sources(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    official = RawDocument(
        archive,
        SEC_COMPANYFACTS_BULK_URL,
        datetime(2026, 9, 3, tzinfo=timezone.utc),
        digest,
        "sec_edgar",
        SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE,
        "application/zip",
        200,
    )

    local_first = _run(archive, tmp_path)
    local_resume = _run(archive, tmp_path)
    official_first = _run(archive, tmp_path, provenance=official)
    official_resume = _run(archive, tmp_path, provenance=official)
    local_switch = _run(archive, tmp_path)
    local_repeat = _run(archive, tmp_path)

    assert local_first.per_cik[0].status == "imported"
    assert local_resume.per_cik[0].status == "skipped"
    assert official_first.per_cik[0].status == "imported"
    assert official_resume.per_cik[0].status == "skipped"
    assert local_switch.per_cik[0].status == "imported"
    assert local_repeat.per_cik[0].status == "skipped"
    inventory = pd.read_parquet(tmp_path / "inventory.parquet")
    assert set(inventory["source_authority"]) == {"manual_review", "official_regulator"}


@pytest.mark.parametrize("official", [False, True])
@pytest.mark.parametrize("field", ["ingested_at", "authority_selection", "executable_authority"])
def test_resume_repairs_altered_persisted_time_and_authority(
    tmp_path: Path, official: bool, field: str
) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    provenance = RawDocument(
        archive,
        SEC_COMPANYFACTS_BULK_URL,
        datetime(2026, 9, 3, tzinfo=timezone.utc),
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        "sec_edgar",
        SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE,
        "application/zip",
        200,
    ) if official else None
    assert _run(archive, tmp_path, provenance=provenance).per_cik[0].status == "imported"
    assert _run(archive, tmp_path, provenance=provenance).per_cik[0].status == "skipped"

    path = tmp_path / ("facts.parquet" if field == "authority_selection" else "inventory.parquet")
    frame = pd.read_parquet(path)
    if field == "ingested_at":
        frame[field] = "2000-01-01T00:00:00+00:00"
    elif field == "authority_selection":
        frame[field] = "manual_review" if official else "canonical_sec"
    else:
        frame[field] = True
    frame.to_parquet(path, index=False)

    repaired = _run(archive, tmp_path, provenance=provenance)
    assert repaired.per_cik[0].status == "imported"
    assert repaired.execution_allowed is False
    inventory = pd.read_parquet(tmp_path / "inventory.parquet")
    facts = pd.read_parquet(tmp_path / "facts.parquet")
    checkpoint = json.loads(repaired.checkpoint_path.read_text(encoding="utf-8"))
    assert inventory.iloc[0]["ingested_at"] == checkpoint["entries"]["0000000001"]["retrieved_at"]
    assert inventory.iloc[0]["executable_authority"].item() is False
    assert set(facts["authority_selection"]) == {"canonical_sec" if official else "manual_review"}
    assert _run(archive, tmp_path, provenance=provenance).per_cik[0].status == "skipped"


def test_resume_replays_authority_after_a_newer_canonical_writer_fact(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    provenance = RawDocument(
        archive, SEC_COMPANYFACTS_BULK_URL,
        datetime(2026, 9, 3, tzinfo=timezone.utc),
        hashlib.sha256(archive.read_bytes()).hexdigest(), "sec_edgar",
        SEC_COMPANYFACTS_BULK_DOCUMENT_TYPE, "application/zip", 200,
    )
    assert _run(archive, tmp_path, provenance=provenance).per_cik[0].status == "imported"
    newer = replace(_record(value=11), filed="2026-01-01", form="10-K/A")
    write_statement_evidence(
        _source(tmp_path, value=11), (newer,), tmp_path / "facts.parquet",
        tmp_path / "inventory.parquet", instrument_id="ONE",
    )
    frame = pd.read_parquet(tmp_path / "facts.parquet")
    older_rows = frame["source_id"] != newer.source_id
    assert set(frame.loc[older_rows, "authority_selection"]) == {"retained_sec"}
    assert _run(archive, tmp_path, provenance=provenance).per_cik[0].status == "skipped"

    frame.loc[older_rows, "authority_selection"] = "canonical_sec"
    frame.to_parquet(tmp_path / "facts.parquet", index=False)
    assert _run(archive, tmp_path, provenance=provenance).per_cik[0].status == "imported"
    repaired = pd.read_parquet(tmp_path / "facts.parquet")
    assert set(repaired.loc[repaired["source_id"] != newer.source_id, "authority_selection"]) == {"retained_sec"}
    assert set(repaired.loc[repaired["source_id"] == newer.source_id, "authority_selection"]) == {"canonical_sec"}
    assert _run(archive, tmp_path, provenance=provenance).per_cik[0].status == "skipped"


@pytest.mark.parametrize("alias_kind", ["base", "staging_downloads", "object_prefix"])
def test_import_rejects_preexisting_cache_directory_aliases_before_sentinel_mutation(
    tmp_path: Path, alias_kind: str
) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    root = tmp_path / "cache"
    root.mkdir()
    namespace = root / "sec_companyfacts_bulk"
    sentinel = root / f"{alias_kind}-sentinel" if alias_kind == "base" else tmp_path / f"{alias_kind}-sentinel"

    if alias_kind == "base":
        alias = namespace
    elif alias_kind == "staging_downloads":
        (namespace / "staging").mkdir(parents=True)
        alias = namespace / "staging" / "downloads"
    else:
        (namespace / "objects" / "sha256").mkdir(parents=True)
        alias = namespace / "objects" / "sha256" / digest[:2]
    _directory_alias_or_skip(alias, sentinel)

    marker = sentinel / "marker.txt"
    marker.write_bytes(b"keep")
    before = _sentinel_snapshot(sentinel)

    result = _run(archive, tmp_path)

    _assert_alias_failure(result)
    assert _sentinel_snapshot(sentinel) == before




def test_cache_rejects_preexisting_part_alias_before_overwriting_target(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    namespace = tmp_path / "cache" / "sec_companyfacts_bulk"
    downloads = namespace / "staging" / "downloads"
    downloads.mkdir(parents=True)
    sentinel = tmp_path / "part-sentinel.bin"
    sentinel.write_bytes(b"keep")
    _file_alias_or_skip(downloads / "sec-companyfacts-bulk.part", sentinel)

    result = _run(archive, tmp_path)
    _assert_alias_failure(result)
    assert sentinel.read_bytes() == b"keep"


def test_cache_rejects_preexisting_content_object_alias(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    namespace = tmp_path / "cache" / "sec_companyfacts_bulk"
    prefix = namespace / "objects" / "sha256" / digest[:2]
    prefix.mkdir(parents=True)
    sentinel = tmp_path / "object-sentinel.bin"
    sentinel.write_bytes(b"keep")
    _file_alias_or_skip(prefix / digest, sentinel)

    result = _run(archive, tmp_path)
    _assert_alias_failure(result)
    assert sentinel.read_bytes() == b"keep"


def test_cache_rejects_preexisting_manifest_alias(tmp_path: Path) -> None:
    archive = _archive(tmp_path, {"CIK0000000001.json": _facts()})
    namespace = tmp_path / "cache" / "sec_companyfacts_bulk"
    manifests = namespace / "manifests"
    manifests.mkdir(parents=True)
    sentinel = tmp_path / "manifest-sentinel.json"
    sentinel.write_text(json.dumps({"content_sha256": None}), encoding="utf-8")
    _file_alias_or_skip(manifests / "sec-companyfacts-bulk.json", sentinel)

    result = _run(archive, tmp_path)
    _assert_alias_failure(result)
    assert sentinel.read_text(encoding="utf-8") == json.dumps({"content_sha256": None})


def test_cache_rejects_preexisting_invalidation_alias_before_appending_target(tmp_path: Path) -> None:
    first_archive = _archive(tmp_path, {"CIK0000000001.json": _facts(value=10)})
    first = _run(first_archive, tmp_path)
    assert first.per_cik[0].status == "imported"
    second_archive = _archive(tmp_path, {"CIK0000000001.json": _facts(value=11)})
    namespace = tmp_path / "cache" / "sec_companyfacts_bulk"
    manifests = namespace / "manifests"
    sentinel = tmp_path / "invalidation-sentinel.jsonl"
    sentinel.write_text("keep\n", encoding="utf-8")
    _file_alias_or_skip(manifests / "invalidations.jsonl", sentinel)

    result = _run(second_archive, tmp_path)
    _assert_alias_failure(result)
    assert sentinel.read_text(encoding="utf-8") == "keep\n"
    assert first.archive_sha256 != hashlib.sha256(second_archive.read_bytes()).hexdigest()


class _Member:
    def __init__(self, filename: str, file_size: int, compress_size: int) -> None:
        self.filename = filename
        self.file_size = file_size
        self.compress_size = compress_size
        self.flag_bits = 0
        self.external_attr = 0


class _Package:
    def __init__(self, *members: _Member) -> None:
        self._members = members

    def infolist(self) -> list[_Member]:
        return list(self._members)


def test_unselected_member_metadata_does_not_consume_selected_extraction_budget() -> None:
    members = _Package(
        _Member("unselected.json", 1024 * 1024 * 1024, 10 * 1024 * 1024),
        _Member("CIK0000000001.json", 128, 128),
    )

    selected = bulk_module._validated_members(members, {"CIK0000000001.json"})

    assert set(selected) == {"unselected.json", "CIK0000000001.json"}


def test_selected_member_budget_rejects_many_bounded_members_without_large_allocation() -> None:
    one_member = 180 * 1024 * 1024
    members = _Package(*(_Member(f"CIK000000000{i}.json", one_member, 1024 * 1024) for i in range(1, 4)))

    with pytest.raises(BulkCacheError, match="selected bulk members exceed"):
        bulk_module._validated_members(members, {member.filename for member in members.infolist()})
