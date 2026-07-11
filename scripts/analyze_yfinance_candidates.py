from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from etf_cockpit.core.config import ProviderSection
from etf_cockpit.core.paths import REPORTS_DIR
from etf_cockpit.data.yfinance_provider import YFinanceProvider


DEFAULT_CANDIDATES = ROOT / "data" / "raw" / "trade_candidates" / "yahoo_trade_candidates_2026-06-30.csv"


@dataclass(frozen=True)
class CandidateMetric:
    instrument_id: str
    name: str
    isin: str
    yahoo_symbol: str
    shares: float
    currency: str
    latest_date: str
    latest_price: float | None
    trade_value_eur: float | None
    rows: int
    return_1w: float | None
    return_1m: float | None
    return_3m: float | None
    return_6m: float | None
    return_12m: float | None
    volatility_20d_ann: float | None
    volatility_60d_ann: float | None
    current_drawdown: float | None
    max_drawdown_12m: float | None
    distance_from_52w_high: float | None
    sma50_signal: bool | None
    sma200_signal: bool | None
    median_volume_60d: float | None
    median_turnover_60d_eur: float | None
    technical_score: int
    advisory_status: str
    blocked_by: str
    reason_full: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyse user-supplied EUR Yahoo Finance trade candidates.")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--as-of", type=str, default="")
    args = parser.parse_args()

    candidates = pd.read_csv(args.candidates)
    as_of = pd.to_datetime(args.as_of).date() if args.as_of else date.today()
    start = as_of.replace(year=as_of.year - args.years)
    section = ProviderSection(
        active_provider="yfinance",
        symbols_map={row.instrument_id: row.yahoo_symbol for row in candidates.itertuples(index=False)},
    )
    result = YFinanceProvider(section, default_currency="EUR").fetch_prices([], start, as_of)
    if not result.ok or result.data is None:
        print(result.message)
        return 1

    metrics = analyse_candidates(candidates, result.data)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORTS_DIR / f"yfinance_trade_candidate_analysis_{timestamp}.csv"
    json_path = REPORTS_DIR / f"yfinance_trade_candidate_analysis_{timestamp}.json"
    md_path = REPORTS_DIR / f"yfinance_trade_candidate_analysis_{timestamp}.md"
    frame = pd.DataFrame([asdict(metric) for metric in metrics])
    frame.to_csv(csv_path, index=False)
    json_path.write_text(json.dumps([asdict(metric) for metric in metrics], indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(metrics, result.message), encoding="utf-8")
    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(frame[["instrument_id", "yahoo_symbol", "latest_price", "trade_value_eur", "technical_score", "advisory_status", "blocked_by"]].to_string(index=False))
    return 0


def analyse_candidates(candidates: pd.DataFrame, prices: pd.DataFrame) -> list[CandidateMetric]:
    output: list[CandidateMetric] = []
    lookup = candidates.set_index("instrument_id").to_dict(orient="index")
    for instrument_id, group in prices.groupby("etf_id", sort=False):
        meta = lookup.get(str(instrument_id), {})
        output.append(_analyse_one(str(instrument_id), meta, group))
    missing = sorted(set(candidates["instrument_id"].astype(str)) - set(prices["etf_id"].astype(str).unique()))
    for instrument_id in missing:
        meta = lookup.get(instrument_id, {})
        output.append(_missing_metric(instrument_id, meta, "No yfinance price rows were returned."))
    return sorted(output, key=lambda metric: (metric.advisory_status, metric.instrument_id))


def _analyse_one(instrument_id: str, meta: dict[str, object], group: pd.DataFrame) -> CandidateMetric:
    group = group.sort_values("date").copy()
    adjusted = pd.to_numeric(group["adjusted_close"], errors="coerce").dropna()
    close = pd.to_numeric(group["close"], errors="coerce").dropna()
    volume = pd.to_numeric(group["volume"], errors="coerce").fillna(0)
    rows = int(len(adjusted))
    latest_date = str(pd.to_datetime(group["date"]).max().date()) if rows else "unknown"
    latest_price = float(close.iloc[-1]) if not close.empty else None
    shares = _float(meta.get("shares"), 0.0)
    trade_value = latest_price * shares if latest_price is not None else None
    returns = np.log(adjusted / adjusted.shift(1)).dropna()
    sma50 = adjusted.rolling(50, min_periods=50).mean()
    sma200 = adjusted.rolling(200, min_periods=200).mean()
    current_drawdown = _safe_float(adjusted.iloc[-1] / adjusted.cummax().iloc[-1] - 1.0) if rows else None
    drawdown_series = adjusted / adjusted.cummax() - 1.0
    max_drawdown_12m = _safe_float(drawdown_series.tail(252).min()) if rows else None
    high_52w = adjusted.tail(252).max() if rows else np.nan
    distance_52w = _safe_float(adjusted.iloc[-1] / high_52w - 1.0) if rows and high_52w > 0 else None
    flags: list[str] = []
    score = 0

    ret_1w = _horizon_return(adjusted, 5)
    ret_1m = _horizon_return(adjusted, 21)
    ret_3m = _horizon_return(adjusted, 63)
    ret_6m = _horizon_return(adjusted, 126)
    ret_12m = _horizon_return(adjusted, 252)
    vol20 = _annualised_vol(returns.tail(20))
    vol60 = _annualised_vol(returns.tail(60))
    sma50_signal = bool(adjusted.iloc[-1] > sma50.iloc[-1]) if rows >= 50 and pd.notna(sma50.iloc[-1]) else None
    sma200_signal = bool(adjusted.iloc[-1] > sma200.iloc[-1]) if rows >= 200 and pd.notna(sma200.iloc[-1]) else None

    if rows < 252:
        flags.append("insufficient_12m_history")
    if latest_price is None or latest_price <= 0:
        flags.append("missing_latest_price")
    if sma50_signal is True:
        score += 1
    elif sma50_signal is False:
        flags.append("below_sma50")
    if sma200_signal is True:
        score += 2
    elif sma200_signal is False:
        flags.append("below_sma200")
    for label, value in (("positive_3m", ret_3m), ("positive_6m", ret_6m), ("positive_12m", ret_12m)):
        if value is not None and value > 0:
            score += 1
        else:
            flags.append(label.replace("positive", "not_positive"))
    if current_drawdown is not None and current_drawdown > -0.10:
        score += 1
    elif current_drawdown is not None and current_drawdown < -0.25:
        flags.append("deep_current_drawdown")
        score -= 1
    if vol60 is not None and vol60 > 0.40:
        flags.append("high_60d_volatility")
        score -= 1
    if ret_1m is not None and ret_1m > 0.18:
        flags.append("short_term_overextended")
        score -= 1
    if str(instrument_id) == "VIE":
        flags.append("share_count_ambiguous_8_or_7")

    status = _status_from_score(score, flags)
    reason = _reason(score, flags, ret_3m, ret_6m, ret_12m, current_drawdown, vol60)
    median_volume = _safe_float(volume.tail(60).median()) if len(volume) else None
    median_turnover = median_volume * latest_price if median_volume is not None and latest_price is not None else None
    return CandidateMetric(
        instrument_id=instrument_id,
        name=str(meta.get("name", "")),
        isin=str(meta.get("isin", "")),
        yahoo_symbol=str(meta.get("yahoo_symbol", "")),
        shares=shares,
        currency=str(meta.get("currency", "EUR")),
        latest_date=latest_date,
        latest_price=_safe_float(latest_price),
        trade_value_eur=_safe_float(trade_value),
        rows=rows,
        return_1w=ret_1w,
        return_1m=ret_1m,
        return_3m=ret_3m,
        return_6m=ret_6m,
        return_12m=ret_12m,
        volatility_20d_ann=vol20,
        volatility_60d_ann=vol60,
        current_drawdown=current_drawdown,
        max_drawdown_12m=max_drawdown_12m,
        distance_from_52w_high=distance_52w,
        sma50_signal=sma50_signal,
        sma200_signal=sma200_signal,
        median_volume_60d=median_volume,
        median_turnover_60d_eur=_safe_float(median_turnover),
        technical_score=score,
        advisory_status=status,
        blocked_by=", ".join(flags) if flags else "",
        reason_full=reason,
    )


def _missing_metric(instrument_id: str, meta: dict[str, object], reason: str) -> CandidateMetric:
    return CandidateMetric(
        instrument_id=instrument_id,
        name=str(meta.get("name", "")),
        isin=str(meta.get("isin", "")),
        yahoo_symbol=str(meta.get("yahoo_symbol", "")),
        shares=_float(meta.get("shares"), 0.0),
        currency=str(meta.get("currency", "EUR")),
        latest_date="unknown",
        latest_price=None,
        trade_value_eur=None,
        rows=0,
        return_1w=None,
        return_1m=None,
        return_3m=None,
        return_6m=None,
        return_12m=None,
        volatility_20d_ann=None,
        volatility_60d_ann=None,
        current_drawdown=None,
        max_drawdown_12m=None,
        distance_from_52w_high=None,
        sma50_signal=None,
        sma200_signal=None,
        median_volume_60d=None,
        median_turnover_60d_eur=None,
        technical_score=-99,
        advisory_status="manual_review",
        blocked_by="missing_price_data",
        reason_full=reason,
    )


def _horizon_return(series: pd.Series, horizon: int) -> float | None:
    if len(series) <= horizon:
        return None
    return _safe_float(np.log(series.iloc[-1] / series.iloc[-1 - horizon]))


def _annualised_vol(returns: pd.Series) -> float | None:
    if len(returns) < 10:
        return None
    return _safe_float(returns.std() * np.sqrt(252))


def _status_from_score(score: int, flags: list[str]) -> str:
    hard_flags = {"missing_price_data", "missing_latest_price", "insufficient_12m_history"}
    if hard_flags & set(flags):
        return "manual_review"
    if score >= 5 and "below_sma200" not in flags and "deep_current_drawdown" not in flags:
        return "add_candidate"
    if score >= 3:
        return "watchlist"
    return "no_trade"


def _reason(score: int, flags: list[str], ret_3m: float | None, ret_6m: float | None, ret_12m: float | None, drawdown: float | None, vol60: float | None) -> str:
    parts = [
        f"Technical score {score}.",
        f"3m={_fmt_pct(ret_3m)}, 6m={_fmt_pct(ret_6m)}, 12m={_fmt_pct(ret_12m)}.",
        f"Current drawdown={_fmt_pct(drawdown)}, 60d vol={_fmt_pct(vol60)}.",
    ]
    if flags:
        parts.append("Flags: " + ", ".join(flags) + ".")
    else:
        parts.append("No blocking technical flags from this price-only screen.")
    parts.append("Price-only screen; not a fundamental valuation or trade authorisation.")
    return " ".join(parts)


def render_markdown(metrics: list[CandidateMetric], source_message: str) -> str:
    lines = [
        "# YFinance Trade Candidate Analysis",
        "",
        source_message,
        "",
        "This is deterministic price-only evidence. It is not broker execution advice and cannot override risk gates.",
        "",
        "| Instrument | Yahoo | Latest | Value EUR | Score | Status | Flags |",
        "| --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for metric in metrics:
        lines.append(
            (
                f"| {metric.instrument_id} | {metric.yahoo_symbol} | "
                f"{_fmt_number(metric.latest_price)} | {_fmt_number(metric.trade_value_eur)} | "
                f"{metric.technical_score} | {metric.advisory_status} | {metric.blocked_by or '-'} |"
            )
        )
    lines.append("")
    lines.append("## Details")
    for metric in metrics:
        lines.extend(["", f"### {metric.instrument_id} - {metric.name}", metric.reason_full])
    return "\n".join(lines) + "\n"


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _fmt_number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.2f}"


def _float(value: object, default: float) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _safe_float(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        value_float = float(value)
        if not np.isfinite(value_float):
            return None
        return value_float
    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
