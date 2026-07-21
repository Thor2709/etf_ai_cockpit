# BATCH-B01-POLICY

## Outcome and authority

Deliver the first dependency-valid policy slice for `B01-POLICY`: a deterministic, visible, machine-readable strategy/instrument capability matrix (`ISSUE-0008`) followed serially by typed, versioned and staged settings (`ISSUE-0037`). The later provider, legal and credential owners (`ISSUE-0080`, `ISSUE-0149`, `ISSUE-0176`) remain blocked until their canonical dependency edges are resolved and reviewed.

Normal recommendations remain unleveraged and long-only. Rejected, research-only and unsupported products or strategies cannot enter ranking, modelling, portfolio, paper or order paths through provider misclassification or a risk-profile override. `execution_allowed=false` is invariant. This batch does not implement broker writes, live activation, paid mandatory providers, cloud uploads, legal approval or a plaintext secret store.

## Fresh snapshot and reconciliation

- `VERIFIED` authorised base: merged `origin/main` at `05fd95164b5085f077b68b4d43c9d895dddc6369`.
- `VERIFIED` control refresh: `ec7578a47125c061d018f51a93a9efb9eb5a2ad7` updates the generation base, canonical hashes and read-only reconciliation evidence without changing issue status.
- `VERIFIED` branch/worktree: `codex/b01-governance-20260721` at `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.worktrees\b01-governance-20260721`; clean before this plan.
- `VERIFIED` primary checkout remains dirty with unrelated user-owned files and is not touched.
- `VERIFIED` no open pull requests were present at the B01 start snapshot.
- `VERIFIED` supplied specification SHA-256: `7A1D122E0BDBCB68DCD2B202A6F628F33718B2B9AE81CC2305649A7016D95810`.
- `VERIFIED` `PLAN_step2.md` and `PLAN_step3.md` are absent from this clean worktree. They are not reconstructed.
- `UNKNOWN` Codex CLI version because direct executable version inspection was denied by the operating system. Model routing is Sol-high for the root; no Terra, xhigh or max routing is used.
- `VERIFIED` locked release interpreter: Python 3.12.10 at `C:\Users\thor2\AppData\Local\Temp\etf-ai-cockpit-release-3262a46\Scripts\python.exe`.
- `VERIFIED` the repeated B01-start GitHub semantic sync projection is a no-op: zero create, update, close, reopen or blocked actions; semantic plan SHA-256 `b6cea0ac9ea1a16a83fd3ea3981d45cfea2f86d5dba1728bfee03583ce01a3f6`.

## Readiness and no-change gate

| Issue | Current state | Readiness | Disposition |
|---|---|---|---|
| `ISSUE-0008` | `implemented_initially` | `VERIFIED` ready | Audit existing taxonomy, retain accepted behaviour and implement only the missing staged capability/instrument contract. |
| `ISSUE-0037` | `planned` | `VERIFIED` ready | Implement after the ISSUE-0008 authority contract is frozen. |
| `ISSUE-0080` | `integrated` | `BLOCKED` | Unresolved blocking edges to `ISSUE-0070` and `ISSUE-0076`; no writes in this batch wave. |
| `ISSUE-0149` | `hardening_required` | `BLOCKED` | Unresolved blocking edge to `ISSUE-0080`; no simulated terms/legal approval. |
| `ISSUE-0176` | `planned`, high risk | `BLOCKED` | Unresolved edges to `ISSUE-0037`, `ISSUE-0076`, `ISSUE-0080`, `ISSUE-0144`, `ISSUE-0145`, `ISSUE-0146` and `ISSUE-0149`; no credential-vault implementation until resolved. |

`NO_CHANGE` is not claimed for either selected issue. Existing ISSUE-0008 taxonomy, rejection tests and authority boundary are retained evidence, but they do not satisfy the amended per-asset/per-strategy staged matrix. ISSUE-0037 has a partial settings page and provider form, but lacks the required typed versioned schema, migration and staged semantic-impact contract.

## Acceptance criteria

### ISSUE-0008

- `B01-0008-AC1`: the canonical matrix classifies every retained strategy family from the issue body and the amended asset families: stocks, ETFs, bond ETFs, ordinary funds/share classes, supported bond types, cash/FX, and explicit exclusions including OTC/penny shares, illiquid microcaps, leveraged/inverse products, crypto, derivatives, shorting, margin/leverage and complex structured funds.
- `B01-0008-AC2`: every strategy row declares reason, required data, required tests, authority, UI visibility, and score/paper/live implications; every instrument capability cell declares data, model, liquidity, broker and legal prerequisites.
- `B01-0008-AC3`: deterministic resolution covers analyse, portfolio, backtest, paper, draft-order, canary and bounded-automatic stages and returns a stable support state plus reason codes. Every imported instrument resolves explicitly; unknown CFI/security types reject rather than fall through.
- `B01-0008-AC4`: martingale, grid, autonomous LLM/model-only/sentiment-only trading, RL agents, unsupported derivatives, leverage and shorts remain rejected or research-only as specified. No risk profile or configuration can promote an excluded class. Long-only actions are limited to `buy/add`, `hold`, `avoid/no_trade`, `trim/sell` and `manual_review`; `execution_allowed=false` remains asserted.
- `B01-0008-AC5`: the Strategy Scope/System Map UI and audit/export projection show the same matrix, support states, prerequisites and reason codes through an application-facing contract; route/control smoke and UI/export parity pass.

### ISSUE-0037

- `B01-0037-AC1`: settings cover universe/watchlists, target weights, risk limits, costs/slippage, models, provider/news/RSS/macro definitions, paper settings, ISO-4217 selected currency, stock/ETF/ordinary-fund/bond scope, five canonical risk profiles, exact `1W/1M/3M/6M/9M/2Y/5Y` horizons and `Quick/Medium/High/Full` depth.
- `B01-0037-AC2`: one typed, versioned configuration schema supplies safe defaults and deterministic migration from existing onboarding/config values, preserving compatible values and reporting unsupported ones explicitly.
- `B01-0037-AC3`: edits are staged and validated as a whole before atomic persistence; invalid currency, horizon, profile, depth, provider or safety-bound values cannot partially save.
- `B01-0037-AC4`: before/after preview identifies policy and run-manifest effects. A semantic change creates a new settings version and is traceable into new analysis/selection output; presentation does not calculate policy consequences independently.
- `B01-0037-AC5`: exports and logs redact secret values. Existing plaintext `.env` entry behaviour is not expanded; secure credential CRUD remains unavailable with an explicit `ISSUE-0176` dependency until the vault/legal/provider contracts are ready.
- `B01-0037-AC6`: migration, locale/currency, validation, save/reload, redaction, version/run-manifest parity and Settings UI smoke tests pass.

## Frozen contracts and sequencing

Wave 1 freezes ISSUE-0008 enums, reason codes, capability stages, support-state semantics, schema validation and resolver behaviour in tests before downstream presentation work. Existing public strategy-scope consumers remain compatible unless an explicitly reviewed migration is added. UI consumes an application/governance projection and does not import configuration or calculate authority locally.

Wave 2 begins only after Wave 1 focused validation and review. It freezes the typed settings/version/migration/impact-preview contract before storage and UI consumers. Secret references are opaque and redacted; no secret value enters normal configuration serialization. An unavailable secure-credential action must identify its dependency instead of writing plaintext.

Status or dependency-edge transitions occur only after executable acceptance evidence and independent review. A downstream issue is not made ready by changing its programme status.

## Dependency, affinity and conflict map

1. ISSUE-0008 contract tests and table fixtures.
2. Canonical scope models, YAML/schema validation and deterministic resolver.
3. Application projection, audit/export and UI parity.
4. ISSUE-0037 typed schema/migration/version/impact tests.
5. Settings storage and application facade.
6. Settings UI and export/run-manifest parity.
7. Focused integration, independent review, broader gate, traceability and convergence.

The authority model, product-scope configuration, settings schema, application state/facades, route metadata, UI pages, exports and generated programme records are serial write-conflict groups. Package builds, full suites, registry generation and GitHub operations are central-only. ISSUE-0080/0149/0176 writers are not released while their edges remain unresolved.

## Ownership

- Root orchestrator: both selected issue contracts and all shared schemas/public interfaces; tests and implementation; batch integration; status; commits; PR/push/merge; and any authorised GitHub synchronisation.
- Shared scout/reviewer: read-only current-state, dependency and collision map, then bounded completed-diff review. No writes or delegation.
- Shared test/reproduction or failure-diagnosis role: staged only for a genuinely independent test boundary or concrete unexplained failure.
- Independent Sol-medium reviewer: required after each stable authority/security-sensitive slice and before release hand-off.

One writer owns each shared file/symbol/contract at a time. Work-in-progress is limited to ISSUE-0008 implementation plus the already frozen B00 release follow-up; ISSUE-0037 remains read-only until ISSUE-0008 is frozen.

## Validation and evidence

ISSUE-0008 starts with a failing behavioural contract proving the amended matrix/resolver is absent, followed by the smallest implementation and focused pass. Planned focused checks include:

```text
python -m pytest -q tests/test_strategy_scope.py tests/scope_boundary/test_rejection_registry.py tests/test_authority_resolution.py tests/scope_boundary/test_execution_boundary.py <new capability/UI/export tests>
python -m ruff check <changed Python paths>
python -m compileall -q src scripts
python scripts/validate_issue_registry.py
python scripts/generate_issue_registry.py --check
python scripts/update_programme_status.py --check
git diff --check
```

ISSUE-0037 additionally requires focused config migration, atomic save/reload, redaction, settings-to-run-manifest and Settings UI tests. The root then runs affected architecture, authority, route, UI-acceptance and application integration checks, followed by the proportionate broader/release gate before merge. Complete source/packaged/UI/security/legal evidence is not inferred from focused tests.

## Rollback and stop conditions

Each issue is a separate logical reversible checkpoint. Rollback restores the prior scope/settings contract without changing user data; any settings migration must prove backward compatibility and recovery before it is used.

Stop the affected lane for a stale or changed base, material source-precedence conflict, unexpected status downgrade, unowned file, generated hand edit, schema migration without compatibility evidence, unknown instrument silently accepted, authority promotion, secret disclosure, plaintext credential expansion, paid/online mandatory startup, live execution change, non-deterministic reason code, product-code correction required on a frozen release branch, or two non-improving repair attempts. Record the exact blocker and continue only independent ready work.

## Progress

- `VERIFIED` B00 feature and convergence PRs merged; canonical control base and GitHub issue state converge.
- `VERIFIED` B01 base reconciliation, deterministic control refresh and no-op GitHub readback complete at `ec7578a47125c061d018f51a93a9efb9eb5a2ad7`.
- `VERIFIED` read-only scope/settings call-path and gap map complete.
- `VERIFIED` ISSUE-0008 test-first implementation is frozen at `96b963b7bcdf8f0adee039eeb8a25f67be23fbfd`: schema-2 staged strategy/instrument capabilities, fail-closed classification, application projection, System Map parity, and audit export are implemented without changing live authority.
- `VERIFIED` the root focused boundary passed 135 tests. The independent Sol-medium re-review passed 116 focused tests plus Ruff and `git diff --check`, verified exact historical schema-1 migration, and returned no findings for `B01-0008-AC1` through `B01-0008-AC5`.
- `VERIFIED` Ruff, compileall, registry validation and deterministic registry/status freshness passed. The enforcing full gate ran for 1,053.6 seconds at `96b963b7bcdf8f0adee039eeb8a25f67be23fbfd`; full tests, Windows package build/artefacts, source/package parity, packaged smoke, performance, source policy, bulk cache, security, privacy/backup, legal terms and SBOM all passed.
- `BLOCKED` only the full gate's mandatory signature check failed: `ETF_COCKPIT_RELEASE_SIGNING_KEY is not set`. This exactly matches the B00 protected-CI external configuration fingerprint. It is retained for B13 and does not justify weakening the gate or stopping independent B01 work.
- `VERIFIED` the 31 generated gate/runtime files were archived outside the repository at `C:\Users\thor2\AppData\Local\Temp\etf-ai-cockpit-b01-validation-96b963b-20260722-0141`, leaving the feature worktree clean. Release-manifest SHA-256: `593BED5766795533FFC407618544D54346424222835E87AF0D8494CE0B2B0426`; report SHA-256: `FE4BF60B8CBBA8C3CB10DC4486C67F5EDF5C4F5AC73E58691EC1BB177E52B23E`; full-test-log SHA-256: `EFFF09503868522D69262F388D9E91B979A8EFC750CE14914B0C9DE9120C90B2`.
- `VERIFIED` PR `#456` merged the reviewed ISSUE-0008 checkpoint as `47bdc95b6f8360b454f3bfa707226af8c500ad53`. Transition guard, supply-chain scan, Linux release gate and Windows release gate all passed on the exact head; the post-merge capability/System Map smoke passed 24 tests.
- `VERIFIED` PR `#457` merged the guard-compatible base-only control refresh as `3fc1f2073b9f5ba6aec2e28e812d985a1086165a`. All 197 canonical records and status counts remained unchanged; the transition allowlist was empty; the fresh GitHub projection was a no-op; status-transition, supply-chain, Linux release and Windows release checks all passed.
- `VERIFIED` post-merge ISSUE-0008 control convergence and GitHub projection were prepared locally: two read-only projections agree byte-for-byte and contain exactly one update, zero create/close/reopen/blocked actions; safe-evidence SHA-256 `ADBDCA7AD5DCFA38AEFB8E6923D476AD5866EFB3C1265FCCC61C24E7D5177A77`. The existing guard correctly forbids combining canonical migration evidence with a programme-status transition, so that local convergence is removed from the ISSUE-0037 feature PR and deferred to a separately reviewed guard-compatible sequence. `origin/main` truthfully remains at ISSUE-0008 `implemented_initially` until that sequence merges.
- `VERIFIED` ISSUE-0037 now has one `settings_bundle.v1` application contract covering canonical controls, whole-bundle validation, deterministic read-only legacy migration with surfaced diagnostics, monotonic version/revision identity, lock-held expected-revision recheck, grouped atomic persistence/readback, immutable secret-free snapshots, audit export, Settings/Onboarding UI and explicit `ISSUE-0173`/`0174`/`0175`/`0176` unavailable states. `execution_allowed=false` remains literal throughout.
- `VERIFIED` reviewer-discovered boundary failures were reproduced before repair: secret-name aliases could leak, persisted allowlists could bypass full validation, preview/save revisions differed, run outputs could precede a settings mismatch, migration diagnostics were discarded, and independently reloaded settings could mix run/cache revisions. The repaired contract uses typed extra-forbidden provider metadata, normalized secret rejection, full load validation, exact next-version preview identity, settings-bound run IDs reserved before output, and one captured settings revision per publication/cache-read operation.
- `VERIFIED` final focused settings/UI/security suite passed 28 tests; the publication/interleaving subset passed 7 tests independently. The expanded affected collection contains 174 tests across settings, versioning, onboarding, atomic I/O, export, architecture, security, universe/cache, forecast/backtest, recovery and UI. Its pre-documentation run passed with one intentional skip, and final integration/release validation remains pending below.
- `VERIFIED` the independent Sol-medium reviewer returned PASS after executable two-file/two-row interleaving tests proved that each cache operation now resolves one settings revision and rejects evidence from another settings era. No review finding remains in the bounded ISSUE-0037 diff.
- `VERIFIED` a clean-runtime affected run exposed one documented ordering dependency: the optional-model forecast fixture supplied an in-memory frame before canonical `dataset:prices` existed, so the pre-publication manifest failed closed. After the later standard UI/bootstrap fixture created the local baseline, the exact node passed 1/1. Both results are retained; no manifest dependency was weakened.
- `REVISE` the first protected full gate ran for 1,086 seconds and passed package build, package artefacts, source/package parity, packaged smoke, performance, source policy, bulk cache, security, privacy/backup, legal terms and SBOM. It failed full tests only because `test_every_record_has_typed_final_release_contract_fields` still required every record to retain bootstrap SHA `452d440...`, while the then-present local ISSUE-0008 convergence recorded merged SHA `47bdc95...`; mandatory signature also retained the external `ETF_COCKPIT_RELEASE_SIGNING_KEY is not set` residual. Evidence: `C:\Users\thor2\AppData\Local\Temp\etf-ai-cockpit-b01-settings-full-eaef242-20260722-0255`; manifest SHA-256 `894F2F97F1E1CDD7E5950CE965AB26A655AD7DEADA169C20154585550285BBC8`; report SHA-256 `36317434EB4B963345C4A1C7197C507F4D987E8F316658286F31FB20B32F7354`; test-log SHA-256 `3456F8E8F8359D84B6AC88780A1EDA28DD07629B040F77492F66B2C678507638`.
- `VERIFIED` the stale bootstrap assertion was replaced with strict per-record full lowercase Git-SHA and canonical ISO-date validation. The entire B00 control-plane suite passed 33 tests; Ruff and diff check passed; independent review confirmed transition, downgrade, invalid-SHA/date, authority, unresolved-edge and `execution_allowed=false` coverage remains intact. A second full gate is required before checkpoint.
- `VERIFIED` the second protected full gate ran against exact committed head `f43ab37792f99ac01f5e44bd5309f7c60645df2f` for 896.5 seconds. Full tests, Windows package build, package artefacts, source/package parity, packaged smoke, performance, source policy, bulk cache, security, privacy/backup, legal terms and SBOM all passed. Only mandatory signing failed with the unchanged external `ETF_COCKPIT_RELEASE_SIGNING_KEY is not set` fingerprint; the gate was not weakened. Evidence: `C:\Users\thor2\AppData\Local\Temp\etf-ai-cockpit-b01-settings-full-f43ab37-20260722-0315`; manifest SHA-256 `367990C8E2610219CB2FE1FE209EBB266A246232944A3E0F270608BCDD9D50E9`; report SHA-256 `FD9D8302CA1ED0B7972CED8600CD77B339F61F8551F9DC0CCD7B9330D2E99CF0`; full-test-log SHA-256 `1EA12BEF613C865E03526134E811C8434ED6AF7CADC264BED68C80F0D9BEA085`.
- `VERIFIED` after rebuilding on merged base `3fc1f2073b9f5ba6aec2e28e812d985a1086165a`, a fresh 229-test affected collection passed 228 tests with one intentional skip. Ruff, compileall, canonical registry validation/freshness, programme-status freshness, completion-document freshness, exact-head transition guard and `git diff --check` all passed; no runtime artefacts remained in the worktree.
- `REVISE` PR `#458` initial CI passed Windows release, status-transition and supply-chain gates but failed the Linux full-test and packaged-smoke checks. The retained Linux evidence proves one current-feature cause: settings identity hashed raw `universe.yaml` bytes, so Git checkout CRLF/LF conversion changed the companion revision and rejected the shipped settings document. Evidence directory: `C:\Users\thor2\AppData\Local\Temp\etf-ai-cockpit-pr458-linux-failure-29855605404`; manifest SHA-256 `BC676181D9EAD854CA4A0432876A7F4797B80E3D639D983E0D2E7A19CA30602B`; report SHA-256 `E9A0F61590C508B76B2C532C4BB74B42CAC6329F488DA6A7B86886655488FB27`; full-test-log SHA-256 `F7B65D3643A710C42B3800F2193FCD2923F6B49846E4065496E1CC4C9F277C82`; package-smoke-log SHA-256 `1FDA7E6F88B8491DBC9E1DED993319E324573FC95BEB1B473568A0B1850FE026`.
- `VERIFIED` the LF/CRLF parity regression failed before repair and passes after canonical text-line normalization at `3b718a59c559c463333e904d79fefc65c320a3de`. Native and Linux-like companion trees now resolve revision `54eb00f2a9245e6fb1960ddb072c82a986b07e059d07ad1359f10da3fa9e0385`; 76 focused settings/control tests, all 52 UI tests, the exact offline smoke path, and the 229-test affected collection passed with one intentional skip. Ruff, compileall and diff check passed.
- `IN_PROGRESS` ISSUE-0037 was rebuilt without control-file reversal in isolated worktree `b01-settings-pr-20260722` from merged base `3fc1f2073b9f5ba6aec2e28e812d985a1086165a`. Its base refresh is frozen at `1e27dea38aaef1a1e95b1e0f8c740528197a5d7c`; reviewed settings implementation and control-test fixes are at `176bf794e784b1292fe15e6be7dafcea548ea8d0`; the cross-platform repair is at `3b718a59c559c463333e904d79fefc65c320a3de`. PR `#458` CI rerun and merge remain. ISSUE-0008 remains `implemented_initially` and ISSUE-0037 remains `planned` until their respective merged evidence and guard-compatible convergence exist; no premature transition is authorised.
- `BLOCKED` ISSUE-0080, ISSUE-0149 and ISSUE-0176 as recorded above.
- `VERIFIED` PR `#458` subsequently passed the status-transition guard, supply-chain scan, Linux release gate and Windows release gate on repaired head `13a34e9522605b07fccf4e6a8c083383aeeaa18a`, with the exact reviewed 51-file allowlist and no reviews. It merged as `3b159c25457c7376b7108999bd8a6c7bb13188fe`. Fresh post-merge product validation passed 43 settings/publication/UI/audit tests plus the exact offline smoke; the separate 16 B00 control failures were only the expected stale recorded base after the merge.
- `VERIFIED` the B01 control-guard amendment is isolated in `b01-guard-transition-20260722` from exact `origin/main` `3b159c25457c7376b7108999bd8a6c7bb13188fe`. Schema `1.2` adds `generation_base_and_status_transitions` while preserving schema-`1.1` behaviour: exact registry/source hashes, empty added/removed IDs, canonical transition-graph validation, immutable unrelated records and top-level policy, append-only typed acceptance evidence, changed full-SHA `verified_commit`, and a no-downgrade gate remain mandatory.
- `VERIFIED` the new schema-`1.2` tests failed before implementation and the final complete transition-guard suite passes 37 tests. Ruff, compileall and `git diff --check` pass. The current amendment PR intentionally performs only a deterministic base refresh with an empty transition allowlist under schema `1.1`; all 197 records and status counts remain unchanged and the generated GitHub projection contains zero actions. No programme-status transition is authorised until the amendment itself is reviewed, merged and revalidated from its merged SHA.
- `VERIFIED` the first independent review rejected the draft because its positive fixture omitted canonical `transition_history`, `status_transition` and `verified_date` deltas, and because a fabricated 40-hex `verified_commit` could pass. Both defects were reproduced before repair. Schema `1.2` now reconstructs and requires the exact canonical writer delta, rejects dependency-evidence changes, and requires each evidence commit to exist and be ancestral to the reviewed generation base. Canonical-writer and temporary-Git ancestry/divergence/nonexistent-object regressions pass; the full combined control set passes 100 tests. Independent re-review passed with no blocking or non-blocking findings; only normal committed-PR platform CI uncertainty remains.
- `IN_PROGRESS` after that merge, the first guarded convergence will use schema `1.2` to advance only ISSUE-0008 `implemented_initially -> integrated` and ISSUE-0037 `planned -> in_progress`, each with append-only reviewed evidence and its merged verified SHA. ISSUE-0037 must then follow the canonical graph through `implemented_initially` before `integrated`; no state jump is permitted.
- `VERIFIED` PR `#459` merged the reviewed schema-`1.2` amendment as `b25bf6b53f5024df6ae4e298f64ade08d4c65d46`; Linux release, Windows release, status-transition and supply-chain checks all passed on exact head `dbf0c3063657d90ccba555b0768d8b3d16cdafad` with the exact 36-file allowlist and no reviews.
- `REVISE` the first real canonical writer -> registry generator -> schema-`1.2` convergence failed closed: canonical control state retains `transition_history` and `status_transition`, while the generated registry intentionally projects only `programme_status`, `verified_commit`, `verified_date` and `acceptance_evidence`. The positive unit fixture had copied the control record directly and therefore validated the wrong layer. No transition branch was committed or published.
- `VERIFIED` the isolated projection repair now validates the exact generated registry delta, independently validates the canonical control state against `origin/main`, retains verified-commit existence/ancestry checks, and adds reviewed-date projection coverage. The corrected 38-test guard suite passes, and the repaired guard passes the suspended real two-transition convergence worktree end to end. Independent re-review passed with no findings. The repair PR remains base-only with 197/197 records and counts unchanged and a zero-action GitHub projection; only exact-head protected CI remains required.
- `VERIFIED` PR `#460` merged the projection repair as `a5dee7579e2ca5ae1e40a7152c798749d428d36b`. Status-transition, supply-chain and Linux release checks passed immediately. The first Windows run failed only the documented unrelated atomic-transaction permission flake (`PermissionError(13, Access is denied)`); every other Windows release node passed. The single permitted unchanged-head retry passed, after which exact head/base, the 35-file allowlist and zero reviews were reverified before merge.
- `IN_PROGRESS` the first real status convergence was recreated from merged repair base `a5dee7579e2ca5ae1e40a7152c798749d428d36b`. It changes exactly ISSUE-0008 `implemented_initially -> integrated` with verified commit `47bdc95b6f8360b454f3bfa707226af8c500ad53` and ISSUE-0037 `planned -> in_progress` with verified commit `3b159c25457c7376b7108999bd8a6c7bb13188fe`; all 197 counts remain unchanged and the read-only GitHub plan contains exactly those two status updates.
- `VERIFIED` independent review passed the recreated convergence with no findings: both evidence commits exist and are ancestors of the reviewed base; each control record contains one exact append-only canonical event; only the two corresponding generated registry records change; policy and `execution_allowed=false` are unchanged; the schema-`1.2` manifest, generated status/documents and two-action safe-sync sidecar are exact. Protected CI and later checksum-reviewed GitHub apply/readback remain.
