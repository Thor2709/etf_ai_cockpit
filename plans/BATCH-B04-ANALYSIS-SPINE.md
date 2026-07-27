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
