"""Application facade for read-only validation evidence previews."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone

import pandas as pd

from etf_cockpit.features.training_centre import LocalTrainingRegistry
from etf_cockpit.portfolio.optimiser import returns_from_adjusted_prices
from etf_cockpit.validation.protocol import ValidationReport, ValidationSpec, evaluate_trials, report_fingerprint


def build_validation_preview(prices: pd.DataFrame | None, *, spec: ValidationSpec | None = None) -> ValidationReport | None:
    """Build a transparent protocol report from local adjusted-price returns.

    The preview deliberately does not train or promote a model.  It proves the
    split/report contract in the user-facing workspaces and keeps promotion
    false until a caller supplies real, separately versioned trial scores.
    """

    values, definition, regimes, subgroups = _preview_inputs(prices, spec)
    if values is None:
        return None
    return evaluate_trials(
        {"baseline": values, "current_pipeline": values},
        spec=definition,
        parameters={"baseline": {"kind": "naive"}, "current_pipeline": {"kind": "preview_only"}},
        regime_labels=regimes,
        subgroup_labels=subgroups,
    )


def record_validation_preview(root, prices: pd.DataFrame | None, *, researcher_decision: str = "pending") -> dict[str, object] | None:
    """Persist the complete local preview search, including discarded trials."""

    values, definition, _, _ = _preview_inputs(prices, None)
    report = build_validation_preview(prices, spec=definition) if values is not None else None
    if report is None or values is None:
        return None
    frame = prices if isinstance(prices, pd.DataFrame) else pd.DataFrame()
    data_hash = _sha256(frame.to_json(orient="split", date_format="iso").encode("utf-8"))
    feature_hash = _sha256(json.dumps({"source": "adjusted_close", "window": 0}, sort_keys=True).encode("utf-8"))
    code_hash = _validation_code_hash()
    environment_hash = _sha256(b"local-validation-preview")
    registry = LocalTrainingRegistry(root)
    experiment = registry.create_experiment("local-validation-preview", experiment_id="exp-validation-preview")
    report_hash = report_fingerprint(report)
    execution_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    run = registry.create_run(
        str(experiment["experiment_id"]),
        run_id=f"validation_{execution_id}_{report_hash[:8]}",
        parameters={"protocol_version": report.protocol_version, "spec_fingerprint": definition.fingerprint},
        dataset_hash=data_hash,
        feature_hash=feature_hash,
        code_hash=code_hash,
        environment_hash=environment_hash,
    )
    try:
        stored = registry.record_validation_report(
            str(run["run_id"]),
            report,
            trial_returns={"baseline": values.tolist(), "current_pipeline": values.tolist()},
            data_hash=data_hash,
            code_hash=code_hash,
            features={"source": "adjusted_close", "window": 0},
            thresholds={"regime_abs_median": float(pd.Series(values).abs().median())},
            variants={"baseline": "naive", "current_pipeline": "preview_only"},
            selection_method="highest development-fold mean with final test held out",
        )
        registry.record_researcher_decision(
            str(stored["report_id"]),
            decision=researcher_decision,  # type: ignore[arg-type]
            reviewer="local-user",
            rationale="Preview retained for transparent local review; no model authority is granted.",
        )
        promotion = registry.validation_promotion_result(str(stored["report_id"]))
        registry.update_run(str(run["run_id"]), status="completed", progress=1.0, completion_report={"report_fingerprint": report_hash})
    except Exception as exc:
        try:
            registry.update_run(
                str(run["run_id"]),
                status="failed",
                progress=1.0,
                completion_report={
                    "status": "validation_evidence_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        except Exception:
            pass
        raise
    return {"report": stored, "promotion": promotion}


def load_training_evidence(root) -> dict[str, tuple[dict[str, object], ...]]:
    """Load local training and validation evidence through the application boundary."""

    return LocalTrainingRegistry(root).snapshot()


def _preview_inputs(prices: pd.DataFrame | None, spec: ValidationSpec | None) -> tuple[object, ValidationSpec, list[str], list[str]]:
    returns = returns_from_adjusted_prices(prices if prices is not None else pd.DataFrame(), window=0)
    if returns.empty:
        return None, spec or ValidationSpec(), [], []
    values = returns.mean(axis=1).to_numpy(float)
    definition = spec or ValidationSpec(n_splits=3, test_size=10, final_test_size=10, horizon=1, embargo=2, bootstrap_repetitions=40, seed=42)
    required = definition.final_test_size + definition.n_splits * definition.test_size + definition.horizon + definition.embargo
    if len(values) < required:
        return None, definition, [], []
    regime_threshold = float(pd.Series(values).abs().median())
    regimes = ["stress" if abs(value) >= regime_threshold else "calm" for value in values]
    return values, definition, regimes, ["local_adjusted_price" for _ in values]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validation_code_hash() -> str:
    """Hash the executable preview implementation used for retained evidence."""

    source = "\n".join(inspect.getsource(function) for function in (build_validation_preview, record_validation_preview, _preview_inputs))
    return _sha256(source.encode("utf-8"))


__all__ = ["build_validation_preview", "load_training_evidence", "record_validation_preview"]
