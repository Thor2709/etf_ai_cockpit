from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from scripts.import_official_filing import _resolve_published_at, import_official_filing


FIXTURE = Path(__file__).parent / "fixtures" / "official" / "esef_report_package" / "synthetic-ming-2025.xbri"
MING_LEI = "7V6Z97IO7R1SEAO84Q32"
MING_URL = "https://filings.xbrl.org/7V6Z97IO7R1SEAO84Q32/2025-12-31/ESEF/NO/0/synthetic-ming-2025.xbri"


def test_publication_date_uses_adjacent_api_metadata_not_import_time(tmp_path: Path) -> None:
    source = tmp_path / "synthetic-ming-2025.xbri"
    shutil.copyfile(FIXTURE, source)
    (tmp_path / "filing-api-record.json").write_text(
        json.dumps({"data": {"type": "filing", "attributes": {"date_added": "2025-02-27", "package_url": MING_URL}}}),
        encoding="utf-8",
    )

    result = import_official_filing(
        source,
        jurisdiction="NO",
        instrument_id="MING",
        source_url=MING_URL,
        expected_period="2025-12-31",
        lei=MING_LEI,
        published_at="2026-03-05T00:00:00Z",
        output_dir=tmp_path / "evidence",
    )

    identity = json.loads((tmp_path / "evidence" / "identity.json").read_text(encoding="utf-8"))
    assert result["known_at"] == "2025-02-27"
    assert identity["known_at"] == "2025-02-27"


def test_publication_date_requires_explicit_value_without_api_metadata(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="publication date is required"):
        _resolve_published_at(tmp_path / "package.xbri", MING_URL, None)
    assert _resolve_published_at(tmp_path / "package.xbri", MING_URL, "2025-02-27") == "2025-02-27"
