# Wave 5 Task 21 implementation report

## Task completed

Implemented the complete audit-manifest/export/import/UI seam while preserving
the local-only boundary and `execution_allowed=false`.

## Files and symbols examined

Reviewed `_write_audit_manifest`, `_export_trust_critical_evidence`,
`validate_audit_archive`, `import_audit_json`, `chatgpt_audit_page` and the
Task 20 trust/export regression tests. Changed files are listed below.

## RED

Added `tests/test_complete_audit_packet.py::test_generated_audit_manifest_declares_complete_canonical_artefact_set` before implementation. The intended command was:

```text
python -m pytest tests\\test_complete_audit_packet.py -q
```

This worktree has no Python launcher (`'python' is not recognized as an internal or external command`), so the test process could not start and no behavioural exit code was produced. The parent worktree must rerun this command with its available runtime.

## GREEN / implementation

- Extended deterministic audit export with provider, identity, statements, fund documents/holdings, ETF disclosures, KID/methodology, news validation, conflicts, evidence ledger, score history/components/metrics, drivers, clusters, attribution, edge/cost, health, workflow/session, redacted config and issue-dossier artefacts.
- Every required record now carries `schema_version`, `source_authority`, `sha256` and `allow_unavailable`; optional gaps produce a JSON-shaped unavailable marker and reason rather than silent omission.
- Added a separate `checksum_manifest.json`; archive validation checks required-entry hashes, all listed hashes and unlisted files, scans common secret forms and offers safe validated extraction with traversal containment.
- External JSON audit imports reject unredacted secrets and audit archives, and persisted notes explicitly retain `execution_allowed=false`, `executable_authority=false` and cannot change scores/actions/configuration.
- ChatGPT audit UI verifies extraction/checksums before displaying the output path and included artefact count.

## Files changed

- `configs/audit_manifest.yaml`
- `src/etf_cockpit/chatgpt_bridge/export_pack.py`
- `src/etf_cockpit/chatgpt_bridge/audit_packet.py`
- `src/etf_cockpit/chatgpt_bridge/import_audit.py`
- `src/etf_cockpit/app/pages/chatgpt_audit.py`
- `tests/test_complete_audit_packet.py`

## Commands and results

- `git diff --check` - passed (only line-ending normalisation warnings).
- `python -m pytest tests\\test_complete_audit_packet.py -q` - blocked: Python executable unavailable.
- `ruff check ...` - blocked: Ruff executable unavailable.

No archive, extraction, secret-scan or packaged/browser evidence could be generated in this worktree without Python/runtime tooling.

## Evidence

The implementation commit is `8cc6d8c`; the focused RED test and validation
report are in this worktree. `git diff --check` passed.

## Remaining uncertainty and risk

Runtime pytest/Ruff/compileall and source/package UI checks remain unverified;
the parent must confirm generated archive checksums and marker paths with a
working Python environment.

## Limitations and review handoff

The parent must run the focused complete-audit and Task 20 regression tests, scoped Ruff/compileall, a real export/archive validation and source/packaged UI smoke checks. Independent specification-compliance and code-quality review remain required. `execution_allowed=false` is preserved throughout.

## Exact next action

Run the focused pytest, Ruff and compileall commands in the parent worktree, then perform the independent Task 21 review and fix any Critical/Important findings before integration.

## Recommended next action

Run the parent-worktree focused tests and independent specification/code-quality review before cherry-picking or merging.

## Independent review and fix pass

Fresh reviewer `task21_reviewer3` assessed the exact implementation head and
rejected it initially. The specification finding was that the focused
canonical artefact test required both root and `evidence_export` checksum
manifests while the exporter emitted only the root copy. Important code
findings were colliding unavailable markers and permissive validation of
required manifest records.

The fix pass adds deterministic root/evidence checksum manifests with an
explicit `self_hash_excluded` contract, unique source-derived unavailable
markers, strict validation for `complete-audit-v1` records, and regression
tests for malformed manifests, traversal-safe extraction and marker
uniqueness. The fix pass was reviewed in the same worktree after the initial
review; no Critical or Important finding remains in the inspected diff.

Fresh verification:

- `C:\Users\thor2\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m compileall -q src tests` - passed.
- `git diff --check` - passed (line-ending normalisation warnings only).
- Focused pytest - unavailable: the bundled runtime has no `pytest` module and
  the repository venv launcher is not present in the isolated worktree.
- Ruff - unavailable: no Ruff executable is present in the isolated worktree.
- Package/browser/export runtime evidence remains closure-pending because the
  required project runtime dependencies are unavailable in this environment.

The implementation remains non-executable and preserves
`execution_allowed=false`.

The subsequent re-review found and reproduced one remaining Important gap:
strict validation accepted an empty `required` list and a list-valued
`checksums` field. The validator now enforces the complete canonical path set
and object-valued checksum map, with a focused regression test. A final fresh
re-review is required after this correction.

Final re-review approved specification compliance and confirmed the validator,
exporter and authority boundaries. It identified only a test-fixture issue:
the traversal test used a strict incomplete manifest. The fixture now uses a
legacy minimal manifest to isolate extraction traversal, while strict
completeness remains covered separately. Pytest, Ruff, archive export and
UI/package runtime checks remain unavailable in this environment.

Final closure review at head `5270d60` returned SPEC PASS and CODE PASS with
no Critical or Important findings. It confirmed the strict canonical set,
dual checksum manifests, marker uniqueness, traversal guard, legacy fixture
boundary and `execution_allowed=false` authority boundary. Runtime pytest,
Ruff, package, browser and live export checks remain closure-pending because
the required environment dependencies are unavailable.
