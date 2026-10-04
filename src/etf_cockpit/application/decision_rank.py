"""Record-gated decision-rank cutover routing for facade consumers (application; ADR-0002)."""

from __future__ import annotations

from collections.abc import Mapping


def decision_rank_route(
    consumer: str,
    rank_scores: Mapping[str, object] | None = None,
    *,
    promotion_record: Mapping[str, object] | None = None,
    cutover_enabled: bool | None = None,
) -> dict[str, object]:
    """Route a facade consumer through the configured, record-gated rank cutover."""

    from etf_cockpit.analysis.decision.rank_validation import route_consumer_rank

    return route_consumer_rank(
        consumer,
        rank_scores or {},
        promotion_record=promotion_record,
        cutover_enabled=cutover_enabled,
    )
