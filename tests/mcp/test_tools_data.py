from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from etf_cockpit.application import mcp_data_views, mcp_etf_views
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.errors import ConfirmationError
from etf_cockpit.mcp.registry import CallContext, RateLimiter, invoke_tool
from etf_cockpit.mcp import tools_data, tools_etf, tools_universe
from etf_cockpit.data.universe_store import UniverseRecord


def _context(rate_path: Path | None = None) -> CallContext:
    return CallContext(
        enabled_tiers=frozenset({"read", "edit", "read_job"}),
        profile="full",
        audit=AuditRecorder(sink=lambda _record: None),
        rate_limiter=RateLimiter(path=rate_path or Path.cwd() / ".tmp_pytest" / "mcp-rate-limits.sqlite3"),
    )


def test_data_health_is_paged_and_keeps_unavailable_values(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"dataset": f"dataset-{index}", "status": "unavailable", "row_count": None} for index in range(12)]
    monkeypatch.setattr(mcp_data_views, "data_health_view", lambda **_kwargs: {"as_of": "2026-11-02", "rows": rows})

    first = invoke_tool("data_health", {"limit": 4}, context=_context())
    second = invoke_tool("data_health", {"limit": 4, "cursor": first["next_cursor"]}, context=_context())

    assert len(first["rows"]) == 4
    assert len(second["rows"]) == 4
    assert first["rows"][0]["row_count"] is None
    assert first["rows"][0]["status"] == "unavailable"
    assert first["next_cursor"]


def test_canonical_data_services_are_called_and_unavailability_is_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Service:
        def __init__(self, _config: object) -> None:
            pass

        def validate_prices(self):
            calls.append("validate_prices")
            return SimpleNamespace(status="Unavailable", analysis_allowed=False, as_of_date=None, issues=(), dataset_metadata=())

    monkeypatch.setattr(mcp_data_views, "DataService", Service)
    data = invoke_tool("data_validate_prices", {}, context=_context())
    assert calls == ["validate_prices"]
    assert data["status"] == "Unavailable"
    assert data["analysis_allowed"] is False
    assert data["as_of_date"] is None

    look_through_calls: list[tuple[str, datetime]] = []
    monkeypatch.setattr(
        mcp_etf_views,
        "load_etf_look_through",
        lambda instrument_id, **kwargs: look_through_calls.append((instrument_id, kwargs["decision_time"])) or {"status": "unavailable", "coverage": None},
    )
    instant = datetime(2026, 11, 2, tzinfo=timezone.utc)
    result = mcp_etf_views.etf_look_through_view("FUND", instant)
    assert look_through_calls == [("FUND", instant)]
    assert result["coverage"] is None


def test_every_edit_tool_requires_a_valid_token_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.csv"
    source.write_text("source", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    writes: list[str] = []

    monkeypatch.setattr(mcp_data_views, "rollback_preview", lambda: {"available": True, "rows": 1})
    monkeypatch.setattr(mcp_data_views, "preview_local_import", lambda path, dataset_type: {"valid": True, "path": str(path), "dataset_type": dataset_type})
    monkeypatch.setattr(mcp_universe_ops := tools_universe.mcp_universe_ops, "preview_universe_change", lambda *args, **kwargs: {"valid": True, "expected_revision": kwargs.get("expected_revision") or "R1"})
    monkeypatch.setattr(mcp_universe_ops, "preview_universe_import", lambda source: {"valid": True, "expected_revision": "R1"})
    monkeypatch.setattr(mcp_etf_views, "preview_disclosure_import", lambda *args: {"valid": True})
    monkeypatch.setattr(mcp_data_views, "commit_local_import", lambda *args: writes.append("data_import"))
    monkeypatch.setattr(mcp_data_views, "rollback_prices", lambda: writes.append("rollback"))
    monkeypatch.setattr(mcp_etf_views, "commit_disclosure_import", lambda *args: writes.append("disclosure"))
    monkeypatch.setattr(tools_data, "_submit_workflow", lambda *args: writes.append("refresh"))

    cases = [
        ("data_refresh", {"source": "prices"}),
        ("data_rollback_prices", {"reason": "restore previous validated snapshot"}),
        ("data_import_commit", {"path": str(source), "dataset_type": "prices"}),
        ("filing_import", {"path": str(source), "jurisdiction": "NO", "instrument_id": "BANK", "source_url": "https://example.invalid/filing", "period": "2025", "sha256": digest}),
        ("universe_change_commit", {"action": "disable", "instrument_id": "BANK", "fields": {}, "expected_revision": "R1"}),
        ("universe_import_commit", {"source": str(source), "expected_revision": "R1"}),
        ("etf_disclosure_import", {"kind": "document", "path": str(source), "instrument_id": "FUND", "as_of": date(2026, 1, 1), "sha256": digest}),
    ]
    for name, arguments in cases:
        context = _context(tmp_path / "rate_limits.sqlite3")
        staged = invoke_tool(name, arguments, context=context)
        assert isinstance(staged["confirm_token"], str)
        assert writes == []
        with pytest.raises(ConfirmationError):
            invoke_tool(name, {**arguments, "confirm_token": "invalid-token"}, context=context)
        assert writes == []


def test_etf_outputs_are_compact_and_paged(monkeypatch: pytest.MonkeyPatch) -> None:
    holdings = [{"name": f"Holding {index}", "weight": 0.1} for index in range(15)]
    monkeypatch.setattr(mcp_etf_views, "etf_holdings_view", lambda *_args, **_kwargs: {"status": "available", "holdings": holdings, "splits": {"sector": {"known": 1.0}}, "gaps": None})
    first = invoke_tool("etf_holdings", {"instrument_id": "FUND", "as_of": date(2026, 11, 2), "top_n": 15, "limit": 5}, context=_context())
    second = invoke_tool("etf_holdings", {"instrument_id": "FUND", "as_of": date(2026, 11, 2), "top_n": 15, "limit": 5, "cursor": first["next_cursor"]}, context=_context())
    assert len(first["holdings"]) == len(second["holdings"]) == 5
    assert first["next_cursor"]

    monkeypatch.setattr(mcp_etf_views, "etf_disclosures_view", lambda _instrument: {"status": "available", "documents": [{"document": index} for index in range(8)], "parsed_fields": [], "conflicts": []})
    page = invoke_tool("etf_disclosures", {"instrument_id": "FUND", "limit": 3}, context=_context())
    assert len(page["documents_and_fields"]) == 3
    assert page["next_cursor"]


def test_universe_search_filters_and_preserves_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        UniverseRecord(instrument_id="A", name="Alpha Fund", isin="needs_verification", isin_status="needs_verification", ticker="ALP", asset_type="etf", tier="primary", enabled=True),
        UniverseRecord(instrument_id="B", name="Beta Bank", isin="needs_verification", isin_status="needs_verification", ticker="BET", asset_type="stock", tier="secondary", enabled=False),
    ]
    monkeypatch.setattr(tools_universe.mcp_universe_ops, "universe_snapshot", lambda: {"records": records, "revision": "R5", "integrity_errors": ()})
    result = invoke_tool("universe_search", {"query": "alpha", "enabled": True}, context=_context())
    assert result["revision"] == "R5"
    assert [item["instrument_id"] for item in result["records"]] == ["A"]


def test_data_import_preview_returns_a_commit_bound_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "prices.csv"
    source.write_text("date,price\n", encoding="utf-8")
    monkeypatch.setattr(mcp_data_views, "preview_local_import", lambda path, dataset_type: {"status": "ok", "dataset_type": dataset_type, "rows": 1})
    monkeypatch.setattr(mcp_data_views, "commit_local_import", lambda path, dataset_type: {"status": "ok", "dataset_type": dataset_type})

    context = _context()
    preview = invoke_tool("data_import_preview", {"path": str(source), "dataset_type": "prices"}, context=context)
    assert isinstance(preview["confirm_token"], str)
    result = invoke_tool("data_import_commit", {"path": str(source), "dataset_type": "prices", "confirm_token": preview["confirm_token"]}, context=context)
    assert result["status"] == "ok"


def test_filing_import_uses_session_root_from_an_unrelated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import official_filing_import
    from etf_cockpit.mcp.errors import InvalidArgumentsError, MCPToolError

    root = tmp_path / "configured"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    source = elsewhere / "filing.xbri"
    source.write_bytes(b"local filing")
    calls = []
    monkeypatch.setattr(official_filing_import, "import_official_filing", lambda path, **kwargs: calls.append((path, kwargs)) or {"status": "ok"})
    arguments = {"path": str(source), "jurisdiction": "NO", "instrument_id": "BANK", "source_url": "https://example.invalid/filing", "period": "2025-12-31", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    context = _context()
    context.session = SimpleNamespace(root=root)
    preview = invoke_tool("filing_import", arguments, context=context)
    assert calls == []
    invoke_tool("filing_import", {**arguments, "confirm_token": preview["confirm_token"]}, context=context)
    assert len(calls) == 1
    assert calls[0][1]["universe_root"] == root.resolve()
    assert calls[0][1]["output_dir"] == root.resolve() / "evidence" / "norway" / "BANK-2025"

    context.session = None
    preview = invoke_tool("filing_import", arguments, context=context)
    with pytest.raises(MCPToolError, match="DATA_ROOT_UNAVAILABLE"):
        invoke_tool("filing_import", {**arguments, "confirm_token": preview["confirm_token"]}, context=context)
    context.session = SimpleNamespace(root=root)
    escaping = {**arguments, "instrument_id": "../../../../escape"}
    preview = invoke_tool("filing_import", escaping, context=context)
    with pytest.raises(InvalidArgumentsError, match="configured data root"):
        invoke_tool("filing_import", {**escaping, "confirm_token": preview["confirm_token"]}, context=context)
    assert len(calls) == 1


def test_savings_bank_import_rejects_stale_revision_and_save_time_race(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import mcp_universe_ops
    from etf_cockpit.data.universe_store import UniverseRevisionConflict, load_universe, save_universe

    existing = UniverseRecord("BANK", "Bank", isin="needs_verification", isin_status="needs_verification", ticker="BANK")
    candidate = UniverseRecord("NEW", "New Bank", isin="needs_verification", isin_status="needs_verification", ticker="NEW")
    concurrent = UniverseRecord("OTHER", "Other Bank", isin="needs_verification", isin_status="needs_verification", ticker="OTHER")
    initial = save_universe((existing,), "", root=tmp_path)
    monkeypatch.setattr(mcp_universe_ops, "ROOT", tmp_path)
    builds = []

    def build(root, *, apply):
        assert apply is False
        builds.append(root)
        save_universe((existing, concurrent), initial.revision, root=root)
        return [candidate]

    monkeypatch.setattr(mcp_universe_ops, "sync_savings_banks", build)
    monkeypatch.setattr(mcp_universe_ops, "isin_corrections", lambda root: {"BANK": "US0378331005"})
    with pytest.raises(ValueError, match="revision changed"):
        mcp_universe_ops.commit_universe_import("savings_bank_gap", expected_revision="stale")
    assert builds == []
    with pytest.raises(UniverseRevisionConflict):
        mcp_universe_ops.commit_universe_import("savings_bank_gap", expected_revision=initial.revision)
    current = load_universe(tmp_path)
    assert [record.instrument_id for record in current.records] == ["BANK", "OTHER"]
    assert current.records[0].isin == "NEEDS_VERIFICATION"

    monkeypatch.setattr(mcp_universe_ops, "sync_savings_banks", lambda root, *, apply: [candidate] if apply is False else pytest.fail("unguarded write"))
    result = mcp_universe_ops.commit_universe_import("savings_bank_gap", expected_revision=current.revision)
    saved = load_universe(tmp_path)
    assert result["save_result"].revision == saved.revision
    assert [record.instrument_id for record in saved.records] == ["BANK", "OTHER", "NEW"]
    assert saved.records[0].isin == "US0378331005"


def test_local_import_commit_previews_and_commits_with_only_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(mcp_data_views, "preview_local_import", lambda path, dataset_type: {"dataset_type": dataset_type})
    monkeypatch.setattr(mcp_data_views, "commit_local_import", lambda path, dataset_type: calls.append((path, dataset_type)) or {"status": "ok"})
    arguments = {"path": str(tmp_path / "prices.csv")}
    context = _context()
    staged = invoke_tool("data_import_commit", arguments, context=context)
    assert staged["preview"]["dataset_type"] == "prices"
    assert isinstance(staged["confirm_token"], str)
    assert calls == []
    result = invoke_tool("data_import_commit", {**arguments, "confirm_token": staged["confirm_token"]}, context=context)
    assert result["status"] == "ok"
    assert calls == [(Path(arguments["path"]), "prices")]


def test_filing_script_parser_patch_reaches_application_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import import_official_filing as script
    from etf_cockpit.application import official_filing_import as application

    assert script is application
    issuer = UniverseRecord("BANK", "Bank", ticker="BANK", asset_type="equity_certificate", lei="1" * 20)
    monkeypatch.setattr(script, "load_sparebank_records", lambda root, **kwargs: (issuer,))
    monkeypatch.setattr(script, "_resolve_published_at", lambda *args: "2026-03-05T00:00:00Z")
    parsed = []

    def parser(path):
        parsed.append(path)
        raise RuntimeError("patched parser reached")

    monkeypatch.setattr(script, "parse_esef_package", parser)
    source = tmp_path / "filing.xbri"
    source.write_bytes(b"filing")
    with pytest.raises(RuntimeError, match="patched parser reached"):
        script.import_official_filing(source, jurisdiction="NO", instrument_id="BANK", source_url="https://example.invalid", expected_period="2025", output_dir=tmp_path / "evidence")
    assert parsed == [source]
    assert not (tmp_path / "evidence").exists()


def test_pit_script_patch_reaches_history_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import pit_history_backfill as script
    from etf_cockpit.application import pit_history as application

    assert script is application
    monkeypatch.setattr(script, "_imported_ids", lambda path: {("BANK", "filing-1")})
    logged = []
    monkeypatch.setattr(script, "_append_log", lambda path, row: logged.append(dict(row)))
    filing = {"id": "filing-1", "date_added": "2026-03-05", "period_end": "2025-12-31", "package_url": "/filing.xbri"}
    result = script.import_generic_history("BANK", "L", [filing], lambda filing: pytest.fail("patched history was bypassed"), tmp_path / "log.jsonl", importer=lambda *args, **kwargs: pytest.fail("already imported"))
    assert result[0]["status"] == "already_imported"
    assert logged == result
    assert not (tmp_path / "log.jsonl").exists()


def test_disclosures_page_all_canonical_records_and_conflicts(monkeypatch: pytest.MonkeyPatch) -> None:
    import pandas as pd

    docs = pd.DataFrame([{"instrument_id": "FUND", "document": index} for index in range(103)])
    reports = pd.DataFrame([{"instrument_id": "FUND", "field": index, "verification_status": "conflict"} for index in range(107)])
    monkeypatch.setattr(tools_etf.mcp_etf_views, "read_document_registry", lambda: docs)
    monkeypatch.setattr(tools_etf.mcp_etf_views, "read_etf_report_records", lambda: reports)
    cursor = None
    seen = []
    while True:
        page = invoke_tool("etf_disclosures", {"instrument_id": "FUND", "limit": 25, "cursor": cursor}, context=_context())
        assert len(page["documents_and_fields"]) <= 25
        assert len(page["conflicts"]) <= 25
        assert page["documents"] is page["parsed_fields"] is None
        seen.extend(page["documents_and_fields"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert [row["document"] for row in seen[:103]] == list(range(103))
    assert [row["field"] for row in seen[103:]] == list(range(107))

    conflicts, cursor = [], None
    while True:
        page = invoke_tool("etf_disclosures", {"instrument_id": "FUND", "limit": 25, "conflicts_cursor": cursor}, context=_context())
        assert len(page["conflicts"]) <= 25
        conflicts.extend(page["conflicts"])
        cursor = page["conflicts_next_cursor"]
        if cursor is None:
            break
    assert [row["field"] for row in conflicts] == list(range(107))


def test_holdings_gaps_and_readiness_failed_dates_are_paged(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.mcp.errors import InvalidCursorError

    dates = [f"2026-01-{day:02}" for day in range(1, 13)]
    monkeypatch.setattr(mcp_etf_views, "etf_holdings_view", lambda *args, **kwargs: {"holdings": [{"name": "Holding"}], "gaps": dates})
    arguments = {"instrument_id": "FUND", "as_of": date(2026, 11, 2), "include_gaps": True, "limit": 5}
    first = invoke_tool("etf_holdings", arguments, context=_context())
    second = invoke_tool("etf_holdings", {**arguments, "gaps_cursor": first["gaps_next_cursor"]}, context=_context())
    third = invoke_tool("etf_holdings", {**arguments, "gaps_cursor": second["gaps_next_cursor"]}, context=_context())
    assert first["gaps"] + second["gaps"] + third["gaps"] == dates
    assert [len(page["gaps"]) for page in (first, second, third)] == [5, 5, 2]
    assert third["gaps_next_cursor"] is None
    with pytest.raises(InvalidCursorError):
        invoke_tool("etf_holdings", {**arguments, "cursor": first["gaps_next_cursor"]}, context=_context())

    monkeypatch.setattr(mcp_data_views, "data_readiness_view", lambda *args, **kwargs: {"failed_dates": dates, "summary": {"status": "FAIL", "dates_failed": 12, "failed_dates": dates}, "interval": {}})
    arguments = {"start": date(2026, 1, 1), "end": date(2026, 1, 12), "limit": 5}
    first = invoke_tool("data_readiness", arguments, context=_context())
    second = invoke_tool("data_readiness", {**arguments, "cursor": first["next_cursor"]}, context=_context())
    third = invoke_tool("data_readiness", {**arguments, "cursor": second["next_cursor"]}, context=_context())
    assert first["failed_dates"] + second["failed_dates"] + third["failed_dates"] == dates
    assert [len(page["failed_dates"]) for page in (first, second, third)] == [5, 5, 2]
    assert third["next_cursor"] is None
    for page in (first, second, third):
        assert page["summary"] == {"status": "FAIL", "dates_failed": 12}
