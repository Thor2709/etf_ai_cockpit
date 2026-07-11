from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from etf_cockpit.core.paths import DERIVED_DIR


def build_market_regime(prices: pd.DataFrame, candidate_report: pd.DataFrame | None = None) -> dict[str, object]:
    if prices.empty or not {"etf_id", "date", "adjusted_close"}.issubset(prices.columns):
        return _empty_regime("No clean yfinance price panel is available.")
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    pivot = frame.dropna(subset=["date", "adjusted_close"]).pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
    pivot = pivot.dropna(how="all")
    if len(pivot) < 220:
        return _empty_regime("Less than 220 trading days are available for regime scoring.")

    latest = pivot.ffill().iloc[-1]
    sma200 = pivot.ffill().rolling(200, min_periods=160).mean().iloc[-1]
    above = (latest > sma200).dropna()
    configured_pct_above = float(above.mean()) if not above.empty else 0.0
    benchmark_id = str(pivot.columns[0])
    benchmark = pivot[benchmark_id].dropna()
    benchmark_above_sma200 = bool(latest.get(benchmark_id, np.nan) > sma200.get(benchmark_id, np.nan))
    benchmark_return_60d = _horizon_return(benchmark, 60)
    benchmark_return_120d = _horizon_return(benchmark, 120)
    returns = pivot.ffill().pct_change(fill_method=None)
    median_vol_60d = float(returns.tail(60).std(skipna=True).median() * np.sqrt(252)) if len(returns) >= 60 else None
    drawdowns = pivot.ffill() / pivot.ffill().cummax() - 1.0
    median_drawdown = float(drawdowns.iloc[-1].median(skipna=True))
    candidate_pct_above = _candidate_pct_above_sma200(candidate_report)
    combined_pct_above = _weighted_available(
        [
            (configured_pct_above, 0.75),
            (candidate_pct_above, 0.25),
        ]
    )
    avg_corr_60d = _average_correlation(returns.tail(60))

    score = 5.0
    score += 1.8 if benchmark_above_sma200 else -1.8
    score += (combined_pct_above - 0.50) * 4.0
    score += 0.8 if (benchmark_return_60d or 0.0) > 0 else -0.6
    score += 0.7 if (benchmark_return_120d or 0.0) > 0 else -0.5
    if median_vol_60d is not None and median_vol_60d > 0.30:
        score -= 0.8
    if median_drawdown < -0.15:
        score -= 0.8
    score = _clamp_score(score)
    label = "Supportive" if score >= 7.0 else "Caution" if score >= 5.0 else "Defensive review"
    return {
        "regime_score_10": round(score, 1),
        "regime_label": label,
        "benchmark_id": benchmark_id,
        "benchmark_above_sma200": benchmark_above_sma200,
        "benchmark_return_60d": benchmark_return_60d,
        "benchmark_return_120d": benchmark_return_120d,
        "configured_pct_above_sma200": round(configured_pct_above, 4),
        "candidate_pct_above_sma200": None if candidate_pct_above is None else round(candidate_pct_above, 4),
        "combined_pct_above_sma200": round(combined_pct_above, 4),
        "median_volatility_60d_ann": None if median_vol_60d is None else round(median_vol_60d, 4),
        "median_current_drawdown": round(median_drawdown, 4),
        "average_correlation_60d": None if avg_corr_60d is None else round(avg_corr_60d, 4),
        "summary": _regime_summary(label, score, combined_pct_above, benchmark_return_60d, benchmark_return_120d, median_drawdown),
    }


def build_portfolio_fit_lookup(prices: pd.DataFrame) -> dict[str, dict[str, object]]:
    if prices.empty or not {"etf_id", "date", "adjusted_close"}.issubset(prices.columns):
        return {}
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    pivot = frame.dropna(subset=["date", "adjusted_close"]).pivot(index="date", columns="etf_id", values="adjusted_close").sort_index().ffill()
    if pivot.shape[1] < 2:
        return {}
    benchmark_id = str(pivot.columns[0])
    returns = pivot.pct_change(fill_method=None).tail(252).dropna(how="all")
    benchmark = returns[benchmark_id].dropna()
    output: dict[str, dict[str, object]] = {}
    for instrument_id in pivot.columns:
        series = returns[instrument_id].dropna()
        joined = pd.concat([series, benchmark], axis=1, join="inner").dropna()
        if len(joined) < 40:
            output[str(instrument_id)] = {"score": None, "label": "Portfolio fit pending: not enough overlapping returns."}
            continue
        corr = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
        variance = float(joined.iloc[:, 1].var())
        beta = float(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / variance) if variance > 0 else None
        score = _portfolio_fit_score(corr, beta)
        output[str(instrument_id)] = {
            "score": round(score, 1),
            "label": f"Benchmark corr {corr:.2f}; beta {_fmt_float(beta)}. Lower duplicate exposure scores better.",
            "correlation_to_benchmark": round(corr, 4),
            "beta_to_benchmark": None if beta is None else round(beta, 4),
        }
    return output


def build_benchmark_attribution_lookup(
    prices: pd.DataFrame,
    *,
    window: int = 120,
    benchmark_id: str | None = None,
) -> dict[str, dict[str, object]]:
    if prices.empty or not {"etf_id", "date", "adjusted_close"}.issubset(prices.columns):
        return {}
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    pivot = frame.dropna(subset=["date", "adjusted_close"]).pivot(index="date", columns="etf_id", values="adjusted_close").sort_index().ffill()
    if pivot.shape[1] < 2:
        return {}
    benchmark_id = str(benchmark_id) if benchmark_id and benchmark_id in pivot.columns else str(pivot.columns[0])
    returns = pivot.pct_change(fill_method=None).dropna(how="all")
    benchmark_returns = returns[benchmark_id].dropna()
    output: dict[str, dict[str, object]] = {}
    for instrument_id in pivot.columns:
        instrument = str(instrument_id)
        series = returns[instrument_id].dropna()
        joined = pd.concat([series, benchmark_returns], axis=1, join="inner").dropna()
        joined.columns = ["instrument", "benchmark"]
        sample = joined.tail(window)
        if len(sample) < max(60, window // 2):
            output[instrument] = {
                "benchmark_id": benchmark_id,
                "period_days": window,
                "label": "Benchmark attribution pending: not enough overlapping yfinance returns.",
                "instrument_return": None,
                "benchmark_return": None,
                "beta_to_benchmark": None,
                "correlation_to_benchmark": None,
                "alpha_proxy": None,
                "alpha_t_stat": None,
            }
            continue
        instrument_prices = pivot[instrument_id].dropna()
        benchmark_prices = pivot[benchmark_id].dropna()
        instrument_return = _horizon_return(instrument_prices, min(window, len(instrument_prices) - 1))
        benchmark_return = _horizon_return(benchmark_prices, min(window, len(benchmark_prices) - 1))
        variance = float(sample["benchmark"].var())
        beta = float(sample["instrument"].cov(sample["benchmark"]) / variance) if variance > 0 else None
        corr_raw = float(sample["instrument"].corr(sample["benchmark"]))
        corr = corr_raw if np.isfinite(corr_raw) else None
        alpha_proxy = None
        alpha_t_stat = None
        if beta is not None and benchmark_return is not None and instrument_return is not None:
            alpha_proxy = float(instrument_return - beta * benchmark_return)
            residual = sample["instrument"] - beta * sample["benchmark"]
            residual_std = float(residual.std())
            if residual_std > 0 and len(residual) >= 80:
                alpha_t_stat = float(residual.mean() / residual_std * np.sqrt(len(residual)))
        output[instrument] = {
            "benchmark_id": benchmark_id,
            "period_days": window,
            "label": _benchmark_attribution_label(benchmark_id, instrument_return, benchmark_return, beta, corr, alpha_proxy, alpha_t_stat),
            "instrument_return": None if instrument_return is None else round(float(instrument_return), 4),
            "benchmark_return": None if benchmark_return is None else round(float(benchmark_return), 4),
            "beta_to_benchmark": None if beta is None else round(beta, 4),
            "correlation_to_benchmark": None if corr is None else round(corr, 4),
            "alpha_proxy": None if alpha_proxy is None else round(alpha_proxy, 4),
            "alpha_t_stat": None if alpha_t_stat is None else round(alpha_t_stat, 4),
        }
    return output


def write_market_regime(regime: dict[str, object], directory: Path = DERIVED_DIR) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "market_regime.json"
    csv_path = directory / "market_regime.csv"
    json_path.write_text(json.dumps(regime, indent=2, default=str), encoding="utf-8")
    pd.DataFrame([regime]).to_csv(csv_path, index=False)
    return json_path, csv_path


def _empty_regime(reason: str) -> dict[str, object]:
    return {
        "regime_score_10": None,
        "regime_label": "Regime unavailable",
        "summary": reason,
    }


def _candidate_pct_above_sma200(candidate_report: pd.DataFrame | None) -> float | None:
    if candidate_report is None or candidate_report.empty or "sma200_signal" not in candidate_report:
        return None
    values = candidate_report["sma200_signal"].map(_bool_like).dropna()
    if values.empty:
        return None
    return float(values.mean())


def _horizon_return(series: pd.Series, days: int) -> float | None:
    clean = series.dropna().astype(float)
    if len(clean) <= days:
        return None
    start = float(clean.iloc[-days - 1])
    end = float(clean.iloc[-1])
    if start <= 0:
        return None
    return (end / start) - 1.0


def _average_correlation(returns: pd.DataFrame) -> float | None:
    if returns.shape[1] < 2:
        return None
    corr = returns.corr()
    mask = np.triu(np.ones(corr.shape), k=1).astype(bool)
    values = corr.where(mask).stack().dropna()
    return float(values.mean()) if not values.empty else None


def _portfolio_fit_score(correlation: float, beta: float | None) -> float:
    score = 8.0 - max(correlation - 0.65, 0.0) * 6.0
    if beta is not None and beta > 1.25:
        score -= min((beta - 1.25) * 2.0, 1.5)
    return _clamp_score(score)


def _benchmark_attribution_label(
    benchmark_id: str,
    instrument_return: float | None,
    benchmark_return: float | None,
    beta: float | None,
    corr: float | None,
    alpha_proxy: float | None,
    alpha_t_stat: float | None,
) -> str:
    if instrument_return is None or benchmark_return is None:
        return "Benchmark attribution pending: return window is unavailable."
    t_text = "t-stat n/a" if alpha_t_stat is None else f"t-stat {alpha_t_stat:.2f}"
    return (
        f"Benchmark {benchmark_id}: instrument {_fmt_pct(instrument_return)}, benchmark {_fmt_pct(benchmark_return)}, "
        f"beta {_fmt_float(beta)}, corr {_fmt_float(corr)}, alpha proxy {_fmt_pct(alpha_proxy)} ({t_text}). "
        "Attribution is descriptive and does not prove causality."
    )


def _weighted_available(values: list[tuple[float | None, float]]) -> float:
    weighted = 0.0
    total = 0.0
    for value, weight in values:
        if value is None:
            continue
        weighted += value * weight
        total += weight
    return weighted / total if total > 0 else 0.0


def _regime_summary(label: str, score: float, pct_above: float, ret60: float | None, ret120: float | None, drawdown: float) -> str:
    return (
        f"{label}: regime {score:.1f}/10. {pct_above:.0%} of the yfinance universe is above SMA200; "
        f"benchmark 60d {_fmt_pct(ret60)}, 120d {_fmt_pct(ret120)}; median drawdown {_fmt_pct(drawdown)}."
    )


def _bool_like(value: object) -> bool | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1%}"


def _fmt_float(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _clamp_score(value: float) -> float:
    return max(0.0, min(10.0, float(value)))
