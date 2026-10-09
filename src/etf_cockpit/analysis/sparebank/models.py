"""Typed, immutable contracts for native Sparebank EC analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


CONTRACT_ID = "sparebank-analysis-suite.v1"
UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class SparebankRoutingResult:
    """Fail-closed routing decision based only on canonical evidence."""

    applies: bool
    suite_id: str | None
    reason_codes: tuple[str, ...] = ()
    evidence: Mapping[str, object] = field(default_factory=dict)
    execution_allowed: bool = False

    @property
    def allowed(self) -> bool:
        return self.applies


RoutingResult = SparebankRoutingResult


@dataclass(frozen=True)
class ECClaimState:
    """Point-in-time ownership claim state; absent facts remain ``None``."""

    effective_at: str | None = None
    known_at: str | None = None
    source_id: str | None = None
    revision_id: str | None = None
    instrument_id: str | None = None
    bank_entity: str | None = None
    listing_id: str | None = None
    owner_pools: Mapping[str, float] = field(default_factory=dict)
    self_owned_pools: Mapping[str, float] = field(default_factory=dict)
    owner_pool_total: float | None = None
    self_owned_pool_total: float | None = None
    reported_eierbrok: float | None = None
    reconstructed_eierbrok: float | None = None
    eierbrok_difference: float | None = None
    registered_ec_count: float | None = None
    outstanding_ec_count: float | None = None
    treasury_ec_count: float | None = None
    period_end_ec_count: float | None = None
    weighted_average_ec_count: float | None = None
    owner_attributable_book: float | None = None
    owner_attributable_earnings: float | None = None
    foundation_ec_count: float | None = None
    foundation_holdings: object | None = None
    voting_share: float | None = None
    venue: str | None = None
    accounting_equity: float | None = None
    claim_status: str = "partial"
    provenance: Mapping[str, str] = field(default_factory=dict)
    field_provenance: Mapping[str, str] = field(default_factory=dict)
    unavailable_fields: tuple[str, ...] = ()
    coverage: float = 0.0
    reason_codes: tuple[str, ...] = ()
    execution_allowed: bool = False

    @property
    def source_revision(self) -> str | None:
        return self.revision_id

    @property
    def eierbrok(self) -> float | None:
        return self.reconstructed_eierbrok


@dataclass(frozen=True)
class ECClaimPath:
    """Projection of the two capital pools under their own payout ratios."""

    periods: tuple[Mapping[str, object], ...] = ()
    formula: str = "eierbrok = owner_pool / (owner_pool + self_owned_pool)"
    reason_codes: tuple[str, ...] = ()
    execution_allowed: bool = False


@dataclass(frozen=True)
class SparebankAnalysis:
    """Versioned native suite output with explicit unavailable sections."""

    contract: str
    routing: SparebankRoutingResult
    claim_state: ECClaimState
    claim_path: ECClaimPath
    coverage: float
    reason_codes: tuple[str, ...] = ()
    provenance: Mapping[str, object] = field(default_factory=dict)
    owner_book_per_ec: float | None = None
    owner_eps: float | None = None
    owner_pb: float | None = None
    owner_pe: float | None = None
    count_conventions: Mapping[str, str] = field(default_factory=dict)
    bank_economics: object = UNAVAILABLE
    events: object = UNAVAILABLE
    valuation: object = UNAVAILABLE
    scorecard: object = UNAVAILABLE
    generic_valuation_status: str = "not_applicable"
    generic_valuation_reason: str | None = None
    execution_allowed: bool = False

    @property
    def suite_id(self) -> str:
        return self.contract

    @property
    def contract_id(self) -> str:
        return self.contract


@dataclass(frozen=True)
class BankEconomics:
    """Interpretation-layer output; unavailable inputs remain ``None``."""

    status: str = "partial"
    reported: Mapping[str, object] = field(default_factory=dict)
    normalised: Mapping[str, object] = field(default_factory=dict)
    resilience: Mapping[str, object] = field(default_factory=dict)
    credit: Mapping[str, object] = field(default_factory=dict)
    funding: Mapping[str, object] = field(default_factory=dict)
    concentration: Mapping[str, object] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    calculation_ids: tuple[str, ...] = ()
    unavailable_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    coverage: float = 0.0
    execution_allowed: bool = False
    # SB2: book calculations that feed the lending and capital-allocation axes, and the plain-language
    # reason each missing figure is missing (input id -> reason).
    lending: Mapping[str, object] = field(default_factory=dict)
    allocation: Mapping[str, object] = field(default_factory=dict)
    reasons: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SparebankEventAnalysis:
    """Point-in-time structural-event ledger and merger economics."""

    status: str = "partial"
    events: tuple[Mapping[str, object], ...] = ()
    recipient_ledger: tuple[Mapping[str, object], ...] = ()
    unresolved_milestones: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    coverage: float = 0.0
    execution_allowed: bool = False


@dataclass(frozen=True)
class SparebankScorecard:
    """Versioned underwriting breakdown and separately labelled tactical evidence."""

    status: str
    formula_version: str
    formula_checksum: str
    judgement_version: str
    judgement_status: str
    judgement_source: str
    axes: Mapping[str, object] = field(default_factory=dict)
    composite_10: float | None = None
    composite_before_gate_cap_10: float | None = None
    gate_cap_10: float | None = None
    overall_coverage: float = 0.0
    composite_coverage: float = 0.0
    missing_axes: tuple[str, ...] = ()
    gate_reasons: tuple[str, ...] = ()
    underwriting: Mapping[str, object] = field(default_factory=dict)
    tactical: Mapping[str, object] = field(default_factory=dict)
    execution_allowed: bool = False


__all__ = [
    "CONTRACT_ID",
    "UNAVAILABLE",
    "ECClaimPath",
    "ECClaimState",
    "BankEconomics",
    "SparebankEventAnalysis",
    "SparebankScorecard",
    "RoutingResult",
    "SparebankAnalysis",
    "SparebankRoutingResult",
]
