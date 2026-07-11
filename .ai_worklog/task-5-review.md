# Wave 0 Task 5 independent review

## Scope and basis

Fresh review of `7089cd7034fe0c2bbd732b664c6b54201ac8956a` against base
`d5ea661`, using `.ai_worklog/task-5-brief.md`,
`docs/superpowers/plans/2026-07-11-etf-ai-cockpit-foundation-operations-boundary-plan.md`
Task 5, the changed-source diff, and the current closure-matrix policy. This
review did not edit source or tests and did not mutate issue ledgers, closure
status, or any remote tracker.

## SPECIFICATION verdict - CHANGES REQUIRED

The read-only result shape and the visible happy/failure-path tests are
present, but the evidence boundary is not fail-closed enough for independent
approval. In particular, package evidence can be asserted without running a
package command, and the verifier accepts manifest-declared commands without
checking them against the deterministic plan.

### Critical findings

None observed. I found no tracker write, issue-state mutation, credential use,
broker capability, `execution_allowed` change, or other authority/scope drift.

### Important findings

1. **Package pass is synthesised from the build result.**
   `scripts/verify_clean_environment.ps1:223-231` invokes only the build
   command and then creates a `package` row by copying the build result. A
   successful build therefore records `package=pass` without a package
   command or package artefact. The script also has no browser stage. This
   violates the explicit clean-environment fail-closed requirement and the
   package/browser evidence gate.

2. **Manifest commands are not bound to the deterministic command plan.**
   `scripts/verify_issue.py:646-696` validates the gate labels and result but
   never compares each run's command/argv to `fixed_command_plan()` or another
   matrix-declared command. A caller can self-attest an arbitrary command while
   claiming a required gate; the verifier only checks the supplied metadata.
   This breaks the Task 5 requirement that verification reads only the fixed,
   matrix-declared commands.

3. **Missing output captures can satisfy a gate.**
   `scripts/verify_issue.py:465-466,338-389` defaults missing
   `output_paths`/`output_checksums` to empty lists, and the validator treats
   two empty lists as valid. A passing run can therefore contain no captured
   stdout/stderr or SHA-256-addressed output, contrary to the evidence
   contract.

4. **Run-level environment binding is fail-open.**
   `scripts/verify_issue.py:481-483` substitutes the request's expected
   environment hash when a run omits `environment_hash`; only a supplied,
   different value is rejected. A manifest can consequently pass while its
   captured run has no environment identity at all.

5. **Package/build runs do not require screenshot metadata.**
   `scripts/verify_issue.py:681-692` validates screenshots only for `browser`
   and `ui` gates. A required `package` (or `build`) gate may pass with no
   screenshot, although the brief explicitly calls out missing package/browser
   evidence and fake/missing screenshot metadata as non-passing.

### Minor findings

1. Screenshot validation checks extension, checksum and positive declared
   dimensions, but does not decode the image or verify that the bytes are an
   image with those dimensions (`scripts/verify_issue.py:392-428`). A text
   file named `.png` with a matching hash and fabricated dimensions is
   accepted.
2. The clean-environment manifest uses uppercase `BLOCKED`/`pass` mixtures and
   omits per-run source/environment hashes (`scripts/verify_clean_environment.ps1:103-116,240-250`),
   so it is not directly representable as the typed `VerificationRun` package
   consumed by `verify_issue.py` without an additional normalisation step.
3. `execute_command_plan()` does not catch `OSError`/`FileNotFoundError` around
   `subprocess.run` (`scripts/verify_issue.py:780-788`); a missing fixed tool
   raises instead of yielding a typed blocked run. The dedicated PowerShell
   script does fail closed, but the Python command-capture helper does not.

## CODE-QUALITY verdict - CHANGES REQUIRED

The implementation is readable, deterministic in ordering, uses local paths,
redacts captured output, protects evidence-root traversal, and preserves
backwards-compatible optional fields in `VerificationRun`. However, the
fail-open behaviours above are contract-level correctness defects, not merely
style concerns. Test coverage is narrow: the visible tests cover stale hashes,
skips, informational runs, reviewer identity, screenshot metadata and a bad
checksum, but do not cover command-plan binding, empty output captures,
missing run environment hashes, package-only screenshots, or the synthetic
package row.

## Independently run commands and results

```text
& "C:\\Users\\thor2\\Desktop\\Trading App\\etf_ai_cockpit\\.venv\\Scripts\\python.exe" -m pytest tests/release/test_verification_automation.py tests/release/test_clean_environment.py tests/release/test_package_matrix.py tests/operations/test_verification_records.py -q --tb=short
20 passed in 1.96s (exit 0)
```

The worktree-local interpreter was also checked with the same command and
failed before collection: `No module named pytest` (exit 1). The broader
`tests/release` + `tests/operations` run, Ruff, compileall, `pip check`, and
PowerShell parser were not independently rerun in this fresh review after the
parent requested immediate closure of the review; implementer-reported results
are therefore not treated as independent evidence.

## Closure recommendation

Do not approve or integrate Task 5 yet. Keep all issue and closure-matrix
statuses unchanged. First make command selection and run metadata mandatory,
execute package and browser stages independently (with real artefacts), then
add focused regression tests for each finding and rerun the requested release,
operations, Ruff, compileall, dependency and PowerShell checks.

## Limitations

This is a source/diff review plus the focused test command above. It does not
constitute package, browser, clean-environment, full-release, or full-suite
evidence, and it makes no issue-closure recommendation beyond retaining the
current open statuses.
