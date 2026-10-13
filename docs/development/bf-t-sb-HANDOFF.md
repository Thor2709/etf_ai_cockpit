# bf/t-sb handoff — bug-hunt batch

All 13 IDs fixed, each with test_<id> in tests/test_bugfix_t-sb.py.

- CHAT-P03-N003: merger_bridge → unavailable `INVALID_MERGER_INPUT` for non-numeric costs or tax_rate outside [0,1) (new `all_finite_or_none` = H:allnum in core/values.py).
- CHAT-P03-N005: implementation_shortfall denominator = reference*(filled+unfilled); total<=0 unavailable.
- CHAT-P03-N008: dividend_history keep_events=0 → [].
- P03-N006: justified_price_to_book None for g<0.
- P03-N007: normalisation_bridge unavailable + `reason_code=INVALID_NORMALISATION_ADJUSTMENT` when any adjustment is invalid (new field on NormalisationBridge).
- K01: stock_universe price_currency = quote_major.
- K02a: removed the always-missing securities/rate-cycle components (still in not_adjusted).
- K02b: valuation() unavailable `VALUATION_ASSUMPTIONS_INVALID` when assumption_errors.
- K02c: filing identity = join of all present fields.
- K02d: statement_series returns `status="unavailable"` with reasons kept (with_derived_owner_earnings treats empty current as no-op).
- K02e: owner_normalisation early return replaced by structured unavailable dict (missing_components, reason_code).
- K02f: quarterly_score_history sorts by _quarter after tail(1).
- K03: ec_capital + overkursfond rules in configs/esef_extension_concepts.yaml.

## Tests
`python -m pytest -q --tb=line -p no:cacheprovider tests/test_bugfix_t-sb.py tests/test_sparebank*.py tests/test_import_layering.py tests/test_stock_*.py tests/test_performance_policy.py`
- test_bugfix_t-sb.py: 13 passed.
- Only failures are base failures listed in gate-fails-1b733dc4.txt: test_teaching_bank_production_route_exposes_scorecard_and_workspace, test_latest_sparebank_scores_takes_latest_native_run, test_source_has_no_hardcoded_sparebank_issuer_table, test_no_new_layering_violations.

## Existing assertions updated (pinned buggy behaviour)
- tests/test_sparebank_sb2.py: benign-loss normalisation now resolved (K02a); unavailable case asserts structured dict (K02e).
- tests/test_sparebank_sb2_data.py: SharePremiumMember now yields `overkursfond` (K03).

## Files changed
configs/esef_extension_concepts.yaml; analysis/sparebank/{bank_economics,book_calcs,dividends,events,valuation}.py; analysis/stock_universe.py; application/{sparebank_evidence,sparebank_peers}.py; core/values.py; the two tests above.

NEEDS_OPUS_DECISION: none.
