from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class FundamentalEvidence:
    instrument_id: str
    as_of: str
    values: Mapping[str, float]
    missing_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    eligibility: str
    source_authority: str


_FIELDS = ("valuation", "profitability", "leverage", "growth", "shareholder_return")


def build_fundamental_evidence(claims: Mapping[str, object], instrument_id: str, as_of: str) -> FundamentalEvidence:
    values: dict[str, float] = {}
    missing: list[str] = []
    for field in _FIELDS:
        value = claims.get(field)
        try:
            if value is None:
                raise ValueError
            values[field] = float(value)
        except (TypeError, ValueError):
            missing.append(field)
    if len(values) < 2:
        eligibility = "not_score_eligible"
    elif any(value < 0 for value in values.values()):
        eligibility = "eligible_negative_evidence"
    else:
        eligibility = "eligible"
    warnings = ("missing_fundamental_fields",) if missing else ()
    return FundamentalEvidence(instrument_id, as_of, values, tuple(missing), warnings, eligibility, "vendor_unofficial")
