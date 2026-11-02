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
