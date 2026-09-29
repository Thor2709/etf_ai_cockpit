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
    "build_instrument_assessment",
    "load_domain_registry",
]
