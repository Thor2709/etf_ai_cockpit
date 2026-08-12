from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from collections.abc import Mapping

import pandas as pd

from etf_cockpit.features.cash_comparison import validate_cash_comparison_result


@dataclass(frozen=True)
class AttributionResult:
    instrument_return: float | None
    benchmark_return: float | None
    beta: float | None
    correlation: float | None
    alpha_proxy: float | None
    alpha_t_stat: float | None
    sector_attribution: str
    sample_size: int
    sector_return: float | None = None
    sector_beta: float | None = None
    sector_correlation: float | None = None
    sector_relative_return: float | None = None
    sector_alpha_proxy: float | None = None
    sector_sample_size: int = 0
    theme_attribution: str = "N/A"
    theme_return: float | None = None
    theme_beta: float | None = None
    theme_correlation: float | None = None
    theme_relative_return: float | None = None
    theme_alpha_proxy: float | None = None
    theme_sample_size: int = 0
    as_of: str | None = None
    source_dataset: str = "adjusted_price_returns"
    status: str = "unavailable"
    reason: str = "Benchmark attribution unavailable."
    execution_allowed: bool = False
    cash_instrument_return: float | None = None
    cash_return: float | None = None
    excess_over_cash: float | None = None
    cash_currency: str | None = None
    cash_start_date: str | None = None
    cash_end_date: str | None = None
    cash_horizon_years: float | None = None
    cash_rate: float | None = None
    cash_vintage: str | None = None
    cash_comparison_status: str = "unavailable"
    cash_comparison_reason: str | None = "Cash comparison unavailable."
    cash_source_id: str | None = None
    cash_source_authority: str | None = None
    cash_source_checksum: str | None = None
    cash_source_terms: str | None = None
    cash_methodology: str | None = None
    cash_mapping_methodology: str | None = None
    cash_day_count: str | None = None
    cash_compounding: str | None = None
    cash_reinvestment: str | None = None
    cash_effective_at: str | None = None
    cash_published_at: str | None = None
    cash_available_at: str | None = None
    cash_curve_id: str | None = None
    cash_curve_version: str | None = None
    cash_curve_revision: int | None = None
    cash_curve_type: str | None = None
    cash_extrapolation_allowed: bool | None = None
    cash_fallback: bool | None = None
    cash_fallback_from: str | None = None
    cash_interpolation: str | None = None
    cash_freshness: str | None = None
    cash_freshness_status: str | None = None
    cash_decision_time: str | None = None
    cash_knowledge_cutoff: str | None = None
    inflation_context: object = None

    @property
    def broad_return(self) -> float | None:
        return self.benchmark_return

    @property
    def broad_beta(self) -> float | None:
        return self.beta

    @property
    def broad_correlation(self) -> float | None:
        return self.correlation


def build_benchmark_attribution(
    instrument_returns: pd.Series,
    broad_returns: pd.Series,
    sector_returns: pd.Series | None = None,
    theme_returns: pd.Series | None = None,
    cash_comparison: Mapping[str, object] | None = None,
    *,
    instrument_currency: str | None = None,
) -> AttributionResult:
    """Return descriptive broad and sector-relative attribution evidence.

    Returns are expected to be period returns, not prices. Values are aligned
    by timestamp where available, and no interpolation or forward-fill is
    performed. The result is informational and never execution authority.
    """

    broad_frame = pd.concat(
        [
            _clean_series(instrument_returns, "instrument"),
            _clean_series(broad_returns, "broad"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    cash = _cash_fields(cash_comparison, expected_currency=instrument_currency)
    if len(broad_frame) < 2:
        return _unavailable(
            "Fewer than two clean overlapping instrument/broad return observations are available.",
            cash_fields=cash,
        )

    instrument_return = _compound(broad_frame["instrument"])
    benchmark_return = _compound(broad_frame["broad"])
    beta, correlation = _beta_corr(broad_frame["instrument"], broad_frame["broad"])
    alpha_proxy = _alpha(instrument_return, benchmark_return, beta)
    alpha_t_stat = _alpha_t_stat(broad_frame["instrument"], broad_frame["broad"], beta)

    sector_return = sector_beta = sector_correlation = sector_relative_return = sector_alpha_proxy = None
    sector_sample_size = 0
    sector_status = "N/A"
    if sector_returns is not None:
        sector_frame = pd.concat(
            [
                _clean_series(instrument_returns, "instrument"),
                _clean_series(sector_returns, "sector"),
            ],
            axis=1,
            join="inner",
        ).dropna()
        sector_sample_size = len(sector_frame)
        if sector_sample_size >= 2:
            sector_status = "available"
            sector_return = _compound(sector_frame["sector"])
            sector_instrument_return = _compound(sector_frame["instrument"])
            sector_relative_return = sector_instrument_return - sector_return if sector_return is not None and sector_instrument_return is not None else None
            sector_beta, sector_correlation = _beta_corr(sector_frame["instrument"], sector_frame["sector"])
            sector_alpha_proxy = _alpha(sector_instrument_return, sector_return, sector_beta)

    theme_return = theme_beta = theme_correlation = theme_relative_return = theme_alpha_proxy = None
    theme_sample_size = 0
    theme_status = "N/A"
    if theme_returns is not None:
        theme_frame = pd.concat(
            [
                _clean_series(instrument_returns, "instrument"),
                _clean_series(theme_returns, "theme"),
            ],
            axis=1,
            join="inner",
        ).dropna()
        theme_sample_size = len(theme_frame)
        if theme_sample_size >= 2:
            theme_status = "available"
            theme_return = _compound(theme_frame["theme"])
            theme_instrument_return = _compound(theme_frame["instrument"])
            theme_relative_return = theme_instrument_return - theme_return if theme_instrument_return is not None and theme_return is not None else None
            theme_beta, theme_correlation = _beta_corr(theme_frame["instrument"], theme_frame["theme"])
            theme_alpha_proxy = _alpha(theme_instrument_return, theme_return, theme_beta)

    as_of = _as_of(broad_frame.index)
    return AttributionResult(
        instrument_return=instrument_return,
        benchmark_return=benchmark_return,
        beta=beta,
        correlation=correlation,
        alpha_proxy=alpha_proxy,
        alpha_t_stat=alpha_t_stat,
        sector_attribution=sector_status,
        sample_size=len(broad_frame),
        sector_return=sector_return,
        sector_beta=sector_beta,
        sector_correlation=sector_correlation,
        sector_relative_return=sector_relative_return,
        sector_alpha_proxy=sector_alpha_proxy,
        sector_sample_size=sector_sample_size,
        theme_attribution=theme_status,
        theme_return=theme_return,
        theme_beta=theme_beta,
        theme_correlation=theme_correlation,
        theme_relative_return=theme_relative_return,
        theme_alpha_proxy=theme_alpha_proxy,
        theme_sample_size=theme_sample_size,
        as_of=as_of,
        status="available",
        reason="Broad benchmark attribution computed from overlapping clean returns.",
        **cash,
    )


def _clean_series(series: pd.Series, name: str) -> pd.Series:
    if not isinstance(series, pd.Series):
        return pd.Series(dtype=float, name=name)
    result = pd.to_numeric(series, errors="coerce").replace([float("inf"), float("-inf")], pd.NA).dropna()
    result.name = name
    return result


def _compound(series: pd.Series) -> float | None:
    if series.empty:
        return None
    return float((1.0 + series.astype(float)).prod() - 1.0)


def _beta_corr(instrument: pd.Series, benchmark: pd.Series) -> tuple[float | None, float | None]:
    if len(instrument) < 2:
        return None, None
    variance = float(benchmark.var())
    beta = None if not isfinite(variance) or variance <= 0 else float(instrument.cov(benchmark) / variance)
    correlation = float(instrument.corr(benchmark))
    if not isfinite(correlation):
        correlation = None
    return beta, correlation


def _alpha(instrument_return: float | None, benchmark_return: float | None, beta: float | None) -> float | None:
    if instrument_return is None or benchmark_return is None or beta is None:
        return None
    return float(instrument_return - beta * benchmark_return)


def _alpha_t_stat(instrument: pd.Series, benchmark: pd.Series, beta: float | None) -> float | None:
    if beta is None or len(instrument) < 3:
        return None
    residual = instrument - beta * benchmark
    standard_deviation = float(residual.std())
    if not isfinite(standard_deviation) or standard_deviation <= 0:
        return None
    return float(residual.mean() / standard_deviation * (len(residual) ** 0.5))


def _as_of(index: pd.Index) -> str | None:
    if len(index) == 0:
        return None
    parsed = pd.to_datetime(index, errors="coerce")
    if len(parsed) == 0 or pd.isna(parsed.max()):
        return None
    return parsed.max().date().isoformat()


def _unavailable(
    reason: str,
    *,
    cash_fields: Mapping[str, object] | None = None,
) -> AttributionResult:
    return AttributionResult(
        None,
        None,
        None,
        None,
        None,
        None,
        "N/A",
        0,
        reason=reason,
        **(dict(cash_fields) if cash_fields is not None else {}),
    )


def _cash_fields(
    value: Mapping[str, object] | None,
    *,
    expected_currency: str | None = None,
) -> dict[str, object]:
    if value is not None and expected_currency is None:
        value = {
            "status": "unavailable",
            "reason": "instrument currency is unavailable for cash comparison",
        }
    value = validate_cash_comparison_result(value, expected_currency=expected_currency).as_dict()
    return {
        "cash_instrument_return": _optional_float(value.get("instrument_return")),
        "cash_return": _optional_float(value.get("cash_return")),
        "excess_over_cash": _optional_float(value.get("excess_over_cash")),
        "cash_currency": value.get("currency"),
        "cash_start_date": value.get("start_date"),
        "cash_end_date": value.get("end_date"),
        "cash_horizon_years": _optional_float(value.get("horizon_years")),
        "cash_rate": _optional_float(value.get("rate")),
        "cash_vintage": value.get("vintage"),
        "cash_comparison_status": str(value.get("status", "unavailable")),
        "cash_comparison_reason": value.get("reason") if value else "Cash comparison unavailable.",
        "cash_source_id": value.get("source_id"),
        "cash_source_authority": value.get("source_authority"),
        "cash_source_checksum": value.get("source_checksum"),
        "cash_source_terms": value.get("source_terms"),
        "cash_methodology": value.get("methodology"),
        "cash_mapping_methodology": value.get("mapping_methodology"),
        "cash_day_count": value.get("day_count"),
        "cash_compounding": value.get("compounding"),
        "cash_reinvestment": value.get("reinvestment"),
        "cash_effective_at": value.get("effective_at"),
        "cash_published_at": value.get("published_at"),
        "cash_available_at": value.get("available_at"),
        "cash_curve_id": value.get("curve_id"),
        "cash_curve_version": value.get("curve_version"),
        "cash_curve_revision": value.get("curve_revision"),
        "cash_curve_type": value.get("curve_type"),
        "cash_extrapolation_allowed": value.get("extrapolation_allowed"),
        "cash_fallback": value.get("fallback"),
        "cash_fallback_from": value.get("fallback_from"),
        "cash_interpolation": value.get("interpolation"),
        "cash_freshness": value.get("freshness"),
        "cash_freshness_status": value.get("freshness_status"),
        "cash_decision_time": value.get("decision_time"),
        "cash_knowledge_cutoff": value.get("knowledge_cutoff"),
        "inflation_context": value.get("inflation_context"),
    }


def _optional_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None
