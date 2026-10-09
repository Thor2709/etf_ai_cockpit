"""Stock page sections: score first, every gap with its reason, dated notes, peers with counts."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
from types import SimpleNamespace

import pytest

from etf_cockpit.analysis import stock_metrics as sm
from etf_cockpit.analysis import stock_text as tx
from etf_cockpit.analysis.stock_peers import PeerPick
from etf_cockpit.analysis.stock_universe import UniverseEvidence
from etf_cockpit.app.pages import stock_page as sp
from etf_cockpit.application import stock_views as sv
from etf_cockpit.application.stock_views import ComponentRow, NumberRow, PeerRow, StockPageModel
from tests.test_stock_evidence import CONFIG, DECISION, _evidence, _market, _period

UTC = timezone.utc


def _texts(control: object, out: list[str] | None = None) -> list[str]:
    out = [] if out is None else out
    value = getattr(control, "value", None)
    if isinstance(value, str):
        out.append(value)
    for child in getattr(control, "controls", None) or []:
        _texts(child, out)
    content = getattr(control, "content", None)
    if content is not None:
        _texts(content, out)
    return out


def _walk(control: object):
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _by_key(control: object, key: str):
    return next(item for item in _walk(control) if getattr(item, "key", None) == key)


def _model(**overrides: object) -> StockPageModel:
    components = [
        ComponentRow("momentum", "Momentum algorithm", 9.2, 0.5, True, "Momentum +28.0% over 60 days."),
        ComponentRow("relative_strength", "Relative strength algorithm", None, 0.5, False, "no benchmark reference is bound to this snapshot"),
    ]
    base = dict(
        instrument_id="T", name="Test Co", symbol="T", available=True, score=7.4, coverage=0.83, used=1, total=2, label="watchlist",
        headline="Evidence score 7.4 of 10 (strong), built from 1 of 2 components.", sentences=["Profitability: EBIT margin 20.0%."], components=components,
    )
    base.update(overrides)
    return StockPageModel(**base)  # type: ignore[arg-type]


def test_score_card_leads_with_the_ring_and_names_every_missing_component() -> None:
    texts = "\n".join(_texts(sp.score_card(_model())))
    assert "of 10" in texts and "7.4" in texts and "83%" in texts
    assert "no benchmark reference is bound to this snapshot" in texts  # the missing step is named
    assert "None" not in texts and "{" not in texts


def test_no_score_card_says_which_step_is_missing_instead_of_a_number() -> None:
    model = _model(score=None, coverage=None, used=0, total=0, label="", headline="No score: Momentum (no price history).", components=[])
    texts = "\n".join(_texts(sp.score_card(model)))
    assert "Unavailable" in texts and "no price history" in texts and "no score row for this instrument" in texts


def test_unavailable_numbers_show_their_reason_not_a_blank() -> None:
    rows = [
        NumberRow("pe", "P/E", "29.0x", "TTM · 2026-06-30 · yfinance", None, "price / EPS", True),
        NumberRow("implied_growth_pe", "Implied growth (P/E)", "—", "spot", "cost of equity is not configured (configs/stock_fundamentals_v1.yaml)"),
    ]
    texts = "\n".join(_texts(sp.numbers_cards(_model(numbers=[("Valuation", rows)]), ("Valuation",))[0]))
    assert "29.0x" in texts and "cost of equity is not configured" in texts


def test_peer_table_shows_the_median_with_its_count() -> None:
    cells = {key: ("12.0x", None) for key, _ in sv.PEER_COLUMNS}
    model = _model(
        peers=[PeerRow("T", "Test Co", "self", "this stock", cells), PeerRow("P1", "Peer One", "auto", "same industry (X)", cells), PeerRow("", "Peer median (this stock excluded)", "median", "", {k: ("11.0x (n=2)", None) for k, _ in sv.PEER_COLUMNS})],
        peer_summary="1 peers: Peer One (auto).",
    )
    texts = "\n".join(_texts(sp.peers_card(model, config=None)))
    assert "11.0x (n=2)" in texts and "Peer One" in texts and "same industry (X)" in texts


def test_notes_are_dated_stored_locally_and_retractable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr("etf_cockpit.data.stock_notes.ROOT", tmp_path)
    card = sp.notes_card(_model())
    assert "No notes yet" in "\n".join(_texts(card))
    _by_key(card, "stock.notes.input").value = "Waiting for the next quarterly report."
    _by_key(card, "stock.notes.add").on_click(None)
    texts = "\n".join(_texts(card))
    assert "Waiting for the next quarterly report." in texts and str(datetime.now(UTC).year) in texts
    assert (tmp_path / "data" / "notes" / "T.jsonl").exists()
    retract = next(item for item in _walk(card) if str(getattr(item, "key", "")).startswith("stock.notes.retract."))
    retract.on_click(None)
    assert "Waiting for the next quarterly report." not in "\n".join(_texts(card))


def test_page_model_is_built_from_shared_evidence_with_reasons(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr("etf_cockpit.data.stock_notes.ROOT", tmp_path)
    periods = [_period(y) for y in (2022, 2023, 2024, 2025)]
    evidence = _evidence(periods=periods, market=_market())
    universe = UniverseEvidence(
        DECISION, evidence={"T": evidence}, names={"T": "Test Co"}, peers={"T": [PeerPick("P1", "Peer One", 3, ("same industry (X)",), "auto")]}, periods={"T": periods}, config=dict(CONFIG)
    )
    monkeypatch.setattr(sv, "snapshot_stock_evidence", lambda _snapshot: universe)
    component = SimpleNamespace(key="momentum", label="Momentum", score_10=8.0, score_eligible=True, why="Momentum +10%.", source_id="yfinance", freshness_status="ok")
    row = SimpleNamespace(final_score_10=6.5, final_label="watchlist", score_coverage=0.5, components=[component], yahoo_symbol="T", one_line_reason="")
    model = sv.build_stock_page_model(object(), "T", row)
    assert model.available and model.score == 6.5 and model.coverage == 0.5
    assert [c.key for c in model.components][0] == "momentum"
    missing = {c.key: c.why for c in model.components if not c.eligible}
    assert missing and all(reason for reason in missing.values())  # nothing is silently dropped
    unavailable = [r for _t, group in model.numbers for r in group if not r.available]
    assert all(r.reason for r in unavailable)
    assert model.sentences and model.peers[-1].origin == "median"


def test_only_normal_stocks_use_the_stock_page() -> None:
    assert sp.is_normal_stock({"asset_type": "stock", "sector": "Technology"})
    assert not sp.is_normal_stock({"asset_type": "etf", "sector": "Technology"})
    assert not sp.is_normal_stock({"asset_type": "stock", "sector": "Banks"})
    assert not sp.is_normal_stock({"asset_type": "stock", "sector": "Banks"}, SimpleNamespace(final_label="scorecard_owned"))


def test_stock_research_keeps_the_legacy_panels_for_uncovered_instruments(monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.app.pages import stock_research

    state = SimpleNamespace(snapshot=SimpleNamespace(config=None))
    owned = SimpleNamespace(final_label="scorecard_owned")
    assert stock_research._stock_statements(state, "BANK", owned) is None  # bank scorecard owns its page
    monkeypatch.setattr(sp, "build_model", lambda *_a: _model(available=False, unavailable_reason="not a normal stock"))
    assert stock_research._stock_statements(state, "ETF1", SimpleNamespace(final_label="watchlist")) is None
    monkeypatch.setattr(sp, "build_model", lambda *_a: _model(numbers=[("Valuation", [NumberRow("pe", "P/E", "29.0x", "TTM", None, "", True)])]))
    texts = "\n".join(_texts(stock_research._stock_statements(state, "T", SimpleNamespace(final_label="watchlist"))))
    assert "Peer comparison" in texts and "Your notes" in texts and "29.0x" in texts


def test_fiscal_table_uses_the_canonical_fcf_calculation(monkeypatch: pytest.MonkeyPatch) -> None:
    period = _period(2025)
    monkeypatch.setattr(sm, "free_cash_flow", lambda _cfo, _capex: 123.0)
    row = sv._fiscal_rows([period], "EUR")[0]
    assert row["fcf"] == tx.money(123.0, None)


def test_missing_fiscal_cells_and_identity_fields_show_reasons() -> None:
    period = _period(2025)
    missing = replace(period, values={"cfo": 80.0})
    fiscal = sv._fiscal_rows([missing], None)[0]
    assert "revenue is not reported" in fiscal["revenue"] and "needs capital expenditure" in fiscal["fcf"]

    card = sp.identity_card(_model(), {}, [], None)
    rendered = "\n".join(_texts(card))
    assert "listing currency is not recorded" in rendered
    assert "listing region is not recorded" in rendered
    assert "sector is not recorded" in rendered
