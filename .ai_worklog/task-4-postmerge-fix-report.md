# Wave 0 Task 4 post-merge scanner fix

Date: 2026-07-12 (Australia/Sydney)
Branch: `wave0/task4-postmerge-hardening`
Base: `0f2b2cb` (Task 4 merged checkpoint)

## Root cause

The post-merge package-inventory test scanned ignored generated `build/`
artefacts. Vendored package files then produced false boundary violations
(certificate resources, model `token_ordering` identifiers and an audit-parser
phrase). The repository `.gitignore` already classifies `build/` and `dist/`
as generated package output; source boundary scanning must not treat those
artefacts as production source.

## RED

Added `test_ignored_generated_package_roots_are_not_scanned`, which creates a
prohibited symbol below `build/`. The focused test failed behaviourally before
the change (`assert report.result == "pass"`; observed `fail`).

## GREEN and regression evidence

- The scanner now excludes top-level generated `build/` and `dist/` roots while
  continuing to scan production source subtrees, including `src/etf_cockpit/data`
  and `src/etf_cockpit/models`.
- Focused Task 4 and release bundle: 54 passed, exit 0.
- Release and operations regressions: 74 passed, exit 0.
- Scoped Ruff, compileall, pip check and `git diff --check`: passed.
- Production scan: `pass`, 356 files, zero violations, schema `1.0`, policy
  checksum `89680ebfdca87827728919e687f50f30cebe014741ce35eb4b3c32daa83452f1`,
  `execution_allowed=false`, `executable_authority=false`.

No issue status, authority, broker capability, credentials, product scope or
user data changed. The generated transaction artefact found during concurrent
post-merge verification was separately recovered only after its committed
destination checksums matched the journal; no destination payload was altered.
