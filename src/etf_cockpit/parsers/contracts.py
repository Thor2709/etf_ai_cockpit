from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Generic, TypeVar
from urllib.parse import urlparse


T = TypeVar("T")
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "official" / "manifest.json"
OFFICIAL_SOURCE_DOMAINS = {
    "sec_companyfacts": {"data.sec.gov"},
    "sec_submissions": {"data.sec.gov"},
    "esef_api_response": {"filings.xbrl.org"},
    "esef_report_package": {"filings.xbrl.org"},
    "priips_kid": {"fund-docs.vanguard.com"},
    "index_methodology": {"www.lseg.com", "lseg.com"},
}


@dataclass(frozen=True)
class OfficialFixture:
    fixture_id: str
    source_url: str
    retrieved_at: datetime
    sha256: str
    document_type: str
    authority: str
    entity: str
    period: str
    licence_note: str
    relative_path: str
    path: Path


@dataclass(frozen=True)
class RawDocument:
    path: Path
    source_url: str
    retrieved_at: datetime
    sha256: str
    provider_id: str
    document_type: str
    media_type: str
    http_status: int


@dataclass(frozen=True)
class ParseWarning:
    code: str
    message: str
    severity: str
    source_location: str | None = None


@dataclass(frozen=True)
class ParseResult(Generic[T]):
    records: tuple[T, ...]
    warnings: tuple[ParseWarning, ...]
    parser_name: str
    parser_version: str
    source_sha256: str
    success: bool


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("fixture relative_path must be a non-empty string")
    normalised = value.replace("\\", "/")
    parsed = PurePosixPath(normalised)
    if parsed.is_absolute() or ".." in parsed.parts or re.match(r"^[A-Za-z]:/", normalised):
        raise ValueError(f"fixture path must be relative to the manifest: {value}")
    return parsed.as_posix()


def _provenance_text(value: object, field: str, fixture_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"fixture provenance field {field} must be non-empty: {fixture_id}")
    return value.strip()


def load_fixture_manifest(path: Path = DEFAULT_FIXTURE_MANIFEST) -> tuple[OfficialFixture, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("fixtures"), list):
        raise ValueError("fixture manifest must use schema_version 1 and contain fixtures")

    fixtures: list[OfficialFixture] = []
    seen_ids: set[str] = set()
    for item in payload["fixtures"]:
        fixture_id = str(item.get("fixture_id", "")).strip()
        if not fixture_id or fixture_id in seen_ids:
            raise ValueError(f"fixture_id must be non-empty and unique: {fixture_id!r}")
        seen_ids.add(fixture_id)
        relative_path = _safe_relative_path(item.get("relative_path"))
        fixture_path = path.parent / relative_path
        fixture_root = path.parent.resolve(strict=True)
        if fixture_path.is_symlink():
            raise ValueError(f"fixture path must remain within the fixture root: {relative_path}")
        try:
            resolved_fixture_path = fixture_path.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"fixture file is missing: {relative_path}") from exc
        if not resolved_fixture_path.is_relative_to(fixture_root):
            raise ValueError(f"fixture path must remain within the fixture root: {relative_path}")
        if not resolved_fixture_path.is_file():
            raise ValueError(f"fixture file is missing: {relative_path}")
        expected_sha256 = str(item.get("sha256", "")).lower()
        actual_sha256 = _sha256_file(fixture_path)
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or actual_sha256 != expected_sha256:
            raise ValueError(f"fixture checksum mismatch: {fixture_id}")
        retrieved_at = datetime.fromisoformat(str(item["retrieved_at"]).replace("Z", "+00:00"))
        if retrieved_at.tzinfo is None:
            raise ValueError(f"fixture retrieved_at must include a timezone: {fixture_id}")
        source_url = str(item.get("source_url", "")).strip()
        authority = _provenance_text(item.get("authority"), "authority", fixture_id)
        entity = _provenance_text(item.get("entity"), "entity", fixture_id)
        period = _provenance_text(item.get("period"), "period", fixture_id)
        licence_note = _provenance_text(item.get("licence_note"), "licence_note", fixture_id)
        if not source_url.startswith("https://"):
            raise ValueError(f"fixture source_url must use HTTPS: {fixture_id}")
        expected_domains = OFFICIAL_SOURCE_DOMAINS.get(str(item.get("document_type")))
        hostname = (urlparse(source_url).hostname or "").lower()
        if expected_domains and hostname not in expected_domains:
            raise ValueError(f"fixture source authority domain is invalid: {fixture_id}")
        fixtures.append(
            OfficialFixture(
                fixture_id=fixture_id,
                source_url=source_url,
                retrieved_at=retrieved_at,
                sha256=expected_sha256,
                document_type=str(item["document_type"]),
                authority=authority,
                entity=entity,
                period=period,
                licence_note=licence_note,
                relative_path=relative_path,
                path=fixture_path,
            )
        )
    result = tuple(fixtures)
    _validate_esef_selection(result)
    return result


def _validate_esef_selection(fixtures: tuple[OfficialFixture, ...]) -> None:
    packages = [item for item in fixtures if item.document_type == "esef_report_package"]
    if not packages:
        return
    api_fixtures = [item for item in fixtures if item.document_type == "esef_api_response"]
    if len(api_fixtures) != 1:
        raise ValueError("ESEF package requires exactly one retained API selection response")
    try:
        api_items = json.loads(api_fixtures[0].path.read_text(encoding="utf-8"))["data"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("ESEF API selection response is invalid") from exc
    for package in packages:
        matches = []
        for item in api_items:
            attributes = item.get("attributes", {})
            package_url = "https://filings.xbrl.org" + str(attributes.get("package_url", ""))
            if (
                package_url == package.source_url
                and attributes.get("sha256") == package.sha256
                and attributes.get("fxo_id") == package.entity
                and "-ESEF-" in str(attributes.get("fxo_id", ""))
            ):
                matches.append(item)
        if len(matches) != 1:
            raise ValueError(f"ESEF package was not uniquely selected by the retained API response: {package.fixture_id}")
