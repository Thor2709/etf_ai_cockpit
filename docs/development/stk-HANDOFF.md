# STKFIX handoff

STATUS: PARTIAL
TASK_ID: STKFIX

## Findings and regression tests

1. S2: EDGAR cash plus investments now takes the latest constituent filing; stored FX is filtered by decision time. Tests: `test_edgar_cash_and_investments_are_known_at_the_later_filing`, `test_fx_rate_rejects_an_observation_not_yet_known_at_the_decision_time`.
2. S2: evidence cache keys include the complete decision timestamp. Test: `test_universe_evidence_cache_uses_the_complete_decision_timestamp`.
3. S2: refresh eligibility is separate from analysis membership; historical replay includes disabled stocks through their supplied lifecycle date. Test: `test_disabled_delisted_stock_keeps_historical_fundamentals_and_peer_contribution`.
4. S5: EDGAR fields retain their own units; ROIC, growth, balance-sheet ratios and EV reject incompatible currencies. Tests: `test_edgar_keeps_each_field_currency_instead_of_labeling_every_value_with_one_unit`, `test_merge_preserves_source_field_currency_metadata`, `test_mixed_currency_roic_growth_and_ev_are_unavailable_and_minority_is_required`.
5. S5: debt totals add disjoint short-term amounts; lease-inclusive debt removes reported finance leases before downstream lease addition. Test: `test_edgar_debt_adds_disjoint_borrowings_and_normalizes_lease_inclusive_total`.
6. S3/S7: EV requires reported minority interest; incomplete dividend years stay unavailable; fiscal and identity gaps carry reasons. Tests: `test_mixed_currency_roic_growth_and_ev_are_unavailable_and_minority_is_required`, `test_dividend_yield_is_unavailable_when_the_trailing_year_is_incomplete`, `test_missing_fiscal_cells_and_identity_fields_show_reasons`.
7. S7: ticker resolution requires an exact symbol; ISIN verification requires matching listing evidence and share class; enriched quote types are revalidated. Tests: `test_unmatched_ticker_stays_unresolved_with_candidates`, `test_share_class_name_mismatch_does_not_verify_an_isin`, `test_unsupported_enriched_quote_type_is_rejected`.
8. S1: analyst evidence is appended/read from `stock_fundamentals.parquet`; legacy snapshot analyst rows migrate on refresh; fiscal FCF calls the canonical calculation. Tests: `test_analyst_component_reads_the_canonical_fundamentals_store`, `test_refresh_moves_legacy_snapshot_analyst_rows_into_the_canonical_store`, `test_fiscal_table_uses_the_canonical_fcf_calculation`.

## Validation

- Listed pytest command: 129 passed, 0 failed.
- Ruff on changed Python files: passed.
- `git diff --check 0ee9a96e`: passed; no whitespace errors.
- Removed the unused parser `instants` name and unused `pytest` import; normalized changed `instrument_detail.py` lines to LF.

## Open gap and decision

- Current universe records have `enabled` and `lifecycle` flags but no effective lifecycle dates. The analysis path accepts a supplied `lifecycle_date` and uses it for replay membership, but no actual delisting/merger dates were supplied. Dates were not inferred from comments.
- NEEDS_OPUS_DECISION: provide authoritative lifecycle dates and authorize adding them to `configs/universe.yaml` (outside this packet's write set). Until then, flagged historical stocks remain in current analysis because their post-event membership cannot be determined safely.
