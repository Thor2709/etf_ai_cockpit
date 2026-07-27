# BATCH-DOCS-SDD-20260727

- Base: `6525429d56160167fbeb023636f8b00b05e28336`
- Branch: `docs/current-sdd-20260727`
- Current task: replace the legacy MVP master specification with a code-verified current SDD, architecture index, traceability map and focused ADR set; align related repository documentation.
- Implementation: the single `sol_worker` completed the bounded documentation and documentation-test change; one focused correction removed an invented snapshot symbol and made all eight required runtime contracts explicit.
- Review: accepted after complete diff, path, link, generated-marker and authority/status scope review.
- Validation: documentation pytest (6 passed), Ruff, compile and `git diff --check` pass. Source compile and offline smoke pass. Registry generation/status and the aggregate changed/offline validators retain the pre-existing fail-closed baseline: control records reference `5a6766c3a7520299cc2c058455ddcd7b2993dc8e` while `origin/main` is `6525429d56160167fbeb023636f8b00b05e28336`.
- Blocker: no documentation blocker; the stale programme-control baseline is outside this task's authorised write scope and is reported without repair.
- Next action: final base/scope audit, logical commits, push and documentation PR.
- Authority: documentation only. Product behaviour, financial calculations, issue records/status, generated status artefacts and `execution_allowed=false` must not change.
