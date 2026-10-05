"""Golden: the persisted scoreboard of the pinned sample universe (AppState._write_current_scoreboard)."""

from __future__ import annotations

from refactor_parity._harness import assert_matches_golden

NOTES = (
    "Built by AppState._write_current_scoreboard on the second (cached) snapshot of the pinned pipeline; the scored "
    "SimpleInstrumentScore objects are observed through a spy on write_simple_scoreboard and recorded under score_objects "
    "(final_score_10, rank, score_rank, per-component key/score_10/status/authority/eligibility, canonical_score, "
    "authority_decision, ... : fields the frame does not carry; the frame has no final_score_10/rank column). The frame is "
    "then read back from data/derived/scoreboard.parquet. Recorded: the full column list, order and dtypes; the instrument order "
    "(rank order); EVERY column as a list in that order (final_score_10, every *_score_10 / *_status / *_authority "
    "component, rank/score_rank, final_label/decision/research_state, *_allowed eligibility flags, canonical_* columns, "
    "text columns), plus the canonical fail-closed projection's shape/columns/order. Missing values are explicit "
    "('<NaN>' for float NaN, null for None); nothing is zero-filled. sha256 values are masked. Floats compared "
    "rel=1e-9/abs=1e-12, everything else exact. Forecast components are N/A in this environment because the clean "
    "checkout has no universe store (universe_revision ''), which makes forecasts fail closed. Clock: see _clock.py."
)


def test_scoreboard_matches_golden(pipeline_capture: dict[str, object]) -> None:
    section = pipeline_capture["sections"]["scoreboard"]  # type: ignore[index]
    assert_matches_golden("scoreboard", section, notes=NOTES)


def test_scoreboard_golden_is_not_vacuous(pipeline_capture: dict[str, object]) -> None:
    section = pipeline_capture["sections"]["scoreboard"]  # type: ignore[index]
    columns = section["columns_by_name"]
    assert section["score_history_warning"] is None
    assert section["shape"][0] >= 50 and section["shape"][1] > 150
    assert {"final_label", "decision", "research_state", "legacy_action", "execution_allowed"} <= set(section["columns"])
    assert any(name.startswith("canonical_") for name in section["columns"])
    assert set(columns["execution_allowed"]) == {False}
    assert columns["instrument_id"] == section["order"]
    assert section["canonical_projection"]["order"] == section["order"]
    objects = section["score_objects"]
    assert objects["order"] == section["order"]
    ranks = [rank for rank in objects["rank"] if rank is not None]
    assert ranks == list(range(1, len(ranks) + 1))
    assert any(value is not None for value in objects["final_score_10"])
    # Unranked instruments carry no components and no score at the base.
    assert all(len(components) >= 5 for rank, components in zip(objects["rank"], objects["components"], strict=True) if rank is not None)
    assert all(len(components) == 0 for rank, components in zip(objects["rank"], objects["components"], strict=True) if rank is None)
    assert len(ranks) >= 40
