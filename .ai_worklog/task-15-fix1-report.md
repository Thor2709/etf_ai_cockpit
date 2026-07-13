# Task 15 fix 1 - parsed disclosure hardening

## Task completed

Implemented the four independent review blockers for PRIIPs KID and index-methodology evidence. Parser contracts, aliases, UI execution boundaries and approved score weights remain unchanged; `execution_allowed` remains false.

## Files and symbols examined

- `parsers/priips_kid.py`: `parse_priips_kid`, `_extract_costs`.
- `parsers/index_methodology.py`: `IndexMethodologyRecord`, parser warnings, new holdings assessment helpers.
- `data/parsed_disclosures.py`: parsed row stores, `_read_frame`, combined publication helpers.
- `data/fund_documents.py` and `app/pages/trust_evidence.py`: FundDocument registry and KID/methodology import flow.
- `signals/simple_scores.py`: `SimpleScoreComponent`, component provenance/eligibility and liquidity/risk seams.
- Focused parser, persistence, score, registry, UI and audit tests.

## Findings or changes

- Replaced broad DOTALL KID cost extraction with bounded cost-section/table parsing. Recognised Vanguard entry, exit, ongoing, transaction and performance values are retained; question/header or malformed values produce `cost_table_malformed`, partial confidence, manual review and `score_eligible=False`.
- Added deterministic `assess_methodology_holdings` and `apply_methodology_holdings_assessment`. Explicit cap/geography disagreements emit `methodology_holdings_conflict`; no holdings emits explicit `methodology_holdings_unavailable`; both are manual-review and score-ineligible. Persisted methodology rows can receive the assessment and the trust import path compares stored holdings.
- Added `build_priips_kid_cost_evidence` (plus compatibility aliases) as an opt-in source-aware liquidity/risk component. It carries `priips_kid:<checksum>`, `issuer_document`, document date/freshness, conflict/manual-review state and fail-closed eligibility. Numeric values come only from parsed cost percentages or SRI; stale, malformed or incomplete records are excluded.
- Added atomic KID/methodology parsed-store plus FundDocument registry/CSV publication helpers. Trust UI imports now use the combined transaction; parsed `_read_frame` raises on corrupt parquet before any overwrite.
- Added golden, conflict, evidence, transaction rollback and corruption regressions.

## Evidence

- Initial RED tests failed on the known bad KID values/high confidence, missing conflict/evidence/atomic APIs and silent corrupt-store overwrite.
- Focused parser/persistence/registry/UI/audit suite: 45 passed.
- KID score hook regressions: 4 passed.
- Ruff, compileall and `git diff --check` passed (Git only reported normal LF/CRLF notices).

## Commands or tests run

- `python -m pytest -q tests/test_priips_kid_parser.py tests/test_index_methodology_parser.py tests/test_parsed_disclosures.py tests/test_fund_documents.py tests/test_instrument_detail.py tests/test_button_contracts.py tests/test_trust_critical_artifacts.py::test_trust_evidence_pages_are_registered tests/test_trust_critical_artifacts.py::test_audit_export_includes_trust_critical_evidence_and_session_log --disable-warnings --maxfail=1`
- `python -m pytest -q tests/test_simple_scores.py::test_complete_fresh_kid_is_observable_as_issuer_cost_evidence tests/test_simple_scores.py::test_incomplete_or_stale_kid_is_excluded_from_cost_evidence --disable-warnings`
- `python -m ruff check` on all edited source and tests.
- `python -m compileall -q src tests`.
- `git diff --check`.

## Remaining uncertainty and risk

- Full `tests/test_simple_scores.py` still has six pre-existing failures because ignored generated `data/raw/trade_candidates/yahoo_trade_candidates_*.csv` fixtures and secondary-universe rows are absent; these are unrelated to this fix.
- Full clean-first-run/package/browser gates remain release-level checks.

## Recommended next action

Review the scoped diff, cherry-pick/merge the commit, then run the repository release gate with the generated trade-candidate and secondary-universe fixtures present.
