from __future__ import annotations

from datetime import date
import inspect
import json
from pathlib import Path
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application import data_service as data_service_module
from etf_cockpit.data import trade_candidate_analysis
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.errors import ConfirmationError, InvalidArgumentsError, MCPToolError
from etf_cockpit.mcp.registry import CallContext, invoke_tool
from etf_cockpit.mcp import tools_scores


def test_research_writes_refuse_invalid_confirmation_without_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import research_evidence

    writes: list[str] = []
    monkeypatch.setattr(research_evidence, "record_research_findings", lambda *args, **kwargs: writes.append("findings"))
    monkeypatch.setattr(research_evidence, "record_research_thesis", lambda *args, **kwargs: writes.append("thesis"))
    context = CallContext(
        enabled_tiers=frozenset({"research"}),
        profile="full",
        audit=AuditRecorder(sink=lambda _record: None),
    )
    calls = (
        (
            "research_record_findings",
            {"items": [], "expected_revision": "revision", "confirm_token": "invalid"},
        ),
        (
            "research_record_thesis",
            {
                "instrument_ids": ["outside"], "thesis": "Claim", "evidence_refs": ["finding"],
                "invalidation_rules": ["Rule"], "review_date": "2026-12-01",
                "expected_revision": "revision", "confirm_token": "invalid",
            },
        ),
    )

    for name, arguments in calls:
        with pytest.raises(ConfirmationError):
            invoke_tool(name, arguments, context=context)
    assert writes == []


def test_scores_ranked_pages_compactly_and_preserves_unavailable_score(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from etf_cockpit.application import scoreboard_publication, score_views

    scores = [
        SimpleNamespace(display_id="one", rank=1, final_score_10=None, final_label="unavailable", final_action="unavailable", name="One", asset_type="ETF", one_line_reason="missing score"),
        SimpleNamespace(display_id="two", rank=2, final_score_10=6.0, final_label="hold", final_action="hold", name="Two", asset_type="ETF", one_line_reason="available score"),
    ]
    snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=())), universe_revision="R1")
    session = SimpleNamespace(root=tmp_path, snapshot=snapshot)
    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (session, snapshot))
    monkeypatch.setattr(score_views, "published_scores", lambda *_args: scores)
    monkeypatch.setattr(score_views, "_rank_sort_key", lambda score: score.rank)
    monkeypatch.setattr(score_views, "score_buy_eligible", lambda _score: False)
    monkeypatch.setattr(score_views, "score_gate_failed", lambda _score: False)
    monkeypatch.setattr(score_views, "score_coverage", lambda _score: None)
    monkeypatch.setattr(scoreboard_publication, "score_rank_authority", lambda: "unavailable")
    monkeypatch.setattr(scoreboard_publication, "scoreboard_status", lambda **_kwargs: {"status": "unavailable"})

    first = tools_scores.scores_ranked(top_n=1)
    assert len(first["rows"]) == 1
    assert first["rows"][0]["score_10"] is None
    assert first["next_cursor"]
    second = tools_scores.scores_ranked(top_n=1, cursor=first["next_cursor"])
    assert [row["instrument_id"] for row in second["rows"]] == ["two"]
    assert second["next_cursor"] is None


def test_screen_run_pages_through_canonical_query_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from etf_cockpit.application import decision_views, screening_data

    snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=())))
    session = SimpleNamespace(root=tmp_path, snapshot=snapshot)
    built: list[tuple[object, object]] = []
    queried: list[tuple[object, object]] = []
    result = SimpleNamespace(
        rows=[{"instrument_id": "one"}, {"instrument_id": "two"}],
        total_input=2, total_matched=2, available_fields=("instrument_id",),
        unavailable_fields=(), warnings=(), query_checksum="query-1",
    )
    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (session, snapshot))
    monkeypatch.setattr(screening_data, "load_screening_fundamentals", lambda _root: pd.DataFrame())
    monkeypatch.setattr(decision_views, "build_screen_rows", lambda snap, fundamentals: built.append((snap, fundamentals)) or pd.DataFrame())
    monkeypatch.setattr(
        screening_data, "run_screen_query",
        lambda snap, rows, **kwargs: queried.append((snap, rows)) or result,
    )

    first = tools_scores.screen_run(top_n=1)
    second = tools_scores.screen_run(top_n=1, cursor=first["next_cursor"])
    assert first["rows"] == [{"instrument_id": "one"}]
    assert first["next_cursor"]
    assert second["rows"] == [{"instrument_id": "two"}]
    assert second["next_cursor"] is None
    assert len(built) == len(queried) == 2


def test_screen_run_default_page_bounds_wide_rows_without_losing_any(monkeypatch, tmp_path):
    from etf_cockpit.application import decision_views, screening_data
    from etf_cockpit.mcp.paging import DEFAULT_PAGE_SIZE
    from etf_cockpit.mcp.serialise import build_envelope, envelope_dict

    rows = [{"instrument_id": str(index), "evidence": "wide row " * 600, "score": None} for index in range(60)]
    result = SimpleNamespace(rows=rows, total_input=70, total_matched=60, available_fields=("instrument_id",),
                             unavailable_fields=("missing",), warnings=("missing evidence",), query_checksum="wide")
    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (SimpleNamespace(root=tmp_path), object()))
    monkeypatch.setattr(screening_data, "load_screening_fundamentals", lambda _root: pd.DataFrame())
    monkeypatch.setattr(decision_views, "build_screen_rows", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(screening_data, "run_screen_query", lambda *_args, **_kwargs: result)
    received = []
    cursor = None
    while True:
        page = tools_scores.screen_run(**({"cursor": cursor} if cursor else {}))
        assert len(json.dumps(envelope_dict(build_envelope(page)), separators=(",", ":"))) <= 32_000
        assert 0 < len(page["rows"]) <= DEFAULT_PAGE_SIZE
        assert page["rows_total"] == page["total_matched"] == 60
        assert page["total_input"] == 70 and page["warnings"] == ["missing evidence"]
        received.extend(page["rows"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert received == rows


def test_score_history_omitted_range_is_supported(monkeypatch, tmp_path):
    from etf_cockpit.application import score_explain
    from etf_cockpit.application.ui_views.stock_research import RANGE_DAYS

    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (SimpleNamespace(root=tmp_path), object()))
    result = tools_scores.score_history("VWCE")
    assert inspect.signature(tools_scores.score_history).parameters["range"].default == "1Y"
    assert "1Y" in RANGE_DAYS and RANGE_DAYS["1Y"] == 365
    assert result == score_explain.load_score_history("VWCE", range_key="1Y", root=tmp_path)


def test_screen_run_links_individually_oversized_row(monkeypatch, tmp_path):
    from etf_cockpit.application import decision_views, screening_data

    rows = [{"instrument_id": "large", "evidence": "x" * 40_000}, {"instrument_id": "small", "score": None}]
    result = SimpleNamespace(rows=rows, total_input=2, total_matched=2, available_fields=(),
                             unavailable_fields=(), warnings=(), query_checksum="oversized")
    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (SimpleNamespace(root=tmp_path), object()))
    monkeypatch.setattr(screening_data, "load_screening_fundamentals", lambda _root: pd.DataFrame())
    monkeypatch.setattr(decision_views, "build_screen_rows", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(screening_data, "run_screen_query", lambda *_args, **_kwargs: result)
    page = tools_scores.screen_run()
    link = page["rows"][0]
    assert link["type"] == "resource_link"
    assert json.loads((tmp_path / link["uri"].removeprefix("cockpit://exports/")).read_text(encoding="utf-8")) == rows[0]
    assert page["rows"][1] == rows[1] and page["rows_total"] == 2
    assert page["next_cursor"] is None
    assert len(json.dumps(page)) <= 32_000


def test_score_detail_and_rank_tools_delegate_to_application_services(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from etf_cockpit.application import instrument_detail_loader, rank_validation_service, score_explain

    snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=())))
    session = SimpleNamespace(root=tmp_path, snapshot=snapshot)
    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (session, snapshot))
    monkeypatch.setattr(score_explain, "explain_score", lambda snap, instrument_id: {"instrument_id": instrument_id, "score_10": None, "status": "unavailable"})
    monkeypatch.setattr(instrument_detail_loader, "load_instrument_detail", lambda snap, instrument_id, sections: {"instrument_id": instrument_id, "sections": list(sections)})
    assert tools_scores.score_explain(" missing ")["score_10"] is None
    assert tools_scores.instrument_detail("missing", sections=("overview",))["sections"] == ["overview"]

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        rank_validation_service, "build_rank_validation_report",
        lambda **kwargs: calls.append(kwargs) or {"status": "unavailable", "execution_allowed": False},
    )
    result = tools_scores.rank_validation_run(years=(2,))
    assert result["status"] == "succeeded"
    assert result["result"]["status"] == "unavailable"
    assert calls == [{"root": tmp_path, "years": (2,), "scope": "listing:euronext_oslo:all", "benchmark_id": None}]


def test_instrument_detail_caps_500_row_history(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import instrument_detail_loader

    history = [{"date": str(day), "adjusted_close": None if day == 499 else day + 1} for day in range(500)]
    panel = {"status": "available", "rows": 500, "history": history, "latest_price": None}
    payload = {"sections": {"overview": {"status": "available", "data": {"price": panel}}}, "execution_allowed": False}
    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (None, object()))
    monkeypatch.setattr(instrument_detail_loader, "load_instrument_detail", lambda *_args: payload)

    result = tools_scores.instrument_detail("one", sections=["overview"])
    price = result["sections"]["overview"]["data"]["price"]
    assert price["history"] == history[-60:]
    assert price["history_pagination"] == {"rows_total": 500, "rows_returned": 60, "truncated": True}
    assert price["rows"] == 500
    assert price["latest_price"] is price["history"][-1]["adjusted_close"] is None
    assert len(panel["history"]) == 500
    assert "history_pagination" not in panel


@pytest.mark.parametrize("oversized_summary", [False, True])
def test_instrument_detail_overview_score_and_resource_fit_budget(monkeypatch: pytest.MonkeyPatch, oversized_summary: bool) -> None:
    from etf_cockpit.application import instrument_detail_loader
    from etf_cockpit.mcp.resources import RESOURCE_SPECS, read_resource
    from etf_cockpit.mcp.serialise import build_envelope, envelope_dict

    rows = [{"date": str(day), "value": day, "source": "stored"} for day in range(500)]
    payload = {
        "instrument_id": "one", "status": "available", "identity": {"name": "One"},
        "sections": {
            "overview": {"status": "available", "data": {"price": {"history": rows, "latest_price": 499}}},
            "score": {"status": "available", "data": {
                "history": {"rows": rows}, "score_10": None,
                "summary": "large summary " * 3000 if oversized_summary else "canonical summary",
            }},
        },
        "execution_allowed": False,
    }
    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (None, object()))
    monkeypatch.setattr(instrument_detail_loader, "load_instrument_detail", lambda *_args: payload)

    result = tools_scores.instrument_detail("one", sections=["overview", "score"])
    assert len(json.dumps(envelope_dict(build_envelope(result)))) < 32_000
    score = result["sections"]["score"]
    if oversized_summary:
        assert score["status"] == "truncated"
        assert score["truncated"] is True
        assert "score_history(instrument_id=..., range='1M')" in score["hint"]
        assert "data" not in score
    else:
        assert score["data"]["summary"] == "canonical summary"
        assert score["data"]["score_10"] is None
        assert score["data"]["history"]["rows"] == rows[-60:]
        assert score["data"]["history"]["rows_pagination"]["rows_total"] == 500
    spec = next(spec for spec in RESOURCE_SPECS if spec.uri == "cockpit://instrument/{id}")
    resource = read_resource(spec, {"id": "one"}, CallContext())
    assert len(resource) < 32_000
    assert json.loads(resource)["data"] == result


def test_instrument_detail_preserves_unavailable_section(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.application import instrument_detail_loader

    unavailable = {"status": "unavailable", "reason": "No stored score evidence", "data": None}
    payload = {"sections": {"score": unavailable}, "execution_allowed": False}
    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (None, object()))
    monkeypatch.setattr(instrument_detail_loader, "load_instrument_detail", lambda *_args: payload)

    result = tools_scores.instrument_detail("missing", sections=["score"])
    assert result["sections"]["score"] == unavailable
    assert result["sections"]["score"]["data"] is None
    assert result["execution_allowed"] is False


def test_candidate_tool_filters_out_universe_and_delegates_to_data_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot = SimpleNamespace(
        config=SimpleNamespace(universe=SimpleNamespace(etfs=(SimpleNamespace(id="inside"),))),
    )
    session = SimpleNamespace(root=tmp_path, snapshot=snapshot)
    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (session, snapshot))
    calls: list[dict[str, object]] = []

    class FakeDataService:
        def __init__(self, config):
            assert config is snapshot.config

        def run_stored_candidate_analysis(self, **kwargs):
            calls.append(kwargs)
            return {"message": "candidate report"}

    monkeypatch.setattr(data_service_module, "DataService", FakeDataService)
    monkeypatch.setattr(
        tools_scores, "_job",
        lambda _root, _kind, _label, _payload, handler, **_kwargs: {"result": handler(None)},
    )

    result = tools_scores.candidate_analyse(["outside"], years=2)
    assert result["result"]["classification"] == "provisional_not_ranked"
    assert calls == [{"years": 2, "identifiers": ("outside",), "root": tmp_path}]
    with pytest.raises(InvalidArgumentsError, match="outside the configured universe"):
        tools_scores.candidate_analyse(["inside"])
    assert len(calls) == 1


def test_candidate_service_filters_requested_ids_and_leaves_missing_prices_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    input_path = tmp_path / "candidates.csv"
    pd.DataFrame(
        [
            {"instrument_id": "one", "yahoo_symbol": "ONE"},
            {"instrument_id": "two", "yahoo_symbol": "TWO"},
            {"instrument_id": "outside", "yahoo_symbol": "OUT"},
        ]
    ).to_csv(input_path, index=False)
    requested_mapping: dict[str, str] = {}

    class FakeProvider:
        def __init__(self, section, *, default_currency):
            requested_mapping.update(section.symbols_map)

        def fetch_prices(self, _identifiers, _start, _end):
            return SimpleNamespace(
                ok=True,
                message="fixture prices",
                data=pd.DataFrame(
                    [{"etf_id": "one", "date": date(2026, 1, 2), "adjusted_close": 10.0, "close": 10.0, "volume": float("nan"), "currency": "EUR"}]
                ),
            )

    monkeypatch.setattr(trade_candidate_analysis, "YFinanceProvider", FakeProvider)
    config = SimpleNamespace(targets=SimpleNamespace(base_currency="EUR"))
    data = trade_candidate_analysis.fetch_candidate_prices(
        config, candidate_path=input_path, identifiers=("one", "two"),
    )
    report = trade_candidate_analysis.analyse_candidate_prices(data.candidates, data.prices)
    rows = report.set_index("instrument_id")
    assert set(data.candidates["instrument_id"]) == {"one", "two"}
    assert requested_mapping == {"one": "ONE", "two": "TWO"}
    assert pd.isna(rows.loc["one", "shares"])
    assert pd.isna(rows.loc["one", "trade_value_native"])
    assert pd.isna(rows.loc["one", "median_volume_60d"])
    assert pd.isna(rows.loc["two", "latest_price"])
    assert pd.isna(rows.loc["two", "trade_value_native"])
    assert pd.isna(rows.loc["two", "technical_score"])
    assert rows.loc["two", "blocked_by"] == "missing_price_data"


@pytest.mark.parametrize("session_source", ["active", "fallback"])
@pytest.mark.parametrize("entrypoint", ["score_history", "top_n_selection", "rank_validation_run"])
def test_score_session_rejects_foreign_root_before_read_or_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, session_source: str, entrypoint: str,
) -> None:
    from etf_cockpit.application import score_explain, selection_views

    monkeypatch.setattr(tools_scores, "ROOT", tmp_path / "configured")
    foreign = SimpleNamespace(root=tmp_path / "foreign", snapshot=SimpleNamespace())
    monkeypatch.setattr(tools_scores, "_DEFAULT_SESSION", foreign)
    monkeypatch.setattr(
        tools_scores, "current_call_context",
        lambda: SimpleNamespace(session=foreign if session_source == "active" else None),
    )
    calls = []
    monkeypatch.setattr(score_explain, "load_score_history", lambda *args, **kwargs: calls.append("history"))
    monkeypatch.setattr(selection_views, "load_top_n_selection", lambda *args, **kwargs: calls.append("selection"))
    monkeypatch.setattr(tools_scores, "_job", lambda *args, **kwargs: calls.append("job"))
    with pytest.raises(MCPToolError, match="DATA_ROOT_MISMATCH"):
        getattr(tools_scores, entrypoint)(*(["one"] if entrypoint == "score_history" else []))
    assert calls == []
    assert not foreign.root.exists()


@pytest.mark.parametrize("session_source", ["active", "fallback"])
def test_score_session_accepts_resolved_configured_root(monkeypatch, tmp_path, session_source) -> None:
    monkeypatch.setattr(tools_scores, "ROOT", tmp_path)
    session = SimpleNamespace(root=str(tmp_path / "subdir" / ".."), snapshot=SimpleNamespace())
    monkeypatch.setattr(tools_scores, "_DEFAULT_SESSION", session)
    monkeypatch.setattr(
        tools_scores, "current_call_context",
        lambda: SimpleNamespace(session=session if session_source == "active" else None),
    )
    assert tools_scores._session() is session


def _research_item(source_url="https://example.com/article?topic=earnings"):
    return {
        "subject": "one", "kind": "filing", "claim": "External claim", "stance": 0.5,
        "confidence": 0.8, "source_url": source_url, "source_title": "Filing",
        "published_at": "2025-01-01T00:00:00Z", "retrieved_at": "2025-01-02T00:00:00Z",
    }


@pytest.mark.parametrize("source_url", [
    "https://user:fixture-secret@example.com/article",
    "https://user@example.com/article",
    "https://example.com/article?api_key=fixture-secret",
    "https://example.com/article?%61ccess_token=fixture-secret",
    "https://example.com/article?Password=fixture-secret",
    "https://example.com/article?client_secret=fixture-secret",
    "https://example.com/article?X-Amz-Credential=fixture-secret",
    "https://example.com/article?signature=fixture-secret",
    "https://example.com/article?key=fixture-secret",
])
def test_research_url_credentials_refused_before_preview_and_persistence(monkeypatch, tmp_path, source_url):
    from etf_cockpit.application import research_evidence
    from etf_cockpit.mcp import tools_research

    monkeypatch.setattr(tools_research, "_root", lambda: tmp_path)
    item = _research_item(source_url)
    with pytest.raises(InvalidArgumentsError, match="credentials|credential query") as preview_error:
        tools_research.research_findings(prepare_items=[item])
    with pytest.raises(ValueError, match="credentials|credential query") as persist_error:
        research_evidence.record_research_findings(
            [item], expected_revision=research_evidence.research_revision(tmp_path), root=tmp_path,
        )
    assert "fixture-secret" not in str(preview_error.value)
    assert "fixture-secret" not in str(persist_error.value)
    assert not (tmp_path / "data").exists()


def test_research_legacy_url_credentials_never_returned(tmp_path):
    from etf_cockpit.application import research_evidence
    from etf_cockpit.data.ai_research_evidence import validate_item

    record = validate_item(_research_item())
    record["source_url"] = "https://user:fixture-secret@example.com/article"
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ai_research_evidence.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must not contain credentials"):
        research_evidence.load_research_findings(root=tmp_path)


@pytest.mark.parametrize("kind,expected", [
    ("filing", ["ai-new"]), ("news", ["news-new"]), (None, ["thesis-new", "news-new", "ai-new"]),
])
def test_research_filters_apply_to_all_sources_before_paging(monkeypatch, tmp_path, kind, expected):
    from etf_cockpit.application import research_evidence
    from etf_cockpit.data.ai_research_evidence import validate_item
    from etf_cockpit.mcp import tools_research

    old = "2025-01-02T00:00:00Z"
    recent = "2025-02-02T00:00:00Z"
    ai_old = validate_item(_research_item())
    ai_old["evidence_id"] = "ai-old"
    ai_new = validate_item({**_research_item(), "retrieved_at": recent})
    ai_new["evidence_id"] = "ai-new"
    monkeypatch.setattr(research_evidence, "load_ai_research_evidence", lambda _root: [ai_old, ai_new])
    monkeypatch.setattr(research_evidence, "_load_news", lambda *_args: [
        {"id": "news-old", "kind": "news", "subject": "one", "known_at": old},
        {"id": "news-new", "kind": "news", "subject": "one", "known_at": recent},
        {"id": "news-other", "kind": "news", "subject": "two", "known_at": recent},
    ])
    monkeypatch.setattr(research_evidence, "_load_theses", lambda *_args: [
        *[{"id": f"thesis-old-{i}", "kind": "thesis", "subject": "one", "known_at": old} for i in range(30)],
        {"id": "thesis-new", "kind": "thesis", "subject": "one", "known_at": "2025-02-02T01:00:00+01:00"},
    ])
    monkeypatch.setattr(tools_research, "_root", lambda: tmp_path)
    monkeypatch.setattr(tools_research, "DEFAULT_PAGE_SIZE", 1)
    arguments = dict(subject="one", kind=kind, since="2025-02-01T00:00:00Z", include_news=True, include_theses=True)
    page = tools_research.research_findings(**arguments)
    ids = [item["id"] for item in page["findings"]]
    while page["next_cursor"]:
        page = tools_research.research_findings(**arguments, cursor=page["next_cursor"])
        ids.extend(item["id"] for item in page["findings"])
    assert ids == expected
    assert page["sentiment"]["n"] == (0 if kind == "news" else 1)


def test_candidate_default_uses_verified_stored_evidence_and_network_requires_opt_in(monkeypatch, tmp_path):
    snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=())))
    monkeypatch.setattr(tools_scores, "_snapshot", lambda: (SimpleNamespace(root=tmp_path), snapshot))
    payloads = []

    def execute_job(_root, _kind, _label, payload, handler, **_kwargs):
        payloads.append(payload)
        return {"result": handler(None)}

    monkeypatch.setattr(tools_scores, "_job", execute_job)
    network_calls = []
    monkeypatch.setattr(
        data_service_module.DataService, "run_yfinance_candidate_analysis",
        lambda self, **kwargs: network_calls.append(kwargs) or "explicit network result",
    )
    monkeypatch.setattr(trade_candidate_analysis, "fetch_candidate_fundamentals", lambda *_: pytest.fail("unexpected network fundamentals"))
    monkeypatch.setattr(trade_candidate_analysis, "YFinanceProvider", lambda *_args, **_kwargs: pytest.fail("unexpected network prices"))

    # No stored evidence must return unavailable, without attempting either fetch.
    missing = tools_scores.candidate_analyse(["one"])["result"]
    assert missing["status"] == "unavailable"
    assert network_calls == []
    input_dir = tmp_path / "data" / "raw" / "trade_candidates"
    input_dir.mkdir(parents=True)
    pd.DataFrame([
        {"instrument_id": "one", "yahoo_symbol": "ONE"},
        {"instrument_id": "two", "yahoo_symbol": "TWO"},
        {"instrument_id": "outside", "yahoo_symbol": "OUT"},
    ]).to_csv(input_dir / "yahoo_trade_candidates_fixture.csv", index=False)
    prices = pd.DataFrame([
        {"etf_id": instrument, "date": "2026-01-02", "adjusted_close": 10.0, "close": 10.0, "currency": "EUR"}
        for instrument in ("one", "outside")
    ])
    price_path = tmp_path / "data" / "forecasts" / trade_candidate_analysis.CANDIDATE_PRICE_SNAPSHOT_PATH.name
    binding = trade_candidate_analysis.adjusted_price_snapshot_binding(prices, calculation_window={
        "start_date": "2026-01-02", "end_date": "2026-01-02", "decision_time": "2026-01-02T23:59:59Z",
    })
    assert binding is not None
    trade_candidate_analysis.write_candidate_price_snapshot(prices, binding, path=price_path)
    result = tools_scores.candidate_analyse(["one", "two"], years=2)["result"]
    assert result["status"] == "provisional"
    assert result["classification"] == "provisional_not_ranked"
    assert result["rank_authority"] is result["execution_allowed"] is False
    rows = {row["instrument_id"]: row for row in result["rows"]}
    assert set(rows) == {"one", "two"}
    assert rows["one"]["latest_price"] == 10.0
    assert rows["two"]["latest_price"] is None
    assert rows["two"]["technical_score"] is None
    assert network_calls == []
    # A damaged binding must never be used as local evidence.
    price_path.write_text(price_path.read_text() + "\n", encoding="utf-8")
    assert tools_scores.candidate_analyse(["one"])["result"]["status"] == "unavailable"
    assert network_calls == []
    assert tools_scores.candidate_analyse(["one"], allow_network=True)["result"]["status"] == "provisional"
    assert network_calls == [{"years": 5, "identifiers": ("one",)}]
    assert payloads[0]["allow_network"] is False
    assert payloads[-1]["allow_network"] is True


def test_rank_validation_parallelises_independent_windows_and_replays_in_requested_order(monkeypatch, tmp_path):
    from etf_cockpit.application import rank_validation_service as service

    prices = pd.DataFrame({
        "instrument_id": ["one", "one"], "date": ["2020-01-01", "2026-01-01"],
        "adjusted_close": [10.0, 12.0], "known_at": ["2020-01-01T00:00:00Z", "2026-01-01T00:00:00Z"],
    })
    original = prices.copy(deep=True)
    monkeypatch.setattr(service, "_read_table", lambda path: prices if path and path.name == "prices_daily.parquet" else pd.DataFrame())
    monkeypatch.setattr(service, "_load_membership", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(service, "load_rank_validation_policy", lambda: SimpleNamespace(version="test", holding_period_sessions=20))
    monkeypatch.setattr(service, "window_coverage", lambda _prices, _years: {"sufficient": True})
    monkeypatch.setattr(service, "window_decision_times", lambda _prices, years, **_kwargs: ([years], []))
    monkeypatch.setattr(service, "price_momentum_risk_evidence", lambda _prices, times: (pd.DataFrame({"window": times}), {}))
    monkeypatch.setattr(service, "research_policy", lambda policy, **_kwargs: policy)
    barrier = Barrier(3)
    second_finished = Event()
    lock = Lock()
    state = {"active": 0, "peak": 0}
    completed = []

    def replay(evidence, _memberships, _prices, _costs, _benchmark, _cash, times, *, policy):
        years = int(evidence["window"].iloc[0])
        assert times == [years]
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        if years in (5, 1, 3):
            barrier.wait(timeout=10)
        if years == 5:
            assert second_finished.wait(timeout=10)
        with lock:
            completed.append(years)
            state["active"] -= 1
        if years == 1:
            second_finished.set()
        return years, years

    monkeypatch.setattr(service, "run_stored_rank_validation", replay)
    monkeypatch.setattr(service, "rank_validation_report_dict", lambda replay, validation, **_kwargs: {"window": replay})
    result = service.build_rank_validation_report(root=tmp_path, years=(5, 1, 3, 2))
    assert state["peak"] == 3
    assert completed.index(1) < completed.index(5)
    assert [window["requested_years"] for window in result["windows"]] == [5, 1, 3, 2]
    assert [window["sections"]["price_factors"]["window"] for window in result["windows"]] == [5, 1, 3, 2]
    assert result["parallelism"] == {
        "unit": "requested_year_windows_including_replay", "executor": "thread_pool",
        "max_workers": 3, "output_order": "requested",
    }
    assert result["rank_authority"] is result["execution_allowed"] is False
    pd.testing.assert_frame_equal(prices, original)
