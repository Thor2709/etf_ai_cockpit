# Wave 0 Task 4 - independent review 1

Date: 2026-07-12 (Australia/Sydney)
Worktree: `C:\Users\thor2\Desktop\Trading App\.worktrees\wave0-task4-execution-boundary`
Reviewed range: `c5fd053425376508e141f3cef3cc09f72d2fe791b5..a4f2956`
Reviewer role: fresh bounded independent review; no source or test authorship

## Evidence reviewed

- The Task 4 brief, `.ai_worklog/task-4-report.md`, the Task 4 section of
  `docs/superpowers/plans/2026-07-11-etf-ai-cockpit-foundation-operations-boundary-plan.md`,
  and the current diff from `c5fd053` to `a4f2956`.
- `src/etf_cockpit/governance/static_checks.py`, the rejection registry, all
  three future-only documents, the three scope-boundary test modules, and the
  package metadata.
- The recorded GREEN evidence (40 tests) was treated as supplied evidence. No
  long test suite was rerun, as requested.

## Targeted independent verification

The current checker returned the recorded passing result (`pass`, 232 scanned
files, no violations) and `git diff --check c5fd053..a4f2956` was clean. I ran
short temporary-tree probes only; these do not modify source or tests.

- A violation under `src/etf_cockpit/data/bad.py` or
  `src/etf_cockpit/models/bad.py` returned `pass`.
- `broker.pem`/`secrets.key` containing `BROKER_API_KEY=x` returned `pass`.
- `.env` containing `EXECUTION_ALLOWED=true` and an INI `[DEFAULT]` section
  containing `execution_allowed=true` returned `pass`.
- `url: https://broker.example/orders`, `importlib.import_module("broker_sdk")`,
  and UI labels `"Buy"`/`"Submit"` returned `pass`.
- A registry mapping with top-level `executable_authority: true` returned no
  validation errors.
- Ordinary allow-list boundary cases behaved as intended: `tests_evil/` and
  `docs/architecture/future_evil/` were scanned, while the exact `tests/` and
  `docs/architecture/future/` paths were skipped.

## Specification-compliance verdict: CHANGES_REQUIRED

The commit provides the requested report model, basic AST/config/dependency
checks, registry records, future-only documents and package discoverability,
and it preserves the false authority values in the committed artefacts. The
recorded focused suite and basic allow-list boundary tests are useful evidence.
However, the scanner and registry validator have bypasses in production source,
credential resources and authority configuration. These leave the required
no-execution boundary incomplete even though the current tree passes.

## Code-quality verdict: CHANGES_REQUIRED

The implementation is readable and deterministic for the fields tested, and
the diff is scoped. The exclusion and parsing decisions are too broad in some
places and too narrow in others: entire production package subtrees are
omitted, while several explicitly prohibited resource/config forms are not
visited. Registry validation is also ad hoc and does not enforce all of the
authority/schema fields present in the file. The important findings below need
targeted fixes and adversarial regressions before approval.

## Findings by severity

### Critical

None identified in this bounded review.

### Important

1. **Production package subtrees are silently outside the scan.**

   `_EXCLUDED_DIRECTORIES` includes `data` and `models` at
   `src/etf_cockpit/governance/static_checks.py:31-48`, and
   `_iter_scannable_files()` rejects any path containing one of those names at
   lines 220-230. Consequently all 40 files in `src/etf_cockpit/data/` and all
   11 files in `src/etf_cockpit/models/` are omitted from the current 232-file
   report. A temporary `src/etf_cockpit/data/bad.py` containing
   `def place_order(): pass` returned `pass` instead of
   `PROHIBITED_ORDER_SYMBOL`. Runtime directories should be excluded only by
   their intended top-level/runtime roots; package source directories must
   remain in the production scan.

2. **Credential-resource scanning does not visit the private-key suffixes it
   claims to handle.**

   `_scan_credential_resource()` checks `.pem`, `.key`, `.p12` and `.pfx` at
   lines 544-550, but `_TEXT_SUFFIXES` at lines 50-61 does not include any of
   those suffixes, so `_iter_scannable_files()` never yields them. A temporary
   `broker.pem` containing `BROKER_API_KEY=x` therefore returned `pass`.
   Include the credential/resource suffixes in the inventory (or reject
   suspicious resource names before text parsing) and add a regression for
   private-key material.

3. **Authority configuration is not checked for all supported config forms.**

   `_read_config()` returns `None` for `.env`/`.env.local`, so the authority
   pass in `_scan_config()` (lines 463-516) never sees `EXECUTION_ALLOWED=true`
   in those files. The INI reader builds its mapping from
   `parser.sections()` at line 440 and therefore omits `[DEFAULT]` values; a
   `[DEFAULT] execution_allowed=true` fixture also returned `pass`. Both forms
   can carry schema/config authority and violate the requirement to reject any
   enabled `execution_allowed`/`executable_authority` value. Parse env
   assignments and include ConfigParser defaults (and add the corresponding
   failure-path tests).

4. **The rejection-registry validator does not enforce top-level
   `executable_authority=false` or the full auditable schema.**

   `validate_rejection_registry()` checks top-level `execution_allowed` at
   lines 604-608 but never checks top-level `executable_authority`. A mapping
   identical to the valid registry except for
   `executable_authority: true` returned `[]` from the validator. It also does
   not require top-level `registry_id`, `policy_version` or `last_reviewed`,
   record `scope`/`reviewed_at`, non-empty evidence-reference strings or
   reference existence. This permits an authority-bearing or unauditable
   registry to load despite the committed file carrying those fields. Enforce
   both top-level false literals and the complete versioned/audit schema, with
   tests for each mutation.

5. **The future-document allow-list accepts executable/config files, not only
   future documentation.**

   `_is_allow_listed()` skips every file beneath
   `docs/architecture/future/` at lines 215-218. A temporary
   `docs/architecture/future/bad.py` containing `def place_order(): pass`
   returned `pass`; the same content under `tests/` is an intentional fixture
   exception, but a Python/config resource in a documentation directory is not
   future-only documentation. Restrict this allow-list to the documented file
   types (or explicitly reject executable/config files there) so the
   allow-list cannot be used to hide production-like code.

6. **Order-control and endpoint detection misses valid prohibited forms.**

   `_UI_ORDER_CONTROL_RE` at lines 142-145 only matches phrases containing
   `order`, `buy now/order` or `sell now/order`; a UI source label `"Buy"` or
   `"Submit"` returned `pass`. `_scan_config()` inspects endpoint *key names*
   at lines 496-505 but not scalar URL values; `url:
   https://broker.example/orders` also returned `pass`. These are direct
   false negatives for the required current-UI-control and order-endpoint
   checks. Broaden the semantic UI-control patterns/path detection and inspect
   parsed endpoint/URL values, while retaining the benign `sort_order` case.

### Minor

1. Known broker SDKs imported through `importlib.import_module("broker_sdk")`
   are not detected by the AST import pass, and dependency scanning is limited
   to a fixed manifest-name set (for example, `requirements-prod.txt` is not
   treated as a dependency manifest). These are additional coverage gaps to
   address when hardening the scanner after the Important fixes.

## Confirmed strengths and boundaries

- `place_order()` and camel-case `OrderRouter` fixtures fail with the expected
  prohibited-symbol code, while `sort_order = 'asc'` passes.
- Known direct SDK imports, HTTP calls with an `/orders` path, authority values
  in YAML/INI section mappings, and `secrets.env` credential fixtures are
  rejected by the current paths.
- The exact allow-list prefixes use slash boundaries, so ordinary names such as
  `tests_evil/` and `future_evil/` do not escape through prefix matching.
- All three committed architecture records begin with the approved
  `# Future-only / no-authority` banner and contain no runnable order example
  or credential value. The package metadata uses setuptools package discovery,
  and the new `governance/__init__.py` is discoverable.
- The committed report and registry retain `execution_allowed=false` and
  `executable_authority=false`; no broker SDK, order endpoint, issue status,
  external upload or unrelated product capability was added in this range.

## Final decision

**CHANGES_REQUIRED**

The focused evidence is not sufficient for approval while production package
subtrees, credential resources, authority config forms and a top-level registry
authority mutation can bypass the boundary. Re-review after the targeted fixes
and adversarial tests above; do not close the later UI/package/browser tracker
records from this task.
