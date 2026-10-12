# Issue 241 handoff

DONE (acceptance matrix; initial → final):
- C1 all initial gaps implemented: PARTIAL → DONE; the following criteria pass synthetic validation.
- C2 through-cycle valuation and recorded basis: PARTIAL → DONE; `cyclical_sector_adapters.py:303-318,672-751`.
- C3 energy/materials/industrials score consumption: MISSING → DONE; `simple_scores.py:2699-2789`, `decision/stock.py:333-360,733-775`, synthetic end-to-end test `test_gap_241.py:122-184`.
- C4 insufficient history unavailable with reason: PARTIAL → DONE; `cyclical_sector_adapters.py:319-335,694-697`, `test_gap_241.py:186-199`.

SAFE_POINT: Adapter and score plumbing verified on synthetic point-in-time fixtures. Real-data acceptance is open because no cyclical evidence persistence/provider path exists. Execution remains disabled; issue state unchanged.

DEFAULTS: Require two distinct cycles; compute EV / (revenue × normalized margin) with matching currency, period, standard, and jurisdiction; fail closed on incomplete evidence. Reuse existing yield and margin ranges; weights and gates unchanged.

TESTS: `python -m pytest tests/test_gap_241.py tests/test_cyclical_sector_adapters.py tests/test_architecture_boundaries.py -q --tb=line -p no:cacheprovider` — 42 passed, including 4 focused gap tests.

OPEN: Real-data ingestion and acceptance remain outside the synthetic safe point.
