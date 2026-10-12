# Gap 247 handoff

DONE: Correction pass: domicile, distribution policy, frequency and amount evidence are now bound to the decision time (future, malformed, timezone-incompatible, missing-decision-time -> unavailable with reason). Joined resolved document domicile, dated distribution policy and exact-match share-class distribution metrics in ETF Economics; exposed tax, currency and hedge assumptions with source metadata and unavailable reasons.
SAFE_POINT: Synthetic machinery is implemented. Real-data acceptance and issue completion remain open until the owner specifies tax/hedge assumptions, scope and accepted source artefacts.
TESTS: `python -m pytest tests/test_gap_247.py -q --tb=line -p no:cacheprovider` — 4 passed after correcting one presentation assertion. The combined required run had 41 passing checks and that initial assertion failure; the tax-context, instrument-detail and architecture checks passed.
DEFAULTS: Tax and hedging remain disabled. The existing 0.15 withholding input remains inert legacy configuration, not approved guidance. Residence tax, distribution amount without distribution currency, economic currency exposure without weights, and hedge economics remain unavailable without evidence.
OPEN: Owner-provided residence/source-withholding assumptions, hedge assumptions and methodology, and accepted source artefacts are required for real-data acceptance.

CORRECTION_DEFAULTS: Evidence without a decision time is unavailable. A bare-date known_at counts as known only from the next UTC day; as_of after the decision time is rejected. Tests: 8 in tests/test_gap_247.py.
