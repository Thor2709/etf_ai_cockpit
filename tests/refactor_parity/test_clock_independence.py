"""Wall-clock independence of the pipeline goldens.

The goldens are recorded with ``now`` = 2026-09-30T12:00Z.  Here the whole pipeline is re-run with the frozen ``now``
moved +400 days and +7 hours (``today`` stays the pinned business date, which the sample prices end on).  Every
pipeline section must still equal its fixture: no pinned value (and no schema) depends on ``datetime.now()``.

Clock reads on the pinned paths (all go through ``tests/refactor_parity/_clock.py``, installed before etf_cockpit
is imported in the capture subprocess):

* ``date.today()``  - etf_cockpit.data.sample_data (sample price end date): FROZEN to 2026-09-30.
* ``datetime.now()``/``utcnow()``/``today()`` - provenance, atomic_io, classification, signal_pipeline, session_log,
  timing, logging, workflow, trust_artifacts, fund_documents, scheduler, shadow_run, app.state: FROZEN (timestamps
  only; shifted here to prove independence).
* ``time.time()`` - pandas CSV parser timing, logging: COUNTED, not frozen (durations/locks; no output depends on it).
* ``pandas.Timestamp.now()`` - sample_data ``ingested_at`` column only: cannot be frozen (compiled classmethod), the
  column is excluded from every digest.
"""

from __future__ import annotations

import pytest

from refactor_parity._harness import assert_section_matches_fixture, refresh_requested

PIPELINE_SECTIONS = ("snapshot", "backtest", "scoreboard", "persisted_schema")


@pytest.mark.skipif(refresh_requested(), reason="golden refresh run: fixtures are being rewritten")
@pytest.mark.parametrize("section", PIPELINE_SECTIONS)
def test_goldens_do_not_depend_on_the_wall_clock(shifted_pipeline_capture: dict[str, object], section: str) -> None:
    sections = shifted_pipeline_capture["sections"]
    assert_section_matches_fixture(section, sections[section])  # type: ignore[index]


def test_the_shifted_run_really_used_a_different_clock(shifted_pipeline_capture: dict[str, object]) -> None:
    clock = shifted_pipeline_capture["clock"]
    assert clock["today"] == "2026-09-30"  # type: ignore[index]
    assert clock["now"] == "2027-11-04T19:00:00+00:00"  # type: ignore[index]
    reads = clock["reads"]  # type: ignore[index]
    assert reads["etf_cockpit.data.sample_data:date.today"] >= 1
    # The sample dates came from the frozen date, not from the real clock.
    assert any(key.endswith(":datetime.now") for key in reads)
