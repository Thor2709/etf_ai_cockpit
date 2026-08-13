from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import log, sqrt
from pathlib import Path

import pandas as pd

from etf_cockpit.core.config import AppConfig, ProviderSection
from etf_cockpit.core.paths import RAW_DIR, REPORTS_DIR
from etf_cockpit.core.workflow import PublicationScopeFactory, publication_scope
from etf_cockpit.data.yfinance_provider import YFinanceProvider


@dataclass(frozen=True)
class CandidatePriceData:
    candidates: pd.DataFrame
    prices: pd.DataFrame
    effective_as_of: date
    source_message: str


@dataclass(frozen=True)
class CandidateAnalysisResult:
    rows: int
    csv_path: Path
    json_path: Path
    markdown_path: Path
    effective_as_of: date
    source_message: str


def latest_candidate_input(directory: Path = RAW_DIR / "trade_candidates") -> Path:
    files = sorted(directory.glob("yahoo_trade_candidates_*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No yfinance candidate CSV found in {directory}.")
    return files[0]


def fetch_candidate_prices(
    config: AppConfig,
    *,
    years: int = 5,
    as_of_date: date | None = None,
    candidate_path: Path | None = None,
) -> CandidatePriceData:
    path = candidate_path or latest_candidate_input()
    candidates = pd.read_csv(path)
    required = {"instrument_id", "yahoo_symbol"}
    missing = required - set(candidates.columns)
    if missing:
        raise ValueError(f"Candidate file {path} is missing columns: {sorted(missing)}")

    as_of = as_of_date or date.today()
    start = _years_back(as_of, years)
    section = ProviderSection(
        active_provider="yfinance",
        symbols_map={
            str(row.instrument_id): str(row.yahoo_symbol)
            for row in candidates.itertuples(index=False)
            if str(row.instrument_id).strip() and str(row.yahoo_symbol).strip()
        },
    )
    result = YFinanceProvider(section, default_currency=config.targets.base_currency).fetch_prices([], start, as_of)
    if not result.ok or result.data is None:
        raise RuntimeError(result.message)
    prices = result.data.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    effective_as_of = prices["date"].max().date()
    return CandidatePriceData(candidates=candidates, prices=prices, effective_as_of=effective_as_of, source_message=result.message)


def refresh_candidate_analysis(
    config: AppConfig,
    *,
    years: int = 5,
    as_of_date: date | None = None,
    candidate_path: Path | None = None,
    publish_guard: PublicationScopeFactory | None = None,
) -> CandidateAnalysisResult:
    data = fetch_candidate_prices(config, years=years, as_of_date=as_of_date, candidate_path=candidate_path)
    fundamentals = fetch_candidate_fundamentals(data.candidates)
    report = analyse_candidate_prices(data.candidates, data.prices, fundamentals=fundamentals)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with publication_scope(publish_guard):
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = REPORTS_DIR / f"yfinance_trade_candidate_analysis_{timestamp}.csv"
    json_path = REPORTS_DIR / f"yfinance_trade_candidate_analysis_{timestamp}.json"
    markdown_path = REPORTS_DIR / f"yfinance_trade_candidate_analysis_{timestamp}.md"
    with publication_scope(publish_guard):
        report.to_csv(csv_path, index=False)
    with publication_scope(publish_guard):
        json_path.write_text(json.dumps(report.to_dict(orient="records"), indent=2, default=str), encoding="utf-8")
    with publication_scope(publish_guard):
        markdown_path.write_text(_render_candidate_markdown(report, data.source_message), encoding="utf-8")
    return CandidateAnalysisResult(
        rows=len(report),
        csv_path=csv_path,
        json_path=json_path,
        markdown_path=markdown_path,
        effective_as_of=data.effective_as_of,
        source_message=data.source_message,
    )


def analyse_candidate_prices(
    candidates: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    fundamentals: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    lookup = candidates.set_index("instrument_id").to_dict(orient="index")
    fundamental_lookup = fundamentals.set_index("instrument_id").to_dict(orient="index") if fundamentals is not None and not fundamentals.empty else {}
    for instrument_id, group in prices.groupby("etf_id", sort=False):
        meta = {**lookup.get(str(instrument_id), {}), **fundamental_lookup.get(str(instrument_id), {})}
        rows.append(_analyse_one_candidate(str(instrument_id), meta, group))
    missing = sorted(set(candidates["instrument_id"].astype(str)) - set(prices["etf_id"].astype(str).unique()))
    for instrument_id in missing:
        meta = {**lookup.get(instrument_id, {}), **fundamental_lookup.get(instrument_id, {})}
        rows.append(_missing_candidate_row(instrument_id, meta, "No yfinance price rows were returned."))
    return pd.DataFrame(rows).sort_values(["advisory_status", "instrument_id"]).reset_index(drop=True)


def fetch_candidate_fundamentals(candidates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    try:
        import yfinance as yf
    except Exception as exc:
        return pd.DataFrame(
            [
                {
                    "instrument_id": str(row.get("instrument_id", "")),
                    "fundamental_warnings": f"yfinance import failed for fundamentals: {type(exc).__name__}: {exc}",
                    "fundamental_available": False,
                    "fundamental_missing_fields": "all_yfinance_fundamental_fields",
                    "fundamental_source": "yfinance",
                    "fundamental_limitations": "Fundamentals unavailable; missing data is not scored as bad data.",
                }
                for _, row in candidates.iterrows()
            ]
        )
    for _, candidate in candidates.iterrows():
        instrument_id = str(candidate.get("instrument_id") or "").strip()
        yahoo_symbol = str(candidate.get("yahoo_symbol") or "").strip()
        if not instrument_id or not yahoo_symbol:
            continue
        try:
            ticker = yf.Ticker(yahoo_symbol)
            info = _safe_dict(getattr(ticker, "info", {}))
            rows.append(_fundamental_row(instrument_id, yahoo_symbol, info))
        except Exception as exc:
            rows.append(
                {
                    "instrument_id": instrument_id,
                    "yahoo_symbol": yahoo_symbol,
                    "fundamental_warnings": f"fundamentals unavailable: {type(exc).__name__}: {exc}",
                    "fundamental_available": False,
                    "fundamental_missing_fields": "all_yfinance_fundamental_fields",
                    "fundamental_source": "yfinance",
                    "fundamental_limitations": "Fundamentals unavailable; missing data is not scored as bad data.",
                }
            )
    return pd.DataFrame(rows)


def _analyse_one_candidate(instrument_id: str, meta: dict[str, object], group: pd.DataFrame) -> dict[str, object]:
    group = group.sort_values("date").copy()
    adjusted = pd.to_numeric(group["adjusted_close"], errors="coerce").dropna()
    close = pd.to_numeric(group["close"], errors="coerce").dropna()
    volume = pd.to_numeric(group.get("volume", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    rows = int(len(adjusted))
    returns = _log_returns(adjusted)
    latest_price = _safe_float(close.iloc[-1]) if not close.empty else None
    shares = _safe_float(meta.get("shares")) or 0.0
    trade_value = latest_price * shares if latest_price is not None else None
    ret_1w = _horizon_return(adjusted, 5)
    ret_1m = _horizon_return(adjusted, 21)
    ret_3m = _horizon_return(adjusted, 63)
    ret_6m = _horizon_return(adjusted, 126)
    ret_12m = _horizon_return(adjusted, 252)
    vol20 = _annualised_vol(returns.tail(20))
    vol60 = _annualised_vol(returns.tail(60))
    sma50 = adjusted.rolling(50, min_periods=50).mean()
    sma200 = adjusted.rolling(200, min_periods=200).mean()
    sma50_signal = bool(adjusted.iloc[-1] > sma50.iloc[-1]) if rows >= 50 and pd.notna(sma50.iloc[-1]) else None
    sma200_signal = bool(adjusted.iloc[-1] > sma200.iloc[-1]) if rows >= 200 and pd.notna(sma200.iloc[-1]) else None
    drawdown_series = adjusted / adjusted.cummax() - 1.0 if rows else pd.Series(dtype=float)
    current_drawdown = _safe_float(drawdown_series.iloc[-1]) if not drawdown_series.empty else None
    max_drawdown_12m = _safe_float(drawdown_series.tail(252).min()) if not drawdown_series.empty else None
    high_52w = adjusted.tail(252).max() if rows else None
    distance_52w = _safe_float(adjusted.iloc[-1] / high_52w - 1.0) if high_52w and high_52w > 0 else None
    median_volume = _safe_float(volume.tail(60).median()) if len(volume) else None
    median_turnover = median_volume * latest_price if median_volume is not None and latest_price is not None else None
    score, flags = _technical_score(
        rows=rows,
        latest_price=latest_price,
        sma50_signal=sma50_signal,
        sma200_signal=sma200_signal,
        ret_1m=ret_1m,
        ret_3m=ret_3m,
        ret_6m=ret_6m,
        ret_12m=ret_12m,
        current_drawdown=current_drawdown,
        vol60=vol60,
        instrument_id=instrument_id,
    )
    asset_type = _candidate_asset_type(meta)
    return {
        "instrument_id": instrument_id,
        "name": str(meta.get("name", "")),
        "isin": str(meta.get("isin", "")),
        "yahoo_symbol": str(meta.get("yahoo_symbol", "")),
        "analysis_tier": str(meta.get("analysis_tier", "secondary")),
        "data_policy": str(meta.get("data_policy", "yfinance_only")),
        "instrument_type": str(meta.get("instrument_type", "")),
        "asset_type": asset_type,
        "shares": shares,
        "currency": str(meta.get("currency", "EUR")),
        "latest_date": str(pd.to_datetime(group["date"]).max().date()) if rows else "unknown",
        "source_dataset": "yfinance_adjusted_close",
        "provenance": "local candidate adjusted-close history",
        "latest_price": latest_price,
        "trade_value_eur": _safe_float(trade_value),
        "rows": rows,
        "return_1w": ret_1w,
        "return_1m": ret_1m,
        "return_3m": ret_3m,
        "return_6m": ret_6m,
        "return_12m": ret_12m,
        "volatility_20d_ann": vol20,
        "volatility_60d_ann": vol60,
        "current_drawdown": current_drawdown,
        "max_drawdown_12m": max_drawdown_12m,
        "distance_from_52w_high": distance_52w,
        "sma50_signal": sma50_signal,
        "sma200_signal": sma200_signal,
        "median_volume_60d": median_volume,
        "median_turnover_60d_eur": _safe_float(median_turnover),
        "high_low_spread_proxy_20": _high_low_spread_proxy(group.tail(20)),
        "market_cap": _safe_float(meta.get("market_cap")),
        "quote_type": str(meta.get("quote_type", "")),
        "trailing_pe": _safe_float(meta.get("trailing_pe")),
        "forward_pe": _safe_float(meta.get("forward_pe")),
        "price_to_book": _safe_float(meta.get("price_to_book")),
        "earnings_yield": _safe_float(meta.get("earnings_yield")),
        "fcf_yield": _safe_float(meta.get("fcf_yield")),
        "roe": _safe_float(meta.get("roe")),
        "operating_margin": _safe_float(meta.get("operating_margin")),
        "profit_margin": _safe_float(meta.get("profit_margin")),
        "debt_to_equity": _safe_float(meta.get("debt_to_equity")),
        "recommendation_mean": _safe_float(meta.get("recommendation_mean")),
        "value_score_10": _safe_float(meta.get("value_score_10")) if _is_stock_like_asset_type(asset_type) else None,
        "quality_score_10": _safe_float(meta.get("quality_score_10")) if _is_stock_like_asset_type(asset_type) else None,
        "analyst_revision_score_10": _safe_float(meta.get("analyst_revision_score_10")) if _is_stock_like_asset_type(asset_type) else None,
        "fundamental_warnings": str(meta.get("fundamental_warnings", "")),
        "fundamental_available": bool(meta.get("fundamental_available", False)),
        "fundamental_missing_fields": str(meta.get("fundamental_missing_fields", "")),
        "fundamental_source": str(meta.get("fundamental_source", "yfinance")),
        "fundamental_limitations": str(meta.get("fundamental_limitations", "Yahoo/yfinance fundamentals are unofficial vendor evidence and may be incomplete.")),
        "technical_score": score,
        "advisory_status": _status_from_score(score, flags),
        "blocked_by": ", ".join(flags),
        "reason_full": _reason(score, flags, ret_3m, ret_6m, ret_12m, current_drawdown, vol60),
    }


def _technical_score(
    *,
    rows: int,
    latest_price: float | None,
    sma50_signal: bool | None,
    sma200_signal: bool | None,
    ret_1m: float | None,
    ret_3m: float | None,
    ret_6m: float | None,
    ret_12m: float | None,
    current_drawdown: float | None,
    vol60: float | None,
    instrument_id: str,
) -> tuple[int, list[str]]:
    flags: list[str] = []
    score = 0
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
    if instrument_id == "VIE":
        flags.append("share_count_ambiguous_8_or_7")
    return score, flags


def _missing_candidate_row(instrument_id: str, meta: dict[str, object], reason: str) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "name": str(meta.get("name", "")),
        "isin": str(meta.get("isin", "")),
        "yahoo_symbol": str(meta.get("yahoo_symbol", "")),
        "analysis_tier": str(meta.get("analysis_tier", "secondary")),
        "data_policy": str(meta.get("data_policy", "yfinance_only")),
        "instrument_type": str(meta.get("instrument_type", "")),
        "asset_type": _candidate_asset_type(meta),
        "shares": _safe_float(meta.get("shares")) or 0.0,
        "currency": str(meta.get("currency", "EUR")),
        "latest_date": "unknown",
        "source_dataset": "yfinance_adjusted_close",
        "provenance": "local candidate adjusted-close history",
        "latest_price": None,
        "trade_value_eur": None,
        "rows": 0,
        "return_1w": None,
        "return_1m": None,
        "return_3m": None,
        "return_6m": None,
        "return_12m": None,
        "volatility_20d_ann": None,
        "volatility_60d_ann": None,
        "current_drawdown": None,
        "max_drawdown_12m": None,
        "distance_from_52w_high": None,
        "sma50_signal": None,
        "sma200_signal": None,
        "median_volume_60d": None,
        "median_turnover_60d_eur": None,
        "high_low_spread_proxy_20": None,
        "market_cap": _safe_float(meta.get("market_cap")),
        "quote_type": str(meta.get("quote_type", "")),
        "trailing_pe": _safe_float(meta.get("trailing_pe")),
        "forward_pe": _safe_float(meta.get("forward_pe")),
        "price_to_book": _safe_float(meta.get("price_to_book")),
        "earnings_yield": _safe_float(meta.get("earnings_yield")),
        "fcf_yield": _safe_float(meta.get("fcf_yield")),
        "roe": _safe_float(meta.get("roe")),
        "operating_margin": _safe_float(meta.get("operating_margin")),
        "profit_margin": _safe_float(meta.get("profit_margin")),
        "debt_to_equity": _safe_float(meta.get("debt_to_equity")),
        "recommendation_mean": _safe_float(meta.get("recommendation_mean")),
        "value_score_10": _safe_float(meta.get("value_score_10")),
        "quality_score_10": _safe_float(meta.get("quality_score_10")),
        "analyst_revision_score_10": _safe_float(meta.get("analyst_revision_score_10")),
        "fundamental_warnings": str(meta.get("fundamental_warnings", "")),
        "fundamental_available": bool(meta.get("fundamental_available", False)),
        "fundamental_missing_fields": str(meta.get("fundamental_missing_fields", "")),
        "fundamental_source": str(meta.get("fundamental_source", "yfinance")),
        "fundamental_limitations": str(meta.get("fundamental_limitations", "Yahoo/yfinance fundamentals are unofficial vendor evidence and may be incomplete.")),
        "technical_score": -99,
        "advisory_status": "manual_review",
        "blocked_by": "missing_price_data",
        "reason_full": reason,
    }


def _status_from_score(score: int, flags: list[str]) -> str:
    if {"missing_price_data", "missing_latest_price", "insufficient_12m_history"} & set(flags):
        return "manual_review"
    if score >= 5 and "below_sma200" not in flags and "deep_current_drawdown" not in flags:
        return "add_candidate"
    if score >= 3:
        return "watchlist"
    return "no_trade"


def _reason(
    score: int,
    flags: list[str],
    ret_3m: float | None,
    ret_6m: float | None,
    ret_12m: float | None,
    drawdown: float | None,
    vol60: float | None,
) -> str:
    parts = [
        f"Technical score {score}.",
        f"3m={_fmt_pct(ret_3m)}, 6m={_fmt_pct(ret_6m)}, 12m={_fmt_pct(ret_12m)}.",
        f"Current drawdown={_fmt_pct(drawdown)}, 60d vol={_fmt_pct(vol60)}.",
    ]
    parts.append("Flags: " + ", ".join(flags) + "." if flags else "No blocking technical flags from this price-only screen.")
    parts.append("Price-only screen; not a fundamental valuation or trade authorisation.")
    return " ".join(parts)


def _render_candidate_markdown(report: pd.DataFrame, source_message: str) -> str:
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
    for _, row in report.iterrows():
        lines.append(
            (
                f"| {row['instrument_id']} | {row['yahoo_symbol']} | "
                f"{_fmt_number(row['latest_price'])} | {_fmt_number(row['trade_value_eur'])} | "
                f"{row['technical_score']} | {row['advisory_status']} | {row['blocked_by'] or '-'} |"
            )
        )
    lines.append("")
    lines.append("## Details")
    for _, row in report.iterrows():
        lines.extend(["", f"### {row['instrument_id']} - {row['name']}", str(row["reason_full"])])
    return "\n".join(lines) + "\n"


def _fundamental_row(instrument_id: str, yahoo_symbol: str, info: dict[str, object]) -> dict[str, object]:
    quote_type = str(info.get("quoteType") or "").upper()
    market_cap = _safe_float(info.get("marketCap"))
    trailing_pe = _safe_float(info.get("trailingPE"))
    forward_pe = _safe_float(info.get("forwardPE"))
    price_to_book = _safe_float(info.get("priceToBook"))
    free_cashflow = _safe_float(info.get("freeCashflow"))
    roe = _safe_float(info.get("returnOnEquity"))
    operating_margin = _safe_float(info.get("operatingMargins"))
    profit_margin = _safe_float(info.get("profitMargins"))
    debt_to_equity = _safe_float(info.get("debtToEquity"))
    recommendation_mean = _safe_float(info.get("recommendationMean"))
    earnings_yield = (1.0 / trailing_pe) if trailing_pe and trailing_pe > 0 else None
    fcf_yield = (free_cashflow / market_cap) if free_cashflow is not None and market_cap and market_cap > 0 else None
    value_score = _value_score_10(trailing_pe=trailing_pe, forward_pe=forward_pe, price_to_book=price_to_book, fcf_yield=fcf_yield)
    quality_score = _quality_score_10(
        roe=roe,
        operating_margin=operating_margin,
        profit_margin=profit_margin,
        debt_to_equity=debt_to_equity,
    )
    analyst_score = _analyst_score_10(recommendation_mean)
    required_fields = {
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "price_to_book": price_to_book,
        "fcf_yield": fcf_yield,
        "roe": roe,
        "operating_margin": operating_margin,
        "profit_margin": profit_margin,
        "debt_to_equity": debt_to_equity,
        "recommendation_mean": recommendation_mean,
    }
    missing_fields = [name for name, value in required_fields.items() if value is None]
    warnings = []
    if value_score is None:
        warnings.append("value_fields_missing")
    if quality_score is None:
        warnings.append("quality_fields_missing")
    if missing_fields:
        warnings.append("missing_fields=" + "|".join(missing_fields))
    return {
        "instrument_id": instrument_id,
        "yahoo_symbol": yahoo_symbol,
        "quote_type": quote_type,
        "market_cap": market_cap,
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "price_to_book": price_to_book,
        "earnings_yield": earnings_yield,
        "fcf_yield": fcf_yield,
        "roe": roe,
        "operating_margin": operating_margin,
        "profit_margin": profit_margin,
        "debt_to_equity": debt_to_equity,
        "recommendation_mean": recommendation_mean,
        "value_score_10": value_score,
        "quality_score_10": quality_score,
        "analyst_revision_score_10": analyst_score,
        "fundamental_available": bool(len(missing_fields) < len(required_fields)),
        "fundamental_missing_fields": "|".join(missing_fields),
        "fundamental_source": "yfinance",
        "fundamental_limitations": "Yahoo/yfinance fundamentals are unofficial vendor evidence; missing fields stay N/A and do not count as bad values.",
        "fundamental_warnings": ", ".join(warnings),
    }


def _value_score_10(
    *,
    trailing_pe: float | None,
    forward_pe: float | None,
    price_to_book: float | None,
    fcf_yield: float | None,
) -> float | None:
    scores: list[float] = []
    if trailing_pe is not None and trailing_pe > 0:
        scores.append(_lower_is_better_score(trailing_pe, good=12.0, bad=45.0))
    if forward_pe is not None and forward_pe > 0:
        scores.append(_lower_is_better_score(forward_pe, good=10.0, bad=40.0))
    if price_to_book is not None and price_to_book > 0:
        scores.append(_lower_is_better_score(price_to_book, good=1.5, bad=10.0))
    if fcf_yield is not None:
        scores.append(_higher_is_better_score(fcf_yield, good=0.08, bad=-0.02))
    return _mean_score(scores)


def _quality_score_10(
    *,
    roe: float | None,
    operating_margin: float | None,
    profit_margin: float | None,
    debt_to_equity: float | None,
) -> float | None:
    scores: list[float] = []
    if roe is not None:
        scores.append(_higher_is_better_score(roe, good=0.18, bad=-0.05))
    if operating_margin is not None:
        scores.append(_higher_is_better_score(operating_margin, good=0.20, bad=0.0))
    if profit_margin is not None:
        scores.append(_higher_is_better_score(profit_margin, good=0.12, bad=-0.05))
    if debt_to_equity is not None and debt_to_equity >= 0:
        # Yahoo reports this as a percentage for many equities.
        scores.append(_lower_is_better_score(debt_to_equity, good=40.0, bad=250.0))
    return _mean_score(scores)


def _analyst_score_10(recommendation_mean: float | None) -> float | None:
    if recommendation_mean is None or recommendation_mean <= 0:
        return None
    return round(max(0.0, min(10.0, 10.0 * (5.0 - recommendation_mean) / 4.0)), 1)


def _higher_is_better_score(value: float, *, good: float, bad: float) -> float:
    if good == bad:
        return 5.0
    return round(max(0.0, min(10.0, 10.0 * (value - bad) / (good - bad))), 1)


def _lower_is_better_score(value: float, *, good: float, bad: float) -> float:
    if good == bad:
        return 5.0
    return round(max(0.0, min(10.0, 10.0 * (bad - value) / (bad - good))), 1)


def _mean_score(scores: list[float]) -> float | None:
    return None if not scores else round(sum(scores) / len(scores), 1)


def _candidate_asset_type(meta: dict[str, object]) -> str:
    explicit = str(meta.get("instrument_type") or "").strip().lower()
    if explicit == "etf":
        return "ETF"
    if explicit == "stock":
        return "Stock"
    if explicit == "certificate":
        return "Certificate"
    if explicit in {"equity_certificate", "equity certificate", "egenkapitalbevis"}:
        return "Equity certificate"
    quote_type = str(meta.get("quote_type") or "").upper()
    text = " ".join(str(meta.get(key) or "") for key in ("name", "notes", "instrument_id", "yahoo_symbol")).lower()
    if quote_type in {"ETF", "MUTUALFUND"} or "etf" in text or "ucits" in text:
        return "ETF"
    return "Stock"


def _is_stock_like_asset_type(asset_type: str) -> bool:
    return asset_type in {"Stock", "Certificate", "Equity certificate"}


def _high_low_spread_proxy(frame: pd.DataFrame) -> float | None:
    if frame.empty or not {"high", "low", "close"}.issubset(frame.columns):
        return None
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    proxy = ((high - low) / close).replace([float("inf"), float("-inf")], pd.NA).dropna()
    return _safe_float(proxy.mean()) if not proxy.empty else None


def _safe_dict(value: object) -> dict[str, object]:
    try:
        if value is None:
            return {}
        if hasattr(value, "items"):
            return dict(value.items())
        return dict(value)  # type: ignore[arg-type]
    except Exception:
        return {}


def _horizon_return(series: pd.Series, horizon: int) -> float | None:
    if len(series) <= horizon:
        return None
    latest = _safe_float(series.iloc[-1])
    prior = _safe_float(series.iloc[-1 - horizon])
    if latest is None or prior is None or latest <= 0 or prior <= 0:
        return None
    return log(latest / prior)


def _log_returns(series: pd.Series) -> pd.Series:
    shifted = series.shift(1)
    returns = (series / shifted).map(lambda value: log(value) if value and value > 0 else None)
    return pd.to_numeric(returns, errors="coerce").dropna()


def _annualised_vol(returns: pd.Series) -> float | None:
    if len(returns) < 10:
        return None
    return _safe_float(returns.std() * sqrt(252))


def _safe_float(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        number = float(value)
    except Exception:
        return None
    return number if pd.notna(number) else None


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _fmt_number(value: object) -> str:
    number = _safe_float(value)
    return "n/a" if number is None else f"{number:,.2f}"


def _years_back(as_of: date, years: int) -> date:
    try:
        return as_of.replace(year=as_of.year - years)
    except ValueError:
        return as_of.replace(month=2, day=28, year=as_of.year - years)
