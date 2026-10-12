- C1 PARTIAL -> DONE: closed missing-evidence/fallback/timing gaps in the existing implementation; six focused functions in `tests/test_gap_241.py` (15 cases).
- C2 PARTIAL -> DONE: `cyclical_sector_adapters._cycle_adjusted_valuation` uses linked normalised earnings, records basis, rejects unverified reported fallback; peak-year and evidence-cutoff tests.
- C3 PARTIAL -> DONE: public candidate and configured simple-score consumers use the adapter; `decision.stock._cyclical_scored_metrics` consumes its evidence; end-to-end fixtures cover energy, materials and industrials.
- C4 PARTIAL -> DONE: zero/one cycle and absent adapter evidence produce unavailable scores with reasons; `test_insufficient_cycle_history_makes_sector_scores_unavailable_with_reason`.
- Original #241 spot/normalised separation DONE: `test_golden_cyclical_families_preserve_metrics_cycles_and_scenarios`.
- Original #241 source-linked operational metrics DONE: `test_operational_claims_require_linked_point_in_time_authority`.
- Original #241 scenario portfolio impact DONE: `test_golden_cyclical_families_preserve_metrics_cycles_and_scenarios`.
- Original #241 adequate history/confidence DONE: `test_formula_units_directions_and_cycle_history_confidence`.
DONE (units): reused adapter, both consumers and existing config entries; added missing-adapter rejection, reported-basis validation and exact timestamp checks; preserved generic non-cyclical behavior.
SAFE_POINT: Machinery verified on synthetic fixtures only; real-data acceptance requires stored issuer evidence/ingestion outside this packet. Execution remains false; issue/owner settings unchanged.
TESTS: required gap/adapter/architecture suite 53 passed (15/35/3); stock wiring/decision/simple-score regression suites 68 passed (4/11/53); 121 total, `-q --tb=line -p no:cacheprovider`.
DEFAULTS: two distinct non-overlapping cycles known by the normalised evidence cutoff; EV / (revenue * normalised margin), matching valuation currency/period/standard/jurisdiction; explicitly linked reported fallback only when margin supplied.
DEFAULTS: existing yield [0,0.10] and margin [0,0.25] ranges retained; timestamp cutoffs match exactly, date-only consumers retain daily semantics; weights, gates and peer-rank authority unchanged.
OPEN: real-data ingestion/acceptance and hosted gates remain outside the offline synthetic safe point; no network, deployment, persistence migration or GitHub changes.
