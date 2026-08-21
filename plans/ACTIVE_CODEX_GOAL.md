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

## Current ISSUE-0112 product checkpoint (supersedes older checkpoints below)

- ISSUE-0059 integration PR #686 merged exact reviewed head
  `560e68511eb228d831f9c31e0babdafa26c0a57e` as
  `87b05852121ff6ecdd1c9b1b8ae5ed423875523c`; writer run `31672396480`
  completed with full reconciliation, zero-action readback and
  `execution_allowed=false`.
- ISSUE-0112 dependency PR #687 merged exact reviewed head
  `9816f420a650f64c6c0fbc24f2b7f9720fe8b124` as exact main
  `79d4110f39a0aa903a0df361316befcaaff782eb`. Run `31673015385` passed
  Linux, Windows, terminal validation and the status guard. Only the ISSUE-0051
  and ISSUE-0059 dependency edges changed; ISSUE-0112 remained `planned` and
  generic reconciliation was zero action.
- Clean product lane
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0112_product_review`,
  branch `codex/issue0112-product-review-20260813`, starts from that exact base.
  Product commit `5e8a82153a095c70a2dc3457c60e3891092c6226` adds only the canonical
  benchmark, cash, peer, reference-portfolio and VWCE-anchor contract plus its
  focused tests.
- PR #688 initial frozen head `76d061ae0452ddfe358829adecd5a91241dbaf03`
  is rejected and hosted run `31677268341` is cancelled/stale. Both independent
  reviewers reproduced one consolidated finding set: unbound VWCE fact/currency/
  horizon cutoffs, mutable caller-owned versioned evidence, hash-only serialized
  validation, unenforced canonical share-class identity, unaligned reference
  portfolios and a test-only production contract.
- Consolidated correction commit `e927fe25914ec33193cfc74c8b3496c4ef7e4b21`
  closes all findings in the existing contract and portfolio-analysis facade.
  It seals nested evidence and the registry, semantically reconstructs serialized
  records, enforces canonical VWCE identity and PIT/currency/horizon/conversion
  evidence, aligns reference portfolios at effective and knowledge cutoffs, and
  projects benchmark/profile evidence without changing raw analysis. The complete
  229-test focused/adjacent set passes; Ruff, contract mypy, compile, diff hygiene
  and programme check mode pass. Existing application-facade mypy output remains
  at its unchanged five-error baseline. Freeze one replacement exact head for
  paired re-review and fresh H-tier Linux, Windows and terminal evidence.
- Replacement head `df974a6a5f16ddeeae4e7e1db63c130aed78693c` is rejected and
  run `31679353881` is cancelled/stale after paired re-review demonstrated the
  final bounded gaps: contradictory registry/anchor availability, invalid
  listing status, missing conversion and resolution provenance, non-finite
  horizons, non-deterministic SemVer precedence, listing/anchor chronology,
  direct nested execution evidence and duplicate requested references.
  Consolidated commit `cb3e513d34dfdaf441905ee905f0dc768d4cc11c`
  closes those exact paths without wider architecture. The complete 241-test
  focused/adjacent set passes with Ruff, contract mypy, compile and diff hygiene;
  conversion and anchor evidence now produce a canonical resolution digest and
  all unavailable combinations fail closed. Freeze one final replacement head
  for both exact-head reviews and fresh H-tier Linux/Windows/terminal evidence.
- Final review of `80226ff2737c2963b9f9efb65fda90117e0d43f9` rejected
  one newly demonstrated authoritative-selection defect plus two strict typing/
  provenance boundaries; run `31681320326` is cancelled/stale. Commit
  `c247b4698c5773b707f41a142ca344d1af7c6f99` selects the newest PIT-authoritative
  benchmark, cash and peer before status evaluation, strictly types opportunity
  anchors, and refuses profile claims from incomplete manually constructed
  resolutions. All 246 focused/adjacent tests pass with Ruff, contract mypy,
  compile and diff hygiene. Freeze one replacement head for paired exact-head
  review and fresh H-tier evidence; no adjacent contract or authority changed.
- Paired review of `4bb842a53d181abcfb309e50740ec22a25648279`
  rejected the final analogous VWCE boundaries and production-delivery gap;
  run `31682292726` is cancelled/stale. Commit
  `2b1cd0d9a9fa422b2fdba002f1cc65b54d8efcfd` makes the newest PIT listing
  authoritative before status evaluation, strictly types risk-indicator and
  resolution authority, binds claims to the actual anchor/conversion evidence,
  and carries snapshot-attached canonical evidence through ordinary analysis,
  save, load and existing service-evidence UI projection. All 269 affected
  contract, sandbox, UI, cash, attribution, peer and optimiser tests pass with
  Ruff, contract mypy, compile and diff hygiene. Freeze one final exact head for
  paired review and fresh H-tier evidence; `execution_allowed=false` remains.
- Paired review of `19a19d170edb1df2057e4be1a31b6d4eb076a863`
  rejected four remaining demonstrated delivery boundaries, and exact-head run
  `31683739150` is cancelled/stale: the real `CockpitSnapshot` path omitted the
  registry and VWCE evidence, Portfolio UI omitted both projections, selected
  registry records lacked content-digest provenance, and manually constructed
  available anchor resolutions were not replayed against the actual listing,
  horizon, conversion and point-in-time cutoffs. Consolidated product commit
  `db39adbed19a76dca23c0a3764fcd4ddf6a46977` closes only those paths. The
  affected 278-test contract, sandbox, UI, cash, attribution, peer and optimiser
  suite passes with Ruff, targeted contract mypy, compile, programme byte-clean
  and diff-hygiene evidence. Freeze one replacement exact head for paired final
  review and fresh H-tier Linux/Windows/terminal validation; preserve all
  lifecycle, provider/broker/release and `execution_allowed=false` boundaries.
- Paired review of `d7bb08462ad033ee9537f834ffa89f0ab5fd6e4f`
  rejected five newly reproduced strict provenance/input boundaries; run
  `31685879923` is cancelled/stale. Consolidated commit
  `006abd94ec4380407484b1227ba1ae35106d6ea6` requires exact canonical-registry
  membership for the selected VWCE anchor, validates every tied listing source,
  preserves explicit empty overrides for fail-closed validation, rejects duplicate
  reference requests and forbids source-hash type coercion. All 286 affected tests
  plus Ruff, targeted contract mypy, compile, programme freshness and diff hygiene
  pass. Freeze one replacement exact head for paired final review and fresh H-tier
  Linux/Windows/terminal evidence; no adjacent architecture or authority changed.
- Paired review of `4aa2ef11f72b33775dd6a7cd031c7473a3dff2c7`
  rejected four newly reproduced fail-closed boundaries; run `31687764826` is
  cancelled/stale. Commit `858ea6310369dbcb7a765aac128e11307e7b47b6`
  selects the newest PIT-authoritative reference portfolio before alignment,
  requires every profile anchor to be uniquely registry-bound, strictly types
  listing hashes and rejects nested execution authority in selections,
  resolutions and profile inputs. All 292 affected tests plus Ruff, targeted
  contract mypy, compile, programme freshness and diff hygiene pass. Freeze one
  replacement exact head for paired final review and fresh H-tier evidence.
- Paired review of `e9bab1eeaae710c056e7dff18bb365395587d6c2`
  rejected two provenance validations; run `31689397297` is cancelled/stale.
  Commit `0511bb7e5a7984d1fa24899db13c584e22b90b81` rejects non-string
  mapping keys before canonical hashing and requires exact unique registry
  membership for every projected available selection and reference. All 298
  affected tests plus Ruff, targeted contract mypy, compile, programme freshness
  and diff hygiene pass. Freeze one replacement head for final paired review and
  fresh H-tier Linux/Windows/terminal evidence.
- Final paired review of `f269c592c28b60f79205f4bbec1a1c2da996d6ff`
  produced one approval and one demonstrated delivery blocker; run `31690695124`
  is cancelled/stale. The real builder only emitted unavailable evidence and the
  UI omitted available selected identities. Commit
  `82371502a356ef62231ee39647d2c88da9a57cf8` adds the existing-envelope,
  duplicate-key-safe local registry input, packages it, derives deterministic
  snapshot PIT inputs from current config/as-of state, renders all selected
  identities/versions/digests, and proves builder -> save/load -> rebuilt-snapshot
  available readback. All 320 affected tests plus Ruff, targeted mypy, compile,
  packaging assertion, programme freshness and diff hygiene pass. Freeze one
  replacement exact head for paired final review and fresh H-tier evidence.
- Paired review of `ccc64e372ed0034a548dd68a4383493cb7874083`
  rejected placeholder availability, raw-count PIT selection, nested export
  authority, hidden VWCE identity, hard-coded no-trade holdings and JSON EOF
  hygiene; run `31692775935` completed but is stale. Commit
  `9dccd8d11802eabce3f36dfac59bd22feb370d3c` marks packaged identity-only
  records unavailable without fabricated hashes, selects dated anchor/listing
  histories at effective/knowledge cutoffs, rejects nested execution on export,
  removes hard-coded no-trade and renders selected VWCE identity/cutoffs. The
  source-backed injected available path remains proven through rebuild/save/load.
  All 324 affected tests plus Ruff, targeted mypy, compile, programme freshness
  and diff hygiene pass. Freeze one replacement head for paired final review and
  fresh H-tier Linux/Windows/terminal evidence.
- Replacement head `3020c4b811179fb7c77158a9fd1a0eb4ac98bc7d` is rejected;
  run `31694667839` is cancelled/stale. Whole-diff review found no additional
  code defect, while risk review reproduced two final delivery failures:
  selection/reference projections were not bound to their declared semantic
  slots, and the wheel installed the registry outside the application resolver's
  path. The consolidated correction binds benchmark, cash, peer and reference
  identities at construction and UI readback, relocates the unchanged registry
  into an importable package resource and proves an isolated wheel install/load.
  The 163 focused contract/UI/sandbox/package tests and 152 adjacent financial/
  PIT tests pass with Ruff, targeted mypy, compile, programme byte-clean, diff
  hygiene and byte-identical relocation evidence. Commit and freeze one new exact
  head for paired final review and fresh H-tier Linux/Windows/terminal evidence.
- Both reviews of `7d0ca499a43fd63b43ced5c6de97a1ffaf24b16e`
  reproduced the same single missing declaration invariant: `peer_set_id` was
  not bound to the selected available peer or `None` for an unavailable peer.
  Run `31696193800` is cancelled/stale. Add only that invariant and its available,
  unavailable and forged UI-readback regressions, then freeze one replacement
  head for both final reviews and fresh H-tier evidence.
- Review of `4374015cdfc814a30d43c9cc9465f3cfbc3fc49d` produced one
  approval and one newly demonstrated acceptance blocker; run `31697195555` is
  cancelled/stale. The generic contract supports no-trade, but the real snapshot
  requests only equal-weight and maximum-diversification and therefore omits the
  canonical current-portfolio/no-trade baseline from analysis, UI and persistence.
  The bounded correction derives a deterministic, checksum/PIT-bound no-trade
  reference from exact holdings plus implied cash, projects its weights and
  provenance through UI/save-load readback, and fails closed on malformed dates,
  identifiers, weights, totals and source values. The 170 affected tests, 152
  adjacent financial/PIT tests and 11 targeted adversarial tests pass with Ruff,
  targeted mypy, compile, byte-clean generation and diff hygiene. Freeze one
  final replacement head for paired review and fresh H-tier validation.
- Both reviews of `97597ab5af3c830ad9e31d2b2d386f01a1f2ce84`
  rejected the no-trade source boundary; run `31700680310` is cancelled/stale.
  The production builder filtered holdings before derivation, allowing excluded
  exposure to be relabelled as cash and checksum-bound as truth, while negative
  market values remained accepted. The consolidated correction preserves the
  complete pre-filter source for no-trade derivation/checksum and fails closed on
  excluded holdings and negative/non-finite values. Its production-builder
  reproduction and complete 176-test affected suite pass with Ruff, targeted
  mypy, compile, programme freshness, package proof and diff hygiene. Freeze one
  replacement exact head for paired review and fresh H-tier validation.
- Reviews of `5907e23ff1d57a9d6646e0d768b2eea4b10b84f5` rejected two
  final PIT paths and run `31702055238` failed preflight/cancelled downstream.
  Invalid current holdings could retain a stale registry no-trade record; source
  knowledge time was synthesized and omitted from the holdings checksum; and the
  isolated-wheel test invoked an unavailable backend directly. Always strip stale
  no-trade, require and checksum non-future source knowledge provenance, preserve
  its actual timestamp, and use the pinned build frontend for the unchanged wheel
  install/load proof. The consolidated correction passes 180 focused contract/
  sandbox/UI tests, Ruff, targeted mypy, compile, programme freshness, diff
  hygiene and a real pinned-frontend isolated wheel build/install/load. Freeze
  one replacement exact head for final paired review and fresh H-tier evidence.
- Both reviews of `1bd954ecbe4381a43089cef551ae52c0163983f2`
  rejected three exact input-truth paths; run `31704018549` is cancelled/stale.
  No-trade weights were not reconciled to market values, timezone-naive knowledge
  was silently interpreted as UTC, and an available VWCE anchor could carry
  nested fees/tracking/risk facts marked unavailable. Correct only those three
  fail-closed validations and add their focused regressions. The consolidated
  correction passes 199 affected contract/sandbox/UI tests, the pinned-frontend
  isolated wheel proof, Ruff, targeted mypy, compile, programme freshness and
  diff hygiene. Freeze one replacement exact head for paired final review and H.
- Risk review of `008ee66f0e161da1d66532a5893731c5c9d8a5ea`
  reproduced one metadata predicate defect; run `31706356179` is cancelled/stale.
  Authority/status/version-only nested VWCE mappings counted as financial facts.
  The correction excludes metadata keys and requires substantive fees, tracking
  and risk facts; 200 affected tests and Ruff pass. Freeze one replacement head.
- Both reviews of `035494598fab594f3cbde7babccc76444c5c3008` rejected two
  final declaration paths; run `31707789636` is cancelled/stale. Metadata aliases
  still counted as VWCE facts and invalid-input fallback omitted explicit benchmark
  and cash declarations. The correction closes both with 200 affected tests plus
  Ruff, targeted mypy, programme freshness and diff hygiene green.
- A live one-update ISSUE-0112 `planned -> in_progress` plan and candidate were
  prepared read-only, then rejected before publication by the existing guard:
  the reviewed product commit is not an ancestor of the PR base. The invalid
  control commits remain isolated on local branch
  `codex/issue0112-product-20260813`; they must not be pushed or merged. Do not
  redesign the authority contract. Freeze this product-only lane for paired
  exact-head review and fresh H-tier Linux, Windows and terminal validation.
- Before merge, require exact product evidence and the existing lifecycle
  automation/readback tests. After merge, prepare the legal status authority
  from the new exact main, apply only ISSUE-0112 `planned -> in_progress`,
  require the ordered writer and generic zero-action readback, then immediately
  execute the existing aggregate `in_progress -> implemented_initially ->
  integrated` completion bound to the same reviewed product commit and
  evidence. Preserve all dependency, external authority and
  `execution_allowed=false` boundaries.

- Replacement head `8c5dc03ba1d939a8c4fad28fc8f246741825b77a` is rejected by
  both exact-head reviewers and run `31717953477` is cancelled/stale. The
  consolidated demonstrated set was limited to declaration-window drift in
  backtest/attribution, non-canonical peer derivation, forged nested execution
  evidence, Training Centre argument binding, feature-cache identity/readback,
  pre-resolution signal features, incomplete N/A schemas, an unbound macro
  caller and the sparse-correlation regression. One bounded correction now
  resolves the full calculation window, uses only digest-bound canonical peer
  members, recursively validates relative evidence, binds feature reads to the
  universe/settings/reference tuple, routes all affected callers and restores
  complete fail-closed outputs. The complete affected 328-test product/UI set,
  99 macro/regime tests, all five packaged workflows, Ruff, targeted mypy,
  compile, byte-clean programme generation and diff hygiene pass. Complete the
  checkpoint update, then freeze one replacement exact head for paired review
  and fresh H-tier Linux, Windows and terminal evidence.

- Frozen replacement head `713c2a837fc7244cc01e07947fb3e80629446bd7`
  is rejected by both independent reviews; hosted run `31722219785` failed the
  attributable changed-test preflight and skipped H-tier package/pilot gates.
  The complete consolidated set is strict decision-time calculation windows,
  canonical benchmark/cash and peer binding, minimum overlap, immutable retained
  instrument evidence, supplied-feature sanitisation, complete N/A row schemas,
  macro binding and the exact SignalService CI fixture. One bounded correction
  closes those paths without workflow or authority changes. The complete affected
  product/UI/macro suite and exact hosted changed-test selection pass locally,
  including all five packaged workflows; Ruff, targeted mypy, compile, byte-clean
  programme generation and diff hygiene pass. Freeze one new exact head for both
  final reviews and a fresh H-tier run with Linux, Windows, terminal and pilots.

- Replacement head `660acbc93444d255341ed337ad3e6cf5fd11894a` is rejected by
  both exact-head reviewers and hosted run `31726428231` is cancelled/stale.
  The newly demonstrated final set is same-window benchmark attribution,
  future candidate exclusion, exact intraday cutoff clipping, ordinary official
  cash evidence wiring, BacktestService call compatibility and cache structural
  validation ordering. One bounded correction addresses only those six paths;
  the four reproduced full-suite failures, adversarial ISSUE-0112 tests, broad
  affected suite and changed validation pass with static/programme hygiene.
  Freeze one final exact head, rerun both reviews against it and require fresh
  Linux, Windows, terminal, packaged and parallel-pilot H-tier evidence.

- Replacement head `79fc7445aa2b053baba49fd7b8f7fb36055d8ff9` is rejected:
  backtest alone still admitted a date-only close before an intraday cutoff, and
  two committed blank lines failed whole-diff whitespace preflight. Run
  `31731679751` is cancelled/stale. The surgical correction scopes backtest
  prices through the shared exact decision-window helper before every calculation,
  adds the noon-cutoff regression and removes only the two whitespace defects.
  Focused backtest/attribution tests, the exact hosted changed-test selection and
  all five packaged workflows pass with static, programme and diff checks clean.
- Frozen product head `ecff814fd07ae187196b5bc5e22f0e310dbb0a28` passed both
  independent exact-head reviews and every Linux, Windows, terminal, release and
  platform-pilot job in H-tier run `31733243156`. The final cross-platform
  aggregation alone failed because three tests that explicitly require Windows
  directory junctions were not in its exact platform-outcome contract. The one
  bounded correction permits only those three node IDs to be skipped on Linux
  and pass on Windows, adds exact lane regressions, and replays the successful
  hosted artifacts to `passed` with no differences. Product semantics and
  `execution_allowed=false` are unchanged. Freeze one corrected head for paired
  exact review and fresh H-tier evidence; no adjacent pilot or CI redesign.
- Corrected head `3ec216f679bf3ec4d602985e0a9bca0549231c8c` passed both
  independent reviews. Run `31755008546` proved Windows release, both platform
  pilots and cross-platform aggregation, but its Linux release subprocess
  twice segfaulted in pandas' native CSV parser at the same discarded-result
  atomic post-write validator, in two different previously passing disclosure
  tests. One bounded persistence correction replaces only the six identical
  parsed-disclosure CSV validation callbacks with a strict UTF-8 standard-library
  parser that accepts quoted multiline cells and rejects malformed quoting or
  inconsistent widths. Atomic I/O, authoritative parquet data, workflows, pins,
  product calculations, lifecycle authority and `execution_allowed=false` are
  unchanged. The complete parsed-disclosure rollback/concurrency suite and Ruff
  pass; freeze one replacement head for paired exact review and fresh H-tier
  evidence, with no adjacent CI or persistence redesign.

- Exact head `7ebff7c3dbfe054a96d574eea8aa7f2596d5a7b9` is rejected by
  both independent reviews and H-tier run `31784447898`; the run stopped in
  changed-test preflight before Linux, Windows and pilot gates. The complete
  demonstrated set is source-price revision binding for feature/forecast
  caches, enforcement of the declared calculation window, validation of every
  populated candidate chronology alias, and blank VWCE listing IDs mapping to
  explicit unavailable evidence. One consolidated correction binds every
  production cache read to the adjusted-price snapshot and cutoff, refuses
  unbound cache publication/reuse, clips feature/forecast calculations to the
  canonical window, applies conservative date-only chronology and preserves
  explicit-empty no-fallback semantics. Direct regressions pass 45 focused
  tests; changed validation, Ruff, compile, byte-clean programme generation and
  diff hygiene pass. Freeze one replacement exact head for paired review and a
  fresh complete H-tier run; `execution_allowed=false` and authority boundaries
  remain unchanged.

- Replacement head `b3f36a28bee58f79a4c27e912e5215d5095016c8` is rejected by
  both final reviewers; H-tier run `31788494031` passed classifier,
  supply-chain and exact changed-test preflight, then was cancelled as stale.
  The complete newly demonstrated set is caller-supplied feature binding,
  future or malformed cost chronology in attribution, forecast horizon/model
  request identity and canonical cash-selection gating. One bounded correction
  requires current price/window attrs on supplied features, derives or rejects
  unbound feature publication, clips and validates every dated cost row, binds
  main and candidate forecast caches to normalized request identity, and keeps
  cash comparison unavailable unless local curve evidence matches an available
  canonical cash identity and window. Focused ISSUE-0112, publication,
  attribution, scoring, cash and recovery suites pass with Ruff, compile and
  diff hygiene clean. Freeze one replacement exact head for paired review and
  fresh complete H-tier evidence; preserve `execution_allowed=false`.

- Replacement head `c86e225ab66e70ee39fbb97a6489fd73fe239ba6` is rejected by
  both final reviewers; run `31791678297` was cancelled as stale. The complete
  unique set is forecast request identity at shared readers, the candidate
  price snapshot used by candidate readers, and fail-closed attribution for
  future cashflows and malformed cost values. One bounded correction threads
  normalized horizon/model-mode identity through every forecast read and
  write, atomically retains and replay-validates the local candidate price
  snapshot, and applies canonical chronology plus strict numeric validation to
  cashflow and cost evidence. Direct forecast consumer, candidate score/UI and
  attribution regressions pass with the broader affected suite, Ruff, compile
  and diff hygiene. Freeze one replacement exact head for paired review and a
  fresh complete H-tier run; no hidden provider I/O or authority change is
  introduced and `execution_allowed=false` remains.

## Historical ISSUE-0017 product checkpoint

- ISSUE-0016 PR #671 merged exact reviewed head
  `89fb083f9c0244e376b39d85ccea5d96379377b1` as exact main
  `9d3550589f8aacbe6686a1e07711007e50bef9cf`. Linux, Windows and terminal
  validation passed in run `31384086112`; the status guard passed in run
  `31384086094`.
- Ordered writer run `31387114454` applied and verified only ISSUE-0016
  `implemented_initially -> integrated` with
  `zero_action_readback=true`. Generic convergence run `31387113274` passed.
  A fresh generic exact-main readback accepts authority sequence 21, projects
  ISSUE-0016 `integrated`, and reports zero create, update, close, reopen or
  blocked actions. `execution_allowed=false` remains unchanged.
- ISSUE-0017, "First-run onboarding and setup wizard", is the next canonical
  implementation-order issue. It is P1, dependency-ready and activation-ready
  with no blocking or activation dependencies. Its bounded acceptance scope is
  storage location, hardware profile, mandatory versus optional providers,
  offline sample/bulk bootstrap, encryption/backup preferences and explicit
  staged-execution defaults.
- Clean product worktree
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0017_product_final`,
  branch `codex/issue0017-product-final-20260810`, starts at exact base/head
  `9d3550589f8aacbe6686a1e07711007e50bef9cf` with an empty diff. Inspect the
  existing verified implementation and focused tests first, implement only a
  reproduced acceptance gap, then prepare the complete legal lifecycle
  transaction before freezing one review head. Preserve local-first behavior,
  all existing safety and authority boundaries, and `execution_allowed=false`.
- Initial product commit `cb2149963d497f2235edc5cb1d35cc9af2fe82ee`
  was rejected after independent criterion review reproduced unused selected
  storage, metadata-only bootstrap and absent quota-to-UI propagation. One
  consolidated correction produced exact product commit
  `f6fd24678be4c13730d2c821f9d3ed2d9bc9edce`; independent re-review approved
  all criteria and the focused onboarding, import/export and atomic-I/O suites.
- Same-PR lifecycle preparation failed closed because the existing guard
  requires `verified_commit` to be an ancestor of the reviewed PR base. The
  invalid candidate/authority lane is preserved locally and will not be
  published. Freeze this product-only head for H-tier review and validation;
  after merge, prepare the single automatic ISSUE-0017
  `implemented_initially -> integrated` transaction against the real merged
  product commit, then require ordered writer and generic zero-action readback.
  `execution_allowed=false` remains unchanged.
- Final parallel review of exact head
  `1245881daf1a60a5a229789329bf5d31d11db6e4` reproduced two bounded
  persistence defects even though H-tier run `31420199673` passed: the
  explicit schema-v2 migration called the canonical save path that rejected
  every legacy source, and a rejected in-guard race could leave durable backup
  artifacts. Consolidated commit
  `916ee1aa3a8228f1bab46ae4546c3b523d23c12c` adds the single explicit,
  checksum/CAS-guarded v2-to-v3 migration, requires acknowledgement only for
  unverifiable non-hash legacy data, verifies successful backups and removes
  backup artifacts when stale or tampered guarded writes reject. The complete
  universe/onboarding/manager surface passes with one expected platform skip;
  Ruff, compile, diff hygiene and programme byte-clean checks pass. Freeze one
  documented replacement head for both independent reviews and fresh H-tier
  Linux/Windows/terminal evidence. Product scope, external authority and
  `execution_allowed=false` remain unchanged.
- Parallel review then rejected documented head
  `5aa6c9bcb4af6f33e5347938d6731f76a6d9233f` for four exact cases: a
  caller-reachable migration escape, post-commit backup ambiguity, a symlinked
  canonical-store escape and orphaned policy profiles after legal same-tier
  onboarding replacement. Run `31448286398` was cancelled and is stale.
  Consolidated commit `c2397dc20500b534ba17ccdb4a048831721ddabd`
  removes the public legacy switch and enforces digest-bound acknowledgement
  in the guarded migration writer, verifies commit/backup disposition while
  the group guard is held, rejects symlinked canonical destinations and keeps
  only policy profiles whose records survive replacement. All four focused
  regressions and the complete universe/onboarding/manager suite pass with two
  capability-specific skips; Ruff, compile and diff hygiene pass. Freeze one
  final documented head for both independent reviews and fresh H-tier gates.
- Re-review rejected documented head
  `5289d1206b0a88e990a9bc57538b4d9706c0435d` after reproducing a junction
  swap before atomic destination resolution and a stale writer deleting a
  following writer's verified backup. Run `31449729020` is cancelled and
  stale. Commit `3a6ffe1bcf2e48fa055b6e7db8323e451e2b60b4` binds the
  canonical destination check before resolution and repeats it under the held
  group guard, removes unowned backup-directory cleanup and makes the shared
  backup helper remove only its own failed checkpoint. Both exact races, the
  prior closure regressions and the complete universe/onboarding/manager/atomic
  surface pass with two capability-specific skips. Freeze one replacement head
  for parallel final review and fresh H-tier Linux/Windows/terminal gates.
- Both exact-head reviewers rejected frozen head
  `f01a673a284c6c7aaf1d0f3699371bef4dfdde70`; hosted run `31391040254` is
  cancelled and stale. Their consolidated findings were partial cross-root
  writes, destructive/noncanonical bulk import, sparse-config replacement,
  ignored storage/hardware choices, empty-machine UI failure, invalid-scope
  self-corruption, descendant symlink escape and contradictory backup choices.
  One bounded correction at `45e5e9aa4f350df3f464e3a536ccbcbe24556d8d`
  makes bulk explicitly unavailable with zero price writes, groups all
  onboarding-owned outputs with revision/path/volume preflight, propagates only
  storage/universe and hardware selection, preserves active risk/cost config,
  supports empty local startup and rejects unsupported backup claims before
  writes. Focused onboarding, import/export, universe, jobs, resource-profile
  and atomic-I/O tests plus Windows changed validation pass. Freeze one final
  documented head for both reviews and fresh H-tier package validation.
- Re-review rejected `d6abc257d27a657e3286915551265da5b08ac008` only
  for runtime-root/scheduler propagation and a reproduced junction swap; run
  `31394272704` is cancelled and stale. The final bounded correction
  `437c935ae9416c6723dd04880ccc45a21c3fd5f1` keeps the existing canonical
  project-local runtime root explicit, rejects unsupported custom roots before
  writes, removes incidental-CWD authority, applies the persisted hardware
  profile to the real durable scheduler at restart and same-session setup, and
  revalidates destination identity under the grouped-write precondition. The
  148-test focused surface has 147 passes and one platform-capability skip;
  Ruff, compile and diff hygiene pass. Freeze the fully documented replacement
  head for final parallel reviews and fresh H-tier validation.
- Final parallel review rejected `9e5d097565739ef9e4d2259e4f2f9877766c4b4c`
  after reproducing two persistence defects: onboarding reset an existing
  cross-tier-duplicate policy and a canonical universe save could be lost when
  it committed after onboarding's first revision check. Hosted run
  `31397877895` is stale and failed preflight because its Windows junction test
  invoked `cmd` on Linux. Consolidated correction
  `279e61541bdd8b87c72cec5b51e06839842543e0` preserves the policy, places the
  canonical saver under the same grouped guard with an in-guard CAS, adds the
  deterministic interleaving regression, and capability-skips the Windows-only
  junction test. The affected onboarding/universe/application surface, Ruff,
  compile and diff hygiene pass. Freeze one replacement head and repeat both
  exact-head reviews plus fresh Linux, Windows and terminal validation.
- Risk review approved replacement head
  `4842e62dec7349cc793f9e3a5ddafc2926a198e7`, while whole-diff review
  reproduced two remaining bounded defects: permitted cross-tier duplicate
  records were collapsed even though their policy flag survived, and persisted
  unsupported encrypted-backup metadata was accepted. Run `31401913671` was
  cancelled and is stale. Commit `9ae2fceab6a39643c33acc2f25bb88e9ea23495c`
  now preserves records according to the canonical same-tier/cross-tier policy
  and makes unsupported persisted backup preferences fail closed. Both
  regressions plus the affected focused suite, Ruff, compile and diff hygiene
  pass. Freeze this documented head for final exact-head reviews and fresh
  H-tier Linux/Windows/terminal validation; no further scope expansion is
  authorised absent a newly demonstrated defect.
- Risk review again approved `8c125409f1b388e696620205035fa2a553d696cf`,
  while whole-diff review reproduced the remaining identity gap: onboarding's
  local merge did not fully apply canonical instrument-ID, ticker and verified
  ISIN semantics. Run `31403933793` was cancelled and is stale. Commit
  `9304f1386047da4f6773e1901dbd44e5ba1c10b1` now preserves legal cross-tier
  identity duplicates and replaces later same-tier or disallowed collisions
  across all three canonical identities. The focused onboarding, universe and
  presentation-boundary guards plus Ruff, compile and diff hygiene pass. Freeze
  this documented head for final exact-head review and H-tier gates.
- Both final reviewers rejected `3059a24623a60a4a0ab0e98964e1602aeff79403`
  after reproducing one canonical identity-integrity defect: validation allowed
  legal cross-tier identities that schema-v3 reload dropped, tier tracking could
  miss a third same-tier reuse, and onboarding could collapse two distinct
  records when an incoming row matched them through different identities. Run
  `31405719378` was cancelled and is stale. Bounded H-tier commit
  `2023d1c7faebf18742a744e92d8f2c4aa89639a8` tracks all tiers per canonical
  ID/ticker/verified-ISIN, round-trips legal cross-tier records, rejects repeated
  same-tier identity, and fails onboarding before writes on ambiguous matches.
  ID/ticker/ISIN round-trip, triplet and no-write regressions plus the affected
  onboarding, universe, application and presentation-boundary suite pass.
  Freeze the documented head for final review and H-tier gates.
- Final review rejected `8abbce95706a5b18b71514615d2395a9aa00c46f`
  with five demonstrated persistence/integrity gaps: application config bypassed
  canonical universe integrity, onboarding lacked its own stale-writer CAS,
  backup state overstated durability, malformed ISIN authority was accepted,
  and unresolved disabled tickers could be re-enabled on resave. Run
  `31407286024` was cancelled and is stale. Consolidated H-tier commit
  `b959929168417b3642e42d6edf0464a2b83cbb8c` routes active config through the
  canonical decoder, adds checksum-bound onboarding CAS, records backup as
  unavailable/not enabled, validates verified ISIN shape/status, and preserves
  unresolved disabled ticker state. Deterministic integrity, concurrency,
  backup-state, ISIN and resave regressions plus the affected application,
  scheduler and architecture suite pass. Freeze the documented head for final
  review and complete H-tier gates.
- Parallel review rejected `b702dc288257226b875ea4326464b0038da13c47`
  because active config unnecessarily rejected valid schema-v2 snapshots and
  cross-tier duplicate instrument IDs conflicted with the application's global
  row-key/CRUD contract. Run `31410039718` was cancelled and is stale. Smallest
  safe commit `a7347395ffb006e3bf8721555e07d89388e7a038` restores canonical schema-v2
  active loading, makes instrument IDs globally case-insensitively unique, and
  retains cross-tier override only for ticker and verified ISIN. Onboarding
  deterministically replaces a same-ID row rather than creating duplicate row
  authority. Focused universe/onboarding/application/UI/architecture checks
  pass. Freeze the documented head for final review and H-tier gates.
- Parallel review rejected `a5efafe7eb1fc80f582500e1aee3bf3cdd3b035d`
  for six bounded compatibility/truth gaps: dotted/underscore ticker ID aliasing,
  non-boolean legacy override flags, boolean bootstrap row counts, stale
  unresolved-symbol metadata, overstated sample row counts and a misleading
  duplicate-policy label. Run `31413658110` was cancelled and is stale. Commit
  `14d50990583d583f9cbd88fd3977eebb7622aa23` preserves exact ticker IDs,
  validates legacy policy and onboarding evidence types/content, reports only
  newly selected sample rows and states the constrained override accurately.
  Focused onboarding/universe/application/UI/architecture checks pass. Freeze
  the documented head for final review and H-tier gates.
- Whole-diff review approved product behavior at
  `fdc74518806b33b987138cefa04fc344e11d637e`, while risk review reproduced one
  final integrity gap: application-written schema-v2 stores carried SHA-256
  revisions that legacy loading did not verify. Run `31416908410` was cancelled
  and is stale. Commit `f244709db135847508732cfd6398508928d8a3b3`
  verifies hash-shaped schema-v2 revisions on load and under onboarding's held
  group precondition while preserving genuinely legacy non-hash compatibility.
  Tamper rejection through both canonical and active config loaders and backup
  preservation are covered. Freeze the documented head for final review and
  H-tier gates.
- Both reviews rejected `82cebca3f749a11733de3d670ee1981a51715827`
  because integrity-invalid or revision-downgraded schema-v2 state could still
  be laundered through canonical save and backup. Run `31418506968` was
  cancelled and is stale. Commit `fb548c4467274a70a5c58277334c15db5aa07a8e`
  now requires explicit migration before schema-v2 active use/save, rejects
  integrity-invalid state before backup and again under the held guard, and
  blocks Universe Manager save when its snapshot reports integrity errors.
  Laundering, revision downgrade, no-backup and UI-block regressions plus the
  affected focused suite pass. Freeze the documented head for final review and
  H-tier gates.

## Superseded ISSUE-0016 product checkpoint

## Superseded ISSUE-0015 product checkpoint

- ISSUE-0014 product PR #665 merged exact reviewed head
  `576b5837e0ee096f9762c38122a7b439193001d4` as
  `0f45b6e7ece668c0cad9e34e6022b2cbaf53d619`; lifecycle PR #668 merged exact
  reviewed head `827225cb3b5f5f509dc024c713d9fa93efa35ad0` as exact main
  `830a00a84eebdb26e1099f3cb003898e9b0ceab2`. Ordered writer `31369949128`
  applied and verified the single aggregate `in_progress ->
  implemented_initially -> integrated` replay with two writes and
  `zero_action_readback=true`; generic convergence `31369949140` and the fresh
  exact-main readback both passed with zero actions. Reconciliation projects
  ISSUE-0014 `integrated` and `execution_allowed=false` remains.
- ISSUE-0015 is the next implementation-order issue and is canonically
  dependency-ready: priority P1, no blocking or activation dependencies,
  status `implemented_initially`, and required change "Drive the page from the
  canonical dependency and closure registry; show implementation, release,
  data, model, paper and live authority separately."
- Clean worktree
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0015_product`,
  branch `codex/issue0015-product-20260810`, was rebased from its prepared
  two-commit checkpoint onto exact base
  `830a00a84eebdb26e1099f3cb003898e9b0ceab2`. The bounded four-file product
  diff makes the existing `/roadmap` projection validate complete canonical
  registry, readiness, dependency-edge and closure evidence; fail closed on
  malformed or partial state; keep authority dimensions separate; and expose
  the unchanged `execution_allowed=false` policy. Focused programme-map and UI
  tests, Ruff, compile and diff hygiene pass after rebase.
- Before merge, complete checkpoint chronology, classify and validate the exact
  head, prepare every legal lifecycle component for the sole
  `implemented_initially -> integrated` completion, launch both independent
  reviews and required hosted CI on the same frozen head, and require the
  ordered writer plus generic zero-action readback after merge.
- First frozen head `05d73bb1ccef2eba3a6a378707dc1dd1f5a640cc` is rejected
  after both parallel verdicts were collected; its hosted evidence is stale.
  Both reviewers reproduced inconsistent dependency/activation edge evidence
  overstating readiness, and whole-diff review additionally reproduced a
  whitespace canonical ID escaping through `StopIteration`. One consolidated
  two-file correction recomputes the exact readiness projection from canonical
  ledger and reviewed edge evidence, rejects inconsistent projection fields,
  normalizes lookup without accepting malformed IDs, and adds both regressions.
  Freeze one replacement head after focused validation, then repeat both
  reviews and hosted tier-O validation in parallel.
- Both replacement-head reviewers rejected `cb6255ebfa1505fd3b793c2d7c80cd182feb313f`
  for one newly reproduced canonical-parity defect: reviewed edge dates were
  nonblank but not constrained to the generator's exact `YYYY-MM-DD` shape.
  The sole follow-up enforces that existing canonical rule and adds the exact
  malformed-date regression; no lifecycle, dependency or authority changes.
- Both reviewers then rejected `a90182bf7674c3409446f31f4a4eac0ac71fd76a`
  for the remaining canonical schema boundary: arbitrary/unknown IDs,
  non-folded local-only closure and absent per-blocking-edge evidence could be
  accepted even though canonical validation rejects them. The bounded closure
  enforces the existing canonical ID pattern and reference set, requires exact
  edge-evidence coverage, rejects nonempty local-only records, and adds the
  reproduced fail-closed regressions. No broader validator or workflow change.
- Reviewers rejected `b0266a75add96621258f0cdb5a6d47c9a6bda63c` for the final
  partial-record set: omitted dependency/input fields, whitespace or duplicate
  references, impossible reviewed dates, required-input mismatch and missing
  programme status. The consolidated closure now requires those existing raw
  canonical fields and semantic values exactly, with focused regressions; it
  does not change canonical content, dependencies, lifecycle or authority.
- Reviewers rejected `2858b94e0fcf820ecbf8e91ac5c6500d8439520a` for the final
  canonical-record invariants consumed by the map: required typed metadata and
  phase/priority, strict unresolved evidence, self/cycle rejection and exact
  generated reverse links. The bounded closure mirrors those existing
  canonical checks and focused probes only; it adds no new schema, status,
  dependency, workflow or authority.
- Whole-diff review approved `3296ebb707f82728bcd43efa34cc42e3b3d57bba`;
  risk review rejected only two outer-envelope gaps: declared package counts
  were not bound to actual records, and duplicate JSON keys used last-key-wins
  parsing. The exact follow-up checks both existing count identities and uses
  duplicate-key-rejecting JSON parsing with policy/record/readiness probes.
- Whole-diff review approved `7947d6fd65d5b0cb04b1385b90c1b9fc8fb127a0`;
  risk review reproduced one remaining count-type gap where JSON `true` could
  satisfy a one-record count. The single consolidated correction requires both
  declared counts to be exact integers and adds boolean/fractional regressions;
  focused roadmap/UI tests, Ruff and diff hygiene pass. Freeze one replacement
  head and repeat both reviews with fresh tier-O hosted validation.
- Replacement head `406408c8c70f3938000499fbecf672d3faf48e76` passed 46 focused
  roadmap/UI/route tests, Ruff and diff hygiene; both exact-head reviewers
  approved it and tier-O run `31378744478` passed classifier, supply chain,
  product/protected preflight and terminal validation. Product PR #669 merged
  that exact head as `70cf36d6be6033c1ffa6ab9cfa71204fe68ca8c8`.
- Clean lifecycle branch `codex/issue0015-lifecycle-20260810` starts at that
  exact main and contains only ISSUE-0015 `implemented_initially -> integrated`,
  its mechanically generated projections, one status-completion candidate and
  append-only sequence-20 authority. Fresh live plan
  `80858ee7873d8b479280e635575e351b96c377a7eb9736249d16a778ab401c7b`
  contains exactly one update; candidate and authority preserve
  `execution_allowed=false`. Complete exact-head E-tier guards/review, merge,
  then require the ordered writer and generic zero-action readback.

## Superseded ISSUE-0014 validation-repair checkpoint

- Product PR #665 merged independently approved exact head
  `576b5837e0ee096f9762c38122a7b439193001d4` as exact main
  `0f45b6e7ece668c0cad9e34e6022b2cbaf53d619`. H-tier run `31355486697`
  passed preflight, supply chain, Linux and Windows packages, terminal
  validation, both repeated pilots and cross-platform aggregation.
- Clean branch `codex/issue0014-bootstrap-replay-repair-20260810` starts at
  that exact main. Lifecycle preparation deterministically failed because the
  audited B00 ISSUE-0014 source predates transition history but the exact
  legacy bootstrap allowlist covered only ISSUE-0011 and ISSUE-0012. The sole
  H-tier correction adds ISSUE-0014's complete fixed source identity and a
  fail-closed parameterized regression; no replay shape, writer, authority,
  dependency edge, product code or execution permission changes.
- Both independent reviewers approved repair head
  `5e2a4358e825168b27194582bd30a69b47c5a7ca`; H-tier run `31364891591`
  passed preflight, supply chain, Linux, Windows and terminal validation. PR
  #667 merged it as exact main `35007496ae5052ef5ac41ede746ed76f1a48ab87`.
- The preserved lifecycle lane fast-forwarded cleanly to that exact main and
  now contains only ISSUE-0014's ordered `in_progress -> implemented_initially
  -> integrated` canonical transaction, mechanical projections, candidate and
  append-only sequence-19 authority. The fresh live plan is
  `956b10f1cc6b1501c3246aa6ee009b3478c8fe58ee965ec12de995ac690c7b5c`,
  candidate ref is
  `474bf56be46ae61e756103e4c90570db9879984cfed2b3f0f346ec7da7763387`
  and aggregate authority is
  `fa4fb0c9731d6ec134362d9ca08b583db0ea715609650ea934fa500805e71bcf`.
  `execution_allowed=false`; exact-head E-tier review/validation, merge,
  ordered writer and generic zero-action readback remain.
- An earlier Product PR #665 checkpoint was frozen at exact head
  `5ef8429547a36b6e127a142bb4e81b2e07f35fc6`; canonical lifecycle and
  `execution_allowed=false` are unchanged.
- H-tier run `31345050975` passed preflight, supply chain, Linux and Windows
  release packages, terminal validation and both repeated platform pilots.
  Cross-platform aggregation alone failed because the exact POSIX memory-limit
  parser test passed on Linux and intentionally skipped on Windows, while its
  existing platform-specific contract was absent from the explicit aggregator
  allowlist.
- Clean branch `codex/pilot-platform-outcome-repair-20260810` starts at exact
  main `c8a7da624c97f1a04191fd3ad1b7880bca83feec`. Its sole H-tier repair adds
  that exact test, outcome direction and three observed lanes plus a
  fail-closed regression. The corrected aggregator accepts the preserved run
  artifacts with zero other differences. Exact-head review and full H-tier
  validation are required before merge; then rebase PR #665 and repeat its
  invalidated exact-head review and validation once.
- Both verdicts for first repair head
  `9495b4eb5b26c2eec894fdbcc1d4b1b9b2070da6` were collected: risk review
  approved, while whole-diff review rejected only a self-referential predicate
  test that could not detect a wrong constant or omitted lane. Run
  `31349420262` was cancelled and is stale. The consolidated test correction
  hard-codes the exact contract, exercises complete report aggregation, and
  proves rejection of an extra lane, reversed outcomes and an unrelated test;
  focused tests, Ruff, mypy, compile, generator check and diff hygiene pass.
  Whole-diff re-review approved replacement head
  `218b412804d128dac1b0cc5b0831da46a3738103`, while risk review demonstrated
  that per-lane allowance still accepted a partial subset of the required
  three-lane signature; run `31349890546` is cancelled and stale. The final
  bounded correction requires the complete observed lane set to equal the
  exact three-lane contract and adds full-path regressions for each omitted
  lane. Whole-diff review approved head
  `4ce827bec114bf340be7b92b2a02829cfc30843f`, while risk review reproduced
  one final defect: unioning lanes across repetitions let a complete first
  repetition mask a partial second one. Run `31350158760` is cancelled and
  stale. The exact correction tracks and enforces the complete lane signature
  independently for every affected repetition and adds the reproduced
  second-repetition omission regression. Both final reviewers approved exact
  head `1af5bc4f9361e0100994fcfc0d5116a0d10768e2`; H-tier run
  `31350660155` passed classifier, preflight, supply chain, Linux and Windows
  release packages, terminal validation, both repeated platform pilots and
  cross-platform aggregation. PR #666 merged that exact head as main
  `784d10fe5e1d4c2a602e5a5cf5485379d50da924`.
- PR #665 now incorporates that exact main through integration commit
  `599f5a4e81e453916e4cdcf3320d1929aded3449` without changing ISSUE-0014
  product behavior or canonical lifecycle. Revalidate byte-clean generation,
  classifier and directly coupled repair tests, then freeze one replacement
  product head for both independent reviews and fresh H-tier validation.
  `execution_allowed=false` remains unchanged.
- Replacement head `aee786ec7d1bf127864d1a2b84346427844019e9` received whole-diff
  approval, while risk review reproduced one deterministic provenance defect:
  the workflow fixture pinned price and candidate clocks but not the yfinance
  reference-data provider clock. Its hosted run `31354453616` is cancelled and
  stale. The single consolidated correction pins the same fixed date for ETF
  metadata and holdings, supplies a real holdings fixture, and asserts both
  committed and audit-packet reference dates. Freeze one new head after focused
  validation, then repeat both reviews and fresh H-tier validation in parallel.

## Current ISSUE-0010 product checkpoint

- ISSUE-0104 completion PR #656 merged independently approved exact head
  `2e183215d64ba7cdb3bf1dc649bfeca62eb9dad5` as exact main
  `43b7561b910758aafe7c5501803fbcbe86fd197b`. Release run `31265876805`
  passed classifier, preflight, supply chain, authoritative Linux and Windows
  packages and terminal validation; guard `31265876806` passed.
- Ordered writer `31267257715` applied the sole aggregate ISSUE-0104
  `in_progress -> implemented_initially -> integrated` replay with one proposal
  and receipt, `terminal_status=applied_and_verified` and
  `zero_action_readback=true`. Generic convergence `31267257761` passed. A fresh
  exact-main generic readback has zero actions; canonical state and GitHub issue
  #244 both resolve to `integrated`, and `execution_allowed=false` remains.
- ISSUE-0010 is dependency-ready with no blocking inputs. Clean worktree
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0010_product_v3`,
  branch `codex/issue0010-product-20260809-v3`, starts empty at exact main
  `43b7561b910758aafe7c5501803fbcbe86fd197b`.
- The bounded scope is a local, non-executable LLM thesis diary with exact
  generation provenance, immutable/reproducible forward-only lifecycle,
  disclosure-safe redaction export and behavioral isolation from scores,
  optimisers, risk gates, proposals and orders. It must preserve
  `execution_allowed=false` and requires H-tier persistence validation.
- The first prepared product head
  `ede07a26d6556e0caff79a78ecb10aa935f3fbcf` passed its focused suite but was
  rejected after both parallel reviews. Their complete finding set is
  cross-process lost updates, future-observation replay, reconstructed rather
  than exact prompt provenance, stale UI lifecycle projection, unsafe
  redaction export, missing behavioral non-interference proof and incorrect
  non-H classification.
- Consolidated correction commit
  `f535c0dec6285de2a31a4b515fd83f907b8eadc1` passed focused adversarial
  validation and was transplanted once onto this exact-main lane without
  conflict. Canonical inputs now record only the legal ISSUE-0010
  `planned -> in_progress` transaction and all generated projections are
  byte-clean.
- Live plan `e85ef463b0ec18b3b33ffdbf20c449fc26915d302bf66a6f0e8014aa80db782f`
  contains one status-only update for GitHub issue #14. Append-only authority
  `52a917e9e678729a974545b08dc8ef74abe6079168af8270dd430d9b2e262e80`
  and candidate ref
  `6741dbdac63e87a11dc6671e305bf04d623e72cd91b03fb45c23d9a78418e4ee`
  bind it to exact parent `43b7561b910758aafe7c5501803fbcbe86fd197b`
  and preserve `execution_allowed=false`. Focused adversarial tests, exact
  status guard, byte-clean generation, H-tier classification and the exact
  one-action candidate validation pass. Freeze this completed tree and start
  both independent reviews and H-tier hosted CI in parallel.
- Frozen head `b3afaa2ab790e13af439e4db5f7fb883d9224cfb` was rejected
  after both parallel reviews completed. Their consolidated findings were
  current-time future-event leakage, redaction disclosure in UI/export,
  partial multi-instrument generation writes and unbound request/model/response
  provenance. H run `31269127682` also timed out preflight because two changed
  broad test modules took 65 and 109 seconds before packages could start.
- Consolidated correction `d28da1de5c367a85077cfda333730c3b2d6a25c9`
  closes all findings with one atomic generation batch/report transaction,
  effective-current replay and redaction cutoffs, fully scrubbed current UI,
  exact semantic provenance binding and explicit synthetic fallback records.
  The two broad tests now match base; dedicated ISSUE-0010 modules reduce the
  exact changed-test selection to 42.3 seconds on Windows.
- Replacement head `f1462202e8630cb6f41623a59ac4e0ed9575ea3d`
  passed byte-clean generation, transition guard, H classification, live
  candidate validation and focused local validation. Both parallel reviewers
  rejected it only after all verdicts were collected: generated entries used
  snapshot time rather than actual response availability, and immutable
  entry/packet validation trusted self-consistent hashes without rechecking
  exact request/model/raw-response/commentary semantics. Release run
  `31270403242` is stale and must not be reused.
- One consolidated four-file correction now hash-binds stable response
  availability to both creation and decision time, preserves snapshot
  `as_of_date` separately, revalidates exact provenance at immutable-entry and
  packet boundaries, and adds focused historical replay, mismatch and retry
  regressions. Head `e8a122f00bba59712a3afb010edddcda84142744`
  passed 37 exact changed tests in 41.8 seconds plus all exact control checks,
  but both parallel reviewers found one final consolidated boundary set:
  caller-context reuse could backdate a later response, malformed synthetic
  provenance and redaction markers were accepted, and packet replay omitted
  store chronology/unique-event invariants. Release run `31271660658` is stale.
- The permitted final correction keeps generation availability in the frozen
  response status and passes it through the UI save path without mutating the
  request context; requires strict exact/synthetic provenance; enforces fully
  scrubbed, internally consistent redacted entries; and reuses full store event
  history validation for packet replay. Head
  `d83b691c5cfd3d449a002726013296ce2969d917` passed 46 exact changed tests in
  44.5 seconds and all control checks, but exact-head adversarial review then
  demonstrated three remaining PIT gaps: save context was not bound to the
  generated request context, safe exports retained post-cutoff event payloads,
  and future-dated evidence snapshots were accepted. Release run
  `31273205539` is stale.
- The final bounded correction now retains and deep-copies the immutable
  generation context, requires every exact request to carry that context and
  rejects any save mismatch, filters exported entries/events to the effective
  cutoff while rebuilding chains and checksums, and rejects recognized snapshot
  dates/timestamps after decision availability. Head
  `3c702a546e85b0f03225885e5ef58fa42f3471de` passed exact changed/control
  validation, but reviewers demonstrated nested metadata timestamps bypassing
  the top-level bound, retroactively backdated expiry payloads, and exact saves
  with availability before their required snapshot date. The bounded closure
  recursively validates recognized temporal fields through dictionaries/lists,
  requires exact audit contexts to carry an ISO snapshot date, and rejects an
  expiry before its event time. Focused mutation/retry, future-payload/readback,
  nested-future-evidence, historical-availability and expiry regressions pass.
  Exact head `79ec77ba659659dfee8fba54d764c6a93daa3af7` received both
  independent approvals. H run `31275348236` then failed identically on Linux
  and Windows only because the existing malformed-transition fixture still
  constructed obsolete ISSUE-0010 `in_progress -> ready`, masking its intended
  malformed date/commit/evidence errors. The bounded test-only correction now
  derives the legal next hop before injecting each malformed field; all seven
  adversarial cases pass. Replacement head
  `6b5a00b34e6d5c992c5a182428b3df648a704489` received both independent
  approvals and passed the exact status guard. H-tier run `31276736844` then
  timed out the unchanged exact changed-test selection at 120 seconds in both
  the initial attempt and its single permitted retry; authority preflight and
  supply-chain validation passed. The sole bounded correction preserves all
  seven independent malformed-event assertions while exercising the two
  generic registry entrypoints once instead of redundantly for every malformed
  variant. The exact local selection passes in 65.3 seconds. Head
  `8023867cd48c27f35a439e4f3fd9a8602de44a3e` received both independent
  approvals and exact guard `31277808316` passed. Release run `31277808312`
  nevertheless reproduced the same 120-second changed-test timeout before
  packages; fresh authority and supply-chain validation passed. The single
  demonstrated harness correction assigns only changed-test execution a
  bounded 240-second ceiling, leaving every selected test, classifier, H-tier
  package and terminal requirement unchanged, with a direct timeout-contract
  regression. Head `4670c084fcfec15342527652c90a9968205485af`
  passed exact guard `31278463750`; hosted run `31278463749` passed authority,
  supply chain and the full changed-test preflight in 125.2 seconds before its
  now-stale package jobs were cancelled after whole-diff review rejected the
  head. The risk reviewer approved. The consolidated final findings were an
  accepted contradictory redaction state retaining raw content and nested
  future timestamps in outcome details bypassing the PIT bound. The bounded
  product correction enforces redaction-state/content consistency and reuses
  the existing recursive temporal validator for outcome details, with direct
  adversarial regressions. Replacement head
  `e10b9914f4806f0e3e549cd3f74edb1c4132455e` passed the full exact changed
  selection in 69.9 seconds and guard `31279691735`; its now-stale H run
  `31279691720` was cancelled after risk review found two further deterministic
  defects, while whole-diff review approved. Case variants of a thesis ID could
  collide on a Windows path and tuples could bypass recursive PIT checks before
  JSON normalization. The consolidated correction adds casefolded collision
  rejection inside single/batch transaction boundaries while preserving the
  original entry, and traverses tuple arrays in the existing recursive temporal
  validator for snapshots and outcomes. Replacement head
  `5d11f10d95931b3971b33e606920aed526a0b570` passed the exact changed suite
  in 71.8 seconds and received risk approval; its stale H run `31281223390`
  was cancelled after whole-diff review required restoration of all seven
  malformed variants through both generic registry entrypoints and rejection
  of nested `executable_authority=true` in synthetic provenance. The bounded
  correction restores those entrypoint assertions now that the 240-second
  ceiling is proven and recursively rejects executable-authority markers in
  JSON-compatible synthetic metadata. Final reviewed product head
  `19bbee09aef0f4bb19faa72183510c0dc5975973` passed exact guard
  `31281965468` and H-tier run `31281965469`, including fresh Linux, Windows
  and terminal validation, then merged in PR #657 as exact main
  `dbb53c04a17327b8b97a73c8841c5368c2e82c9f`.
- Ordered writer `31284329688` applied only ISSUE-0010 `planned -> in_progress`
  with `terminal_status=applied_and_verified` and zero-action readback;
  generic convergence `31284329681` passed and `execution_allowed=false`
  remains. Clean completion lane
  `codex/issue0010-completion-20260809` starts at that exact main with an empty
  diff. Its sole scope is the existing atomic ISSUE-0010
  `in_progress -> implemented_initially -> integrated` replay, bound to PR
  #657, the reviewed merge, reviews and exact validation evidence. Canonical
  inputs are updated first and generated projections are byte-clean; no
  product, dependency-edge or authority-framework change is permitted. The
  classifier keeps this control-only transaction E-tier. The base-anchored
  reusable sidecar predates ISSUE-0010's product changes, so it cannot
  self-authorize replacement in this transaction and the hosted package gate
  remains required. Frozen head `cfbe45a129f0e0ce47341bde514f6f1ab99570a3`
  received risk approval, but whole-diff review found one stale generic
  control-plane negative fixture: after ISSUE-0010 became `integrated`, its
  hard-coded `closed` target was legal rather than a skip. Stale release run
  `31285303818` was cancelled. The consolidated test-only correction now
  chooses a canonical record with an available two-step forward skip and
  derives that invalid target, preserving the rejection across later status
  changes; the exact reproduction suite passes. Because this required test
  correction is an ordinary test surface, the replacement transaction
  classifies O-tier; exact-main cadence is known and not due, so hosted
  preflight, supply-chain and terminal validation remain required while Linux
  and Windows packages are not required for this replacement head. Whole-diff
  re-review approved, but risk re-review found the correction's `planned ->
  in_progress` table entry was itself legal. The final test-only closure maps
  `planned -> implemented_initially` and asserts every selected skip is absent
  from `CONTROL_ALLOWED_TRANSITIONS`, eliminating dependence on future
  canonical status ordering.
- Final completion head `4abb1d92830801d73045aa1499f4cec71caec8a4`
  received both independent approvals, passed guard `31286274630` and O-tier
  release run `31286274627`, then merged in PR #658 as exact main
  `f6104403ab0f5e4e007700e5cbc1870429370f27`. Writer `31286431060`
  applied one aggregate proposal and receipt with
  `terminal_status=applied_and_verified` and `zero_action_readback=true`;
  convergence `31286431065` passed. GitHub issue #14 and canonical state agree
  on `integrated`; fresh generic plan
  `51be8c545bc6f962076d2c310067748d72ab9a519378c09c18119040e768dafc`
  has zero actions and `execution_allowed=false` remains.
- ISSUE-0011 is dependency-ready and selected next. Clean branch
  `codex/issue0011-product-20260809` starts at exact main
  `f6104403ab0f5e4e007700e5cbc1870429370f27`. Its bounded product scope is a
  deterministic main-UI action inventory generated from registered controls,
  routes and command metadata, with stable unique IDs, bound command
  contracts, visible failure states, six required workflow lanes and no
  execution authority. Rejected head
  `eefdd8b613cd0bf34d2414d35fd624ded2e90bd8` omitted post-construction and
  keyed input/file-picker bindings, trusted editable signals and substring
  lane labels, lacked a real route failure surface and could not resolve its
  contract from an installed wheel; its evidence is stale. The consolidated
  uncommitted correction discovers and validates 238 source/config contracts
  and generates 282 contracted actions (202 controls, 40 routes and 40
  commands). It fixes the paper-open and stock-research parity regressions,
  binds exact callbacks and deterministic signals/lanes, renders controlled
  unknown/builder route failures, invokes inventory validation in package
  smoke and preserves `execution_allowed=false`. The 43-test focused suite,
  Ruff, compile, diff hygiene and byte-clean generation pass. A locally built
  wheel installed outside the source tree generates the same 282-action
  inventory twice and validates all actions as non-executable. Exact head
  `aa1453f6eec7ad57e40b778ae86b9118d2334c53` was then rejected because
  unresolved lambda/setattr controls could accept invented callbacks, the
  synthetic-scenario action was a no-op, universe edit cancel metadata was
  false, palette command metadata named a different runtime path, and failed
  invocation replay returned a success signal. The final uncommitted
  correction fails closed on every unresolved discovered callback, gives the
  seeded synthetic action deterministic visible success/failure behavior,
  names the existing universe dismissals truthfully, directly binds palette
  result controls to `select_palette_command`, and stores/replays the original
  completed or failed terminal result without a second callback. Two disjoint
  focused selections pass 100 tests; Ruff, compile, diff hygiene and byte-clean
  generation pass. The exact classifier returns H because the product diff
  changes `pyproject.toml` and `scripts/smoke_app.py`; evidence reuse is false,
  package gate is required, and fresh exact-head Linux and Windows hosted gates
  remain mandatory after review freezes the replacement head. Rejected head
  `e52308309e4817447696f8a219556df67da6a5ba` was then shown to leave direct
  result-button dispatch outside terminal replay, collapse command-palette
  change and submit events into one control contract, and silently omit orphan
  configured inputs. The final bounded uncommitted correction routes the real
  result `on_click` through its generated `navigate_palette_command` contract,
  keeps completed/failed terminal results across direct duplicate dispatch,
  inventories stable `shell.command-palette.on-change` and `.on-submit`
  actions with exact callbacks, and rejects every unmatched actionable/input
  contract. Fourteen passive fields falsely declared as input actions were
  removed from metadata without changing their UI. The resulting 225 metadata
  contracts generate 283 actions (203 controls, 40 routes and 40 commands),
  all non-executable. Two focused selections pass 87 tests; H classification
  and fresh hosted Linux/Windows requirements are unchanged. Exact head
  `de14e2ea9f4dc366067ea6fc3e0bb0f03041c491` passed whole-diff review but
  risk review found that direct dispatch did not return its preserved terminal
  result. The final correction returns that existing result and directly
  asserts completed/failed status, signal, message and replay state; its
  focused regression, Ruff, compile and diff hygiene pass. Exact head
  `962d3bca6ccffca5f4d4548640689b6d7d52415c` was then rejected because a
  direct named event callback was accepted even when its symbol was undefined,
  and `select_palette_command` still declared `None` despite returning the
  preserved `UIInvocationResult`. The bounded uncommitted correction checks
  direct source callback names against module imports/definitions and their
  enclosing parameters/local bindings while preserving nested, imported,
  parameter, post-construction, attribute and lambda callback forms. The
  palette handler now returns `UIInvocationResult | None` explicitly. The
  29-test focused selection, targeted two-file MyPy with return checking,
  Ruff, compile and diff hygiene pass; the exact 225-contract/283-action
  non-executable inventory and H classification remain unchanged. Exact head
  `ceb1fd963f303cf1b68e528cbdfdda397196f39d` was then blocked because the
  full targeted MyPy command still found an un-narrowed route-metadata index
  and two `importlib.metadata.SimplePath` conversions, while a lambda wrapper
  could still call an undefined callback name. The final bounded uncommitted
  correction narrows page-title metadata to a non-empty tuple, converts
  installed distribution paths through their string representation, and
  validates direct names called inside lambda event wrappers against the same
  available-symbol set. The exact two-file MyPy command passes without
  error-code exclusions; the unavailable PyYAML stub uses the repository's
  narrow import annotation. The 30-test focused selection, Ruff, compile and
  diff hygiene pass. The exact
  225-contract/283-action non-executable inventory, package mechanics and H
  classification remain unchanged. Exact head
  `1944caa539d0f63ed0de52ccdd7e9cb6dfc3abec` received both independent
  approvals. H-tier run `31293133592` passed Linux full tests, package build,
  source/package parity and every policy check, but Linux package smoke failed
  because the extracted sdist's partial `tests/` tree was mistaken for a
  repository checkout and an intentionally absent acceptance-test source was
  required at runtime. The bounded package correction requires acceptance-test
  files only when a `.git` checkout marker exists and adds the exact
  package-versus-checkout regression. The runtime contract and 283-action
  inventory are unchanged; fresh exact-head H gates remain required.
- ISSUE-0011 is already canonically `in_progress`; the product PR therefore
  carries no artificial status or dependency transaction. Before product
  merge, retain exact product/review/gate evidence and the post-merge writer
  expectation. After the reviewed merge exists, prepare the existing atomic
  `in_progress -> implemented_initially -> integrated` replay against that
  exact product commit and require the authorized writer plus zero-action
  generic readback. Product PR #659 merged independently approved exact head
  `b782a9f75d4e6653ddc6ee1dbd733e8e775c24cc` as
  `18b93e91ed8c9152e509d70ae0548b57550606fa` after H-tier run
  `31295173994` passed Linux, Windows, package smoke and terminal validation.
  The clean completion lane then reproduced one deterministic legacy-prefix
  defect: B00 imported ISSUE-0011 directly as `in_progress` before
  `transition_history` existed. The single bounded H repair accepts only that
  exact bootstrap-empty origin across preparation, writer and terminal
  validation; the ordered two hops, authority, dependency state and
  `execution_allowed=false` remain unchanged. Repair PR #660 merged reviewed
  exact head `3ee6f811495149a4a526ea1335cd941a6012c766` as
  `79ef677112f89c74b0ac652ede04a4411646b4d9` after H-tier run
  `31299002822` passed Linux, Windows and terminal validation. The preserved
  completion lane is rebased onto that exact main and prepares only GitHub
  issue #15 at live plan SHA
  `5081667a34d01125c464d622c59a9fce715c9097d5d7f5cf08e67ba9e4317ea0`
  under aggregate authority
  `c417a1345e877422ea30dcaac81a23bf1cf72cf544edec2186a8f0a85a05572b`;
  the expected post-merge writer and generic readback remain one applied
  replay followed by zero actions.

- Completion PR #661 merged independently approved exact head
  `0d789d0550a38c107b427bec40ac6bfff98ce5da` as
  `a80aa32a3c6ffaeb5e7075d152c2d4cce9e888ea`. Status guard run
  `31300304421` and release run `31300304453` passed. Writer run
  `31301505274` returned `applied_and_verified` with an acceptance receipt and
  `zero_action_readback=true`; fresh generic exact-main readback has no
  actions at plan SHA
  `da8f7f0f36d1a9c9124b02634176b51b3e9e11cddbebcf39457cdeec9f615ef1`.
  GitHub issue #15 resolves to canonical `integrated` and
  `execution_allowed=false` remains.
- ISSUE-0012 is the next implementation-order, dependency-ready issue. Product
  commit
  `43fcbca8f5960af7f54f48bb94e0d08682f49c78` is rebased onto the
  repaired main and remains locally green. Exact-main lifecycle preparation reproduced
  `ISSUE-0012: status replay transition history prefix must be a list`; the
  failed projection remains isolated in worktree
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0012_lifecycle_premerge`
  at live one-action plan SHA
  `8e3778a20cd1b1c64da5c69347238c017c932f56d1f16649bd7a2dd8847fe3aa`.
  Repair PR #662 merged independently approved exact head
  `f23e814127fc62db4c936e9b4788ff7b242d2288` as
  `5718ed5a2cb961985a215a25277951c271c4571d` after H-tier run
  `31303632447` passed Linux, Windows and terminal validation. Only complete
  fixed ISSUE-0011 and ISSUE-0012 B00 records may use the empty prefix; every
  other identity or malformed source fails closed. Hops, dependencies, retry
  behavior, authority and `execution_allowed=false` are unchanged. Product
  worktree
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_issue0011_readback`,
  branch `codex/issue0012-product-20260809` starts at exact main
  `5718ed5a2cb961985a215a25277951c271c4571d`. Scope is the existing shared
  workflow-status service and persistent activity/run-log contract extended
  across every declared long-running workflow, with visible started/step/
  progress/success/failure/timestamp/output/error state and no execution or
  external-write authority.
- Fresh exact-main lifecycle proof after the repair generated one ISSUE-0012
  action at plan SHA
  `8e3778a20cd1b1c64da5c69347238c017c932f56d1f16649bd7a2dd8847fe3aa`
  and prepared aggregate authority
  `e1b1ea5d819d666f8a1b8b2d27ce683772ad35dd1f59de8e6458e5ff102004f1`.
  The status guard correctly prohibits embedding that replay in the product
  PR because product commit `43fcbca8f5960af7f54f48bb94e0d08682f49c78`
  is not yet an ancestor of the reviewed generation base. The product PR
  therefore remains product-only; immediately after its exact reviewed merge,
  regenerate the already-proved compact completion transaction from the new
  main, validate the writer, and require zero-action generic readback.
- Product PR #663 head `b1023cf53a4634c8fc4c7263660677ffc10364a3`
  was rejected by both exact-head reviewers. Their persistence, cancellation,
  runtime-binding, terminal-status, redaction and visible-timestamp findings
  were collected before one consolidated correction. Correction commit
  `3303ac2f` preserves the session trace across restart, binds every publication
  to its owning action and cancellation state, records unavailable outcomes as
  failures, emits forecast stages at their actual service boundaries, exposes
  the macro/news action, redacts cache errors and renders start/output/error
  evidence. Attributable focused evidence passed 18 lifecycle/startup tests,
  the remaining startup tests in bounded groups, 31 workflow/resource/macro
  tests, 21 button/accessibility tests, 54 import/report tests, 3 forecast
  tests, 10 event-log/redaction tests, Ruff, compileall and diff checks. The
  exact classifier keeps the replacement product head O-tier with no packaged
  gate due; freeze it only after this checkpoint and run whole-diff review,
  risk review and the exact-head hosted release gate concurrently.
- Replacement head `f82ddaf8748787bf9ea51fdbf37eff933ecdd511`
  passed hosted run `31306934161` but both reviewers rejected its cancellation
  publication boundary, so that CI evidence is stale. The whole-diff review
  also found non-atomic concurrent starts, raw UI exceptions, ESEF unavailable
  success and stale non-dashboard progress rendering. One final consolidated
  correction commit `eff4ba5c` makes activity starts atomic, reserves cancelled
  ownership until callback exit, and uses the same lock for one verified
  durable publication at a time. Cancellation therefore wins before a write
  or waits for that write and rejects every later write. It also redacts UI
  failures, records ESEF unavailability as failed and rebuilds the shared shell
  on non-dashboard terminal events. Focused correction evidence passed 24
  ISSUE-0012 tests and 201 coupled workflow/startup/import/holdings/disclosure/
  release-hardening tests plus Ruff, compileall and diff checks. Re-freeze only
  after this checkpoint, then repeat both reviews and hosted O-tier validation
  against one exact head.
- Exact head `aadea38329f051523c18e235b67040c1852d5150` was rejected by
  both parallel reviewers for five newly demonstrated terminal-integrity
  defects: an update/cancel mutation race, non-atomic session-log compaction,
  unguarded snapshot-derived writes, disclosure unavailability recorded as
  success and remaining raw job/provider errors. Consolidated correction
  commit `9e77291d` linearizes update mutation with the controller transition,
  stages/validates/fsyncs/atomically replaces compacted history, scopes feature
  and backtest publications, re-raises cancellation from reference import,
  fails unavailable disclosure terminals and removes raw exception text.
  Focused evidence passed 33 ISSUE-0012 tests, 143 directly affected tests and
  41 yfinance/release-hardening tests plus Ruff, compileall and diff checks.
  Repeat both independent reviews and hosted O-tier validation against the
  final checkpointed head; do not reuse the rejected head's evidence.
- Exact head `61fdc2ac636946d7bf1d69201881faf01e96fecf` was rejected
  after both reviewers confirmed unguarded sample/API-status/rollback writes;
  risk review also found restart recovery depended on secondary activity
  events instead of canonical workflow events. Correction commit `fb0916fc`
  now recovers start/step/finish/cancel directly from the existing locked
  `workflow_*` events when richer activity events are absent, and threads the
  lock-held publication scope through sample inputs, clean prices, rollback,
  API/yfinance status and snapshot initialization. Provider failures are
  redacted and unavailable status is terminal failure. Focused evidence passed
  40 ISSUE-0012, 51 rollback/yfinance and 23 workflow/startup tests plus the
  directly coupled release/trust regressions, Ruff, compileall and diff checks.
  Protected clean-price-store coverage makes the new checkpointed head H-tier;
  repeat both reviews and hosted Linux, Windows and terminal validation. Prior
  hosted runs are stale.
- Exact head `2edf3a41a078e3db4a7f2033bf318cb2c4283c39` whole-diff
  review found the remaining in-scope gap: SEC/OAM/ESEF/manual filing controls
  bypassed the shared lifecycle. Correction commit `116c80c1` routes all
  seven controls through canonical activity ownership, guarded publication,
  unavailable/redacted terminals and shell refresh, and adds their catalog
  entries. Focused evidence passed 49 ISSUE-0012 and 156 filing/trust/UI tests,
  deterministic SEC cancellation publication evidence, Ruff, compileall and
  diff checks. Risk review separately reproduced cross-process session-log
  contention and pre-existing crash-atomicity gaps in broad financial/audit
  writers; record those as later persistence hardening and do not expand this
  product issue into a new locking or generation framework. Repeat scoped
  whole-diff and risk review plus full H-tier hosted validation on the final
  head.
- Exact head `39a7016ee9742979d6e0eff237672b4556af1e72` was rejected
  for four scoped recovery gaps: truncated-tail startup append failure,
  synchronous filing work without a reachable cancel control, disclosure
  losing-start cleanup and retries bypassing canonical activity ownership.
  Correction commit `d8dd2344` applies existing bounded tail recovery before
  append/compaction, runs official filing work in the existing background
  pattern with a persistent-shell cancel control, handles atomic-start losers
  safely and makes retries re-enter the decorated lifecycle wrapper. Focused
  ISSUE-0012, startup, error-recovery, trust and button evidence passed with
  Ruff, compileall and diff checks. Re-run both scoped reviews and the full
  H-tier Linux/Windows/terminal gate on the final checkpointed head.
- Exact head `5336501786e19bdb6102b7dd5517fb032f2d6cb1` was rejected
  after both scoped reviewers completed. Their consolidated findings were
  worker-lifetime handling of byte-backed browser uploads, stale success text
  after cancellation, missing official-filing retry re-entry, synchronous
  document/report/holdings/KID/methodology imports, ESEF discovery publishing
  after cancellation and path-only picker handling. Correction commit
  `8bb8bfcdf38e9b1ce23595bf789f29c96e3da343` routes every affected import
  through the existing background lifecycle, materialises path/byte uploads
  for exactly the worker lifetime, restores canonical cancellation messages,
  binds ESEF publication to the owning action and makes retry callbacks
  re-enter that lifecycle. Focused ISSUE-0012 and coupled trust/button/error-
  recovery/startup evidence passed with Ruff, compileall and diff checks.
  Freeze one checkpoint head after this chronology update; both scoped reviews
  and fresh H-tier Linux, Windows and terminal validation remain required.
- Exact head `de06050914635a3bb736f504e39c3bf73021cbbc` was rejected
  after both parallel reviewers completed. Their consolidated findings were
  late success text surviving canonical cancellation in generic helpers,
  synchronous cache rebuild without safe retry, and synchronous notes/news
  imports without reachable cancellation or retry. Hosted H-tier run
  `31317068279` separately passed generation, smoke and supply-chain controls
  but timed out its six-module changed-test selection at 240 seconds before
  Linux/Windows packaging. Correction commit
  `633e64607c070c05e6306aab3de6a0a1b17f4a3d` restores canonical cancelled
  messages in every affected finalizer, moves both actions onto the existing
  background lifecycle, guards cache deletion and preserves safe retry. Five
  lightly edited broad test modules are restored to base without weakening
  their full-suite assertions; the actual changed-test set is now ISSUE-0012
  plus Flet startup and passes locally below the hosted window. The five
  restored modules also pass independently, focused ISSUE-0012 and correction
  regressions pass, and Ruff, compileall and diff checks pass. Freeze one new
  exact head after this checkpoint, then repeat both reviews and fresh H-tier
  Linux, Windows and terminal validation; rejected-head evidence is stale.
- Exact head `fb9ebd6dff118dfa19a784245f09d4534b88c33d` was rejected
  after both parallel reviewers completed. The newly demonstrated final gap
  was cancellation reachability: validation, renew imports and cache cleanup
  did not rerender the persistent shell at start, while accepted ChatGPT and
  Import/Export audit controls still ran synchronously and their retry paths
  did not re-enter each complete operation. Its hosted run `31319351588`
  passed preflight, including the corrected changed-test window, but was
  cancelled/disregarded during Linux/Windows packaging after review rejected
  the head. Correction commit
  `e3df8c194fd3b85077dfa532f9b564ce72207d12` immediately exposes the shell
  cancel control for every affected start, routes all three registered audit
  exports through background owned lifecycles, restores cancellation and
  retries each full operation including ChatGPT archive validation. The
  generated action-control catalog now enumerates every registered control.
  Focused ISSUE-0012 passes 71 tests; the exact changed-test set passes in
  115.5 seconds without warnings, with Ruff, compileall and diff checks green.
  Freeze one final exact head after this checkpoint and repeat both reviews
  plus fresh H-tier Linux, Windows and terminal validation.
- Exact head `2a91dd466be9a70d868a82c53956181f7b10b738` was rejected
  after both parallel reviewers completed. All runtime lifecycle findings were
  accepted; the complete residual set was two missing Dashboard holdings/
  factsheet keys in reverse action-control coverage and an empty file-picker
  terminal that cleared activity before the final shell rerender. Hosted run
  `31320604306` passed corrected preflight but was cancelled/disregarded during
  Linux/Windows packaging after rejection. Correction commit
  `72792c1c3533e4d4c25b05fd10ef270f1555c7e2` adds exact and reverse catalog
  coverage, records both accepted Dashboard controls and always rerenders the
  picker terminal. Focused ISSUE-0012, Ruff, compileall and diff checks pass.
  Freeze the replacement exact head after this checkpoint and repeat both
  reviews plus fresh H-tier Linux, Windows and terminal validation.
- Exact head `0216f820eb7c111cd95c0bc287d50e05e6b526c0` received whole-diff
  approval and one consolidated risk-review finding: four accepted disclosure
  import controls were absent from reverse-complete action-control coverage.
  The bounded correction adds those existing controls and derives the reverse
  completeness regression from the accepted disclosure-import buttons. Its
  hosted evidence is stale; freeze one replacement head after focused checks,
  then repeat both reviews and fresh H-tier Linux, Windows and terminal gates.
- Exact head `a5144b49ed996af95f4a1706d8bc5f87d97b9742` received risk-review
  approval and one newly demonstrated whole-diff rejection: browser byte
  uploads left document/holdings registries bound to deleted temporary paths,
  and only five of seven accepted controls were config-derived in the reverse
  regression. The final bounded pass reuses checksum-addressed raw retention
  before those registry writes and derives the exact seven-control set from
  UI acceptance. Its hosted evidence is stale; focused checks, both reviews
  and fresh H-tier Linux, Windows and terminal gates remain required.
- Exact head `daa23b34a6c54faf5b0c0d85920cbc442a94e65f` passed 109 focused
  cases in whole-diff review but received one truthful-authority risk finding:
  its new holdings test rewrote `manual_unverified` to `issuer`, masking the
  production callback's pre-persistence rejection. The narrow final repair
  permits only structurally valid non-score manual context in the existing
  atomic holdings/document importer, preserves `source=manual_unverified`,
  `authority=unknown`, `score_eligible=false`, binds the document with
  `manual_unverified` authority and removes the test rewrite. Rejected-head CI
  is stale; both reviews and fresh H-tier gates remain required.
- Exact head `a1e1f756343453850991c7eb3ade23f443d1c78c` received both code/risk
  approvals, but Linux H-tier run `31324672892` deterministically failed one
  unchanged legacy cancellation assertion. The newer reviewed ownership
  contract reserves a cancelled activity until its callback exits so late
  publication cannot overlap a replacement action. The bounded test-only
  correction now asserts that reservation, explicit owner release and durable
  cancellation log; no runtime behavior or authority changes. Repeat both
  exact-head reviews and fresh Linux, Windows and terminal H-tier validation.
- Final product head `043c14f8f88aa79911e378a390477521584d4da3`
  received independent whole-diff and risk approval. H-tier run `31326072782`
  passed preflight, supply chain, Linux, Windows and terminal validation after
  the single documented retry of a native pandas C-parser crash. PR #663
  merged that exact head as `c9efd6b351db76290e3371314d67c986406168f5`.
  Clean lifecycle branch `codex/issue0012-lifecycle-20260810` starts at that
  exact main and contains only the canonical two-hop
  `in_progress -> implemented_initially -> integrated` completion, mechanical
  projections and append-only status-replay authority. The live plan SHA is
  `8e3778a20cd1b1c64da5c69347238c017c932f56d1f16649bd7a2dd8847fe3aa`;
  aggregate authority is
  `60d2ce9cc6057817850dcb42ca1ed7e51c5ddbb96d9415280d557e134bcc7206`.
  Both exact-head reviews approved after fresh lifecycle run `31328999996`
  passed Linux, Windows and terminal validation and guard run `31328999997`
  passed. PR #664 merged exact head
  `30be81ef0c73059331cbe9b2268e66f9f02314c6` as
  `c8a7da624c97f1a04191fd3ad1b7880bca83feec`. Writer `31330290295`
  returned `applied_and_verified` with one aggregate proposal and receipt and
  `zero_action_readback=true`; generic live readback is zero-action at plan
  SHA `999f68c57c2ec349c21280aa94b751a6dac5130a9d03981d2d63a72bdf743f7c`.
  GitHub issue #16 and canonical state now agree on `integrated`, with
  `execution_allowed=false`.
- ISSUE-0014 remains the next implementation-order dependency-ready product
  issue. Both independent reviewers rejected exact head
  `a66c66ad6c2f941b6640d81320988b0b8af9e129`; this consolidated correction
  replaces simulated package/browser evidence with the real sdist artifact,
  registered routes and loopback HTTP startup, and adds canonical local
  refresh/algorithm/forecast/scoreboard/audit APIs, managed migration backup,
  valid interrupted-write recovery, runner-wide socket denial, provider-
  transport failure and application-API paper restart/rejection regressions.
  Hosted run `31330623071` is stale evidence: preflight failed before the Linux
  and Windows package jobs. Canonical issue status and authority remain
  unchanged pending corrected exact-head review and required H-tier validation.
  Whole-diff review approved first replacement head
  `396e366c4bfe2617d0b0353d14e89b9ffe18f2b7`; risk review rejected it for
  incomplete DNS/datagram denial, an unpinned workflow date and checksum-
  ambiguous proposal negatives. Its run `31332248276` is stale after changed-
  test preflight exceeded 240 seconds. One bounded correction now covers all
  four findings. Both reviews approved exact head
  `f25e006a506d2c141b42544ad3dca64e7fe4c831`, but fresh run `31333048454`
  deterministically reproduced the 240-second Linux changed-test timeout.
  The final bounded correction removes only duplicate initial snapshot and
  route rendering; all 16 journeys retain their assertions and pass locally
  in 140 seconds. Both reviews approved exact head
  `b3696a504f26dfedad3a5948030cfa8bfab19429`; run `31333531773` completed
  changed tests in 183 seconds and exposed the independent preflight absence
  of the configured setuptools backend. Keep real sdist execution when the
  backend exists, assert the exact isolated-build command everywhere, and
  leave authoritative package execution mandatory in the H-tier package job.
  Both reviews approved exact head
  `48682c5ea4510cec950a01b3316060563f66d70c`. H-tier run `31334147828`
  passed preflight, supply chain, Linux and Windows release packages and
  terminal validation, but its repeated report-only pilots demonstrated that
  the new all-routes browser probe exceeded its 120-second subprocess limit
  only in the four-worker safe lane; both serial repetitions passed. Classify
  that resource-heavy Flet probe into the existing serial/flet lane, without
  changing product, workflow or validation authority, then freeze one final
  replacement head for both reviews and fresh validation. Both reviewers
  rejected replacement head `b353740b67b0528fb42d51de13bb2c5fb807b7a1`
  after jointly demonstrating that its purported all-routes probe still named
  only `/` and `/training-centre` while production registers every route in
  `PAGES`; run `31339056458` was cancelled and discarded as stale. The single
  consolidated correction derives and exercises the complete production route
  registry while retaining the existing serial/flet partition. Both reviewers
  approved exact head `3e80a31b7d31245076625dbec9292bb3c5e95754`.
  H-tier run `31339637212` passed preflight, supply chain, both authoritative
  release packages, terminal validation and the Linux parallel pilot, but its
  second Windows serial repetition crossed UTC midnight and exposed one
  unpinned host-date path in the test probe. The single bounded correction
  binds candidate analysis to the probe's existing fixed date and asserts that
  every download uses that date; production, authority and workflow code stay
  unchanged.

## ISSUE-0104 product chronology

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
- Exact head `c50647a809ccbe84649b05e43fb0025c8354d9f3` was rejected
  after both reviewers completed. The consolidated defects are an incorrect
  real-backtest checksum keyword, omitted factsheet evidence in shared
  score/backtest/cache loading, duplicate persisted report identities, and
  multi-row pre-2.1 migration losing untouched-row fingerprint context.
  Release run `30787415201` passed preflight and started both H-tier package
  jobs; Linux and Windows both failed the deterministic real-backtest defect,
  so all evidence for that head is stale.
- Final narrow correction commit
  `853ade3f6ee042ad579201d5797f32ed06b81ad0` fixes all four reproduced defects. A real
  260-session structural-holdings backtest, shared factsheet/holdings
  score/service/cache/yfinance loading, duplicate report-reader rejection and
  reviewed/unreviewed multi-row migration are covered. The 111-case affected
  selection passes 110 tests with one expected skip in 35.7 seconds;
  architecture, Ruff, compile and diff hygiene pass. Freeze the replacement
  exact head.
- Replacement exact head `e9a672994541918b2a974e30a8d164c2cfd83314`
  was rejected after both parallel reviewers completed. The consolidated
  findings are fail-closed handling for malformed canonical factsheet/holdings
  stores, preservation of real canonical-writer structural provenance, and
  stable cross-kind `legal_form` conflict detection. Hosted release run
  `30789907061` reached both H-tier package jobs, but Linux and Windows failed;
  all review and CI evidence for that head is stale.
- Consolidated correction commit
  `6e31cc5ae050b953066ad5374d3c5d4f6efdadf9` fails malformed structural stores
  closed in the selector, carries explicit factsheet and holdings document
  bindings through the real canonical writers and shared projection/backtest,
  and makes `legal_form`/`domicile` stable cross-kind conflict fields. Four
  direct adversarial cases pass; the combined affected structure, scoring,
  parser, document, holdings, release-hardening and architecture suite reaches
  100% with one expected skip and no failures. Ruff, compile and diff hygiene
  pass. Freeze the checkpoint head for parallel reviews and fresh H-tier
  hosted validation.
- Exact head `ab8b7c0a79a52749eae68cf78165247f63893b7f` is rejected
  after both parallel reviewers completed. Their complete finding set is
  cross-kind legal conflicts being projected as resolved, numeric stress being
  unreachable from a real canonical parse/review/readback path, and malformed
  top-level review eligibility being bypassed by older verified history.
  Status guard `30792984804` passed. Stale release run `30792984780` passed
  preflight and Windows; it was cancelled after rejection while Linux was
  running, so its Linux and terminal results are not attributable evidence.
- Apply one consolidated correction and focused regression set for those three
  findings only. No lifecycle, authority, dependency, provider or execution
  scope changes are permitted. Freeze one replacement head after focused
  validation, then repeat both reviews and fresh H-tier hosted validation.
- Consolidated correction commit
  `fd0e6cb8957351427c0066c769ce4c820c973bf2` preserves point-in-time review
  replay while rejecting inconsistent current review state, keeps cross-kind
  stable conflicts unresolved, and carries four typed fraction inputs through
  real PDF parse, reviewed persistence, readback and structural stress. The
  focused parser/disclosure/structure/correction suite reaches 100% with one
  expected skip; the direct review-history follow-up passes 20 tests. Ruff,
  compile and diff hygiene pass. Freeze the replacement checkpoint head.
- Exact head `6bdb98a489bd046175432d833626751cf73900ec` is rejected
  after both reviewers completed. The complete newly demonstrated set is
  partial-token acceptance of percentage/suffixed numeric stress values and
  malformed or metadata-inconsistent review history falling back to trusted
  top-level verification fields. Status guard `30795502020` passed. Release
  run `30795502035` was cancelled after rejection, so its package and terminal
  evidence is stale.
- Make one narrow parser/review-state correction with real-path regressions,
  preserving valid historical review replay and all prior fixes. Freeze one
  new exact head and repeat both reviews plus fresh H-tier gates.
- Narrow correction commit
  `be211955a1a4dde05723e03388c65b4c471d9ca2` requires complete bare-decimal
  stress tokens, rejects percent/suffix/backtracking cases through the real
  reviewed path, and fails closed on malformed or current-metadata-inconsistent
  review history. Valid verified-before-rejection replay remains covered. The
  focused correction/structure/parser suite passes 71 tests with one expected
  skip; Ruff, compile and diff hygiene pass. Freeze the checkpoint head.
- Exact head `86f6ba03e19cfe948ff852d9eb6ca84e3beef8b1` is rejected after
  both reviewers completed. The complete finding set is canonical readback
  accepting an empty reviewer/unsupported review decision, supplied projection
  accepting missing or empty verified history, and numeric stress combining a
  quartet across unrelated report revisions. Status guard `30797521767`
  passed; release run `30797521771` was cancelled after rejection and is stale.
- Correct those three exact authority/provenance cases only: verified evidence
  requires one semantically valid history, and all stress inputs must share one
  exact reviewed report revision. Preserve valid historical replay and all
  previous strict-token behavior, then freeze one replacement head.
- Consolidated correction commit
  `044375c91d9e56334266f7860c738609fc3508fe` enforces semantically complete
  review history in canonical and supplied readback and binds each numeric
  stress quartet to one report revision while preserving valid historical
  replay. The attributable focused suite passes 117 tests with one expected
  skip; Ruff, compile and diff hygiene pass. Freeze one exact replacement head
  for parallel whole-diff review, risk review and fresh H-tier hosted gates.
- Exact head `387d7de921dcc189a8479da2c11af155d2e22965` was rejected after
  both reviewers completed. The consolidated finding set is one supplied-frame
  trust-boundary gap: extraction content was not recomputed against its stored
  fingerprint, malformed score/execution flags were accepted, and duplicate
  report identities bypassed canonical readback validation. Release run
  `30799282419` was cancelled after rejection and is stale.
- Correction commit `1c53cea7a03dc40afea1c1f0742e7d294ab52843` routes supplied
  report frames through schema-aware fingerprint, review-authority and unique
  identity validation before structural or numeric use. Facade-level mutation,
  authority-flag and duplicate-ID regressions pass within a 112-test focused
  suite; Ruff, compile and diff hygiene pass. Freeze one replacement head and
  repeat both exact-head reviews plus fresh H-tier hosted gates.
- Exact head `750ee1be352f3b7c8852d2d779ec4abf352997b1` was rejected after
  both reviewers completed. Newly reproduced parity gaps covered canonical
  review/manual/verifiability semantics, original-container schema identity,
  non-mapping members, exact document-kind/source-authority binding, bare
  decimal grammar and global registry source identity. Release run
  `30801792515` was cancelled after rejection and is stale.
- Final parity correction commit
  `673f30f073427e03d181f6a5bcad4e908a4d01ee` applies those exact
  canonical rules to every supplied projection, cap and cache path without
  changing lifecycle or execution authority. The complete focused parity suite
  passes 124 tests; Ruff, compile and diff hygiene pass. Freeze one replacement
  head and repeat both reviews plus fresh H-tier gates.
- Exact head `1bcf863e6402e9cb7d883d319bd0e09b4210bc2f` was rejected after
  both reviewers completed. The complete new finding set is strict stored
  boolean handling for `parse_success`, numeric document-family binding,
  duplicate-registry cache identity and explicit derivative/synthetic
  negation. Release run `30803686888` was cancelled and is stale.
- Residual correction commit `875b893fd87d386475cdc3d0815acbe1d24d6c66`
  covers those four reproduced cases only. The focused suite passes 130 tests;
  Ruff, compile and diff hygiene pass, and `execution_allowed=false` is
  unchanged. Freeze the replacement head for both exact-head reviews and fresh
  H-tier hosted gates.
- Exact head `52cae8cf7f87da46f95e53c643061acc7d394e54` was rejected after
  both reviewers completed. The complete finding set is field-local negation,
  unconditional `parse_success` schema typing and stale-cache prevention when
  structural storage is corrupt or unreadable. Release run `30805501748` was
  cancelled and is stale.
- Correction commit `3fa69aaef0757aba3013598497cb74ae98fdfd6d` covers only those
  reproduced paths. The focused suite passes 153 tests; Ruff, compile and diff
  hygiene pass, and execution/lifecycle authority is unchanged. Freeze the
  replacement head for both exact-head reviews and fresh H-tier hosted gates.
- Exact head `ea5a7863876a7bff8ce32812de115a74590ed120` was rejected after
  both reviewers completed. The consolidated acceptance gaps are supported
  report schemas, one-revision numeric quartets, strict typed input channels
  and cache identity, clause-aware contradiction handling, and per-decision
  backtest structural provenance. Release run `30807318004` was cancelled and
  is stale.
- Complete provenance correction commit
  `e858f5a8c0d57690ed7456baf7132d0a47ccc434` covers those reproduced
  paths without lifecycle or authority changes. Four attributable focused
  suites pass 182 tests total; Ruff, compile and diff hygiene pass. Freeze the
  replacement head for both exact-head reviews and fresh H-tier hosted gates.
- Exact head `a7862cb70e33afd6c12f4db2656abb88e7ac8ae5` was rejected after
  both reviewers completed. The complete finding set is point-in-time conflict
  eligibility, same-clause contradiction safety, structural identity-alias
  agreement and typed-channel type/kind agreement. Release run `30811214008`
  was cancelled and is stale.
- Point-in-time correction commit
  `55582bf9169db7da3a2a293c76e6a8b8f48b8939` covers only those
  reproduced paths. Four focused suites pass 202 tests total; Ruff, compile and
  diff hygiene pass. Freeze the replacement head for both exact-head reviews
  and fresh H-tier hosted gates.
- Replacement exact head `10607cf4fa0563a958821391c7735491bfac2416`
  was rejected after both parallel reviewers completed. The consolidated set
  is decision-time replay of cross-report review authority, contradictory
  `instrument_id`/`etf_id` rejection, mandatory cached signal provenance and
  architecture wording consistent with point-in-time conflict scoring.
  Release run `30814812246` was cancelled after rejection and is stale.
- Consolidated correction commit
  `f82797a7fb854fdeb8ae2f70a68582835334df4c` binds conflicts to the review
  event visible at each decision, preserves verified intervals before later
  rejection, rejects contradictory instrument aliases before projection or
  hashing, and invalidates cached backtests without complete per-decision
  structural provenance. The four attributable focused suites, Ruff, compile
  and diff hygiene pass. A runtime-dated integration fixture was also made
  deterministic by selecting an explicit post-import decision time.
  Lifecycle authority, dependencies and `execution_allowed=false` are
  unchanged. Freeze one replacement head after this checkpoint, then run both
  exact-head reviews and fresh H-tier hosted gates in parallel.
- Exact head `6440440df1892a74c1734f935f52d1a437ed6ba8` was rejected
  after both reviewers completed. The consolidated defects are false
  cross-period conflicts for time-varying structure, omitted conflict-candidate
  provenance in the ETF panel, and cache acceptance without recomputing exact
  per-decision structural cap/hash. H-tier run `31246422546` also failed its
  vulnerability scan on `cryptography==49.0.0` / `CVE-2026-69247`; preflight,
  lifecycle-candidate validation and status guard passed, but package jobs did
  not start, so the run is stale.
- Combined correction commit
  `9aea82a16bc2b1e71fbcf71c79068c02f9a83f25` uses one shared stable/varying
  field policy, binds varying fields to the latest reporting period while
  preserving same-period and stable-field conflicts, renders complete conflict
  provenance, and recomputes cached cap/hash from canonical evidence for every
  signal date. It also updates only the directly coupled release and GitHub
  writer runtime to non-vulnerable `cryptography==50.0.0`; the reviewed Linux
  wheel hash is
  `06a32a980526a6ab9a4b9bf8f7385800791e2bb960903cb6b530e4817509a3b7`.
  Four product suites and five supply-chain/authority suites pass; Ruff,
  compile, diff hygiene, binary hash-lock download and `pip-audit` pass with no
  known vulnerabilities. Lifecycle state and `execution_allowed=false` are
  unchanged. Freeze the checkpoint head and repeat both exact-head reviews and
  fresh H-tier gates in parallel.
- Exact head `e8001fe01a54878a89b1778137156cb265cb63c4` received risk
  approval after 361 passing tests and one expected skip, but whole-diff review
  reproduced one new defect: an absent optional holdings file was converted to
  an empty frame and then misclassified as a malformed canonical store,
  suppressing otherwise valid report/factsheet evidence. Run `31248171632`
  passed status guard, supply chain, locked-writer candidate validation and
  preflight, then was cancelled as stale while H-tier packages and pilots ran.
- Narrow correction commit
  `6781a488ab4fe68f77246ae4af6c340b91d693c6` validates holdings schema only
  when the canonical file exists, while existing corrupt and schema-malformed
  files still fail closed. The new exact-registry-bound factsheet regression
  proves valid evidence remains resolved when optional holdings are absent;
  the correction suite, Ruff, compile and diff hygiene pass.
  `execution_allowed=false` and all lifecycle/authority state remain unchanged.
  Freeze the replacement head for both exact-head reviews and fresh H-tier
  hosted validation.
- Replacement exact head `f81a16c0fe349450e889a22c6780aa1a85bad1ad`
  was rejected after both parallel reviewers completed. The consolidated
  findings are review events accepted before the exact report `known_at` and
  an existing holdings store with identity plus unrelated columns being
  silently skipped instead of rejected. Run `31249002466` passed status and
  supply-chain checks, then was cancelled as stale immediately after the
  review rejection.
- Consolidated correction commit
  `2bb6f818ddceeb1fcdea66727e59c0c446c8e243` rejects review history before
  report ingestion in canonical, supplied and defensive structural replay,
  and requires every existing canonical holdings store to contain the required
  writer schema. Projection, confidence-cap, stress, selector, canonical
  readback, service/cache and backtest regressions pass across the five
  directly coupled test modules; Ruff, compile and diff hygiene pass.
  Lifecycle authority and `execution_allowed=false` remain unchanged. Freeze
  one replacement exact head and repeat both reviews plus fresh H-tier hosted
  validation in parallel.
- Exact head `bb72a93ba3c874e061c9b9668cc4950e90324a33` was rejected
  after both parallel reviewers completed. The consolidated valid findings
  are malformed existing holdings surviving a later merge, lost updates from
  concurrent holdings publishers, review publication before exact
  `known_at`, and a cache regression that returned before exercising the
  structural loader. Release run `31250191446` passed classifier,
  supply-chain, candidate validation and preflight, then was cancelled as
  stale while Linux, Windows and pilots ran. The reported `issues/open.md`
  manifest mismatch is not a contract defect: `programme-generation.v1`
  deliberately hashes canonical LF text, and two mechanical generations plus
  check mode were byte-clean.
- Combined correction commit
  `4630445c0380b9ad5dae56fb0fd588d241f8fb8a` applies full canonical holdings
  validation at every reader/writer boundary, serializes every holdings
  publisher across the complete transaction with registry-first lock order,
  rejects and pre-validates future-bound report reviews, and makes the cache
  corruption regression reach the loader. The six directly coupled modules
  pass at 100%; Ruff, compile, generator check and diff hygiene pass.
  Lifecycle authority and `execution_allowed=false` are unchanged. Freeze one
  replacement head for both reviews and fresh H-tier hosted validation.
- Exact head `8c48b7199705396d42bb137f72a65c46b3258241` was rejected
  after both reviewers completed. The two newly demonstrated defects are an
  empty existing Parquet bypassing schema checks and the document-coupled
  holdings writer publishing its post-binding frame without the semantic
  staged validator. Run `31252092595` passed classifier, preflight,
  supply-chain, candidate validation and lint/type gates; both package jobs
  timed out in the unchanged 1,800-second full-test stage, terminal validation
  failed, and the still-running pilots were cancelled as stale.
- Narrow follow-up commit
  `8a94de3613f02f58c10de8571895c86c05e0342d` checks required schema before
  accepting an empty persisted frame and validates the complete post-binding
  holdings frame both before staging and from staged Parquet bytes. Direct
  load, merge and rollback regressions pass, as do the full holdings and
  ISSUE-0104 correction modules, Ruff, compile and diff hygiene. No lifecycle,
  provider or execution authority changes. Freeze one replacement exact head
  and repeat both reviews plus fresh H-tier hosted validation.
- Exact head `3581a1b2195890d08baa3fffb1ae04d8b3f118fe` received an
  independent risk approval but was rejected by the whole-diff review after
  both verdicts completed. Reversing annual/half-year registry order changed
  the family source displayed by the document matrix and therefore changed
  the structure provenance hash. Release run `31254041778` passed classifier,
  supply chain, candidate validation and preflight, then was cancelled and
  its in-flight package/pilot evidence discarded as stale.
- Bounded correction commit
  `17194503a000de86b723e5e12207495a201db604` deterministically selects the
  latest selected family revision by document date, known-at time and source
  identity. The annual/half-year regression proves both the displayed source
  and complete structure provenance hash are invariant to registry ordering;
  all 86 structure tests, Ruff and diff hygiene pass. Lifecycle authority and
  `execution_allowed=false` remain unchanged. Freeze one new exact head and
  repeat both reviews plus fresh H-tier hosted validation in parallel.
- Replacement head `aab53ce37e58384ed4c2ae0c79217194a6b4fd97` received
  whole-diff and risk approvals; the sole whole-diff note was a non-blocking
  report-row ordering follow-up. Fresh run `31255297689` passed classifier,
  supply chain, candidate validation and preflight, but both serial package
  suites timed out at exactly 1,800 seconds and terminal validation failed.
  Bounded diagnosis reproduced a valid cache hit taking about 20 seconds
  because structural evidence was replayed separately for every signal row;
  repeated snapshots therefore exhausted the cross-platform suite ceiling.
- Single blocker correction commit
  `0993e85a0093103884bc5ba413f95a14fd9a335c` batches structural cache
  readback by decision date and instrument and vectorizes the canonical
  no-evidence case without weakening provenance comparison. Valid cache
  readback falls from about 20.2 to 0.8 seconds and snapshot construction from
  about 26.1 to 4.8 seconds. Both direct cache/tamper regressions and the full
  69-test backtest/correction modules pass; Ruff and diff hygiene pass.
  Freeze one final exact head for both reviews and fresh H-tier packages and
  pilots. Lifecycle authority and `execution_allowed=false` are unchanged.
- Exact head `cc7f5748ebed06031f80f4c040e166e599a147fe` received risk
  approval but was rejected after both parallel verdicts completed. The
  whole-diff review demonstrated that null/sentinel instrument identities
  could pass the empty-evidence cache path and that the batching regression
  did not exercise non-empty evidence across multiple dates. Fresh release
  run `31258800287` passed classifier, supply chain, candidate validation and
  preflight, then was cancelled; its package and pilot evidence is stale.
- Consolidated correction commit
  `3c6eac38be61677e1fcd4a1a6e785cc96e8129bb` rejects null, empty and
  sentinel cache identities before normalization and proves non-empty
  structural replay occurs once per unique decision date for all instruments
  while retaining exact cap/hash tamper rejection. The complete 77-test
  backtest/correction modules, Ruff and diff hygiene pass. Freeze one new
  exact head, repeat both reviews and fresh H-tier hosted validation in
  parallel, and make no further correction absent a newly demonstrated
  defect. Lifecycle authority and `execution_allowed=false` remain unchanged.
- Exact head `df97611e8fcfa5d9b1e8db00e31c882214ead1fe` was rejected
  after both parallel reviews completed. Both reviewers accepted the cache
  correction; their newly demonstrated findings were mixed optional holdings
  identity columns changing retained provenance after a union-schema merge,
  and stale/ineligible holdings claims resolving as structural confidence
  evidence. Release run `31259494785` reached package and pilot execution but
  was cancelled and its evidence discarded as stale.
- Combined correction commit
  `811c094ae5f408f35f2f8fb569929c9eb2a5fc2a` hashes every holding
  against one fixed canonical optional-identity schema, with sequential and
  concurrent ticker/ISIN merge regressions. Structural consumption now rejects
  stale, aged, incomplete, non-issuer and non-score-eligible holdings claims
  explicitly, keeping their confidence cap at zero. The 229-test combined
  backtest, holdings, structure and correction suite passes, as do Ruff and
  diff hygiene. Freeze one replacement head and repeat both reviews plus fresh
  H-tier hosted validation in parallel. Lifecycle authority and
  `execution_allowed=false` remain unchanged.
- Exact head `91cbf92e70afe339b8a835edf7f99b11eb319c5b` received a
  whole-diff approval with one non-blocking concurrent source-ID assertion,
  but risk review demonstrated that a holding dated after the historical
  decision produced a negative age and could bypass the stale check. Release
  run `31260389662` reached package and pilot execution, then was cancelled and
  discarded as stale after both verdicts completed.
- Narrow follow-up commit
  `2efad098e514f4722f21e53fa771f452aeb5bb3b` rejects a holdings date
  later than the effective decision before freshness evaluation, proves future
  holdings cannot resolve, raise the confidence cap or validate a forged
  cached replay, and asserts each concurrent mixed-schema import retains its
  expected source ID. The 231-test combined backtest, holdings, structure and
  correction suite passes, as do Ruff and diff hygiene. Freeze the replacement
  head for both reviews and fresh H-tier hosted validation; no further change
  is permitted without a newly demonstrated defect. Lifecycle authority and
  `execution_allowed=false` remain unchanged.
- Exact head `52d2eb31096b141c23850fcc60ccbc89c445e9a3` received risk
  approval but was rejected by the whole-diff review after both verdicts
  completed: an arbitrary non-empty signal ID outside the configured universe
  could pass the empty-evidence cache path. Release run `31261532414` was
  cancelled and its in-flight package/pilot evidence discarded as stale.
- Minimal correction commit
  `13e0b378e3686dffe9a5e5bdd9901d9f2b858d50` binds every cached signal
  ID to `config.universe.enabled_ids` before either cache-validation path and
  adds the exact unconfigured-ID regression. The complete 79-test
  backtest/correction modules, Ruff and diff hygiene pass. Freeze the final
  head for both reviews and fresh H-tier hosted validation; lifecycle authority
  and `execution_allowed=false` remain unchanged.

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

## ISSUE-0017 lifecycle checkpoint — 2026-08-11

- Product PR #672 merged exact independently approved head
  `52cadf44abff48ff09cd23cf792acad64dbab94e` as exact main
  `3845aaa10a1e0718bc62e4a6698658ce6cd0326a`. Run `31450653397` passed
  preflight, supply chain, authoritative Linux and Windows package gates and
  terminal validation; `execution_allowed=false` remains unchanged.
- Clean lifecycle lane `codex/issue0017-lifecycle-final-20260811` starts from
  that exact main commit. Its only canonical mutation is ISSUE-0017
  `implemented_initially -> integrated`; no dependency edge changes are
  authorised.
- Exact live plan `48d98a6e297123958fa4f8c1f87e5837023664bb477f5e560bad44eaf56dd4ce`
  targets only GitHub issue #21's programme status. Candidate authority
  `ab10ce027d85b169f549d300335123adae63e637053bb0431a809e2634ea1d48`
  and append-only authority sequence 22 are bound to the same snapshot, plan
  and product commit. Require ordered writer success and generic zero-action
  readback after the exact lifecycle head merges.
- ISSUE-0018 is the next canonical dependency-ready product issue. Begin its
  disjoint product lane only after ISSUE-0017's writer/readback converges.

## ISSUE-0018 product checkpoint — 2026-08-11

- ISSUE-0017 lifecycle PR #673 merged exact reviewed head
  `7e664542fdeea154cbca2c999334a3be565fb515` as exact main
  `9c3ac836587d3e2b494bca20e27b559978eb8c9b`. Exact-head H-tier run
  `31453379949` and status guard run `31453379906` passed. Writer run
  `31455074038` applied and verified the single ISSUE-0017 projection; generic
  convergence run `31455074057` and an independent exact-main live readback
  both returned zero actions. `execution_allowed=false` remains unchanged.
- ISSUE-0018, "Watchlist and universe manager", is dependency-ready and is the
  active product issue. Clean lane `codex/issue0018-product-20260811` is based
  on exact main `9c3ac836587d3e2b494bca20e27b559978eb8c9b`; implementation checkpoint
  `b80967bb956b083f7033aba4ae1c9ac6de3d228e` is one product commit ahead.
- Bounded product scope is local CSV/XLSX/paste/supplied-provider import,
  deterministic identity resolution and row classification, immutable source
  plus correction overlays, reproducible versioned manifests, exclusions,
  horizons and quotas, and cancel-safe chunk resume. It adds no provider,
  workflow, scoring or broker calls and does not enter ISSUE-0126 point-in-time
  universes or ranking work.
- Focused universe import/store/manager/architecture tests pass with the
  expected capability skip; Ruff, compile and diff hygiene pass. Complete the
  checkpoint chronology before freezing, then run both exact-head independent
  reviews and fresh H-tier Linux, Windows and terminal evidence in parallel.
- The legal post-merge lifecycle remains one ISSUE-0018
  `implemented_initially -> integrated` transaction bound to the reviewed
  product PR and merged product commit, followed by the existing writer and
  generic zero-action readback. Do not merge while required lifecycle evidence
  is known to be absent.
- Initial PR #674 head `62d6103cd013dd325ad8bbdc794d6ea92f4f9baa`
  was rejected by both exact-head reviews and hosted run `31455384153` after
  concrete identity, resume, flag-normalisation, UI-contract, failed-write,
  duplicate-field and XLSX-bound defects were reproduced. Its evidence is
  stale and must not be reused.
- Consolidated correction commit
  `5e89f7b15a8c1264518c36443772b1c5f53d6373` fixes the complete review set,
  adds focused regressions and classifies the exact persistent import module as
  H-tier while retaining checkpoint chronology as E and ordinary product as O.
  The affected focused suite passes (one expected capability skip), changed
  preflight and UI inventory pass, and Ruff, compile, diff hygiene and generator
  check pass. Freeze the next checkpoint commit for both parallel reviews and
  fresh hosted H-tier Linux, Windows and terminal evidence.
- Replacement head `e766016eccf6415323a06ff5cd3b364146a6b614` was rejected
  after both reviewers reproduced newly demonstrated fail-closed gaps in
  malformed booleans, normalized/persisted JSON collisions, provider JSON
  transports, aggregate XLSX limits and redirected manifest destinations.
  Hosted run `31457631651` is cancelled and stale.
- Final bounded correction commit
  `5bbd8204d04005ff4855f9f07674d0bcb05f4d8a` closes that complete finding set
  in the import module with focused adversarial regressions. Import and store
  suites pass with one existing platform-capability skip; Ruff, compile, diff
  hygiene and generator checks pass. Freeze one final checkpoint head for both
  reviews and fresh H-tier evidence; no further adjacent hardening is in scope.
- Head `009610ecf3a5aff4bd9508e9dcaf225527f3e544` was rejected for one newly
  reproduced safety case: contradictory valid boolean aliases selected the
  first value. Run `31459084752` was cancelled and is stale. Commit
  `fcd44eb0eb103944bdff3bf8d8ae90c3b8dfb42b` rejects conflicts across every
  supported alias pair; all 45 import regressions, Ruff, compile and diff
  hygiene pass. Repeat both exact-head reviews and fresh H-tier evidence.
- Risk review approved head `61ea71394e6b2cc3725d6ee1aba210d394a24dbf`,
  while whole-diff review found manifest destination identity was not repeated
  by the existing atomic precondition under the held group guard. Run
  `31460776868` is cancelled and stale. Commit
  `33f31a3d3e9cd025da38c4fc94f5ea380ef51b7d` applies the existing guarded
  pattern and adds a deterministic redirect-race regression. All 46 import
  regressions plus Ruff, compile and diff hygiene pass. Freeze and revalidate.

## ISSUE-0018 lifecycle checkpoint — 2026-08-11

- Product PR #674 merged exact independently approved head
  `5b2bd54347fc8b2b683bc44b9a415702a7a778b2` as exact main
  `94e6376e1a81cdd11bc6c64adc1ebd6499c26bac`. Run `31462859675`
  passed classifier, preflight, supply chain, authoritative Linux and Windows
  package gates and terminal validation; `execution_allowed=false` remains
  unchanged.
- Clean lifecycle lane `codex/issue0018-lifecycle-20260811` starts from that
  exact main. Its only canonical mutation is ISSUE-0018
  `implemented_initially -> integrated`; no dependency-edge change is
  authorised. Mechanical generation is byte-clean.
- Exact live plan `ed62f5135396abb107b07b808aafe77733a2b3856e45cbb11ddb179458c9b0d7`
  contains one update for GitHub issue #22 and no other action. Candidate
  authority ref `21796ad5c30c5f53cd5487b5bbc1876321122b392579c08357cdd7e2af461cf0`
  and append-only authority sequence 23/id
  `db7622b54f8afd1ccdf24a6b356f3691aecb2e46b68c90136e8389aa2b9c08d8`
  bind the same snapshot, plan and product merge.
- Freeze one lifecycle head after focused guards. Require independent exact-head
  review, merge, ordered writer `applied_and_verified`, and generic zero-action
  readback before selecting the next dependency-ready product issue.
- Lifecycle PR #675 merged independently approved head
  `d1333017f86d1b1dc6c5bbe79dbc975257baaaf6` as exact main
  `f4f6707d19e4de0d26144971f6c254750e44aaa2`; status guard
  `31493345117` and release run `31493345148` passed all required Linux,
  Windows and terminal checks. Writer run `31497001531` then failed closed
  before any transport write when its required fresh Actions-run read
  transiently failed after the identical initial read had succeeded. Attempt 2
  correctly remained ineligible. The sole bounded H-tier repair retries only
  explicit read-only HTTP 500/502/503/504 and transport failures, with a focused
  regression; caller proof, mutation semantics and `execution_allowed=false`
  remain unchanged.
- Bounded reader repair PR #676 merged exact reviewed head
  `aad1635b2ae1f1a61e2b78cc8c8e376a2ba98408` as exact main
  `4e601b44a8f0373f37813da4391121aebee4a67a`; H-tier run
  `31498834325` passed Linux, Windows and terminal validation. GitHub #22
  remains `implemented_initially` because sequence 23 has no legal fresh-run
  retrigger after the zero-write failure, and another retry/recovery authority
  repair is outside the one-cycle limit. Record that control-plane follow-up
  separately; do not bypass OIDC or append duplicate authority.
- Exact-main audit found no remaining ISSUE-0019 product gap: every accepted
  Instrument Detail panel, ETF/stock smoke, row navigation and unavailable
  state is implemented and focused tests pass. With lifecycle projection work
  frozen, ISSUE-0021 is the next canonical phase-01 dependency-ready product
  issue. Clean lane `codex/issue0021-product-20260812` starts at exact main
  `4e601b44a8f0373f37813da4391121aebee4a67a`; implement only its portfolio
  sandbox delta while preserving ledger isolation and
  `execution_allowed=false`.
- ISSUE-0021's bounded product delta now composes the existing optimiser,
  robust-risk, cost, overlap and canonical capability services around an exact
  account/portfolio/as-of and direct/look-through snapshot binding. Candidate
  intent and derived result evidence publish through one atomic independent-CAS
  transaction; deterministic exports are atomic; rejected or inapplicable rows
  cannot enter the checksum-bound pre-ISSUE-0130 draft hand-off. The affected
  persistence, sandbox, UI, optimiser, cost, risk and execution-boundary suite
  passes 96 tests; Ruff, compile, generated-state check and diff check pass.
  Classifier result is H with fresh Linux, Windows and terminal evidence
  required before merge. Freeze only after committing the complete checkpoint,
  then run whole-diff and risk reviews against the same exact head in parallel
  with hosted H-tier CI.
- Frozen head `62cb487212b5cee98a05464887c5c799d761af9d` and hosted run
  `31506000586` are invalidated. Parallel whole-diff and risk reviews
  demonstrated seven bounded product/persistence defects: duplicate-row
  capability order dependence, incomplete line/classifier checksum binding,
  aggregate-constraint draft leakage, torn candidate/result reads, incomplete
  hand-off integrity, unresolved target-only capability and missing mixed-asset
  UI controls. Hosted preflight additionally proved the two new actions lacked
  acceptance contracts. One consolidated correction closes all eight and adds
  exact regressions; the complete 185-test affected suite, offline smoke, Ruff,
  compile, generated-state and diff checks pass. Commit one replacement head
  and repeat both independent reviews plus fresh H-tier hosted evidence.
- Replacement head `a531e63e219fa469e395516889096b35a846a0f3`
  and run `31509217777` are also invalidated after both repeated reviewers
  reproduced two newly exposed readback defects: as-of/source-identity changes
  suppressed old results without setting `source_stale`, and self-consistent
  tampered derived content was not compared with canonical recomputation. The
  bounded correction now marks every selected binding change stale and requires
  exact canonical result equality before readback; both reproductions and the
  complete sandbox/UI suite pass. Freeze one final replacement head and repeat
  the exact-head reviews and fresh H-tier gates without reopening adjacent work.
- Head `5a81d4866388fa18ff81e9cbbf4799eaff80fb31` and run
  `31510633704` are invalidated after final reviewers reproduced three bounded
  data-shape/UI consistency defects: sparse `is_look_through` NaN inverted a
  direct drift, duplicate capability evidence lacked a total order, and the
  rebalance preview ignored the selected holdings view/source identity. Strict
  optional-boolean lineage, complete capability ordering and a source-bound
  filtered preview now close the exact reproductions; focused sandbox/UI and
  static checks pass. Freeze the next head for the final repeated reviews and
  fresh H-tier evidence only.
- Head `0b57ede3c30214fa6261a84f11fbd9b032ef930e` and run
  `31512179961` are invalidated after final review found that production
  holdings `as_of_date`/`source` were not bound and that the legacy ETF-only
  rebalance service threw on a supported mixed-asset target. Row-level holdings
  vintage/provider now participate in checksum and cited binding, and mixed
  assets receive an explicit source-bound inapplicable preview without silent
  removal. Exact provenance/load and AAPL UI regressions plus focused checks
  pass. Freeze the next head for final review and fresh H gates.
- Head `bc08cf83f974befb00ca99692ef26bd9afc9c867` and run
  `31513745409` are invalidated by one final mixed-asset branch reproduction:
  a held AAPL position with a zero target bypassed the positive-target guard
  and reached the ETF-only rebalance service as a false sell. The guard now
  blocks every selected or targeted non-configured position regardless of
  target weight; the exact zero-exit regression passes. Freeze the replacement
  head for final approval and fresh H-tier evidence.
- Whole-diff review approved head `d74e32e6e655ff639587c9fe18f0ba211c7624fa`
  and risk review verified the guard fix but reproduced one independent parser
  defect: ragged CSV rows could discard trailing fields. Run `31461743133` is
  cancelled and stale. Commit `7b899a71830e483f453cc254d5470fdac6a06755`
  requires every non-empty CSV row to match header width; all 48 import
  regressions plus Ruff, compile and diff hygiene pass. Freeze and revalidate.
- Head `db62cdccfd5a7327d7a4923f1ade6f40b778c6d0` and run
  `31514947591` are invalidated after the complete parallel review set found
  two deterministic ISSUE-0021 blockers: configured stocks could still enter
  the ETF-only rebalance preview, and overlap selection omitted the sandbox
  as-of cutoff. The canonical capability decision now determines preview
  applicability for every held or positive-target instrument, including held
  zero-target exits, and overlap evidence receives the timezone-aware selected
  snapshot cutoff. Exact configured-`UCG` and future-known-evidence regressions
  pass; freeze one replacement head for both reviews and fresh H-tier evidence.
- Head `55f3185500d36b18e9839727fcf380973d9b7dfd` and run
  `31516901901` are invalidated after both reviewers demonstrated four bounded
  source-integrity/readback defects: binding as-of could differ from overlap
  cutoff, adjusted prices were omitted from result identity, a caller checksum
  was not compared with canonical candidate content, and a formerly held
  unconfigured target could not be reloaded as stale. One canonical as-of now
  drives binding and overlap selection; price revision/checksum are bound;
  candidate checksum equality is mandatory; and persisted intent validates
  independently of current holdings before current-rule recomputation. All
  four exact regressions pass. Freeze one replacement head and repeat the two
  reviews plus fresh H-tier evidence without adjacent redesign.
- Head `f96ba9d3ddaa3f21d1d360e1204352c2b673bcc7` and run
  `31518687496` are invalidated by two final exact identity findings: candidate
  as-of still used the report date while result/overlap could use holdings
  vintage, and selector labels could be attached to one fixed snapshot without
  resolving matching data. Candidate, result and overlap now share the report
  decision as-of; persisted candidate/result as-of is cross-checked; binding
  derives account/portfolio/snapshot identity from the supplied immutable
  snapshot and rejects mismatched selections. Report-only staleness, distinct
  A/B source checksums and UI relabelling regressions pass. Freeze one exact
  replacement head for the repeated reviews and fresh H-tier gates.

## ISSUE-0021 completion and ISSUE-0024 product checkpoint — 2026-08-12

- ISSUE-0021 product PR #677 merged exact independently reviewed head
  `42b8dce8ab34441c78c4e4e82ac7d1d9cf894ad1` as exact main
  `6784b054d13b36c0ca4cd6434ab1bec85cc8131f`. H-tier run `31520049790`
  passed classifier, preflight, supply chain, Linux, Windows and terminal
  validation. The merged portfolio sandbox remains context-only and
  `execution_allowed=false`. ISSUE-0018's unprojected sequence-23 follow-up
  remains frozen under the completed bounded repair-cycle limit.
- ISSUE-0024, "Earnings, dividends and event calendar", is the next canonical
  phase-01 implementation-order issue. It is P1/P2, `implemented_initially`,
  dependency-ready and activation-ready with no blocking dependencies. Clean
  lane `codex/issue0024-product-20260812` starts at exact main
  `6784b054d13b36c0ca4cd6434ab1bec85cc8131f` with an empty diff.
- Exact-main audit confirms the canonical local-first event ledger, complete
  required event vocabulary, atomic raw/clean/audit persistence, point-in-time
  cutoff helper, Instrument Detail and News/Context surfaces already exist.
  The bounded product gap is to validate declared event timezone metadata,
  make decision-time availability explicit in normal UI readback, and prove
  every required event type plus visible non-destructive quota/unavailable
  handling. Do not add a provider, network authority, scoring authority or
  execution path; preserve `execution_allowed=false`.
- The bounded delta now validates IANA timezone names, uses one canonical
  fail-closed decision-time normaliser, filters both UI surfaces through the
  existing availability/ingestion cutoff and suppresses raw event rows when a
  cutoff is absent. All required event types, event import/persistence,
  source-policy quota behavior, onboarding quota non-destruction, UI,
  architecture, Ruff, compile, generator check and diff hygiene pass in the
  73-test focused set. Classify the complete diff, commit one stable head and
  launch both independent reviews plus required hosted evidence in parallel.
- Frozen head `527c9062c2c73d94898d98aa403e4803dddfb6b1` and H-tier run
  `31525671258` are invalidated after both reviewers completed. The consolidated
  finding set was exact and bounded: concurrent appends could lose one
  canonical row, incomplete ledgers could be stamped decision-time available,
  date precision accepted a populated event time, and the public News/Context
  route lost direct test coverage.
- The single consolidated correction serializes the complete read/merge/publish
  append under the existing persistent guard, independently verifies complete
  canonical rows and checksums before load, disclosure or republication,
  enforces date/time precision and restores public route coverage. Concurrent
  append, malformed-ledger no-write and both UI regressions pass with the
  complete affected focused suite, Ruff, compile, programme byte-clean check
  and diff hygiene. Freeze one replacement head for both reviews and fresh
  H-tier hosted validation; add no adjacent work.
- Replacement head `87422b3d99222a5b6e30b1c9153b22accad9660d` and run
  `31527781649` are invalidated after both repeated verdicts were collected.
  Three newly demonstrated integrity gaps remain: clean rows are not bound to
  their contained raw JSON and audit summary, `event_date` accepts a datetime
  suffix, and individually valid conflicting observations can still be loaded
  and disclosed. Use the one bounded follow-up to close exactly this clean/raw/
  audit, lexical-date and conflict set with no retry, adjacent hardening or
  shared persistence redesign.
- The bounded follow-up now validates the complete clean/raw/audit bundle,
  exact contained raw names and payloads, audit row/frame identity, lexical
  dates, duplicate rows and conflicting observations before load, disclosure
  or append. Orphan/missing/extra/tampered evidence remains untouched and
  fails closed. The complete affected event/import/source-policy/quota/UI/
  architecture suite, Ruff, compile, generator byte-clean check and diff
  hygiene pass. Freeze this final replacement head for both reviews and fresh
  H-tier gates; no further event-store generalisation is in scope.
- Head `cba1b3e8090445a119bbc9e9213a919f9c093f0d` and run `31529996742`
  are invalidated after both final reviews found two omissions inside the same
  triad contract: audit validation entries were not content-bound and nested
  raw JSON was outside the flat inventory. The final minimal closure derives
  exact audit entries from every canonical row and rejects nested or linked raw
  entries before load or append. Add only the two no-write regressions, rerun
  the affected suite once and freeze the replacement head; no further
  hardening cycle is permitted.
- Head `243949f8dc03f4f8328fa6bbf427d55e6004c58b` and run `31531221048`
  are invalidated after both reviewers reproduced one remaining raw-inventory
  boundary in two states: a fresh store accepted nested evidence before its
  first clean ledger, and an existing bundle ignored an extra non-JSON file.
  The consolidated correction treats every pre-existing raw entry as evidence
  when no clean ledger exists and permits only the exact canonical raw JSON
  set plus the atomic writer's named durable guard once a ledger exists. Exact
  no-write regressions cover both cases; no adjacent event-store change is in
  scope. Freeze one replacement head for both reviews and fresh H-tier gates.

## ISSUE-0024 merge and ISSUE-0033 product checkpoint — 2026-08-12

- ISSUE-0024 PR #678 merged exact independently approved head
  `89634f179eb947d4f0af8685cf4ef025685dd618` as exact main
  `4f7082d06d1695158d8998563dc083e86fe5e364`. H-tier run `31533062736`
  passed classifier, preflight, supply chain, Linux, Windows and terminal
  validation. Event rows remain context-only and `execution_allowed=false`.
- Exact-main audits found no remaining ISSUE-0026 or ISSUE-0027 product delta.
  ISSUE-0026's prior product merge `5b7a0150b3b01f3ec6685c7c14e62ae3dac1b050`
  is an ancestor and 37 focused macro warehouse/scenario/dashboard tests pass.
  ISSUE-0027's product commit `0903a48c5b77924a86abf5ffc4b254917e82d797`
  is an ancestor and 11 Forecast Lab/model-zoo/UI tests pass. Do not repeat
  either completed implementation while lifecycle sequence 23 remains frozen.
- ISSUE-0033, "Alerts and review reminders", is the next canonical phase-01
  dependency-ready issue. It is P2 and `planned`, with no blocking or
  activation dependencies. Clean lane `codex/issue0033-product-20260812`
  starts at exact main `4f7082d06d1695158d8998563dc083e86fe5e364`
  with an empty diff. Implement only local typed alerts, lifecycle controls,
  explicit blocking policy and the accepted Dashboard, Activity Log and
  Instrument Detail surfaces; add no external notification or execution path.
- The bounded ISSUE-0033 delta now provides strict typed generation for all
  eight accepted triggers, deterministic deduplication, CAS-backed local
  persistence, reconstructible snooze/dismiss/expiry state, explicit
  portfolio/order/model incident domains and active-only blocking under a
  caller-supplied policy. Dashboard digest and Activity Log expose local
  dismiss/snooze controls; Instrument Detail remains scoped read-only; corrupt
  storage is visibly unavailable. The 51-test focused alert/UI/persistence/
  architecture set, changed-app offline smoke, Ruff, compile, programme
  freshness and diff hygiene pass. Classify and freeze one complete head for
  parallel review and required hosted validation; `execution_allowed=false`.

## ISSUE-0033 merge and ISSUE-0053 product checkpoint — 2026-08-12

- ISSUE-0033 PR #679 merged exact independently approved head
  `2e51ad9301930b2cfcc2a20d70dd52152719801f` as exact main
  `6df628966908ba15b5359762e1efe99c0199618f`. H-tier run `31545092924`
  passed classifier, preflight, supply chain, Linux, Windows and terminal
  validation. Alerts remain local and informational by default;
  `execution_allowed=false` is unchanged.
- Exact-main audit confirms ISSUE-0034 and ISSUE-0036 already retain their
  product implementations, so they are not being repeated while lifecycle
  sequence 23 remains frozen. ISSUE-0053, "What matters today digest", is the
  next dependency-ready phase-01 product gap: P1/P2, `planned`, no blocking or
  activation dependencies.
- Clean lane `codex/issue0053-product-20260812` starts at exact main
  `6df628966908ba15b5359762e1efe99c0199618f` with an empty product diff. An
  older unmerged ISSUE-0053 branch is reference evidence only; do not merge or
  cherry-pick its stale repository-wide state. Adapt only the bounded digest
  behavior to current main, preserving local-only context and
  `execution_allowed=false`.
- The bounded current-main implementation now renders all nine accepted digest
  categories through one deterministic 12-item context projection. One
  validated snapshot cutoff governs timestamp-attributable score runs, the
  complete active alert population, news/adjusted-price evidence and upcoming
  events. Canonical news metadata and finite positive, instrument-matched price
  evidence fail closed; score and rank truth remain separate; missing evidence
  is not reported as zero change; interrupted exports and both decision fields
  reach manual review. Conflicting same-date adjusted closes fail closed and
  warning no-change is emitted only when both runs provide comparable evidence.
  Macro contradiction comparison remains explicitly manual-review because no
  canonical seam exists. The final review correction passes 34 focused digest
  and 6 run-change tests, plus Ruff, compile, programme freshness and diff
  hygiene. Freeze one replacement head for paired review and fresh required
  hosted validation; add no provider, macro inference or authority.

## ISSUE-0053 merge and ISSUE-0058 product checkpoint — 2026-08-12

- ISSUE-0053 PR #680 merged exact independently approved head
  `a5bd22b0906c55ad789e261e8bfceedb029787b0` as exact main
  `542862895dbdc7f29b1dd4c9b686ac526ae8ab94`. O-tier run `31551246756`
  passed classifier, preflight, supply chain and terminal validation; the
  classifier required no Linux/Windows package jobs. The local digest remains
  context-only and `execution_allowed=false` is unchanged.
- ISSUE-0058, "Closed-source/promotional-claim detector for imported notes",
  is the next dependency-ready product gap: P2, `planned`, no blocking or
  activation dependencies. Clean lane `codex/issue0058-product-20260812`
  starts at exact main `542862895dbdc7f29b1dd4c9b686ac526ae8ab94` with an
  empty diff.
- Extend only the existing manual-note credibility classifier and its current
  UI/audit consumers to expose the accepted promotional and missing-method
  evidence flags. Keep imported notes context-only, local, non-executable and
  visibly attributable; add no provider, network or scoring authority.
- The bounded implementation now persists nine deterministic reason codes and
  per-code states, rejects internally inconsistent structured evidence, and
  leaves legacy rows explicitly unknown/unavailable. News & Context, Data &
  Models, Audit Notes/export and Instrument Detail show the same local evidence;
  corrupt stores fail visibly closed. The consolidated review correction keeps
  source metadata out of claim semantics, handles explicit "no missing" lists,
  verifies persisted states against canonical reclassification and routes all
  presentation reads through the application facade. Fourteen focused tests
  and architecture checks pass; the 204-test affected run had one unrelated
  cache-lifecycle timing failure that passed its single allowed exact retry.
  Ruff, compile, programme freshness and diff hygiene pass. Freeze one
  replacement O-tier candidate for parallel whole-diff/risk review and fresh
  cadence-required hosted package validation;
  `execution_allowed=false` and `executable_authority=false` remain unchanged.

## ISSUE-0058 merge and ISSUE-0051 product checkpoint — 2026-08-12

- ISSUE-0058 PR #681 merged exact independently approved head
  `c37e7452c1ef7abf2568854094d636bc21362935` as exact main
  `5d584e860ade7a7b0ecbbaaaa5efb3161c47c2b9`. Cadence-required run
  `31555021894` passed classifier, preflight, supply chain, Linux, Windows and
  terminal validation. Manual-note credibility remains context-only and
  `execution_allowed=false` is unchanged.
- ISSUE-0046 is mechanically ready but cannot be implemented without the
  distribution and benchmark/cash contracts owned by unresolved ISSUE-0108
  and ISSUE-0112. ISSUE-0051, "Currency-specific risk-free and cash
  comparisons", is the next dependency-ready issue and supplies the cash
  comparison prerequisite for ISSUE-0112 without inventing benchmark policy.
- Clean lane `codex/issue0051-product-20260812` starts from exact main
  `5d584e860ade7a7b0ecbbaaaa5efb3161c47c2b9` with an empty diff. Implement
  only point-in-time, currency-, horizon- and vintage-matched cash comparison
  from official local/imported curve evidence with declared compounding, day
  count, reinvestment and freshness semantics. Missing or incompatible
  evidence remains explicitly unavailable; add no provider, benchmark,
  scoring, broker or execution authority. Expected validation tier is H.
- The bounded implementation adds a pure exact-period cash-return calculator
  for annual, continuous and simple compounding with ACT/360, ACT/365F and
  ACT/ACT-ISDA conventions. Eligible evidence must be an official spot curve
  with complete source lineage, declared reinvestment/freshness, exact
  currency and horizon, and a vintage available by the UTC period-start
  knowledge cutoff. Later revisions, stale/conflicted/malformed evidence,
  unsupported curves and partial lineage fail explicitly unavailable;
  inflation remains context only.
- Caller-supplied validated comparisons now round-trip descriptively through
  `SimpleInstrumentScore`, the canonical scoreboard, benchmark-attribution
  projection, Comparison and Instrument Detail. Missing or malformed injected
  results remain unavailable and cannot alter scores, actions, gates or
  authority. The focused seven-suite regression passes 183 tests; the final
  ISSUE-0051 suite passes 24 tests, with Ruff, compile, programme freshness and
  diff hygiene clean. Freeze one H-tier head for paired whole-diff/risk review
  and fresh Linux, Windows and terminal validation.
- Final root review reproduced and closed two remaining identity/time gaps
  before publication: direct attribution now binds cash evidence to the
  instrument currency, and the normal local score path excludes adjusted-price
  endpoints whose conservative next-UTC-day availability time has not arrived
  instead of synthesising a future decision. The final ISSUE-0051 suite passes
  35 tests; Ruff, compile, programme freshness and diff hygiene remain clean.
  Publish only the resulting replacement H-tier head for paired re-review and
  full hosted evidence.
- Paired review of that head then reproduced five additional bounded defects:
  official provenance and explicit timestamps were not positively enforced,
  curve tenor selection assumed ACT/365F, cash disappeared when broad
  attribution was unavailable, inverted effective/available times survived,
  and missing instrument currency could bypass generic binding. One
  consolidated correction now closes all five with explicit official-source
  authority, timezone-aware curve timestamps, day-count-coupled tenor lookup,
  preserved descriptive cash fields, strict bitemporal ordering and mandatory
  currency at attribution/persistence boundaries. The final ISSUE-0051 suite
  passes 45 tests and directly affected warehouse, attribution, score and trust
  suites pass; static, compile, programme-freshness and diff checks are clean.
  Freeze one replacement H-tier head and disregard cancelled run `31563287001`.
- Final paired review found one direct-ingest timezone bypass plus whitespace
  lineage and non-integral revision coercion. The narrowly scoped follow-up
  now requires explicit timezone-aware timestamps for every curve-bearing
  warehouse row, nonblank lineage at construction/readback and positive
  integral non-boolean revisions. The combined ISSUE-0051 and macro-warehouse
  run passes 67 tests; Ruff, compile, programme freshness and diff hygiene pass.
  Cancelled run `31564924105` is invalid; publish only the new exact head.
- Paired review of `bb98f3151d05501272754b0f26f681f282621233`
  then reproduced coercive revision decoding at both curve model boundaries and
  impossible total returns at serialized/continuous-compounding boundaries.
  The bounded correction makes `MacroObservation.revision` and
  `CurveSnapshot.revision` strict positive integers, rejects boolean/float/
  string identities, and requires every instrument/cash total return to remain
  finite and greater than -100%. The combined ISSUE-0051 and macro-warehouse
  suites, Ruff, compile, programme freshness and diff hygiene pass. Although
  run `31565656403` passed, its rejected head makes that evidence invalid;
  publish one replacement H-tier head for fresh paired review and full gates.
- Paired review of `a6833a337b1e31572b6cb082bbf01bd07555a95d`
  then reproduced three remaining boundary bypasses: ledger/readback revision
  coercion, adjusted-price division underflow to an impossible -100% return,
  and whitespace-only fallback lineage. The consolidated correction now
  validates revisions before bitemporal append and at both bitemporal/macro
  readback, rejects underflowed adjusted returns during construction, and
  requires conditional fallback lineage to be nonblank. All 156 directly
  affected bitemporal, macro, cash, attribution, score and Instrument Detail
  tests pass; Ruff, compile, programme freshness and diff hygiene pass. Run
  `31581729559` is invalid/cancelled; freeze one new H-tier head for fresh
  paired review and full hosted evidence.
- Paired review of `a6a185930517b8668298a0b687aad660a6ffe7be`
  reproduced the final bounded integrity/readback set: coercive or non-finite
  curve points, marker-path and CSV revision coercion, and loss of valid
  scoreboard cash when persisted attribution is unavailable. Hosted run
  `31584468586` is cancelled and invalid. Consolidated product commit
  `90bde0e18934662c1aafe9e27b9c70c371f3d40a` strictly validates curve rates
  and tenors, rejects untyped CSV revisions and malformed stored revisions,
  and preserves validated scoreboard cash in Instrument Detail. The complete
  cash/macro/bitemporal/detail set, directly coupled attribution/score/detail
  suites, Ruff, compile, programme freshness and diff hygiene pass. Freeze one
  fully documented H-tier replacement head for both final reviews and fresh
  Linux, Windows and terminal evidence; no adjacent architecture is added.
- Both reviews rejected `3e9049d329d7ed455b43885f345928ecaa5d22c4`
  after reproducing coercive boolean/string financial values; risk review also
  reproduced a direct curve row whose declared identity disagreed with its
  storage dataset. Run `31587875943` is invalid and failed preflight because
  the four-file affected suite exceeded its 240-second budget. Consolidated
  product commit `f0cded147c0eeaec0cc48ab4b724e6bb4b16c9a6` rejects
  non-numeric cash rates, horizons, returns and excess fields before conversion,
  binds direct curve rows to `curve:<curve_id>` on ingest and readback, and
  keeps the Instrument Detail fallback regression in the focused ISSUE-0051
  suite so the unchanged slow UI file is no longer selected. All exact
  regressions, complete cash and macro suites, bitemporal coverage, Ruff,
  compile, programme freshness and diff hygiene pass. Freeze one documented
  replacement H-tier head for paired review and fresh hosted evidence.
- Paired review rejected `df9f7115f7df5992828798fe6e36f56ef765d63f`
  after reproducing future publication chronology accepted as then-known curve
  evidence and scoreboard cash accepted without a declared instrument currency.
  Run `31589943093` is cancelled and invalid. Consolidated product commit
  `e7b5bec9b74fe3ed0fc46541abbbb58c43102d48` requires
  `published_at <= available_at` at curve ingest/readback, carries publication
  identity through cash construction, validation, scores, attribution,
  persistence and projections, and requires nonblank instrument currency for
  selector fallback. Exact publication/currency regressions, complete cash and
  macro suites, coupled attribution/score/detail suites, Ruff, compile,
  programme freshness and diff hygiene pass. Freeze one replacement H-tier
  exact head for paired review and fresh Linux, Windows and terminal evidence.
- Paired review rejected `8e13454f837383f91ba57a76b63c9fbd88b99210`
  because official snapshots synthesized publication from availability,
  boolean/string/non-finite proxy horizon bounds were coerced, and the
  projection helper omitted its mandatory non-execution flag. Run
  `31591207680` is cancelled and invalid. Consolidated product commit
  `ef02901442c360e494cca8999aaf80d04f24acb3` requires and preserves an
  explicit timezone-aware snapshot publication timestamp, strictly validates
  finite mapping bounds, and makes cash projection/readback round-trip with
  `execution_allowed=false`. Distinct and inverted publication, malformed
  mapping and direct round-trip regressions plus complete cash/macro/bitemporal
  suites, Ruff, compile, programme freshness and diff hygiene pass. Freeze one
  replacement H-tier exact head for paired review and fresh hosted gates.
- Paired review rejected `7245e76ac27606f9542fd71dd354d178fcdcd5b1`
  after reproducing partial multi-point curve visibility, inferred availability
  accepted as exact, and persisted cash accepted without instrument currency.
  Run `31593071919` is cancelled and invalid. Consolidated product commit
  `e6a2b209a05a0ed4d51370a72e6a58f03a56f6ad` binds every curve row to the
  declared snapshot point count, rejects incomplete snapshots and non-exact
  availability/timezone confidence, and clears persisted cash fields when
  currency is absent. Exact partial-write, inferred-confidence and persisted
  currency regressions plus complete cash/macro/bitemporal and coupled
  attribution/score/detail suites, compile, programme freshness and diff
  hygiene pass. Freeze one replacement H-tier head for paired review and fresh
  Linux, Windows and terminal evidence.
- Paired review rejected `ea1f13105a22f7824a1870be14600f0f1d4b6435`
  for duplicate or missing direct tenors and unsupported reinvestment semantics.
  Run `31594650274` is cancelled and invalid. Consolidated product commit
  `a418e341941bd4d1ac7fa25527d73ab700ff4e6a` converts malformed direct-row
  validation to explicit unavailable, requires complete unique tenor identity,
  and permits only the supported `reinvested_income` cash convention at
  snapshot, readback, construction and serialized validation boundaries.
  Exact missing/duplicate-tenor and reinvestment regressions plus complete
  cash/macro/bitemporal suites, Ruff, compile, programme freshness and diff
  hygiene pass. Freeze one replacement H-tier head for paired review and fresh
  hosted validation.
- Paired review rejected `b311951978c8a29d704b03bb084c277c9365a4fa`
  after reproducing malformed persisted curve rows escaping readback and a
  missing reinvestment convention being treated as supported. Exact-head run
  `31596482736` is cancelled and invalid. Consolidated product commit
  `0f873715766c48815ceea8f471eb01d39c512183` moves persisted-row decoding
  inside the fail-closed curve boundary and requires the supported
  `reinvested_income` convention at snapshot and readback boundaries. Exact
  corrupt-ledger and missing-reinvestment regressions plus the complete
  cash/macro/bitemporal suite, Ruff, compile, programme freshness and diff
  hygiene pass. Freeze one replacement H-tier head for paired final review and
  fresh hosted validation.
- Paired review rejected `4bfd2203b8c4f9891600608b0fde7411100a0f72`
  with six reproduced evidence-boundary defects: subsecond timestamp loss,
  duplicate or regressing curve revisions, coercive authority booleans,
  ambiguous financial dates, a builder/readback cutoff mismatch, and direct
  curves lacking official lineage suppressing valid fallback. Exact-head run
  `31598259140` is cancelled and invalid. Consolidated product commit
  `16aa063435d95cea57f5d71204336bc8c5dc3000` preserves subsecond chronology,
  validates persisted revision history, strictly types policy/authority data,
  requires canonical dates and cutoffs, and fails closed on unofficial curve
  lineage. Exact adversarial regressions and the complete affected focused
  suites, Ruff, compile, programme freshness and diff hygiene pass. Freeze one
  replacement H-tier head for paired final review and fresh hosted validation.
- Paired review rejected `8f37a76abe2742985f48c7074a7c7a5fd05f37b0`
  after reproducing malformed adjusted-price rows being discarded, partial
  multi-point curve writes, nullable curve revisions widened in mixed-row
  persistence, and non-risk-free rows accepted as cash curves. Exact-head run
  `31601620259` is cancelled and invalid. Consolidated product commit
  `695acd192656107059e77361d33d2efe3f775012` strictly validates every adjusted-price row in both calculation
  paths, commits each curve snapshot atomically, preserves nullable integer
  revision identity through persistence, and requires `risk_free` curve kind
  throughout ingest and readback. Exact adversarial regressions and the full
  affected 247-test focused surface, Ruff, compile, byte-clean generation and
  diff hygiene pass. Freeze one replacement H-tier head for paired final
  review and fresh hosted validation.
- Paired review rejected `b78373eb8759c02b5ced04ad0872bae38f8fab6e`
  because cash unit/kind/input-authority identity was not preserved, curve
  history validation was outside the serialized append boundary and poisoned
  earlier decision-time prefixes, and manifest failure left a committed batch
  that could not be resubmitted. Exact-head run `31605516797` is cancelled and
  invalid. Consolidated product commit
  `24c02406819052da86c297fcf9d5f5ca5b3f88d9` carries and validates decimal risk-free evidence and disabled
  authority through every projection/readback, serializes prospective history
  validation with all snapshot points, limits readback validation to eligible
  history, and rolls database changes back when manifest projection fails.
  Exact unit/authority, concurrent-conflict, chronology-prefix and manifest
  rollback regressions plus the complete affected focused surface, Ruff,
  compile, byte-clean generation and diff hygiene pass. Freeze one replacement
  H-tier head for paired final review and fresh hosted validation.
- Paired review rejected `4547bb9effb5cc281153453fcd51c660cb244df3`
  because `pd.NA` direct-score status and instrument currency could escape as
  ambiguous-boolean exceptions. Exact-head run `31620960088` is cancelled and
  invalid. Product commit `2933fc2df7c52d06df579b835fa6b54cfdc9ccbb`
  strictly normalizes those two scalar boundaries to unavailable; exact
  regressions and the affected suites pass with static and diff checks. Freeze
  one replacement H-tier head for paired final review and hosted validation.
- Paired review rejected `1ed00119a5978ae656380064bdfbf0a96f61da2f`
  because offset-bearing adjusted-price timestamps were reduced to local dates
  before UTC availability and direct-score `pd.NA` instrument currency could
  raise. Exact-head run `31622330986` is cancelled and invalid. Product commit
  `45ea6cf56d343ab5e7d6cbe8c3944a7aeceee1e5` enforces date-only/UTC-midnight
  price endpoints and strictly types direct-score currency. Exact regressions
  and affected suites pass with static and diff checks. Freeze one replacement
  H-tier head for paired final review and hosted validation.
- Paired review rejected `5f7f4144529f923c6499498ee29db98ef97c48e8`
  because the exported return helper accepted non-positive periods and cash
  comparison evidence lacked immutable instrument identity. Exact-head run
  `31624964263` is cancelled and invalid. Product commit
  `56f3d13f17fc723478d4a853ba59be908abc8c43` rejects same-day/inverted
  periods and binds instrument identity through calculation, validation,
  score, attribution, persistence and selector readback. Same-currency swap
  and period regressions plus the complete affected focused surface, Ruff,
  compile, byte-clean generation and diff hygiene pass. Freeze one replacement
  H-tier head after the attributable packaged gate reaches a terminal result.
- Paired review rejected `91881c4bc6d30c0f22fd469d4f854064ecdda7ed`
  because fallback provenance could contradict the selected curve. Exact-head
  run `31623845675` is cancelled and invalid. Product commit
  `d21ec796e9aa52eb9ef89f8a33cfc7e1c0031eba` requires primary evidence to
  omit `fallback_from` and fallback evidence to name a distinct nonblank
  primary in construction and serialized readback. Exact regressions and the
  ISSUE-0051 suite pass with static and diff checks. Freeze one replacement
  H-tier head for paired final review and hosted validation.
- Paired review rejected `fd112929181768b6d065b45da97f9e5929bc0357`
  because generic curve ingestion bypassed serialized admission, future
  malformed rows poisoned earlier decision-time reads, the JSON manifest could
  diverge from a failed SQLite commit, direct attribution omitted unit/kind,
  and non-string status could escape fail-closed validation. Exact-head run
  `31609238072` is cancelled and invalid. Consolidated product commit
  `4ed063c0b7411a0e70e95d76a5b84e0d5b618333` rejects generic curve rows,
  filters raw history before decoding, stores the authoritative immutable
  manifest with points in SQLite while treating JSON as projection, and
  preserves cash identity with strict malformed-status handling. Exact
  regressions and the complete affected focused surface, Ruff, compile,
  byte-clean generation and diff hygiene pass. Freeze one replacement H-tier
  head for paired final review and fresh hosted validation.
- Paired review rejected `c559e0cd0c0663d58eefdff81836aed26cde96dc`
  because unavailable direct scores retained injected cash fields and a primary
  with missing freshness suppressed a valid fresh fallback. Exact-head run
  `31617207389` is cancelled and invalid. Consolidated product commit
  `3840fd5fe5fb3c9c91d74fd366ded6b92a34930b` clears all unavailable cash
  projection fields and requires both freshness declarations to be explicitly
  fresh before selection. Exact regressions and the complete affected focused
  surface, Ruff, compile, byte-clean generation and diff hygiene pass. Freeze
  one replacement H-tier head for paired final review and hosted validation.
- Paired review rejected `5d8f7203648442928fcbad55ab3d02385a0df820`
  on one malformed-input escape: `pd.NA` cash currency was normalized before
  the guarded boundary. Exact-head run `31619460965` is cancelled and invalid.
  Product commit `77e0b932e2cb97f7c920e44a3daa3bfbdeb3f6e2` strictly types evidence
  currency inside the fail-closed block; the exact regression and complete
  ISSUE-0051 suite pass with static and diff checks. Freeze one replacement
  H-tier head for paired final review and fresh hosted validation.
- Paired review rejected `302fb671ab25c23cff9a2c45bbe405f836562b10`
  for inverted persisted chronology, blank curve lineage, direct-score cash
  bypass, stale-primary fallback suppression, future malformed generic history
  poisoning, and duplicate-key proxy configuration. Exact-head run
  `31613846758` is cancelled and invalid. Consolidated product commit
  `db7d17166875324c3c5802bdd6f11a13e78df7a3` closes those six exact
  boundaries with fail-closed chronology/lineage/config validation, cutoff-first
  decoding, fresh fallback selection, and canonical score cash sanitization.
  Exact regressions and the complete affected focused surface, Ruff, compile,
  byte-clean generation and diff hygiene pass. Freeze one replacement H-tier
  head for paired final review and fresh hosted validation.

- Final paired review of `366407d644fffd0e6276b41e1292a73f05a7a771`
  produced one approval and one reproduced identity defect: Instrument Detail
  could validate persisted scoreboard cash against the row's self-declared
  currency instead of the configured instrument currency. Hosted run
  `31631451728` was cancelled and is invalid. The sole consolidated correction
  binds attribution fallback to the canonical instrument ID and currency passed
  by `build_instrument_detail`; contradictory USD evidence for a configured EUR
  instrument remains unavailable. The complete ISSUE-0051 suite, Ruff,
  compile, byte-clean programme generation and diff hygiene pass. Freeze one
  replacement H-tier head for both exact-head reviews and fresh Linux, Windows
  and terminal validation; `execution_allowed=false` remains unchanged.

- Paired review of `70eae22148fc3b32779991cd44d73b0c4759df13`
  approved the canonical attribution correction but reproduced two additional
  malformed persistence boundaries before merge: non-scalar instrument
  currency could raise during benchmark-attribution publication, and malformed
  persisted curve `ingested_at` lineage could read back as available. Run
  `31635448229` is cancelled and invalid. One consolidated correction requires
  scalar textual currency before cash persistence and timezone-aware
  `ingested_at` during persisted curve-history validation. Exact regressions and
  the complete ISSUE-0051 and macro-warehouse suites pass with Ruff, compile,
  byte-clean programme generation and diff hygiene. Freeze one replacement
  H-tier head for both exact-head reviews and fresh hosted evidence;
  `execution_allowed=false` remains unchanged.

- Whole-diff review approved `dac31303204db8b7a6c0dc39a11bb6ff3e6d576c`,
  while risk review reproduced one well-formed but impossible PIT chronology:
  curve `ingested_at` could precede `available_at` at admission and persisted
  readback. Run `31637457785` is cancelled and invalid. The sole follow-up
  enforces `ingested_at >= available_at` at both existing validation boundaries
  and adds admission/no-write and persisted-unavailable regressions. The full
  macro-warehouse suite, Ruff and diff hygiene pass. Freeze one replacement
  H-tier head for paired review and fresh hosted evidence; no adjacent
  chronology or storage contract is changed and `execution_allowed=false`
  remains unchanged.

## ISSUE-0051 merge and bounded ISSUE-0018 projection recovery

- ISSUE-0051 PR #682 merged exact reviewed product head
  `83c2843632e2e88a39fe3fcefa21858b436aada4` as
  `6b9a79d86e4d17656619c1f969b5f44a2d47c4d9`. H-tier run
  `31638791406` passed classifier, preflight, supply chain, Linux and Windows
  with 3,573 tests per platform, and terminal validation. The merge has exact
  parents `5d584e860ade7a7b0ecbbaaaa5efb3161c47c2b9` and the reviewed head;
  `execution_allowed=false` remains unchanged.
- Exact-main convergence run `31642819307` failed closed with zero desired
  writes because the latest existing ISSUE-0018 status authority has no remote
  projection. Live reconciliation proves this is the sole mismatch: authority
  sequence 23 expected one ISSUE-0018 `implemented_initially -> integrated`
  event while GitHub issue #22 still has zero comments. Original writer run
  `31497001531` attempt 1 recorded `transport_writes=0` before a caller-proof
  read failure; attempt 2 correctly remained ineligible.
- The one permitted bounded H-tier repair is isolated in clean worktree
  `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit_wt_post0051`, branch
  `codex/post0051-convergence-20260813`, from exact base
  `6b9a79d86e4d17656619c1f969b5f44a2d47c4d9`. It authorizes only a fresh,
  first-attempt, OIDC-attested dispatch for the exact unrecoverable ISSUE-0018
  authority, requires unchanged historical candidate and ledger blobs, one
  absent projection, all prior authorities reconciled, and post-write full
  reconciliation with zero-action readback. It adds no write retry,
  compensation, body rewrite, broader resource authority or lifecycle change.
  Freeze only after focused tests, static checks, paired review and fresh
  Linux/Windows/terminal H-tier evidence.

## ISSUE-0018 recovery completion and ISSUE-0051 lifecycle start

- Bounded repair PR #683 merged exact reviewed head
  `9d2a08800d09bb71313ebe3addc2e2ee2ec78b37` as
  `84f0353573f8ff7d49af1934d3149271009fc22c`. H-tier run
  `31645482556` passed Linux, the documented single Windows timeout retry and
  authoritative terminal validation; both final independent reviews approved.
- First-attempt recovery run `31650363325` appended exactly the missing
  ISSUE-0018 proposal and receipt. Its evidence records
  `terminal_status=applied_and_verified`, two transport writes, full authority
  reconciliation, `zero_action_readback=true` and `execution_allowed=false`.
  Independent generic live reconciliation is zero action with no blocked,
  create, update, close or reopen operations. The bounded repair is complete
  and must not be reopened without a fresh deterministic failure.
- Clean branch `codex/issue0051-lifecycle-start-20260813` starts from exact
  main `84f0353573f8ff7d49af1934d3149271009fc22c`. Record only ISSUE-0051
  `planned -> in_progress`, bound to merged product PR #682, reviewed merge
  `6b9a79d86e4d17656619c1f969b5f44a2d47c4d9`, H-tier run
  `31638791406` and the exact independent product reviews. Generate all
  projections mechanically, prepare the checksum-bound status authority, and
  require E-tier guards plus ordered writer and zero-action readback before the
  separate atomic two-hop completion transaction.

- ISSUE-0051 initial lifecycle PR #684 merged exact reviewed head
  `342316801ffdb4efc62cdccd160067f2047ef62b` as
  `c546f1dd4b2c01356c7164fafa18bab065efa2d1`. Tier-O run `31651266717`,
  standalone status guard and both independent reviews passed. Ordered writer
  run `31651750441` applied only `planned -> in_progress`, reconciled all
  authority projections and returned `zero_action_readback=true` with
  `execution_allowed=false`.
- Clean branch `codex/issue0051-completion-20260813` starts from exact main
  `c546f1dd4b2c01356c7164fafa18bab065efa2d1`. Append exactly the ordered
  ISSUE-0051 hops `in_progress -> implemented_initially -> integrated`, bind
  both to product PR #682 and the same review/evidence tuple, use one aggregate
  proposal and receipt, and require full generic reconciliation plus zero-action
  readback. Do not change product code or dependency edges.

## ISSUE-0051 convergence and ISSUE-0059 integration

- ISSUE-0051 completion PR #685 merged exact independently approved head
  `381c7d013c4e8e326eb3ee68ac5f39adef60bcc3` as
  `e5c70f7f08665f5b041e4a20614061ee9f8a85b8`. Cadence-required run
  `31652457420` attempt 2 passed Linux, Windows and terminal validation after
  the one documented transient retry; status guard, preflight and supply chain
  also passed. Writer run `31666997864` applied the ordered aggregate replay
  with one proposal and receipt, two transport writes, full authority
  reconciliation, `zero_action_readback=true` and `execution_allowed=false`.
- Clean branch `codex/issue0059-integration-20260813` starts from exact main
  `e5c70f7f08665f5b041e4a20614061ee9f8a85b8`. Record only ISSUE-0059
  `implemented_initially -> integrated`, bound to product PR #574 exact head
  `37ef3fc9e18c682408ecc079fc65e85426ccee7e`, merge
  `80c63200e733fada6ae2d76ac67feb776f281c38`, release run `30338519123`,
  status guard `30338519047` and supply-chain run `30338519237`. Preserve all
  dependency edges and product code, prepare the one-update authority, and
  require exact-head review, focused E-tier guards, ordered writer and generic
  zero-action readback before resolving ISSUE-0112 dependency evidence.

## ISSUE-0059 convergence and ISSUE-0112 dependency readiness

- ISSUE-0059 integration PR #686 merged exact independently approved head
  `560e68511eb228d831f9c31e0babdafa26c0a57e` as
  `87b05852121ff6ecdd1c9b1b8ae5ed423875523c`. Cadence run `31668262647`
  passed Linux and, after the one documented 1,800-second timeout retry,
  Windows and terminal validation. Writer run `31672396480` applied one
  proposal and receipt with two transport writes, full reconciliation,
  `zero_action_readback=true` and `execution_allowed=false`.
- Clean branch `codex/issue0112-dependencies-20260813` starts from exact main
  `87b05852121ff6ecdd1c9b1b8ae5ed423875523c`. Record only the two independent
  ISSUE-0112 dependency edges to the integrated ISSUE-0051 cash-comparison and
  ISSUE-0059 benchmark-attribution contracts in one atomic same-consumer batch.
  Preserve ISSUE-0112 at `planned`, change no product code or execution
  authority, generate projections mechanically, and require focused E-tier
  guards and exact-head review before product implementation.

## ISSUE-0112 product final production-path correction

- PR #688 head `25677bcbf96ec4f111ce47e9c732401a3df8cf6f` is rejected and
  hosted run `31709228880` is cancelled/stale. The complete paired verdict
  reproduced two bounded acceptance defects: `content_hash` could count as a
  substantive nested VWCE fact, and production attribution, validation,
  feature and forecast paths could omit canonical benchmark/cash declarations
  or select the first enabled instrument.
- One consolidated working-tree correction now treats `content_hash` as
  metadata, shares one fail-closed canonical reference adapter across the real
  production callers, derives benchmark attribution/features/forecasts only
  from the resolved canonical data identity, and preserves explicit N/A when
  resolution is absent. Caller-supplied raw benchmark returns cannot bypass the
  canonical declaration. The affected 232-test collection, architecture
  boundaries, Ruff, attributable targeted mypy, compile, byte-clean programme
  generation, imports and diff hygiene pass; `execution_allowed=false` remains
  unchanged. Freeze one replacement exact head for paired review and fresh
  Linux, Windows, terminal and packaged H-tier evidence.
- Replacement head `0880f0cfc3d7cc1d8ad62886bdf579e3ea65e77f` is rejected by
  both exact-head reviewers and run `31713061927` is cancelled/stale. Their
  complete reproduced set showed remaining first-column benchmark use in
  backtest/regime/score paths, Training Centre context loss, mutable forged
  projections, schema-divergent N/A evidence, stale forecast/backtest/feature
  cache acceptance and optional-model raw returns labelled as excess. One
  consolidated caller/provenance correction removes every demonstrated
  fallback, reconstructs and seals declarations, binds production cache write
  and readback to canonical reference identity, routes all snapshot/UI callers,
  and post-processes every model's relative fields from the same canonical
  series or N/A. Freeze only after the complete affected tests, static checks,
  byte-clean generation and package proof pass; no workflow, authority or
  execution boundary changes.
- Head `2f67ca378feb2d148c92ff686728ab460dfa7df1` is rejected and run
  `31770710533` is cancelled/stale. Whole-diff review approved, but risk review
  reproduced feature and forecast payload substitution under a valid reference
  sidecar. One consolidated correction now publishes each payload and identity
  record through the existing recoverable atomic group, binds the pair by
  SHA-256, and re-verifies one guarded snapshot before use. Valid and legacy
  unbound reads retain their established behavior when no binding is requested;
  bound legacy, malformed, substituted, interrupted or interleaved pairs fail
  closed. Fifty-eight focused cache, recovery, settings and adjacent tests plus
  Ruff, compile and diff hygiene pass. Freeze one replacement exact head for
  paired review and fresh H-tier evidence; no generic atomic-I/O, workflow,
  financial, authority or `execution_allowed=false` changes.
- Head `59caeac64d422e39e06ec57b8032eaebcd00eb72` is rejected by both
  final reviewers and run `31774026353` is cancelled/stale. Both reproduced the
  same cross-identity TOCTOU: forecast selection validated identity A, then a
  second guarded read could accept an atomically published identity-B pair
  because it rechecked only the checksum. The one newly demonstrated correction
  shares complete snapshot validation across selection and final read, requiring
  the requested universe, settings, reference identity, identity hash and payload
  checksum on that second snapshot. A deterministic A-to-B interleaving regression
  now fails closed; no adjacent cache or persistence behavior changes.
- Head `69cdce6e47d3c3883daab2859fd5b3f32f195ac1` passed risk review but
  is rejected by whole-diff review; run `31774945960` is stale. A settings-only
  request filtered no forecast candidates, so a newer cache from another settings
  revision could mask an older valid file. Candidate selection now applies the
  same snapshot validator whenever universe, settings or reference identity is
  requested, with a deterministic newer-stale/older-valid regression. The stale
  run also exposed an unrelated-order dependency in the directly changed backtest
  rollback test; that test now stubs manifest reservation so it proves only its
  atomic-output boundary and is self-contained. No production backtest behavior
  or validation machinery changes.
- Head `20d619fb996038970f81e655697adfcf5c15cc73` is rejected and run
  `31777912307` is stale. The paired reviews reproduced two malformed-sidecar
  escapes: recursive valid JSON raised `RecursionError`, and Python mapping
  equality admitted `execution_allowed: 0` as equal to `false` when the claimed
  hash was copied. Existing read boundaries now treat recursive decode/hash as
  unavailable and require the stored identity's recomputed canonical hash to
  equal both its claim and the requested identity hash. Direct regressions cover
  feature, forecast, service-match and guarded-payload readers; no generic JSON,
  atomic-I/O, financial, authority or execution behavior changes.
- Head `8b4ef8d722a84e246489d2eb1cc5eed50f807f96` is rejected and run
  `31778851004` is cancelled/stale. Review found three remaining consumers of
  the same demonstrated contracts: supplied feature attrs and cached backtest
  metadata still used type-insensitive mapping equality, and forecast row
  filtering ignored a settings-only request. Both identities now use the shared
  recomputed-hash verifier; backtest publication persists the identity hash; and
  row filtering activates for universe, settings or reference requests. Direct
  signal, backtest-tamper and mixed-source settings regressions cover those exact
  paths. No adjacent service, financial, persistence or authority change.
- Head `3e7f5677e72de7f2f5ca8a2ebe67e66899afd267` is rejected and run
  `31780004420` is cancelled/stale. Final review reproduced backtest payload/
  sidecar cross-binding between concurrent writers, a checksum-valid feature
  parquet missing `date` that raised instead of becoming unavailable, and deep
  recursion escaping the canonical registry/application validators. Backtest
  payloads, sidecars and metadata now publish in one existing atomic group and
  cached reuse parses one guarded complete snapshot. Feature schema conversion
  stays inside its fail-closed boundary, and the two canonical validators map
  recursive malformed input to their existing unavailable/error contracts.
  Exact interleaving, missing-schema and 10k-depth regressions cover the set;
  no atomic-I/O, workflow, financial, authority or execution redesign.
- Head `a3ae5dbcbe44b21b39677aeb213207ebe7261ac3` is rejected and run
  `31782031303` is cancelled/stale. Complete review reproduced four bounded
  contract gaps: cached backtest projection/strategy metadata was not bound to
  the fresh canonical context; benchmark-absent backtests leaked absolute
  momentum into relative-strength fields; two remaining recursive malformed
  reference paths escaped; and `Selection`/`VwceAnchorResolution` accepted wrong
  primitive types. Publication/readback now hash and validate the complete
  canonical backtest binding, benchmark-absent relative fields remain N/A, the
  recursive paths use existing fail-closed results, and both value objects reject
  the demonstrated types. Direct regressions cover only those cases; no adjacent
  financial formula, persistence, workflow, authority or execution change.
- Head `cf0edc22aab8be16cb5c22c000929ebf6646bc72` is rejected by both
  exact-head reviewers and run `31794764667` is stale. The consolidated
  demonstrated set is limited to three paths: the UI forecast writer used a
  different request identity from configured and candidate readers, malformed
  canonical instrument objects escaped the unavailable boundary, and
  list-valued cost or cashflow chronology raised instead of failing closed.
  Apply one bounded correction with an actual writer-to-snapshot readback
  regression and direct malformed-input regressions, then freeze one new head
  for paired review and fresh Linux, Windows, terminal, package and pilot
  H-tier evidence. Preserve exact identity validation, all existing authority
  boundaries and `execution_allowed=false`.
- The single consolidated working-tree correction now derives the interactive
  writer arguments from the same canonical `[60]`/optional-models-disabled
  identity used by configured and candidate readers, rejects non-mapping
  instrument evidence at both resolution boundaries, and classifies non-scalar
  cost/cashflow chronology as invalid before pandas evaluation. The complete
  affected focused collection, 64-test changed validation with offline smoke,
  Ruff, compile, registry validation, byte-clean programme generation and diff
  hygiene pass. Freeze and publish one replacement exact head for paired final
  review and fresh full H-tier evidence.
- Hosted run `31797431753` attempt 2 completed all 526 changed tests within the
  existing 240-second bound (`220.694s`) and corrected the earlier timeout-only
  diagnosis. Its sole failure demonstrated a point-in-time defect: a canonical
  cash decision after the actual observation time could admit a not-yet-
  available adjusted endpoint. One bounded correction now rejects that future
  decision before local curve resolution and makes the available-flow fixture
  use an actually eligible endpoint. The exact failing regression, the new
  explicit replay-observation regression, the full cash-comparison suite,
  focused simple-score cash tests, Ruff, compile, byte-clean programme
  generation and diff hygiene pass. Freeze one replacement exact head; do not
  alter the validator timeout, test selection, CI architecture or authority.
- Exact head `61ef80802eb58e23ac55f888c78e3c1ff66247b2` is rejected by both
  final reviewers, and hosted run `32470544434` is stale after the changed-test
  collection reproducibly exceeded its 240-second bound. The complete bounded
  finding set is: propagate the snapshot replay date through every production
  cash-score caller; reject malformed, unordered or timezone-naive canonical
  cash chronology; reject non-scalar breadth chronology/provenance; and raise
  only the finite changed-test timeout to 360 seconds without altering test
  selection, sharding, classification or workflow topology. One consolidated
  working-tree correction and direct regressions now cover those four findings;
  freeze a replacement exact head only after focused verification and then run
  paired review plus fresh full H-tier evidence.
- Exact head `7f121763597cd0b06d08d7821f405eb9f8658865` is rejected by both
  final reviewers, and run `32473727621` is cancelled/stale. Both reproduced
  one production chronology conflict: snapshot reference inputs declared the
  adjusted-price end date at `D` but the decision at `D 23:59:59`, one second
  before the endpoint becomes conservatively available, while score callers
  supplied only the date label. The single bounded correction declares the
  decision at the existing `D+1 00:00:00Z` availability instant and propagates
  that full canonical timestamp through all four score callers. A real snapshot
  reference writer-to-score readback and the positive local-curve path now use
  the actual final endpoint and pass focused validation. Freeze one replacement
  head for paired review and fresh full H-tier evidence; make no adjacent change.
- Exact head `d0f3d54f3dcb23b39e80b8b5938afb3aa4548ce0` is rejected and run
  `32475420169` failed preflight. The complete new demonstrated set is confined
  to malformed candidate breadth: invalid candidate CSV bytes and non-scalar
  `sma200_signal` could still escape the production score builder. The same run
  identified two tests retaining the superseded end-of-day cutoff, and review
  required the snapshot chronology regression to invoke the real score builder.
  One consolidated correction makes both malformed paths unavailable, extends
  writer-to-score readback, and aligns only those two coupled expectations with
  `D+1 00:00:00Z`. Direct adversarial and coupled tests pass; freeze one final
  head for paired review and fresh H-tier evidence with no further broadening.
- Exact head `c548c48becb08040ed219597fa38619d2c5e35a0` is rejected, and run
  `32477488001` is stale after all changed product tests passed in 320 seconds
  but the enforced architecture boundary failed. Review reproduced the parallel
  raw-candidate CSV escape, the separate score-path `_bool_like` non-scalar
  escape, and a regression whose default directory was bound before monkeypatch.
  The consolidated correction gives both candidate loaders dynamic fail-closed
  boundaries, rejects non-scalar trend evidence in the real candidate scorer,
  and routes the dashboard's two demonstrated implementation imports through
  the existing application facade. Direct builder adversarial tests and the
  button/architecture boundary suite pass. Freeze one replacement head for
  final paired review and fresh H-tier evidence; no adjacent redesign.
