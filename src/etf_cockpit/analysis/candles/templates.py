"""Low-authority single and adjacent-bar candle templates."""

from __future__ import annotations

from collections.abc import Mapping

from etf_cockpit.analysis.candles.features import calculate_candle_features, validate_ohlcv


_PATTERN_WEIGHTS = {
    "gap_up": 0.10,
    "gap_down": -0.10,
    "bullish_rejection": 0.15,
    "bearish_rejection": -0.15,
}


def detect_candle_templates(
    candle: Mapping[str, object],
    previous_candle: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Detect simple gap and rejection templates without assigning action."""

    features = calculate_candle_features(candle)
    if features.get("status") != "available":
        return {
            "status": "unavailable",
            "reason": features.get("reason", "candle_features_unavailable"),
            "patterns": (),
            "template": "unavailable",
            "action": "none",
            "action_authority": False,
            "execution_allowed": False,
        }

    patterns: list[str] = []
    previous_validation = validate_ohlcv(previous_candle) if previous_candle is not None else None
    if previous_validation is not None and previous_validation.get("valid"):
        previous_close = previous_validation["values"]["close"]
        if features["open"] > previous_close:
            patterns.append("gap_up")
        elif features["open"] < previous_close:
            patterns.append("gap_down")

    candle_range = float(features["range"])
    body = float(features["body"])
    if candle_range > 0:
        rejection_threshold = max(body * 2.0, candle_range * 0.5)
        if features["lower_wick"] >= rejection_threshold and features["close"] >= features["open"]:
            patterns.append("bullish_rejection")
        if features["upper_wick"] >= rejection_threshold and features["close"] <= features["open"]:
            patterns.append("bearish_rejection")

    template = "+".join(patterns) if patterns else "no_useful_signal"
    return {
        "status": "available" if patterns else "no_useful_signal",
        "template": template,
        "patterns": tuple(patterns),
        "previous_close_status": (
            "available"
            if previous_validation is not None and previous_validation.get("valid")
            else "unavailable"
        ),
        "reason": None if patterns else "no_named_template_matched",
        "action": "none",
        "action_authority": False,
        "execution_allowed": False,
    }


def score_candle_contribution(
    templates: Mapping[str, object],
    *,
    cap: float = 0.25,
) -> dict[str, object]:
    """Return a signed, capped score contribution; never an action."""

    import math

    if not math.isfinite(float(cap)) or cap <= 0:
        raise ValueError("cap must be a finite positive number")
    patterns = templates.get("patterns", ())
    if not isinstance(patterns, (list, tuple)):
        patterns = ()
    values = [
        _PATTERN_WEIGHTS[pattern]
        for pattern in patterns
        if isinstance(pattern, str) and pattern in _PATTERN_WEIGHTS
    ]
    if not values:
        return {
            "status": "unavailable",
            "contribution": None,
            "cap": float(cap),
            "reason": templates.get("reason", "no_useful_signal"),
            "action": "none",
            "action_authority": False,
            "execution_allowed": False,
        }

    raw_contribution = sum(values)
    if raw_contribution == 0:
        return {
            "status": "unavailable",
            "contribution": None,
            "cap": float(cap),
            "reason": "conflicting_pattern_evidence",
            "action": "none",
            "action_authority": False,
            "execution_allowed": False,
        }
    contribution = max(-float(cap), min(float(cap), raw_contribution))
    return {
        "status": "available",
        "contribution": contribution,
        "cap": float(cap),
        "uncapped_contribution": raw_contribution,
        "reason": None,
        "action": "none",
        "action_authority": False,
        "execution_allowed": False,
    }
