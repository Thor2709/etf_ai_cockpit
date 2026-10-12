- C1 PARTIAL -> DONE: verified existing machinery and closed normalized-margin authority bypass; `tests/test_gap_241.py` retains 10 test functions/29 cases, including all four required tests.
- C2 DONE: `cyclical_sector_adapters._cycle_adjusted_valuation` uses linked normalised earnings, records basis, rejects unverified reported fallback; peak-year and evidence-cutoff tests.
- C3 DONE: public candidate/configured simple scores and `decision.stock._cyclical_scored_metrics` consume adapter evidence; end-to-end fixtures cover energy, materials and industrials (50x valuation, value 2/10, quality 4/10).
- C4 DONE: zero/one cycle and absent adapter evidence produce unavailable scores with reasons; `test_insufficient_cycle_history_makes_sector_scores_unavailable_with_reason`.
- Original #241 spot/normalised separation DONE: `test_golden_cyclical_families_preserve_metrics_cycles_and_scenarios`.
- Original #241 source-linked operational metrics DONE: `test_operational_claims_require_linked_point_in_time_authority`.
- Original #241 scenario portfolio impact DONE: `test_golden_cyclical_families_preserve_metrics_cycles_and_scenarios`.
- Original #241 adequate history/confidence DONE: `test_formula_units_directions_and_cycle_history_confidence`.
DONE (units): reused adapter, both consumers/config entries; normalized margin requires official/issuer evidence, otherwise unavailable with reason and original provenance; MODEL/VENDOR/MANUAL/COMMUNITY regression cases added; base 96332e477a9ee0f7546b58dda9aeced9af371065.
SAFE_POINT: Machinery verified on synthetic fixtures only; real-data acceptance requires stored issuer evidence/ingestion outside this packet. Execution remains false; issue/owner settings unchanged.
TESTS: `test_gap_241.py` 29, `test_cyclical_sector_adapters.py` 35, `test_architecture_boundaries.py` 3: 67 passed on 2026-10-12; required command used `-q --tb=line -p no:cacheprovider` (64 existing NumPy empty-slice warnings).
DEFAULTS: two distinct non-overlapping cycles known by the normalised evidence cutoff; EV / (revenue * normalised margin), matching valuation currency/period/standard/jurisdiction; explicitly linked reported fallback only when margin supplied.
DEFAULTS: existing yield [0,0.10] and margin [0,0.25] ranges retained; exact timezone-aware cutoffs, date-only callers mean midnight UTC; weights, gates and peer-rank authority unchanged.
OPEN: real-data ingestion/acceptance and hosted gates remain outside the offline synthetic safe point; no network, deployment, persistence migration or GitHub changes.
