from __future__ import annotations

from dataclasses import replace

import pandas as pd

from etf_cockpit.app import router
from etf_cockpit.app.router import PAGES, _page_route, navigate_to
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
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
