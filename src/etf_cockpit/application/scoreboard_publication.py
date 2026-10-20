"""Scoreboard publication: classification currency, scoreboard writing and score-history failure records (application; ADR-0002)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatchcase
import hashlib
from io import BytesIO
import json
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

import numpy as np
import pandas as pd

from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.data.classification import classification_score_state
from contextlib import contextmanager
from etf_cockpit.data.trust_artifacts import refresh_static_trust_artifacts as refresh_static_trust_artifacts, write_trust_artifacts_for_scores
from etf_cockpit.features.regime import build_market_regime, write_market_regime
from etf_cockpit.application.benchmark_reference import context_from_snapshot
from etf_cockpit.models.calibration import (
    evaluate_forecast_calibration,
    load_forecast_history,
    write_forecast_calibration,
)
from etf_cockpit.application.snapshot_builder import CockpitSnapshot
from etf_cockpit.signals.canonical_scoring import FORECAST_DOMAIN, RANK_DOMAINS, load_score_policy, rank_domain_weights
from etf_cockpit.signals.simple_scores import (
    COMPONENT_LABELS,
    build_simple_instrument_scores as build_simple_instrument_scores,
    headline_weights,
    load_latest_candidate_report,
    simple_scoreboard_frame,
    write_simple_scoreboard,
)


SCOREBOARD_PUBLICATION_BINDING_ENTITY_TYPE = "scoreboard_publication_binding"


# --- Score lineage (S3-01/S3-02): one row per user-visible score field ---------------------------------------------

LINEAGE_SCHEMA_VERSION = "score_lineage.v1"
SCORE_SURFACES = ("ui", "export", "scoreboard", "history", "api", "decision")  # "decision": DA-v1 / QV / QVM assessment
AUTHORITIES = ("descriptive", "rank", "decision")
_V3_CONFIG = "configs/score_engine_v3.yaml"
_HEADLINE_CONFIG = _V3_CONFIG + "#asset_policies.*.headline_evidence"  # NS1: the legacy composite reads the v3 yaml
_V3_CODE = "signals/canonical_scoring.py:build_canonical_score"
_LEGACY_CODE = "signals/simple_scores.py:build_simple_instrument_scores (legacy evidence composite, forecast weight 0 by owner rule F5)"
_ALL_PERSISTED = ("ui", "export", "scoreboard", "history")
_HORIZON = "1-3 months"
_CUTOFF_PRICE = "latest validated price date of the run; never after the snapshot decision time"
_ELIGIBLE_V3 = "score-eligible components only (ok status, fresh, sourced, no conflict); a failed critical gate gives no value"
_LEGACY_WEIGHTS = "legacy_evidence_weights"
_DA_POLICY = "da_v1_policy"
_DA_CODE = "analysis/decision/opportunity.py:_benchmark_scores (read via application/decision_views.py)"
_DA_ROUTE_CODE = "analysis/decision/rank_validation.py:route_consumer_rank (via application/decision_views.py:_ui_decision_rank_route)"
_DA_ELIGIBLE = "unavailable (UNAVAILABLE_INPUTS) when a required input is missing, stale or conflicting; never zero-filled or reweighted"
_DECISION = ("decision",)
_PATH_CODE = {
    "legacy_composite": "signals/simple_scores.py:build_simple_instrument_scores",
    "v3_canonical_groups": _V3_CODE,
    "display_adjusted_score_10": "application/score_views.py:apply_missing_data_penalty",
    "DA-v1": "analysis/decision/rank_validation.py:route_consumer_rank",
}


@dataclass(frozen=True)
class ScoreLineageRow:
    """Where one visible score field comes from and what it may be used for."""

    field: str  # exact column/field name, or an fnmatch pattern for a family such as ``*_score_10``
    surfaces: tuple[str, ...]
    origin_formula: str
    code_path: str
    weights_source: str  # "v3_policy" | "legacy_evidence_weights" | "none"
    data_cutoff: str
    eligibility_rule: str
    authority: str  # descriptive | rank | decision
    horizon: str
    domain: str = "evidence"  # "expected_return" is the separate model-forecast domain


def _row(field: str, surfaces: tuple[str, ...], origin: str, code: str, weights: str, eligibility: str, authority: str,
         *, cutoff: str = _CUTOFF_PRICE, domain: str = "evidence") -> ScoreLineageRow:
    return ScoreLineageRow(field, surfaces, origin, code, weights, cutoff, eligibility, authority, _HORIZON, domain)


SCORE_LINEAGE: tuple[ScoreLineageRow, ...] = (
    _row("final_combined_score_10", _ALL_PERSISTED, "legacy evidence composite 0-10 (display name: Research score)",
         _LEGACY_CODE, _LEGACY_WEIGHTS,
         "unavailable when a critical gate fails or coverage is below the policy minimum; the stored/exported value is never penalised",
         "rank"),
    _row("final_score_10", ("ui",),
         "displayed score (in-memory row only): equals final_combined_score_10, or display_adjusted_score_10 while the "
         "missing-data preference is on; never stored or exported",
         "application/score_views.py:snapshot_scores (apply_missing_data_penalty when the preference is on)",
         _LEGACY_WEIGHTS, "same as final_combined_score_10; with the preference on the value is pulled toward 5 by missing evidence",
         "descriptive"),
    _row("score", ("api",), "typed API score = final_combined_score_10 (0-10, never the raw signal in [-1, 1])",
         "signals/simple_scores.py:build_simple_instrument_scores; application/api.py:LocalApplicationApi.get_scores", _LEGACY_WEIGHTS,
         "unavailable when the instrument has no canonical score row or same-date signals conflict", "rank"),
    _row("research_score_10", ("ui",), "same value as final_combined_score_10 (shown beside the display-adjusted value)",
         "signals/simple_scores.py:build_simple_instrument_scores; application/score_views.py:score_display_values", _LEGACY_WEIGHTS, "same as final_combined_score_10", "rank"),
    _row("display_adjusted_score_10", ("ui",), "5 + (research - 5) x coverage: display annotation only, never stored",
         "application/score_views.py:apply_missing_data_penalty", "none",
         "only while the user preference is on; the visible rank follows this displayed value", "descriptive"),
    _row("rank", ("history", "api"), "stored research rank: ordinal of final_combined_score_10 (unavailable last, ties by identifier)",
         "signals/simple_scores.py:build_simple_instrument_scores", _LEGACY_WEIGHTS,
         "ordinary instruments only; native bank rows carry no rank", "rank"),
    _row("rank", ("ui",), "visible rank: the research rank, re-ordered by final_score_10 only while the missing-data preference is on",
         "signals/simple_scores.py:build_simple_instrument_scores; application/score_views.py:_ranked_by_displayed_score",
         _LEGACY_WEIGHTS, "ordinary instruments only; rank deltas recompute the previous rank on the same basis", "rank"),
    _row("score_rank", ("history",), "same stored ordinal as rank", "signals/simple_scores.py:build_simple_instrument_scores",
         _LEGACY_WEIGHTS, "same as rank", "rank"),
    _row("score_rank", ("ui",), "same visible ordinal as rank",
         "signals/simple_scores.py:build_simple_instrument_scores; application/score_views.py:_ranked_by_displayed_score",
         _LEGACY_WEIGHTS, "same as rank", "rank"),
    _row("evidence_score_10", _ALL_PERSISTED, "evidence-component composite before risk/friction shaping", _LEGACY_CODE,
         _LEGACY_WEIGHTS, "usable evidence components only", "descriptive"),
    _row("evidence_quality_10", _ALL_PERSISTED, "data quality and completeness score", _LEGACY_CODE, _LEGACY_WEIGHTS,
         "usable evidence components only", "descriptive"),
    _row("risk_friction_10", _ALL_PERSISTED, "0.60 risk + 0.40 liquidity/cost components", _LEGACY_CODE, _LEGACY_WEIGHTS,
         "usable evidence components only", "descriptive"),
    _row("coverage", _ALL_PERSISTED, "share of configured evidence present (0-1)", _LEGACY_CODE, _LEGACY_WEIGHTS,
         "always defined; 0 when nothing is usable", "descriptive"),
    _row("canonical_attractiveness_10", _ALL_PERSISTED, "v3 attractiveness group", _V3_CODE, "v3_policy", _ELIGIBLE_V3,
         "descriptive"),
    _row("canonical_risk_implementation_10", _ALL_PERSISTED, "v3 risk/implementation group", _V3_CODE, "v3_policy",
         _ELIGIBLE_V3, "descriptive"),
    _row("canonical_evidence_confidence_10", _ALL_PERSISTED, "v3 evidence confidence (coverage, freshness, structure cap)",
         _V3_CODE, "v3_policy", _ELIGIBLE_V3, "descriptive"),
    _row("canonical_coverage", _ALL_PERSISTED, "v3 configured-weight coverage (0-1)", _V3_CODE, "v3_policy",
         "always defined", "descriptive"),
    _row("canonical_expected_return_10", _ALL_PERSISTED,
         "v3 model-forecast domain (baseline/TimesFM/Toto), separate from the rank (S3-02)", _V3_CODE, "v3_policy",
         "advisory model outputs only; rank weight 0 until #811 promotes it with the paired #928 test", "descriptive",
         cutoff="forecast date; evaluation data must post-date each model's pretraining cutoff", domain=FORECAST_DOMAIN),
    _row("backtest_trust_score_10", _ALL_PERSISTED, "backtest-trust context score (informational)",
         "signals/simple_scores.py:build_simple_instrument_scores", "none", "informational; never part of the rank",
         "descriptive"),
    _row("model_calibration_score_10", _ALL_PERSISTED, "forecast-calibration context score (informational)",
         "signals/simple_scores.py:build_simple_instrument_scores", "none", "informational; never part of the rank",
         "descriptive"),
    _row("market_regime_score_10", _ALL_PERSISTED, "market-regime context score (informational)",
         "signals/simple_scores.py:build_simple_instrument_scores", "none", "informational; never part of the rank",
         "descriptive"),
    _row("portfolio_fit_score_10", _ALL_PERSISTED, "portfolio-fit context score (informational)",
         "signals/simple_scores.py:build_simple_instrument_scores", "none", "informational; never part of the rank",
         "descriptive"),
    _row("*_score_10", _ALL_PERSISTED, "per-component 0-10 score (component key in the name)",
         "signals/simple_scores.py:SimpleScoreComponent", _LEGACY_WEIGHTS,
         "shown with its status; ineligible components carry no weight", "descriptive"),
    # Decision Architecture v1 (DA-v1) with its QV / QVM benchmark rankers: side by side with the paths above.
    _row("active_rank_score", _DECISION,
         "score of the ranker the #811 cutover selects: the v3 replay until a valid promotion record activates DA-v1",
         _DA_ROUTE_CODE, _DA_POLICY, "falls back to the v3 comparator, with a reason, when the promoted score is unavailable",
         "decision"),
    _row("v3_replay_score", _DECISION, "v3 comparator retained beside the active rank for replay", _DA_ROUTE_CODE, _DA_POLICY,
         "v3 replay score only; unavailable when v3 is missing", "decision"),
    _row("benchmark_rankers.score", _DECISION,
         "benchmark ranker scores: Q, V, M, R, QV=(Q+V)/2, QVM=(Q+V+M)/3, five_factor, v3 replay", _DA_CODE, _DA_POLICY,
         _DA_ELIGIBLE, "decision"),
    _row("benchmark_rankers.percentile", _DECISION, "universe percentile of one benchmark ranker score", _DA_CODE, _DA_POLICY,
         _DA_ELIGIBLE, "decision"),
    _row("baseline_z", _DECISION, "DA-v1 baseline z-score across the eligible universe (metric weights: configs/decision_domains_v1.yaml)",
         _DA_CODE, _DA_POLICY, _DA_ELIGIBLE, "decision"),
    _row("percentile", _DECISION, "DA-v1 universe percentile of the baseline z-score", _DA_CODE, _DA_POLICY, _DA_ELIGIBLE, "decision"),
    _row("universe_rank", _DECISION, "DA-v1 universe rank of the baseline z-score", _DA_CODE, _DA_POLICY, _DA_ELIGIBLE, "decision"),
    _row("peer_percentile", _DECISION, "DA-v1 peer-group percentile", _DA_CODE, _DA_POLICY, _DA_ELIGIBLE, "decision"),
    _row("peer_rank", _DECISION, "DA-v1 peer-group rank", _DA_CODE, _DA_POLICY, _DA_ELIGIBLE, "decision"),
    _row("domain_scores", _DECISION, "DA-v1 per-domain scores", _DA_CODE, _DA_POLICY, _DA_ELIGIBLE, "decision"),
    _row("coverage", _DECISION, "DA-v1 share of required metric weight present (0-1)", _DA_CODE, _DA_POLICY,
         "always defined; 0 when nothing is usable", "decision"),
)

_SCORE_FIELD_NAMES = frozenset({"rank", "score_rank", "score", "coverage", "final_score_10"})
_DECISION_SCORE_FIELD_NAMES = frozenset(
    {"active_rank_score", "v3_replay_score", "baseline_z", "percentile", "universe_rank", "peer_percentile", "peer_rank", "domain_scores"}
)


def is_visible_score_field(name: object) -> bool:
    """True when a column/field name denotes a user-visible score, rank or coverage value."""

    text = str(name or "").strip()
    return text in _SCORE_FIELD_NAMES or text in _DECISION_SCORE_FIELD_NAMES or text.endswith("_10") or (
        text.startswith("benchmark_rankers.") and text.rsplit(".", 1)[-1] in {"score", "percentile"}
    )


def lineage_row_for(field: str, surface: str | None = None) -> ScoreLineageRow | None:
    """The lineage row covering ``field`` (exact names win over family patterns); ``None`` when unregistered."""

    components = {f"{key}_score_10" for key in COMPONENT_LABELS}  # the family pattern covers real component keys only
    matches = [
        row for row in SCORE_LINEAGE
        if (row.field == field or ("*" in row.field and fnmatchcase(field, row.field) and field in components))
        and (surface is None or surface in row.surfaces)
    ]
    return min(matches, key=lambda row: "*" in row.field) if matches else None


def unregistered_score_fields(fields: Iterable[object], surface: str | None = None) -> list[str]:
    """Visible score fields without a lineage row (the lineage test fails on any)."""

    return sorted({str(name) for name in fields if is_visible_score_field(name) and lineage_row_for(str(name), surface) is None})


def score_rank_authority(*, promotion_record: Mapping[str, object] | None = None) -> dict[str, object]:
    """Which path produces the visible rank: the legacy composite until the #811 cutover activates DA-v1.

    ``display_only_paths`` never carry rank authority in the lineage manifest: the manifest derives its ``rank``
    authority from this same declaration. The v3 groups and the display adjustment are display-only throughout.
    """

    from etf_cockpit.analysis.decision.rank_validation import resolve_rank_cutover

    cutover = resolve_rank_cutover(promotion_record=promotion_record)
    da_active = bool(cutover.active)
    active = "DA-v1" if da_active else "legacy_composite"
    display_only = ["v3_canonical_groups", "display_adjusted_score_10"] + (["legacy_composite"] if da_active else [])
    return {
        "active_rank_path": active,
        "active_ranker": cutover.ranker,
        "candidate_rank_path": "DA-v1",
        "cutover_gate": "#811",
        "cutover_enabled": cutover.enabled,
        "cutover_active": da_active,
        "cutover_reason": cutover.reason,
        "display_only_paths": display_only,
        "path_code": dict(_PATH_CODE),
        "domain_rank_weights": rank_domain_weights(load_score_policy("ETF")),
        "forecast_domain": FORECAST_DOMAIN,
        "execution_allowed": False,
    }


def _formula_version(row: ScoreLineageRow, policy: Any, cutover_policy: Any) -> str:
    if row.weights_source == _DA_POLICY:
        return str(cutover_policy.version)
    if row.weights_source == "none":
        return "not-weighted"
    return str(policy.formula_version)  # v3 groups and the headline composite: the v3 yaml version


def score_lineage_manifest(*, promotion_record: Mapping[str, object] | None = None) -> list[dict[str, object]]:
    """Generated, versioned lineage table: one row per visible score field and surface.

    ``authority`` agrees with :func:`score_rank_authority`: a row whose code path is display-only never says ``rank``.
    """

    from etf_cockpit.analysis.decision.rank_validation import load_rank_validation_policy

    policy = load_score_policy("ETF")
    legacy = {"ETF": headline_weights("ETF"), "STOCK": headline_weights("Stock")}
    rank_authority = score_rank_authority(promotion_record=promotion_record)
    display_only_code = [_PATH_CODE[path] for path in rank_authority["display_only_paths"]]  # type: ignore[attr-defined]
    cutover_policy = load_rank_validation_policy()
    da_weights = {name: dict(spec.weights) for name, spec in cutover_policy.rankers.items() if spec.weights}
    sources: dict[str, tuple[object, str, str]] = {
        "v3_policy": (policy.groups, policy.formula_checksum, _V3_CONFIG),
        _DA_POLICY: (da_weights, cutover_policy.checksum, "configs/decision_cutover_v1.yaml"),
        _LEGACY_WEIGHTS: (legacy, policy.formula_checksum, _HEADLINE_CONFIG),
        "none": ({}, "none", "none"),
    }
    forecast_weight = rank_domain_weights(policy)[FORECAST_DOMAIN]
    manifest: list[dict[str, object]] = []
    for row in SCORE_LINEAGE:
        authority = row.authority
        if authority == "rank" and any(code in row.code_path for code in display_only_code):
            authority = "descriptive"  # this path is display-only now (e.g. the legacy composite after the #811 cutover)
        weights, digest, source = sources[row.weights_source]
        if row.weights_source == "v3_policy" and isinstance(weights, Mapping):
            # S3-02: only the rank groups are active rank weights; the forecast domain's internal sizing is labelled apart.
            if row.domain == FORECAST_DOMAIN:
                weights = {"domain_internal_sizing_not_rank_weights": dict(weights.get(FORECAST_DOMAIN, {}))}
            else:
                weights = {group: weights[group] for group in RANK_DOMAINS if group in weights}
        for surface in row.surfaces:
            manifest.append(
                {
                    "schema_version": LINEAGE_SCHEMA_VERSION,
                    "field": row.field,
                    "surface": surface,
                    "origin_formula": row.origin_formula,
                    "code_path": row.code_path,
                    "formula_version": _formula_version(row, policy, cutover_policy),
                    "weights_source": source,
                    "active_weights": weights,
                    "config_hash": digest,
                    "score_engine_version": policy.formula_version,
                    "score_engine_checksum": policy.formula_checksum,
                    "data_cutoff": row.data_cutoff,
                    "eligibility_rule": row.eligibility_rule,
                    "authority": authority,
                    "horizon": row.horizon,
                    "domain": row.domain,
                    "rank_weight": forecast_weight if row.domain == FORECAST_DOMAIN else None,
                    "execution_allowed": False,
                }
            )
    return manifest


class ScoreboardPublicationBindingError(RuntimeError):
    """The scoreboard was published but its exact score-history binding was not recorded."""


def _signal_classification_is_current(signal: object, *, root: Path) -> bool:
    instrument_id = str(getattr(signal, "etf_id", "") or "").strip()
    if not instrument_id:
        return False
    metrics = getattr(signal, "supporting_metrics", {})
    stored_token = (
        str(metrics.get("classification_invalidation_hash") or "unavailable")
        if isinstance(metrics, dict)
        else "unavailable"
    )
    state = classification_score_state(root, instrument_id)
    if str(state.get("status")) == "unavailable":
        return False
    current_token = str(state.get("invalidation_token") or "unavailable")
    token_is_bound = stored_token not in {"", "none", "nan", "unavailable"}
    return not (
        (token_is_bound and stored_token != current_token)
        or (bool(state.get("invalidated_score_keys")) and stored_token != current_token)
    )


class ScoreboardSession(Protocol):
    def _record_score_history_failure(self, exc: Exception, scoreboard_path: Path) -> None:
        ...
    @contextmanager
    def activity_publication(self, expected_action_id: str | None = None):
        ...
    score_history_warning: str | None
    snapshot: CockpitSnapshot


def _write_current_scoreboard(session: ScoreboardSession) -> Path:
    candidate_report, _ = load_latest_candidate_report()
    reference_context = context_from_snapshot(
        session.snapshot,
        purpose="comparison",
        analysis_id=f"scoreboard:{getattr(session.snapshot, 'universe_revision', 'unknown')}",
    )
    regime = build_market_regime(
        session.snapshot.prices,
        candidate_report,
        benchmark_id=reference_context.benchmark_data_id,
        benchmark_reference=reference_context.projection,
        benchmark_registry=reference_context.registry,
    )
    with session.activity_publication():
        write_market_regime(regime)
    calibration = evaluate_forecast_calibration(load_forecast_history(), session.snapshot.prices)
    with session.activity_publication():
        write_forecast_calibration(calibration)
    from etf_cockpit.application.score_views import published_scores

    # The missing-data penalty is a display annotation: stored scoreboard and history rows are never penalised.
    scores = published_scores(session.snapshot)
    scoreboard_frame = simple_scoreboard_frame(scores)
    with session.activity_publication():
        path = write_simple_scoreboard(scores)
    try:
        with session.activity_publication():
            paths = write_trust_artifacts_for_scores(
                session.snapshot.config,
                scores,
                scoreboard_frame,
                prices=session.snapshot.prices,
            )
            history_path = paths.get("score_history") if isinstance(paths, dict) else None
            try:
                if not isinstance(history_path, Path) or not history_path.is_file():
                    raise RuntimeError("Score history publication path is unavailable.")
                # The trust writer names the run it wrote; a plain mapping without that identity (legacy writers)
                # keeps the previous newest-run binding.
                run_id = getattr(paths, "run_id", None)
                if run_id is None:
                    _record_scoreboard_publication_binding(path, history_path, scoreboard_frame)
                else:
                    _record_scoreboard_publication_binding(path, history_path, scoreboard_frame, run_id=str(run_id))
            except Exception as binding_exc:
                raise ScoreboardPublicationBindingError(str(binding_exc)) from binding_exc
    except Exception as exc:
        # The scoreboard itself is published; trust artifacts or their exact
        # publication binding are missing. Keep that absence explicit.
        session._record_score_history_failure(exc, path)
    else:
        session.score_history_warning = None
    return path


def _record_scoreboard_publication_binding(
    scoreboard_path: Path,
    history_path: Path,
    expected_scoreboard: pd.DataFrame,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Bind exact scoreboard bytes to the score-history run that published them.

    ``run_id`` is the run that wrote this scoreboard's history; the binding uses exactly that run's rows. Without
    it (direct callers that only hold the file) the globally newest history run is used, as before.
    """

    scoreboard_bytes = scoreboard_path.read_bytes()
    actual_scoreboard = pd.read_parquet(BytesIO(scoreboard_bytes))
    try:
        pd.testing.assert_frame_equal(
            _normalise_scoreboard_values(expected_scoreboard),
            _normalise_scoreboard_values(actual_scoreboard),
            check_dtype=False,
            check_exact=True,
        )
    except AssertionError as exc:
        raise RuntimeError("Scoreboard changed while its score-history publication was being recorded.") from exc
    history = pd.read_parquet(history_path)
    required = {"run_id", "run_completed_at", "snapshot_hash"}
    if history.empty or not required.issubset(history.columns):
        raise ValueError("Score history has no verifiable publication identity.")
    completed = pd.to_datetime(history["run_completed_at"], utc=True, errors="coerce")
    if completed.isna().any():
        raise ValueError("Score history contains an unverifiable completion time.")
    if run_id is not None:
        selected = history["run_id"].astype(str).str.strip().eq(str(run_id).strip())
        if not selected.any():
            raise ValueError("Score history has no rows for the publishing run.")
        history = history.loc[selected]
        completed = completed.loc[selected]
    newest = completed.max()
    latest = history.loc[completed.eq(newest)]
    run_ids = {str(value).strip() for value in latest["run_id"] if pd.notna(value)}
    hashes = {str(value).strip().lower() for value in latest["snapshot_hash"] if pd.notna(value)}
    if len(run_ids) != 1 or len(hashes) != 1:
        raise ValueError("Latest score history publication identity is ambiguous.")
    run_id = next(iter(run_ids))
    score_snapshot_hash = next(iter(hashes))
    if not run_id or len(score_snapshot_hash) != 64 or any(char not in "0123456789abcdef" for char in score_snapshot_hash):
        raise ValueError("Latest score history snapshot hash is invalid.")

    root = scoreboard_path.resolve().parents[2]
    score_completed_at = newest.to_pydatetime().astimezone(timezone.utc)
    published_at = max(datetime.now(timezone.utc), score_completed_at)
    scoreboard_digest = hashlib.sha256(scoreboard_bytes).hexdigest()
    payload = {
        "schema_version": "scoreboard_publication_binding.v1",
        "run_id": run_id,
        "score_snapshot_hash": score_snapshot_hash,
        "score_completed_at": score_completed_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "known_at": published_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "scoreboard_sha256": scoreboard_digest,
        "execution_allowed": False,
    }
    identity = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if hashlib.sha256(scoreboard_path.read_bytes()).hexdigest() != scoreboard_digest:
        raise RuntimeError("Scoreboard changed while its publication binding was being recorded.")
    with TransactionalStore(root) as store:
        store.put_many(
            [(SCOREBOARD_PUBLICATION_BINDING_ENTITY_TYPE, identity, payload)],
            immutable=True,
        )
    return payload


def _normalise_scoreboard_values(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert Arrow-backed nested arrays and NumPy scalars to comparable Python values."""

    normalised = frame.reset_index(drop=True).copy()
    for column in normalised.columns:
        normalised[column] = normalised[column].map(_normalise_nested_value)
    return normalised


def _normalise_nested_value(value: object) -> object:
    if isinstance(value, np.ndarray):
        return _normalise_nested_value(value.item() if value.ndim == 0 else value.tolist())
    if isinstance(value, np.generic):
        return _normalise_nested_value(value.item())
    if isinstance(value, Mapping):
        return {key: _normalise_nested_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise_nested_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalise_nested_value(item) for item in value)
    return value
