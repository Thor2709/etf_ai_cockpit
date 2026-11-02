from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application import data_service as data_service_module
from etf_cockpit.data import trade_candidate_analysis
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.errors import ConfirmationError, InvalidArgumentsError
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

        def run_yfinance_candidate_analysis(self, **kwargs):
            calls.append(kwargs)
            return "candidate report"

    monkeypatch.setattr(data_service_module, "DataService", FakeDataService)
    monkeypatch.setattr(
        tools_scores, "_job",
        lambda _root, _kind, _label, _payload, handler, **_kwargs: {"result": handler(None)},
    )

    result = tools_scores.candidate_analyse(["outside"], years=2)
    assert result["result"]["classification"] == "provisional_not_ranked"
    assert calls == [{"years": 2, "identifiers": ("outside",)}]
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
