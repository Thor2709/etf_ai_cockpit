# work-P handoff: refactor-parity golden regeneration (2026-10-11)
Method: HEAD code + a5fdf3b1 universe.yaml passes all 22 parity tests, so f78dcb6f, 80e70112, 54c25f4e (incl. shadow models) change no golden. All diffs come from universe.yaml; split by applying RABO-only / SBNOR-only variants.
- snapshot (universe/enabled ids 58->57, signals.items, features frames): INTENDED, 01ae95bc (RABO removed; later ids shift one row, retained cross-sectional components drift <=0.005 total_score, no action/blocked_by/reason_short change). SBNOR alone: no snapshot change.
- backtest (equity curves, metrics, ai_added_value, operational_evidence_rows 6121->5996): INTENDED, 01ae95bc (RABO portfolio member gone). SBNOR alone: no backtest change.
- scoreboard rows 58->57, rank shifts, relative_strength/crowding peer correlation, 5 combined scores: INTENDED, 01ae95bc (universe-dependent cross-section; no decision label change for retained rows).
- scoreboard SBNOR row (tier sparebanken, asset_type Equity certificate, decision "Sparebank scorecard pending", canonical score unavailable, ranks): INTENDED, 93be47c5 (regrouping to Sparebank tier; scorecard pending without filing evidence).
- persisted_schema: row counts, forecast frame 870->855 rows/58->57 instruments (RABO, 01ae95bc); run-manifest file names/run_ids change because the config fingerprint changed (both commits). No file family added/removed/changed columns; no commit intentionally changed a persisted family.
FIXES: none needed (no regression found).
REGENERATED: backtest, snapshot, scoreboard, persisted_schema via ETF_REFRESH_REFACTOR_GOLDENS=1 (byte-identical to the isolated HEAD run). tests/refactor_parity/test_persisted_schema_golden.py: updated hardcoded manifest name backtest__s5944577a97bd -> backtest__s153d62356354 (config fingerprint).
TESTS: tests/refactor_parity + tests/test_simple_scores.py 75 passed; -k "universe or sparebank" 306 passed, 1 skipped.
NEEDS_OPUS_DECISION: none.
