from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

Action = Literal[
    "buy",
    "add",
    "hold",
    "trim",
    "sell",
    "no_trade",
    "manual_review",
    "add_candidate",
    "trim_candidate",
]
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
    action: Action
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
