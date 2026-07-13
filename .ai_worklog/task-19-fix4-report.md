# Task 19 Fix 4 - review findings

## Task completed

Fixed the latest Task 19 Instrument Detail review findings without changing
score authority or adding an import/export service:

- `_safe_bool` now accepts native, numpy and pandas boolean scalars, preserves
  explicit false values, and uses the requested fail-closed default for
  malformed/missing values.
- Canonical row scoping now validates `instrument_id`, `etf_id` and
  `display_id` wherever the shared selector is used. Matching rows with a
  contradictory populated alias are rejected; foreign-only and idless rows
  remain unavailable/manual-review as before.
- Fundamentals and parsed disclosure panels use null-safe boolean handling;
  nullable or malformed eligibility cannot become score-eligible.
- Broad attribution renders canonical `alpha`; sector alpha remains separate.
- Instrument Detail exposes a keyed, functional export control backed by the
  existing `AppState.export_audit_packet` service. It is disabled with an
  explicit unavailable message when the selected model or capability is
  absent.
- Evidence panels render reusable Source ID, Authority and Conflict badges,
  carrying stored provenance through the view model and using `unavailable`
  when no value is present.

## RED evidence

`python -m pytest tests/test_task19_instrument_detail.py -q --tb=short`

Before the production changes: 17 passed, 7 failed. The failures were the
intended regressions for numpy/pandas booleans, contradictory `display_id`,
nullable fundamentals, canonical broad alpha, the missing export control and
missing provenance badge labels.

## GREEN and affected checks

- `python -m pytest tests/test_task19_instrument_detail.py -q --tb=short` - 24 passed.
- `python -m pytest tests/test_instrument_detail.py tests/test_fundamentals.py tests/test_parsed_disclosures.py tests/test_task18_integration.py -q --tb=short` - 28 passed.
- `python -m ruff check src/etf_cockpit/app/selectors/instrument_detail.py src/etf_cockpit/app/pages/instrument_detail.py tests/test_task19_instrument_detail.py` - passed.
- `python -m compileall -q src/etf_cockpit/app/selectors/instrument_detail.py src/etf_cockpit/app/pages/instrument_detail.py tests/test_task19_instrument_detail.py` - passed.
- `git diff --check` - passed (only expected CRLF conversion warnings were emitted).

## Skipped or baseline failures

- `tests/test_button_contracts.py::test_button_inventory_covers_registered_routes_and_control_metadata` still reports the pre-existing uncovered `dashboard.open-what-changed` and `dashboard.score-row-detail.*` controls; the new Instrument Detail key is covered by the added acceptance entry.
- The combined affected command including `tests/test_simple_scores.py` was stopped after two existing fixture/configuration failures for missing trade-candidate data and secondary-universe rows. Those failures are outside Task 19 ownership.
- Full release/package/browser/keyboard/responsive/clean-first-run evidence remains closure-pending per the Task 19 brief.

## Remaining uncertainty and risk

The existing audit packet export is portfolio-wide rather than a new
instrument-only archive; the Instrument Detail control intentionally routes to
that repository-supported service and does not invent a Task 20 export API.
