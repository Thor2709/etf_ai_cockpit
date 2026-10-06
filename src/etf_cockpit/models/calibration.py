from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from math import ceil, isfinite, log, sqrt
from numbers import Real
from pathlib import Path

import numpy as np
import pandas as pd

from etf_cockpit.core.paths import DERIVED_DIR, FORECASTS_DIR


CALIBRATION_COLUMNS = [
    "instrument_id",
    "model_name",
    "evaluated_forecasts",
    "matured_forecasts",
    "oos_mase",
    "oos_directional_accuracy",
    "q10_q90_coverage",
    "calibration_score_10",
    "calibration_status",
    "calibration_label",
]
_CONFORMAL_NOMINAL_COVERAGE = 0.80
_CONFORMAL_QUANTILES = (5, 10, 25, 50, 75, 90, 95)


def conformal_quantile_adjustment(
    nonconformity_scores: Iterable[object],
    *,
    minimum_matured_samples: int,
    target_coverage: float = _CONFORMAL_NOMINAL_COVERAGE,
) -> dict[str, object]:
    """Return the finite-sample split-conformal upper order statistic.

    The rank is ``ceil((n + 1) * target_coverage)`` (one based), capped at
    ``n``. The caller supplies only scores from predictions whose outcomes
    matured strictly before its decision time.
    """

    minimum_value = _finite_number(minimum_matured_samples)
    coverage_value = _finite_number(target_coverage)
    if minimum_value is None or not minimum_value.is_integer() or coverage_value is None:
        return {"status": "unavailable", "reason": "Conformal thresholds are invalid.", "adjustment": None, "sample_count": 0}
    minimum = int(minimum_value)
    coverage = coverage_value
    if minimum < 1 or not 0 < coverage < 1:
        return {"status": "unavailable", "reason": "Conformal thresholds are invalid.", "adjustment": None, "sample_count": 0}
    scores = np.asarray(
        [float(value) for value in nonconformity_scores if _finite_number(value) is not None],
        dtype=float,
    )
    scores = scores[np.isfinite(scores) & (scores >= 0)]
    count = int(scores.size)
    if count < minimum:
        return {
            "status": "unavailable",
            "reason": f"Only {count} matured calibration samples are available; {minimum} are required.",
            "adjustment": None,
            "sample_count": count,
        }
    rank = min(count, ceil((count + 1) * coverage))
    adjustment = float(np.partition(scores, rank - 1)[rank - 1])
    return {"status": "available", "reason": None, "adjustment": adjustment, "sample_count": count}


def coverage_confidence_interval(hits: Iterable[object]) -> tuple[float, float] | None:
    """Return the two-sided 95% Wilson interval for Bernoulli coverage hits."""

    values = [float(value) for value in hits if _finite_number(value) in (0.0, 1.0)]
    count = len(values)
    if not count:
        return None
    successes = sum(values)
    z = 1.96  # Standard normal 95% confidence level, conservative at small n.
    proportion = successes / count
    denominator = 1 + z * z / count
    centre = (proportion + z * z / (2 * count)) / denominator
    radius = z * sqrt((proportion * (1 - proportion) / count) + z * z / (4 * count * count)) / denominator
    return max(0.0, centre - radius), min(1.0, centre + radius)


def calibrate_forecast_distribution(
    forecasts: pd.DataFrame,
    prices: pd.DataFrame,
    distribution: Mapping[str, object] | None,
    *,
    instrument_id: str,
    decision_time: object,
    settings: object | None,
) -> dict[str, object]:
    """Apply a point-in-time split-conformal adjustment to one forecast band.

    Rows are matched on instrument and exact horizon, require successful,
    score-eligible predictions with explicit 10th and 90th quantiles, and use
    adjusted-close outcomes at the corresponding trading-session horizon.
    Outcomes on the decision date are excluded because date-only prices do
    not establish whether they were known before an intraday decision.
    """

    output = dict(distribution) if isinstance(distribution, Mapping) else {}
    probability_fields = ("probability_loss", "probability_beat_cash", "probability_beat_benchmark")
    for field in probability_fields:
        output[field] = None
    output["probability_calibration_status"] = "unavailable"
    output["probability_calibration_reason"] = "Matching calibrated probability evidence is unavailable."
    metadata: dict[str, object] = {
        "status": "unavailable",
        "reason": "Forecast calibration inputs are unavailable.",
        "sample_count": 0,
        "empirical_coverage": None,
        "coverage_confidence_interval": None,
        "confidence_interval_method": "wilson_95",
        "nominal_coverage": _CONFORMAL_NOMINAL_COVERAGE,
        "coverage_tolerance": None,
        "adjustment": None,
        "poor_calibration": False,
        "model_construction": [],
    }
    output["conformal_calibration"] = metadata

    model_construction = _distribution_model_construction(output)
    if model_construction is None:
        metadata["reason"] = "Target model identity is missing or invalid for calibration."
        return output
    metadata["model_construction"] = model_construction

    minimum = _setting_number(settings, "minimum_matured_samples", integer=True)
    tolerance = _setting_number(settings, "coverage_tolerance")
    if minimum is None or minimum < 2 or tolerance is None or not 0 <= tolerance <= 0.2:
        metadata["reason"] = "Forecast calibration configuration is missing or invalid."
        return output
    metadata["coverage_tolerance"] = tolerance
    cutoff = _decision_cutoff(decision_time)
    if cutoff is None:
        metadata["reason"] = "A valid decision time is required for point-in-time calibration."
        return output
    horizon = _finite_number(output.get("horizon_days"))
    q10 = _finite_number(output.get("q10_return"))
    q50 = _finite_number(output.get("q50_return"))
    q90 = _finite_number(output.get("q90_return"))
    if horizon is None or horizon <= 0 or not horizon.is_integer() or q10 is None or q50 is None or q90 is None:
        metadata["reason"] = "A valid horizon and complete q10/q50/q90 forecast band are required."
        return output
    output = _repair_distribution_quantiles(output)
    output["conformal_calibration"] = metadata
    if not isinstance(forecasts, pd.DataFrame) or forecasts.empty:
        metadata["reason"] = "Historical forecast rows are unavailable."
        return output
    forecast_columns = {
        "etf_id", "model_name", "forecast_date", "horizon_days", "expected_return",
        "q10_return", "q90_return", "status", "model_allowed_in_score", "model_id",
        "prediction_id", "fold_id", "out_of_fold",
    }
    if not forecast_columns.issubset(forecasts.columns):
        metadata["reason"] = "Historical forecasts are missing out-of-fold model and prediction provenance."
        return output
    price_columns = {"etf_id", "date", "adjusted_close"}
    if not isinstance(prices, pd.DataFrame) or prices.empty or not price_columns.issubset(prices.columns):
        metadata["reason"] = "A dated adjusted-close price snapshot is unavailable."
        return output

    decision_day = cutoff.normalize()
    price_columns = ["date", "adjusted_close", *(column for column in ("is_stale", "stale", "staleness_status", "freshness_status") if column in prices)]
    price_frame = prices.loc[prices["etf_id"].astype(str).eq(str(instrument_id)), price_columns].copy()
    price_frame["date"] = pd.to_datetime(price_frame["date"], errors="coerce", utc=True, format="mixed").dt.normalize()
    price_frame["adjusted_close"] = pd.to_numeric(price_frame["adjusted_close"], errors="coerce")
    price_frame = price_frame.loc[
        price_frame["date"].notna()
        & price_frame["date"].lt(decision_day)
    ].sort_values("date", kind="stable")
    if price_frame["date"].duplicated().any():
        metadata["reason"] = "Conflicting price rows prevent point-in-time calibration."
        return output
    price_dates = pd.DatetimeIndex(price_frame["date"])
    closes = price_frame["adjusted_close"].to_numpy(dtype=float)
    stale_prices = price_frame.apply(_price_is_stale, axis=1).to_numpy(dtype=bool)
    if len(price_dates) <= int(horizon):
        metadata["reason"] = "The price snapshot does not contain matured target sessions."
        return output

    history = forecasts.loc[
        forecasts["etf_id"].astype(str).eq(str(instrument_id))
        & pd.to_numeric(forecasts["horizon_days"], errors="coerce").eq(int(horizon))
        & forecasts["status"].astype(str).str.lower().eq("ok")
        & forecasts["model_allowed_in_score"].astype(str).str.lower().isin({"true", "1", "yes"})
    ].copy()
    history["forecast_date"] = pd.to_datetime(history["forecast_date"], errors="coerce", utc=True, format="mixed").dt.normalize()
    history["expected_return"] = pd.to_numeric(history["expected_return"], errors="coerce")
    history["q10_return"] = pd.to_numeric(history["q10_return"], errors="coerce")
    history["q90_return"] = pd.to_numeric(history["q90_return"], errors="coerce")
    history["model_id"] = history["model_id"].map(_nonempty_text)
    history["prediction_id"] = history["prediction_id"].map(_nonempty_text)
    history["fold_id"] = history["fold_id"].map(_nonempty_text)
    history["_model_member"] = history.apply(lambda row: _matching_model_member(row, model_construction), axis=1)
    history["_out_of_fold"] = history["out_of_fold"].map(_truthy)
    history["_run_id"] = history["run_id"].map(_nonempty_text) if "run_id" in history else ""
    history = history.loc[
        history["forecast_date"].notna()
        & history["forecast_date"].lt(decision_day)
        & history["_model_member"].notna()
        & history["_out_of_fold"]
        & history["fold_id"].notna()
        & history["prediction_id"].notna()
        & history["expected_return"].notna()
        & history["q10_return"].notna()
        & history["q90_return"].notna()
    ]
    if history.empty:
        metadata["reason"] = "No matching out-of-fold predictions with verifiable provenance are available."
        return output

    candidates: dict[tuple[str, tuple[str, str, int]], dict[str, object]] = {}
    conflicts: set[tuple[str, tuple[str, str, int]]] = set()
    for row in history.to_dict(orient="records"):
        origin = price_dates.get_indexer([row["forecast_date"]])[0]
        if origin < 0 or origin + int(horizon) >= len(price_dates):
            continue
        target_day = price_dates[origin + int(horizon)]
        if not target_day < decision_day:
            continue
        if stale_prices[origin] or stale_prices[origin + int(horizon)]:
            continue
        expected = _finite_number(row.get("expected_return"))
        lower = _finite_number(row.get("q10_return"))
        upper = _finite_number(row.get("q90_return"))
        origin_close = closes[origin]
        target_close = closes[origin + int(horizon)]
        if (
            expected is None
            or lower is None
            or upper is None
            or lower > upper
            or not isfinite(origin_close)
            or not isfinite(target_close)
            or origin_close <= 0
            or target_close <= 0
        ):
            continue
        # Forecast returns are log returns (see models.base), so the realised
        # outcome is a log return too.
        actual = log(target_close / origin_close)
        if not isfinite(actual):
            continue
        prediction_id = str(row["prediction_id"])
        outcome_identity = (str(instrument_id), target_day.date().isoformat(), int(horizon))
        dedupe_key = (prediction_id, outcome_identity)
        candidate = {
            "model_member": int(row["_model_member"]),
            "forecast_date": row["forecast_date"],
            "run_id": str(row["_run_id"] or ""),
            "prediction_id": prediction_id,
            "expected": expected,
            "lower": lower,
            "upper": upper,
            "actual": actual,
            "target_day": target_day,
            "outcome_identity": outcome_identity,
        }
        previous = candidates.get(dedupe_key)
        if previous is not None:
            if any(previous[field] != candidate[field] for field in ("model_member", "forecast_date", "run_id", "expected", "lower", "upper", "actual")):
                conflicts.add(dedupe_key)
            continue
        candidates[dedupe_key] = candidate

    for key in conflicts:
        candidates.pop(key, None)

    events: dict[tuple[object, ...], dict[int, dict[str, object]]] = {}
    for candidate in candidates.values():
        event_key = (
            candidate["forecast_date"],
            candidate["run_id"],
            candidate["target_day"],
            candidate["outcome_identity"],
        )
        members = events.setdefault(event_key, {})
        member = int(candidate["model_member"])
        if member in members:
            # Multiple distinct predictions from one ensemble member make
            # this historical ensemble outcome ambiguous.
            members[member] = {}
        elif members.get(member) != {}:
            members[member] = candidate

    scores: list[float] = []
    hits: list[float] = []
    expected_members = set(range(len(model_construction)))
    for members in events.values():
        if set(members) != expected_members or any(not member for member in members.values()):
            continue
        member_rows = list(members.values())
        actual = float(member_rows[0]["actual"])
        lower = float(np.median([float(member["lower"]) for member in member_rows]))
        upper = float(np.median([float(member["upper"]) for member in member_rows]))
        if lower > upper:
            continue
        # Interval nonconformity is zero inside the historical q10–q90 band.
        scores.append(max(lower - actual, actual - upper, 0.0))
        hits.append(float(lower <= actual <= upper))

    metadata["sample_count"] = len(scores)
    coverage_interval = coverage_confidence_interval(hits)
    metadata["empirical_coverage"] = None if not hits else round(float(np.mean(hits)), 6)
    metadata["coverage_confidence_interval"] = (
        None if coverage_interval is None else [round(coverage_interval[0], 6), round(coverage_interval[1], 6)]
    )
    adjustment = conformal_quantile_adjustment(scores, minimum_matured_samples=minimum)
    if adjustment["status"] != "available":
        metadata["reason"] = adjustment["reason"] or "Matured calibration evidence is unavailable."
        return output

    metadata["adjustment"] = adjustment["adjustment"]
    if coverage_interval is None:
        metadata["reason"] = "Empirical coverage could not be calculated from matured outcomes."
        return output
    acceptable_low = _CONFORMAL_NOMINAL_COVERAGE - tolerance
    acceptable_high = _CONFORMAL_NOMINAL_COVERAGE + tolerance
    poor_calibration = coverage_interval[1] < acceptable_low or coverage_interval[0] > acceptable_high
    metadata["poor_calibration"] = poor_calibration
    metadata["status"] = "poor_calibration" if poor_calibration else "calibrated"
    metadata["reason"] = (
        "Matured interval coverage is outside the configured tolerance; confidence is reduced."
        if poor_calibration
        else "Matured interval coverage is within the configured tolerance."
    )
    if poor_calibration:
        output["probability_calibration_reason"] = "Probability evidence is unavailable because interval calibration is poor."
    else:
        probability_evidence = _matching_probability_evidence(output, model_construction, minimum, decision_day)
        if probability_evidence is not None:
            output.update(probability_evidence)
            output["probability_calibration_status"] = "available"
            output["probability_calibration_reason"] = None

    conformal_adjustment = float(adjustment["adjustment"])
    output = _widen_distribution_quantiles(output, conformal_adjustment)
    output["conformal_calibration"] = metadata
    return output


def _distribution_model_construction(distribution: Mapping[str, object]) -> list[dict[str, str | None]] | None:
    raw = distribution.get("per_model_distributions")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and raw:
        entries = [item for item in raw if isinstance(item, Mapping)]
        if len(entries) != len(raw):
            return None
    else:
        entries = [distribution]
    construction = []
    for entry in entries:
        model_id = _nonempty_text(entry.get("model_id"))
        if model_id is None:
            return None
        construction.append(
            {
                "model_name": _nonempty_text(entry.get("model_name")),
                "model_id": model_id,
                "model_version": _nonempty_text(entry.get("model_version")),
                "target_id": _nonempty_text(entry.get("target_id")),
            }
        )
    ordered = sorted(construction, key=lambda item: (item["model_id"] or "", item["model_version"] or "", item["target_id"] or ""))
    keys = [tuple(item.values()) for item in ordered]
    return None if not ordered or len(keys) != len(set(keys)) else ordered


def _matching_model_member(row: pd.Series, construction: list[dict[str, str | None]]) -> int | None:
    model_id = _nonempty_text(row.get("model_id"))
    model_name = _nonempty_text(row.get("model_name"))
    model_version = _nonempty_text(row.get("model_version"))
    target_id = _nonempty_text(row.get("target_id"))
    for index, member in enumerate(construction):
        if (
            model_id == member["model_id"]
            and (member["model_name"] is None or (model_name or "").casefold() == member["model_name"].casefold())
            and model_version == member["model_version"]
            and target_id == member["target_id"]
        ):
            return index
    return None


def _matching_probability_evidence(
    distribution: Mapping[str, object],
    construction: list[dict[str, str | None]],
    minimum_samples: int,
    decision_day: pd.Timestamp,
) -> dict[str, float] | None:
    evidence = distribution.get("probability_calibration_evidence")
    if not isinstance(evidence, Mapping) or evidence.get("status") != "calibrated":
        return None
    count = _finite_number(evidence.get("sample_count"))
    evidence_time = _decision_cutoff(evidence.get("matured_through"))
    if (
        count is None
        or not count.is_integer()
        or count < minimum_samples
        or evidence.get("model_construction") != construction
        or evidence_time is None
        or not evidence_time.normalize() < decision_day.normalize()
    ):
        return None
    probabilities = evidence.get("probabilities")
    if not isinstance(probabilities, Mapping):
        return None
    output = {field: _finite_number(probabilities.get(field)) for field in ("probability_loss", "probability_beat_cash", "probability_beat_benchmark")}
    if any(value is None or not 0.0 <= value <= 1.0 for value in output.values()):
        return None
    return {field: float(value) for field, value in output.items() if value is not None}


def _nonempty_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    text = str(value).strip()
    return text or None


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "1", "yes"}


def _repair_distribution_quantiles(distribution: Mapping[str, object]) -> dict[str, object]:
    """Repair present quantiles with a cumulative maximum in probability order."""

    output = dict(distribution)
    for prefix in ("", "net_"):
        fields = [f"{prefix}q{level:02d}_return" for level in _CONFORMAL_QUANTILES]
        present = [(field, _finite_number(output.get(field))) for field in fields]
        valid = [(field, value) for field, value in present if value is not None]
        if valid:
            repaired = np.maximum.accumulate([value for _, value in valid])
            for (field, _), value in zip(valid, repaired, strict=True):
                output[field] = float(value)
    return output


def _widen_distribution_quantiles(distribution: Mapping[str, object], adjustment: float) -> dict[str, object]:
    output = dict(distribution)
    fields = [f"q{level:02d}_return" for level in _CONFORMAL_QUANTILES]
    for field in fields:
        value = _finite_number(output.get(field))
        if value is not None:
            level = int(field[1:3])
            output[field] = value - adjustment if level < 50 else value + adjustment if level > 50 else value
    for field in [f"net_{name}" for name in fields]:
        value = _finite_number(output.get(field))
        if value is not None:
            level = int(field[5:7])
            output[field] = value - adjustment if level < 50 else value + adjustment if level > 50 else value
    return _repair_distribution_quantiles(output)


def _setting_number(settings: object | None, name: str, *, integer: bool = False) -> int | float | None:
    if isinstance(settings, Mapping):
        value = settings.get(name)
    else:
        value = getattr(settings, name, None)
    number = _finite_number(value)
    if number is None or (integer and not number.is_integer()):
        return None
    return int(number) if integer else number


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _decision_cutoff(value: object) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True, format="mixed")
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _price_is_stale(row: pd.Series) -> bool:
    for column in ("is_stale", "stale"):
        value = row.get(column)
        if value is not None and not pd.isna(value) and str(value).strip().lower() in {"true", "1", "yes"}:
            return True
    for column in ("staleness_status", "freshness_status"):
        value = row.get(column)
        if value is not None and not pd.isna(value) and str(value).strip().casefold() in {"stale", "warning", "block", "unknown"}:
            return True
    return False


def calibration_status() -> str:
    return "Forecast calibration is calculated from matured local forecast artefacts in data/forecasts."


def load_forecast_history(directory: Path = FORECASTS_DIR) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(directory.glob("*.csv")):
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        if frame.empty:
            continue
        frame["source_file"] = str(path)
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def evaluate_forecast_calibration(forecasts: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Evaluate only forecasts whose target date is present in local prices.

    The function deliberately leaves current, not-yet-matured forecasts as pending. It does
    not backfill missing model runs or pretend that TimesFM/Toto were calibrated when only
    current-date forecasts exist.
    """
    if forecasts.empty or prices.empty:
        return pd.DataFrame(columns=CALIBRATION_COLUMNS)
    required_forecasts = {"model_name", "etf_id", "forecast_date", "horizon_days", "expected_return", "status"}
    required_prices = {"etf_id", "date", "adjusted_close"}
    if not required_forecasts.issubset(forecasts.columns) or not required_prices.issubset(prices.columns):
        return pd.DataFrame(columns=CALIBRATION_COLUMNS)

    forecast_frame = forecasts.copy()
    forecast_frame["model_name"] = forecast_frame["model_name"].astype(str).str.lower()
    forecast_frame["instrument_id"] = forecast_frame["etf_id"].astype(str)
    forecast_frame["forecast_date"] = pd.to_datetime(forecast_frame["forecast_date"], errors="coerce")
    forecast_frame["horizon_days"] = pd.to_numeric(forecast_frame["horizon_days"], errors="coerce")
    forecast_frame["expected_return"] = pd.to_numeric(forecast_frame["expected_return"], errors="coerce")
    forecast_frame["q10_return"] = pd.to_numeric(forecast_frame.get("q10_return"), errors="coerce")
    forecast_frame["q90_return"] = pd.to_numeric(forecast_frame.get("q90_return"), errors="coerce")
    if "model_allowed_in_score" in forecast_frame:
        allowed = forecast_frame["model_allowed_in_score"].astype(str).str.lower().isin({"true", "1", "yes"})
    else:
        allowed = pd.Series(True, index=forecast_frame.index)
    forecast_frame = forecast_frame[
        (forecast_frame["status"].astype(str).str.lower() == "ok")
        & allowed
        & forecast_frame["forecast_date"].notna()
        & forecast_frame["horizon_days"].notna()
        & forecast_frame["expected_return"].notna()
    ].copy()
    if forecast_frame.empty:
        return pd.DataFrame(columns=CALIBRATION_COLUMNS)

    price_frame = prices.copy()
    price_frame["date"] = pd.to_datetime(price_frame["date"], errors="coerce")
    price_frame["adjusted_close"] = pd.to_numeric(price_frame["adjusted_close"], errors="coerce")
    price_frame = price_frame.dropna(subset=["date", "adjusted_close"])
    pivots = {
        str(instrument_id): group.sort_values("date").set_index("date")["adjusted_close"].astype(float)
        for instrument_id, group in price_frame.groupby("etf_id", sort=False)
    }

    rows: list[dict[str, object]] = []
    for (instrument_id, model_name), group in forecast_frame.groupby(["instrument_id", "model_name"], sort=False):
        series = pivots.get(str(instrument_id))
        if series is None or len(series) < 5:
            rows.append(_pending_row(str(instrument_id), str(model_name), len(group), "no_price_history"))
            continue
        matured: list[dict[str, float]] = []
        for _, forecast in group.iterrows():
            actual = _actual_horizon_return(series, forecast["forecast_date"], int(forecast["horizon_days"]))
            if actual is None:
                continue
            expected = float(forecast["expected_return"])
            q10 = _finite_or_none(forecast.get("q10_return"))
            q90 = _finite_or_none(forecast.get("q90_return"))
            matured.append(
                {
                    "expected": expected,
                    "actual": actual,
                    "absolute_error": abs(expected - actual),
                    "direction_hit": float(np.sign(expected) == np.sign(actual)),
                    "covered": float(q10 is not None and q90 is not None and q10 <= actual <= q90),
                    "has_interval": float(q10 is not None and q90 is not None),
                    "horizon_days": float(forecast["horizon_days"]),
                }
            )
        if not matured:
            rows.append(_pending_row(str(instrument_id), str(model_name), len(group), "pending_no_matured_forecasts"))
            continue
        eval_frame = pd.DataFrame(matured)
        scale = _mase_scale(series, int(round(float(eval_frame["horizon_days"].median()))))
        mase = float(eval_frame["absolute_error"].mean() / scale) if scale > 0 else None
        directional = float(eval_frame["direction_hit"].mean())
        interval_rows = eval_frame[eval_frame["has_interval"] > 0]
        coverage = float(interval_rows["covered"].mean()) if not interval_rows.empty else None
        score, status, label = _calibration_score_and_label(len(eval_frame), mase, directional)
        rows.append(
            {
                "instrument_id": str(instrument_id),
                "model_name": str(model_name),
                "evaluated_forecasts": int(len(group)),
                "matured_forecasts": int(len(eval_frame)),
                "oos_mase": None if mase is None else round(mase, 4),
                "oos_directional_accuracy": round(directional, 4),
                "q10_q90_coverage": None if coverage is None else round(coverage, 4),
                "calibration_score_10": score,
                "calibration_status": status,
                "calibration_label": label,
            }
        )
    return pd.DataFrame(rows, columns=CALIBRATION_COLUMNS)


def write_forecast_calibration(frame: pd.DataFrame, directory: Path = DERIVED_DIR) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    output = frame.copy() if not frame.empty else pd.DataFrame(columns=CALIBRATION_COLUMNS)
    parquet_path = directory / "model_calibration.parquet"
    csv_path = directory / "model_calibration.csv"
    output.to_parquet(parquet_path, index=False)
    output.to_csv(csv_path, index=False)
    return parquet_path, csv_path


def calibration_lookup(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    if frame.empty:
        return {}
    output: dict[str, dict[str, object]] = {}
    for instrument_id, group in frame.groupby("instrument_id", sort=False):
        scored = pd.to_numeric(group.get("calibration_score_10"), errors="coerce").dropna()
        statuses = sorted({str(value) for value in group.get("calibration_status", pd.Series(dtype=str)).dropna().unique()})
        matured = int(pd.to_numeric(group.get("matured_forecasts"), errors="coerce").fillna(0).sum())
        if not scored.empty:
            score = round(float(scored.mean()), 1)
            label = _overall_label(score, matured, statuses)
        elif matured <= 0:
            score = None
            label = "Calibration pending: no matured local forecast rows"
        else:
            score = None
            label = "Calibration limited: forecast rows exist but metrics are incomplete"
        output[str(instrument_id)] = {
            "score": score,
            "label": label,
            "matured_forecasts": matured,
            "statuses": ", ".join(statuses) if statuses else "unknown",
        }
    return output


def _actual_horizon_return(series: pd.Series, forecast_date: pd.Timestamp, horizon_days: int) -> float | None:
    clean = series.dropna().sort_index()
    if horizon_days <= 0 or clean.empty:
        return None
    start_pos = clean.index.searchsorted(pd.Timestamp(forecast_date), side="right") - 1
    if start_pos < 0:
        return None
    target_pos = start_pos + horizon_days
    if target_pos >= len(clean):
        return None
    start_price = float(clean.iloc[start_pos])
    target_price = float(clean.iloc[target_pos])
    if start_price <= 0 or target_price <= 0:
        return None
    # Forecasts are log returns (see models.base): keep the outcome in log units.
    return float(np.log(target_price / start_price))


def _mase_scale(series: pd.Series, horizon_days: int) -> float:
    clean = series.dropna().sort_index().astype(float)
    log_prices = np.log(clean.where(clean > 0))
    returns = log_prices.diff(max(1, int(horizon_days))).replace([np.inf, -np.inf], np.nan).dropna().abs()
    if returns.empty:
        returns = log_prices.diff().replace([np.inf, -np.inf], np.nan).dropna().abs()
    if returns.empty:
        return 1.0
    return max(float(returns.mean()), 1e-9)


def _pending_row(instrument_id: str, model_name: str, evaluated: int, status: str) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "model_name": model_name,
        "evaluated_forecasts": int(evaluated),
        "matured_forecasts": 0,
        "oos_mase": None,
        "oos_directional_accuracy": None,
        "q10_q90_coverage": None,
        "calibration_score_10": None,
        "calibration_status": status,
        "calibration_label": "Calibration pending: wait until forecast horizons mature against later yfinance prices.",
    }


def _calibration_score_and_label(n: int, mase: float | None, directional: float) -> tuple[float, str, str]:
    if n < 3:
        return 4.0, "limited", f"Limited calibration: only {n} matured forecast rows."
    if mase is not None and mase <= 1.0 and directional >= 0.55:
        return 8.0, "good", "Good calibration: forecast errors beat the local naive scale and direction is useful."
    if mase is not None and mase <= 1.5 and directional >= 0.50:
        return 6.0, "mixed", "Mixed calibration: useful but not yet strong enough for high authority."
    return 3.5, "weak", "Weak calibration: forecast error or direction accuracy is not good enough."


def _overall_label(score: float, matured: int, statuses: list[str]) -> str:
    status_text = ", ".join(statuses) if statuses else "unknown"
    if score >= 7.0:
        return f"Calibrated evidence: {matured} matured rows, status {status_text}"
    if score >= 5.0:
        return f"Partly calibrated: {matured} matured rows, status {status_text}"
    return f"Low calibration trust: {matured} matured rows, status {status_text}"


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    return number if np.isfinite(number) else None
