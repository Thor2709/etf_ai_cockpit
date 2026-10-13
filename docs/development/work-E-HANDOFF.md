CLASSIFICATION INTENDED — 80e96966: snapshot.signals.items[*].reason_short (58 fields) now describes the action because unavailable values are safely labelled.
CLASSIFICATION INTENDED — 80e96966: snapshot.signals.items[*].supporting_metrics.reason_full (58 fields) labels missing Toto/TimesFM/drift unavailable and uses published total/confidence; no numerical evidence changed.
CLASSIFICATION REGRESSION — 80e96966: formatting removed NaN-text detection and 58 nonfinite_score_narrative_suppressed warnings; this reporting fix did not authorize decision changes.
CLASSIFICATION REGRESSION — 80e96966: all 572 scoreboard differences derive from the lost warning: score_objects final_action (39), one_line_reason, warnings, authority_decision.research_state; columns_by_name evidence_quality_10, final_label, research_state, legacy_action, decision, blocked_by, reason_short, evidence_warning_count.
FIXES — d1c29413: preserve exact raw NaN narrative provenance through an explicit snapshot-only option; default callers keep their existing warnings. None/pd.NA/infinity/invalid strings acquire no warning. No zero-fill; execution_allowed=false.
FIXES — Snapshot warnings and all scoreboard differences restored to release/rc-2026-10-10 values; decisions and numerical evidence unchanged.
REGENERATED — Harness ETF_REFRESH_REFACTOR_GOLDENS=1 with test_snapshot_golden.py and test_scoreboard_golden.py; intentional refresh failures occurred as documented. Only snapshot.json has a Git diff (116 explanation fields).
REGENERATED — scoreboard.json, backtest.json and persisted_schema.json unchanged from release base; no fields attributable to the other recent fixes remain changed.
TESTS — python -m pytest tests/refactor_parity tests/test_work_*.py -q --tb=line -p no:cacheprovider (PowerShell glob expanded): 51 passed, exit 0; includes all four previously failing cases and all remaining parity tests.
TESTS — NaN provenance boundaries/default opt-out passed; exhaustive golden-field comparison and git diff --check passed.
REVIEWS — Runtime-attested reviewer and risk_reviewer approved the final two-file source diff; initial breadth and caller-scope findings resolved.
NEEDS_OPUS_DECISION — None: no intended trading-decision changes; no push, PR, release, deployment or execution changes.
