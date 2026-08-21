from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd

from etf_cockpit.core.paths import DERIVED_DIR
from etf_cockpit.features.benchmark_attribution import build_benchmark_attribution
from etf_cockpit.portfolio.benchmark_reference_contract import (
    CanonicalBenchmarkRegistry,
    unavailable_reference_projection,
    validate_execution_disabled,
)
from etf_cockpit.application.benchmark_reference import validate_benchmark_reference
from etf_cockpit.application.benchmark_reference import clip_to_decision_window


def build_market_regime(
    prices: pd.DataFrame,
    candidate_report: pd.DataFrame | None = None,
    *,
    max_forward_fill: int | None = None,
    benchmark_id: str | None = None,
    benchmark_reference: Mapping[str, object] | None = None,
    benchmark_registry: CanonicalBenchmarkRegistry | None = None,
    peer_member_ids: Sequence[str] | None = None,
) -> dict[str, object]:
    validate_execution_disabled(benchmark_reference or _unavailable_reference())
    reference = dict(benchmark_reference or _unavailable_reference())
    canonical_benchmark_id = validate_benchmark_reference(
        benchmark_reference, benchmark_id, registry=benchmark_registry
    )
    if prices.empty or not {"etf_id", "date", "adjusted_close"}.issubset(prices.columns):
        return _empty_regime("No clean yfinance price panel is available.", benchmark_reference=reference)
    frame = _clip_to_reference_window(prices, reference)
    if frame.empty:
        return _empty_regime("The declared benchmark calculation window is unavailable.", benchmark_reference=reference)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    pivot = frame.dropna(subset=["date"]).pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
    pivot = pivot.dropna(how="all")
    if len(pivot) < 220:
        return _empty_regime("Less than 220 trading days are available for regime scoring.", benchmark_reference=reference)

    benchmark_id = canonical_benchmark_id
    if benchmark_id is None or benchmark_id not in pivot.columns:
        return _empty_regime(
            "Canonical benchmark/cash resolution is unavailable; regime comparison is N/A.",
            benchmark_reference=reference,
        )

    filled = pivot.ffill(limit=max_forward_fill)
    latest = filled.iloc[-1]
    sma200 = filled.rolling(200, min_periods=160).mean().iloc[-1]
    valid = latest.notna() & sma200.notna()
    above = (latest[valid] > sma200[valid]).dropna()
    configured_pct_above = float(above.mean()) if not above.empty else 0.0
    benchmark = pivot[benchmark_id].dropna()
    benchmark_above_sma200 = bool(latest.get(benchmark_id, np.nan) > sma200.get(benchmark_id, np.nan))
    benchmark_return_60d = _horizon_return(benchmark, 60)
    benchmark_return_120d = _horizon_return(benchmark, 120)
    returns = filled.pct_change(fill_method=None)
    median_vol_60d = float(returns.tail(60).std(skipna=True).median() * np.sqrt(252)) if len(returns) >= 60 else None
    drawdowns = filled / filled.cummax() - 1.0
    median_drawdown = float(drawdowns.iloc[-1].median(skipna=True))
    candidate_pct_above = _candidate_pct_above_sma200(
        candidate_report,
        decision_time=_reference_decision_time(reference),
    )
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
        "benchmark_reference": reference,
        "execution_allowed": False,
        "configured_pct_above_sma200": round(configured_pct_above, 4),
        "candidate_pct_above_sma200": None if candidate_pct_above is None else round(candidate_pct_above, 4),
        "combined_pct_above_sma200": round(combined_pct_above, 4),
        "median_volatility_60d_ann": None if median_vol_60d is None else round(median_vol_60d, 4),
        "median_current_drawdown": round(median_drawdown, 4),
        "average_correlation_60d": None if avg_corr_60d is None else round(avg_corr_60d, 4),
        "summary": _regime_summary(label, score, combined_pct_above, benchmark_return_60d, benchmark_return_120d, median_drawdown),
    }


def build_portfolio_fit_lookup(
    prices: pd.DataFrame,
    *,
    benchmark_id: str | None = None,
    benchmark_reference: Mapping[str, object] | None = None,
    benchmark_registry: CanonicalBenchmarkRegistry | None = None,
    peer_member_ids: Sequence[str] | None = None,
) -> dict[str, dict[str, object]]:
    validate_execution_disabled(benchmark_reference or _unavailable_reference())
    reference = dict(benchmark_reference or _unavailable_reference())
    if prices.empty or not {"etf_id", "date", "adjusted_close"}.issubset(prices.columns):
        return {}
    frame = _clip_to_reference_window(prices, reference)
    if frame.empty:
        return {}
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    pivot = frame.dropna(subset=["date", "adjusted_close"]).pivot(index="date", columns="etf_id", values="adjusted_close").sort_index().ffill()
    if pivot.shape[1] < 2:
        return {
            str(item): _unavailable_fit("not enough clean instruments", reference)
            for item in pivot.columns
        }
    benchmark_id = validate_benchmark_reference(
        benchmark_reference, benchmark_id, registry=benchmark_registry
    )
    if benchmark_id is None or benchmark_id not in pivot.columns:
        return {
            str(item): _unavailable_fit(
                "canonical benchmark/cash resolution is unavailable", reference
            )
            for item in pivot.columns
        }
    returns = pivot.pct_change(fill_method=None).tail(252).dropna(how="all")
    benchmark = returns[benchmark_id].dropna()
    output: dict[str, dict[str, object]] = {}
    for instrument_id in pivot.columns:
        series = returns[instrument_id].dropna()
        joined = pd.concat([series, benchmark], axis=1, join="inner").dropna()
        if len(joined) < 40:
            output[str(instrument_id)] = _unavailable_fit(
                "not enough overlapping returns", reference, label_prefix="Portfolio fit pending"
            )
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
            "benchmark_reference": reference,
            "execution_allowed": False,
        }
    return output


def build_benchmark_attribution_lookup(
    prices: pd.DataFrame,
    *,
    window: int = 120,
    benchmark_id: str | None = None,
    metadata: dict[str, object] | None = None,
    benchmark_reference: Mapping[str, object] | None = None,
    benchmark_registry: CanonicalBenchmarkRegistry | None = None,
    peer_member_ids: Sequence[str] | None = None,
) -> dict[str, dict[str, object]]:
    validate_execution_disabled(benchmark_reference or _unavailable_reference())
    reference = dict(benchmark_reference or _unavailable_reference())
    peer_member_ids = _canonical_peer_member_ids(reference, peer_member_ids)
    if prices.empty or not {"etf_id", "date", "adjusted_close"}.issubset(prices.columns):
        return {}
    frame = _clip_to_reference_window(prices, reference)
    if frame.empty:
        return {}
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    pivot = frame.dropna(subset=["date", "adjusted_close"]).pivot(index="date", columns="etf_id", values="adjusted_close").sort_index()
    if pivot.shape[1] < 2:
        return {
            str(item): _unavailable_attribution(
                str(item), window, "not enough clean instruments", reference
            )
            for item in pivot.columns
        }
    benchmark_id = validate_benchmark_reference(
        benchmark_reference, benchmark_id, registry=benchmark_registry
    )
    if benchmark_id is None or benchmark_id not in pivot.columns:
        return {
            str(item): _unavailable_attribution(
                str(item), window, "canonical benchmark/cash resolution is unavailable", reference
            )
            for item in pivot.columns
        }
    returns = pivot.pct_change(fill_method=None).dropna(how="all")
    benchmark_returns = returns[benchmark_id].dropna()
    output: dict[str, dict[str, object]] = {}
    metadata = metadata or {}
    for instrument_id in pivot.columns:
        instrument = str(instrument_id)
        series = returns[instrument_id].dropna()
        joined = pd.concat([series, benchmark_returns], axis=1, join="inner").dropna()
        joined.columns = ["instrument", "benchmark"]
        sample = joined.tail(window)
        if len(sample) < max(60, window // 2):
            output[instrument] = {
                "status": "N/A",
                "instrument_id": instrument,
                "benchmark_id": benchmark_id,
                "period_days": window,
                "label": "Benchmark attribution pending: not enough overlapping yfinance returns.",
                "instrument_return": None,
                "benchmark_return": None,
                "beta_to_benchmark": None,
                "correlation_to_benchmark": None,
                "alpha_proxy": None,
                "alpha_t_stat": None,
                "sector_return": None,
                "sector_relative_return": None,
                "sector_beta": None,
                "sector_correlation": None,
                "sector_alpha_proxy": None,
                "sector_attribution_status": "N/A",
                "sector_sample_size": 0,
                "theme_return": None,
                "theme_relative_return": None,
                "theme_beta": None,
                "theme_correlation": None,
                "theme_alpha_proxy": None,
                "theme_attribution_status": "N/A",
                "theme_sample_size": 0,
                "sample_size": len(sample),
                "as_of": sample.index.max().date().isoformat() if len(sample) else None,
                "source_dataset": "adjusted_price_returns",
                "benchmark_reference": reference,
                "execution_allowed": False,
            }
            continue
        broad_result = build_benchmark_attribution(sample["instrument"], sample["benchmark"])
        instrument_return = broad_result.instrument_return
        benchmark_return = broad_result.benchmark_return
        beta = broad_result.beta
        corr = broad_result.correlation
        alpha_proxy = broad_result.alpha_proxy
        alpha_t_stat = broad_result.alpha_t_stat
        sector_result = _sector_attribution_result(returns, str(instrument_id), peer_member_ids, window)
        theme_result = _peer_attribution_result(returns, str(instrument_id), peer_member_ids, "theme", window)
        output[instrument] = {
            "status": "available",
            "instrument_id": instrument,
            "benchmark_id": benchmark_id,
            "period_days": len(sample),
            "label": _benchmark_attribution_label(benchmark_id, instrument_return, benchmark_return, beta, corr, alpha_proxy, alpha_t_stat),
            "instrument_return": None if instrument_return is None else round(float(instrument_return), 4),
            "benchmark_return": None if benchmark_return is None else round(float(benchmark_return), 4),
            "beta_to_benchmark": None if beta is None else round(beta, 4),
            "correlation_to_benchmark": None if corr is None else round(corr, 4),
            "alpha_proxy": None if alpha_proxy is None else round(alpha_proxy, 4),
            "alpha_t_stat": None if alpha_t_stat is None else round(alpha_t_stat, 4),
            "sector_return": sector_result.get("sector_return"),
            "sector_relative_return": sector_result.get("sector_relative_return"),
            "sector_beta": sector_result.get("sector_beta"),
            "sector_correlation": sector_result.get("sector_correlation"),
            "sector_alpha_proxy": sector_result.get("sector_alpha_proxy"),
            "sector_attribution_status": sector_result.get("sector_attribution_status", "N/A"),
            "sector_sample_size": sector_result.get("sector_sample_size", 0),
            "theme_return": theme_result.get("theme_return"),
            "theme_relative_return": theme_result.get("theme_relative_return"),
            "theme_beta": theme_result.get("theme_beta"),
            "theme_correlation": theme_result.get("theme_correlation"),
            "theme_alpha_proxy": theme_result.get("theme_alpha_proxy"),
            "theme_attribution_status": theme_result.get("theme_attribution_status", "N/A"),
            "theme_sample_size": theme_result.get("theme_sample_size", 0),
            "sample_size": len(sample),
            "as_of": sample.index.max().date().isoformat() if len(sample) else None,
            "source_dataset": "adjusted_price_returns",
            "benchmark_reference": reference,
            "execution_allowed": False,
        }
    return output


def write_market_regime(regime: dict[str, object], directory: Path = DERIVED_DIR) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "market_regime.json"
    csv_path = directory / "market_regime.csv"
    json_path.write_text(json.dumps(regime, indent=2, default=str), encoding="utf-8")
    pd.DataFrame([regime]).to_csv(csv_path, index=False)
    return json_path, csv_path


def _empty_regime(
    reason: str,
    *,
    benchmark_reference: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "regime_score_10": None,
        "regime_label": "Regime unavailable",
        "benchmark_id": None,
        "benchmark_above_sma200": None,
        "benchmark_return_60d": None,
        "benchmark_return_120d": None,
        "configured_pct_above_sma200": None,
        "candidate_pct_above_sma200": None,
        "combined_pct_above_sma200": None,
        "median_volatility_60d_ann": None,
        "median_current_drawdown": None,
        "average_correlation_60d": None,
        "benchmark_reference": dict(benchmark_reference or _unavailable_reference()),
        "execution_allowed": False,
        "summary": reason,
    }


def _unavailable_reference() -> dict[str, object]:
    return unavailable_reference_projection()


def _unavailable_fit(
    reason: str,
    benchmark_reference: Mapping[str, object] | None = None,
    *,
    label_prefix: str = "Portfolio fit unavailable",
) -> dict[str, object]:
    return {
        "score": None,
        "label": f"{label_prefix}: {reason}.",
        "status": "N/A",
        "correlation_to_benchmark": None,
        "beta_to_benchmark": None,
        "benchmark_reference": dict(benchmark_reference or _unavailable_reference()),
        "execution_allowed": False,
    }


def _unavailable_attribution(
    instrument_id: str,
    window: int,
    reason: str,
    benchmark_reference: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "status": "N/A",
        "instrument_id": instrument_id,
        "benchmark_id": None,
        "period_days": window,
        "label": f"Benchmark attribution unavailable: {reason}.",
        "instrument_return": None,
        "benchmark_return": None,
        "beta_to_benchmark": None,
        "correlation_to_benchmark": None,
        "alpha_proxy": None,
        "alpha_t_stat": None,
        "sector_return": None,
        "sector_relative_return": None,
        "sector_beta": None,
        "sector_correlation": None,
        "sector_alpha_proxy": None,
        "sector_attribution_status": "N/A",
        "sector_sample_size": 0,
        "theme_return": None,
        "theme_relative_return": None,
        "theme_beta": None,
        "theme_correlation": None,
        "theme_alpha_proxy": None,
        "theme_attribution_status": "N/A",
        "theme_sample_size": 0,
        "sample_size": 0,
        "as_of": None,
        "source_dataset": "adjusted_price_returns",
        "benchmark_reference": dict(benchmark_reference or _unavailable_reference()),
        "execution_allowed": False,
    }


def _candidate_pct_above_sma200(
    candidate_report: pd.DataFrame | None,
    *,
    decision_time: object | None,
) -> float | None:
    if candidate_report is None or candidate_report.empty or "sma200_signal" not in candidate_report:
        return None
    frame = candidate_report.copy()
    decision = _parse_authority_timestamp(decision_time)
    if decision is None:
        return None
    values: list[bool] = []
    for _, row in frame.iterrows():
        signal = _bool_like(row.get("sma200_signal"))
        observation, observation_valid = _candidate_chronology(
            row,
            ("effective_at", "as_of", "as_of_date", "latest_date", "date"),
            date_only_end_of_day=True,
        )
        provenance = _candidate_provenance(row)
        known_at, knowledge_valid = _candidate_chronology(
            row,
            ("known_at", "available_at", "retrieved_at", "imported_at", "published_at"),
            date_only_end_of_day=True,
        )
        if (
            signal is None
            or observation is None
            or not observation_valid
            or not knowledge_valid
            or provenance is None
        ):
            continue
        if observation > decision or (known_at is not None and known_at > decision):
            continue
        values.append(signal)
    if not values:
        return None
    return float(sum(values) / len(values))


def _reference_decision_time(reference: Mapping[str, object]) -> object | None:
    analysis = reference.get("analysis")
    return analysis.get("decision_time") if isinstance(analysis, Mapping) else None


def _parse_authority_timestamp(
    value: object,
    *,
    date_only_end_of_day: bool = False,
) -> pd.Timestamp | None:
    if isinstance(value, (bool, int, float, np.number)) or value is None:
        return None
    text = value.strip() if isinstance(value, str) else str(value).strip()
    if not text:
        return None
    try:
        parsed = pd.Timestamp(value)
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize("UTC")
        parsed = parsed.tz_convert("UTC")
        date_only = isinstance(value, date) and not isinstance(value, datetime)
        if date_only_end_of_day and (date_only or (len(text) == 10 and text[4] == "-" and text[7] == "-")):
            parsed = parsed.normalize() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        return parsed
    except (TypeError, ValueError, OverflowError):
        return None


def _candidate_chronology(
    row: pd.Series,
    fields: tuple[str, ...],
    *,
    date_only_end_of_day: bool = False,
) -> tuple[pd.Timestamp | None, bool]:
    populated: list[object] = []
    for field in fields:
        if field not in row:
            continue
        value = row.get(field)
        if not pd.api.types.is_scalar(value):
            return None, False
        if pd.isna(value):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        populated.append(value)
    if not populated:
        return None, True
    parsed_values: list[pd.Timestamp] = []
    for value in populated:
        parsed = _parse_authority_timestamp(value, date_only_end_of_day=date_only_end_of_day)
        if parsed is None:
            return None, False
        parsed_values.append(parsed)
    return max(parsed_values), True


def _candidate_timestamp(row: pd.Series, fields: tuple[str, ...]) -> pd.Timestamp | None:
    value, valid = _candidate_chronology(row, fields, date_only_end_of_day=True)
    return value if valid else None


def _candidate_observation_timestamp(row: pd.Series) -> pd.Timestamp | None:
    value, valid = _candidate_chronology(
        row,
        ("effective_at", "as_of", "as_of_date", "latest_date", "date"),
        date_only_end_of_day=True,
    )
    return value if valid else None


def _candidate_provenance(row: pd.Series) -> str | None:
    for field in ("provenance", "source_dataset", "source_id", "source", "data_policy"):
        if field not in row:
            continue
        value = row.get(field)
        if not pd.api.types.is_scalar(value):
            return None
        if not pd.isna(value) and str(value).strip():
            return str(value).strip()
    return None


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
    values: list[float] = []
    for left_index, left in enumerate(returns.columns):
        for right in returns.columns[left_index + 1:]:
            joined = returns[[left, right]].dropna()
            if len(joined) < 3:
                continue
            correlation = joined.iloc[:, 0].corr(joined.iloc[:, 1])
            if correlation is not None and np.isfinite(correlation):
                values.append(float(correlation))
    return float(np.mean(values)) if values else None


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


def _sector_attribution_result(
    returns: pd.DataFrame,
    instrument_id: str,
    peer_member_ids: Sequence[str] | None,
    window: int,
) -> dict[str, object]:
    return _peer_attribution_result(returns, instrument_id, peer_member_ids, "sector", window)


def _peer_attribution_result(
    returns: pd.DataFrame,
    instrument_id: str,
    peer_member_ids: Sequence[str] | None,
    dimension: str,
    window: int,
) -> dict[str, object]:
    prefix = dimension
    if not peer_member_ids:
        return {f"{prefix}_attribution_status": "N/A", f"{prefix}_sample_size": 0}
    peers = [str(peer) for peer in peer_member_ids if str(peer) in returns.columns and str(peer) != instrument_id]
    if not peers:
        return {f"{prefix}_attribution_status": "N/A", f"{prefix}_sample_size": 0}
    peer_returns = returns[peers].mean(axis=1, skipna=False).rename(prefix)
    instrument = returns[instrument_id].rename("instrument")
    joined = pd.concat([instrument, peer_returns], axis=1, join="inner").dropna().tail(window)
    if len(joined) < 3:
        return {f"{prefix}_attribution_status": "N/A", f"{prefix}_sample_size": len(joined)}
    result = build_benchmark_attribution(joined["instrument"], joined[prefix])
    relative_return = None
    if result.instrument_return is not None and result.benchmark_return is not None:
        relative_return = round(result.instrument_return - result.benchmark_return, 4)
    return {
        f"{prefix}_return": None if result.benchmark_return is None else round(result.benchmark_return, 4),
        f"{prefix}_relative_return": relative_return,
        f"{prefix}_beta": None if result.beta is None else round(result.beta, 4),
        f"{prefix}_correlation": None if result.correlation is None else round(result.correlation, 4),
        f"{prefix}_alpha_proxy": None if result.alpha_proxy is None else round(result.alpha_proxy, 4),
        f"{prefix}_attribution_status": "available" if result.status == "available" else "N/A",
        f"{prefix}_sample_size": len(joined),
    }


def _canonical_peer_member_ids(
    reference: Mapping[str, object],
    peer_member_ids: Sequence[str] | None,
) -> tuple[str, ...] | None:
    peer = reference.get("peer_set")
    selected_records = reference.get("selected_records")
    if (
        reference.get("status") != "available"
        or not isinstance(peer, Mapping)
        or peer.get("status") != "available"
        or not isinstance(selected_records, Mapping)
        or selected_records.get("peer_set") != peer.get("content_hash")
        or not isinstance(peer.get("member_instrument_ids"), Sequence)
    ):
        return None
    members = peer.get("member_instrument_ids")
    if not isinstance(members, Sequence) or isinstance(members, (str, bytes)):
        return None
    if any(not isinstance(item, str) or not item.strip() for item in members):
        return None
    return tuple(dict.fromkeys(item.strip() for item in members))


def _clip_to_reference_window(
    prices: pd.DataFrame,
    reference: Mapping[str, object],
) -> pd.DataFrame:
    analysis = reference.get("analysis")
    if reference.get("status") != "available":
        return prices
    if not isinstance(analysis, Mapping):
        return pd.DataFrame()
    start = analysis.get("start_date")
    end = analysis.get("end_date")
    decision_time = analysis.get("decision_time")
    if not all(isinstance(value, str) and value for value in (start, end, decision_time)):
        return pd.DataFrame()
    return clip_to_decision_window(
        prices,
        start_date=start,
        end_date=end,
        decision_time=decision_time,
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
    if value is None or not pd.api.types.is_scalar(value):
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
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
