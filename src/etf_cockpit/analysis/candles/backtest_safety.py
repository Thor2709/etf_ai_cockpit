"""Next-bar-only candle template simulation with OHLC ambiguity reporting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

from etf_cockpit.analysis.candles.features import calculate_candle_features, prepare_adjusted_ohlcv
from etf_cockpit.analysis.candles.templates import detect_candle_templates


_BULLISH = frozenset({"gap_up", "bullish_rejection"})
_BEARISH = frozenset({"gap_down", "bearish_rejection"})


def backtest_candle_templates(
    candles: Sequence[Mapping[str, object]],
    *,
    stop_pct: float = 0.02,
    target_pct: float = 0.04,
) -> dict[str, object]:
    """Simulate template observations entering at the immediately following open.

    The function is a descriptive simulation only. A bar that reaches both its
    stop and target is marked ambiguous and receives no assumed exit fill.
    """

    if not math.isfinite(float(stop_pct)) or not math.isfinite(float(target_pct)) or stop_pct <= 0 or target_pct <= 0:
        raise ValueError("stop_pct and target_pct must be finite positive numbers")

    prepared = [prepare_adjusted_ohlcv(candle) for candle in candles]
    rows: list[dict[str, object]] = []
    for decision_index in range(max(0, len(prepared) - 1)):
        decision_candle = candles[decision_index]
        prior = candles[decision_index - 1] if decision_index > 0 else None
        templates = detect_candle_templates(decision_candle, prior)
        patterns = tuple(templates.get("patterns", ()))
        if not patterns:
            continue

        bullish = any(pattern in _BULLISH for pattern in patterns)
        bearish = any(pattern in _BEARISH for pattern in patterns)
        signal_date = decision_candle.get("date", decision_candle.get("as_of_date"))
        execution_candle = prepared[decision_index + 1]
        execution_date = candles[decision_index + 1].get("date", candles[decision_index + 1].get("as_of_date"))
        if bullish and bearish:
            rows.append({
                "status": "ambiguous_signal",
                "signal_date": signal_date,
                "execution_date": execution_date,
                "patterns": patterns,
                "entry_price": None,
                "exit_price": None,
                "fill_assumed": False,
                "ambiguity_reason": "conflicting_pattern_directions",
            })
            continue
        if execution_candle.get("status") != "available":
            rows.append({
                "status": "unavailable",
                "signal_date": signal_date,
                "execution_date": execution_date,
                "patterns": patterns,
                "entry_price": None,
                "exit_price": None,
                "fill_assumed": False,
                "reason": execution_candle.get("reason", "next_bar_ohlcv_unavailable"),
            })
            continue

        entry_features = calculate_candle_features(execution_candle)
        if entry_features.get("status") != "available":
            rows.append({
                "status": "unavailable",
                "signal_date": signal_date,
                "execution_date": execution_date,
                "patterns": patterns,
                "entry_price": None,
                "exit_price": None,
                "fill_assumed": False,
                "reason": entry_features.get("reason", "next_bar_ohlcv_unavailable"),
            })
            continue

        entry = float(entry_features["open"])
        high = float(entry_features["high"])
        low = float(entry_features["low"])
        side = "long" if bullish else "short"
        stop = entry * (1.0 - stop_pct if side == "long" else 1.0 + stop_pct)
        target = entry * (1.0 + target_pct if side == "long" else 1.0 - target_pct)
        stop_hit = low <= stop if side == "long" else high >= stop
        target_hit = high >= target if side == "long" else low <= target
        if stop_hit and target_hit:
            rows.append({
                "status": "ambiguous",
                "signal_date": signal_date,
                "execution_date": execution_date,
                "patterns": patterns,
                "side": side,
                "entry_price": entry,
                "exit_price": None,
                "stop_price": stop,
                "target_price": target,
                "fill_assumed": False,
                "ambiguous": True,
                "ambiguity_reason": "stop_and_target_inside_same_bar",
            })
            continue

        exit_price = stop if stop_hit else target if target_hit else None
        rows.append({
            "status": "closed" if exit_price is not None else "open_no_exit",
            "signal_date": signal_date,
            "execution_date": execution_date,
            "patterns": patterns,
            "side": side,
            "entry_price": entry,
            "exit_price": exit_price,
            "stop_price": stop,
            "target_price": target,
            "fill_assumed": True,
            "ambiguous": False,
            "execution_basis": "next_bar_open",
        })

    ambiguous = sum(bool(row.get("ambiguous")) for row in rows)
    valid_candles = sum(calculate_candle_features(candle).get("status") == "available" for candle in candles)
    backtest_available = len(prepared) >= 2 and valid_candles >= 2
    for row in rows:
        row.setdefault("execution_basis", "next_bar_open")
        row["action"] = "none"
        row["execution_allowed"] = False
        row["action_authority"] = False
        row["simulation_only"] = True
    return {
        "status": "available" if backtest_available else "unavailable",
        "reason": None if backtest_available else "at_least_two_valid_ohlcv_observations_required",
        "execution_basis": "next_bar_open",
        "rows": rows,
        "backtest_count": len(rows),
        "ambiguity_count": ambiguous,
        "ambiguity_warning": (
            f"{ambiguous} same-bar stop/target ambiguity(ies); no ambiguous exit fill assumed."
            if ambiguous
            else "No same-bar stop/target ambiguity reported."
        ) if backtest_available else "Backtest unavailable; at least two valid OHLCV observations are required.",
        "simulation_only": True,
        "action_authority": False,
        "execution_allowed": False,
    }
