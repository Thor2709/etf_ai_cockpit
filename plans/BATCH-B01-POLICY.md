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
- `IN_PROGRESS` root release of the reviewed ISSUE-0008 checkpoint through PR validation and merge; ISSUE-0037 remains serially next.
- `PENDING` ISSUE-0037 typed settings contract and implementation.
- `BLOCKED` ISSUE-0080, ISSUE-0149 and ISSUE-0176 as recorded above.
