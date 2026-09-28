"""Validated, descriptive OHLCV candle features."""

from __future__ import annotations

import math
from collections.abc import Mapping


CANDLE_SCORE_CAP = 0.25
_OHLC_FIELDS = ("open", "high", "low", "close")
_ADJUSTED_OHLC_FIELDS = tuple(f"adjusted_{field}" for field in _OHLC_FIELDS)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def prepare_adjusted_ohlcv(candle: Mapping[str, object]) -> dict[str, object]:
    """Project one OHLCV row to adjusted prices without mixing price bases."""

    adjusted_presence = tuple(field in candle for field in _ADJUSTED_OHLC_FIELDS)
    if "price_basis" in candle and all(field in candle for field in _OHLC_FIELDS):
        prices = {field: candle[field] for field in _OHLC_FIELDS}
        basis = candle.get("price_basis", "unavailable")
    elif any(adjusted_presence):
        if not all(adjusted_presence):
            return {
                "status": "unavailable",
                "reason": "adjusted_ohlc_incomplete",
                "execution_allowed": False,
            }
        prices = {name: candle[field] for name, field in zip(_OHLC_FIELDS, _ADJUSTED_OHLC_FIELDS, strict=True)}
        basis = "provided_adjusted_ohlc"
    elif "adjusted_close" in candle:
        close = _finite_number(candle.get("close"))
        adjusted_close = _finite_number(candle.get("adjusted_close"))
        if close is None or adjusted_close is None or close <= 0 or adjusted_close <= 0:
            return {
                "status": "unavailable",
                "reason": "same_row_adjustment_factor_unavailable",
                "execution_allowed": False,
            }
        raw_prices = {field: _finite_number(candle.get(field)) for field in _OHLC_FIELDS}
        if any(value is None for value in raw_prices.values()):
            return {
                "status": "unavailable",
                "reason": "raw_ohlc_unavailable_for_adjustment",
                "execution_allowed": False,
            }
        factor = adjusted_close / close
        prices = {field: float(value) * factor for field, value in raw_prices.items()}
        basis = "adjusted_ohlc_from_same_row_adjustment"
    else:
        prices = {field: candle.get(field) for field in _OHLC_FIELDS}
        basis = "raw_ohlc"

    result: dict[str, object] = {
        **prices,
        "volume": candle.get("volume"),
        "price_basis": basis,
        "status": "available",
        "execution_allowed": False,
    }
    if "date" in candle:
        result["date"] = candle["date"]
    elif "as_of_date" in candle:
        result["date"] = candle["as_of_date"]
    return result


def validate_ohlcv(candle: Mapping[str, object]) -> dict[str, object]:
    """Validate a complete OHLCV observation and return explicit reasons."""

    prepared = prepare_adjusted_ohlcv(candle)
    if prepared.get("status") != "available":
        return {
            "status": "invalid",
            "valid": False,
            "reasons": (str(prepared.get("reason", "ohlcv_unavailable")),),
            "execution_allowed": False,
        }

    values: dict[str, float] = {}
    reasons: list[str] = []
    for field in _OHLC_FIELDS:
        value = _finite_number(prepared.get(field))
        if value is None:
            reasons.append(f"invalid_{field}")
        else:
            values[field] = value
            if value <= 0:
                reasons.append(f"non_positive_{field}")
    volume = _finite_number(prepared.get("volume"))
    if volume is None:
        reasons.append("invalid_volume")
    elif volume < 0:
        reasons.append("negative_volume")

    if len(values) == len(_OHLC_FIELDS):
        low = values["low"]
        high = values["high"]
        if high < low:
            reasons.append("high_below_low")
        if values["open"] < low or values["open"] > high:
            reasons.append("open_outside_low_high")
        if values["close"] < low or values["close"] > high:
            reasons.append("close_outside_low_high")

    return {
        "status": "valid" if not reasons else "invalid",
        "valid": not reasons,
        "reasons": tuple(reasons),
        "values": values if not reasons else {},
        "price_basis": prepared.get("price_basis", "unavailable"),
        "execution_allowed": False,
    }


def calculate_candle_features(candle: Mapping[str, object]) -> dict[str, object]:
    """Calculate bounded descriptive features for a validated candle."""

    validation = validate_ohlcv(candle)
    if not validation["valid"]:
        return {
            "status": "unavailable",
            "reason": ", ".join(validation["reasons"]),
            "validation": validation,
            "execution_allowed": False,
        }

    values = validation["values"]
    open_price = values["open"]
    high = values["high"]
    low = values["low"]
    close = values["close"]
    candle_range = high - low
    body = abs(close - open_price)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    has_range = candle_range > 0
    return {
        "status": "available",
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": values.get("volume"),
        "price_basis": validation["price_basis"],
        "range": candle_range,
        "body": body,
        "body_fraction": body / candle_range if has_range else None,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "upper_wick_fraction": upper_wick / candle_range if has_range else None,
        "lower_wick_fraction": lower_wick / candle_range if has_range else None,
        "direction": "up" if close > open_price else "down" if close < open_price else "flat",
        "unavailable_reason": None if has_range else "zero_price_range",
        "execution_allowed": False,
    }
