# Task 15 fix 2 - KID score direction

## Task completed

Corrected the PRIIPs KID score direction in `build_priips_kid_cost_evidence`.
Disclosed ongoing costs now apply a bounded inverse penalty to the
`liquidity_cost` raw score, and PRIIPs SRI values 1-7 map inversely onto the
bounded risk raw-score contract. Component keys, approved weights, issuer
document authority and `execution_allowed=False` remain unchanged; no proxy
values are created when disclosure evidence is absent.

## Findings or changes

- Added RED regression tests proving that a higher disclosed ongoing cost must
  not improve `liquidity_cost`, and a higher SRI must not improve `risk`.
- The RED run reproduced both review blockers: 0.50% scored 7.5 versus 0.05%
  scoring 5.2, and SRI 6 scored 6.0 versus SRI 2 scoring 2.0.
- Applied `_clamp(-explicit_value)` for disclosed cost percentages, preserving
  the existing `[-1, 1]` raw-score contract without inventing a cost ceiling.
- Applied an inverse 1-7 SRI mapping across the same raw-score contract.

## Evidence

- Exact monotonicity regressions: 2 passed after the implementation.
- Focused Task 15 parser, persistence, registry, UI, audit and KID score
  tests: 51 passed.
- Ruff, compileall and `git diff --check`: passed.

## Commands or tests run

- `python -m pytest -q tests/test_simple_scores.py::test_higher_disclosed_ongoing_cost_never_improves_liquidity_cost_score tests/test_simple_scores.py::test_higher_sri_never_improves_risk_score --disable-warnings --maxfail=2` (RED: 2 failed, then GREEN: 2 passed).
- `python -m pytest -q tests/test_priips_kid_parser.py tests/test_index_methodology_parser.py tests/test_parsed_disclosures.py tests/test_fund_documents.py tests/test_instrument_detail.py tests/test_button_contracts.py tests/test_trust_critical_artifacts.py::test_trust_evidence_pages_are_registered tests/test_trust_critical_artifacts.py::test_audit_export_includes_trust_critical_evidence_and_session_log tests/test_simple_scores.py::test_complete_fresh_kid_is_observable_as_issuer_cost_evidence tests/test_simple_scores.py::test_incomplete_or_stale_kid_is_excluded_from_cost_evidence tests/test_simple_scores.py::test_higher_disclosed_ongoing_cost_never_improves_liquidity_cost_score tests/test_simple_scores.py::test_higher_sri_never_improves_risk_score --disable-warnings --maxfail=1` (51 passed).
- `python -m ruff check src/etf_cockpit/signals/simple_scores.py tests/test_simple_scores.py`.
- `python -m compileall -q src tests`.
- `git diff --check`.

## Remaining uncertainty and risk

- The full repository release gate, full `tests/test_simple_scores.py` fixture
  run and package/browser checks were not repeated; they are outside this
  focused score-direction fix.

## Recommended next action

Review and merge the scoped commit `fix: correct KID evidence score direction`.
