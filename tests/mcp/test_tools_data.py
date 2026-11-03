from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from etf_cockpit.application import mcp_data_views, mcp_etf_views
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.errors import ConfirmationError
from etf_cockpit.mcp.registry import CallContext, RateLimiter, invoke_tool
from etf_cockpit.mcp import tools_data, tools_etf, tools_universe
from etf_cockpit.data.universe_store import UniverseRecord


def test_validate_prices_pages_both_collections_and_preserves_summary(monkeypatch, tmp_path):
    from etf_cockpit.mcp.paging import DEFAULT_PAGE_SIZE
    from etf_cockpit.mcp.registry import use_call_context
    from etf_cockpit.mcp.serialise import build_envelope, envelope_dict

    issues = [{"id": index, "detail": "issue " * 300, "value": None} for index in range(70)]
    metadata = [{"dataset": str(index), "detail": "metadata " * 200} for index in range(65)]
    report = {"issues": issues, "dataset_metadata": metadata, "status": "Blocked",
              "analysis_allowed": False, "as_of_date": None, "unavailable_reason": "missing evidence"}
    monkeypatch.setattr(mcp_data_views, "validate_prices_view", lambda **_kwargs: report)
    active = _context()
    active.session = SimpleNamespace(root=tmp_path)
    with use_call_context(active):
        first = tools_data.data_validate_prices()
        for key, cursor_arg, next_key, expected in (
            ("issues", "cursor", "next_cursor", issues),
            ("dataset_metadata", "metadata_cursor", "metadata_next_cursor", metadata),
        ):
            page = first
            received = []
            while True:
                assert len(json.dumps(envelope_dict(build_envelope(page)), separators=(",", ":"))) <= 32_000
                assert 0 < len(page[key]) <= DEFAULT_PAGE_SIZE
                assert page["rows_total"] == 135 and page[f"{key}_rows_total"] == len(expected)
                assert page["status"] == "Blocked" and page["analysis_allowed"] is False
                assert page["as_of_date"] is None and page["unavailable_reason"] == "missing evidence"
                received.extend(page[key])
                if page[next_key] is None:
                    break
                page = tools_data.data_validate_prices(**{cursor_arg: page[next_key]})
            assert received == expected


@pytest.mark.parametrize("portfolio", [False, True])
def test_look_through_default_uses_latest_matching_publication_knowledge(monkeypatch, tmp_path, portfolio):
    from etf_cockpit.application import scoreboard_publication
    from etf_cockpit.data.local_storage import TransactionalStore

    scoreboard = tmp_path / "data" / "derived" / "scoreboard.parquet"
    scoreboard.parent.mkdir(parents=True)
    scoreboard.write_bytes(b"published scoreboard bytes")
    digest = hashlib.sha256(scoreboard.read_bytes()).hexdigest()
    with TransactionalStore(tmp_path) as store:
        for name, known_at, checksum in (
            ("old", "2026-10-20T21:00:00Z", digest),
            ("latest", "2026-10-30T21:00:00Z", digest),
            ("unrelated", "2026-11-02T21:00:00Z", "0" * 64),
        ):
            store.put_many([(scoreboard_publication.SCOREBOARD_PUBLICATION_BINDING_ENTITY_TYPE, name, {
                "schema_version": "scoreboard_publication_binding.v1", "known_at": known_at,
                "score_completed_at": "2026-10-20T20:00:00Z", "scoreboard_sha256": checksum,
                "execution_allowed": False,
            })], immutable=True)
    calls = []
    monkeypatch.setattr(mcp_etf_views, "etf_look_through_view", lambda instrument, time: calls.append((instrument, time)) or {"coverage": None})
    monkeypatch.setattr(mcp_etf_views, "portfolio_look_through_view", lambda snapshot, time: calls.append((snapshot, time)) or {"coverage": None})
    snapshot = SimpleNamespace(facts_known_at="2026-11-03T12:00:00Z")
    active = _context()
    active.session = SimpleNamespace(root=tmp_path, snapshot=snapshot)
    # No optional arguments at all selects the portfolio; instrument-only calls
    # omit decision_time too. Neither uses the newer in-memory snapshot time.
    result = invoke_tool("etf_look_through", {} if portfolio else {"instrument_id": "FUND"}, context=active)
    assert calls == [(snapshot if portfolio else "FUND", datetime(2026, 10, 30, 21, tzinfo=timezone.utc))]
    assert result["decision_time"] == "2026-10-30T21:00:00Z"
    assert result["coverage"] is None


def test_look_through_missing_publication_fails_closed_but_explicit_time_works(monkeypatch, tmp_path):
    from etf_cockpit.mcp.errors import MCPToolError

    calls = []
    monkeypatch.setattr(mcp_etf_views, "etf_look_through_view", lambda instrument, time: calls.append(time) or {"coverage": None})
    active = _context()
    active.session = SimpleNamespace(root=tmp_path)
    with pytest.raises(MCPToolError, match="SCOREBOARD_KNOWLEDGE_UNAVAILABLE"):
        invoke_tool("etf_look_through", {"instrument_id": "FUND"}, context=active)
    assert calls == []
    instant = datetime(2026, 10, 30, tzinfo=timezone.utc)
    result = invoke_tool("etf_look_through", {"instrument_id": "FUND", "decision_time": instant}, context=active)
    assert calls == [instant] and result["decision_time"] == "2026-10-30T00:00:00Z"


@pytest.mark.parametrize("submission_route", ["session", "api"])
def test_refresh_submission_binds_dedupe_to_normalised_request(submission_route):
    from etf_cockpit.mcp.registry import use_call_context

    submissions = []

    def submit_workflow(*, workflow_type, label, input_payload, dedupe_key):
        submissions.append((workflow_type, input_payload, dedupe_key))
        return "wf_refresh"

    def execute(command):
        assert command.idempotency_key == f"mcp:{command.dedupe_key.rsplit(':', 1)[1]}"
        submissions.append((command.workflow_type, command.input_payload, command.dedupe_key))
        return SimpleNamespace(status="accepted", resource_id="wf_refresh")

    context = _context()
    context.session = (SimpleNamespace(submit_workflow=submit_workflow) if submission_route == "session"
                       else SimpleNamespace(application_api=SimpleNamespace(execute=execute)))
    context.session.find_active_workflow = lambda **_kwargs: None
    with use_call_context(context):
        first = tools_data.data_refresh(" PRICES ", ids=None, years=1, rescore=False)
        repeated = tools_data.data_refresh("prices", ids=[], years=1, rescore=False)
        changed = tools_data.data_refresh("prices", years=2, rescore=False)
        other_source = tools_data.data_refresh("fundamentals", years=1, rescore=False)
    assert first["job_id"] == repeated["job_id"] == changed["job_id"] == other_source["job_id"] == "wf_refresh"
    assert len(submissions) == 4
    assert submissions[0][1] == {"source": "prices", "ids": [], "years": 1, "rescore": False}
    assert submissions[0][2].startswith("mcp:data_refresh:")
    keys = [submission[2].split(":") for submission in submissions]
    assert all(len(key) == 4 and len(key[2]) == 64 and len(key[3]) == 32 for key in keys)
    assert keys[0][2] == keys[1][2]
    assert len({keys[index][2] for index in (0, 2, 3)}) == 3
    assert len({key[3] for key in keys}) == 4


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


@pytest.mark.parametrize("canonical_date", ["2026-10-30", None, "missing"])
def test_data_health_uses_canonical_report_date_and_reports_missing_date(monkeypatch, canonical_date) -> None:
    from etf_cockpit.data.health import DataHealthReport, DataHealthRow, DataHealthStatus

    row = DataHealthRow(dataset="prices", status=DataHealthStatus.HEALTHY, path="fixture.parquet", row_count=1,
                        checksum=None, as_of="2026-10-30", freshness="fresh", provider=None,
                        last_success=None, last_failure=None, warnings=())
    report = DataHealthReport(created_at="2026-11-02T00:00:00Z", as_of_date=canonical_date, rows=(row,))
    if canonical_date == "missing":
        report = SimpleNamespace(rows=(row,), as_of="1999-01-01")
        monkeypatch.setattr(mcp_data_views, "filter_data_health_rows", lambda report, **kwargs: report.rows)
    monkeypatch.setattr(mcp_data_views, "load_config", lambda: None)
    monkeypatch.setattr(mcp_data_views, "build_data_health", lambda *args, **kwargs: report)

    result = invoke_tool("data_health", {}, context=_context())
    assert result["rows"][0]["dataset"] == "prices"
    assert result["rows"][0]["row_count"] == 1
    assert result["as_of"] == (canonical_date if canonical_date != "missing" else None)
    if canonical_date in (None, "missing"):
        assert result["unavailable_reason"]
    else:
        assert result["unavailable_reason"] is None


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


@pytest.mark.parametrize("history", [False, True])
@pytest.mark.parametrize("resolver_source", ["script", "application", "explicit"])
def test_sparebank_script_lei_resolver_patch_reaches_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, history: bool, resolver_source: str
) -> None:
    from scripts import sparebank_refresh as script
    from etf_cockpit.application import sparebank_refresh as application

    record = SimpleNamespace(instrument_id="BANK", lei="", ticker="BANK", isin="")
    resolved = []
    requested_leis = []
    now = "2026-03-05T00:00:00Z"

    def resolver(rec, evidence_dir, client, *, now):
        resolved.append((rec, evidence_dir, client, now))
        return "patched-lei"

    def forbidden_resolver(*args, **kwargs):
        pytest.fail("selected LEI resolver was bypassed")

    client = SimpleNamespace(filings_for_lei=lambda lei: requested_leis.append(lei) or ())
    monkeypatch.setattr(script, "load_sparebank_records", lambda root: (record,))
    monkeypatch.setattr(application, "load_sparebank_records", lambda root: (record,))
    monkeypatch.setattr(script, "_resolve_lei", resolver if resolver_source == "script" else forbidden_resolver)
    application_resolver = resolver if resolver_source == "application" else forbidden_resolver
    monkeypatch.setattr(application, "_resolve_lei", application_resolver)
    module = application if resolver_source == "application" else script
    kwargs = {"lei_resolver": resolver} if resolver_source == "explicit" else {}

    rows = module.refresh_sparebanks(
        tmp_path, universe_root=tmp_path, client=client, decision_time=now,
        history=history, write_summary=False, rescorer=lambda *args: (None, None, "partial"), **kwargs,
    )

    assert resolved == [(record, tmp_path / "evidence" / "norway" / "BANK", client, now)]
    assert requested_leis == ["patched-lei"]
    assert rows[0]["lei"] == "patched-lei"
    assert rows[0]["reason"] == "no_filing_found"
    assert application._resolve_lei is application_resolver


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


def test_data_health_reads_only_session_root_and_configuration(tmp_path, monkeypatch):
    import pandas as pd

    root = tmp_path / "owner"
    config_dir = root / "configs"
    config_dir.mkdir(parents=True)
    (config_dir / "universe.yaml").write_text("etfs: []\n", encoding="utf-8")
    clean = root / "data" / "clean"
    clean.mkdir(parents=True)
    pd.DataFrame({"date": ["2026-10-30"], "close": [123.0]}).to_parquet(clean / "prices.parquet")
    original_load = mcp_data_views.load_config
    reads = []

    def configured_load(path):
        reads.append(path)
        assert path == config_dir
        return original_load(path)

    monkeypatch.setattr(mcp_data_views, "load_config", configured_load)
    monkeypatch.setattr(mcp_data_views, "ROOT", tmp_path / "forbidden-root")
    context = _context(tmp_path / "limits.sqlite3")
    context.session = SimpleNamespace(root=root)
    result = invoke_tool("data_health", {"dataset": "prices"}, context=context)
    assert reads == [config_dir]
    assert result["rows"][0]["row_count"] == 1
    assert Path(result["rows"][0]["path"]) == clean / "prices.parquet"


@pytest.mark.parametrize(("tool_name", "arguments", "facade", "result"), [
    ("data_readiness", {"start": date(2026, 10, 29), "end": date(2026, 10, 30)},
     "data_readiness_view", {"failed_dates": [], "summary": {}, "interval": {}}),
    ("data_provider_status", {}, "data_provider_status_view", ()),
    ("data_validate_prices", {}, "validate_prices_view", {"status": "Unavailable"}),
    ("data_import_preview", {"path": "fixture.csv"}, "preview_local_import", {"valid": False}),
    ("data_rollback_prices", {"reason": "fixture"}, "rollback_preview", {"available": True}),
])
def test_data_facades_receive_session_root(tmp_path, monkeypatch, tool_name, arguments, facade, result):
    reads = []

    def read(*args, root, **kwargs):
        reads.append(root)
        return dict(result) if isinstance(result, dict) else result

    monkeypatch.setattr(mcp_data_views, facade, read)
    context = _context(tmp_path / "limits.sqlite3")
    context.session = SimpleNamespace(root=tmp_path)
    invoke_tool(tool_name, arguments, context=context)
    assert reads == [tmp_path.resolve()]


@pytest.mark.parametrize("facade", ["preview_local_import", "commit_local_import", "rollback_preview", "rollback_prices", "validate_prices_view"])
def test_process_bound_data_services_refuse_mismatched_root_before_io(tmp_path, monkeypatch, facade):
    def forbidden_load(*args, **kwargs):
        pytest.fail("configuration from another root was read")

    monkeypatch.setattr(mcp_data_views, "load_config", forbidden_load)
    arguments = (tmp_path / "fixture.csv",) if "import" in facade else ()
    with pytest.raises(ValueError, match="ETF_COCKPIT_ROOT"):
        getattr(mcp_data_views, facade)(*arguments, root=tmp_path)


@pytest.fixture(params=["session", "api"])
def workflow_submission_context(request, tmp_path, monkeypatch):
    from etf_cockpit.application import headless_session
    from etf_cockpit.application.api import LocalApplicationApi
    from etf_cockpit.core.job_scheduler import DurableJobScheduler

    scheduler = DurableJobScheduler(tmp_path, max_concurrency=1)
    snapshot = SimpleNamespace(universe_revision="submission-fixture")
    context = _context(tmp_path / "limits.sqlite3")
    commands = []
    execute = LocalApplicationApi.execute

    def record_command(api, command):
        submission_id = command.dedupe_key.rsplit(":", 1)[1]
        if request.param == "session":
            command_hash = hashlib.sha256(f"{command.workflow_type}\0{command.dedupe_key}".encode("utf-8")).hexdigest()
            assert command.idempotency_key == f"mcp-{command_hash}"
        else:
            assert command.idempotency_key == f"mcp:{submission_id}"
        commands.append(command)
        return execute(api, command)

    monkeypatch.setattr(LocalApplicationApi, "execute", record_command)
    monkeypatch.setattr(headless_session, "ROOT", tmp_path)
    session = headless_session.HeadlessSession(snapshot, root=tmp_path)
    session._job_scheduler = scheduler
    if request.param == "session":
        context.session = session
    else:
        api = LocalApplicationApi(lambda: snapshot, scheduler=scheduler, root=tmp_path)
        context.session = SimpleNamespace(application_api=api, find_active_workflow=session.find_active_workflow)
    return context, scheduler, commands


def _confirmed_refresh(context):
    arguments = {"source": "prices", "years": 1, "rescore": False}
    preview = invoke_tool("data_refresh", arguments, context=context)
    return invoke_tool("data_refresh", {**arguments, "confirm_token": preview["confirm_token"]}, context=context)["job_id"]


def test_confirmed_identical_refresh_after_completion_creates_new_job(workflow_submission_context):
    context, scheduler, commands = workflow_submission_context
    first = _confirmed_refresh(context)
    completed = scheduler.run_once(lambda _context: "offline completion", workflow_id=first)
    assert completed.status.value == "succeeded"
    assert scheduler.get_workflow(first).status.value == "succeeded"

    second = _confirmed_refresh(context)

    assert second != first
    assert scheduler.get_workflow(second).status.value == "queued"
    assert len(scheduler.list_workflows()) == 2
    first_key = scheduler.get_workflow(first).dedupe_key.rsplit(":", 1)
    second_key = scheduler.get_workflow(second).dedupe_key.rsplit(":", 1)
    assert first_key[0] == second_key[0]
    assert first_key[1] != second_key[1]
    assert len(commands) == 2
    assert len({command.idempotency_key for command in commands}) == 2


def test_confirmed_identical_refresh_while_queued_reuses_job(workflow_submission_context):
    context, scheduler, commands = workflow_submission_context
    first = _confirmed_refresh(context)
    assert scheduler.get_workflow(first).status.value == "queued"

    second = _confirmed_refresh(context)

    assert second == first
    assert len(scheduler.list_workflows()) == 1
    assert len(scheduler.list_jobs()) == 1
    assert len(commands) == 1


def test_identical_score_history_backfill_after_completion_creates_new_job(workflow_submission_context):
    context, scheduler, commands = workflow_submission_context
    arguments = {"start": date(2026, 10, 1), "end": date(2026, 10, 30)}
    first = invoke_tool("score_history_backfill", arguments, context=context)["job_id"]
    assert invoke_tool("score_history_backfill", arguments, context=context)["job_id"] == first
    assert len(scheduler.list_workflows()) == 1
    completed = scheduler.run_once(lambda _context: "offline completion", workflow_id=first)
    assert completed.status.value == "succeeded"
    assert scheduler.get_workflow(first).status.value == "succeeded"

    second = invoke_tool("score_history_backfill", arguments, context=context)["job_id"]

    assert second != first
    assert scheduler.get_workflow(second).status.value == "queued"
    assert len(scheduler.list_workflows()) == 2
    assert len(commands) == 2
    assert len({command.idempotency_key for command in commands}) == 2


def test_completed_refresh_replacement_is_reused_while_queued(workflow_submission_context, tmp_path):
    context, scheduler, commands = workflow_submission_context
    now = [0.0]
    context.rate_limiter = RateLimiter(path=tmp_path / "controlled-limits.sqlite3", clock=lambda: now[0])
    first = _confirmed_refresh(context)
    assert scheduler.run_once(lambda _context: "offline completion", workflow_id=first).status.value == "succeeded"

    replacement = _confirmed_refresh(context)
    assert replacement != first
    assert scheduler.get_workflow(replacement).status.value == "queued"
    # Each preview + confirmation consumes two calls. C arrives in the next
    # quota window; B remains queued throughout, and the real quota stays enabled.
    now[0] += 3601
    repeated = _confirmed_refresh(context)

    assert repeated == replacement
    assert len(scheduler.list_workflows()) == len(scheduler.list_jobs()) == 2
    assert len(commands) == 2


def _seed_250_newer_terminal_workflows(scheduler):
    from etf_cockpit.core.job_scheduler import JobSpec
    from etf_cockpit.data.local_storage import storage_layout

    seed = scheduler.submit("refresh", "Terminal history", (JobSpec("start", "Start"),), dedupe_key="terminal:0")
    scheduler.cancel(seed.workflow_id)
    newer = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(timespec="milliseconds")
    with sqlite3.connect(storage_layout(scheduler.root).transactional_path) as connection:
        connection.execute("UPDATE workflow_runs SET created_at = ? WHERE workflow_id = ?", (newer, seed.workflow_id))
        connection.executemany(
            """
            INSERT INTO workflow_runs (
                workflow_id, workflow_type, label, status, dedupe_key, input_hash,
                inputs_json, outputs_json, created_at, finished_at, resource_json
            )
            SELECT ?, workflow_type, label, status, ?, input_hash,
                   inputs_json, outputs_json, ?, finished_at, resource_json
            FROM workflow_runs WHERE workflow_id = ?
            """,
            ((f"terminal-{index}", f"terminal:{index}", newer, seed.workflow_id) for index in range(1, 250)),
        )
    window = scheduler.list_workflows(limit=200)
    assert len(window) == 200
    assert all(row.status.value == "cancelled" for row in window)


def test_older_queued_refresh_is_found_and_reused_after_250_terminal_workflows(workflow_submission_context):
    context, scheduler, commands = workflow_submission_context
    first = _confirmed_refresh(context)
    _seed_250_newer_terminal_workflows(scheduler)

    original = scheduler.get_workflow(first)
    prefix = original.dedupe_key.rsplit(":", 1)[0] + ":"
    assert scheduler.find_active_workflow("refresh", prefix) == original
    assert _confirmed_refresh(context) == first
    assert scheduler.get_workflow(first).status.value == "queued"
    assert len(commands) == 1


def test_refresh_submits_new_job_after_250_terminal_workflows(workflow_submission_context):
    context, scheduler, commands = workflow_submission_context
    _seed_250_newer_terminal_workflows(scheduler)
    assert scheduler.find_active_workflow("refresh", "mcp:data_refresh:") is None

    submitted = _confirmed_refresh(context)

    assert scheduler.get_workflow(submitted).status.value == "queued"
    assert len(commands) == 1


@pytest.mark.parametrize("lookup", ["missing", "legacy_listing", "failed", "missing_id"])
def test_refresh_fails_closed_when_active_lookup_is_unavailable(lookup):
    from etf_cockpit.mcp.errors import MCPToolError
    from etf_cockpit.mcp.registry import use_call_context

    def find_active_workflow(**_kwargs):
        if lookup == "failed":
            raise RuntimeError("lookup unavailable")
        return SimpleNamespace(workflow_id=None)

    context = _context()
    context.session = SimpleNamespace(submit_workflow=lambda **_kwargs: pytest.fail("unsafe submission"))
    if lookup == "legacy_listing":
        context.session.list_workflows = lambda **_kwargs: []
    elif lookup != "missing":
        context.session.find_active_workflow = find_active_workflow
    with use_call_context(context), pytest.raises(MCPToolError) as error:
        tools_data.data_refresh("prices")
    assert error.value.reason_code == "JOB_SERVICE_UNAVAILABLE"


@pytest.mark.parametrize("record_kind", ["mapping", "record"])
def test_refresh_reuses_active_lookup_match(record_kind):
    import json

    from etf_cockpit.mcp.registry import use_call_context

    payload = {"source": "prices", "ids": [], "years": 5, "rescore": True}
    fingerprint = hashlib.sha256(json.dumps(
        ["data_refresh", payload], sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    matching = {"workflow_id": "existing"}
    lookups = []

    def find_active_workflow(*, workflow_type, dedupe_prefix):
        lookups.append((workflow_type, dedupe_prefix))
        return matching if record_kind == "mapping" else SimpleNamespace(**matching)

    context = _context()
    context.session = SimpleNamespace(find_active_workflow=find_active_workflow, submit_workflow=lambda **_kwargs: pytest.fail("duplicate submission"))
    with use_call_context(context):
        assert tools_data.data_refresh("prices")["job_id"] == "existing"
    assert lookups == [("refresh", f"mcp:data_refresh:{fingerprint}:")]


def test_confirmed_submission_identity_is_derived_from_token():
    from etf_cockpit.mcp.registry import use_call_context

    commands = []

    def execute(command):
        commands.append(command)
        return SimpleNamespace(status="accepted", resource_id="submitted")

    context = _context()
    context.session = SimpleNamespace(find_active_workflow=lambda **_kwargs: None, application_api=SimpleNamespace(execute=execute))
    token = "single-use-token-with-nonce"
    with use_call_context(context):
        assert tools_data.data_refresh("prices", confirm_token=token)["job_id"] == "submitted"
    submission_id = hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert commands[0].dedupe_key.rsplit(":", 1)[1] == submission_id
    assert commands[0].idempotency_key == f"mcp:{submission_id}"
