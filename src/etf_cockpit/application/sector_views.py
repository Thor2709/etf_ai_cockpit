"""Verified real-asset, cyclical and innovation sector projections for Instrument Detail (application; ADR-0002)."""

from collections.abc import Mapping
import math

from etf_cockpit.analysis.real_asset_sector_adapters import (
    RealAssetAdapterError,
    RealAssetProjection,
    unavailable_real_asset_projection,
    verify_real_asset_projection,
)
from etf_cockpit.analysis.cyclical_sector_adapters import (
    CyclicalAdapterError,
    CyclicalProjection,
    unavailable_cyclical_projection,
    verify_cyclical_projection,
)
from etf_cockpit.analysis.innovation_sector_adapters import (
    InnovationAdapterError,
    InnovationProjection,
    unavailable_innovation_projection,
    verify_innovation_projection,
)


def load_sector_position_metadata(snapshot: object, decision_time: object, ids: list[str]) -> dict[str, dict[str, object]]:
    """Direct stocks use the existing dated classification resolver."""
    supplied = getattr(snapshot, "sector_position_metadata", None)
    if isinstance(supplied, Mapping):
        return dict(supplied)
    from etf_cockpit.core.paths import ROOT
    from etf_cockpit.data.classification import classification_store_exists, read_instrument_context

    if not classification_store_exists(ROOT):
        return {}
    result = {}
    for instrument_id in ids:
        context = read_instrument_context(ROOT, instrument_id, effective_at=decision_time, decision_time=decision_time)
        if context.instrument_type != "stock" or context.classification_status not in {"resolved", "available"}:
            continue
        result[instrument_id] = {
            "exposure_type": "security", "sector": context.sector,
            "economic_country": context.operating_country,
            "entity": context.entity_id, "asset_class": context.asset_class,
            # Conservative projection availability, after every source was
            # resolved at this cutoff; never a fabricated publication date.
            "known_at": context.decision_time, "source_ids": context.source_ids,
        }
    return result


def build_sector_attractiveness(snapshot: object, sectors: list[str]) -> dict[str, dict[str, object]]:
    """Average available canonical attractiveness within configured sectors.

    Coverage counts scored instruments, not exposure weights. Missing scores
    do not become neutral observations or zero returns.
    """
    universe = getattr(getattr(snapshot, "config", None), "universe", None)
    instruments = list(getattr(universe, "etfs", ()))
    supplied = getattr(snapshot, "sector_score_evidence", None)
    if supplied is None and instruments:
        from etf_cockpit.application.score_views import snapshot_scores

        supplied = [{"instrument_id": row.display_id, "score": getattr(getattr(row, "canonical_score", None), "attractiveness_10", None)} for row in snapshot_scores(snapshot)]
    scores = {}
    for row in supplied or ():
        key, value = str(row.get("instrument_id")), row.get("score")
        if key not in scores or scores[key] is None:
            scores[key] = value
    result = {}
    enabled = set(getattr(universe, "enabled_ids", ()))
    for sector in sectors:
        members = [item.id for item in instruments if item.id in enabled and getattr(item, "sector", None) == sector]
        values = [float(scores[key]) for key in members if isinstance(scores.get(key), (int, float)) and math.isfinite(scores[key])]
        result[sector] = {"score": sum(values) / len(values) if values else None, "coverage": len(values) / len(members) if members else None, "count": len(values), "reason": None if values else "No canonical attractiveness evidence is available for this sector.", "missing": [key for key in members if key not in scores or scores[key] is None]}
    return result


def load_real_asset_projection(
    instrument_id: str,
    *,
    projection: RealAssetProjection | Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Verify optional in-memory real-asset evidence; never calculate in the UI."""

    if projection is None:
        return unavailable_real_asset_projection(instrument_id)
    try:
        payload = verify_real_asset_projection(projection)
        if payload.get("instrument_id") != str(instrument_id):
            raise RealAssetAdapterError("real-asset projection identity mismatch")
        return payload
    except (RealAssetAdapterError, TypeError, ValueError):
        return unavailable_real_asset_projection(instrument_id, "real_asset_evidence_invalid")


def load_cyclical_projection(
    instrument_id: str,
    *,
    projection: CyclicalProjection | Mapping[str, object] | None = None,
    expected_source_digest: str | None = None,
) -> dict[str, object]:
    """Verify optional in-memory cyclical evidence; never calculate in the UI."""

    if projection is None or expected_source_digest is None:
        return unavailable_cyclical_projection(instrument_id)
    try:
        payload = verify_cyclical_projection(
            projection,
            expected_source_digest=expected_source_digest,
        )
        if payload.get("instrument_id") != str(instrument_id):
            raise CyclicalAdapterError("cyclical projection identity mismatch")
        return payload
    except (CyclicalAdapterError, TypeError, ValueError):
        return unavailable_cyclical_projection(instrument_id, "cyclical_evidence_invalid")


def load_innovation_projection(
    instrument_id: str,
    *,
    projection: InnovationProjection | Mapping[str, object] | None = None,
    expected_source_digest: str | None = None,
) -> dict[str, object]:
    """Verify optional local innovation-sector evidence; never calculate in UI."""

    if projection is None or expected_source_digest is None:
        return unavailable_innovation_projection(instrument_id)
    try:
        payload = verify_innovation_projection(
            projection,
            expected_source_digest=expected_source_digest,
        )
        if payload.get("instrument_id") != str(instrument_id):
            raise InnovationAdapterError("innovation projection identity mismatch")
        return payload
    except (InnovationAdapterError, TypeError, ValueError):
        return unavailable_innovation_projection(instrument_id, "innovation_evidence_invalid")
