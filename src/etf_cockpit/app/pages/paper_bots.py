"""Read-only Bots view: forward paper bots against the cash-flow-matched VWCE shadow account (minimal, functional)."""

from __future__ import annotations

from datetime import date

import flet as ft

from etf_cockpit.app import theme
from etf_cockpit.app.components import chartkit as ck
from etf_cockpit.app.components.kit import Disclosure, EmptyState, GlassCard, KpiTile, ListRow, Note
from etf_cockpit.app.components.shell.page_view import PageChrome, PageView
from etf_cockpit.app.formatting import format_currency, format_percent
from etf_cockpit.app.pages._l4a_common import page_body
from etf_cockpit.app.state import AppState
from etf_cockpit.application.ui_facade import load_paper_bots_view

_CHART_WIDTH = 760
_CHART_HEIGHT = 260
_COLOURS = (ck.palette.P, ck.palette.SECOND, ck.palette.VIO, ck.palette.NEG)


def paper_bots_page(page: ft.Page | None, state: AppState) -> PageView:
    view = load_paper_bots_view()
    forward = view.get("forward") or {}
    replay = view.get("replay")
    body: list[ft.Control] = [
        Note("Paper only: execution_allowed=false. Fills happen at the next session open with modelled costs; a missed fill is logged and keeps its cash."),
        *_track_cards(forward, replay=False),
    ]
    if replay:
        body.extend(_track_cards(replay, replay=True))
    else:
        body.append(
            GlassCard(
                "Conditional historical simulation",
                "Not run",
                body=EmptyState("No replay stored", "Run scripts/run_paper_bots.py --replay to store a separately labelled replay over the stored history."),
            )
        )
    body.append(GlassCard("What to expect", body=ft.Column([Note(text) for text in view.get("expectations") or []], spacing=theme.SPACE_1)))
    return PageView(
        chrome=PageChrome("Bots", "Frozen paper bots compared with the cash-flow-matched VWCE shadow account", []),
        body=page_body(body),
    )


def _track_cards(report: dict, *, replay: bool) -> list[ft.Control]:
    title = str(report.get("label") or "Forward paper record") if replay else "Forward paper record"
    status = str(report.get("status") or "unavailable")
    bots = report.get("bots") or []
    header_note = (
        str(report.get("caveat") or "") + " Never mixed with the forward record."
        if replay else "Forward record: decided before the outcome was known."
    )
    if not bots:
        return [GlassCard(title, status.title(), body=ft.Column([Note(header_note), EmptyState("Unavailable", str(report.get("reason") or "No bot record yet."))], spacing=theme.SPACE_2))]
    cards: list[ft.Control] = [
        GlassCard(
            title,
            status.title(),
            body=ft.Column(
                [
                    Note(header_note + (f" (as of {report.get('as_of')})" if report.get("as_of") else "")),
                    _wealth_chart(bots, title),
                    *(_bot_block(bot) for bot in bots),
                ],
                spacing=theme.SPACE_3,
            ),
        )
    ]
    cards.append(_relative_card(bots, title))
    return cards


def _wealth_chart(bots: list[dict], title: str) -> ft.Control:
    """One curve per bot on the sorted union of every bot's dates; a day a bot has no value for stays a gap (``None``)."""

    dates = sorted({date.fromisoformat(item) for bot in bots for item in bot.get("dates") or []})
    if not dates:
        return EmptyState("No wealth curve yet", "A curve needs a completed session after the first funding.")
    series = []
    for index, bot in enumerate(bots):
        by_day = dict(zip((date.fromisoformat(item) for item in bot.get("dates") or []), bot.get("wealth") or []))
        if not by_day:
            continue
        values = [by_day.get(day) for day in dates]
        series.append(ck.Series(f"{bot['family']}", values, _COLOURS[index % len(_COLOURS)], 2.4 if bot["family"] != "B0" else 3.2, decimals=0))
    return ck.line_chart(
        dates, series, x_name="Date", y_name=f"{title}: wealth (EUR)", width=_CHART_WIDTH, height=_CHART_HEIGHT,
        unavailable_reason=None if series else "No bot has a verified wealth series yet.", empty_title="No wealth curve",
    )


def _relative_card(bots: list[dict], title: str) -> ft.Control:
    rows: list[ft.Control] = []
    for bot in bots:
        if bot["family"] == "B0":
            continue
        uncertainty = bot.get("uncertainty") or {}
        rows.append(
            ListRow(
                "ok" if uncertainty.get("status") == "available" and (uncertainty.get("lower") or 0) > 0 else "attention",
                f"{bot['family']} · {bot.get('name')}",
                _interval_text(uncertainty),
                tag=(str(uncertainty.get("verdict") or "Unconfirmed advantage"), "mute"),
            )
        )
    charts: list[ft.Control] = []
    for bot in bots:
        bands = (bot.get("uncertainty") or {}).get("bands") or []
        if bot["family"] != "B0" and bands:
            months = [date.fromisoformat(f"{item['month']}-01") for item in bands]
            charts.append(
                ck.line_chart(
                    months,
                    [ck.Series(f"{bot['family']} relative wealth", [item["relative_wealth"] * 100 for item in bands], ck.palette.P, 2.6, decimals=1)],
                    bands=[ck.Band("95% interval", [item["lower"] * 100 for item in bands], [item["upper"] * 100 for item in bands])],
                    x_name="Month", y_name="Relative wealth vs VWCE shadow (%)", width=_CHART_WIDTH, height=_CHART_HEIGHT,
                )
            )
    return GlassCard(
        f"{title}: relative wealth and uncertainty",
        body=ft.Column(
            [*(rows or [EmptyState("No relative result yet", "Needs funded, completed sessions for a bot and its VWCE shadow account.")]), *charts,
             Note("Date-clustered (calendar-month) interval. An advantage is only shown when the interval excludes 0.")],
            spacing=theme.SPACE_2,
        ),
    )


def _interval_text(uncertainty: dict) -> str:
    if uncertainty.get("status") != "available":
        return str(uncertainty.get("reason") or "Interval unavailable.")
    return (
        f"{uncertainty['months']} months · mean monthly relative return {format_percent(uncertainty['mean_monthly_relative_return'], decimals=2)} · "
        f"{int(float(uncertainty['confidence']) * 100)}% interval {format_percent(uncertainty['lower'], decimals=2)} to {format_percent(uncertainty['upper'], decimals=2)}"
    )


def _bot_block(bot: dict) -> ft.Control:
    metrics = bot.get("metrics") or {}
    tiles = ft.Row(
        [
            KpiTile("Value", format_currency(metrics.get("final_value_eur"), decimals=0) if metrics.get("final_value_eur") is not None else None, sub="Latest valuation"),
            KpiTile("Relative wealth", format_percent(metrics.get("compounded_relative_wealth"), decimals=2) if metrics.get("compounded_relative_wealth") is not None else None, sub=str(metrics.get("compounded_relative_wealth_label") or bot.get("reason") or "Unavailable")[:80]),
            KpiTile("Period excess", format_percent(metrics.get("period_excess_return"), decimals=2) if metrics.get("period_excess_return") is not None else None, sub="R_p - R_b"),
            KpiTile("Drawdown", format_percent(metrics.get("max_drawdown"), decimals=1) if metrics.get("max_drawdown") is not None else None, sub="Maximum"),
            KpiTile("Turnover", f"{metrics['turnover']:.2f}x" if metrics.get("turnover") is not None else None, sub="Traded / average value"),
            KpiTile("Costs", format_currency(metrics.get("costs_eur"), decimals=2) if metrics.get("costs_eur") is not None else None, sub="Fees + spread/slippage"),
        ],
        wrap=True,
        spacing=theme.SPACE_2,
    )
    log_lines = "\n".join(
        f"{row['session']} {row['side']} {row['instrument_id']} {row['status']} qty={row['quantity']} fill={row['fill_price']} fee={row['fee']} · {row['reason']}"
        + (f" · {row['outcome_reason']}" if row.get("outcome_reason") else "")
        for row in bot.get("trade_log") or []
    ) or "No orders yet."
    return ft.Column(
        [
            ListRow(
                "ok" if bot.get("status") == "available" else "attention",
                f"{bot['family']} · {bot.get('name')}",
                f"{bot.get('score_lineage_version')} · {bot.get('decisions')} decisions · targets {bot.get('latest_targets') or 'none'}"
                + (f" · {bot.get('reason')}" if bot.get("reason") else ""),
                tag=(f"{bot.get('missed_fills', 0)} missed", "bad" if bot.get("missed_fills") else "mute"),
            ),
            tiles,
            Disclosure("Trade log (reason per trade, missed fills included)", log_lines),
        ],
        spacing=theme.SPACE_1,
    )


__all__ = ["paper_bots_page"]
