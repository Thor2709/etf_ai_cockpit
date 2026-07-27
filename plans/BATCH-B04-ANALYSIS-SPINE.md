# B04 Analysis Spine

## Authority and outcome

Base revision: `b8eb6b4967d5655ed4e528ee9cb222690a424d57`
(`origin/main`). `PLAN_step3.md` is absent from both the working tree and
`origin/main`; it is not reconstructed. B03 is complete through integrated
ISSUE-0156. This batch follows the final-release specification and canonical
registry for ISSUE-0074, ISSUE-0098–ISSUE-0109 as applicable, ISSUE-0112,
ISSUE-0123, ISSUE-0157, ISSUE-0172 and ISSUE-0174.

The batch outcome is one local-first, point-in-time multi-asset analysis,
forecast, peer, benchmark and risk-profile contract. Shared schemas are frozen
before downstream consumers. Missing, stale, conflicted or unsupported
evidence remains explicit. Adjusted/total-return prices are required for
returns, risk gates remain authoritative and `execution_allowed=false`.

## Sequence

1. Review and record ISSUE-0098's existing ISSUE-0074 score and ISSUE-0083
   classification interfaces without overstating incomplete contracts.
2. Advance ISSUE-0098 through separate guarded readiness and implementation
   transitions.
3. Implement the smallest usable point-in-time peer-cohort and sector-adapter
   framework with deterministic fallback, support, exclusions, versioning,
   read-only UI lineage and tests.
4. Recompute the canonical graph after ISSUE-0098 integration and select the
   next dependency-valid B04 issue. Do not pull blocked downstream work
   forward.

## Active prerequisite

`IN_PROGRESS` review only ISSUE-0098→ISSUE-0074. The merged canonical score-v3
interface supplies typed asset-specific components, configured weights,
coverage/conflict handling, deterministic formula/source hashes and separated
score outputs. It does not yet supply ISSUE-0098's point-in-time peer membership,
effective sample size, robust statistics, hierarchical fallback, bootstrap
intervals or reusable peer stores. Record the edge as `partial_interface`;
leave ISSUE-0098 planned and ISSUE-0083 unresolved.

This step changes no product code, status, dependency list, acceptance
criterion, policy or authority. It requires the exact dependency-edge guard,
registry/status/document freshness, focused canonical-score and control tests,
supply-chain validation, diff hygiene and a zero-action GitHub projection.

The proposed 197-record registry has SHA-256
`ecc1b95ae86fcf89b21c8b67b3c64135dc1e597f5f6ec77826c8d3a11be37aa2`.
The live GitHub projection is the zero-action semantic plan
`f51ed48ed324a3d4fbe89da65cacb8285ebd5fb59bc222efe542f4c8f8cb7dec`.

`VERIFIED` PR #538 merged the first edge checkpoint as
`4e5540b982fc370a2312d64f78a454ef652ce940` from reviewed head
`aff8a4b947d9033eb1151a7d06ce0c039b6fdde8`. Status guard run
`30262850204` and supply-chain run `30262850140` passed; the redundant
evidence-only release run was cancelled. The post-merge GitHub readback
remained the zero-action plan
`f51ed48ed324a3d4fbe89da65cacb8285ebd5fb59bc222efe542f4c8f8cb7dec`.

`IN_PROGRESS` the second readiness review records only
ISSUE-0098→ISSUE-0083 as `complete`. The merged classification contract
provides point-in-time sector, industry, business-model and country/currency
context; confidence, alternatives and deterministic fallback; version and
score-invalidation tokens; immutable replay; and fail-closed sector-adapter
routing. ISSUE-0098 still owns cohort membership and peer statistics.

ISSUE-0098 remains planned with all declared dependency interfaces now
reviewed. The proposed registry SHA-256 is
`4935b3dc3ad8645251a31c0629eeaa9afa528607a669c610cccfba687cc7246b`;
the live GitHub projection remains the zero-action plan
`f51ed48ed324a3d4fbe89da65cacb8285ebd5fb59bc222efe542f4c8f8cb7dec`.

`VERIFIED` PR #539 merged the classification edge checkpoint as
`ec721a5576c3ce3a26690d906b256d94106d5db0` from reviewed head
`05831cba6b617ac4dd50936d647807422640d81e`. Status guard run
`30263254026` and supply-chain run `30263254064` passed; the redundant
evidence-only release run was cancelled. Post-merge GitHub readback remained
zero action.

`IN_PROGRESS` the separate guarded transition advances only ISSUE-0098
`planned -> ready`. Both declared dependency interfaces are resolved while
the score interface's limitations remain explicit. The 197-record registry
has proposed SHA-256
`8d21b82252ad512ec05b1135b18e5e281bb8a4f2e4dffdcccf3964a3ede2d494`.
The reviewed GitHub plan contains exactly one Programme-status update for
open issue #238 with semantic SHA-256
`68cef5b7a35b34bda5043b84ba2c3782d218a5b8a9b52b8e7f1b40b7cab4aaf2`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` readiness PR #540 merged ISSUE-0098 as ready in
`b3dd4decbef105ef8eff44abc5a97820507ea64a` from reviewed head
`5dcfddff00b74b70998759e790d1a8334018d60a`. Status guard run
`30263595362` and supply-chain run `30263595352` passed; the redundant release
run was cancelled. Checksum-approved GitHub plan
`68cef5b7a35b34bda5043b84ba2c3782d218a5b8a9b52b8e7f1b40b7cab4aaf2`
applied only #238 and zero-action readback
`df90dd12bae8df17922cc4b913e26669ac3524548f6057c52dba5338d0349456`
verified convergence.

`IN_PROGRESS` the separate implementation hand-off advances only ISSUE-0098
`ready -> in_progress`. The smallest usable product is a versioned local
peer-cohort/metric contract using frozen point-in-time classification and
universe evidence: deterministic leaf-to-parent fallback, effective sample
size, median/MAD, weighted empirical CDF, winsorisation, hierarchical
shrinkage, seeded bootstrap intervals, explicit members/exclusions/support,
sector-adapter routing and read-only Instrument Detail lineage.

Excluded: downstream sector-family implementations, forecasts, expected
returns, recommendations, optimiser/order work, remote providers and live
execution. The proposed registry SHA-256 is
`6f7fc25da846cec6c6ee23c131bf77f918d36f17b27e0ee0f24751699394178c`;
the reviewed one-update GitHub plan is
`af636dec29f5aa00750f1a09bb1d30c46a3a2f08cd71cfec37b98eafb6a7426a`.

`BLOCKED REVIEW CHECKPOINT` the initial ISSUE-0098 implementation and its one
authorised focused correction were not accepted or committed. On unchanged
base `3beeb75071d5c063d870c42e7f07a66a9860b7b1`, a historical cohort admitted a
`PeerObservation` whose `InstrumentContextV2.decision_time` was in the future
because eligibility checked only the observation timestamps. A second
reproduction showed `PeerCohortStore.append` accepting an arbitrary
`result_hash` that did not authenticate the canonical projection payload.
These are point-in-time and immutable-audit contract failures. The branch
remains unmerged; `execution_allowed=false`. Any later authorised attempt must
first add failing tests for both reproductions and must not reuse the rejected
implementation wholesale.

`AUTHORIZED REPAIR` on 2026-07-27 the user explicitly authorised one new
bounded repair attempt in this existing worktree, retaining the reviewed
ISSUE-0098 implementation. The only product blockers in scope are exact-cutoff
ISSUE-0083 classification resolution/validation and canonical peer-result
hash verification before write and on replay. One Sol-low worker may implement
the repair and receive at most one focused correction. No other issue or
downstream analysis work is authorised; `execution_allowed=false`.

`REVIEWED REPAIR CHECKPOINT` the worker implementation plus its one focused
correction are accepted for release validation. The data boundary now resolves
target and candidate ISSUE-0083 contexts at exact UTC cut-offs; analysis
excludes invalid candidate lineage and fails closed for an invalid target.
Canonical schema, frozen-universe, formula, hierarchy, statistical, warning
and authority fields participate in the result hash. The store validates
before creation and independently reconstructs and recalculates replay.
Orchestrator reproductions passed for future-context exclusion, historical
revision invariance, forged-hash rejection without storage residue and
rehashed SQLite tamper rejection. Focused evidence is 52 peer/classification/
architecture tests, 85 Instrument Detail tests and 9 architecture/document
tests, plus Ruff, compileall and diff hygiene. Protected Linux and Windows
release gates and supply-chain validation remain required before merge.

`IN_PROGRESS` product PR #542 merged the reviewed ISSUE-0098 peer-cohort tree
as `fc734201b138d3f24fa68d8c07422322506d6fc5`. Protected Linux and Windows
evidence passed package build, artefacts, source/package parity, packaged
smoke, performance and policy checks. A deterministic generation-base refresh
left only the documented B03 simple-score baseline on both platforms; no
ISSUE-0098 or changed-path test failed. Supply-chain validation passed and
`execution_allowed=false`.

The separate guarded convergence advances only ISSUE-0098
`in_progress -> implemented_initially`. The proposed 197-record registry has
SHA-256 `c77d4b5e306f6d50425be783751cfd6ecf361d40bd42da31dd5a4f6e9aa11f76`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #238 with semantic SHA-256
`e9d4d3eee2d726a2614d775c8ac2f7cc4240fa36b9be82906bc6472f290b51be`.
No dependency, scope, acceptance, policy or authority change is included.

`VERIFIED` product PR #548 merged ISSUE-0099 as
`55c41b57cc222ce365b27adcf9dadbb0742aeca3` from exact reviewed head
`a8e07c3a2c20239b8b11fa8c65e6313efcf29e2a`. The financial-institution
adapter now preserves typed bank, insurer and diversified-financial metrics,
units, direction, period, reporting standard, jurisdiction, source authority,
point-in-time classification lineage, deterministic stresses and explicit
missing-data authority caps. Instrument Detail exposes verified read-only
evidence and `execution_allowed=false`.

Protected release run `30314202998` passed Linux and Windows package build,
artefact, source/package parity, packaged smoke, performance, policy,
security, privacy, legal and SBOM checks. Both full suites retained only the
exact authorised B03 simple-score invalidation node and fingerprint; no
ISSUE-0099 or changed-path test failed. Final-head status guard
`30315386005` and supply-chain run `30315386015` passed; redundant
manifest-only release run `30315386073` was cancelled.

`IN_PROGRESS` the separate guarded convergence advances only ISSUE-0099
`in_progress -> implemented_initially`. The proposed 197-record registry has
SHA-256 `fe2ea7354395c6246853131a6dfb2f2abc97d729b43fe6f22fb743520f7609f8`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #239 with semantic SHA-256
`64f05b2fc8b4d6fe319fabe16871a0289add24c9eff9197e93a7f7aecea7c9a6`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` implemented-initially PR #543 merged as
`a01c663cd10bc13057175bd128456108bfceb0c4` from reviewed head
`01f95db5f1211ffc436e01458f78d8d0e63d123c`. Status guard run
`30276147784` and supply-chain run `30276148150` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`e9d4d3eee2d726a2614d775c8ac2f7cc4240fa36b9be82906bc6472f290b51be`
applied only #238, and zero-action readback
`bb68cd2ac53599bb3a26b7c619f35174b492cf707ed2d21376e32604c504ba0a`
verified convergence.

`IN_PROGRESS` the final separate convergence advances only ISSUE-0098
`implemented_initially -> integrated`. The proposed 197-record registry has
SHA-256 `3c484a44ce57f2b5b9a04e8011a5691e67e90c5e31b8d8b768873a5d1b1e7e10`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #238 with semantic SHA-256
`04c08b15461989be76539fc401ea00c99c199ab79a5c1ea2a6379eceebb05b74`.
No dependency, scope, acceptance, policy or authority change is included;
`execution_allowed=false`.

`VERIFIED` integrated PR #544 merged ISSUE-0098 as
`389278a6a30e5fc96ce96d2c796de2f075bb3b60` from reviewed head
`0d44615bc0cf7a95e24d3228ad9782b0a3947db6`. Status guard run
`30276601498` and supply-chain run `30276601199` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`04c08b15461989be76539fc401ea00c99c199ab79a5c1ea2a6379eceebb05b74`
applied only #238, and zero-action readback
`e9e91f058561411005a408eae8f1e1508d02c24c8b2427cfc08b5bc4ed6b6c4a`
verified final ISSUE-0098 convergence.

`IN_PROGRESS` the next dependency-valid B04 prerequisite reviews only
ISSUE-0099→ISSUE-0098. The integrated `peer-cohort.v1` contract supplies
versioned sector-adapter registration and applicability lineage,
classification-gated routing, exact-cutoff leaf-to-parent cohorts, explicit
exclusions/support, robust peer statistics and verified deterministic replay.
ISSUE-0099 retains all bank, insurer and diversified-financial formulas,
regulatory evidence, stress models, country variants and UI rationale.

Record the edge as `complete` while ISSUE-0099 remains planned. The proposed
197-record registry has SHA-256
`1a65285002021849652bd57a8c89d2e5e0285bbaa8717e6279b21ce2df627a79`;
the live GitHub projection remains the zero-action semantic plan
`e9e91f058561411005a408eae8f1e1508d02c24c8b2427cfc08b5bc4ed6b6c4a`.
No product, status, dependency-list, scope, acceptance, policy or authority
change is included; `execution_allowed=false`.

`VERIFIED` peer-framework edge PR #545 merged as
`d149defcce3398c3cc463bc0d1cdbdf9a1e7cb4b` from reviewed head
`9e2a59e5178f1634500519b82e59cfb0b004ecdd`. Status guard run
`30310958193` and supply-chain run `30310958226` passed; the redundant
evidence-only release run was cancelled. The live GitHub projection remained
the zero-action plan
`e9e91f058561411005a408eae8f1e1508d02c24c8b2427cfc08b5bc4ed6b6c4a`.

`IN_PROGRESS` the separate guarded readiness transition advances only
ISSUE-0099 `planned -> ready`. Its sole blocking dependency interface is
reviewed complete while financial formulas, regulatory evidence, stress
models, country variants and UI rationale remain unimplemented ISSUE-0099
scope. The proposed 197-record registry has SHA-256
`971a2df0cbe9d1d49b189d9fe19ec1afb7768f989f1f588016d1ad2b6e132ea0`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #239 with semantic SHA-256
`d66bd2acc35adf35bb4b0b33678d2dda5ba31106df7d1d8f83c588c672b4c2bd`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` readiness PR #546 merged as
`b1f2c065b4556b7b5200b70e05ef0aa2940bb60e` from reviewed head
`12cfd39eb22c415a488692d8d18b15e1e870cf61`. Status guard run
`30311207538` and supply-chain run `30311207583` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`d66bd2acc35adf35bb4b0b33678d2dda5ba31106df7d1d8f83c588c672b4c2bd`
applied only #239, and zero-action readback
`86cb76eb492a78ba911634f94271ef4005f012e15ce14743676437e67ffa114d`
verified convergence.

`IN_PROGRESS` the bounded ISSUE-0099 implementation handoff advances only
`ready -> in_progress`. The smallest usable outcome is a typed
financial-institution adapter framework integrated through the existing
peer-cohort registry and Instrument Detail facade. It covers bank capital,
funding, asset-quality and profitability evidence; insurer underwriting,
solvency, reserve and investment evidence; and diversified-financial funding,
credit-loss, capital and revenue-mix evidence. Every metric preserves unit,
direction, period, reporting standard, jurisdiction, source and point-in-time
lineage. Missing evidence remains explicit, lowers confidence and prevents
high-authority labels. Deterministic credit-loss, funding and market shocks
remain read-only and `execution_allowed=false`.

The implementation excludes remote providers, paid dependencies, semantically
invalid generic valuation or industrial leverage fallbacks, other sector
children, forecasts, expected returns, recommendations, optimisation, order
transmission and broker writes. The proposed 197-record registry has SHA-256
`814aafe0626e0f1e52c82be7a8702e4797156a5eda50bad98d51e498207da3ba`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #239 with semantic SHA-256
`8f64d4225a23e54723f129c5a0d68893da9ebc8b7ad3e0e6c06c1285e61f0749`.
No dependency, scope, acceptance, policy or authority change is included.
