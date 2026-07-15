from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

import etf_cockpit.parsers.esef_ixbrl as esef_ixbrl
from etf_cockpit.parsers.esef_ixbrl import map_ifrs_fact, parse_esef_package


FIXTURE = Path("tests/fixtures/official/esef_report_package/7245003GZ2696Y0W1X57-2026-03-31.xbri")


def test_real_esef_package_extracts_facts_and_retains_extensions() -> None:
    result = parse_esef_package(FIXTURE)
    assert result.success is True
    assert result.records
    assert any(record.entity_lei == "7245003GZ2696Y0W1X57" for record in result.records)
    assert any(record.mapping_status == "unmapped_extension" for record in result.records)
    assert {record.period_end for record in result.records} >= {"2024-03-31", "2025-03-31", "2026-03-31"}


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


def test_parser_extracts_context_period_unit_and_decimals_and_deduplicates(tmp_path: Path) -> None:
    package = tmp_path / "minimal.xbri"
    xhtml = """<?xml version='1.0'?>
    <html xmlns='http://www.w3.org/1999/xhtml' xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'
      xmlns:xbrli='http://www.xbrl.org/2003/instance' xmlns:ifrs-full='https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full'
      xmlns:ext='https://example.test/ext'>
      <body><xbrli:context id='c1'><xbrli:entity><xbrli:identifier scheme='http://standards.iso.org/iso/17442'>549300TESTLEI00000001</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
      <ix:nonFraction name='ifrs-full:Revenue' contextRef='c1' unitRef='EUR' decimals='-3'>1,000</ix:nonFraction>
      <ix:nonFraction name='ifrs-full:Revenue' contextRef='c1' unitRef='EUR' decimals='-3'>1,000</ix:nonFraction>
      <ix:nonNumeric name='ext:CustomNarrative' contextRef='c1'>Narrative</ix:nonNumeric></body></html>"""
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("META-INF/reportPackage.json", '{"documentInfo":{"documentType":"https://xbrl.org/report-package/2023/xbri"}}')
        archive.writestr("reports/report.xhtml", xhtml)
    result = parse_esef_package(package)
    assert result.success is True
    assert len(result.records) == 2
    revenue = next(record for record in result.records if record.concept == "Revenue")
    assert revenue.entity_lei == "549300TESTLEI00000001"
    assert revenue.period_start == "2025-01-01"
    assert revenue.period_end == "2025-12-31"
    assert revenue.unit == "EUR"
    assert revenue.decimals == "-3"
    assert any(warning.code == "duplicate_fact" for warning in result.warnings)
    extension = next(record for record in result.records if record.concept == "CustomNarrative")
    assert extension.mapping_status == "unmapped_extension"
    assert extension.namespace == "https://example.test/ext"
    assert any(warning.code == "unmapped_extension" for warning in result.warnings)


def _write_context_package(path: Path) -> None:
    xhtml = """<?xml version='1.0'?>
    <html xmlns='http://www.w3.org/1999/xhtml' xmlns:ix='http://www.xbrl.org/2013/inlineXBRL'
      xmlns:xbrli='http://www.xbrl.org/2003/instance' xmlns:ifrs-full='https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full'>
      <body>
        <xbrli:context id='current'><xbrli:entity><xbrli:identifier>549300TESTLEI00000001</xbrli:identifier></xbrli:entity>
          <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period>
        </xbrli:context>
        <xbrli:context id='comparative'><xbrli:entity><xbrli:identifier>549300TESTLEI00000001</xbrli:identifier></xbrli:entity>
          <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
        </xbrli:context>
        <ix:nonFraction name='ifrs-full:Revenue' contextRef='current' unitRef='EUR' decimals='0'>100</ix:nonFraction>
        <ix:nonFraction name='ifrs-full:Revenue' contextRef='comparative' unitRef='EUR' decimals='0'>90</ix:nonFraction>
      </body>
    </html>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "META-INF/reportPackage.json",
            '{"documentInfo":{"periodEnd":"2026-03-31"}}',
        )
        archive.writestr("reports/report.xhtml", xhtml)


def test_context_period_ends_are_preserved_over_package_period_hint(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "periods.xbri"
    _write_context_package(package)
    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: False)

    result = parse_esef_package(package)

    assert result.success is True
    periods = {(record.context_id, record.period_start, record.period_end) for record in result.records}
    assert ("current", "2025-01-01", "2025-12-31") in periods
    assert ("comparative", "2024-01-01", "2024-12-31") in periods


def test_arelle_validation_failure_is_serialised_and_blocks_import(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "invalid.xbri"
    _write_context_package(package)
    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: True)
    monkeypatch.setattr(
        esef_ixbrl,
        "_run_arelle_validation",
        lambda _path, _timeout_seconds: ({"code": "xbrl.error", "severity": "error", "message": "broken rule"},),
    )

    result = parse_esef_package(package)

    assert result.success is False
    warning = next(warning for warning in result.warnings if warning.code == "arelle_validation")
    assert warning.severity == "error"
    assert "broken rule" in warning.message


def test_nonfatal_arelle_package_diagnostics_do_not_block_offline_facts(monkeypatch) -> None:
    """Optional validator diagnostics must not discard facts that parsed offline."""

    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: True)
    monkeypatch.setattr(
        esef_ixbrl,
        "_run_arelle_validation",
        lambda _path, _timeout_seconds: (
            {"code": "IOerror", "severity": "error", "message": "package archive is not a standalone instance"},
            {"code": "ix11.12.1.2:missingReferences", "severity": "error", "message": "missing reference emitted after offline taxonomy retrieval"},
            {"code": "exception:AttributeError", "severity": "error", "message": "formulaOptions is unavailable in this Arelle release"},
        ),
    )

    result = parse_esef_package(FIXTURE)

    assert result.success is True
    assert result.records
    assert {warning.severity for warning in result.warnings if warning.code in {"IOerror", "ix11.12.1.2:missingReferences", "exception:AttributeError"}} == {"warning"}


def test_missing_reference_conformance_error_remains_blocking(monkeypatch) -> None:
    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: True)
    monkeypatch.setattr(
        esef_ixbrl,
        "_run_arelle_validation",
        lambda _path, _timeout_seconds: (
            {"code": "ix11.12.1.2:missingReferences", "severity": "error", "message": "required reference is missing from the submitted report"},
        ),
    )

    result = parse_esef_package(FIXTURE)

    assert result.success is False
    assert any(warning.severity == "error" and warning.code == "arelle_validation" for warning in result.warnings)


def test_correlated_loader_error_does_not_downgrade_explicit_conformance_failure(monkeypatch) -> None:
    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: True)
    monkeypatch.setattr(
        esef_ixbrl,
        "_run_arelle_validation",
        lambda _path, _timeout_seconds: (
            {"code": "webCache:retrievalError", "severity": "error", "message": "remote taxonomy unavailable offline"},
            {"code": "ix11.12.1.2:missingReferences", "severity": "error", "message": "required reference is missing from the submitted report"},
        ),
    )

    result = parse_esef_package(FIXTURE)

    assert result.success is False
    assert any(warning.severity == "error" and warning.code == "arelle_validation" for warning in result.warnings)


def test_arelle_validation_timeout_is_controlled_and_does_not_grant_authority(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "timeout.xbri"
    _write_context_package(package)
    monkeypatch.setattr(esef_ixbrl, "_arelle_available", lambda: True)

    def timeout(_path, _timeout_seconds):
        raise TimeoutError("validator deadline exceeded")

    monkeypatch.setattr(esef_ixbrl, "_run_arelle_validation", timeout)

    result = parse_esef_package(package)

    assert result.success is False
    warning = next(warning for warning in result.warnings if warning.code == "arelle_timeout")
    assert warning.severity == "error"
    assert "deadline" in warning.message


@pytest.mark.parametrize("entry_name", ["..\\escape.xhtml", "/absolute.xhtml", "C:\\escape.xhtml"])
def test_parser_rejects_backslash_and_absolute_zip_members(tmp_path: Path, entry_name: str) -> None:
    package = tmp_path / "unsafe.xbri"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(entry_name, "<html />")
    result = parse_esef_package(package)
    assert result.success is False
    assert any(warning.code == "unsafe_archive" for warning in result.warnings)


def test_parser_rejects_unsupported_zip_member_types(tmp_path: Path) -> None:
    package = tmp_path / "unsupported.xbri"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("reportPackage.json", "{}")
        archive.writestr("report.xhtml", "<html />")
        archive.writestr("payload.exe", b"not executable")
    result = parse_esef_package(package)
    assert result.success is False
    assert any(warning.code == "unsupported_member" for warning in result.warnings)


def test_parser_captures_bounded_arelle_validation_failure(monkeypatch) -> None:
    import etf_cockpit.parsers.esef_ixbrl as module

    monkeypatch.setattr(module.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        module,
        "_run_arelle_validation",
        lambda _path, _timeout_seconds: ({"code": "arelle_validation_failed", "severity": "warning", "message": "validation failed"},),
    )

    result = module.parse_esef_package(FIXTURE)

    assert any(warning.code == "arelle_validation_failed" for warning in result.warnings)


def test_arelle_worker_uses_pinned_validate_api_and_serialises_log_errors(monkeypatch) -> None:
    import logging
    import queue as queue_module
    import sys
    import types

    logger = logging.getLogger("test.arelle.worker")
    logger.handlers.clear()
    logger.propagate = False

    class FakeManager:
        def load(self, _path):
            return types.SimpleNamespace(errors=())

        def validate(self):
            logger.error("broken rule", extra={"messageCode": "xbrl.error"})

    class FakeController:
        def __init__(self, **_kwargs):
            self.logger = logger
            self.modelManager = FakeManager()

    fake_arelle = types.ModuleType("arelle")
    fake_arelle.Cntlr = types.SimpleNamespace(Cntlr=FakeController)
    monkeypatch.setitem(sys.modules, "arelle", fake_arelle)
    output = queue_module.SimpleQueue()

    esef_ixbrl._arelle_worker("report.xbri", output)

    result = output.get()
    assert result["status"] == "validation_error"
    assert result["messages"][0]["code"] == "xbrl.error"
    assert result["messages"][0]["severity"] == "error"


def test_state_import_persists_esef_facts_and_official_inventory(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module
    import pandas as pd

    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "statement_facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "filings_statements.parquet")
    monkeypatch.setattr(state_module, "RAW_DIR", tmp_path / "raw")
    state = state_module.AppState.__new__(state_module.AppState)
    state.last_message = "Ready"

    message = state.import_esef_package(FIXTURE, instrument_id="NL_ENTITY")
    assert "complete" in message
    facts = pd.read_parquet(tmp_path / "statement_facts.parquet")
    inventory = pd.read_parquet(tmp_path / "filings_statements.parquet")
    assert facts["schema_version"].eq("statement_facts.v1").all()
    assert facts["source_id"].astype(str).str.startswith("filings_xbrl_org:").all()
    assert inventory["source_authority"].iat[0] == "official_filing"
    assert bool(inventory["executable_authority"].iat[0]) is False
    assert (tmp_path / "raw" / "filings" / "eu_esef").joinpath(f"{parse_esef_package(FIXTURE).source_sha256}.xbri").is_file()


def test_arbitrary_local_import_is_retained_but_requires_manual_review(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module
    import pandas as pd

    local_package = tmp_path / "local-copy.xbri"
    local_package.write_bytes(FIXTURE.read_bytes())
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "statement_facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "filings_statements.parquet")
    monkeypatch.setattr(state_module, "RAW_DIR", tmp_path / "raw")
    state = state_module.AppState.__new__(state_module.AppState)
    state.last_message = "Ready"

    message = state.import_esef_package(local_package, instrument_id="LOCAL_ENTITY")

    assert "source_authority=manual_review" in message
    facts = pd.read_parquet(tmp_path / "statement_facts.parquet")
    inventory = pd.read_parquet(tmp_path / "filings_statements.parquet")
    assert facts["source_id"].astype(str).str.startswith("esef_local_import:").all()
    assert inventory["source_authority"].iat[0] == "manual_review"


def test_invalid_local_import_is_retained_without_clean_store_mutation(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    invalid = tmp_path / "invalid.xbri"
    invalid.write_bytes(b"not-a-zip")
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "statement_facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "filings_statements.parquet")
    monkeypatch.setattr(state_module, "RAW_DIR", tmp_path / "raw")
    state = state_module.AppState.__new__(state_module.AppState)
    state.last_message = "Ready"

    message = state.import_esef_package(invalid)

    digest = hashlib.sha256(invalid.read_bytes()).hexdigest()
    assert "Raw filing retained" in message
    assert (tmp_path / "raw" / "filings" / "eu_esef" / f"{digest}.xbri").is_file()
    assert not (tmp_path / "statement_facts.parquet").exists()
    assert not (tmp_path / "filings_statements.parquet").exists()


def test_state_discovery_and_download_keep_unavailable_state_explicit(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module
    from etf_cockpit.data.providers import ProviderResult
    from etf_cockpit.parsers.contracts import RawDocument
    from datetime import datetime, timezone
    import pandas as pd

    package = tmp_path / "package.xbri"
    package.write_bytes(b"package")

    class FakeProvider:
        def __init__(self, **_kwargs):
            pass

        def list_filings(self, _country, _limit):
            return ProviderResult("filings_xbrl_org", "filings", "ok", "fixture", pd.DataFrame([{"fxo_id": "fixture-1"}]))

        def download_report_package(self, _filing_id, _package_url=None):
            return RawDocument(package, "https://filings.xbrl.org/fixture.xbri", datetime.now(timezone.utc), "a" * 64, "filings_xbrl_org", "esef_report_package", "application/octet-stream", 200)

    monkeypatch.setattr(state_module, "FilingsXbrlOrgProvider", FakeProvider)
    state = state_module.AppState.__new__(state_module.AppState)
    assert "complete" in state.discover_esef_filings("NL")
    assert "downloaded" in state.download_esef_package("fixture-1")
