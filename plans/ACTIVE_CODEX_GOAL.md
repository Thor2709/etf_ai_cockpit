# Active Codex goal — complete the canonical programme through Phase 11

## Objective

Complete the canonical implementation programme issue by issue through
integration, GitHub convergence and Phase 11 certification. Select work only
from canonical readiness and implementation order, preserve
`execution_allowed=false`, and retain all financial, point-in-time, security,
privacy and audit safeguards.

The ISSUE-0177–0180 control-plane work is complete and frozen. Its complete
former active-goal record and chronology are archived in
`plans/archive/ATOMIC_FAST_PATH_ISSUE-0179-0180_2026-07-31.md`. Current delivery
mechanics are defined in `docs/product-completion/DELIVERY_WORKFLOW.md`.

## Current ISSUE-0104 product checkpoint

- Readiness PR #654 merged independently approved exact head
  `92523800cbbb83a307b9250867b495e722b5196c` as
  `fca004a529cccc3b0d4251fc600a897035298014`. Release run
  `30775791157` and guard `30775791108` passed. Ordered writer
  `30776243636` returned `applied_and_verified` with
  `zero_action_readback=true`; fresh generic exact-main convergence is
  zero-action at plan SHA
  `f60115aa8e2cf9655974050b590864231261317ad82250a89563a1e6bf27571e`.
- Canonical and GitHub issue #244 now agree on `ready`. Clean product lane
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0104_product`,
  branch `codex/issue0104-product-20260803`, starts empty at exact main
  `fca004a529cccc3b0d4251fc600a897035298014`.
- Bounded scope is ETF structural/legal/counterparty/lending/collateral
  analysis with per-field document/date/page/confidence, explicit unknown and
  conflict states, evidence-gated numeric stress and a Structure & Documents
  panel. It must not invent values or alpha, inherit stock credit metrics,
  enable execution, or broaden provider/parser authority.
- Product evidence commit
  `8a69a94919bf93d584778659ee01be030c020ce7` implements that bounded scope.
  The affected structure, scoring, parser, document, instrument-detail,
  backtest, recovery and publication suite passes 87 tests with one expected
  skip. The projection generator is byte-clean.
- The product transaction carries the single legal `ready -> in_progress`
  hop. Its live status-only plan SHA is
  `6f0f011be2cfca6b24865e05fba0bd7356c083e6824ca570975ffe8d3c4b5d7d`;
  append-only authority
  `3410411c01d92c04b7a47a456d1b17c50da1645dc5d08a72459f1020697902fe`
  and candidate ref
  `6b69892b1f5cca48be58e9768d3d93e6abfa5c380a0694c6cf43d98128e80155`
  bind issue #244 to exact parent
  `fca004a529cccc3b0d4251fc600a897035298014` with
  `execution_allowed=false`. Before merge, freeze one exact head, run both
  independent reviews and required H-tier Linux/Windows validation in
  parallel, then require the ordered writer and a generic zero-action
  readback.
- First frozen head `b4d5e8ad59df2ee35b63a43258b0c05041320623`
  was rejected after both independent verdicts were collected. The reviewers
  reproduced six defects: unrelated numeric-provenance reuse, missing
  structure cache/vintage identity, uncapped UI confidence precedence,
  incomplete report-row identity, pre-2.1 fingerprint incompatibility and
  acceptance of unreviewed report evidence. Its two hosted preflight attempts
  also exceeded the unchanged 120-second affected-test window, so all review
  and CI evidence for that head is stale.
- Replacement head `68b5b5e2a436183c9a9c89c1b9a2fe1096325a3a`
  was also rejected after both independent verdicts completed. The collected
  findings were point-in-time review-history replay, typed numeric-stress
  reachability and status, strict legacy-fingerprint scope and reviewed-row
  migration, negated derivative/lending wording, and independent report-family
  binding. Hosted release run `30781501084` deterministically exceeded the
  120-second changed-test preflight because two regressions had been placed in
  slow broad modules; Linux and Windows package jobs therefore did not start.
- Bounded follow-up commit
  `df215ae1810ffea55a50f96747305d9dccba52ca` corrects all collected findings and relocates those
  regressions into the directly focused structure and instrument-detail test
  files. The resulting six-file affected test selection passes 107 tests with
  one expected skip in 87.9 seconds; Ruff, compile and diff hygiene pass. It
  does not change canonical/lifecycle authority or `execution_allowed=false`.
  Replacement head `db8dfe4560912ccc885d2f3ec355af4984ece77a` was
  rejected only after both parallel reviewers completed. Their consolidated
  findings are persisted numeric-evidence binding, equal-time append-order
  replay, duplicate registry identity rejection, standard local
  factsheet/holdings reachability, and structural evidence propagation through
  the yfinance signal/backtest path. Release run `30783547607` again timed out
  the broad changed-test selection at 120 seconds before Linux/Windows began;
  its evidence is stale.
- Final bounded correction commit
  `8ed78afef51893f50809d44db03da845c482dca5` covers all five findings and moves the remaining
  ISSUE-0104 Instrument Detail assertions to a dedicated focused module while
  restoring the slow broad module exactly to base. The resulting changed-test
  selection passes 94 tests with one expected skip in 68.3 seconds; the direct
  26-test correction suite passes in 17.9 seconds including command overhead.
  Ruff, compile and diff hygiene pass. Freeze a
  new checkpoint head, then run both independent reviews and fresh H-tier
  hosted validation in parallel.
- Exact head `43b7c168718245fad0549db0464705ccaf102c9b` was rejected
  after both reviewers completed. The collected findings are real backtest and
  service/cache holdings propagation, supplemental non-usable status
  preservation, duplicate rejection at the canonical registry reader, and
  exact numeric instrument binding. Stale release run `30785676406` passed its
  96-case affected selection in 99.45 seconds but reproduced the protected
  presentation-boundary violation caused by a direct selector implementation
  import; package jobs did not start.
- Bounded follow-up commit
  `004c8218d84fbbfb000a8efd85452594afb8611c` fixes the full collected set, routes the structural
  field contract through the existing application facade, and replaces the
  88.69-second hosted full-snapshot assertion with a focused section-routing
  regression. Direct correction, architecture and document suites pass 57
  tests; the resulting 108-case affected selection passes with one expected
  skip in 76.3 seconds locally. Ruff, compile and diff hygiene pass. Record the
  next exact review head.

## Completed UPDATEV2-0018 product checkpoint

- Readiness PR #649 merged as
  `efda3f3f8d9fbb075a902af37102b0752e5aba27` after full Linux/Windows
  validation. Its one permitted omission repair PR #650 merged exact reviewed
  head `728d7a880947907169c25fded95774b6f8b11845` as
  `772d297264c071f83bb668d2190723e969b12cde`; writer run `30769324802`
  returned `terminal_status=applied_and_verified` and
  `zero_action_readback=true`. Fresh generic readback plan
  `371b004ccb8c0ebabceaa5242bb705b793b3cb8093b80c31f7cb5e7be457f44a`
  has zero actions and reconciled authority head `f12d3055...`.
- UPDATEV2-0018 is remotely `ready` with no blocking dependencies. This
  product transaction advances only its canonical lifecycle to
  `in_progress`; ISSUE-0104 remains planned and structural-risk scoring is
  outside this product change.
- The first uncommitted implementation failed independent review on reproduced
  persistence, source-binding, truncation and review-integrity defects. It is
  isolated at
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_updatev2_0018` and
  preserved outside the repository at
  `C:\Users\thor2\AppData\Local\Temp\updatev2-0018-rejected-attempt-20260802-001`;
  it must not be committed or pushed.
- The clean v2 lane is
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_updatev2_0018_v2`
  on `codex/updatev2-0018-product-20260802-v2`, rebased onto exact
  `772d297264c071f83bb668d2190723e969b12cde`.
  Its bounded H-tier scope is deterministic three-kind local report parsing,
  hard subprocess resource bounds, immutable checksum/date/kind/authority
  binding, serialized atomic registry/report/conflict persistence, advisory
  fingerprint-bound human review and Trust Evidence visibility. It adds no
  provider download, OCR, generative extraction, scoring, order or execution
  authority.
- Post-rebase focused validation at implementation checkpoint
  `60430fdd29b37ac3e700a368417e07674ce36c7f` passed all 112 parser,
  persistence, concurrency, review-authority and UI cases with one expected
  Windows skip; Ruff, compile, byte-clean generation and diff hygiene passed.
  The reviewed one-action lifecycle plan
  `be182dd37470ce7ae8804f8ffc704e5f3bfdb7a1640d5a1afe883ef2ba28134a`
  binds UPDATEV2-0018/#158 `ready -> in_progress` to exact parent
  `772d297264c071f83bb668d2190723e969b12cde`, append-only authority
  `ff34fbd53c59e832db0ebddd5a325a1143f76f71cbd86b4d68c2e948a1782748`
  and `execution_allowed=false`. Exact-head review and fresh authoritative
  Linux/Windows H-tier gates are next; after merge, require ordered-writer and
  generic zero-action readback before the existing two-hop completion
  transaction.
- Exact-head review reproduced one audit defect at `3b67dc43...`:
  parser/template revision re-import replaced the prior reviewed extraction.
  Corrected checkpoint `b14b5f272a69f9d2c8824fbb161316d3b5382caa`
  now derives source identity from parser and plugin revision, appends the new
  extraction separately, preserves prior review history and fails closed when
  one declared revision produces a different fingerprint. Focused product
  validation now passes 113 cases with one expected Windows skip.
- Risk re-review then reproduced a one-sided valid-store tamper that bypassed
  same-revision drift detection. Corrected checkpoint
  `d95c28a89e24b22123f72d9ded63327b3445982f` requires exact report/registry
  identity cardinality parity before re-import and leaves all stores unchanged
  on mismatch; both missing-report and missing-registry regressions are
  covered.
- Both exact-head reviewer verdicts were collected before the next correction.
  They additionally reproduced physical duplicate registry rows hidden by
  normalization and prior-revision orphaning when a new parser/template
  identity was imported. Consolidated correction
  `84587edd346d06bfa469b9a1600a8789ff59b323` rejects raw duplicates and
  requires equality of the complete v2 report/registry identity sets before
  any incoming revision is processed; same- and changed-revision divergence
  tests preserve every store byte-for-byte.
- PR #651 exact-head run `30771627783` passed classifier, status guard and
  supply chain but preflight failed before package gates because the three new
  report controls lacked entries in `configs/ui_acceptance.yaml`. The bounded
  correction adds only import/verify/reject contracts linked to
  `tests/ui/test_etf_report_ui.py` and makes their keys explicit in the
  existing button-inventory regression.
- Product PR #651 subsequently merged independently approved exact head
  `ccff5d7421d01df7bdcbfde3f3158893f5c449f2` as
  `7bffd0c57a992f599008a658425fc23575b9aef8`. H-tier run `30772069784`
  passed protected preflight, supply chain, authoritative Linux and Windows
  package gates and terminal validation; status guard `30772069791` passed.
  Ordered writer `30773099083` applied only UPDATEV2-0018
  `ready -> in_progress` with `terminal_status=applied_and_verified` and
  `zero_action_readback=true`; generic convergence `30773099086` produced no
  patch and `execution_allowed=false` remains unchanged.
- Clean completion lane
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_updatev2_0018_completion`,
  branch `codex/updatev2-0018-completion-20260803`, starts empty at exact base
  `7bffd0c57a992f599008a658425fc23575b9aef8`. Its bounded scope is only the
  existing two-hop UPDATEV2-0018 replay
  `in_progress -> implemented_initially -> integrated`, bound to PR #651,
  its merged product commit and completed review/gate/writer evidence. The
  exact live one-action plan is
  `ce935663ef8c49098b5b53f24fa0827b33370cc7f134cb1d946de6eddf9d56d7`;
  prepared replay authority
  `6d5f03adc998d774a53d517bcb110d7d02da442ce8dbf8a42a5457238719749a`
  and candidate ref
  `bc7b8e36f23681298376e15fe631b463001b2ffeaf253038383395aa849800b3`
  preserve `execution_allowed=false`. Reusable evidence is refreshed to the
  exact H-reviewed range `772d2972...ccff5d74` for subsequent eligible
  control-only transactions. Because the sidecar itself changes here, the
  classifier correctly withholds reuse for this PR and requires fresh package
  gates rather than accepting self-authorised evidence.

## Completed convergence repair checkpoint

- Bounded repair PR #640 merged independently reviewed exact head
  `049cc5fac353b380090694f059412ec877df6cc1` as
  `874c9ef277350547ca3eca28d5d5c808d7dea7bb`. H-tier run `30743061770`
  passed classifier, preflight, supply chain, authoritative Linux and Windows
  package gates and terminal validation.
- Ordered writer run `30743990686` accepted authority
  `1e9de93977b28d6fc60f9992c6bad5f0fe4fc3f1a50a777376e6300810509ab1`,
  projected ISSUE-0102 `planned -> ready`, preserved
  `execution_allowed=false`, and recorded a zero-action post-write readback.
  Generic convergence run `30743990684` also passed.
- The permanent contract remains bounded to one legal pending status hop or
  the exact two-hop `in_progress -> implemented_initially -> integrated`
  completion replay. Only the exact active-goal and B04 checkpoint chronology
  paths receive E-tier control classification; all protected runtime,
  workflow, authority, security, persistence, financial, package and release
  surfaces remain H-tier.

## Completed ISSUE-0102 and current bounded readback repair

- ISSUE-0102 dependency PR #638 merged exact reviewed head
  `871ea037c594844a0de9e72e7dbabd3405244b76` as
  `179e16c71328c43a9475dce60743a2d1aeda5aa7`. Run `30737461361` passed
  classifier, preflight, supply chain, authoritative Linux/Windows package
  gates and terminal validation; guard `30737461338` passed. Post-merge
  convergence `30738361187` was zero action at checksum
  `da979ae3fef7344ff4e492bd4468f8a3653e329f6121cb13ba9f2e2a003c1b8f`.
- Product PR #641 merged independently approved exact head
  `671ebac2ec5c0fbdd4afc6d9d0f1c953a1ffaa6b` as
  `4a0b87a0a7e18633ffde1fa69e59baa40ce5e03e`. Tier-O run `30744924925`
  passed fresh authority and product preflight, supply chain and terminal
  validation; status guard `30744924900` passed.
- Ordered writer run `30745092252` projected ISSUE-0102
  `ready -> in_progress` and recorded `zero_action_readback=true`;
  generic convergence run `30745092242` passed and
  `execution_allowed=false` remains unchanged.
- Completion PR #642 merged independently approved exact head
  `b9cf650af3b38e69e183b34b569fced99022fd3c` as
  `0848d93edbae6ecd228d0d1e1620dbd99722092c`. Run `30745452805` passed
  classifier, preflight, supply chain, authoritative Linux/Windows package
  gates and terminal validation; guard `30745452803` passed.
- Ordered writer `30746368016` applied the sole ISSUE-0102 aggregate
  `in_progress -> implemented_initially -> integrated`, bound both hops to
  product PR #641 and merge `4a0b87a0a7e18633ffde1fa69e59baa40ce5e03e`,
  and recorded `terminal_status=applied_and_verified`,
  `zero_action_readback=true` and `execution_allowed=false`.
- Bounded generic-readback repair PR #643 merged two independently approved
  exact head `f8f28c94ae8f4a6f8f15dd8a5ad187cd35dafd2c` as
  `bbe8a789d05a7df688661eb8e2370bb26583dc8f`. H-tier run `30746716333`
  passed classifier, preflight, supply chain, authoritative Linux/Windows
  package gates and terminal validation. Automatic exact-main convergence run
  `30747829943` then passed with zero create/update/close/reopen/blocked
  actions. The sole demonstrated repair cycle is complete and closed.
- Dependency PR #644 merged corrected and independently approved exact head
  `8ff50cfc2ef0b1c6d291b57944082b5fde00877f` as
  `4324ee6af1321cf7ea60a6f03b381c1f1979edb0`. Run `30748705677` passed
  classifier, preflight, supply chain, authoritative Linux/Windows package
  gates and terminal validation; guard `30748705679` passed. Exact-main
  convergence `30749425839` passed.
- ISSUE-0103 readiness PR #645 merged independently approved exact head
  `5b5edb44307244e231582e268e227fcf63c211a1` as
  `2428af72525474d306cf9c04e6c9ecdaef213caa`. Run `30749699624` passed
  classifier, preflight, supply chain, authoritative Linux/Windows package
  gates and terminal validation; its status guard passed. Ordered writer
  `30750550860` applied only ISSUE-0103 `planned -> ready`, returned
  `terminal_status=applied_and_verified`, `zero_action_readback=true` and
  retained `execution_allowed=false`; automatic convergence `30750550864`
  passed.
- A fresh generic exact-main live reconciliation from merge
  `2428af72525474d306cf9c04e6c9ecdaef213caa` produced zero create, update,
  close, reopen or blocked actions at plan SHA
  `4b5797a809179b80f1f964cd4080bff436411e23544b7abb4e5cb0ead42df71f`.
- Current clean product lane:
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0103_product`;
  branch `codex/issue0103-product-20260802`; exact base and starting head
  `2428af72525474d306cf9c04e6c9ecdaef213caa`, with an empty initial diff.
  Scope is the bounded ISSUE-0103 ETF economics implementation and focused
  tests/UI exposure while preserving ISSUE-0106 liquidity, all authority
  boundaries and `execution_allowed=false`.
- The finished bounded product diff adds typed local ETF economics and
  canonical total-return evidence, explicit fee/AUM/flow units, known-at
  replay, matched business-daily tracking metadata, a versioned
  provenance-bound closure proxy policy, normal snapshot loading and the ETF
  Economics panel. Existing ISSUE-0106 liquidity code remains byte-identical.
- Exact reviewed product evidence commit
  `1d3e7515c78d73cbd5d767d4ede2f82f838b0077` is immutable. Root validation
  passed 187 affected economics, market-adjustment and UI tests plus Ruff,
  compile and diff hygiene. Independent whole-diff and financial/point-in-time
  reviewers approved the corrected evidence after canonical-generator,
  append-only coverage, complete action-term, decision-time action/row,
  checksum, unit, closure-policy and UI-lineage counterexamples failed closed.
  The narrowly corrected classifier now treats the canonical
  `market_adjustments.py` calculation/authority surface as H while preserving
  ordinary product and E-tier checkpoint classifications; fresh Linux and
  Windows package gates are mandatory before merge.
- Product PR #646 merged independently approved exact head
  `31e12c1ee0a9390d13c91a5014e3f32915da4bf8` as
  `f245a3f1cf26f074acde50cb9f3e4e1b891bd60a`. H-tier run `30758046593`
  passed preflight, supply chain, Linux, Windows and terminal validation;
  status guard `30758046561` passed. Writer `30759189744` applied only
  ISSUE-0103 `ready -> in_progress` with `zero_action_readback=true` and
  convergence `30759189762` passed with `execution_allowed=false`.
- Bounded repair PR #647 merged independently approved exact head
  `a7d70bc11a91e88ba2f3258da34b697fa02ef058` as
  `124a3f0279850ea034a93c9cb750a382bcfc35c9`; H-tier run `30759893469`
  passed Linux, Windows and terminal validation. It permits only the exact
  unchanged blank unresolved placeholder to lack a historical edge event;
  complete edges and all replay-time dependency changes remain rejected.
- Fresh completion lane
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0103_completion_v2`,
  branch `codex/issue0103-completion-20260802-v2`, started empty at exact base
  `124a3f0279850ea034a93c9cb750a382bcfc35c9`. It records only ISSUE-0103
  `in_progress -> implemented_initially -> integrated`, bound to product PR
  #646, product merge `f245a3f1cf26f074acde50cb9f3e4e1b891bd60a`, the completed
  reviews/gates and repair PR #647. Prepared replay authority
  `b8487fad9581689407475c071bb164db6ebe47db1c7391209e24721ee5771226`
  and candidate ref
  `e2433978166039a7aa8f90c37d0d2bec80785589c04d7d34a8c52f849b507b86`
  preserve `execution_allowed=false`. Exact next action is focused E-tier
  validation, exact-head review, protected merge and writer/readback proof.

### Prior dependency-edge checkpoint (superseded)

- Current UTC date: `2026-08-02`.
- ISSUE-0101 recovery PR #636 merged as
  `07da10ee0403033da30071eab5cfb5205c0af147`; bounded recognition repair PR
  #637 merged exact reviewed head
  `0ca952b170420ceb6d85dbfedffa7f106a66d5d8` as
  `2e3d69541dccc5f71e868e4c55e85bef623cfbd3` after H-tier run
  `30736184903` passed. Automatic convergence run `30737053331` produced zero
  actions at checksum
  `da979ae3fef7344ff4e492bd4468f8a3653e329f6121cb13ba9f2e2a003c1b8f`;
  GitHub #241 projects canonical `integrated` and `execution_allowed=false`.
- ISSUE-0102 is the next implementation-order record. Its sole ISSUE-0098
  dependency is integrated, but the edge requires evidence review before the
  issue is ready.
- Clean evidence-only lane:
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0102_edge`;
  branch `codex/issue0102-dependency-0098-20260802`; exact base and starting
  head `2e3d69541dccc5f71e868e4c55e85bef623cfbd3`, initially empty.
- Current scope records only ISSUE-0102→ISSUE-0098 as `complete` against merged
  `peer-cohort.v1` commit `fc734201b138d3f24fa68d8c07422322506d6fc5`.
  ISSUE-0102 remains `planned`; product code, dependency lists, GitHub state,
  external authority and execution policy are unchanged. The programme
  projection is generated and byte-clean in check mode.
- Exact next action: run E-tier guards, independently review and merge the
  exact dependency head, verify zero-action convergence, then advance
  ISSUE-0102 through readiness and bounded product implementation.

## Prior ISSUE-0101 recovery checkpoint (superseded)

- Current UTC date: `2026-08-02`.
- ISSUE-0101 recovery PR #636 merged exact reviewed head
  `10db96f6a3e877196352f28c11428b7ac9d4859b` as
  `07da10ee0403033da30071eab5cfb5205c0af147`. Run `30733297748` passed the
  authoritative H-tier classifier, preflight, supply-chain, Linux/Windows
  package gates and terminal summary at 2,581 tests per platform; guard run
  `30733297750` passed. The Windows four-worker pilot recorded one report-only
  ESEF parser divergence while the authoritative serial gate passed.
- Automatic writer run `30735911761` appended the one aggregate replay proposal
  and receipt to GitHub #241 with `execution_allowed=false`, then failed its
  immediate zero-action readback. Settled authority reconciliation projects
  `integrated`; generic sync blocks only because create-acceptance scanning does
  not yet recognise the two replay markers as known managed comments.
- Clean bounded H repair lane:
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0101_postmerge`;
  branch `codex/status-replay-comment-recognition-20260802`; exact base and
  starting head `07da10ee0403033da30071eab5cfb5205c0af147`, initially empty.
- Current repair scope: recognise only valid replay proposal/receipt markers in
  generic managed-comment validation, retaining replay parsing, ledger
  reconciliation, fail-closed malformed-marker handling and all authorities.
- Initial H-tier repair PR #634 merged exact reviewed head
  `676aaaeedadcf04c3a4644f4d10902a2c05bd311` as
  `ff10762e8c000b2f2c834073e27a664bc20de143`; run `30724545238` passed fresh
  Linux and Windows package gates and terminal summary.
- The first clean E recovery attempt failed closed before artifact creation:
  replay preparation found that generated `issue_registry.json` omits the
  authoritative transition history held in `programme_control_state.json`.
- Preserved E attempt:
  `C:\Users\thor2\AppData\Local\Temp\issue0101-e-recovery-blocked-20260802`;
  patch SHA-256
  `2A2C65B7B5864D2A95ED641C46D0874667DFE50B20A551082C03B76DF531A4E2`.
- Follow-up H-tier repair PR #635 merged independently approved exact head
  `91aea56ec60d9dfb92968c30428c0a02a35b5652` as
  `a4aadf36cc6c0f8cbb356fff96b572919cf5857f`. Run `30728917010` passed
  classifier, preflight, supply-chain, Linux and Windows package gates and the
  terminal summary; post-merge convergence run `30729715977` passed zero action.
- Clean recovery worktree:
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0101_replay_v2`;
  branch `codex/issue0101-two-hop-recovery-20260802-v2`; exact base and starting
  head `a4aadf36cc6c0f8cbb356fff96b572919cf5857f` with an initially empty diff.
- Canonical input records only ISSUE-0101
  `in_progress -> implemented_initially -> integrated`; both hops share PR #633
  recorded independent review and tier-O validation evidence and verified product commit
  `0680429aa5c30477dc854ef80367a3cc5ff4010e`.
- Current lane: mechanical projection generation/check, H-tier guards,
  exact-head review, merge and GitHub #241 convergence remain pending.
- Exact-head run `30731278862` failed closed before package validation because
  an unconditional depth-one local base fetch marked the already complete
  authority checkout shallow and hid the reviewed product commit from the
  ancestry check. The bounded CI correction preserves full history when the
  trusted base commit is already present and keeps the existing fail-closed
  fallback when it is absent.
- The next exact-head run passed authority preflight, supply chain and both
  Linux/Windows package gates, then terminal validation failed closed because
  validation-mode replay evidence omitted the already-validated replay hops
  and reviewed product commit required by `validation_summary.py`. The bounded
  evidence-projection correction adds only those two identities.
- Protected scope: ISSUE-0101 product code, dependency edges,
  workflows/permissions, external systems and all execution/authority policy
  remain unchanged.
- Preserved rejected evidence path/hash:
  `C:\Users\thor2\AppData\Local\Temp\issue0101-invalid-recovery-evidence-20260802-001`;
  patch SHA-256
  `32488742f363e50f14c566b6890992e37a1a9843d0ed9ca7031fc32fc56e168c`.
- Exact next action: generate all projections atomically, require byte-clean
  check mode, prepare the bounded aggregate proposal/receipt, validate and
  review the exact H-tier head, then merge and verify GitHub #241 reaches
  canonical `integrated` without unrelated writes.

## Frozen delivery evidence and boundaries

- Final fast-path evidence PR #631 merged exact reviewed head
  `11da5e4a880a4e06526147bd30527c24d186804d` as
  `8a0d1d9a7437770aa0567d9ae6787e3881832f27`.
- H-tier run `30659377591` passed classifier, preflight, supply-chain,
  Linux and Windows package gates, both repeated parallel pilots,
  cross-platform aggregation and terminal validation.
- Post-merge convergence `30663879745` passed from exact main with zero
  create, update, close, reopen or blocked actions.
- Frozen compact-control evidence: execution p50/p95
  `0.4000/1.2500 min`; queue p50/p95 `0.0500/1.8833 min`; correct E
  package skipping `5/5`; cache reuse `10/46` (`21.74%`). No polling
  reduction is claimed.
- GitHub authority repair is complete and frozen to repository-authored issue
  creation and lifecycle/status projections already used by the programme.
  It is not a general GitHub database or event-sourcing framework.
- Git remains canonical. Broker/provider/release/deployment authority is
  unchanged and `execution_allowed=false`.
- Do not add speculative GitHub support, compensation or retry of ambiguous,
  cancelled, partially applied or erased writes without explicit user
  approval and a demonstrated safety need.

## Current orchestration

- The Sol-medium root owns requirements, shared state, Git, GitHub,
  integration and release decisions.
- Normally use one named child; maximum two children excluding the root;
  delegation depth one.
- A second child is limited to independent read-only work or a proven disjoint
  worktree. Normally one workspace-writing child is active.
- Product work may overlap immutable CI only through a disjoint worktree and
  must not touch the frozen PR head, canonical/generated control files or
  external state.
- Current named-agent routing supersedes historical Sol/Terra/Luna routing.
- Normally deliver one product issue per product PR. Independent dependency
  evidence may be batched when safe; lifecycle convergence is compact and
  automatic.
- The four-worker safe/unsafe pytest pilot remains report-only. Serial Linux
  and Windows packaged validation remains authoritative.

## Durable memory and compaction survival

Before product, CI or programme-control changes, read:

1. global and project `AGENTS.md`;
2. `docs/product-completion/DELIVERY_WORKFLOW.md`;
3. this active goal and `plans/BATCH-B04-ANALYSIS-SPINE.md`;
4. `PLAN_step2.md`, the relevant issue records, source and tests.

After compaction, a worktree/thread switch, merge, base change or uncertain
handoff, re-read those files and verify `origin/main`, branch, base/head,
upstream, dirty files, blocker and next action. Update this checkpoint before
handoff.

## Completion and stop conditions

Do not abandon reviewed checkpoints, alter PR #560, merge stale PR #562,
close issue #241, publish a release, create a tag, deploy, enable execution or
add broker writes.

After two attempts with the same root cause and no materially improved
evidence, preserve the checkpoint, record the failure fingerprint and
attempts, identify the missing decision or authority, and stop that approach.
A newly evidenced independent cause may receive one bounded repair.

A safe handoff reports goal, worktree, branch, base/head/upstream, dirty files,
issue and status, completed work, tests, protected boundaries, blocker, exact
next action and whether the requested outcome is actually complete.
