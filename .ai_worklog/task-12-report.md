# Task 12 - SEC EDGAR provider and official statement facts

## Scope and acceptance evidence

Implemented the no-key SEC EDGAR acquisition and local statement-facts workflow for `UPDATEV2-0012`. Raw submissions/companyfacts responses are identity-checked against the requested CIK, cached under `data/raw/sec_edgar`, checksum-recorded with sidecar provenance, written atomically, rate-bounded and conditionally revalidated with ETag/Last-Modified when supplied by the transport. Network failure is controlled as unavailable and does not start scoring or broker workflows.

`parse_companyfacts` now retains taxonomy, concept, unit, value, periods, filed/form/accession/fiscal metadata and deterministic SEC source IDs. Explicit US-GAAP mappings are limited to the configured table; duplicate facts are deduplicated with warnings, ambiguous units fail closed, malformed/wrong-identity input produces no records, and custom taxonomies remain retained but unmapped. Clean facts and filing inventory are atomically persisted as parquet with source IDs and official authority.

The Filings & Statements view exposes CIK fetch and local fixture import controls, explicit unavailable/progress messages, statement-facts columns and mapping warnings. AppState routes both paths through the parser and persistence helpers without invoking refresh, model or execution workflows.

## RED-GREEN-REFACTOR

- RED: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py` - failed at collection because `write_statement_facts` was absent (expected).
- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py` - 16 passed.
- Refactor checks: scoped Ruff and compileall passed; generated `data/.schema_versions/*` churn from startup tests was restored and is not part of this checkpoint.

## Files changed

- `src/etf_cockpit/data/sec_edgar_provider.py`
- `src/etf_cockpit/parsers/sec_facts.py`
- `src/etf_cockpit/app/state.py`
- `src/etf_cockpit/app/pages/trust_evidence.py`
- `src/etf_cockpit/core/paths.py`
- `tests/test_sec_edgar_provider.py`
- `tests/test_sec_facts_parser.py`

## Validation and remaining gates

Scoped commands run:

```text
python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py  # 16 passed
python -m pytest -q tests/test_trust_critical_artifacts.py tests/test_e2e_workflow.py tests/test_flet_startup.py tests/test_data_health.py tests/test_paths.py  # 43 passed, 1 existing identity-row assertion failed (16 < 45)
python -m ruff check src/etf_cockpit/data/sec_edgar_provider.py src/etf_cockpit/parsers/sec_facts.py src/etf_cockpit/app/state.py src/etf_cockpit/app/pages/trust_evidence.py src/etf_cockpit/core/paths.py tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py  # passed
python -m compileall -q src/etf_cockpit/data/sec_edgar_provider.py src/etf_cockpit/parsers/sec_facts.py src/etf_cockpit/app/state.py src/etf_cockpit/app/pages/trust_evidence.py src/etf_cockpit/core/paths.py  # passed
```

Package rebuild, packaged/browser/computer-use evidence, audit ZIP readback and clean-first-run gates were not run in this implementation worktree and remain pending. No live network evidence is claimed; tests use injected transport and the retained Microsoft official fixture.

## Independent review fix pass - 2026-07-13

The first independent review rejected `ff8feba` with blocking findings: SEC inventory was overwritten by trust refresh, facts/inventory replaced prior issuers, statement facts were omitted from audit export, unresolved CIKs could inherit the selected instrument, SEC UI keys were duplicated, and a corrupt cached 304 payload was not validated. A fresh fix context was dispatched but did not produce source changes; the parent applied the targeted fix pass after preserving the RED tests.

- RED: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py --disable-warnings --maxfail=1` failed at `test_sec_provider_rejects_corrupt_cached_304_payload` because the cached 304 path did not reject a wrong-CIK payload.
- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 30 passed.
- Audit readback: `python -m pytest -q tests/test_trust_critical_artifacts.py -k audit_export_includes_trust_critical_evidence_and_session_log --disable-warnings --maxfail=1` - passed; the ZIP contains `evidence_export/statement_facts.csv` and its checksum is present in the trust manifest.
- Quality: scoped Ruff and `python -m compileall -q src tests` passed.

Fixes preserve prior fact/inventory rows with deterministic source/document deduplication, preserve SEC rows during normal trust refresh, include statement facts in audit export, use `sec_unresolved_<CIK>` for unresolved CIK attribution with manual-review warning, give fetch/local import distinct UI keys and validate cached 304 checksum plus CIK identity. The known unrelated identity-row baseline remains (`16 < 45`); release/package/browser/clean-first-run gates remain pending.

## Second independent re-review fix pass - 2026-07-13

The fresh re-review of `3f20e33` found that the exact SEC/vendor precedence contract, clean-store schema versioning, known-CIK resolution and split-write failure semantics still needed explicit evidence. These were addressed in the current fix pass.

- RED: `python -m pytest -q tests/test_sec_facts_parser.py --disable-warnings --maxfail=1` failed during collection because `select_authoritative_facts` was absent.
- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 34 passed after the additional migration, authority, identity and failure-path tests.
- Added `statement_facts.v1` and `filings_statements.v1` columns with legacy-row migration on write; registered `statement_facts` with startup migration managed stores.
- Added `select_authoritative_facts` exact-match selection (instrument, concept/canonical metric, unit and period), preserving non-matching vendor claims and unmatched SEC claims for audit/manual review.
- CIK imports now resolve a unique persisted identity mapping when present; otherwise they retain the `sec_unresolved_<CIK>` manual-review identity. Inventory failure messages no longer claim that no data changed.
- Scoped Ruff and compileall remain passing; release/package/browser/clean-first-run gates remain pending.

## Third independent re-review fix pass - 2026-07-13

The following fresh re-review identified one remaining blocking gap: deterministic precedence among multiple exact-key SEC filings and a production invocation of the authority contract. The fix pass now groups exact entity/concept/unit/period keys, selects the latest filed/amended/accession-stable SEC fact deterministically, retains all raw SEC rows in the clean store, and invokes the contract from the production writer. AppState supplies optional vendor claim rows from the local fundamentals store when present. A regression test covers amended duplicate filings and exact-period mismatch.

- RED: `python -m pytest -q tests/test_sec_facts_parser.py --disable-warnings --maxfail=1` initially failed collection before the authority helper existed; the subsequent deterministic-amendment test was added before implementation.
- GREEN: `python -m pytest -q tests/test_sec_facts_parser.py --disable-warnings --maxfail=1` - 13 passed.
- Quality: scoped Ruff and `python -m compileall -q src tests` passed.

The authority selection remains evidence-only and `executable_authority=false`; unmatched vendor claims and all raw SEC facts remain visible for audit/manual review. Package/browser/clean-first-run evidence remains pending.

## Fourth independent re-review fix pass - 2026-07-13

The final re-review required the authority decision to be observable in production rather than a discarded helper result. `write_statement_facts` now persists `authority_selection` (`canonical_sec` or `retained_sec`) while retaining every raw SEC fact. AppState filters vendor claims to rows that explicitly carry concept/canonical metric, unit and period, then supplies them to the writer; wide yfinance fundamentals without those fields cannot be falsely matched. A regression test proves that the latest amended SEC fact is the canonical selection for an exact matching vendor claim while the older filing remains retained.

- GREEN: `python -m pytest -q tests/test_sec_facts_parser.py --disable-warnings --maxfail=1` - 14 passed.
- Quality: scoped Ruff and `python -m compileall -q src tests` passed.

No execution authority is granted by this selection; all rows remain evidence-only and `executable_authority=false`.

## Fifth independent re-review fix pass - 2026-07-13

The production review found that authority labels were calculated only from the incoming batch, allowing an older canonical fact to survive a later amendment. The writer now merges incoming and existing SEC rows first, recomputes deterministic authority across the complete generation, and persists exactly one `canonical_sec` row per matching key while retaining older filings as `retained_sec` audit evidence.

- RED: the reviewer reproduced a sequential-import defect where both `sec:old` and `sec:new` were labelled `canonical_sec`.
- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 37 passed.
- Added a sequential-import regression and retained amended-filing evidence test. Scoped Ruff and compileall passed.

Package/browser/clean-first-run and live-network evidence remain pending; the unrelated identity-row baseline remains recorded separately.

## Sixth independent re-review fix pass - 2026-07-13

The sequential-authority review found the period key was not duration-aware: annual and quarterly facts ending on the same date could collapse. `_fact_key` now distinguishes instant facts from duration facts using start, end and fiscal period, and vendor adapters must provide compatible period semantics before an exact match is possible. An annual-versus-quarterly same-end regression covers the boundary.

- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 38 passed.
- Scoped Ruff and compileall passed.

All authority selection remains evidence-only, deterministic and non-executable. Package/browser/clean-first-run/live-network gates remain pending.

## Seventh independent re-review fix pass - 2026-07-13

The duration review identified SEC Company Facts end-only records that represent instants (for example, balance-sheet facts with `end` and no `start`). Parsing now normalises those records to `instant=<end>`, while duration facts retain start/end/fiscal-period semantics. Exact vendor instant matching and a regression for end-only SEC facts are covered.

- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 39 passed.
- Scoped Ruff and compileall passed.

Remaining package/browser/clean-first-run/live-network gates are still explicitly pending.

## Eighth independent re-review fix pass - 2026-07-13

The instant review identified that production vendor rows may encode an instant as `end` without `start`, matching SEC Company Facts. `_fact_key` now normalises end-only vendor claims to the same instant representation as SEC records; duration claims still require start/end/fiscal period. The regression now uses an end-only vendor row.

- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 39 passed.
- Scoped Ruff and compileall passed.

Package/browser/clean-first-run/live-network evidence remains pending.

## Ninth independent re-review fix pass - 2026-07-13

The raw-evidence review identified that the fixed latest-cache path was mutable while historical inventory rows retained its checksum. Validated SEC responses now also persist under checksum-addressed immutable raw paths; the mutable path remains only the conditional-request cache pointer. 304 responses resolve and validate the immutable generation, and a two-generation regression proves prior bytes remain readable after refresh.

- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 40 passed.
- Scoped Ruff and compileall passed.

Package/browser/clean-first-run/live-network gates remain pending; no credentials or live data were stored.

## Tenth independent re-review fix pass - 2026-07-13

The raw-generation review also found that the UI fetch path used a placeholder `.invalid` contact in its SEC User-Agent. Network fetch now requires a locally configured `ETF_COCKPIT_SEC_EDGAR_USER_AGENT` containing the organisation and contact email (or an explicit programmatic `user_agent`), returning a controlled unavailable state without changing data when absent. The placeholder is no longer used.

- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 41 passed.
- Scoped Ruff and compileall passed.

Live SEC network behaviour remains unverified until a real contact User-Agent is configured; package/browser/clean-first-run gates remain pending.

## Eleventh independent re-review fix pass - 2026-07-13

The User-Agent review found that the provider accepted malformed and placeholder contacts. Central validation now requires a descriptive organisation prefix, a syntactically valid contact email and a non-placeholder domain; `.invalid`, `.example`, `.test`, `.localhost`, malformed and organisation-less values are rejected. The UI remains controlled-unavailable until `ETF_COCKPIT_SEC_EDGAR_USER_AGENT` is configured.

- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 44 passed.
- Scoped Ruff and compileall passed.

Live-network, package/browser and clean-first-run evidence remain pending.

## Twelfth independent re-review fix pass - 2026-07-13

The final User-Agent review found that the first validation regex still admitted malformed mailbox/domain forms. Validation now rejects leading/trailing/consecutive local-part dots, empty or malformed domain labels, trailing dots, non-alphabetic/short TLDs and reserved placeholder domains, while requiring a descriptive organisation prefix. Regression coverage includes all reproduced malformed examples.

- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 49 passed.
- Scoped Ruff and compileall passed.

Live SEC, package/browser and clean-first-run gates remain pending.

## Thirteenth independent re-review fix pass - 2026-07-13

The strict-validation review required the clean facts and filing inventory to share one recoverable transaction boundary. Added `write_statement_evidence`, which builds both merged generations and publishes them through the existing `atomic_write_group`; AppState now uses it and reports `No data changed` on failure. Failure-injection coverage proves both existing stores remain byte-identical when group publication fails.

- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 50 passed.
- Scoped Ruff and compileall passed.

Package/browser/clean-first-run/live-network gates remain pending.

## Fourteenth independent re-review fix pass - 2026-07-13

The fresh independent review reproduced one blocking User-Agent defect: reserved
domains `example.com`, `example.net` and `example.org` were still accepted even
though placeholder domains must fail closed. The validator now rejects those
reserved domains in addition to `.invalid`, `.example`, `.test` and
`.localhost`. The Task 12 atomic evidence regression was also strengthened to
inject a failure after the facts destination had been replaced; the existing
facts and filing-inventory bytes are both restored by the durable transaction
rollback.

- RED: reviewer direct probe accepted `SecEdgarProvider("ETF AI Cockpit contact@example.com", ...)`; the lifecycle rollback test was previously pre-publication only.
- GREEN: `python -m pytest -q tests/test_sec_edgar_provider.py::test_sec_provider_rejects_placeholder_or_non_descriptive_user_agent tests/test_sec_facts_parser.py::test_statement_evidence_atomic_failure_rolls_back_after_first_destination_replaced --disable-warnings --maxfail=1` - 12 passed.
- Focused bundle: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 53 passed.
- Quality: scoped Ruff, `python -m compileall -q src tests` and `git diff --check` passed.

The unrelated identity-row baseline failure remains separately recorded. Package,
browser, clean-first-run and live-network evidence remain pending for the issue
closure gate.

## Fifteenth independent re-review fix pass - 2026-07-13

The fresh review found that an explicit `instrument_id` parameter could bypass
the persisted CIK resolver and publish SEC evidence under an unrelated
instrument. Imports and fetches now require a unique identity-store row whose
instrument ID matches the payload CIK; mismatches fail before any clean-store
write and retain the controlled unavailable message. The adversarial regression
uses a known MSFT CIK with `instrument_id="WRONG"` and proves both destinations
remain absent.

- RED: `python -m pytest -q tests/test_sec_facts_parser.py::test_sec_import_rejects_mismatched_supplied_instrument_id --disable-warnings --maxfail=1` - failed because the import completed under `WRONG`.
- GREEN: the same test plus the known-identity import regression - 2 passed.
- Focused bundle: `python -m pytest -q tests/test_sec_edgar_provider.py tests/test_sec_facts_parser.py tests/test_button_contracts.py tests/test_accessibility_contracts.py tests/test_trust_critical_artifacts.py -k 'not static_trust_artifacts_cover_providers_and_identity' --disable-warnings --maxfail=1` - 54 passed.
- Quality: scoped Ruff, `python -m compileall -q src tests` and `git diff --check` passed.

Package/browser/clean-first-run and live-network evidence remain pending; the
known identity-row fixture failure remains unrelated and separately recorded.

## Final independent re-review - 2026-07-13

Fresh re-review approved Task 12 implementation for integration. SPECIFICATION
PASS and CODE QUALITY PASS; no Critical, Important or Minor correctness findings.
The explicit instrument identity is now accepted only when exactly one persisted
identity row matches the payload CIK and supplied instrument ID. The reviewer
confirmed provider identity/cache checks, immutable raw generations,
deterministic authority, grouped atomic publication and rollback, audit/UI
exposure and `executable_authority=false`.

- Adversarial mismatch regression: 1 passed on each of two runs.
- Focused SEC/trust/UI/accessibility bundle: 54 passed.
- Scoped Ruff, compileall and `git diff --check`: passed.
- Closure evidence still pending: package build/browser interaction,
  clean-first-run and configured live SEC network. These remain issue closure
  gates, not implementation defects.
