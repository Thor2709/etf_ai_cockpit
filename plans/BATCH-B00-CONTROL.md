# BATCH-B00-CONTROL

## Outcome and authority

Deliver a truthful, deterministic final-release control plane before feature fan-out. This batch owns the control-plane portion of `ISSUE-0070` and the adopted final-release issue intake. It does not implement the downstream product capabilities described by the new records.

`execution_allowed=false` remains mandatory. This batch may prepare and review a GitHub issue-sync plan, but applying the plan, pushing, merging, publishing, tagging, deploying, or enabling live execution remains a root-only later action after the batch gates pass.

## Fresh snapshot

- `VERIFIED` repository: `Thor2709/etf_ai_cockpit`.
- `VERIFIED` target/base: `origin/main` at `452d44034197cd5d837c1854603eea030e02acf6` (merge of PR #429), fetched with `git fetch --all --prune` on 2026-07-21.
- `VERIFIED` branch/worktree: `codex/final-release-20260721` at `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.worktrees\final-release-20260721`; clean at batch start.
- `VERIFIED` primary checkout was 325 commits behind and dirty with unrelated files. It remains untouched.
- `VERIFIED` open GitHub PRs: none. GitHub issue inventory: 249 issues.
- `VERIFIED` GitHub reports `main` as not protected (`GET /branches/main/protection` returned HTTP 404). Repository release gates remain mandatory despite the absent host-side rule.
- `VERIFIED` active Git worktrees at snapshot: 70, including historical/other-task worktrees; the two B00 worktrees are isolated and explicitly owned.
- `VERIFIED` provisional-ID collision gate: no local registry or GitHub issue-title collision for `ISSUE-0153`–`ISSUE-0176`.
- `VERIFIED` supplied specification SHA-256: `7A1D122E0BDBCB68DCD2B202A6F628F33718B2B9AE81CC2305649A7016D95810`.
- `VERIFIED` accepted `PLAN_step2.md` SHA-256: `93D32BC63895F3C0EE91704EA0B5EC056E0B789E4E97D6B9571294CD2A6DDB90`; it is absent from the fresh base but present as an untracked local input and matches specification source S1.
- `VERIFIED` `PLAN_step3.md` is absent. It will not be reconstructed.
- `VERIFIED` fresh repository `AGENTS.md` SHA-256: `BD899B98A9769C02201261442D3B778BB6C6383F18BEAC6EEAFF8FF6EB50EFD9`.
- `VERIFIED` global `AGENTS.md` SHA-256: `BA2E0CCF8249FB5E8A82507F79F0314D4DD12ECCE3F28775BB6099FCE59C25E3`.
- `VERIFIED` Codex config SHA-256: `1E86165B29C7B9EF1708A7832F1105478B0A3A6EB99ADB7B9EADFC42234544E7`; routing is `gpt-5.6-sol`, high reasoning, medium verbosity, `max_threads=10`, `max_depth=2`.
- `INFERRED` Codex desktop package version is `26.715.8383.0` from the installed executable path; direct `codex --version` failed with OS access denied.
- `VERIFIED` toolchain: Python 3.12.10, Git 2.54.0.windows.1, GitHub CLI 2.96.0.
- `VERIFIED` permissions: unrestricted local filesystem and network, no approval prompts. External writes remain limited by the current product-owner authority and this plan.

The freshly fetched base equals the specification's audited revision. There are no intervening commits to reconcile; no audited source evidence is marked stale for that reason.

## Acceptance criteria

- `B00-AC-REGISTRY`: schema and validation derive counts, supported IDs, phases, reverse links, and source reconciliation from canonical inputs; duplicate IDs, cycles, invalid edges, missing required typed fields, and generated drift fail deterministically.
- `B00-AC-READINESS`: an unresolved blocking edge cannot become ready through a status mutation. Closed dependencies or reviewed edge-specific `complete`, `partial_interface`, or `waived` evidence may resolve an edge; required inputs never block implementation; activation dependencies never grant activation; every decision has deterministic reason codes.
- `B00-AC-INTAKE`: the 24 collision-free records `ISSUE-0153`–`ISSUE-0176` and normative amendments are represented by a versioned canonical source, retain their dependency/capability/risk/acceptance contracts, and regenerate into the registry and ledgers without hand-editing generated files.
- `B00-AC-GENERATION`: registry, current status, progress, roadmap, implementation order, phase documents, programme/readiness projections, README/ledgers/changelog, and validation reports agree and reproduce byte-for-byte except declared environment/timing fields.
- `B00-AC-VALIDATION`: `validate_app.py` supplies enforcing `--full`, `--offline`, `--packaged`, and `--report-only` modes by composing existing validators/release gates; mandatory failures remain non-zero and reports record causal evidence.
- `B00-AC-SYNC`: a deterministic GitHub dry-run is reviewed by exact action/file/issue scope and SHA-256. No apply occurs in the implementation lane. A later authorised apply must use that exact SHA and produce a no-op readback.
- `B00-AC-SAFETY`: mandatory safe startup remains local-first and provider/model optional; adjusted-price and point-in-time rules remain unchanged; `execution_allowed=false` is asserted in registry, UI, validation, and sync evidence.

## Frozen contract

Each canonical record retains the existing dependency arrays and adds typed `activation_dependencies`, `dependency_edge_evidence`, `provenance`, `verified_commit`, `verified_date`, `acceptance_evidence`, `capability_lane`, `release_blocking`, `write_conflict_group`, and `risk` fields.

`dependency_edge_evidence` is keyed by blocking dependency ID. An edge entry has a versioned state of `unresolved`, `complete`, `partial_interface`, or `waived`. Any state other than `unresolved` requires non-empty evidence references, a reviewed contract/waiver reference, reviewer identity, and review date. Registry validation rejects evidence for a non-declared blocking edge.

Readiness is a pure deterministic projection returning `ready`, issue-level reason codes, and per-edge decisions. `programme_status`, including `ready`, `implemented_initially`, `integrated`, and `hardening_required`, never resolves a blocking dependency. A dependency closes an edge only when its ledger state is `closed`, or the consuming edge contains valid reviewed evidence as defined above. Activation readiness is reported separately and never changes `execution_allowed`.

Generated reverse links derive from blocking, required-input, and activation edges. Historical reconciliation snapshots are immutable evidence; a new snapshot is generated rather than rewriting old snapshots.

## Dependency and affinity graph

1. Final-release source and schema contract.
2. Registry builder, validator, dependency graph, readiness projection, and contract tests.
3. Canonical registry/ledger generation.
4. Status/progress/phase/roadmap/README and application/UI projections.
5. Validator dispatcher modes and report contract.
6. Focused/integration validation.
7. Deterministic GitHub inventory and reviewed sync dry-run.

Steps 2–7 depend on the preceding frozen output. No downstream writer may reinterpret the schema.

## Write and resource conflict graph

- Serial owner: `scripts/issue_registry_core.py`, `scripts/validate_issue_registry.py`, final-release source records, `issues/issue_registry.json`, and registry tests.
- Serialized generators: `scripts/generate_issue_registry.py`, `scripts/generate_completion_documents.py`, `scripts/update_programme_status.py`, and all generated programme/ledger/status artefacts.
- Schema consumers after contract freeze: `src/etf_cockpit/application/programme_map.py`, programme/release-readiness pages, validator dispatcher, and their tests.
- GitHub sync consumes the final generated registry and remote inventory. It must not run concurrently with registry generation.
- Package builds, full suites, and GitHub writes are centralized; workers run only focused checks.

## Ownership

- Root orchestrator: batch scope, frozen contract, batch plan, integration, broad validation, review resolution, commits, PR/push/merge, status transitions, and any authorised GitHub apply.
- Shared mapper: read-only call-path, dependency, and collision map; completed with no writes.
- One Sol-medium B00 high-risk issue owner: the complete serial implementation boundary above, in a dedicated isolated worktree. No child delegation, no push/merge/GitHub apply, and no material contract change without root review.
- One Luna-high shared test/reproduction agent: staged only after the implementation diff exists; tests/fixtures only, disjoint ownership.
- One Sol-low failure-diagnosis agent: staged only if a concrete unexplained failure exists.
- One Sol-medium independent reviewer: read-only after the bounded diff and focused evidence are stable.

## Validation and evidence

Baseline evidence at the frozen base:

- `python scripts/validate_issue_registry.py` — PASS.
- `python scripts/generate_issue_registry.py --check` — PASS/FRESH.
- `python scripts/update_programme_status.py --check` — PASS/FRESH.
- `python -m pytest -q tests/test_issue_registry.py tests/test_programme_map.py tests/ui/test_programme_map_ui.py` — PASS, 14 tests.

Required focused gate after implementation:

```text
python -m pytest -q <new/focused registry, readiness, generator, status, programme-map, validator and sync tests>
python scripts/generate_issue_registry.py --check
python scripts/validate_issue_registry.py
python scripts/update_programme_status.py --check
python -m ruff check <changed Python paths>
python -m compileall -q src scripts
python scripts/validate_app.py --changed
python scripts/validate_app.py --offline
python scripts/sync_github_issues.py <reviewed dry-run arguments>
git diff --check
```

The root then runs affected integration tests and the proportionate broader gate. Enforcing `--full`/`--packaged` may expose pre-existing environment/package failures; each failure is classified before repair and retained as evidence.

## Integration, rollback, and stop conditions

Integrate in dependency order: tests/contracts, registry/schema/readiness, canonical source/intake, generators/derived artefacts, UI projections, validator composition, sync dry-run. The entire batch is one reversible feature series; rollback restores the prior registry/generator contract and discards newly generated B00 artefacts without changing user data.

Stop the affected lane for a provisional-ID collision, ambiguous source-precedence conflict, unexpected status downgrade, stale base, changed remote head before push/merge, unowned file, generated hand edit, non-deterministic output, schema migration without compatibility evidence, secret exposure, live-authority change, or two non-improving repair attempts. Continue independent read-only work where possible.

## Progress

- `VERIFIED` freshness, hashes, toolchain, dirty-checkout isolation, open-PR state, local/remote ID collision gate, and baseline focused checks complete.
- `VERIFIED` mapper found hard-coded `159`, `ISSUE-0152`, static phase ranges, status-based readiness, and missing readiness/evidence fields in the canonical call path.
- `VERIFIED` B00 control implementation is integrated through root commit `3262a46c649b9c16119a52c29b5720fb57600a11`. The canonical registry contains 197 records, including the 24 collision-free final-release records; deterministic generation, evidence-aware readiness, transition authority, package parity, validator composition, UI projection, and dry-run sync evidence are implemented.
- `VERIFIED` the reviewed GitHub dry-run contains 197 actions: 24 create, 173 update, zero close, zero reopen, and zero blocked actions. Its semantic plan SHA-256 is `99F19FA2748C29242665FD88AD68E4898D161687DA5ABB607DCA1EFB3FBE49D2`; safe evidence SHA-256 is `0F18A36EF687D3AFF1F6257BCB0F2A562529BFDA06CF25023476CF06A467ADB8`. No apply or other GitHub mutation has occurred.
- `VERIFIED` the first enforcing `python scripts/validate_app.py --full` run completed in 1,135.2 seconds. Windows package build, package artefacts, source/package parity, packaged smoke, performance, source/security/privacy/backup/legal/SBOM/signature gates passed. It exposed one global-environment mismatch and three mandatory test failures: the static inventory false-positive in `_roadmap_phases`, a real live-publisher recovery race, and a date-sensitive trust fixture.
- `VERIFIED` failure classification preserved production safety: the inventory checker was not weakened; stale official evidence remains ineligible; analytical publication received deterministic ownership/recovery tests and a fail-closed implementation. Failed-gate diagnostics and runtime residue were moved intact outside the repository to `C:\Users\thor2\AppData\Local\Temp\b00-failed-gate-3262a46-20260721` and related `etf-ai-cockpit-b00-*` evidence directories.
- `VERIFIED` the locked release environment at `C:\Users\thor2\AppData\Local\Temp\etf-ai-cockpit-release-3262a46` uses Python 3.12.10, passes `pip check`, and matches the release dependency snapshot with zero missing or mismatched packages.
- `VERIFIED` four evidence-improving review/repair cycles closed publication ownership, checksum/row identity, lease token, process-start/PID-reuse, unreadable evidence, foreign destination, replacement lease, fixed-length token staging, Windows maximum-identifier, cleanup-order, post-commit cleanup, retry/readback, and bounded enumeration defects. Independent review approved exact repair checkpoint `3e6d22e2b37251948e7de9a79dafbba1cade3614` with no remaining findings.
- `VERIFIED` the approved repair series is integrated as root commit `6f792e3` (`fix(storage): make analytical publication ownership-safe`). From the integrated worktree, affected hybrid/trust/inventory tests passed 54/54 and the exact B00 control suite passed 98/98. Ruff, compileall, registry validation, registry/completion/status/control freshness, changed validation, and offline validation passed under the locked interpreter.
- `VERIFIED` `execution_allowed=false` remains asserted; no broker write, deployment, release/tag publication, push, PR, merge, or GitHub issue apply has occurred.
- `VERIFIED` the clean locked-environment enforcing `python scripts/validate_app.py --full` rerun passed at `d5cf0710ac9fe7cf56ef6577bf3e79b3a140ea24` in 850.1 seconds with zero failures. All 14 mandatory checks passed: pinned environment, full tests, Windows package build/artefacts, source/package parity, packaged smoke, performance budgets, source policy, bulk cache, security policy, privacy/backup, legal terms, SBOM, and signature. Optional `torch`, TimesFM, and Toto remained explicitly unavailable without breaking mandatory workflows.
- `VERIFIED` passing release evidence was archived intact outside the repository at `C:\Users\thor2\AppData\Local\Temp\b00-full-gate-pass-d5cf071-20260721` (31 files). The release manifest SHA-256 is `7FE81547B937475FB47D61B6673C4768CA26246B42C3EEA22D88E968A4A326FF`; report SHA-256 is `A23827F8EDE82F3C6991BB92875C448E267738845E3B6F2A1E4244D8812EBB83`; detached signature file SHA-256 is `BC3691B8B496FEE0FF2D29FC7586C16529F4B6CAD6BBBD7C380A0C0F4215BC67`. The outer dispatcher recorded `dirty=true` only after the gate generated its untracked report/runtime outputs; the protected gate's clean-preflight check passed and the outputs were subsequently archived, leaving the worktree clean.
- `VERIFIED` feature PR `#430` merged as `2e5661b8c265ab438dd20e7b13e4ce4ebb13b8eb`; convergence PR `#431` merged as `05fd95164b5085f077b68b4d43c9d895dddc6369` after deterministic status/control regeneration and review.
- `VERIFIED` the approved semantic GitHub issue-sync plan (`99F19FA2748C29242665FD88AD68E4898D161687DA5ABB607DCA1EFB3FBE49D2`) was applied, read back, and converged to the zero-action semantic plan `b6cea0ac9ea1a16a83fd3ea3981d45cfea2f86d5dba1728bfee03583ce01a3f6`.
- `BLOCKED` protected post-merge push run `29840899433` failed only the mandatory `signature` check on Linux job `88669236408` and Windows job `88669236467`: `ETF_COCKPIT_RELEASE_SIGNING_KEY is not set`. Every other mandatory check passed on both operating systems. Repository Actions secrets and variables were empty at readback. This is an external signing-key provisioning requirement retained for B13 release evidence; the workflow is not weakened and no unsigned push/release is treated as protected evidence.
- `VERIFIED` B00 implementation and control-plane convergence are complete at `05fd95164b5085f077b68b4d43c9d895dddc6369`. No release, tag, deployment, live execution, or authority escalation occurred; `execution_allowed=false` remains invariant.
