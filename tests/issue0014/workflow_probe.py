from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd


FIXED_TODAY = date(2026, 8, 10)


class _FixedDate(date):
    @classmethod
    def today(cls) -> date:
        return cls(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day)


def _walk(control: object):
    if control is None:
        return
    yield control
    for attribute in ("controls", "rows", "cells", "actions"):
        values = getattr(control, attribute, None)
        if values:
            for child in values:
                yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


class _Page:
    def __init__(self) -> None:
        self.route = "/"
        self.views: list[object] = []
        self.width = 1400
        self.update_count = 0
        self.go_calls: list[str] = []
        self.overlay: list[object] = []
        self.window = SimpleNamespace()

    def update(self) -> None:
        self.update_count += 1

    def go(self, route: str) -> None:
        self.go_calls.append(route)
        self.route = route


def _route_probe() -> dict[str, object]:
    from etf_cockpit.app.flet_app import initialise_page
    from etf_cockpit.app.router import PAGES, navigate_to
    from etf_cockpit.app.state import AppState
    from etf_cockpit.services import build_snapshot

    routes = ("/", "/training-centre")
    if any(route not in PAGES for route in routes):
        raise AssertionError("route probe named an unregistered route")
    snapshot = build_snapshot(force_sample=True)
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = _Page()
    initialise_page(page, state)
    route_error_keys: list[str] = []
    for route in routes[1:]:
        navigate_to(page, state, route)
        route_error_keys.extend(
            str(getattr(control, "key", ""))
            for view in page.views
            for control in _walk(view)
            if getattr(control, "key", None) == "router.route-error"
        )
    event_path = Path(os.environ["ETF_COCKPIT_ROOT"]) / "logs" / "session.jsonl"
    event_types = []
    if event_path.is_file():
        event_types = [
            str(json.loads(line).get("event_type", ""))
            for line in event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return {
        "routes": list(routes),
        "initial_route": routes[0],
        "go_calls": page.go_calls,
        "route_error_keys": route_error_keys,
        "route_error_events": [value for value in event_types if value == "route_render_failure"],
        "root": os.environ["ETF_COCKPIT_ROOT"],
    }


class _FixtureTicker:
    info = {"longName": "ISSUE-0014 fixture", "currency": "EUR", "quoteType": "ETF"}
    fast_info = {"currency": "EUR"}
    funds_data = SimpleNamespace(fund_overview={}, fund_operations=pd.DataFrame(), top_holdings=pd.DataFrame())


def _fixture_download(symbol: str, **kwargs: object) -> pd.DataFrame:
    end = pd.Timestamp(str(kwargs["end"])) - pd.Timedelta(days=1)
    index = pd.bdate_range(end=end, periods=320)
    offset = float(sum(ord(character) for character in symbol) % 17)
    close = 90.0 + offset + np.linspace(0.0, 18.0, len(index))
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 0.4,
            "Low": close - 0.5,
            "Close": close,
            "Adj Close": close,
            "Volume": np.full(len(index), 10_000.0),
            "Dividends": np.zeros(len(index)),
            "Stock Splits": np.zeros(len(index)),
        },
        index=index,
    )


def _main_workflow_probe() -> dict[str, object]:
    calls: list[str] = []
    download_ends: list[str] = []

    def download(symbol: str, **kwargs: object) -> pd.DataFrame:
        calls.append(symbol)
        download_ends.append(str(kwargs["end"]))
        return _fixture_download(symbol, **kwargs)

    sys.modules["yfinance"] = SimpleNamespace(download=download, Ticker=lambda _symbol: _FixtureTicker())

    from etf_cockpit.app.state import ActivityUnavailableError, AppState
    from etf_cockpit.core.config import load_config
    from etf_cockpit.governance.product_scope import load_gate_policy
    import etf_cockpit.services as services

    services.date = _FixedDate
    config = load_config()
    candidate_path = (
        Path(os.environ["ETF_COCKPIT_ROOT"])
        / "data"
        / "raw"
        / "trade_candidates"
        / "yahoo_trade_candidates_20990101.csv"
    )
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(
        "instrument_id,name,yahoo_symbol,analysis_tier,asset_type\n"
        "VWCE,Vanguard FTSE All-World,VWCE.DE,primary,etf\n",
        encoding="utf-8",
    )
    initial_snapshot = SimpleNamespace(config=config)
    state = AppState(snapshot=initial_snapshot, selected_etf=config.ui.default_etf)
    refresh = state.refresh_yfinance_data()
    algorithms = state.run_algorithm_scores()
    try:
        forecasts = state.run_forecasting_models()
        forecast_state = "available"
    except ActivityUnavailableError as exc:
        forecasts = str(exc)
        forecast_state = "unavailable"
    root = Path(os.environ["ETF_COCKPIT_ROOT"]).resolve()
    scoreboard = root / "data" / "derived" / "scoreboard.parquet"
    scoreboard_before_audit = scoreboard.is_file()
    audit = state.export_audit_packet()
    policy = load_gate_policy()
    for output in (scoreboard, audit):
        if not output.resolve().is_relative_to(root):
            raise AssertionError(f"workflow output escaped isolated root: {output}")
    return {
        "download_calls": len(calls),
        "download_ends": download_ends,
        "fixed_today": FIXED_TODAY.isoformat(),
        "price_as_of": max(pd.to_datetime(state.snapshot.prices["date"])).date().isoformat(),
        "candidate_fixture": str(candidate_path),
        "refresh": refresh,
        "algorithms": algorithms,
        "forecast_state": forecast_state,
        "forecasts": forecasts,
        "scoreboard": str(scoreboard),
        "scoreboard_exists": scoreboard.is_file(),
        "scoreboard_before_audit": scoreboard_before_audit,
        "audit": str(audit),
        "audit_exists": audit.is_file(),
        "execution_allowed": None if policy.policy is None else policy.policy.execution_allowed,
        "root": str(root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("routes", "main"))
    args = parser.parse_args(argv)
    payload = _route_probe() if args.mode == "routes" else _main_workflow_probe()
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
