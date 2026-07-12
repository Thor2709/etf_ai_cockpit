from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from etf_cockpit.signals.research_states import (
    AnalysisStatus,
    InternalSignalIntent,
    PortfolioReviewState,
    ResearchState,
    internal_intent_for_legacy_action,
    normalise_analysis_status,
    public_authority_payload,
    research_state_for_legacy_action,
)

SignalStatus = Literal["ok", "blocked", "warning", "failed"]
ModelStatus = Literal["ok", "failed", "skipped", "unavailable"]
StalenessStatus = Literal["ok", "warning", "block", "dated_only", "unknown"]


@dataclass(frozen=True)
class DatasetMetadata:
    source_name: str
    source_type: str
    as_of_date: date | None
    ingested_at: datetime | None
    currency: str | None
    timezone: str
    provider_or_manual_source: str
    checksum: str
    staleness_status: StalenessStatus
    age_days: int | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ETFIdentity:
    etf_id: str
    name: str
    isin: str | None
    ticker: str
    exchange: str | None
    currency: str
    role: str
    region: str | None = None
    sector: str | None = None
    theme: str | None = None


@dataclass(frozen=True)
class ForecastResult:
    run_id: str
    model_name: str
    model_version: str
    etf_id: str
    forecast_date: date
    horizon_days: int
    expected_return: float | None
    expected_excess_return: float | None
    q10_return: float | None = None
    q50_return: float | None = None
    q90_return: float | None = None
    forecast_vol: float | None = None
    prob_positive_return: float | None = None
    prob_beat_benchmark: float | None = None
    forecast_drawdown_prob: float | None = None
    status: ModelStatus = "ok"
    error_message: str | None = None
    model_allowed_in_score: bool = True
    is_fallback: bool = False
    fallback_model: str | None = None
    reason_unavailable: str | None = None
    oos_mase: float | None = None
    oos_directional_accuracy: float | None = None
    calibration_status: str = "not_evaluated"


@dataclass(frozen=True)
class ComponentScores:
    momentum: float
    trend: float
    risk: float
    rebalance: float
    relative_strength: float
    toto: float
    timesfm: float
    baseline_ml: float
    chatgpt_thesis: float
    cost_penalty: float
    turnover_penalty: float
    concentration_penalty: float


@dataclass(frozen=True)
class SignalResult:
    run_id: str
    signal_date: date
    etf_id: str
    # Legacy action text is retained for one migration release at the
    # import/diagnostic seam only.  Release serializers use ``research_state``
    # and never expose this field.
    action: str
    confidence: float
    total_score: float
    components: ComponentScores
    blocked_by: list[str]
    warnings: list[str]
    reason_short: str
    reason_long: str
    horizon_primary: str
    supporting_metrics: dict[str, float | str | bool | None] = field(default_factory=dict)
    suggested_trade_value_eur: float | None = None
    suggested_new_weight: float | None = None
    status: SignalStatus = "ok"
    model_versions_used: dict[str, str] = field(default_factory=dict)
    timestamp: datetime | None = None
    # v2 governance fields.  ``action`` remains a one-release compatibility
    # import/diagnostic seam; release-facing serializers use ``to_v2_dict``.
    research_state: ResearchState = ResearchState.MANUAL_REVIEW
    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
    analysis_status: AnalysisStatus = "unavailable"
    research_promotion_allowed: bool = False
    portfolio_review_allowed: bool = False
    execution_allowed: Literal[False] = False
    legacy_action: str | None = None
    internal_intent: InternalSignalIntent = InternalSignalIntent.NONE
    migration_version: str = "2.0"
    gate_policy_version: str = "unavailable"
    gate_policy_checksum: str = "unavailable"
    schema_version: str = "2.0"

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "research_state", ResearchState(str(self.research_state)))
        except ValueError:
            object.__setattr__(self, "research_state", ResearchState.MANUAL_REVIEW)
        try:
            object.__setattr__(self, "portfolio_review_state", PortfolioReviewState(str(self.portfolio_review_state)))
        except ValueError:
            object.__setattr__(self, "portfolio_review_state", PortfolioReviewState.NOT_APPLICABLE)
        if self.legacy_action is None:
            object.__setattr__(self, "legacy_action", str(self.action).strip() or None)
        if self.research_state is ResearchState.MANUAL_REVIEW:
            object.__setattr__(self, "research_state", research_state_for_legacy_action(self.action))
        if self.internal_intent is InternalSignalIntent.NONE:
            object.__setattr__(self, "internal_intent", internal_intent_for_legacy_action(self.action))
        raw_analysis_status = str(self.analysis_status or "").strip().casefold()
        valid_analysis_status = raw_analysis_status in {"complete", "partial", "unavailable"}
        object.__setattr__(self, "analysis_status", normalise_analysis_status(raw_analysis_status))
        # This compatibility seam cannot grant authority; Task 3's typed
        # resolver is the only owner of positive promotion/review flags.
        object.__setattr__(self, "research_promotion_allowed", False)
        object.__setattr__(self, "portfolio_review_allowed", False)
        object.__setattr__(self, "execution_allowed", False)
        if valid_analysis_status and self.analysis_status == "unavailable":
            derived: AnalysisStatus = "partial" if self.blocked_by or self.warnings else "complete"
            object.__setattr__(self, "analysis_status", derived)

    def to_v2_dict(self) -> dict[str, object]:
        """Return release-facing authority fields without legacy action verbs."""

        return public_authority_payload(
            research_state=self.research_state,
            portfolio_review_state=self.portfolio_review_state,
            analysis_status=self.analysis_status,
            research_promotion_allowed=self.research_promotion_allowed,
            portfolio_review_allowed=self.portfolio_review_allowed,
            legacy_action=self.legacy_action,
            migration_version=self.migration_version,
            gate_policy_version=self.gate_policy_version,
            gate_policy_checksum=self.gate_policy_checksum,
        )

    def to_public_dict(self) -> dict[str, object]:
        return self.to_v2_dict()


@dataclass(frozen=True)
class DataQualityIssue:
    etf_id: str
    severity: Literal["info", "warning", "block"]
    code: str
    message: str
    date_value: date | None = None


@dataclass(frozen=True)
class DataQualityReport:
    as_of_date: date
    issues: list[DataQualityIssue]
    dataset_metadata: list[DatasetMetadata] = field(default_factory=list)

    @property
    def blocked_etfs(self) -> set[str]:
        return {issue.etf_id for issue in self.issues if issue.severity == "block"}

    @property
    def warning_etfs(self) -> set[str]:
        return {issue.etf_id for issue in self.issues if issue.severity == "warning"}

    @property
    def status(self) -> str:
        if any(issue.severity == "block" for issue in self.issues):
            return "Blocked"
        if any(issue.severity == "warning" for issue in self.issues):
            return "Warning"
        return "Clean"

    @property
    def trading_allowed(self) -> bool:
        return not any(issue.severity == "block" for issue in self.issues)
