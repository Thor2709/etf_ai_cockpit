from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from etf_cockpit.parsers.contracts import load_fixture_manifest


REQUIRED_DOCUMENT_TYPES = {
    "sec_companyfacts",
    "sec_submissions",
    "esef_api_response",
    "esef_report_package",
    "priips_kid",
    "index_methodology",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_official_fixture_manifest_files_match_recorded_sha256():
    fixtures = load_fixture_manifest()

    assert {item.document_type for item in fixtures} >= REQUIRED_DOCUMENT_TYPES
    assert len({item.fixture_id for item in fixtures}) == len(fixtures)
    for item in fixtures:
        assert item.path.is_file()
        assert sha256_file(item.path) == item.sha256
        assert item.source_url.startswith("https://")
        assert item.authority
        assert item.retrieved_at.tzinfo is not None
        assert item.licence_note


def test_esef_package_is_selected_from_retained_api_response():
    fixtures = load_fixture_manifest()
    by_type = {item.document_type: item for item in fixtures}
    api_fixture = by_type["esef_api_response"]
    package_fixture = by_type["esef_report_package"]
    response = json.loads(api_fixture.path.read_text(encoding="utf-8"))
    selected = [
        item
        for item in response["data"]
        if "https://filings.xbrl.org" + item["attributes"]["package_url"]
        == package_fixture.source_url
    ]

    assert len(selected) == 1
    assert selected[0]["attributes"]["fxo_id"] == package_fixture.entity
    assert selected[0]["attributes"]["sha256"] == package_fixture.sha256
    assert "-ESEF-" in selected[0]["attributes"]["fxo_id"]


def test_fixture_manifest_rejects_checksum_mismatch(tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        """{
  "schema_version": 1,
  "fixtures": [{
    "fixture_id": "bad-checksum",
    "source_url": "https://example.test/fixture.json",
    "retrieved_at": "2026-07-10T00:00:00Z",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "document_type": "test",
    "authority": "test authority",
    "entity": "test entity",
    "period": "current",
    "licence_note": "test fixture only",
    "relative_path": "fixture.json"
  }]
}""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="checksum"):
        load_fixture_manifest(manifest)


def test_fixture_manifest_rejects_esef_package_not_selected_by_api(tmp_path):
    api_path = tmp_path / "api.json"
    api_payload = {
        "data": [
            {
                "attributes": {
                    "fxo_id": "ENTITY-2025-12-31-ESEF-NL-0",
                    "package_url": "/entity/2025/ESEF/NL/selected.zip",
                    "sha256": hashlib.sha256(b"package").hexdigest(),
                }
            }
        ]
    }
    api_path.write_text(json.dumps(api_payload), encoding="utf-8")
    package_path = tmp_path / "package.zip"
    package_path.write_bytes(b"package")
    common = {
        "retrieved_at": "2026-07-10T00:00:00Z",
        "authority": "official",
        "period": "2025",
        "licence_note": "public test evidence",
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fixtures": [
                    {
                        **common,
                        "fixture_id": "api",
                        "source_url": "https://filings.xbrl.org/api/filings",
                        "sha256": sha256_file(api_path),
                        "document_type": "esef_api_response",
                        "entity": "NL filings",
                        "relative_path": "api.json",
                    },
                    {
                        **common,
                        "fixture_id": "package",
                        "source_url": "https://filings.xbrl.org/not-selected.zip",
                        "sha256": sha256_file(package_path),
                        "document_type": "esef_report_package",
                        "entity": "ENTITY-2025-12-31-ESEF-NL-0",
                        "relative_path": "package.zip",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="selected"):
        load_fixture_manifest(manifest)


def test_fixture_manifest_rejects_null_provenance(tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fixtures": [
                    {
                        "fixture_id": "null-authority",
                        "source_url": "https://example.test/fixture.json",
                        "retrieved_at": "2026-07-10T00:00:00Z",
                        "sha256": sha256_file(fixture),
                        "document_type": "test",
                        "authority": None,
                        "entity": "entity",
                        "period": "period",
                        "licence_note": "public test evidence",
                        "relative_path": "fixture.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="provenance"):
        load_fixture_manifest(manifest)


def test_fixture_manifest_rejects_symlink_escape(tmp_path, monkeypatch):
    outside = tmp_path.parent / f"{tmp_path.name}-fixture.json"
    outside.write_text("{}", encoding="utf-8")
    link = tmp_path / "linked.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pass
    if not link.exists():
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda value: value == link or original_is_symlink(value))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fixtures": [
                    {
                        "fixture_id": "linked",
                        "source_url": "https://example.test/fixture.json",
                        "retrieved_at": "2026-07-10T00:00:00Z",
                        "sha256": sha256_file(outside),
                        "document_type": "test",
                        "authority": "authority",
                        "entity": "entity",
                        "period": "period",
                        "licence_note": "public test evidence",
                        "relative_path": "linked.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="fixture root"):
        load_fixture_manifest(manifest)


def test_known_official_document_type_requires_matching_source_authority(tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fixtures": [
                    {
                        "fixture_id": "fake-sec",
                        "source_url": "https://example.test/companyfacts.json",
                        "retrieved_at": "2026-07-10T00:00:00Z",
                        "sha256": sha256_file(fixture),
                        "document_type": "sec_companyfacts",
                        "authority": "U.S. Securities and Exchange Commission",
                        "entity": "entity",
                        "period": "period",
                        "licence_note": "public test evidence",
                        "relative_path": "fixture.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="authority domain"):
        load_fixture_manifest(manifest)
