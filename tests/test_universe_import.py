from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
import etf_cockpit.data.universe_import as universe_import

from etf_cockpit.data.universe_import import (
    build_universe_manifest,
    create_import_resume_state,
    dry_run_universe_import,
    export_universe_manifest,
    load_import_resume_state,
    load_universe_manifest,
    resume_universe_import,
    save_import_resume_state,
    save_universe_manifest,
)


def _xlsx(rows: list[list[str]]) -> bytes:
    shared = sorted({value for row in rows for value in row})
    shared_xml = "".join(f"<si><t>{value}</t></si>" for value in shared)
    shared_index = {value: index for index, value in enumerate(shared)}
    sheet_rows = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column, value in enumerate(row, start=1):
            letter = chr(64 + column)
            cells.append(f'<c r="{letter}{row_number}" t="s"><v>{shared_index[value]}</v></c>')
        sheet_rows.append(f'<row r="{row_number}">' + "".join(cells) + "</row>")
    files = {
        "xl/sharedStrings.xml": f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{shared_xml}</sst>',
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="worksheet"/></Relationships>',
        "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(sheet_rows) + "</sheetData></worksheet>",
    }
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_local_import_maps_explicit_identities_and_reports_exclusions() -> None:
    source = (
        "canonical_id,name,ticker,mic,isin,provider_symbol,asset_type,status,isin_status\n"
        "CANON,Caf\u00e9,CAN,,, ,stock,active,\n"
        ",ISIN ETF,ISIN,,IE00B4L5Y983, ,etf,active,verified\n"
        ",MIC ETF,MIC,XOSL,,,etf,active,\n"
        ",Provider ETF,,,,PROVIDER-X,etf,active,\n"
        ",Ticker only,ONLY,,,,stock,active,\n"
        ",Duplicate,,,,PROVIDER-X,etf,active,\n"
        "DEL,Delisted,DEL,,, ,stock,delisted,\n"
        "OFF,Inactive,OFF,,, ,stock,inactive,\n"
        "BAD,Unsupported,BAD,,, ,crypto,active,\n"
    ).encode("cp1252")

    report = dry_run_universe_import(source, source_kind="csv", provider_name="fixture")

    assert report.source_rows[0]["name"] == "Caf\u00e9"
    assert report.records[0].instrument_id == "CANON"
    assert report.mapping_confidence[2] == "verified_isin"
    assert report.mapping_confidence[3] == "ticker_mic"
    assert report.mapping_confidence[4] == "provider_symbol"
    assert report.unresolved_rows == (5,)
    assert report.duplicate_rows == (6,)
    assert report.delisted_rows == (7,)
    assert report.inactive_rows == (8,)
    assert report.unsupported_rows == (9,)
    assert report.execution_allowed is False


def test_xlsx_and_correction_overlay_preserve_source_rows() -> None:
    payload = _xlsx([["ticker", "name"], ["ALPHA", "Alpha"]])
    report = dry_run_universe_import(payload, source_kind="xlsx", correction_overlays={1: {"canonical_id": "A"}})

    assert report.source_rows == ({"ticker": "ALPHA", "name": "Alpha"},)
    assert report.records[0].instrument_id == "A"
    assert report.correction_overlays[1]["canonical_id"] == "A"


def test_provider_universe_accepts_only_supplied_rows_and_reports_secondary_lines() -> None:
    report = dry_run_universe_import(
        '[{"provider_symbol":"ABC","provider":"fixture","name":"ABC","asset_type":"etf","is_primary":false}]',
        source_kind="provider",
    )

    assert len(report.records) == 1
    assert report.records[0].instrument_id == "provider:fixture:ABC"
    assert report.secondary_line_rows == (1,)
    assert report.execution_allowed is False


def test_duplicate_verified_isin_across_share_class_rows_is_quarantined() -> None:
    report = dry_run_universe_import(
        [
            {"canonical_id": "ONE", "isin": "IE00B4L5Y983", "isin_status": "verified", "ticker": "ONE"},
            {"canonical_id": "TWO", "isin": "IE00B4L5Y983", "isin_status": "verified", "ticker": "TWO", "share_class": "secondary"},
        ],
        source_kind="provider",
    )

    assert report.duplicate_rows == (2,)
    assert report.secondary_line_rows == (2,)


def test_manifest_is_reproducible_exportable_and_validates_options(tmp_path: Path) -> None:
    report = dry_run_universe_import(
        "canonical_id,name,ticker,secondary_line\nA,Alpha,A,true\n,Ticker only,ONLY,\n",
        source_kind="paste",
    )
    manifest = build_universe_manifest(report, requested_horizons={"daily": 252}, per_asset_quotas={"stock": 5})
    rebuilt = build_universe_manifest(report, requested_horizons={"daily": 252}, per_asset_quotas={"stock": 5})

    assert manifest.manifest_id == rebuilt.manifest_id
    assert manifest.mapping_confidence == {1: "canonical_id", 2: "ticker_unresolved"}
    assert {issue.code for issue in manifest.issues} == {"secondary_line", "unresolved_identity"}
    assert manifest.row_classifications == {1: ("resolved", "secondary_line"), 2: ("unresolved",)}
    saved = save_universe_manifest(manifest, root=tmp_path)
    loaded = load_universe_manifest(tmp_path)
    assert loaded.manifest_id == manifest.manifest_id
    assert loaded.source_rows == report.source_rows
    assert loaded.mapping_confidence == manifest.mapping_confidence
    assert loaded.issues == manifest.issues
    assert loaded.row_classifications == manifest.row_classifications
    assert export_universe_manifest(manifest, tmp_path / "manifest.json") == tmp_path / "manifest.json"
    assert saved.snapshot_path.exists()
    with pytest.raises(ValueError, match="positive"):
        build_universe_manifest(report, requested_horizons={"daily": 0})
    with pytest.raises(ValueError, match="positive"):
        build_universe_manifest(report, requested_horizons={"daily": True})
    with pytest.raises(ValueError, match="non-negative"):
        build_universe_manifest(report, per_asset_quotas={"stock": True})


def test_manifest_readback_fails_closed_on_safety_and_resolution_inconsistency(tmp_path: Path) -> None:
    report = dry_run_universe_import("canonical_id,name,ticker\nA,Alpha,A\n", source_kind="paste")
    manifest = build_universe_manifest(report)
    saved = save_universe_manifest(manifest, root=tmp_path)
    payload = json.loads(saved.path.read_text(encoding="utf-8"))

    payload["execution_allowed"] = 0
    saved.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly false"):
        load_universe_manifest(tmp_path)

    payload["execution_allowed"] = False
    payload["mapping_confidence"] = {}
    saved.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="cover every source row"):
        load_universe_manifest(tmp_path)


def test_manifest_group_failure_preserves_current_and_immutable_snapshot(tmp_path: Path, monkeypatch) -> None:
    first_report = dry_run_universe_import("canonical_id,name,ticker\nA,Alpha,A\n", source_kind="paste")
    first = build_universe_manifest(first_report)
    first_saved = save_universe_manifest(first, root=tmp_path)
    current_before = first_saved.path.read_bytes()
    snapshot_before = first_saved.snapshot_path.read_bytes()
    second = build_universe_manifest(first_report, requested_horizons={"daily": 252})
    second_snapshot = tmp_path / "data" / "snapshots" / "universe_manifests" / f"{second.manifest_id}.json"
    validate = universe_import._validate_manifest_file

    def fail_snapshot(path: Path) -> None:
        validate(path)
        if path.parent.name == "universe_manifests":
            raise ValueError("snapshot validation failed")

    monkeypatch.setattr(universe_import, "_validate_manifest_file", fail_snapshot)
    with pytest.raises(ValueError, match="snapshot validation failed"):
        save_universe_manifest(second, root=tmp_path)

    assert first_saved.path.read_bytes() == current_before
    assert first_saved.snapshot_path.read_bytes() == snapshot_before
    assert not second_snapshot.exists()


def test_large_import_resume_is_deterministic_and_cancel_safe() -> None:
    source = "canonical_id,name,ticker\n" + "".join(f"A{i},Alpha {i},A{i}\n" for i in range(5))
    report = dry_run_universe_import(source, source_kind="paste")
    state = create_import_resume_state(report, chunk_size=2)
    first, state = resume_universe_import(report, state)
    cancelled, cancelled_state = resume_universe_import(report, state, cancel=True)
    with pytest.raises(ValueError, match="cancelled import"):
        resume_universe_import(report, cancelled_state)
    second, state = resume_universe_import(report, state, max_rows=10)

    assert [record.instrument_id for record in first] == ["A0", "A1"]
    assert cancelled == ()
    assert [record.instrument_id for record in second] == ["A2", "A3", "A4"]
    assert state.complete


def test_resume_readback_rejects_malformed_types_status_and_safety(tmp_path: Path) -> None:
    report = dry_run_universe_import("canonical_id,name,ticker\nA,Alpha,A\n", source_kind="paste")
    state = create_import_resume_state(report, chunk_size=1)
    path = save_import_resume_state(state, tmp_path / "resume.json")
    assert load_import_resume_state(path) == state
    payload = json.loads(path.read_text(encoding="utf-8"))

    for field, value, message in (
        ("total_rows", True, "counts"),
        ("status", "unknown", "status"),
        ("execution_allowed", 0, "exactly false"),
    ):
        changed = dict(payload)
        changed[field] = value
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_import_resume_state(path)


def test_import_requires_explicit_verified_isin_and_keeps_identity_unresolved() -> None:
    report = dry_run_universe_import(
        [
            {"canonical_id": "CANONICAL_ONLY", "name": "Canonical", "isin": "IE00B4L5Y983"},
            {"isin": "IE00B4L5Y983", "isin_status": "verified", "name": "ISIN only"},
        ],
        source_kind="provider",
    )

    assert report.unresolved_rows == (1, 2)
    assert report.records == ()
    assert report.mapping_confidence == {1: "canonical_id", 2: "verified_isin"}


def test_boolean_headers_and_polarity_are_normalized_before_support_checks() -> None:
    report = dry_run_universe_import(
        [
            {"canonical_id": "INACTIVE", "ticker": "INA", "Active": "false"},
            {"canonical_id": "DELISTED", "ticker": "DEL", "Delisted": "true"},
            {"canonical_id": "PRIMARY", "ticker": "PRI", "secondary_line": "false"},
            {"canonical_id": "LEVERAGED", "ticker": "LEV", "Leveraged": "true", "Inverse": "false"},
            {"canonical_id": "CRYPTO", "ticker": "CRY", "Asset Class": "crypto"},
        ],
        source_kind="provider",
    )

    assert report.inactive_rows == (1,)
    assert report.delisted_rows == (2,)
    assert report.secondary_line_rows == ()
    assert report.unsupported_rows == (5,)
    assert report.records[0].instrument_id == "PRIMARY"
    assert report.records[1].leveraged is True


def test_duplicate_headers_and_provider_json_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate CSV header"):
        dry_run_universe_import("ticker,TICKER\nA,A\n", source_kind="csv")
    with pytest.raises(ValueError, match="duplicate provider JSON key"):
        dry_run_universe_import('[{"ticker":"A","ticker":"B"}]', source_kind="provider")


def test_xlsx_member_size_and_sheet_dimension_limits_are_checked() -> None:
    oversized = BytesIO()
    with ZipFile(oversized, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "x" * (universe_import._XLSX_MAX_MEMBER_BYTES + 1))
    with pytest.raises(ValueError, match="ZIP member"):
        dry_run_universe_import(oversized.getvalue(), source_kind="xlsx")

    limited = _xlsx([["canonical_id", "ticker"], ["A", "A"]])
    rebuilt = BytesIO()
    with ZipFile(BytesIO(limited), "r") as source_zip, ZipFile(rebuilt, "w", ZIP_DEFLATED) as target_zip:
        for info in source_zip.infolist():
            value = source_zip.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                value = value.replace(b"<sheetData>", b'<dimension ref="A1:A100001"/><sheetData>')
            target_zip.writestr(info.filename, value)
    with pytest.raises(ValueError, match="row or column limits"):
        dry_run_universe_import(rebuilt.getvalue(), source_kind="xlsx")


def test_resume_binds_digest_to_overlays_records_and_rejects_completed_cancel() -> None:
    report = dry_run_universe_import(
        "ticker,name\nA,Alpha\n", source_kind="paste", correction_overlays={1: {"canonical_id": "A"}}
    )
    state = create_import_resume_state(report, chunk_size=1)
    changed = dry_run_universe_import(
        "ticker,name\nA,Alpha\n", source_kind="paste", correction_overlays={1: {"canonical_id": "B"}}
    )
    with pytest.raises(ValueError, match="does not match"):
        resume_universe_import(changed, state)
    _, complete = resume_universe_import(report, state)
    with pytest.raises(ValueError, match="cannot be cancelled"):
        resume_universe_import(report, complete, cancel=True)


def test_out_of_range_correction_overlays_are_rejected() -> None:
    with pytest.raises(ValueError, match="outside the source rows"):
        dry_run_universe_import(
            "canonical_id,ticker\nA,A\n", source_kind="paste", correction_overlays={2: {"name": "wrong row"}}
        )
