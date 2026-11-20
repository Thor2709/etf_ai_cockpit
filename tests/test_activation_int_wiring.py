"""Activation 2026-11-20: optional INT features reach the pages that the owner uses."""

from __future__ import annotations

from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.analysis.stock_universe import UniverseEvidence
from etf_cockpit.application import stock_views as sv
from tests.test_stock_evidence import CONFIG, DECISION, _evidence, _market, _period

QUALITY_KEYS = (
    "piotroski_f", "altman_z", "beneish_m", "gross_profitability", "accruals",
    "dilution", "sbc_adjusted_fcf", "buyback_yield", "shareholder_yield",
)


def _walk(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", None) or ():
        yield from _walk(child)
    for name in ("content", "body"):
        child = getattr(control, name, None)
        if isinstance(child, (list, tuple)):
            for item in child:
                yield from _walk(item)
        elif child is not None and not isinstance(child, str):
            yield from _walk(child)


def _texts(control) -> str:
    values = []
    for item in _walk(control):
        if isinstance(item, ft.Text) and item.value:
            values.append(str(item.value))
        if isinstance(item, ft.Dropdown):
            values.extend(str(option.text) for option in item.options)
        data = getattr(item, "data", None)
        if isinstance(data, dict) and data.get("title"):
            values.append(str(data["title"]))
    return "\n".join(values)


def test_int04_quality_scores_are_a_number_group_on_the_stock_pages(monkeypatch, tmp_path) -> None:
    from etf_cockpit.app.pages import stock_page as sp
    from etf_cockpit.app.pages import stock_research

    monkeypatch.setattr("etf_cockpit.data.stock_notes.ROOT", tmp_path)
    periods = [_period(year) for year in (2022, 2023, 2024, 2025)]
    universe = UniverseEvidence(
        DECISION, evidence={"T": _evidence(periods=periods, market=_market())}, names={"T": "Test Co"},
        peers={"T": []}, periods={"T": periods}, config=dict(CONFIG),
    )
    monkeypatch.setattr(sv, "snapshot_stock_evidence", lambda _snapshot: universe)
    model = sv.build_stock_page_model(object(), "T", None)

    groups = dict(model.numbers)
    assert [row.key for row in groups["Quality and accounting"]] == list(QUALITY_KEYS)
    assert all(row.available or row.reason for row in groups["Quality and accounting"])
    monkeypatch.setattr(sp, "build_model", lambda *_args: model)
    page = stock_research._stock_statements(SimpleNamespace(snapshot=SimpleNamespace(config=None)), "T", SimpleNamespace(final_label="watchlist"))
    assert "Quality and accounting" in _texts(page)


def test_int09_startup_snapshot_passes_forecast_bridge_inputs(monkeypatch, synthetic_sample_opt_in) -> None:
    from etf_cockpit.application import snapshot_builder

    calls = []
    monkeypatch.setattr(snapshot_builder, "_run_decision_shadow_guard", lambda *args, **kwargs: calls.append(kwargs))
    snapshot_builder.build_snapshot()

    assert calls
    kwargs = calls[-1]
    assert kwargs["forecasts"] is not None and kwargs["forecast_history"] is not None and kwargs["holdings"] is not None
    assert "adjusted_close" in kwargs["price_history"].columns

    def vanished() -> None:
        raise OSError("legacy forecast file removed during the read")

    monkeypatch.setattr(snapshot_builder, "load_forecast_history", vanished)
    snapshot_builder.build_snapshot()
    assert calls[-1]["forecast_history"] is None


def test_int11_optimiser_page_offers_the_skfolio_methods() -> None:
    from etf_cockpit.app.pages.portfolio_optimiser import portfolio_optimiser_page
    from etf_cockpit.core.config import load_config

    dates = pd.date_range("2025-01-01", periods=80)
    prices = pd.DataFrame({
        "date": dates.tolist() * 2,
        "etf_id": ["AAA"] * 80 + ["BBB"] * 80,
        "adjusted_close": [100 + index * 0.1 for index in range(80)] + [90 + index * 0.2 for index in range(80)],
    })
    state = SimpleNamespace(snapshot=SimpleNamespace(config=load_config(), prices=prices), last_message="Ready")
    text = _texts(portfolio_optimiser_page(None, state).body)

    for label in ("skfolio minimum variance", "skfolio minimum CVaR", "skfolio HRP"):
        assert label in text
    from etf_cockpit.application.portfolio_optimiser import METHODS, SKFOLIO_METHODS

    assert f"{len(METHODS) + len(SKFOLIO_METHODS)} transparent methods" in text


def test_int27_chronos2_has_a_model_card_and_a_forecast_lab_row() -> None:
    from etf_cockpit.app.pages import forecast_lab
    from etf_cockpit.models.model_zoo import model_zoo_catalogue, model_zoo_frame

    cards = {card.model_id: card for card in model_zoo_catalogue(optional_status={"chronos2": True})}
    assert cards["chronos2"].state == "available" and cards["chronos2"].licence == "Apache-2.0"
    assert model_zoo_catalogue()[-1].model_id == "chronos2" and model_zoo_catalogue()[-1].state == "unavailable"
    assert "chronos2" in forecast_lab._model_ids(pd.DataFrame(), model_zoo_frame())


def test_int14_robust_risk_reports_a_garch_volatility_forecast() -> None:
    import numpy as np
    import pytest

    from etf_cockpit.portfolio.robust_risk import build_robust_risk_report

    rng = np.random.default_rng(14)
    dates = pd.bdate_range("2024-01-01", periods=300)
    prices = pd.DataFrame({
        "date": list(dates) * 2,
        "etf_id": ["AAA"] * 300 + ["BBB"] * 300,
        "adjusted_close": np.concatenate([100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), 50 * np.exp(np.cumsum(rng.normal(0, 0.015, 300)))]),
    })
    weights = pd.DataFrame({"etf_id": ["AAA", "BBB"], "target_weight": [0.6, 0.4]})

    short = build_robust_risk_report(prices[prices["date"] >= dates[-40]], weights)["volatility_forecast"]
    assert short["status"] == "unavailable" and short["annualised_volatility"] is None and short["reason"]
    for unavailable in (
        build_robust_risk_report(prices, weights.assign(target_weight=0.0)),  # no invested weight: no 0% forecast
        build_robust_risk_report(prices[prices["etf_id"] == "AAA"], weights),  # early unavailable report
    ):
        assert unavailable["volatility_forecast"]["status"] == "unavailable" and unavailable["volatility_forecast"]["reason"]

    pytest.importorskip("arch")
    forecast = build_robust_risk_report(prices, weights)["volatility_forecast"]
    assert forecast["status"] in {"ok", "warning"} and forecast["horizon_sessions"] == 20
    assert 0.0 < forecast["annualised_volatility"] < 1.0
    unheld = pd.DataFrame({"date": list(dates[-10:]), "etf_id": ["CCC"] * 10, "adjusted_close": [10.0 + index for index in range(10)]})
    with_unheld = build_robust_risk_report(
        pd.concat([prices, unheld], ignore_index=True),
        pd.concat([weights, pd.DataFrame({"etf_id": ["CCC"], "target_weight": [0.0]})], ignore_index=True),
    )["volatility_forecast"]
    assert with_unheld["annualised_volatility"] == forecast["annualised_volatility"]


def test_int19_macro_context_carries_the_benchmark_stress_probability() -> None:
    import numpy as np
    import pytest

    from etf_cockpit.features.macro import build_macro_context
    from tests.test_issue_0112_product_review_correction import _available_reference, _available_registry

    pytest.importorskip("statsmodels")
    rng = np.random.default_rng(19)
    dates = pd.bdate_range("2025-01-01", periods=250)
    shocks = np.concatenate([rng.normal(0.0004, 0.005, 150), rng.normal(-0.001, 0.03, 100)])
    prices = pd.DataFrame({
        "date": list(dates) * 2,
        "etf_id": ["BENCH"] * 250 + ["ALT"] * 250,
        "adjusted_close": np.concatenate([100 * np.exp(np.cumsum(shocks)), 50 * np.exp(np.cumsum(rng.normal(0, 0.01, 250)))]),
    })

    stress = build_macro_context(
        prices, benchmark_data_id="BENCH", benchmark_reference=_available_reference(), benchmark_registry=_available_registry(),
    )["stress_probability"]
    assert stress["status"] == "available" and 0.5 < stress["probability"] <= 1.0
    assert stress["execution_allowed"] is False and stress["as_of"].startswith(str(dates[-1].date()))

    stale_prices = prices[(prices["etf_id"] != "BENCH") | (prices["date"] <= dates[-11])]
    stale = build_macro_context(
        stale_prices, benchmark_data_id="BENCH", benchmark_reference=_available_reference(), benchmark_registry=_available_registry(),
    )["stress_probability"]
    assert stale["status"] == "unavailable" and "stale" in stale["reason"]

    no_benchmark = build_macro_context(prices)["stress_probability"]
    assert no_benchmark["status"] == "unavailable" and no_benchmark["reason"]


def test_int22_identity_hints_carry_the_financedatabase_context_for_an_isin(tmp_path) -> None:
    from etf_cockpit.application.identity_views import load_identity_hints
    from etf_cockpit.data.identity_master import IdentityMasterStore

    hint = {
        "hint_id": "financedatabase:2.5.1:abc:etfs/AMS.csv:VWCE.AS:stamp", "source": "financedatabase", "authority": "community",
        "version": "2.5.1", "identifiers": {"isin": "IE00BK5BQT80"},
        "attributes": {"provider_symbol": "VWCE.AS", "name": "Vanguard FTSE All-World", "mic": "XAMS", "currency": "EUR"},
    }
    with IdentityMasterStore(tmp_path) as store:
        store.append_hints([hint])

    assert [row["attributes"]["provider_symbol"] for row in load_identity_hints("IE00BK5BQT80", storage_root=tmp_path)] == ["VWCE.AS"]
    assert load_identity_hints("IE00B4L5Y983", storage_root=tmp_path) == ()
    assert load_identity_hints("", storage_root=tmp_path) == ()
    assert load_identity_hints("IE00BK5BQT80", storage_root=tmp_path / "missing") == ()


def test_int23_imported_pdf_pages_are_searchable_and_exposed_to_mcp(monkeypatch, tmp_path) -> None:
    from etf_cockpit.application import research_evidence
    from etf_cockpit.mcp import tools_research
    from etf_cockpit.mcp.registry import list_tools
    from etf_cockpit.parsers import priips_kid

    pdf = tmp_path / "kid.pdf"
    pdf.write_bytes(b"%PDF fixture")
    monkeypatch.setattr(priips_kid, "_read_pages", lambda _path: (["The total capital ratio is 18 percent."], None))
    assert research_evidence.index_imported_pdf(tmp_path, pdf, source_id="kid:VWCE") == 1
    assert research_evidence.index_imported_pdf(tmp_path, pdf, source_id="kid:VWCE") == 1

    later = "2100-01-01T00:00:00Z"
    assert [hit["source_id"] for hit in research_evidence.search_document_chunks(tmp_path, "capital ratio", as_of=later)["hits"]] == ["kid:VWCE"]
    assert research_evidence.search_document_chunks(tmp_path, "capital ratio", as_of="2000-01-01T00:00:00Z")["hits"] == []
    assert "search_document_chunks" in research_evidence.__all__

    assert "research_document_search" in {spec.name for spec in list_tools(profile="full", tiers="read")}
    monkeypatch.setattr(tools_research, "_root", lambda: tmp_path)
    result = tools_research.research_document_search("capital ratio", later)
    assert result["hits"][0]["untrusted"]["text"].startswith("The total capital") and "text" not in result["hits"][0]
    assert result["execution_allowed"] is False


def test_int26_report_export_needs_local_commentary_and_writes_a_grounded_report(monkeypatch, tmp_path) -> None:
    from pathlib import Path

    from etf_cockpit.app.pages import chatgpt_audit
    from etf_cockpit.application.research_report import export_commentary_report

    state = SimpleNamespace(last_message="", last_export_path=None, local_audit_output=None, recent_activity=[], current_activity=None)
    view = chatgpt_audit.chatgpt_audit_page(SimpleNamespace(update=lambda: None), state)
    next(item for item in _walk(view.body) if getattr(item, "key", None) == "chatgpt.export-report").on_click(None)
    assert "Local model unavailable" in _texts(view.body)

    state.local_audit_report = {"summary": "Risk is concentrated.", "generated_at": "2026-11-20T10:00:00+00:00"}
    calls = []
    monkeypatch.setattr(chatgpt_audit, "export_commentary_report", lambda *args, **kwargs: calls.append(args) or {"status": "written", "path": "r.md"})
    rebuilt = chatgpt_audit.chatgpt_audit_page(SimpleNamespace(update=lambda: None), state)
    next(item for item in _walk(rebuilt.body) if getattr(item, "key", None) == "chatgpt.export-report").on_click(None)
    assert calls == [("Risk is concentrated.", "2026-11-20T10:00:00+00:00")] and "Research report written: r.md" in _texts(rebuilt.body)

    result = export_commentary_report("Risk is concentrated.", "2026-11-20T10:00:00+00:00", root=tmp_path)
    assert result["status"] == "written"
    assert "Risk is concentrated." in Path(result["path"]).read_text(encoding="utf-8")
