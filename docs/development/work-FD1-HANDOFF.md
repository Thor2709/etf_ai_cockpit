# FD1 #937 correction pass 1 audit

Authority: the supplied six BLOCKING findings and local packet
`C:/dev/queues/FD1/issue-937.md` (P1-01 through P1-08, consolidated register,
and Cycle 2 delta). This is a local correction handoff, not programme acceptance,
GitHub synchronisation, a merge, or packaged release evidence.

## Baseline identities and method

- Pre-train base: `26b887aeab0a151cb5454145dc499799569c70a3`, independently
  confirmed by `C:/dev/queues/FD1/base.txt` and FD1 commit ancestry.
- Correction starting HEAD: `4c5a11a73271054dbc283918e221be6781f748e1`;
  preceding implementation: `56d44a866d8b9a88961db338880d0c44155fe128`.
  Both commits are retained. The starting checkout was clean.
- Unmodified starting-HEAD `tests/test_fund_p0_semantics.py` was run against
  pre-train `src/` and `configs/` extracted by `git archive` into an isolated
  temporary directory, with `PYTHONPATH` and `ETF_COCKPIT_ROOT` pointing there.
  Result: **12 failed, 1 passed**. No checkout, branch, stash, or commit changed.
  Local output/XML: `C:/Users/thor2/AppData/Local/Temp/fd1-baseline-a4nskpwo/`.
- Before correction edits, the starting checkout passed **109 tests** across
  semantics, stock sources/metrics/evidence/store/research, decision stock, and
  stock research parity. This establishes those existing tests' starting state;
  it does not validate cases the original tests omitted.
- Dispositions below use the pre-train base, not an already-corrected base.
  Failure at a missing new result field demonstrates an absent acceptance
  contract; it is not claimed as proof of every later assertion independently.
- Expanded correction regressions were also run against isolated archived
  sources at both identities: **19 failed, 2 passed** on pre-train base,
  **9 failed, 12 passed** on starting HEAD. The extra passing pre-train case is
  the currency-conflict guard, before cash-only fallback existed; starting HEAD
  introduces the reviewed fallback conflict and the correction fixes it.
  XML/output roots: `C:/Users/thor2/AppData/Local/Temp/fd1-expanded-26b887ae-j0zayiq1/`
  and `C:/Users/thor2/AppData/Local/Temp/fd1-expanded-4c5a11a7-178z0doi/`.
  These runs precede the subsequently added sequential-NCI assertions.

## Complete per-entry outcomes

All test names below belong to `tests/test_fund_p0_semantics.py`.

| Entry | Outcome | Observed pre-train baseline and regression |
| --- | --- | --- |
| P1-01 | FIXED | `test_cash_only_sec_balance_keeps_cash_and_uses_a_covered_lower_bound`: FAIL, missing `cash`; cash-only coverage retained. |
| P1-02 | FIXED | `test_intangible_only_capex_is_retained_as_partial_and_fcf_fails_closed`: FAIL, missing `capex_extra`; partial spend retained without fabricated total. |
| P1-03 | FIXED | `test_roe_roic_formula_parity_across_metrics_research_and_capital_efficiency`: FAIL, closing versus average ROE; correction extends parity to nonzero leases, native evidence, and strict comparability. |
| P1-04 | FIXED | `test_stale_report_is_display_only_and_never_score_eligible`: FAIL, numeric stale score; `test_stale_metrics_do_not_inflate_quality_evidence`: FAIL, absent input-count contract. Correction adds SEC late publication and sparse-publication cases. |
| P1-05 | FIXED | `test_share_count_disagreement_requires_reconciliation`: both ADR/split cases FAIL, market cap remained `ok`. |
| P1-06 | FIXED | `test_unattributed_consolidated_income_is_unavailable_when_nci_exists`: FAIL, consolidated income retained. Correction covers native NCI ROIC and configurable selected concepts. |
| P1-07 | FIXED | `test_quality_component_exposes_the_two_of_six_case_without_claiming_solvency`: FAIL, absent `input_count`; six declared inputs/two used remain explicit. Gate/weight changes excluded. |
| P1-08 | REJECTED (test already passed on the base) | `test_yahoo_acquisition_cannot_be_used_for_a_pre_acquisition_decision`: PASS, acquisition knowledge time already excludes January 2024 replay. Guard retained. |
| B102-N001 | FIXED | P1-02 test FAIL on base; extra-only capex retained and incomplete FCF unavailable. |
| B102-N003 | FIXED | P1-06 attribution guard, including common-available and unverified configured income. The original singleton baseline FAIL is recorded above; expanded concept baseline is recorded below. No external issuer evidence is claimed. |
| B104-N001 | FIXED | P1-01 cash-only test FAIL on base. |
| B104-N003 | FIXED | P1-04 stale report test FAIL on base; late SEC publication cannot reset fiscal age. |
| B105-N001 | FIXED | P1-06 test FAIL on base; correction also explicitly asserts native NCI ROIC unavailable for incompatible numerator/capital ownership. |
| B105-N003 | FIXED | Stale evidence-quality test FAIL on base; stale inputs have no score or used-count contribution. |
| B003 (share-count override, as cited by the issue) | FIXED | P1-05 ADR and split tests both FAIL on base; reconciliation required. No longer register identifier is invented. |
| B03-C2-N001 | FIXED | `test_diluted_weighted_average_shares_do_not_replace_point_in_time_shares`: FAIL on base, per-share valuation used diluted average 15 instead of point-in-time 10. |
| B04-C2-N001 | FIXED | `test_yahoo_lease_exceeding_total_debt_does_not_create_negative_gross_debt`: FAIL on base, invalid `ib_debt` retained. |
| B05-C2-N001 | FIXED | `test_sparse_newer_statement_row_keeps_previous_cash_flow_evidence`: FAIL on base, missing CFO. Carry-forward kept; correction preserves original per-field knowledge time. |

## Correction findings and defaults

1. Research, strict-comparable research, capital efficiency and native evidence
   reuse `stock_metrics.invested_capital`. ROIC uses closing capital, as already
   chosen by the earlier FD1 implementation. Separately reported leases are
   added to debt excluding those leases; no net-debt redefinition is introduced.
2. Native consolidated NOPAT versus parent equity with reported nonzero NCI
   is unavailable with an ownership-scope reason. No parent EBIT is inferred
   and no minority capital is silently guessed or added.
3. Fiscal period age independently controls score eligibility. Publication
   establishes knowledge availability and cannot renew fiscal age. Sparse
   carry-forward retains per-field knowledge timestamps in in-memory metadata;
   persisted columns and schema remain unchanged.
4. Explicit cash/STI currency mismatch blocks cash-only fallback. Actual missing
   STI still permits the existing labelled liquidity lower-bound/net-debt
   upper-bound display.
5. Selected income concepts are tracked per flow and cumulative operands.
   With positive NCI, unverified parent attribution fails closed regardless
   of configuration list length; common-available income is not parent income.
   The merged period view also suppresses unverified income when positive NCI
   is known, so sparse carry-forward and fallback sources cannot restore it.
   The earlier replay cutoff retains the originally available NCI-free values.
6. This audit records all P1/register outcomes, baseline dispositions, extra
   files, golden fields, validation and remaining evidence limits.

No new dependencies, thresholds, weights, ports, network calls, provider writes,
or execution authority. `ETF_COCKPIT_OPEN_BROWSER=0`; `execution_allowed=false`.

## EXTRA_FILES and GOLDEN accounting

EXTRA_FILES (whole train): `src/etf_cockpit/data/stock_fundamentals.py` is directly
required by B05-C2-N001 and sparse knowledge-time preservation.
`tests/test_stock_sources.py`, `tests/test_stock_store.py`,
`tests/test_stock_research.py`, and `tests/test_capital_efficiency.py` are read/test
coverage, not new edits. `tests/test_stock_metrics.py`,
`tests/test_stock_evidence.py`, and `tests/test_decision_stock.py` contain the
earlier train's directly necessary expectation changes. This audit file is
required by correction finding 6. `capital_efficiency.py` is named by the issue;
its shared denominator change is required to complete lease-bearing parity.

GOLDEN (retained earlier work): `tests/fixtures/refactor_parity/stock_research.json`
changed only five `roic.formula` fields in commit `4c5a11a7`: scenarios
`unclassified_defaults`, `industrial_full`, `bank_residual_income`,
`point_in_time_cutoff`, and `facade_context.report`, from
`(operating_income * (1 - tax_rate)) / (equity + debt - cash)` to
`NOPAT / invested_capital`. No numeric golden values changed in that commit.

GOLDEN (this correction): the same fixture was regenerated using
`ETF_REFRESH_REFACTOR_GOLDENS=1` and the repository's
`test_stock_research_golden.py` / `_harness.assert_matches_golden` tooling.
Exactly **11 string fields** changed from `equity + debt - cash` to
`equity + debt + separately reported leases - cash`:

- For each of `scenarios.unclassified_defaults`, `scenarios.industrial_full`,
  `scenarios.bank_residual_income`, `scenarios.point_in_time_cutoff`, and
  `scenarios.facade_context.report`: `capital_efficiency.reported.metrics.invested_capital.formula`
  and `capital_efficiency.reported.invested_capital_breakdown.metrics.reported_invested_capital.formula`.
- Additionally, `scenarios.industrial_full.capital_efficiency.adjusted.metrics.invested_capital.formula`.

Reason: make the shared lease-aware denominator explicit, directly required by
P1-03 and correction finding 1. A recursive JSON comparison verified no other
fields changed, including all numeric values, scores, statuses and weights.
Refresh mode deliberately reported one failure/one pass; this is the harness's
mandatory signal to rerun with refresh disabled, not a passing validation run.

## Final evidence

Local tests use `-q --tb=line -p no:cacheprovider`, with browser opening disabled
and no network access or package installs:

- **95 passed**: `test_fund_p0_semantics.py` (21), `test_stock_sources.py` (8),
  `test_stock_metrics.py` (7), `test_stock_evidence.py` (15),
  `test_stock_research.py` (39), `test_capital_efficiency.py` (5).
- **29 passed**: `test_stock_store.py` (14), `test_decision_stock.py` (11),
  `test_stock_scoring_wiring.py` (4).
- Architecture plus complete `tests/refactor_parity`: **24 passed, 1 failed**
  initially; the only failure listed the 11 formula strings accounted above.
  All three architecture checks and the other parity files passed unchanged.
- Both independent named reviews reproduced one interaction: a later NCI
  filing's rejected income was resurrected by sparse carry-forward. All five
  configured-concept regression cases failed before its repair. The bounded
  correction preserves the attribution rejection in the merged period view.
- After that interaction repair, **58 affected tests passed**:
  semantics (21), store (14), evidence (15), sources (8). Other passing suites
  are reused because this change does not alter their source dependencies.
- Refresh-disabled `test_stock_research_golden.py`: **2 passed**. Together with
  the unchanged architecture/other parity successes, **all 25 architecture and
  parity cases have passing evidence**. Across the local suites, **149 distinct
  tests** have passing evidence; the 58-case repair rerun is overlapping and
  is not added to that distinct count.
- Independent `reviewer` `/root/fd1_review`: **APPROVE**, all six supplied
  findings addressed. Independent `risk_reviewer` `/root/fd1_risk`: **PASS**,
  reproduced ownership blocker closed, no remaining bounded blockers.
  Runtime role/model/effort were attested using
  `scripts/v2_runtime_attestation.py`: reviewer `gpt-6-astra`/`low`,
  risk reviewer `gpt-6-astra`/`medium`. Both inspected the frozen replacement.
- `git diff --check` passed. Final production/test diff SHA-256 (Git diff for
  `src`, `tests/test_fund_p0_semantics.py`, `tests/test_stock_evidence.py`):
  `0df88f621f0e74edbd61c451b8e705d960eaa3cf851f7182d72aba8e4f1a4671`.
  Golden diff SHA-256:
  `6d9dece7bb78d6d4cdee9409e06c4ef160dd7e537e158dc2e8fcdcb1fe0b2625`.
  HEAD remains `4c5a11a73271054dbc283918e221be6781f748e1`; corrections are
  uncommitted as instructed.

OPEN: no local correction blockers. No packaged Linux/Windows, hosted CI,
merge, release or canonical/GitHub completion is claimed. Stop after this
local correction handoff, as requested.
