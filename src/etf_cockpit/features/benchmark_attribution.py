from __future__ import annotations

from dataclasses import dataclass

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


def build_benchmark_attribution(instrument_returns: pd.Series, broad_returns: pd.Series, sector_returns: pd.Series | None = None) -> AttributionResult:
    frame = pd.concat([instrument_returns.rename("instrument"), broad_returns.rename("broad")], axis=1).dropna()
    if frame.empty:
        return AttributionResult(None, None, None, None, None, None, "N/A", 0)
    covariance = frame["instrument"].cov(frame["broad"])
    variance = frame["broad"].var()
    beta = None if not variance or pd.isna(variance) else float(covariance / variance)
    correlation = None if len(frame) < 2 else float(frame["instrument"].corr(frame["broad"]))
    instrument_return = float((1 + frame["instrument"]).prod() - 1)
    benchmark_return = float((1 + frame["broad"]).prod() - 1)
    alpha = instrument_return - benchmark_return * (beta if beta is not None else 1.0)
    sector_label = "N/A"
    if sector_returns is not None:
        aligned = pd.concat([frame["instrument"], sector_returns.rename("sector")], axis=1).dropna()
        sector_label = "available" if not aligned.empty else "N/A"
    return AttributionResult(instrument_return, benchmark_return, beta, correlation, float(alpha), None, sector_label, len(frame))
