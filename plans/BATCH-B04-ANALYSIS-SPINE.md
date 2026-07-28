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

`VERIFIED` implemented-initially PR #549 merged ISSUE-0099 as
`b41a43dccf28512eaee19618341db4b3f34c6d5c` from reviewed head
`6f6c9950ddc0ed6f69c607bc731b84873817f094`. Status guard run
`30315660329` and supply-chain run `30315660332` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`64f05b2fc8b4d6fe319fabe16871a0289add24c9eff9197e93a7f7aecea7c9a6`
applied only #239, and zero-action readback
`3fc8ff2c316b28e94671bb0521b3eed4310955d0c856b3edaede3fd625113227`
verified convergence.

`IN_PROGRESS` the final separate convergence advances only ISSUE-0099
`implemented_initially -> integrated`. The proposed 197-record registry has
SHA-256 `9cfe0e13df83f6fc65ac539721378d5efaa47d74a266fb3cec5a3bf6166a9766`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #239 with semantic SHA-256
`f9e546349595ee9df28e47585e027f790dd0b5b4bf9f3ad1fb13e1eddcaee978`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` integrated PR #550 merged ISSUE-0099 as
`ecbcfbf8b5706b19996d720a1aeaf945608e7dc9` from reviewed head
`88a4084987c334060bdbd1ccdcc40d6d958a51e1`. Status guard run
`30316036205` and supply-chain run `30316036204` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`f9e546349595ee9df28e47585e027f790dd0b5b4bf9f3ad1fb13e1eddcaee978`
applied only #239, and zero-action readback
`79c8c3ca0be0675b4718247c8f16767a85ccc7a744a6899a4c456350b2a14fc6`
verified final ISSUE-0099 convergence.

`IN_PROGRESS` the next dependency-valid B04 prerequisite reviews only
ISSUE-0100→ISSUE-0098. The integrated `peer-cohort.v1` contract supplies
versioned sector-adapter registration and metric-applicability lineage,
classification-gated stock-only routing, exact-cutoff leaf-to-parent cohorts,
explicit exclusions/support, robust peer statistics and verified replay.
ISSUE-0100 retains all REIT, utility and infrastructure formulas, source
evidence, rate/inflation/refinancing stresses and Real Assets UI rationale.

Record the edge as `complete` while ISSUE-0100 remains planned. The proposed
197-record registry has SHA-256
`fd09ae9dab75686c6a44b4d2b87364ad03a2140b0309df0dd5b517888473becf`;
the live GitHub projection remains the zero-action semantic plan
`79c8c3ca0be0675b4718247c8f16767a85ccc7a744a6899a4c456350b2a14fc6`.
No product, status, dependency-list, scope, acceptance, policy or authority
change is included; `execution_allowed=false`.

`VERIFIED` peer-framework edge PR #551 merged as
`65d35e21c397aaca77483cacc88babebdffd0014` from reviewed head
`27b82c5c714861d8a03165c8560ab15f08e0b653`. Status guard run
`30316338360` and supply-chain run `30316338359` passed; the redundant
evidence-only release run was cancelled. The live GitHub projection remained
the zero-action plan
`79c8c3ca0be0675b4718247c8f16767a85ccc7a744a6899a4c456350b2a14fc6`.

`IN_PROGRESS` the separate guarded readiness transition advances only
ISSUE-0100 `planned -> ready`. Its sole blocking dependency interface is
reviewed complete while all REIT, utility and infrastructure formulas, source
evidence, rate/inflation/refinancing stresses and Real Assets UI rationale
remain unimplemented ISSUE-0100 scope. The proposed 197-record registry has
SHA-256 `e0b645c78be13d62ab62fe2f5a4093835bc288895a28f7513fe7fd761929bebd`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #240 with semantic SHA-256
`d826061bf3c605d2d282fdafcfb623c9fa06a788845f079c22d0da78cbda792e`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` readiness PR #552 merged as
`1c0a4d8a027bbce144dddaafc12c2c329a857675` from reviewed head
`560dbf6d0af199eba1688e39fe514691ec0a9f91`. Status guard run
`30316550340` and supply-chain run `30316550327` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`d826061bf3c605d2d282fdafcfb623c9fa06a788845f079c22d0da78cbda792e`
applied only #240, and zero-action readback
`e9853f722be8f15bad77559ad8c770e858c98b7433e67305c94c97ab59d3c539`
verified convergence.

`IN_PROGRESS` the bounded ISSUE-0100 implementation handoff advances only
`ready -> in_progress`. The smallest usable outcome is a typed local
real-assets adapter integrated through the existing peer-cohort registry and
Instrument Detail facade. It covers REIT FFO/AFFO, occupancy, lease maturity,
LTV, interest cover and explicit NAV sensitivity; utility/infrastructure RAB,
allowed returns, capex funding, sector-specific leverage/coverage and
tariff/regulatory exposure. Maintenance and expansion capex assumptions,
statement reconciliation, country/business variants, parent fallback, source
lineage and deterministic rate/inflation/refinancing stresses must stay
explicit. Missing reliable NAV or RAB inputs remain unavailable.

The implementation excludes remote providers, paid dependencies, generic P/E
or industrial leverage/FCF fallbacks, other sector children, forecasts,
expected returns, recommendations, optimisation, order transmission and
broker writes. The proposed 197-record registry has SHA-256
`515c155d4c3eb480d756bc50887fce53dddffce9f97cf6d4871306088145c543`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #240 with semantic SHA-256
`a9067520a0e16a78bd7b62ea3dfb1dee22976bdc2aace45da921e8f236c76d59`.
No dependency, scope, acceptance, policy or authority change is included;
`execution_allowed=false`.

`VERIFIED` implementation-handoff PR #553 merged as
`d5851534bb41f85d31ddc6e6bba15b7d2798e73c` from reviewed head
`380b47ede525959b36832ada09dcac21ad3d437e`. Status guard run
`30316774523` and supply-chain run `30316774480` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`a9067520a0e16a78bd7b62ea3dfb1dee22976bdc2aace45da921e8f236c76d59`
applied only #240, and zero-action readback
`e8deabbf128bbe36a24da63f2d21f24be74a95e9594aceac014074eddeb1701d`
verified convergence.

`REVIEWED PRODUCT CHECKPOINT` the bounded ISSUE-0100 implementation and its
one focused correction are accepted for release validation. The typed
real-assets adapter preserves sector-specific units, directions, definitions,
period, reporting standard, jurisdiction, source authority, country/business
variant, parent fallback and point-in-time lineage. REIT FFO/AFFO derivation
and reconciliation keep maintenance and expansion capex distinct; occupancy,
lease maturity, LTV, NAV, regulated-asset-base, allowed-return, capex-funding
and tariff/regulatory evidence remain explicit. Missing or unreliable NAV/RAB
is unavailable and status-limiting. Rate, inflation, refinancing and NAV
sensitivity stresses are deterministic, and forged projections fail closed.
Instrument Detail exposes only verified read-only evidence with
`execution_allowed=false`.

Independent integration evidence passed 106 domain, classification, peer,
financial-adapter, statement, fundamentals and architecture checks; 119 stock
research and Instrument Detail checks; and 6 accessibility/button contract
checks, plus Ruff, compileall and diff hygiene. Protected Linux and Windows
release gates and supply-chain validation remain required before merge.

`IN_PROGRESS` product PR #554 merged ISSUE-0100 as
`887b08dce427cadf05e34cccac02111c08b82495` from exact reviewed head
`96f6101c7f15f7d7382e64332e439f5b4bbc497e`. Protected release run
`30318189597` passed Linux and Windows package build, artefact,
source/package parity, packaged smoke, performance, policy, security, privacy,
legal and SBOM checks. Both full suites retained only the exact authorised
B03 simple-score invalidation node and `pd.notna(None)` fingerprint from
protected run `30314202998`; no ISSUE-0100 or changed-path test failed.
Status guard run `30318189573` and supply-chain run `30318189600` passed;
`execution_allowed=false`.

The separate guarded convergence advances only ISSUE-0100
`in_progress -> implemented_initially`. The proposed 197-record registry has
SHA-256 `491c791a1abda7d43d55c05ddf3b6f86e08629da188aeb05682e5d14d12e6e6a`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #240 with semantic SHA-256
`f920f83ebc49cbd50126b42d67c536263357c4c5f627178f24b42fbfc3d34d57`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` implemented-initially PR #555 merged ISSUE-0100 as
`918a4995084c79cbc41b5c8b363625ef6a7db0eb` from reviewed head
`9ac1e5c3baa4da3127e6d1d3f3f0dc2f7a709094`. Status guard run
`30319740434` and supply-chain run `30319740471` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`f920f83ebc49cbd50126b42d67c536263357c4c5f627178f24b42fbfc3d34d57`
applied only #240, and zero-action readback
`0146929cb4be49f4de90fa6545ad294f0eda858a369c61ba5e4d788fc7b0263f`
verified convergence.

`IN_PROGRESS` the final separate convergence advances only ISSUE-0100
`implemented_initially -> integrated`. The proposed 197-record registry has
SHA-256 `ba2827fa2a21ebb7cf76d735878dd1700708399921048ab254f9607677e3bee2`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #240 with semantic SHA-256
`55a9b16f22035841235d6de82556e85f157625d6164a00874de2b83c4c418dfc`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` integrated PR #556 merged ISSUE-0100 as
`e7fd1621ac857797264ab95667b5f09a690b7a34` from reviewed head
`7e09a9e33dc1a6bcb3db7375fae79defcac9ec42`. Status guard run
`30319962532` and supply-chain run `30319962505` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`55a9b16f22035841235d6de82556e85f157625d6164a00874de2b83c4c418dfc`
applied only #240, and zero-action readback
`39f9947bc1e6a43934ab0ae69e748a13c85b63fbfaa0b33571b0b0144f104475`
verified final ISSUE-0100 convergence.

`IN_PROGRESS` the next dependency-valid B04 prerequisite reviews only
ISSUE-0101→ISSUE-0098. The integrated `peer-cohort.v1` contract supplies
versioned sector-adapter registration and metric-applicability lineage,
classification-gated stock-only routing, exact-cutoff leaf-to-parent cohorts,
explicit exclusions/support, robust peer statistics and verified replay.
ISSUE-0101 retains all energy, materials and industrial formulas, cycle
history, commodity/input scenarios, operational source evidence and Cyclicals
UI rationale.

Record the edge as `complete` while ISSUE-0101 remains planned. The proposed
197-record registry has SHA-256
`b3b4102430547c0f3cd6b0a4baf18f4c26d2fabe8ac77a2850ed30e95a624b31`;
the live GitHub projection remains the zero-action semantic plan
`39f9947bc1e6a43934ab0ae69e748a13c85b63fbfaa0b33571b0b0144f104475`.
No product, status, dependency-list, scope, acceptance, policy or authority
change is included; `execution_allowed=false`.

`VERIFIED` peer-framework edge PR #557 merged as
`4469b423e18cfb04a7150d38286645d06ea0af67` from reviewed head
`f4b7d74b8df3e2f461d533ca45db651ce16f7fea`. Status guard run
`30320222055` and supply-chain run `30320222112` passed; the redundant
evidence-only release run was cancelled. The live GitHub projection remained
the zero-action plan
`39f9947bc1e6a43934ab0ae69e748a13c85b63fbfaa0b33571b0b0144f104475`.

`IN_PROGRESS` the separate guarded readiness transition advances only
ISSUE-0101 `planned -> ready`. Its sole blocking dependency interface is
reviewed complete while energy, materials and industrial formulas,
operational source evidence, cycle-history requirements, commodity/input
scenarios and Cyclicals UI rationale remain unimplemented ISSUE-0101 scope.
The proposed 197-record registry has SHA-256
`f747b8bc045a1eafc41f59fef4bc402a3a3b0b0c4ad3639224b965b7747c3f57`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #241 with semantic SHA-256
`5ef2917c04a5a7568052d1a3a00585f2f2353d9f4609d7018db1830ae7a5078f`.
No product, dependency, scope, acceptance, policy or authority change is
included; `execution_allowed=false`.

`VERIFIED` readiness PR #558 merged ISSUE-0101 as
`a5acc69cc6ac0eb9cb7ec86509b98eec330e6537` from reviewed head
`c5d00b5c4c61983020ee48c84f7031f1d1a3418d`. Status guard run
`30320441635` and supply-chain run `30320441736` passed; the redundant
evidence-only release run was cancelled. Checksum-approved GitHub plan
`5ef2917c04a5a7568052d1a3a00585f2f2353d9f4609d7018db1830ae7a5078f`
applied only #241, and zero-action readback
`f8bf6a6a6bed3ef04cd8731ab920d8c04bd87192661dbe579ad6211dd8de239f`
verified convergence.

`IN_PROGRESS` the bounded ISSUE-0101 implementation handoff advances only
`ready -> in_progress`. The smallest usable outcome is one local typed
cyclical adapter family for energy, materials/mining and
non-infrastructure industrials, integrated through the existing peer-cohort
registry and Instrument Detail facade. It keeps spot and normalised margins
separate; requires source-linked production, cost, reserve/resource,
sustaining-capex, decommissioning, backlog, book-to-bill, utilisation,
working-capital and concentration evidence where applicable; reduces
confidence when distinct-cycle history is inadequate; and exposes
deterministic commodity-price, input-cost and demand/rate scenarios.

The implementation excludes persistence, remote commodity providers,
ISSUE-0115 stress-lab work, infrastructure routing, other sector children,
forecasts, expected returns, recommendations, optimisation, order
transmission and broker writes. The proposed 197-record registry has SHA-256
`3bd5be5e907352ea0d52b6b20404fca748ffcc1fa271e3c93b4305d03451af9e`.
The reviewed GitHub plan contains exactly one Programme-status update for open
issue #241 with semantic SHA-256
`9ced52643254b6df3aa223bebc70db6514d8df9c220d139f95f2418d2c686635`.
No dependency, scope, acceptance, policy or authority change is included;
`execution_allowed=false`.

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

`IN_PROGRESS` the next dependency-valid B04 prerequisite review updates only
ISSUE-0106→ISSUE-0128 from `unresolved` to `complete`. The consumer-specific
contract is the immutable `CostEstimate` and deterministic
`estimate_execution_cost` primitive with monotonic size/ADV impact, wider
uncertainty when microstructure evidence is missing, explicit stress/capacity
status, `execution_allowed=false`, and non-mutating realised-fill comparison.
Focused cost-model tests cover finite components, order/listing/session inputs,
size monotonicity and capacity, missing-data widening, fill immutability and
shared-model use.

ISSUE-0106 remains `implemented_initially`; status, acceptance, dependency
lists, policy and authority are unchanged. ISSUE-0128 retains its unresolved
ISSUE-0064 edge and broader low/base/high interval, liquidation, persistence,
FX, cross-module and paper/backtest scope.

`REVIEWED` shared release prerequisite for the preserved checkpoint queue:
the ISSUE-0083 classification-invalidation regression uses fixed market date
`2026-07-10`, which crossed the canonical ten-business-day freshness boundary
and now fails before exercising override invalidation. No durable waiver
authorises retention. The bounded worker changed only the fixture date to the
current local date, preserving every classification-invalidation assertion,
the production stale-data gate and `execution_allowed=false`. The exact
regression and 74 focused simple-score/classification tests pass with Ruff and
diff hygiene. Next action is a protected baseline-correction release before
serial ISSUE-0039, ISSUE-0026, ISSUE-0022 and ISSUE-0059 checkpoint release.

`VERIFIED` shared-prerequisite PR #563 merged as
`b906b405dab83cea623178014b090f0c0217b6c4` from exact reviewed head
`9275ba23e85e136e20d40ec77e0cfd1956dfd7e1`. Status guard, supply-chain,
and full Linux and Windows packaged release gates passed. The post-merge
classification-invalidation regression passes; production freshness policy,
canonical programme status and GitHub issue #223 remain unchanged, with
`execution_allowed=false`. `IN_PROGRESS` the separate deterministic
convergence refreshes only the generation base to the merge commit before
ISSUE-0039 release.

`MERGED` ISSUE-0039 release from fresh main
`b80bf9bda85559b5d82e74c7db0ef458bec544bd`. The independently approved
checkpoint `2c72ac3b2ad394dec9509e3d2f0fe9f7c8253252` changes only timing-tail
reading and focused performance-contract tests; benchmark evidence showed
approximately 1,182x p50 improvement. The transplanted product patch has the
same stable patch id, `166500812524cc02bf3f076a1b2897abb79a8ac1`, as the
approved checkpoint. Root adversarial review found no scope expansion; all 6
focused performance-contract tests pass with Ruff and diff hygiene. PR #565
passed status guard, supply-chain and full Linux and Windows packaged release
gates, then merged from exact head
`8fa82c29d13e8b70d3865b7c060fe600a2e8662b` as
`db554b1b1502224801a28677550b7ff7c7920657`. `IN_PROGRESS` the separate
deterministic convergence refreshes only the generation base to the merge
commit before ISSUE-0026 release. No status, dependency, financial
calculation, broker authority or `execution_allowed=false` change is
authorised.

`VERIFIED` ISSUE-0039 post-merge convergence PR #566 passed status guard and
supply-chain validation, then merged from exact head
`4f5e8865fa75d05f817bfc1bb199b4710c5ebf02` as
`3b790eaeb95345ce70d9d9f6b21f28a1acd8c88e`; the redundant packaged release
run was cancelled after the product head had passed both packaged platforms.

`MERGED` ISSUE-0026 release from fresh main
`3b790eaeb95345ce70d9d9f6b21f28a1acd8c88e`. The dependency-ready canonical
record has no blocking dependencies and remains `implemented_initially`.
The two-file macro-scenario transplant has checkpoint-identical blobs and the
same stable patch id, `3b6da12fa44db5172726c590013e33dcd51941d9`, as the
complete `43fbcfa..203d678` diff. Root adversarial review found period-first
vintage selection, explicit UTC availability cutoffs, same-revision
fail-closed handling, strict rehashed-payload verification and context-only
authority preserved without scope expansion. All 17 focused tests pass with
Ruff and diff hygiene. PR #567 passed status guard, supply-chain and full
Linux and Windows packaged release gates, then merged from exact head
`7d7593cb310b2c4b29e5cf6277d1e719deaedf6a` as
`5b7a0150b3b01f3ec6685c7c14e62ae3dac1b050`. `IN_PROGRESS` the separate
deterministic convergence refreshes only the generation base to the merge
commit before ISSUE-0022 review. No status, dependency, financial
calculation, broker authority or `execution_allowed=false` change is
authorised.

`VERIFIED` ISSUE-0026 post-merge convergence PR #568 passed status guard and
supply-chain validation, then merged from exact head
`c906b599e3af40c824aff156159e6dd9bcba2db1` as
`a3ce6a04e3d023024b3c420c02b824401b21909b`; the redundant packaged release
run was cancelled after the product head had passed both packaged platforms.

`REVIEWED` ISSUE-0022 checkpoint
`df6181deae3815f4e8af6a55c1689d1f9222c57c` changes only five overlap
domain, application, UI and test files. Root adversarial review found
point-in-time holdings selection, explicit stale/missing/cycle/depth
fail-closed states, mapped-plus-unknown conservation, typed direct and
indirect contributors, canonical report hashing and
`execution_allowed=false` preserved. The transplanted patch has the same
stable patch id, `618d1383baa80e8ce514f70e9a54328fec4da858`, as the approved
checkpoint. All 27 focused and 188 affected tests passed with Ruff and diff
hygiene.

`REVISE` protected ISSUE-0022 PR #569 passed status guard, supply-chain and
the full Linux packaged gate, but the Windows full suite exposed an unrelated
non-deterministic baseline test boundary:
`test_real_esef_package_extracts_facts_and_retains_extensions` invoked the
optional bounded Arelle child validator while asserting the local extraction
contract. The failing result retained 285 parsed records but reported
`success=false`; the same fixture passed locally and on Linux. No durable
flake waiver authorises retention or an automatic retry. The bounded worker
changed only that test to make Arelle unavailable for its local-extraction
contract; extraction assertions and all dedicated Arelle diagnostic,
conformance, timeout and worker tests remain unchanged. The focused node
passed five consecutive runs and the full ESEF parser file passed 20/20 in
the worker environment with Ruff and diff hygiene. Root review approved the
one-test correction. Next action is a separate protected baseline-correction
release from fresh main before rebuilding ISSUE-0022; PR #569 remains
unmerged at exact head `7f2f0bf2dd004aff28566ae8946bc23957af32ee`.

`VERIFIED` shared ESEF test-isolation prerequisite PR #570 passed status
guard, supply-chain and full Linux and Windows packaged release gates, then
merged from exact reviewed head
`53e56f15750ab171b444acd2b7135f79c38cb7b8` as
`0c3a086d504d19751e8b1ab87784623c98d7f715`. The protected Windows run
verified the previously failing real-package local-extraction test. Dedicated
Arelle diagnostic, conformance, timeout and worker coverage remains intact.
`IN_PROGRESS` the separate deterministic convergence refreshes only the
generation base to the merge commit before ISSUE-0022 is rebuilt from fresh
main. PR #569 remains unchanged and unmerged.

`VERIFIED` the ESEF prerequisite post-merge convergence PR #571 passed status
guard and supply-chain validation, then merged from exact head
`b87b393232226c1c598bf74382bd2bac2fb6f71b` as
`f37115cae93a2892835a5aaba5da20fbe5a3c785`; the redundant packaged release
run was cancelled after PR #570 had passed both packaged platforms.

`REVIEWED` ISSUE-0022 was rebuilt from fresh main
`f37115cae93a2892835a5aaba5da20fbe5a3c785`. Exactly the five approved
overlap files are checkpoint-identical to
`df6181deae3815f4e8af6a55c1689d1f9222c57c`, and the stable patch id remains
`618d1383baa80e8ce514f70e9a54328fec4da858`. All 27 focused and 188 affected
tests pass with Ruff and diff hygiene. The rebuilt release includes the
merged deterministic ESEF baseline correction and does not modify ESEF,
status, dependency, financial calculation, broker authority or
`execution_allowed=false` semantics. Next action is the protected ISSUE-0022
release from this fresh base.

`MERGED` rebuilt ISSUE-0022 replacement PR #572 passed status guard,
supply-chain and full Linux and Windows packaged release gates, then merged
from exact head `80a6df8204c16d916d9ccc22663272d5709f02ae` as
`92dbc823129ae69ad2facdbf17309379e3f8cb43`. The Windows run verified the
previously failing ESEF regression and all packaged checks. The five-file
product patch retained stable patch id
`618d1383baa80e8ce514f70e9a54328fec4da858`. `IN_PROGRESS` the separate
deterministic convergence refreshes only the generation base to the merge
commit before ISSUE-0059 review. The failed first-attempt PR #569 remains
unchanged at exact head `7f2f0bf2dd004aff28566ae8946bc23957af32ee`
pending supersession cleanup.

`VERIFIED` ISSUE-0022 post-merge convergence PR #573 passed status guard and
supply-chain validation, then merged from exact head
`a131c5b6c891fe97a97c41a16d973e3a1f78c8df` as
`d4ce7a0e7f4467ab7b9f6ad65ee210e8dfb74c5f`; the duplicate packaged run was
cancelled after PR #572 had passed both packaged platforms. Superseded PR
#569 was closed with its exact head unchanged.

`REVISE` root adversarial review rejected preserved ISSUE-0059 checkpoint
`ff44de01814a6f29bd2abcf7521daea5c3901b2f` as submitted. Its chronology
validator permits `effective_at` before the return period ends and
`known_at` before `effective_at`, allowing point-in-time-invalid evidence.
It also subtracts portfolio and benchmark returns expressed in different
measurement currencies whenever an FX attribution row exists, although that
row cannot convert either top-level return. The bounded correction must
require `start_at < end_at <= effective_at <= known_at`, require matching
top-level return currencies, retain currency/FX contribution attribution in
the common reporting currency, and add adversarial tests. No wider redesign,
status/dependency change or execution authority is authorised.

`REVIEWED` the single bounded ISSUE-0059 correction cycle changed only the
checkpoint source and test files. The corrected model now fails closed unless
`start_at < end_at <= effective_at <= known_at` and unless portfolio and
benchmark returns share one measurement currency; currency/FX contribution
attribution remains available inside that common reporting currency. Direct
tests cover effective-before-end, known-before-effective and mixed currencies
even with FX evidence. The full corrected suite passes 22/22 with Ruff,
compile and diff hygiene. Root review found the correction complete without
scope expansion; corrected stable patch id is
`a77c528f936d319a8d2606a08812d10f629fda85`. Next action is a protected
ISSUE-0059 release from fresh main
`d4ce7a0e7f4467ab7b9f6ad65ee210e8dfb74c5f`; programme status remains
`implemented_initially` and `execution_allowed=false`.

`MERGED` corrected ISSUE-0059 PR #574 passed status guard, supply-chain and
full Linux and Windows packaged release gates, then merged from exact head
`37ef3fc9e18c682408ecc079fc65e85426ccee7e` as
`80c63200e733fada6ae2d76ac67feb776f281c38`. The protected gates verified
the corrected point-in-time chronology and common measurement-currency
contracts. `IN_PROGRESS` the separate deterministic convergence refreshes
only the generation base to the merge commit before the prepared ISSUE-0127
dependency-edge transitions. No status, dependency, broker authority or
`execution_allowed=false` change is included in this convergence.

`VERIFIED` ISSUE-0059 post-merge convergence PR #575 passed status guard and
supply-chain validation, then merged from exact head
`c5c3f4ba9a9990b37737fbd9b46093514f369ddb` as
`2ca0c37113da423c06e1fcda15110b028fef74dd`; the duplicate packaged run was
cancelled after PR #574 passed both packaged platforms.

`IN_PROGRESS` the first prepared ISSUE-0127 prerequisite review updates only
ISSUE-0127→ISSUE-0084 from `unresolved` to `complete`. The integrated
corporate-action and FX contract supplies append-only point-in-time action,
coverage and dated-FX stores; explicit action/cash-flow classifications;
source and revision lineage; replay without overwriting as-known history;
transaction/valuation FX attribution; discrepancy quarantine; and explicit
missing, stale and conflicted states. PR #482 passed the protected Linux and
Windows release gate, and its post-merge 50-test product/UI suite passed.

ISSUE-0127 remains `planned`; its separate ISSUE-0072 edge remains unresolved.
No product, status, dependency-list, scope, acceptance, policy, broker or
execution-authority change is included. There is no implementation blocker;
the next action is the single-edge guarded control refresh, deterministic
freshness validation, zero-action GitHub projection, and protected release
from fresh main with `execution_allowed=false`.

`VERIFIED` ISSUE-0127 dependency-edge PR #576 remained unchanged at reviewed
head `bdf759761e9e8aee33ee57197b888a9af1fb2e1d`, with base
`2ca0c37113da423c06e1fcda15110b028fef74dd`, no reviews or comments, and
successful status-guard, supply-chain, Linux and Windows protected checks. It
merged with expected-head protection as
`86502a99f9428c0f1c916bfea3974d41f7c3f2a1`.

`IN_PROGRESS` the current shared prerequisite is deterministic post-merge
convergence from that exact `main` SHA, followed by the bounded throughput
control and P0 remediation programme. ISSUE-0127 remains `planned`; its
ISSUE-0072 edge is the explicit unresolved product blocker. The next action is
to refresh only the canonical generation base, regenerate and prove
byte-fresh projections, require a zero-action GitHub readback, then install the
reviewed throughput controls without changing product scope, authority or
`execution_allowed=false`.

`VERIFIED` post-merge convergence PR #577 passed the exact status guard and
supply-chain scan, reused PR #576's unchanged-tree protected Linux/Windows
evidence, and merged from reviewed head
`b66722f33c308565a28c7fc0ab197b1c41da8b80` as
`4eaed9c8d15212d2c9dc69bad0301eecc03e0c74`. The fresh GitHub readback
remained zero action with semantic checksum
`6130b9437583b7a1ae9932b5c61667b9a4d9c7b9b5d9df7a91e8948b270e654c`.

`IN_PROGRESS` the bounded throughput control transaction allocates unused
ISSUE-0177–ISSUE-0181 as planned records and installs the reviewed plan and
delivery policy. Live generator review found the canonical control schema
rejects every new issue ID even when the status-guard migration manifest
authorises it. This shared programme-control prerequisite must first add
strict manifest-gated canonical extension support; it may not modify existing
records, statuses, dependencies, policies, authority or generated outputs.
The next action is one Sol-worker implementation with focused adversarial
tests, followed by orchestrator-owned record insertion, deterministic
generation and zero-action provider readback. ISSUE-0127 remains `planned`,
ISSUE-0072 remains unresolved and `execution_allowed=false`.

`REVIEWED` the manifest-gated canonical extension prerequisite and five-record
intake are complete in the control worktree. Unused ISSUE-0177–ISSUE-0181 are
allocated as `planned`; their package-defined dependencies, validation tiers,
scope, exclusions, acceptance criteria and rollback contracts are preserved.
All pre-existing 197 record identities, statuses, dependency evidence and
policies are unchanged. The reviewed GitHub dry run has semantic checksum
`c5b0ec62c214b864a45486de4342d8ad09bb115b164bacf67c8711fc3cd52f6c`
and contains exactly five creates plus seven derived downstream-link-only
updates. The next action is exact migration guard, focused generator/control
tests, deterministic second-pass proof and H-tier protected release because
programme-control generator code changed. No provider write occurs before the
control PR merges and its checksum is reverified.

`FAILED` PR #578 head `338996336761da1064366ee1fdc525bdd43fb9d7`
completed the Linux full suite with one freshness failure:
`github-inventory.json` had been rewritten by the final read-only GitHub dry
run after the last completion-document check. The protected test correctly
detected that the safe sync inventory shape was not the canonical
generator-owned inventory shape. No product or policy assertion failed. The
bounded correction is to regenerate that one canonical inventory, rerun its
offline freshness test and publish a new exact head; the obsolete head must
not merge.

`MERGED` corrected PR #578 at `a0e31fcfe84b343462931967571e6138117109e5`
after exact-head status, supply-chain and complete Linux/Windows release gates
passed. The reviewed GitHub plan checksum
`c5b0ec62c214b864a45486de4342d8ad09bb115b164bacf67c8711fc3cd52f6c`
was applied and verified, creating ISSUE-0177–ISSUE-0181 as issues #579–#583;
fresh readback is zero action at checksum
`f3813a75fab0a13ee936fe0e77c6350f78d8377c7f450b4983b9c1e9d8633883`.
`IN_PROGRESS` this evidence-only convergence refreshes the canonical
generation base and remote summary from fresh `origin/main` without changing
any issue semantics, status, dependency evidence, policy or product file.
The next action is exact guards and deterministic check mode, then merge the
small convergence transaction before ISSUE-0177 implementation begins.

`REVIEWED` convergence found that the initial extension generator required
the intake manifest to re-authorise already-canonical control extensions on
every later generation. That made the first zero-addition post-merge
convergence fail closed. The bounded fix distinguishes persisted extensions
in the checked-in registry from genuinely new IDs, while authoritative
control comparison still rejects removals and the migration manifest still
must exactly authorise every new ID. A post-intake adversarial test now proves
unrelated later manifests retain ISSUE-0177–ISSUE-0181 without
re-authorisation. Because programme-control code changed, the convergence
transaction is validation tier H and requires fresh Linux and Windows gates.

`MERGED` convergence PR #584 at
`ed3a7d0813aa930590398d93fc5fa0130f82ec19` after exact-head status,
supply-chain and complete Linux/Windows release gates passed. The registry
retains all 202 canonical records and the GitHub projection remains zero
action at checksum
`f3813a75fab0a13ee936fe0e77c6350f78d8377c7f450b4983b9c1e9d8633883`.

`IN_PROGRESS` ISSUE-0177 now owns the bounded validation-observability slice.
One Sol worker prepared the disjoint checkpoint; orchestrator review required
one correction so an isolated `report_root` cannot leak JUnit output into the
source worktree. The fresh-main transplant adds protected and affected JUnit,
slowest-100 setup/call/teardown durations, deterministic environment/cache/
retry fingerprints, stage and evidence paths, an authoritative pre-test
environment verifier and ignored runtime release artefacts. Focused
orchestrator validation passed 29 tests plus Ruff, MyPy, compileall and diff
hygiene. The canonical status advances only `planned → in_progress`; the
reviewed GitHub dry-run checksum
`db8fd5368dd3665d76a8310be7da0714aadb8c7d3b0c147d302b32852537ab3d`
contains exactly the corresponding ISSUE-0177 status update. A persisted
extension lifecycle defect discovered by this first transition is fixed with
a regression test: only genuinely new extension IDs are forced to begin
`planned`. The next action is exact guards, affected validation and complete
H-tier Linux/Windows evidence; no provider write occurs before merge.

`MERGED` ISSUE-0177 product PR #585 at
`f22abc22f5fee8f97b9ad5dc201374d0a434bfa8` after the exact-head status,
supply-chain and complete Linux/Windows release gates passed. Both platform
jobs reported 2,081 tests with zero failures or errors and retained JUnit,
slowest-100 timings, environment fingerprints, cache/retry and per-stage
evidence. The reviewed GitHub status plan was applied and verified; fresh
readback is zero action at checksum
`187dd923cdb7251e85f14b1d1ef43ff3903537b2572f5268982b182d74f692e8`.
`IN_PROGRESS` this evidence-only transaction advances only ISSUE-0177 from
`in_progress` to `implemented`, reusing the exact-tree protected evidence.
The next action is deterministic generation, exact E-tier guards and an
audited one-field GitHub status update; product code and
`execution_allowed=false` remain unchanged.

`MERGED` ISSUE-0177 implemented-status PR #586 at
`af666cf015c686a59f8fade3e3e07338a7a1b05c`; its exact status guard and
supply-chain scan passed, and the reviewed one-field GitHub plan was applied.
Fresh readback is zero action at checksum
`c352c885b330cf314285c61b427bd9b284c9860942cc6c5a219276c8ffb7d454`.
`IN_PROGRESS` this evidence-only transaction advances only ISSUE-0177 from
`implemented` to `integrated`, using the already successful PR #585
Linux/Windows protected evidence and the audited PR #586 status transaction.
The next action is deterministic generation, exact E-tier guards and the
corresponding one-field GitHub status update.

`MERGED` ISSUE-0177 integrated-status PR #587 at
`4d5f30e6ac19650030a61bec0e22a4eeb2fd57d9`; its exact status guard and
supply-chain scan passed, and the reviewed one-field GitHub plan was applied.
Fresh readback is zero action at checksum
`865d2c698dde37c3ca3731b4297b8b7d5556c045c42f893218ac79e8700c7087`.
`IN_PROGRESS` this evidence-only transaction updates exactly the
ISSUE-0178 → ISSUE-0177 dependency edge from `unresolved` to `complete`, using
the integrated ISSUE-0177 contract and exact protected evidence. The next
action is deterministic generation, schema-1.3 edge guard, E-tier checks and
an audited GitHub projection; the current dry run is already zero action
because dependency-edge evidence is canonical-only metadata.

`BLOCKED` ISSUE-0178 product PR #589 at exact product head
`b7d7df0c859f552cc841ded15e11459634793dc3` passed classifier, preflight,
supply-chain and the complete Linux protected release gate, but Windows
exposed a second pre-existing nondeterministic local ESEF extraction test
boundary. `test_parser_extracts_context_period_unit_and_decimals_and_deduplicates`
retained its parsed facts but reported `success=false` after invoking the
optional Arelle validator; the same node passed on Linux, and PR #570 already
isolated the identical local-extraction contract for the real-package test.
No retry is authorised. The next action is one bounded test-only baseline
prerequisite that disables optional Arelle validation for this local
extraction contract while retaining all dedicated Arelle diagnostic,
conformance, timeout and worker coverage. PR #589 remains unmerged and
unchanged until that prerequisite passes both packaged platforms.
