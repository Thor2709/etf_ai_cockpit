# UPDATEV2-0013 ESEF/iXBRL implementation report

## Scope and acceptance criteria

- Implement bounded `FilingsXbrlOrgProvider` discovery and package acquisition with fixture/API selection, safe identifiers/URLs, unavailable states, checksum-backed immutable raw retention and the existing `RawDocument` contract.
- Parse local ESEF report packages offline with strict ZIP member/size checks, lazy optional XML/Arelle dependencies, entity LEI, package reporting period, contexts/dimensions, units, decimals, duplicate suppression, extension retention/warnings and explicit IFRS mappings only.
- Wire ESEF local import, discovery and download into the existing Filings & Statements page/state, persist facts through the versioned atomic statement-facts/inventory stores, expose authority/warning text and retain `execution_allowed=false` behaviour.

## RED evidence

- `python -m pytest -q tests/test_esef_provider.py tests/test_esef_ixbrl_parser.py --disable-warnings --maxfail=1`
- Initial failure was parser collection: `ModuleNotFoundError: No module named 'defusedxml'` from an eager optional import. The new contract tests also covered the missing provider/state behaviour before implementation.

## Changes

- `src/etf_cockpit/data/esef_provider.py`
  - Added bounded response normalisation, country/limit validation, flattened DataFrame rows and indexing by both `fxo_id` and API `id`.
  - Added explicit fixture-manifest selection, HTTPS `filings.xbrl.org` package URL validation, safe filing IDs, unavailable/error status distinction, response size limits and immutable SHA-256 raw paths written atomically.
- `src/etf_cockpit/parsers/esef_ixbrl.py`
  - Added optional `defusedxml` fallback, disallowed DTD/entity declarations, ZIP traversal/absolute/backslash/size rejection, report-package/XHTML checks and missing taxonomy warnings.
  - Extracts contexts, LEI/entity, start/end/instant periods, dimensions, units, decimals and namespace; suppresses duplicate facts; retains extension concepts with warnings; maps only explicit IFRS concepts; records an Arelle-unavailable warning without granting authority.
- `src/etf_cockpit/parsers/sec_facts.py`
  - Added ESEF-to-`StatementFact` adaptation and provider-aware inventory metadata/authority-selection labels while preserving SEC behaviour and `statement_facts.v1`/`filings_statements.v1` schemas.
- `src/etf_cockpit/app/state.py`
  - Added local ESEF import, official discovery and package download methods with atomic persistence, checksum/provenance and explicit unavailable/manual-review messages.
- `src/etf_cockpit/app/pages/trust_evidence.py`
  - Added country/filing-ID fields and discover/download/import controls on Filings & Statements; parser warning codes and official authority are surfaced in status text.
- `configs/ui_acceptance.yaml`
  - Registered `filings.discover-esef` and `filings.download-esef` controls.
- `tests/test_esef_provider.py`, `tests/test_esef_ixbrl_parser.py`
  - Added RED–GREEN coverage for flattened discovery, fixture selection, immutable download, bounded unavailable state, strict package paths, context/unit/decimal extraction, duplicate and extension handling, state persistence and discovery/download UI state methods.

## Validation evidence

- `python -m pytest -q tests/test_esef_provider.py tests/test_esef_ixbrl_parser.py tests/test_sec_facts_parser.py tests/test_button_contracts.py --disable-warnings --maxfail=1` → `36 passed`.
- `python -m ruff check src/etf_cockpit/data/esef_provider.py src/etf_cockpit/parsers/esef_ixbrl.py src/etf_cockpit/parsers/sec_facts.py src/etf_cockpit/app/state.py src/etf_cockpit/app/pages/trust_evidence.py tests/test_esef_provider.py tests/test_esef_ixbrl_parser.py` → all checks passed.
- `python -m compileall -q src` → passed.
- `git diff --check` → passed (only normal CRLF conversion warnings were reported by Git).
- Additional regression command `python -m pytest -q tests/test_trust_critical_artifacts.py tests/test_flet_startup.py tests/test_e2e_workflow.py --disable-warnings --maxfail=1` was attempted; it stopped in the pre-existing static trust-artifact fixture assertion (`identity.shape[0] == 16`, expected at least 45) before reaching the UI tests. This is unrelated to the ESEF diff and was not changed.

## Closure checklist

- [x] Offline local package parsing and canonical/extension mapping tests.
- [x] Raw checksum and immutable provider retention tests.
- [x] Context/unit/decimal/duplicate/traversal/malformed coverage.
- [x] Atomic statement-facts and filing-inventory persistence with official authority.
- [x] Filings page local import plus API discovery/download controls and acceptance inventory.
- [x] Focused tests, Ruff, compileall and diff checks.
- [ ] Full release/package rebuild gate.
- [ ] Audit/export packet evidence gate.
- [ ] Rebuilt application browser/computer-use smoke gate.
- [ ] Clean-first-run and final closure-matrix evaluation.

The full package/browser/export checks and the unrelated trust-artifact regression remain intentionally unclaimed/skipped for this scoped task.

The issue remains open pending the unchecked release, export and browser gates; this report does not claim closure.

## Fix and independent re-review evidence - 2026-07-13

- Additional RED observations came from the first independent review: comparative contexts were collapsed to the package period; the Arelle adapter was missing; Arelle validation errors were not serialised; arbitrary local packages were attributed to official filing authority; malformed local packages were not retained; and standard-but-unmapped IFRS concepts were classified as custom.
- Fix pass: context period precedence now uses each context end/instant; `_arelle_worker` invokes the pinned Arelle 2.41.x `ModelManager.validate()` API without a positional model, captures logger records as serialisable code/severity/message dictionaries, and runs in a bounded child process; local raw packages are checksum-addressed and retained before parsing; verified fixture/provider provenance remains `filings_xbrl_org`, while arbitrary local imports use `esef_local_import` and `manual_review`; standard IFRS namespaces remain non-custom when unmapped; unsupported archive members are rejected; validation severity and mapping counts are surfaced in import status and Filings inventory columns.
- GREEN focused parser/provider/statement persistence command: `python -m pytest -q tests/test_esef_provider.py tests/test_esef_ixbrl_parser.py tests/test_sec_facts_parser.py --disable-warnings` passed (4 provider + 17 parser + 21 statement tests; exit 0). The broader Task 13 bundle including button, accessibility and official-fixture tests also passed; the fresh reviewer recorded 45 passed for the scoped bundle.
- GREEN worker regression: `python -m pytest -q tests/test_esef_ixbrl_parser.py --disable-warnings --maxfail=1` passed (17 tests; exit 0), including pinned-API worker log-error serialisation.
- Scoped quality checks: Ruff over all Task 13 source/tests passed; `python -m compileall -q src tests` passed; `git diff --check` passed with only expected CRLF conversion warnings.
- Full-suite attempt: the existing package-inventory gate still reports the unrelated baseline `PROHIBITED_UI_ORDER_CONTROL` findings in `src/etf_cockpit/app/pages/universe_manager.py` lines 169 and 220; this Task 13 diff does not touch that file. The baseline is recorded separately and no unrelated repair was made.
- Fresh independent reviewer `task13_esef_reviewer_arelle_fix`: SPECIFICATION PASS, CODE PASS, READY; no Critical, Important or Minor findings. Deferred package rebuild, audit/export, clean-first-run, installed-live-Arelle and browser/computer-use evidence remain closure-pending and are not claimed here.
