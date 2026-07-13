from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.app import router
from etf_cockpit.app.router import PAGES, _page_route, navigate_to
from etf_cockpit.app.pages.instrument_detail import _render_crowding_attribution_panel, _render_evidence_section, instrument_detail_page
from etf_cockpit.app.selectors.instrument_detail import _attribution_panel, _derived_evidence_panel, _etf_disclosure_panel, _feature_driver_panel, _friction_panel, _fundamentals_panel, _instrument_rows, _parsed_panel, _run_changes_panel, _safe_bool, build_instrument_detail
from etf_cockpit.backtest.engine import BacktestReport
from etf_cockpit.app.components.simple_scores import simple_score_grouped_sections
from etf_cockpit.core.config import ETFConfig
from etf_cockpit.services import build_snapshot


REQUIRED_SECTIONS = {
    "identity",
    "price",
    "scores",
    "risk",
    "attribution",
    "fundamentals",
    "etf_disclosures",
    "news",
    "forecasts",
    "backtests",
    "paper_trades",
    "journal",
    "run_changes",
}


def test_instrument_detail_assembles_all_required_sections_and_derived_fields() -> None:
    snapshot = build_snapshot()
    model = build_instrument_detail(snapshot, "VWCE")

    assert REQUIRED_SECTIONS <= set(model.sections)
    assert model.identity["instrument_id"] == "VWCE"
    assert model.sections["price"]["latest_price"] is not None
    assert model.sections["price"]["latest_date"]
    assert model.sections["scores"]["execution_allowed"] is False
    assert "evidence_score" in model.sections["scores"]
    assert "blocked_gates" in model.sections["scores"]
    assert {"momentum", "trend", "relative_strength", "volatility", "drawdown", "liquidity", "cost"} <= set(model.sections["risk"])
    assert {"alpha", "beta", "correlation"} <= set(model.sections["attribution"])


def test_instrument_detail_uses_canonical_id_for_stock_and_sparebanken_rows() -> None:
    snapshot = build_snapshot()
    stock = ETFConfig(
        id="stock-1",
        name="A Display Name",
        ticker="STK.OL",
        role="watchlist",
        instrument_type="stock",
        source_group="Primary tier",
    )
    sparebanken = ETFConfig(
        id="spare-1",
        name="Sparebanken-like certificate",
        ticker="SPARE.OL",
        role="watchlist",
        instrument_type="equity_certificate",
        source_group="Sparebanken",
    )
    config = snapshot.config.model_copy(update={"universe": snapshot.config.universe.model_copy(update={"etfs": [*snapshot.config.universe.etfs, stock, sparebanken]})})
    prices = pd.concat(
        [
            snapshot.prices,
            pd.DataFrame([{"date": "2026-07-13", "etf_id": "stock-1", "adjusted_close": 10.0}, {"date": "2026-07-13", "etf_id": "spare-1", "adjusted_close": 20.0}]),
        ],
        ignore_index=True,
    )
    custom = replace(snapshot, config=config, prices=prices)

    stock_model = build_instrument_detail(custom, "stock-1")
    spare_model = build_instrument_detail(custom, "spare-1")
    assert stock_model.identity["instrument_id"] == "stock-1"
    assert stock_model.identity["asset_type"] == "stock"
    assert spare_model.identity["instrument_id"] == "spare-1"
    assert spare_model.identity["group"] == "Sparebanken"
    assert spare_model.identity["asset_type"] == "equity_certificate"


def test_instrument_detail_missing_or_corrupt_optional_stores_are_explicitly_unavailable(tmp_path, monkeypatch) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector

    snapshot = build_snapshot()
    for name in ("FEATURE_DRIVERS_PATH", "SCOREBOARD_PATH", "FUNDAMENTAL_CLEAN_PATH", "NEWS_CLEAN_PATH", "FUND_HOLDINGS_PATH"):
        path = tmp_path / f"{name}.parquet"
        path.write_bytes(b"not parquet")
        monkeypatch.setattr(selector, name, path)

    model = build_instrument_detail(snapshot, "VWCE")
    for key in ("fundamentals", "news", "etf_disclosures"):
        assert model.sections[key]["status"] == "unavailable"
    assert model.sections["scores"]["execution_allowed"] is False
    assert model.sections["paper_trades"]["status"] == "unavailable"
    assert model.sections["journal"]["status"] == "unavailable"


def test_instrument_detail_route_and_legacy_etf_compatibility(monkeypatch) -> None:
    instrument_detail_route = getattr(router, "instrument_detail_route", None)
    assert callable(instrument_detail_route)
    assert instrument_detail_route("VWCE") == "/instrument/VWCE"
    assert _page_route("/instrument/VWCE") == "/instrument"
    assert PAGES["/etf"][0] == "Instrument Detail"

    class Page:
        route = "/"

        def go(self, route: str) -> None:
            self.route = route

    page = Page()
    state = type("State", (), {"selected_etf": "VWCE", "snapshot": build_snapshot(), "last_message": "Ready"})()
    monkeypatch.setattr(router, "render_shell", lambda *_args: None)
    navigate_to(page, state, "/instrument/VWCE")
    assert page.route == "/instrument/VWCE"
    assert state.selected_etf == "VWCE"


def test_score_row_exposes_keyboard_operable_instrument_detail_action(monkeypatch) -> None:
    from etf_cockpit.signals.simple_scores import build_simple_instrument_scores

    snapshot = build_snapshot()
    state = type("State", (), {"selected_etf": "VWCE", "snapshot": snapshot})()
    page = type("Page", (), {"route": "/"})()
    monkeypatch.setattr(router, "render_shell", lambda *_args: None)
    scores = build_simple_instrument_scores(snapshot.config, [], pd.DataFrame(), pd.DataFrame())
    control = simple_score_grouped_sections([next(score for score in scores if score.display_id == "VWCE")], page=page, state=state)

    def walk(node):
        yield node
        for child in getattr(node, "controls", []) or []:
            yield from walk(child)
        content = getattr(node, "content", None)
        if content is not None:
            yield from walk(content)

    button = next(item for item in walk(control) if getattr(item, "key", "") == "dashboard.score-row-detail.VWCE")
    button.on_click(None)
    assert page.route == "/instrument/VWCE"
    assert state.selected_etf == "VWCE"


def _text_values(control: object) -> list[str]:
    values: list[str] = []
    value = getattr(control, "value", None)
    if value is not None:
        values.append(str(value))
    for child in getattr(control, "controls", []) or []:
        values.extend(_text_values(child))
    content = getattr(control, "content", None)
    if content is not None:
        values.extend(_text_values(content))
    for row in getattr(control, "rows", []) or []:
        for cell in getattr(row, "cells", []) or []:
            values.extend(_text_values(getattr(cell, "content", None)))
    return values


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_instrument_detail_renders_scoped_records_for_etf_panels() -> None:
    snapshot = build_snapshot()
    instrument_id = "VWCE"
    history = pd.DataFrame(
        [
            {"instrument_id": instrument_id, "run_id": "previous", "final_combined_score_10": 4.0, "final_action": "no_trade"},
            {"instrument_id": instrument_id, "run_id": "current", "final_combined_score_10": 7.0, "final_action": "buy"},
        ]
    )
    custom = replace(
        snapshot,
        forecasts=pd.DataFrame([{"etf_id": instrument_id, "forecast_id": "forecast-etf-1", "status": "ok"}]),
        backtest=BacktestReport(
            results=pd.DataFrame(),
            equity_curves=pd.DataFrame(),
            trade_log=pd.DataFrame([{"etf_id": instrument_id, "trade_id": "backtest-trade-etf-1", "return": 0.12}]),
            signal_log=pd.DataFrame([{"etf_id": instrument_id, "signal_id": "backtest-signal-etf-1", "action": "buy"}]),
            ai_added_value=False,
        ),
    )
    model = build_instrument_detail(
        custom,
        instrument_id,
        paper_trades=pd.DataFrame([{"instrument_id": instrument_id, "paper_trade_id": "paper-etf-1", "status": "open"}]),
        journal=pd.DataFrame([{"instrument_id": instrument_id, "journal_id": "journal-etf-1", "thesis": "ETF thesis"}]),
        score_history=history,
    )

    rendered = "\n".join(
        value
        for key in ("price", "forecasts", "backtests", "paper_trades", "journal", "run_changes")
        for value in _text_values(_render_evidence_section(key, model.sections[key]))
    )
    assert "forecast-etf-1" in rendered
    assert "backtest-signal-etf-1" in rendered
    assert "backtest-trade-etf-1" in rendered
    assert "paper-etf-1" in rendered
    assert "journal-etf-1" in rendered
    assert "current" in rendered


def test_instrument_detail_renders_scoped_records_for_stock() -> None:
    snapshot = build_snapshot()
    stock = ETFConfig(id="stock-render", name="Rendered Stock", ticker="STK.OL", instrument_type="stock", role="watchlist")
    config = snapshot.config.model_copy(update={"universe": snapshot.config.universe.model_copy(update={"etfs": [*snapshot.config.universe.etfs, stock]})})
    custom = replace(
        snapshot,
        config=config,
        prices=pd.concat([snapshot.prices, pd.DataFrame([{"etf_id": "stock-render", "date": "2026-07-13", "adjusted_close": 123.45}])], ignore_index=True),
        forecasts=pd.DataFrame([{"etf_id": "stock-render", "forecast_id": "forecast-stock-1", "status": "ok"}]),
    )
    model = build_instrument_detail(custom, "stock-render", paper_trades=pd.DataFrame([{"instrument_id": "stock-render", "paper_trade_id": "paper-stock-1"}]))
    rendered = "\n".join(_text_values(_render_evidence_section("Price history", model.sections["price"])))
    rendered += "\n".join(_text_values(_render_evidence_section("Forecast evidence", model.sections["forecasts"])))
    rendered += "\n".join(_text_values(_render_evidence_section("Paper-trade history", model.sections["paper_trades"])))
    assert "123.45" in rendered
    assert "forecast-stock-1" in rendered
    assert "paper-stock-1" in rendered


def test_etf_disclosures_reject_idless_registry_and_holdings() -> None:
    snapshot = build_snapshot()
    model = build_instrument_detail(
        snapshot,
        "VWCE",
        document_registry=pd.DataFrame({"document_type": ["factsheet"], "coverage_status": ["available"]}),
        holdings=pd.DataFrame({"holding_symbol": ["FOREIGN"], "weight": [1.0]}),
    )
    panel = model.sections["etf_disclosures"]
    assert panel["status"] in {"unavailable", "manual_review"}
    assert panel["manual_review"] is True
    assert panel["document_inventory"] == []
    assert panel["holdings"]["status"] in {"unavailable", "manual_review"}
    assert panel["holdings"]["rows"] == []


def test_etf_disclosures_do_not_use_foreign_ids() -> None:
    snapshot = build_snapshot()
    model = build_instrument_detail(
        snapshot,
        "VWCE",
        document_registry=pd.DataFrame({"etf_id": ["OTHER"], "document_type": ["factsheet"], "coverage_status": ["available"]}),
        holdings=pd.DataFrame({"etf_id": ["OTHER"], "holding_symbol": ["FOREIGN"], "weight": [1.0]}),
    )
    panel = model.sections["etf_disclosures"]
    assert all(row.get("coverage_status") != "available" for row in panel["document_inventory"])
    assert all(row.get("source") != "OTHER" for row in panel["document_inventory"])
    assert panel["holdings"]["status"] in {"unavailable", "manual_review"}
    assert panel["holdings"]["rows"] == []


def test_etf_disclosures_reject_contradictory_supported_ids() -> None:
    panel = _etf_disclosure_panel(
        "VWCE",
        document_registry=pd.DataFrame(
            {
                "instrument_id": ["VWCE"],
                "etf_id": ["OTHER"],
                "document_type": ["factsheet"],
                "coverage_status": ["available"],
            }
        ),
        holdings=pd.DataFrame(
            {
                "instrument_id": ["VWCE"],
                "etf_id": ["OTHER"],
                "as_of": ["2026-07-10"],
            }
        ),
    )

    assert panel["status"] == "manual_review"
    assert panel["manual_review"] is True
    assert panel["document_inventory"] == []
    assert panel["holdings"]["status"] == "manual_review"
    assert panel["holdings"]["rows"] == []


def test_etf_disclosures_nullable_holdings_metadata_fail_closed() -> None:
    panel = _etf_disclosure_panel(
        "VWCE",
        document_registry=pd.DataFrame(),
        holdings=pd.DataFrame(
            {
                "instrument_id": ["VWCE"],
                "as_of": [pd.NA],
                "as_of_date": [pd.NA],
                "completeness": [pd.NA],
                "freshness": [pd.NA],
                "confidence": [pd.NA],
                "source": [pd.NA],
                "authority": [pd.NA],
                "score_eligible": [pd.NA],
            }
        ),
    )

    assert panel["holdings"]["status"] == "manual_review"
    assert panel["holdings"]["manual_review"] is True
    assert panel["holdings"]["as_of"] == "unavailable"
    assert panel["holdings"]["rows"] == []


def test_instrument_rows_reject_foreign_and_contradictory_supported_ids_with_nullable_values() -> None:
    frame = pd.DataFrame(
        {
            "row_id": ["single-instrument", "single-etf", "both-target", "contradictory", "foreign-only", "idless"],
            "instrument_id": ["VWCE", pd.NA, "VWCE", "VWCE", "OTHER", pd.NA],
            "etf_id": [pd.NA, "VWCE", "VWCE", "OTHER", pd.NA, pd.NA],
            "display_id": [pd.NA, pd.NA, pd.NA, pd.NA, pd.NA, pd.NA],
        }
    )

    rows = _instrument_rows(frame, "VWCE", columns=("instrument_id", "etf_id", "display_id"))

    assert rows["row_id"].tolist() == ["single-instrument", "single-etf", "both-target"]


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        ("kid", ("product", "isin")),
        ("methodology", ("provider", "version")),
    ],
)
def test_parsed_panel_nullable_flags_fail_closed_for_kid_and_methodology(kind: str, fields: tuple[str, ...]) -> None:
    frame = pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "success": [pd.NA],
            "manual_review": [pd.NA],
            "score_eligible": [pd.NA],
            "imported_at": ["2026-07-10"],
        }
    )

    panel = _parsed_panel(frame, "VWCE", kind, fields)

    assert panel["status"] == "manual_review"
    assert panel["manual_review"] is True
    assert panel["score_eligible"] is False


def test_parsed_panel_rejects_contradictory_supported_ids() -> None:
    frame = pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "etf_id": ["OTHER"],
            "success": [True],
            "manual_review": [False],
            "score_eligible": [True],
            "imported_at": ["2026-07-10"],
        }
    )

    panel = _parsed_panel(frame, "VWCE", "kid", ("product",))

    assert panel["status"] == "unavailable"
    assert panel["manual_review"] is True
    assert panel["score_eligible"] is False


def test_derived_panels_reject_contradictory_supported_ids(monkeypatch, tmp_path) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector

    feature_path = tmp_path / "feature_drivers.parquet"
    scoreboard_path = tmp_path / "scoreboard.parquet"
    correlation_path = tmp_path / "correlation_clusters.parquet"
    attribution_path = tmp_path / "benchmark_attribution.parquet"
    pd.DataFrame(
        [{"instrument_id": "VWCE", "etf_id": "OTHER", "component": "foreign", "normalised_score": 9.0}]
    ).to_parquet(feature_path)
    pd.DataFrame(
        [{"display_id": "VWCE", "instrument_id": "VWCE", "etf_id": "OTHER", "gross_expected_edge_bps": 12.0}]
    ).to_parquet(scoreboard_path)
    pd.DataFrame([{"instrument_id": "VWCE", "etf_id": "OTHER", "status": "available"}]).to_parquet(correlation_path)
    pd.DataFrame([{"instrument_id": "VWCE", "etf_id": "OTHER", "status": "available"}]).to_parquet(attribution_path)
    monkeypatch.setattr(selector, "FEATURE_DRIVERS_PATH", feature_path)
    monkeypatch.setattr(selector, "SCOREBOARD_PATH", scoreboard_path)
    monkeypatch.setattr(selector, "CORRELATION_CLUSTERS_PATH", correlation_path)
    monkeypatch.setattr(selector, "BENCHMARK_ATTRIBUTION_PATH", attribution_path)

    assert _feature_driver_panel("VWCE")["status"] == "unavailable"
    assert _friction_panel("VWCE")["status"] == "unavailable"
    derived = _derived_evidence_panel("VWCE")
    assert derived["crowding"]["status"] == "unavailable"
    assert derived["attribution"]["status"] == "unavailable"
    history = pd.DataFrame(
        [
            {"instrument_id": "VWCE", "etf_id": "OTHER", "run_id": "previous", "final_action": "no_trade"},
            {"instrument_id": "VWCE", "etf_id": "OTHER", "run_id": "current", "final_action": "buy"},
        ]
    )
    assert _run_changes_panel("VWCE", history)["status"] == "unavailable"


def test_attribution_alpha_fallback_never_uses_sector_alpha() -> None:
    panel = _attribution_panel(
        {"attribution": {"alpha_proxy": 0.11, "sector_alpha_proxy": 0.42, "status": "available"}},
        {"sector_alpha_proxy": 0.42},
    )
    assert panel["alpha"] == 0.11
    assert panel["sector_alpha_proxy"] == 0.42


def test_safe_bool_accepts_numpy_and_pandas_boolean_scalars_but_fail_closes_malformed_values() -> None:
    pandas_boolean = pd.array([True], dtype="boolean")[0]

    assert _safe_bool(np.bool_(True)) is True
    assert _safe_bool(pandas_boolean) is True
    assert _safe_bool(np.bool_(False), default=True) is False
    assert _safe_bool(pd.NA, default=True) is True
    assert _safe_bool("not-a-boolean", default=True) is True


def test_parsed_panel_keeps_valid_numpy_boolean_rows_available_and_eligible() -> None:
    frame = pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "success": pd.array([True], dtype="boolean"),
            "manual_review": pd.array([False], dtype="boolean"),
            "score_eligible": pd.array([True], dtype="boolean"),
            "freshness_status": ["fresh"],
            "imported_at": ["2026-07-10"],
        }
    )

    panel = _parsed_panel(frame, "VWCE", "kid", ("product",))

    assert panel["status"] == "available"
    assert panel["manual_review"] is False
    assert panel["score_eligible"] is True


def test_instrument_rows_rejects_contradictory_display_id_by_default() -> None:
    frame = pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "display_id": ["OTHER"],
            "value": [1.0],
        }
    )

    assert _instrument_rows(frame, "VWCE").empty


def test_fundamentals_panel_fails_closed_for_nullable_score_eligibility() -> None:
    panel = _fundamentals_panel(
        "VWCE",
        pd.DataFrame(
            {
                "instrument_id": ["VWCE"],
                "as_of_date": ["2026-07-10"],
                "eligibility": ["eligible"],
                "score_eligible": pd.array([pd.NA], dtype="boolean"),
            }
        ),
    )

    assert panel["status"] == "manual_review"
    assert panel["score_eligible"] is False


def test_crowding_attribution_renders_canonical_broad_alpha_value() -> None:
    control = _render_crowding_attribution_panel(
        {
            "scores": {"crowding": {}, "friction": {}},
            "attribution": {
                "alpha": 0.11,
                "sector_alpha_proxy": 0.42,
                "status": "available",
            },
        }
    )

    assert "alpha 0.11" in "\n".join(_text_values(control))


def test_instrument_detail_exposes_functional_export_control_and_disabled_state() -> None:
    snapshot = build_snapshot()
    calls: list[bool] = []

    def export_audit_packet() -> str:
        calls.append(True)
        return "exports/instrument-detail.zip"

    state = type(
        "State",
        (),
        {
            "snapshot": snapshot,
            "selected_etf": "VWCE",
            "last_export_path": None,
            "last_message": "Ready",
            "export_audit_packet": staticmethod(export_audit_packet),
        },
    )()
    control = instrument_detail_page(None, state)
    export = next(item for item in _walk(control) if getattr(item, "key", "") == "instrument-detail.export-evidence")

    assert export.disabled is False
    export.on_click(None)
    assert calls == [True]

    unavailable_state = type("State", (), {"snapshot": snapshot, "selected_etf": "missing", "last_export_path": None, "last_message": "Ready"})()
    unavailable = instrument_detail_page(None, unavailable_state)
    disabled_export = next(item for item in _walk(unavailable) if getattr(item, "key", "") == "instrument-detail.export-evidence")
    assert disabled_export.disabled is True
    assert "unavailable" in "\n".join(_text_values(unavailable)).casefold()


def test_evidence_sections_render_source_authority_and_conflict_badges() -> None:
    control = _render_evidence_section(
        "Evidence",
        {
            "source_id": "provider:alpha",
            "source_authority": "official",
            "conflict_id": "conflict-1",
        },
    )
    rendered = "\n".join(_text_values(control))

    assert "Source ID" in rendered
    assert "provider:alpha" in rendered
    assert "Authority" in rendered
    assert "official" in rendered
    assert "Conflict" in rendered
    assert "conflict-1" in rendered
