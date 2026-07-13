# Task 15 fix 3 - deterministic KID ongoing-cost evidence

## Task completed

Fixed `build_priips_kid_cost_evidence` so the approved `liquidity_cost`
component reads a numeric percentage only from the parser's `ongoing_costs`
field. Entry, exit, transaction and performance rows remain descriptive
evidence and cannot mask the ongoing-cost value; no cost proxy is invented.
The approved score keys, inverse SRI mapping, weights, issuer-document
authority and score eligibility gates are unchanged.

## Files and symbols examined

- `src/etf_cockpit/signals/simple_scores.py`: `build_priips_kid_cost_evidence`.
- `tests/test_simple_scores.py`: existing KID score regressions and new
  parser-like cost-field/missing-evidence regressions.
- `src/etf_cockpit/parsers/priips_kid.py`: parser cost-field names and ordering.

## Findings or changes

- Replaced broad concatenated-value percentage matching with a deterministic
  `ongoing_costs` field lookup.
- Added a complete five-field parser-order regression proving that changing
  ongoing cost changes the score monotonically (higher ongoing cost cannot
  improve liquidity/cost score).
- Added a missing-ongoing regression proving entry/exit/transaction/performance
  percentages do not become a proxy; without SRI the component is `risk`,
  `N/A`, score-ineligible and has no raw/10-point score.

## Evidence

- New RED regressions failed before the fix: the complete-field scores both
  clamped to 0.0 from the entry percentage, and missing ongoing evidence was
  incorrectly reported as `liquidity_cost`.
- Focused Task 15 parser/persistence/registry/UI/audit and KID score tests:
  53 passed.
- Ruff, compileall and `git diff --check`: passed.

## Commands or tests run

- `python -m pytest -q tests/test_simple_scores.py::test_complete_kid_cost_fields_score_the_ongoing_cost_row tests/test_simple_scores.py::test_kid_cost_evidence_without_numeric_ongoing_cost_is_unavailable --disable-warnings --maxfail=2` (RED: 2 failed; GREEN: 2 passed).
- Focused Task 15/score pytest command covering parser, methodology, parsed disclosures, registry, instrument detail, trust audit and all KID score regressions (53 passed).
- `python -m ruff check src/etf_cockpit/signals/simple_scores.py tests/test_simple_scores.py`.
- `python -m compileall -q src tests`.
- `git diff --check`.

## Remaining uncertainty and risk

- Transaction costs are intentionally not used as an ongoing-cost fallback;
  the approved score seam has no contract permitting a transaction-cost proxy.
- Full release, package and browser gates were not repeated; they are outside
  this scoped parser-score blocker.

## Recommended next action

Review and merge commit `fix: select KID ongoing cost evidence deterministically`.
