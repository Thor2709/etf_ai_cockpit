"""Low-authority OHLCV candle evidence and simulation helpers."""

from etf_cockpit.analysis.candles.backtest_safety import backtest_candle_templates
from etf_cockpit.analysis.candles.features import (
    CANDLE_SCORE_CAP,
    calculate_candle_features,
    prepare_adjusted_ohlcv,
    validate_ohlcv,
)
from etf_cockpit.analysis.candles.templates import (
    detect_candle_templates,
    score_candle_contribution,
)

__all__ = [
    "CANDLE_SCORE_CAP",
    "backtest_candle_templates",
    "calculate_candle_features",
    "detect_candle_templates",
    "prepare_adjusted_ohlcv",
    "score_candle_contribution",
    "validate_ohlcv",
]
