"""Application-facing projection of the governed capability matrix."""

from __future__ import annotations

from dataclasses import dataclass

from etf_cockpit.governance.capability_scope import CAPABILITY_STAGES, strategy_capability_export
from etf_cockpit.governance.product_scope import load_strategy_scope


@dataclass(frozen=True)
class InstrumentCapabilityView:
    asset_family: str
    state: str
    reason_code: str
    stages: tuple[str, ...]
    horizons: tuple[str, ...]
    stage_summary: tuple[str, ...]
    prerequisite_summary: str
    execution_allowed: bool = False


@dataclass(frozen=True)
class StrategyCapabilityView:
    strategy_id: str
    name: str
    lifecycle: str
    authority: str
    ui_visibility: str
    required_data: tuple[str, ...]
    tests: tuple[str, ...]
    stage_summary: tuple[str, ...]
    score_authority: bool
    paper_authority: bool
    live_authority: bool = False
    execution_allowed: bool = False


@dataclass(frozen=True)
class ScopeCapabilityView:
    status: str
    matrix_version: str
    checksum: str
    stages: tuple[str, ...]
    strategy_count: int
    rejected_strategy_ids: tuple[str, ...]
    strategies: tuple[StrategyCapabilityView, ...]
    instruments: tuple[InstrumentCapabilityView, ...]
    diagnostics: tuple[str, ...]
    execution_allowed: bool = False


def capability_scope_view() -> ScopeCapabilityView:
    """Load and project the canonical matrix without presentation logic."""

    loaded = load_strategy_scope()
    if loaded.policy is None or loaded.diagnostic_mode:
        return ScopeCapabilityView(
            status="unavailable",
            matrix_version="unavailable",
            checksum=loaded.checksum,
            stages=tuple(CAPABILITY_STAGES),
            strategy_count=0,
            rejected_strategy_ids=(),
            strategies=(),
            instruments=(),
            diagnostics=loaded.diagnostics or ("strategy capability matrix unavailable",),
        )

    policy = loaded.policy
    payload = strategy_capability_export(policy)
    raw_strategy_rows = payload["strategy_matrix"]
    strategies = []
    for entry in policy.entries:
        rows = [row for row in raw_strategy_rows if row["strategy_id"] == entry.strategy_id]
        strategies.append(
            StrategyCapabilityView(
                strategy_id=entry.strategy_id,
                name=entry.name,
                lifecycle=entry.lifecycle,
                authority=entry.authority,
                ui_visibility=entry.ui_visibility,
                required_data=entry.required_data,
                tests=entry.tests,
                stage_summary=tuple(f"{row['stage']}={row['state']}/{row['reason_code']}" for row in rows),
                score_authority=entry.score_authority,
                paper_authority=entry.paper_authority,
            )
        )
    instrument_rows = payload["instrument_matrix"]
    instrument_stage_rows = payload["instrument_stage_matrix"]
    instruments = []
    for raw in instrument_rows:
        prerequisites = raw["prerequisites"]
        parts = [
            f"{name}={','.join(str(item) for item in prerequisites[name]) or 'none'}"
            for name in ("data", "models", "liquidity", "broker", "legal")
        ]
        instruments.append(
            InstrumentCapabilityView(
                asset_family=str(raw["asset_family"]),
                state=str(raw["state"]),
                reason_code=str(raw["reason_code"]),
                stages=tuple(str(item) for item in raw["stages"]),
                horizons=tuple(str(item) for item in raw["horizons"]),
                stage_summary=tuple(
                    f"{row['stage']}={row['state']}/{row['reason_code']}"
                    for row in instrument_stage_rows
                    if row["asset_family"] == raw["asset_family"]
                ),
                prerequisite_summary="; ".join(parts),
            )
        )
    return ScopeCapabilityView(
        status="available",
        matrix_version=policy.matrix_version,
        checksum=loaded.checksum,
        stages=tuple(CAPABILITY_STAGES),
        strategy_count=len(policy.entries),
        rejected_strategy_ids=tuple(entry.strategy_id for entry in policy.entries if entry.lifecycle == "rejected"),
        strategies=tuple(strategies),
        instruments=tuple(instruments),
        diagnostics=(),
    )


__all__ = ["InstrumentCapabilityView", "ScopeCapabilityView", "StrategyCapabilityView", "capability_scope_view"]
