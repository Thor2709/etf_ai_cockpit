"""Bind interactive analysis-depth runs to the configured universe of the current snapshot.

bulk_run and execute_profiled_stages take their instruments, inputs and stage
runner from the caller; nothing in the application registered a real runner. This
module is that caller for the interactive app. It reads only evidence already held
by the snapshot (configuration, local prices, features, data-quality report and the
existing signal results). It computes nothing new, never touches the network and
fails closed: a mandatory gate whose evidence is missing or failing raises with the
reason, and optional stages without a local evidence source return None, which
execute_profiled_stages records as an omitted stage.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import math
from typing import TYPE_CHECKING

from etf_cockpit.application.analysis_depth import (
    AnalysisResourcePlan,
    AnalysisStageManifest,
    ProfileRunBinding,
    ProfileRunUnavailable,
    StageRunner,
)

if TYPE_CHECKING:
    from etf_cockpit.services import CockpitSnapshot

INTERACTIVE_ANALYZER_ID = "interactive-snapshot-stages.v1"
# Optional stages that read evidence already held by the snapshot. Every other optional stage
# (peers, ensembles, scenarios, documents, source reconciliation, audits, ...) has no wired local
# source here or needs the network, so it is reported as omitted rather than invented.
LOCAL_OPTIONAL_STAGES = ("core_asset_facts", "core_costs", "forecast_baseline")


class InteractiveStageError(RuntimeError):
    """A mandatory gate cannot pass; the message is the reason shown for the failed run."""


def _finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: object) -> str | None:
    return None if value is None else str(value)


_MISSING = object()
_UNAVAILABLE = {"unavailable": True}  # explicit sentinel; JSON-distinct from every real scalar
# Every per-instrument config field and signal metric a stage function below reads.
_CONFIG_FIELDS = (
    "enabled", "isin", "isin_status", "instrument_type", "analysis_tier", "min_history_days",
    "asset_class", "region", "sector", "theme", "role", "currency", "ter",
)
_METRIC_KEYS = ("estimated_cost_bps", "cost_model_id", "cost_data_quality", "baseline_score")


def _stable(value: object) -> object:
    """JSON-stable form of one evidence value; missing and non-finite values become the sentinel."""

    if value is _MISSING or value is None:
        return _UNAVAILABLE
    if isinstance(value, bool) or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else _UNAVAILABLE
    number = _finite(value)
    return str(value) if number is None else repr(number)


class SnapshotEvidence:
    """Per-instrument lookups over one snapshot, built once per run."""

    def __init__(self, snapshot: "CockpitSnapshot") -> None:
        self.snapshot = snapshot
        self.configs = {etf.id: etf for etf in snapshot.config.universe.etfs}
        self.signals = {signal.etf_id: signal for signal in snapshot.signals}
        self.price_stats: dict[str, tuple[int, str, str]] = {}
        prices = snapshot.prices
        if prices is not None and len(prices) and {"etf_id", "date"} <= set(prices.columns):
            grouped = prices.groupby("etf_id")["date"].agg(["size", "min", "max"])
            for etf_id, row in grouped.iterrows():
                self.price_stats[str(etf_id)] = (int(row["size"]), str(row["min"]), str(row["max"]))
        self.features: dict[str, Mapping[str, object]] = {}
        latest = snapshot.latest_features
        if latest is not None and len(latest) and "etf_id" in latest.columns:
            ordered = latest.sort_values("date") if "date" in latest.columns else latest
            for record in ordered.to_dict("records"):
                self.features[str(record["etf_id"])] = record
        self.issues = list(getattr(snapshot.data_report, "issues", ()))

    def blocking_issue_codes(self, etf_id: str) -> list[str]:
        return sorted({i.code for i in self.issues if i.severity == "block" and i.etf_id in {etf_id, "ALL"}})

    def warning_issue_codes(self, etf_id: str) -> list[str]:
        return sorted({i.code for i in self.issues if i.severity == "warning" and i.etf_id in {etf_id, "ALL"}})

    def analysis_input(self, etf_id: str) -> dict[str, object]:
        """Deterministic identity of the evidence a run reads, so cached stages never outlive it.

        Hashes exactly the values the stage functions below read: every config field, the signal
        metrics keys, the feature row (including its date and which values are unavailable), the
        price statistics, blocked_by, the issue codes by severity and analysis_allowed. A missing
        or non-finite value hashes as an explicit sentinel, never as zero.
        """

        feature = self.features.get(etf_id)
        signal = self.signals.get(etf_id)
        config = self.configs.get(etf_id)
        report = self.snapshot.data_report
        metrics = signal.supporting_metrics if signal is not None else None
        payload = {
            "config": None if config is None else {name: _stable(getattr(config, name, _MISSING)) for name in _CONFIG_FIELDS},
            "prices": self.price_stats.get(etf_id),
            "features": None if feature is None else {
                "date": _stable(feature.get("date")),
                "values": {key: _stable(feature[key]) for key in sorted(feature) if key not in {"date", "etf_id"}},
            },
            "blocked_by": sorted(signal.blocked_by) if signal is not None else None,
            "supporting_metrics": None if metrics is None else {key: _stable(metrics.get(key, _MISSING)) for key in _METRIC_KEYS},
            "analysis_allowed": _stable(getattr(report, "analysis_allowed", _MISSING)),
            "blocking_issues": self.blocking_issue_codes(etf_id),
            "warning_issues": self.warning_issue_codes(etf_id),
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        return {
            "universe_revision": str(getattr(self.snapshot, "universe_revision", "") or ""),
            "data_as_of": _text(getattr(report, "as_of_date", None)),
            "evidence_digest": digest,
        }


def snapshot_stage_runner(snapshot: "CockpitSnapshot", evidence: SnapshotEvidence | None = None) -> StageRunner:
    """Stage runner over the snapshot's existing evidence; no calculation, no network."""

    evidence = evidence if evidence is not None else SnapshotEvidence(snapshot)

    def identity_gate(etf_id: str) -> dict[str, object]:
        config = evidence.configs.get(etf_id)
        if config is None:
            raise InteractiveStageError(f"{etf_id} is not in the configured universe")
        if not config.enabled:
            raise InteractiveStageError(f"{etf_id} is disabled in the configured universe")
        if not config.isin:
            raise InteractiveStageError(f"{etf_id} has no ISIN; identity needs verification")
        if config.isin_status != "verified":
            raise InteractiveStageError(f"{etf_id} ISIN status is {config.isin_status}, not verified")
        return {
            "status": "passed", "passed": True, "isin": config.isin, "isin_status": config.isin_status,
            "instrument_type": config.instrument_type, "analysis_tier": config.analysis_tier,
        }

    def prices_gate(etf_id: str) -> dict[str, object]:
        stats = evidence.price_stats.get(etf_id)
        if stats is None:
            raise InteractiveStageError(f"no local prices for {etf_id}")
        rows, first, last = stats
        needed = evidence.configs[etf_id].min_history_days if etf_id in evidence.configs else 1
        if rows < needed:
            raise InteractiveStageError(f"only {rows} local price rows for {etf_id}, {needed} required")
        return {"status": "passed", "passed": True, "rows": rows, "first_date": first, "last_date": last,
                "min_history_days": needed}

    def data_gate(etf_id: str) -> dict[str, object]:
        report = snapshot.data_report
        if not getattr(report, "analysis_allowed", False):
            raise InteractiveStageError("portfolio data validation blocks analysis")
        codes = evidence.blocking_issue_codes(etf_id)
        if codes:
            raise InteractiveStageError(f"data validation blocks {etf_id}: {', '.join(codes)}")
        return {"status": "passed", "passed": True, "as_of_date": _text(report.as_of_date)}

    def data_quality_gate(etf_id: str) -> dict[str, object]:
        as_of = getattr(snapshot.data_report, "as_of_date", None)
        if as_of is None:
            raise InteractiveStageError("data-quality as-of date is unavailable")
        return {"status": "passed", "passed": True, "as_of_date": str(as_of),
                "warning_codes": evidence.warning_issue_codes(etf_id)}

    def hard_risk_gate(etf_id: str) -> dict[str, object]:
        signal = evidence.signals.get(etf_id)
        if signal is None:
            raise InteractiveStageError(f"no signal risk-gate evidence for {etf_id}")
        blocked = sorted(signal.blocked_by)
        blocking = [code for code in blocked if not code.endswith("_unavailable")]
        if blocking:
            raise InteractiveStageError(f"{etf_id} blocked by hard risk gates: {', '.join(blocking)}")
        return {"status": "passed", "passed": True, "blocked_by": blocked,
                "unavailable_evidence": [code for code in blocked if code.endswith("_unavailable")]}

    def liquidity_gate(etf_id: str) -> dict[str, object]:
        score = _finite(evidence.features.get(etf_id, {}).get("liquidity_score"))
        if score is None:
            raise InteractiveStageError(f"liquidity evidence is unavailable for {etf_id}")
        return {"status": "passed", "passed": True, "liquidity_score": score}

    def formulas(etf_id: str) -> dict[str, object]:
        row = evidence.features.get(etf_id)
        if row is None:
            raise InteractiveStageError(f"no feature evidence for {etf_id}")
        names = sorted(k for k in row if k not in {"date", "etf_id"})
        values = {k: _finite(row[k]) for k in names if _finite(row[k]) is not None}
        if not values:
            raise InteractiveStageError(f"no finite feature values for {etf_id}")
        return {"status": "computed", "as_of": _text(row.get("date")), "values": values,
                "unavailable": [k for k in names if k not in values]}

    def core_asset_facts(etf_id: str) -> dict[str, object] | None:
        config = evidence.configs.get(etf_id)
        if config is None:
            return None
        return {"asset_class": config.asset_class, "region": config.region, "sector": config.sector,
                "theme": config.theme, "role": config.role, "currency": config.currency,
                "ter": _finite(config.ter)}

    def _metrics(etf_id: str) -> Mapping[str, object]:
        signal = evidence.signals.get(etf_id)
        return signal.supporting_metrics if signal is not None else {}

    def core_costs(etf_id: str) -> dict[str, object] | None:
        metrics = _metrics(etf_id)
        cost = _finite(metrics.get("estimated_cost_bps"))
        if cost is None:
            return None
        return {"estimated_cost_bps": cost, "cost_model_id": _text(metrics.get("cost_model_id")),
                "cost_data_quality": _text(metrics.get("cost_data_quality"))}

    def forecast_baseline(etf_id: str) -> dict[str, object] | None:
        score = _finite(_metrics(etf_id).get("baseline_score"))
        return None if score is None else {"baseline_score": score}

    registry: dict[str, Callable[[str], dict[str, object] | None]] = {
        "identity_gate": identity_gate, "prices_gate": prices_gate, "data_gate": data_gate,
        "hard_risk_gate": hard_risk_gate, "liquidity_gate": liquidity_gate,
        "data_quality_gate": data_quality_gate, "formulas": formulas,
        "core_asset_facts": core_asset_facts, "core_costs": core_costs, "forecast_baseline": forecast_baseline,
    }

    def runner(
        instrument_id: str, _analysis_input: object, stage: AnalysisStageManifest, _plan: AnalysisResourcePlan
    ) -> object:
        implementation = registry.get(stage.stage_id)
        if implementation is None:
            if stage.mandatory:
                raise InteractiveStageError(f"no local implementation is registered for mandatory stage {stage.stage_id}")
            return None  # omitted: no wired local evidence source (network-only stages included)
        return implementation(instrument_id)

    return runner


def build_profile_bindings(snapshot: "CockpitSnapshot") -> tuple[ProfileRunBinding, ...]:
    """One binding per enabled instrument of the configured universe, sharing one stage runner."""

    instrument_ids = sorted(snapshot.config.universe.enabled_ids)
    if not instrument_ids:
        raise ProfileRunUnavailable("the configured universe has no enabled instruments")
    evidence = SnapshotEvidence(snapshot)
    runner = snapshot_stage_runner(snapshot, evidence)
    return tuple(
        ProfileRunBinding(instrument_id, evidence.analysis_input(instrument_id), INTERACTIVE_ANALYZER_ID, runner)
        for instrument_id in instrument_ids
    )


def interactive_profile_binder(
    get_snapshot: Callable[[], "CockpitSnapshot | None"],
) -> Callable[[str], tuple[ProfileRunBinding, ...]]:
    """Binder for ProfileRunController: depth -> bindings for the current snapshot's universe."""

    def binder(depth: str) -> tuple[ProfileRunBinding, ...]:
        if not isinstance(depth, str) or not depth.strip():
            raise ProfileRunUnavailable("no analysis depth selected")
        snapshot = get_snapshot()
        if snapshot is None:
            raise ProfileRunUnavailable("no data snapshot is loaded")
        return build_profile_bindings(snapshot)

    return binder


__all__ = [
    "INTERACTIVE_ANALYZER_ID",
    "InteractiveStageError",
    "LOCAL_OPTIONAL_STAGES",
    "SnapshotEvidence",
    "build_profile_bindings",
    "interactive_profile_binder",
    "snapshot_stage_runner",
]
