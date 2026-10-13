"""Evidence-based promotion of optional forecast models (TimesFM 2.5, TimesFM 3.0, Toto 2.0).

An optional model counts in scores only when its matured, out-of-sample
forecasts beat the deterministic baseline on the same instruments, origin dates
and horizon.  Maturity comes from adjusted prices known at ``as_of`` only, via
the calibration evaluation (``oos_mase``, ``oos_directional_accuracy``).
Origins at or before a declared pretraining cutoff or any optional model's first
verified local run never count. Versions and creation timestamps are verified separately.  The decision is a pure function of
stored forecasts and prices; it grants no execution authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date

import pandas as pd

from etf_cockpit.core.config import ModelPromotionSettings
from etf_cockpit.core.values import finite_float_or_none
from etf_cockpit.models.calibration import (
    calibration_grade,
    evaluate_forecast_calibration,
    realised_horizon_return,
)

OPTIONAL_MODELS = ("timesfm", "timesfm3", "toto")
BASELINE_MODEL = "baseline"
# Partial declared cutoff: 2023-11-30 covers only some TimesFM3 pretraining
# corpora (other pretraining data include GiftEvalPretrain and synthetic data).
# Every optional model also requires evidence after its first verified local run.
PRETRAINING_CUTOFFS: dict[str, date] = {"timesfm3": date(2023, 11, 30)}
PRETRAINING_SOURCES: dict[str, str] = {"timesfm3": "Partial: Wikipedia through Nov 2023; Google Trends through Dec 2022; other corpora have no verified cutoff"}


@dataclass(frozen=True)
class CheckpointProvenance:
    """Identity, licence and leakage evidence of one model checkpoint. Nothing is inherited from another."""

    model_name: str
    model_sha: str | None
    config: Mapping[str, object]
    licence: str
    pretraining_cutoff: date | None
    cutoff_scope: str
    note: str = ""

    def as_row(self) -> dict[str, object]:
        return {
            "model_name": self.model_name,
            "checkpoint_sha": self.model_sha or "unknown",
            "checkpoint_config": dict(self.config),
            "checkpoint_licence": self.licence,
            "pretraining_cutoff": self.pretraining_cutoff.isoformat() if self.pretraining_cutoff else "unknown",
            "cutoff_scope": self.cutoff_scope,
            "checkpoint_note": self.note,
        }

    def leakage_flag(self, origin: date) -> str:
        """``possibly_leaked`` unless this checkpoint's own cutoff is declared and the origin follows it.

        Even then a published cutoff is partial evidence only, never proof of no leakage.
        """

        if self.pretraining_cutoff is None or origin <= self.pretraining_cutoff:
            return "possibly_leaked"
        return "after_declared_cutoff"


# Declared licence facts only; an unrecorded fact is "unknown", never copied from another checkpoint.
_CHECKPOINT_LICENCES: dict[str, tuple[str, str]] = {
    "timesfm3": ("non-commercial", "Owner-approved for personal use only; not wired for commercial use."),
}


def checkpoint_provenance(
    model_name: str,
    *,
    model_sha: str | None = None,
    config: Mapping[str, object] | None = None,
) -> CheckpointProvenance:
    """Provenance of ``model_name``; the cutoff comes from ``PRETRAINING_CUTOFFS`` for that model alone.

    ``model_sha`` is supplied by the caller from the checkpoint's recorded revision (weights are
    never opened here); a blank value stays unknown.
    """

    licence, note = _CHECKPOINT_LICENCES.get(model_name, ("unknown", ""))
    cutoff = PRETRAINING_CUTOFFS.get(model_name)
    return CheckpointProvenance(
        model_name=model_name,
        model_sha=(model_sha.strip() or None) if isinstance(model_sha, str) else None,
        config=dict(config or {}),
        licence=licence,
        pretraining_cutoff=cutoff,
        cutoff_scope="partial" if cutoff is not None else "unknown",
        note=note,
    )


COUNTING = "counting"
NOT_PROVEN = "not_proven"
PROMOTION_COLUMNS = [
    "model_name",
    "model_version",
    "evidence_horizon_days",
    "unverifiable_forecasts",
    "version_evidence",
    "state",
    "reason",
    "matured_forecasts",
    "required_forecasts",
    "forecast_origins",
    "required_origins",
    "instruments",
    "model_mase",
    "baseline_mase",
    "model_directional",
    "baseline_directional",
    "calibration_status",
    "pretraining_cutoff",
    "first_local_run",
    "evidence_after",
    "excluded_pre_cutoff",
    "execution_allowed",
]


@dataclass(frozen=True)
class ModelPromotion:
    model_name: str
    state: str
    reason: str
    matured_forecasts: int = 0
    required_forecasts: int = 0
    forecast_origins: int = 0
    required_origins: int = 0
    instruments: int = 0
    model_mase: float | None = None
    baseline_mase: float | None = None
    model_directional: float | None = None
    baseline_directional: float | None = None
    calibration_status: str | None = None
    pretraining_cutoff: str = "unknown"
    first_local_run: str | None = None
    evidence_after: str | None = None
    excluded_pre_cutoff: int = 0
    execution_allowed: bool = False
    model_version: str | None = None
    evidence_horizon_days: int = 60
    unverifiable_forecasts: int = 0
    version_evidence: tuple[dict[str, object], ...] = ()

    @property
    def counting(self) -> bool:
        return self.state == COUNTING

    def evidence_window_open(self, origin: date) -> bool:
        """True when a forecast made on ``origin`` can count as promotion evidence."""

        return self.evidence_after is not None and origin > date.fromisoformat(self.evidence_after)


def promotion_frame(promotions: Mapping[str, ModelPromotion]) -> pd.DataFrame:
    return pd.DataFrame([asdict(item) for item in promotions.values()], columns=PROMOTION_COLUMNS)


def evidence_start(model_name: str, first_local_run: date | None) -> date | None:
    """Origins must be strictly after this date to count; None when no window exists yet."""

    if first_local_run is None:
        return None
    return max(first_local_run, PRETRAINING_CUTOFFS.get(model_name, first_local_run))


def evaluate_model_promotions(
    history: pd.DataFrame,
    prices: pd.DataFrame,
    as_of: date,
    settings: ModelPromotionSettings,
    models: tuple[str, ...] = OPTIONAL_MODELS,
) -> dict[str, ModelPromotion]:
    """Return one promotion decision per optional model from forecasts and prices known at ``as_of``."""

    forecasts = _normalised_history(history, as_of)
    price_series = _price_series(prices, as_of)
    decisions: dict[str, ModelPromotion] = {}
    baseline = forecasts.loc[
        forecasts["model_name"].eq(BASELINE_MODEL)
        & forecasts["horizon_days"].eq(settings.evidence_horizon_days)
    ]
    for model in models:
        own = forecasts.loc[forecasts["model_name"].eq(model)]
        versions = own["model_version"].dropna().unique().tolist()
        if not versions:
            decisions[model] = _decide(model, None, forecasts, baseline, price_series, settings)
            continue
        # Keep separate evidence for each version. The latest observed version is
        # the family decision, and may not inherit eligibility from an older one.
        evaluated = [_decide(model, version, forecasts, baseline, price_series, settings) for version in versions]
        latest = own.sort_values("created_at", na_position="first")["model_version"].dropna().iloc[-1]
        selected = next(item for item in evaluated if item.model_version == latest)
        decisions[model] = replace(selected, version_evidence=tuple(asdict(item) for item in evaluated))
    return decisions


def _decide(
    model: str,
    version: str | None,
    forecasts: pd.DataFrame,
    baseline: pd.DataFrame,
    price_series: dict[str, pd.Series],
    settings: ModelPromotionSettings,
) -> ModelPromotion:
    cutoff = PRETRAINING_CUTOFFS.get(model)
    common = {
        "model_name": model,
        "model_version": version,
        "evidence_horizon_days": settings.evidence_horizon_days,
        "required_forecasts": settings.minimum_matured_forecasts,
        "required_origins": settings.minimum_forecast_origins,
        "pretraining_cutoff": cutoff.isoformat() if cutoff else "unknown",
    }
    own = forecasts.loc[forecasts["model_name"].eq(model)]
    verified = own["provenance_verified"] & own["model_version"].eq(version)
    at_horizon = own.loc[own["horizon_days"].eq(settings.evidence_horizon_days)]
    common["unverifiable_forecasts"] = int((~(at_horizon["provenance_verified"] & at_horizon["model_version"].eq(version))).sum())
    own = own.loc[verified]
    first_run = own["created_at"].min() if not own.empty else pd.NaT
    first_local_run = None if pd.isna(first_run) else first_run.date()
    start = evidence_start(model, first_local_run)
    common["first_local_run"] = None if first_local_run is None else first_local_run.isoformat()
    common["evidence_after"] = None if start is None else start.isoformat()
    if start is None:
        return ModelPromotion(state=NOT_PROVEN, reason=f"No verified local forecasts for this version; {common['unverifiable_forecasts']} unverifiable forecasts.", **common)
    at_horizon = own.loc[own["horizon_days"].eq(settings.evidence_horizon_days)]
    excluded = int((at_horizon["forecast_date"] <= pd.Timestamp(start)).sum())
    common["excluded_pre_cutoff"] = excluded
    eligible = at_horizon.loc[at_horizon["forecast_date"] > pd.Timestamp(start)]
    pairs = eligible.merge(
        baseline.loc[baseline["provenance_verified"], ["etf_id", "forecast_date", "expected_return"]].drop_duplicates(["etf_id", "forecast_date"], keep="last").rename(columns={"expected_return": "baseline_return"}),
        on=["etf_id", "forecast_date"],
        how="inner",
    )
    matured = _matured_pairs(pairs, price_series, settings.evidence_horizon_days)
    count = int(len(matured))
    origins = int(matured["forecast_date"].nunique()) if count else 0
    common.update(matured_forecasts=count, forecast_origins=origins, instruments=int(matured["etf_id"].nunique()) if count else 0)
    if count == 0:
        return ModelPromotion(
            state=NOT_PROVEN,
            reason=f"0 of {settings.minimum_matured_forecasts} matured forecasts after {start.isoformat()}.",
            **common,
        )
    scores = _paired_scores(matured, price_series)
    common.update(scores)
    shortfall = _shortfall(count, origins, settings)
    if shortfall:
        return ModelPromotion(state=NOT_PROVEN, reason=shortfall, **common)
    model_mase, base_mase = scores["model_mase"], scores["baseline_mase"]
    model_dir, base_dir = scores["model_directional"], scores["baseline_directional"]
    if None in (model_mase, base_mase, model_dir, base_dir):
        return ModelPromotion(state=NOT_PROVEN, reason="Accuracy against the baseline cannot be computed from the matured forecasts.", **common)
    if model_mase >= base_mase:
        return ModelPromotion(
            state=NOT_PROVEN,
            reason=f"MASE {model_mase:.3f} does not beat the baseline's {base_mase:.3f} on the same {count} forecasts.",
            **common,
        )
    if model_dir < base_dir:
        return ModelPromotion(
            state=NOT_PROVEN,
            reason=f"Directional accuracy {model_dir:.1%} is below the baseline's {base_dir:.1%} on the same {count} forecasts.",
            **common,
        )
    if scores["calibration_status"] == "weak":
        return ModelPromotion(state=NOT_PROVEN, reason="Calibration is weak despite beating the baseline.", **common)
    return ModelPromotion(
        state=COUNTING,
        reason=(
            f"{common['unverifiable_forecasts']} unverifiable forecasts excluded. Beat the baseline on {count} matured forecasts over {origins} dates "
            f"(MASE {model_mase:.3f} vs {base_mase:.3f}; direction {model_dir:.1%} vs {base_dir:.1%})."
        ),
        **common,
    )


def _shortfall(count: int, origins: int, settings: ModelPromotionSettings) -> str | None:
    if count < settings.minimum_matured_forecasts:
        return f"{count} of {settings.minimum_matured_forecasts} matured forecasts."
    if origins < settings.minimum_forecast_origins:
        return f"{origins} of {settings.minimum_forecast_origins} matured forecast dates."
    return None


def _matured_pairs(pairs: pd.DataFrame, price_series: dict[str, pd.Series], horizon: int) -> pd.DataFrame:
    """Keep pairs whose target session exists in the prices known at as-of."""

    if pairs.empty:
        return pairs
    keep = [
        realised_horizon_return(series, row.forecast_date, horizon) is not None
        if (series := price_series.get(row.etf_id)) is not None and len(series) >= 5
        else False
        for row in pairs.itertuples()
    ]
    return pairs.loc[keep].reset_index(drop=True)


def _paired_scores(matured: pd.DataFrame, price_series: dict[str, pd.Series]) -> dict[str, object]:
    """Pool per-instrument oos_mase / oos_directional_accuracy for the model and baseline on identical pairs."""

    base = matured[["etf_id", "forecast_date", "horizon_days", "baseline_return"]].rename(columns={"baseline_return": "expected_return"})
    model_columns = ["etf_id", "forecast_date", "horizon_days", "expected_return", *[name for name in ("q10_return", "q90_return") if name in matured]]
    frame = pd.concat(
        [
            matured[model_columns].assign(model_name="model"),
            base.assign(model_name=BASELINE_MODEL),
        ],
        ignore_index=True,
    )
    frame["status"] = "ok"
    frame["model_allowed_in_score"] = True
    prices = pd.concat(
        [pd.DataFrame({"etf_id": etf, "date": series.index, "adjusted_close": series.to_numpy()}) for etf, series in price_series.items() if etf in set(matured["etf_id"])],
        ignore_index=True,
    ) if price_series else pd.DataFrame(columns=["etf_id", "date", "adjusted_close"])
    table = evaluate_forecast_calibration(frame, prices)
    pooled = {name: _pool(table.loc[table["model_name"].eq(name)]) for name in ("model", BASELINE_MODEL)}
    model_mase, model_dir, model_n = pooled["model"]
    base_mase, base_dir, _ = pooled[BASELINE_MODEL]
    # Require interval evidence on every instrument before assigning a good grade.
    model_rows = table.loc[table["model_name"].eq("model")]
    coverage_values = pd.to_numeric(model_rows["q10_q90_coverage"], errors="coerce")
    weights = pd.to_numeric(model_rows["matured_forecasts"], errors="coerce")
    coverage = float((coverage_values * weights).sum() / weights.sum()) if not model_rows.empty and coverage_values.notna().all() else None
    grade = None if model_dir is None else calibration_grade(model_n, model_mase, model_dir, coverage)
    return {
        "model_mase": model_mase,
        "baseline_mase": base_mase,
        "model_directional": model_dir,
        "baseline_directional": base_dir,
        "calibration_status": grade,
    }


def _pool(rows: pd.DataFrame) -> tuple[float | None, float | None, int]:
    weights = pd.to_numeric(rows["matured_forecasts"], errors="coerce").fillna(0)
    total = int(weights.sum())
    if total <= 0:
        return None, None, 0
    mase = pd.to_numeric(rows["oos_mase"], errors="coerce")
    direction = pd.to_numeric(rows["oos_directional_accuracy"], errors="coerce")
    if mase.isna().any() or direction.isna().any():
        return None, None, total
    return round(float((mase * weights).sum() / total), 4), round(float((direction * weights).sum() / total), 4), total


def _normalised_history(history: pd.DataFrame, as_of: date) -> pd.DataFrame:
    columns = ["model_name", "etf_id", "forecast_date", "horizon_days", "expected_return"]
    lineage = ["model_version", "created_at", "run_id", "q10_return", "q90_return"]
    empty = pd.DataFrame(columns=[*columns, "status", *lineage, "provenance_verified"])
    if history is None or history.empty or not {*columns, "status"}.issubset(history.columns):
        return empty
    frame = history.reindex(columns=[*columns, "status", *lineage]).copy()
    frame["model_name"] = frame["model_name"].astype(str).str.lower()
    frame["etf_id"] = frame["etf_id"].astype(str)
    for name in ("model_version", "run_id"):
        frame[name] = frame[name].astype("string").str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    frame["forecast_date"] = pd.to_datetime(frame["forecast_date"], errors="coerce", utc=True, format="mixed").dt.tz_convert(None).dt.normalize()
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce", utc=True, format="mixed").dt.tz_convert(None)
    for name in ("horizon_days", "expected_return", "q10_return", "q90_return"):
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    # Date-only forecast artefacts use the end of the UTC origin day. A timestamp
    # after that boundary cannot establish a forecast made at the origin.
    session_end = frame["forecast_date"] + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    frame["provenance_verified"] = (
        frame["created_at"].notna() & frame["created_at"].le(session_end)
        & frame["model_version"].notna() & frame["run_id"].notna()
    )
    frame = frame.loc[
        frame["status"].astype(str).str.lower().eq("ok")
        & frame["forecast_date"].notna()
        & (frame["forecast_date"] <= pd.Timestamp(as_of))
        & frame["horizon_days"].notna()
        & frame["expected_return"].map(lambda value: finite_float_or_none(value) is not None)
    ].copy()
    frame["horizon_days"] = frame["horizon_days"].astype(int)
    # Verify before deduplication so a retrospective rerun cannot replace genuine
    # prospective evidence; versions never overwrite one another.
    return frame.sort_values("created_at", na_position="first").drop_duplicates(
        ["model_name", "model_version", "etf_id", "forecast_date", "horizon_days", "provenance_verified"], keep="last"
    ).reset_index(drop=True)


def _price_series(prices: pd.DataFrame, as_of: date) -> dict[str, pd.Series]:
    """Adjusted closes on or before ``as_of`` per instrument; later prices cannot mature a forecast."""

    if prices is None or prices.empty or not {"etf_id", "date", "adjusted_close"}.issubset(prices.columns):
        return {}
    frame = prices[["etf_id", "date", "adjusted_close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True, format="mixed").dt.tz_convert(None).dt.normalize()
    frame["adjusted_close"] = pd.to_numeric(frame["adjusted_close"], errors="coerce")
    frame = frame.dropna().loc[lambda data: data["date"] <= pd.Timestamp(as_of)]
    return {
        str(etf_id): group.drop_duplicates("date", keep="last").sort_values("date").set_index("date")["adjusted_close"]
        for etf_id, group in frame.groupby("etf_id", sort=False)
    }
