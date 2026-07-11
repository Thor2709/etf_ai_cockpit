from __future__ import annotations

import zipfile
from pathlib import Path

from etf_cockpit.parsers.esef_ixbrl import map_ifrs_fact, parse_esef_package


FIXTURE = Path("tests/fixtures/official/esef_report_package/7245003GZ2696Y0W1X57-2026-03-31.xbri")


def test_real_esef_package_extracts_facts_and_retains_extensions() -> None:
    result = parse_esef_package(FIXTURE)
    assert result.success is True
    assert result.records
    assert any(record.entity_lei == "7245003GZ2696Y0W1X57" for record in result.records)
    assert all(record.period_end == "2026-03-31" for record in result.records)
    assert any(record.mapping_status == "unmapped_extension" for record in result.records)


def test_zip_traversal_and_malformed_archives_fail_closed(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.xbri"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.xhtml", "<html />")
    result = parse_esef_package(traversal)
    assert result.success is False
    assert any(warning.code == "unsafe_archive" for warning in result.warnings)
    malformed = tmp_path / "bad.xbri"
    malformed.write_bytes(b"not zip")
    assert parse_esef_package(malformed).success is False


def test_ifrs_mapping_is_explicit() -> None:
    assert map_ifrs_fact("Revenue") == "revenue"
    assert map_ifrs_fact("hollandcolours:CustomMetric") is None
