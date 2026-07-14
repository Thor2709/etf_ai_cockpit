# Wave 5 Task 21 review fix report

## Review findings addressed

- Added both root and `evidence_export/checksum_manifest.json` copies to the
  complete audit contract and list them in the audit manifest.
- Declared checksum-manifest self-hash exclusion explicitly rather than
  claiming an impossible recursive hash; the outer audit manifest records the
  ordinary SHA-256 of both files.
- Made unavailable and export-failure marker names deterministic and unique
  for source paths that share a stem.
- Added strict `complete-audit-v1` validation of required record fields and
  non-empty SHA-256 values while retaining legacy minimal-manifest support.
- Added regression coverage for malformed strict manifests, extraction path
  traversal and same-stem marker collisions.

## Verification

- Bundled compileall passed:
  `C:\Users\thor2\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m compileall -q src tests`.
- `git diff --check` passed; only line-ending normalisation warnings were
  emitted.
- Focused pytest was unavailable because the bundled Python has no `pytest`
  module and the isolated worktree has no repository venv launcher.
- Ruff was unavailable because no Ruff executable is present in the isolated
  worktree.

## Review disposition

The fresh independent reviewer’s initial blocking findings are addressed in
the working diff. A clean re-review is required before integration.

## Re-review finding and correction

The next fresh re-review demonstrated that strict validation still trusted an
empty required list and a non-object checksum container. The validator now
compares strict manifests with the complete canonical path set, rejects
non-object checksum maps, and the focused tests cover that empty-archive case.

The final review also identified that the traversal regression used a strict
manifest without the full canonical fixture, so validation failed before the
extraction guard ran. The test now uses the documented legacy minimal manifest
solely for traversal isolation; strict completeness remains covered by its
dedicated test.
