"""Bug-hunt batch T-UIB (docs/development/BUGFIX-PLAN-2026-10-10.md, P07)."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


class _Page:
    services: list = []
    overlay: list = []

    def update(self, *_args, **_kwargs) -> None:
        pass


def _walk(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    for child in getattr(control, "items", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _find(root, key):
    for item in _walk(root):
        if getattr(item, "key", None) == key:
            return item
    raise AssertionError(f"no control with key {key}")


def _texts(root) -> list[str]:
    return [str(item.value) for item in _walk(root) if isinstance(item, ft.Text) and item.value]


def _click_segment(root, value) -> None:
    for item in _walk(root):
        data = getattr(item, "data", None)
        if isinstance(data, dict) and data.get("kit") == "Segment" and data.get("value") == value:
            item.on_click(None)
            return
    raise AssertionError(f"no segment {value}")


def _pick(root, label) -> None:
    for item in _walk(root):
        if isinstance(item, ft.PopupMenuItem) and getattr(item.content, "value", None) == label:
            item.on_click(None)
            return
    raise AssertionError(f"no menu item {label}")


def _state():
    snapshot = build_snapshot()
    return AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)


# ---------------------------------------------------------------------------
# P07-N001 / N002 import_export
# ---------------------------------------------------------------------------


def _import_page(monkeypatch=None):
    from etf_cockpit.app.pages.import_export import import_export_page

    return import_export_page(_Page(), _state())


def test_p07_n001(monkeypatch) -> None:
    from etf_cockpit.application.portfolio_imports import PortfolioImportApplication

    calls: list[str] = []
    monkeypatch.setattr(PortfolioImportApplication, "rollback", lambda _s, batch, reason="": calls.append(batch))
    view = _import_page()
    batch = _find(view.body, "import-export.portfolio-rollback-batch")
    button = _find(view.body, "import-export.portfolio-rollback")
    batch.value = "A"
    button.on_click(None)
    batch.value = "B"
    button.on_click(None)
    assert calls == []
    button.on_click(None)
    assert calls == ["B"]


def test_p07_n002(monkeypatch) -> None:
    import etf_cockpit.app.pages.import_export as module

    class _Picker:
        def __init__(self, *args, **kwargs) -> None:
            self.key = kwargs.get("key")

        async def pick_files(self, **_kwargs):
            return [SimpleNamespace(path="x.csv", name="x.csv", bytes=None)]

    monkeypatch.setattr(module.ft, "FilePicker", _Picker)
    monkeypatch.setattr(
        module,
        "validate_import",
        lambda *_a, **_k: SimpleNamespace(valid=True, rows=1, errors=(), import_type="broker", frame=pd.DataFrame(), preview_id="p"),
    )
    handlers: dict[str, object] = {}
    real_primary = module.Button.primary

    def spy(text, *args, **kwargs):
        handlers[kwargs.get("key")] = kwargs.get("on_click")
        return real_primary(text, *args, **kwargs)

    monkeypatch.setattr(module.Button, "primary", staticmethod(spy))
    view = _import_page()
    _pick(view.body, "Broker")
    asyncio.run(handlers["import-export.import"](None))
    assert _find(view.body, "import-export.commit").data["disabled"] is False
    _click_segment(view.body, "1.234,56")
    assert _find(view.body, "import-export.commit").data["disabled"] is True


# ---------------------------------------------------------------------------
# P07-N003 / N004 stress_lab
# ---------------------------------------------------------------------------


def _field_input(root, key) -> ft.TextField:
    return next(item for item in _walk(_find(root, key)) if isinstance(item, ft.TextField))


def _stress_view(monkeypatch, *, saved=None, recorder=None):
    from etf_cockpit.app.pages.stress_lab import stress_lab_page
    from etf_cockpit.application.stress_lab import StressLabFacade
    from etf_cockpit.core.config import load_config

    monkeypatch.setattr(StressLabFacade, "list_saved", lambda _self: ())
    if saved is not None:
        monkeypatch.setattr(StressLabFacade, "load", lambda _self, scenario_id: saved[scenario_id])
    if recorder is not None:
        def fake_save(_self, scenario, *, expected_revision=0):
            recorder.append((scenario.scenario_id, expected_revision))
            return SimpleNamespace(revision=expected_revision + 1)

        monkeypatch.setattr(StressLabFacade, "save", fake_save)
    snapshot = SimpleNamespace(
        config=load_config(),
        holdings=pd.DataFrame({"etf_id": ["AAA"], "current_weight": [1.0], "asset_class": ["equity"]}),
        prices=pd.DataFrame(),
        latest_features=pd.DataFrame(),
    )
    return stress_lab_page(None, SimpleNamespace(snapshot=snapshot))


def _saved(scenario_id, revision, **shocks):
    return SimpleNamespace(
        scenario=SimpleNamespace(scenario_id=scenario_id, name=scenario_id, historical_date=None, shocks=shocks),
        revision=revision,
    )


def test_p07_n003(monkeypatch) -> None:
    view = _stress_view(monkeypatch, saved={"R": _saved("R", 1, rates=-0.02)})
    _field_input(view.body, "stress-lab.equity").value = "-30"
    _field_input(view.body, "stress-lab.scenario-id").value = "R"
    _find(view.body, "stress-lab.load").on_click(None)
    assert _field_input(view.body, "stress-lab.equity").value == ""
    assert _field_input(view.body, "stress-lab.rates").value == "-2.00"


def test_p07_n004(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    view = _stress_view(monkeypatch, saved={"A": _saved("A", 4, equity=-0.1)}, recorder=calls)
    _field_input(view.body, "stress-lab.scenario-id").value = "A"
    _find(view.body, "stress-lab.load").on_click(None)
    _field_input(view.body, "stress-lab.scenario-id").value = "B"
    _field_input(view.body, "stress-lab.name").value = "B"
    _find(view.body, "stress-lab.save").on_click(None)
    assert calls == [("B", 0)]


# ---------------------------------------------------------------------------
# P07-N005 / N006 / N007 jobs
# ---------------------------------------------------------------------------


class _FakeJobsApi:
    def __init__(self, *, rows=(), total=None, next_offset=None, readable=(True, None), cancel_status="accepted") -> None:
        self.rows = tuple(rows)
        self.total = len(self.rows) if total is None else total
        self.next_offset = next_offset
        self.readable = readable
        self.cancel_status = cancel_status

    def jobs_store_status(self):
        return self.readable

    def recover_expired_leases(self):
        return ()

    def get_jobs(self, _page):
        return SimpleNamespace(items=self.rows, total=self.total, next_offset=self.next_offset)

    def execute(self, _command):
        return SimpleNamespace(status=SimpleNamespace(value=self.cancel_status), error_message=None)


def _workflow(workflow_id, status="running"):
    return SimpleNamespace(
        workflow_id=workflow_id, label=f"wf {workflow_id}", status=status, created_at=None, finished_at=None,
        job_count=1, active=status == "running", hash_chain_valid=True, error_message=None,
    )


def _jobs_view(api):
    from etf_cockpit.app.pages.jobs import jobs_page

    state = _state()
    state.application_api = api
    return jobs_page(_Page(), state), state


def test_p07_n005() -> None:
    api = _FakeJobsApi(rows=[_workflow("w1")])
    view, _ = _jobs_view(api)
    assert any("refreshed" in text for text in _texts(view.body))
    api.readable = (False, "OSError: the local job store could not be read")
    api.rows = ()
    view, _ = _jobs_view(api)
    joined = "\n".join(_texts(view.body))
    assert "Job store unavailable: OSError" in joined
    assert "refreshed from the local job store" not in joined


def test_p07_n006() -> None:
    from etf_cockpit.application.contracts import ApiStatus

    api = _FakeJobsApi(rows=[_workflow("w1")])
    api.execute = lambda _c: SimpleNamespace(status=ApiStatus.ACCEPTED, error_message=None)
    view, _ = _jobs_view(api)
    _find(view.body, "jobs.cancel.w1").on_click(None)
    assert "Workflow cancellation was recorded." in _texts(view.body)
    api.execute = lambda _c: SimpleNamespace(status=ApiStatus.FAILED, error_message="no")
    _find(view.body, "jobs.cancel.w1").on_click(None)
    assert "Workflow cancellation did not complete." in _texts(view.body)


def test_p07_n007() -> None:
    api = _FakeJobsApi(rows=[_workflow("w1")], total=101, next_offset=100)
    view, _ = _jobs_view(api)
    joined = "\n".join(_texts(view.body))
    assert "1 of 101" in joined
    assert "more workflows exist" in joined


# ---------------------------------------------------------------------------
# P07-N008 news_context
# ---------------------------------------------------------------------------


def _segment_group_change(view, name, value) -> None:
    group = next(g for g in view.chrome.segment_groups if g.key == name)
    group.on_change(value)


def _table_rows(root, title) -> int:
    card = next(
        item
        for item in _walk(root)
        if isinstance(getattr(item, "data", None), dict) and item.data.get("kit") == "GlassCard" and item.data.get("title") == title
    )
    tables = [item for item in _walk(card) if isinstance(getattr(item, "data", None), dict) and item.data.get("kit") == "DataTable"]
    return tables[0].data.get("rows", 0) if tables else 0


def test_p07_n008(monkeypatch) -> None:
    from etf_cockpit.app.pages import news_context

    frame = pd.DataFrame(
        {
            "published_at": ["2026-01-01T00:00:00Z"] * 3,
            "instrument_id": ["A", "B", "C"],
            "title": ["t1", "t2", "t3"],
            "headline": ["Shares rally", "Shares drop", "Quiet day"],
        }
    )
    monkeypatch.setattr(news_context, "read_frame", lambda _path: frame)
    view = news_context.news_context_page(_Page(), _state())
    counts = {}
    for segment in ("All", "Positive", "Negative"):
        _segment_group_change(view, "news_filter", segment)
        counts[segment] = _table_rows(view.body, "News/context inventory")
    assert counts == {"All": 3, "Positive": 1, "Negative": 1}
    _segment_group_change(view, "news_filter", "Contradictions")
    card = next(i for i in _walk(view.body) if isinstance(getattr(i, "data", None), dict) and i.data.get("title") == "News/macro contradictions")
    inventory = next(i for i in _walk(view.body) if isinstance(getattr(i, "data", None), dict) and i.data.get("title") == "News/context inventory")
    assert card.visible is True and inventory.visible is False


# ---------------------------------------------------------------------------
# P07-N009 macro_factors
# ---------------------------------------------------------------------------


def test_p07_n009(monkeypatch) -> None:
    from etf_cockpit.app.pages import macro_factors
    from etf_cockpit.data.macro_warehouse import MacroObservation

    observations = [
        MacroObservation(
            dataset_id="d", series_id="S", period_start=f"{year}-{month:02d}-01", value=1.0, unit="pct",
            frequency="monthly", country="US", currency="USD", source_id="f.csv",
            source_authority="official_public_file", source_checksum="a" * 64,
            published_at="2026-02-01T00:00:00Z", available_at="2026-02-01T00:00:00Z",
            observed_at="2026-01-01T00:00:00Z", ingested_at="2026-02-02T00:00:00Z",
        )
        for year in range(2021, 2027)
        for month in range(1, 13)
        if (year, month) <= (2026, 1)
    ]
    binding = SimpleNamespace(
        summary={}, observations=observations, curve_coverage={}, context={}, scenario={}, decision_time="x", error=None
    )
    monkeypatch.setattr(macro_factors, "build_macro_context_binding", lambda *_a, **_k: binding)
    monkeypatch.setattr(
        macro_factors, "context_from_snapshot",
        lambda *_a, **_k: SimpleNamespace(benchmark_data_id=None, projection=None, registry=None),
    )
    real_line_chart = macro_factors.ck.line_chart
    spans: list[tuple[str, str]] = []

    def spy(x, series, **kwargs):
        if x:
            spans.append((min(x), max(x)))
        return real_line_chart(x, series, **kwargs)

    monkeypatch.setattr(macro_factors.ck, "line_chart", spy)
    state = SimpleNamespace(snapshot=SimpleNamespace(universe_revision="r"))
    view = macro_factors.macro_factors_page(None, state)
    spans.clear()
    _segment_group_change(view, "macro_horizon", "3M")
    assert spans == [("2025-10-01", "2026-01-01")]
    spans.clear()
    _segment_group_change(view, "macro_horizon", "5Y")
    assert spans == [("2021-01-01", "2026-01-01")]


# ---------------------------------------------------------------------------
# P07-N010 etf_disclosures / filings
# ---------------------------------------------------------------------------


def _visible_keys(view, keys) -> set[str]:
    out = set()
    for key in keys:
        control = _find(view.body, key)
        if control.visible is not False:
            out.add(key)
    return out


def test_p07_n010() -> None:
    from etf_cockpit.app.pages.etf_disclosures import etf_disclosures_page
    from etf_cockpit.app.pages.filings import filings_page

    view = etf_disclosures_page(_Page(), _state())
    keys = ("etf-disclosures.inventory", "disclosures.sfdr", "etf-disclosures.evidence")
    seen = {}
    for segment in ("Documents", "Reports", "Holdings", "SFDR"):
        _segment_group_change(view, "disclosure_view", segment)
        seen[segment] = _visible_keys(view, keys)
    assert seen == {
        "Documents": {"etf-disclosures.inventory"},
        "Reports": {"etf-disclosures.evidence"},
        "Holdings": {"etf-disclosures.evidence"},
        "SFDR": {"disclosures.sfdr"},
    }
    view = filings_page(_Page(), _state())
    keys = ("filings.inventory", "filings.evidence")
    seen = {}
    for segment in ("SEC", "ESEF", "National OAM", "Manual"):
        _segment_group_change(view, "filing_source", segment)
        seen[segment] = _visible_keys(view, keys)
    assert seen == {
        "SEC": {"filings.inventory"},
        "ESEF": set(),
        "National OAM": {"filings.evidence"},
        "Manual": set(),
    }


# ---------------------------------------------------------------------------
# P07-N012 plugin registry
# ---------------------------------------------------------------------------


def test_p07_n012() -> None:
    from etf_cockpit.plugins.contracts import PluginHealth, PluginManifest, PluginResult, PluginStatus
    from etf_cockpit.plugins.registry import PluginRegistry

    class _Plugin:
        manifest = PluginManifest(
            plugin_id="fixture.n012", version="1.0.0", kind="provider", capabilities=("health", "import"),
            licence="Project-local", authority="evidence_only",
        )

        def __init__(self) -> None:
            self.calls: list[str] = []

        def health(self, _context):
            return PluginHealth(status=PluginStatus.AVAILABLE, message="ok")

        def hidden(self, _payload, _context):
            self.calls.append("hidden")
            return PluginResult(status="ok", message="hidden")

        def import_data(self, _payload, _context):
            self.calls.append("import_data")
            return PluginResult(status="ok", message="imported")

    plugin = _Plugin()
    registry = PluginRegistry(allowlist={"fixture.n012": "1.0.0"})
    registry.register(plugin)
    assert registry.invoke("fixture.n012", "hidden", {}).status == "unsupported"
    assert registry.invoke("fixture.n012", "import", {}).status == "ok"
    assert plugin.calls == ["import_data"]


# ---------------------------------------------------------------------------
# P07-N013 training_centre / P07-N014 comparison
# ---------------------------------------------------------------------------


def test_p07_n013() -> None:
    from etf_cockpit.app.pages.training_centre import _step_key

    assert sorted({10, 2, 1}, key=_step_key) == [1, 2, 10]
    assert sorted(["10", 2, "warmup", 1], key=_step_key) == [1, 2, "10", "warmup"]


def test_p07_n014() -> None:
    from etf_cockpit.app.pages.comparison import _option_labels

    scores = {
        "k1": SimpleNamespace(display_id="X1", name="Fund"),
        "k2": SimpleNamespace(display_id="X1", name="Fund"),
        "k3": SimpleNamespace(display_id="X3", name="Other"),
    }
    labels = _option_labels(scores)
    assert labels["k1"] != labels["k2"] and labels["k1"].endswith("· k1") and labels["k2"].endswith("· k2")
    assert labels["k3"] == "X3  Other"
    assert len(set(labels.values())) == 3


# ---------------------------------------------------------------------------
# P07-N016 portfolio_optimiser
# ---------------------------------------------------------------------------


def test_p07_n016() -> None:
    from etf_cockpit.app.pages.portfolio_optimiser import portfolio_optimiser_page
    from etf_cockpit.core.config import load_config

    dates = pd.date_range("2025-01-01", periods=80)
    prices = pd.DataFrame(
        {
            "date": dates.tolist() * 2,
            "etf_id": ["AAA"] * 80 + ["BBB"] * 80,
            "adjusted_close": [100 + i * 0.1 for i in range(80)] + [90 + i * 0.2 for i in range(80)],
        }
    )
    state = SimpleNamespace(snapshot=SimpleNamespace(config=load_config(), prices=prices), last_message="Ready")
    view = portfolio_optimiser_page(_Page(), state)
    run = _find(view.body, "portfolio-optimiser.run")

    def cash_line() -> str:
        return next(t for t in _texts(view.body) if t.startswith("Model version:"))

    _field_input(view.body, "portfolio-optimiser.cash").value = "10"
    run.on_click(None)
    assert "Cash weight: 10.00%" in cash_line()
    _field_input(view.body, "portfolio-optimiser.cash").value = "20"
    run.on_click(None)
    assert "Cash weight: 20.00%" in cash_line()
    _field_input(view.body, "portfolio-optimiser.cash").value = "abc"
    run.on_click(None)
    assert "Comparison details are unavailable." in _texts(view.body)


# ---------------------------------------------------------------------------
# P07-N017 / N021 forward_evidence
# ---------------------------------------------------------------------------


def _forward_view(monkeypatch):
    from etf_cockpit.app.pages import forward_evidence as module

    stored: list[object] = []

    class _Diary:
        def list_entries(self, *_a, **_k):
            return list(stored)

        def record_observation(self, observation, **_k):
            stored.append(
                SimpleNamespace(observation=observation, outcome=SimpleNamespace(status=observation.outcome_status))
            )

    monkeypatch.setattr(module, "ForwardEvidenceDiary", _Diary)
    monkeypatch.setattr(
        module, "ForwardInputManifest", SimpleNamespace(create=lambda **k: SimpleNamespace(as_of=k["as_of"]))
    )
    monkeypatch.setattr(
        module,
        "ForwardEvidenceObservation",
        lambda **k: SimpleNamespace(**k, outcome_status=k.pop("outcome_status", "available") if False else "available"),
    )
    view = module.forward_evidence_page(_Page(), _state())
    return view, stored


def _record(view, observation_id) -> None:
    _field_input(view.body, "forward-evidence.observation-id").value = observation_id
    _field_input(view.body, "forward-evidence.as-of").value = "2026-01-01T00:00:00+00:00"
    _find(view.body, "forward-evidence.record").on_click(None)


def test_p07_n017(monkeypatch) -> None:
    view, _stored = _forward_view(monkeypatch)
    assert "OBS-1" not in _texts(view.body)
    _record(view, "OBS-1")
    assert "OBS-1" in _texts(view.body)


def test_p07_n021(monkeypatch) -> None:
    view, _stored = _forward_view(monkeypatch)
    assert "No observations yet" in _texts(view.body)
    _record(view, "OBS-1")
    texts = _texts(view.body)
    assert "No observations yet" not in texts
    assert "Matured" in [t.title() for t in texts] and "1" in texts


def test_p07_n018(monkeypatch) -> None:
    import etf_cockpit.app.pages.what_changed as module
    from etf_cockpit.application.ui_views.changes import ChangeRow, ChangesView

    def _row(instrument_id, dimension):
        return ChangeRow(
            instrument_id=instrument_id,
            score_delta=1.0,
            rank_delta=None,
            freshness=("same", "mute"),
            model=("same", "mute"),
            forecasts="same",
            news=None,
            backtest_trust=None,
            portfolio_risk=None,
            changed_dimensions=frozenset({dimension}),
            summary=f"summary-{instrument_id}",
        )

    rows = [_row("AAA", "score"), _row("BBB", "freshness")]
    view = ChangesView(subtitle="s", rows=rows, lineage=[], lineage_detail="", extras={"report_summary": ""})
    monkeypatch.setattr(module, "score_history_frame", lambda: pd.DataFrame())
    monkeypatch.setattr(module, "_changes_view", lambda *_a: (view, None))
    rendered = module.what_changed_page(_Page(), SimpleNamespace())
    assert any("AAA" in t for t in _texts(_find(rendered, "what-changed.path")))
    search = _field_input(rendered, "what-changed.filter.instrument")
    search.value = "BBB"
    search.on_change(None)
    path_texts = " ".join(_texts(_find(rendered, "what-changed.path")))
    assert "AAA" not in path_texts and "summary-AAA" not in path_texts
    assert "No instrument selected" in path_texts
