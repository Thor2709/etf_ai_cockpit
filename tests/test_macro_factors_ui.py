from __future__ import annotations

import inspect
from types import SimpleNamespace

import flet as ft
import pandas as pd

from etf_cockpit.app.pages import macro_factors
from etf_cockpit.app.router import PAGES
from etf_cockpit.application import macro_context
from etf_cockpit.core.config import load_config
from etf_cockpit.data.macro_warehouse import MacroObservation


def _walk(control):
    if control is None:
        return
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)


def _text(control) -> str:
    return "\n".join(
        str(item.value)
        for item in _walk(control)
        if isinstance(item, ft.Text)
    )


def _snapshot(**changes):
    value = {
        "config": load_config(),
        "prices": pd.DataFrame(
            {
                "date": ["2024-01-01", "2024-04-01"],
                "etf_id": ["VWCE", "VWCE"],
                "adjusted_close": [100.0, 110.0],
            }
        ),
        "benchmark_reference_decision_time": "2024-03-01T00:00:00Z",
        "benchmark_reference_currency": "USD",
        "benchmark_reference_horizon_years": 0.25,
        "universe_revision": "macro-ui-fixture",
    }
    value.update(changes)
    return SimpleNamespace(**value)


def _observation() -> MacroObservation:
    return MacroObservation(
        dataset_id="macro-fixture",
        series_id="US-CPI",
        period_start="2024-01-01",
        value=2.0,
        unit="index_points",
        frequency="monthly",
        country="US",
        currency="USD",
        source_id="fixture.csv",
        source_authority="official_public_file",
        source_checksum="a" * 64,
        published_at="2024-02-01T00:00:00Z",
        available_at="2024-02-01T00:00:00Z",
        observed_at="2024-01-01T00:00:00Z",
        ingested_at="2024-02-02T00:00:00Z",
    )


def test_macro_factors_workspace_is_registered_and_declares_safe_boundaries() -> None:
    assert PAGES["/macro"][0] == "Macro and Factors"
    source = inspect.getsource(macro_factors.macro_factors_page)
    for label in (
        "Decision-time vintages",
        "Execution allowed: false",
        "Latest local observations",
        "Regime and proxy context",
        "Optional FRED: unavailable",
        "Inflation/rates context:",
        "context_only=true",
        "score_eligible=false",
        "Risk-free curves and lawful benchmarks",
        "Interpolation is declared per curve and bounded",
        "Currency+horizon fallbacks are explicit",
        "Issuer-specific credit curves:",
        "decision-time vintage=",
    ):
        assert label in source
    assert "remote fetch" in source


def test_macro_page_binds_every_producer_to_snapshot_cutoff_and_renders_lineage(
    monkeypatch,
) -> None:
    calls = []
    observation = _observation()

    class Warehouse:
        def summary(self, *, root, decision_time):
            calls.append(("summary", decision_time))
            return {
                "status": "available",
                "row_count": 1,
                "dataset_ids": [observation.dataset_id],
                "missing_country_or_currency_count": 0,
            }

        def observations_as_of(self, *, root, decision_time):
            calls.append(("observations", decision_time))
            return [observation]

        def curve_benchmark_coverage(self, *, root, decision_time):
            calls.append(("curves", decision_time))
            return {
                "status": "unavailable",
                "curve_ids": [],
                "curve_types": [],
                "currencies": [],
                "benchmark_ids": [],
                "source_ids": [],
                "methodologies": [],
                "decision_time": decision_time,
                "issuer_credit": "unavailable",
            }

    monkeypatch.setattr(macro_factors, "MacroWarehouse", Warehouse)
    rendered = macro_factors.macro_factors_page(
        None, SimpleNamespace(snapshot=_snapshot())
    )
    text = _text(rendered)

    expected = "2024-03-01T00:00:00+00:00"
    assert calls == [("summary", expected), ("observations", expected), ("curves", expected)]
    assert "source=fixture.csv" in text
    assert "observed_at=2024-01-01T00:00:00Z" in text
    assert "published_at=2024-02-01T00:00:00Z" in text
    assert "revised_at=unavailable" in text
    assert "ingested_at=2024-02-02T00:00:00Z" in text
    assert "revision=1" in text
    assert "source_observation_ids=unavailable" in text
    assert "authority=official_public_file" in text
    assert "vintage=2024-01-01T00:00:00Z" not in text
    assert "country=US | currency=USD" in text
    assert "uncertainty=exact/exact" in text
    assert "transformation=identity.v1" in text
    assert "Scenario-linked macro evidence" in text
    assert "link=warehouse:" in text
    assert "evidence=" in text
    assert "decision_time=2024-03-01T00:00:00Z" in text
    assert "9999" not in text


def test_binding_rejects_guessed_currency_horizon_and_driver(monkeypatch) -> None:
    observation = _observation()

    class Warehouse:
        def summary(self, **_kwargs):
            return {"status": "available", "row_count": 99}

        def observations_as_of(self, **_kwargs):
            return [observation]

        def curve_benchmark_coverage(self, **kwargs):
            return {"status": "unavailable", "decision_time": kwargs["decision_time"]}

    monkeypatch.setattr(macro_context, "build_macro_context", lambda *args, **kwargs: {})
    binding = macro_context.build_macro_context_binding(
        _snapshot(
            benchmark_reference_currency=None,
            benchmark_reference_horizon_years=float("nan"),
        ),
        warehouse=Warehouse(),
        root=macro_context.Path("."),
    )

    assert binding.summary["row_count"] == 1
    assert binding.summary["status"] == "available"
    assert binding.scenario["status"] == "unavailable"
    assert binding.scenario["portfolio_currency"] == "unavailable"
    assert binding.scenario["horizon_days"] == "unavailable"


def test_date_only_price_at_intraday_cutoff_is_not_used() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2024-02-29", "2024-03-01"],
            "etf_id": ["VWCE", "VWCE"],
            "adjusted_close": [100.0, 500.0],
        }
    )

    selected = macro_context._prices_as_of(prices, "2024-03-01T12:00:00+00:00")

    assert selected["date"].tolist() == ["2024-02-29"]


def test_unknown_source_authority_is_not_reclassified_as_local_import(monkeypatch) -> None:
    observation = _observation().model_copy(update={"source_authority": None})

    class Warehouse:
        def summary(self, **_kwargs):
            return {"status": "available"}

        def observations_as_of(self, **_kwargs):
            return [observation]

        def curve_benchmark_coverage(self, **kwargs):
            return {"status": "unavailable", "decision_time": kwargs["decision_time"]}

    monkeypatch.setattr(macro_context, "build_macro_context", lambda *args, **kwargs: {})
    binding = macro_context.build_macro_context_binding(
        _snapshot(), warehouse=Warehouse(), root=macro_context.Path(".")
    )

    assert binding.scenario["status"] == "unavailable"
    assert "source_authority_invalid" in binding.scenario["limitations"]
    assert "local_user_import" not in str(binding.scenario)


def test_macro_page_fails_closed_with_explicit_unavailable_when_cutoff_missing(
    monkeypatch,
) -> None:
    class Warehouse:
        def summary(self, **_kwargs):
            raise AssertionError("warehouse must not be queried without a cutoff")

    monkeypatch.setattr(macro_factors, "MacroWarehouse", Warehouse)
    rendered = macro_factors.macro_factors_page(
        None,
        SimpleNamespace(snapshot=_snapshot(benchmark_reference_decision_time=None)),
    )
    text = _text(rendered)

    assert "snapshot decision time is unavailable" in text
    assert "decision-time vintage=unavailable" in text
    assert "9999" not in text
