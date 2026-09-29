"""Point-in-time decision contracts and peer-relative domain scoring."""

from etf_cockpit.analysis.decision.contracts import (
    ComparisonScope,
    DecisionDriver,
    DomainSlot,
    EligibilityResult,
    GateResult,
    InstrumentDecisionAssessment,
    MetricShape,
    OpportunitySlot,
    RequirementClass,
    ScoredMetric,
    SubfamilySlot,
)
from etf_cockpit.analysis.decision.domains import (
    DomainReference,
    DomainRegistry,
    MetricDefinition,
    build_instrument_assessment,
    load_domain_registry,
)
from etf_cockpit.analysis.decision.stock import (
    StockDecisionMap,
    compose_stock_decision,
    load_stock_decision_map,
)

__all__ = [
    "ComparisonScope",
    "DecisionDriver",
    "DomainReference",
    "DomainRegistry",
    "DomainSlot",
    "EligibilityResult",
    "GateResult",
    "InstrumentDecisionAssessment",
    "MetricDefinition",
    "MetricShape",
    "OpportunitySlot",
    "RequirementClass",
    "ScoredMetric",
    "SubfamilySlot",
    "StockDecisionMap",
    "build_instrument_assessment",
    "compose_stock_decision",
    "load_domain_registry",
    "load_stock_decision_map",
]
