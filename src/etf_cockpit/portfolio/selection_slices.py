"""Materialise multidimensional views from one frozen SelectionRun table."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from etf_cockpit.portfolio.top_n_selection import SelectionRun


@dataclass(frozen=True)
class SelectionSliceDefinition:
    """One view into the complete candidate table; it never re-scores rows."""

    dimension: Literal["total", "sector", "country", "country_sector"]
    value: str | tuple[str, str] | None
    minimum_raw_support: int
    minimum_effective_support: float
    top_n: int


def materialise_selection_slices(
    run: SelectionRun | Mapping[str, object],
    definitions: tuple[SelectionSliceDefinition, ...] | None = None,
) -> tuple[dict[str, object], ...]:
    """Build total/country/sector/country-sector outputs over the stored table.

    Policy support defaults are copied from the versioned selection policy. A
    slice below either raw or effective support cannot display a winner. The
    effective support rule uses equal candidate weights and therefore equals
    the number of fully eligible rows in that slice.
    """

    if isinstance(run, SelectionRun):
        raw_rows: object = run.candidate_table
        mode = run.mode
        minimum_raw = run.policy.minimum_raw_support
        minimum_effective = run.policy.minimum_effective_support
        top_n = run.top_n
    else:
        raw_rows = run.get("candidate_table", ())
        mode = str(run.get("mode", "unavailable"))
        policy = run.get("policy")
        policy = policy if isinstance(policy, Mapping) else {}
        minimum_raw = _positive_int(policy.get("minimum_raw_support")) or 1
        minimum_effective = _positive_number(policy.get("minimum_effective_support")) or 1.0
        top_n = _positive_int(run.get("top_n")) or _positive_int(policy.get("top_n")) or 1
    if not isinstance(raw_rows, Sequence):
        raw_rows = ()
    rows = tuple(dict(item) for item in raw_rows if isinstance(item, Mapping))
    selected_definitions = definitions or _definitions_for(
        rows, minimum_raw, minimum_effective, top_n
    )
    all_ids = tuple(sorted(str(row.get("instrument_id", "")) for row in rows))
    output: list[dict[str, object]] = []
    for definition in selected_definitions:
        members = tuple(row for row in rows if _matches(row, definition))
        member_ids = tuple(sorted(str(row.get("instrument_id", "")) for row in members))
        excluded_ids = tuple(item for item in all_ids if item not in set(member_ids))
        eligible = tuple(row for row in members if _utility_eligible(row))
        raw_support = len(members)
        effective_support = float(len(eligible))
        if definition.dimension == "country_sector":
            classification_missing = (
                not isinstance(definition.value, tuple)
                or any(str(value).casefold() == "unavailable" for value in definition.value)
            )
        else:
            classification_missing = (
                definition.dimension in {"country", "sector"}
                and str(definition.value).casefold() == "unavailable"
            )
        if mode != "cross_asset":
            status = "unavailable"
            reason = "cross_asset_utility_unavailable"
        elif classification_missing:
            status = "unavailable"
            reason = "slice_classification_unavailable"
        elif raw_support < definition.minimum_raw_support or effective_support < definition.minimum_effective_support:
            status = "insufficient_support"
            reason = "slice_sample_support_below_minimum"
        else:
            status = "available"
            reason = None
        ranked = sorted(
            eligible,
            key=lambda row: (-float(row["utility_score"]), str(row["instrument_id"])),
        )
        winners = tuple(
            str(row["instrument_id"])
            for row in ranked[: definition.top_n]
        ) if status == "available" else ()
        winner_set = set(winners)
        materialised_rows = []
        for row in sorted(members, key=lambda item: str(item.get("instrument_id", ""))):
            instrument_id = str(row["instrument_id"])
            eligible_row = _utility_eligible(row)
            if instrument_id in winner_set:
                why_selected = ("top_n_slice_utility_rank",)
                why_not = ()
            elif not eligible_row:
                why_selected = ()
                why_not = tuple(row.get("why_not", ()))
            elif status != "available":
                why_selected = ()
                why_not = (reason or "slice_unavailable",)
            else:
                why_selected = ()
                why_not = ("outside_slice_top_n",)
            materialised_rows.append(
                {
                    "instrument_id": instrument_id,
                    "utility_score": row.get("utility_score"),
                    "selection_probability": row.get("selection_probability"),
                    "rank_stability": row.get("rank_stability"),
                    "why_selected": why_selected,
                    "why_not": why_not,
                }
            )
        output.append(
            {
                "dimension": definition.dimension,
                "value": definition.value,
                "status": status,
                "reason": reason,
                "candidate_ids": member_ids,
                "excluded_from_slice_ids": excluded_ids,
                "rejected_ids": tuple(
                    sorted(str(row.get("instrument_id", "")) for row in members if not _utility_eligible(row))
                ),
                "selected_ids": winners,
                "raw_support": raw_support,
                "effective_support": effective_support,
                "minimum_raw_support": definition.minimum_raw_support,
                "minimum_effective_support": definition.minimum_effective_support,
                "candidate_table_count": len(rows),
                "rows": tuple(materialised_rows),
                "execution_allowed": False,
            }
        )
    return tuple(output)


def _definitions_for(
    rows: tuple[dict[str, object], ...],
    minimum_raw: int,
    minimum_effective: float,
    top_n: int,
) -> tuple[SelectionSliceDefinition, ...]:
    definitions: list[SelectionSliceDefinition] = [
        SelectionSliceDefinition("total", None, minimum_raw, minimum_effective, top_n)
    ]
    sectors = sorted({str(row.get("sector", "unavailable")) for row in rows})
    countries = sorted({str(row.get("country", "unavailable")) for row in rows})
    country_sectors = sorted(
        {
            (str(row.get("country", "unavailable")), str(row.get("sector", "unavailable")))
            for row in rows
        }
    )
    definitions.extend(
        SelectionSliceDefinition("sector", value, minimum_raw, minimum_effective, top_n)
        for value in sectors
    )
    definitions.extend(
        SelectionSliceDefinition("country", value, minimum_raw, minimum_effective, top_n)
        for value in countries
    )
    definitions.extend(
        SelectionSliceDefinition("country_sector", value, minimum_raw, minimum_effective, top_n)
        for value in country_sectors
    )
    return tuple(definitions)


def _matches(row: dict[str, object], definition: SelectionSliceDefinition) -> bool:
    if definition.dimension == "total":
        return True
    if definition.dimension in {"sector", "country"}:
        return row.get(definition.dimension) == definition.value
    if definition.dimension == "country_sector" and isinstance(definition.value, tuple):
        country, sector = definition.value
        return row.get("country") == country and row.get("sector") == sector
    raise ValueError("selection slice definition is invalid")


def _utility_eligible(row: dict[str, object]) -> bool:
    return (
        row.get("utility_score") is not None
        and not row.get("hard_gate_reasons")
        and not row.get("constraint_reasons")
        and row.get("asset_family") != "unavailable"
    )


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


__all__ = ["SelectionSliceDefinition", "materialise_selection_slices"]
