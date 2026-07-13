from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import pandas as pd


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
    if len(broad_frame) < 2:
        return _unavailable("Fewer than two clean overlapping instrument/broad return observations are available.")

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


def _unavailable(reason: str) -> AttributionResult:
    return AttributionResult(None, None, None, None, None, None, "N/A", 0, reason=reason)
