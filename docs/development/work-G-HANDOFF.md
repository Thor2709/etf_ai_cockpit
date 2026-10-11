# Work-G handoff
STATUS: partial; TimesFM works in SHADOW; Toto is blocked under the no-package-change constraint.
BASE: ebaffd524c4a0cf39971a5a0b827613ff6faac50; branch fix/work-G; local commit only.
OWNER: .owner-root settings saved atomically as version 3; shadow_optional_models=true; timesfm3 enabled.
RUN: 2026-10-09 forecast date, 81 enabled instruments, primary 60-trading-day horizon; 324 rows.
TIMESFM 2.5: 80 ok, 1 unavailable (RABO.AS: fewer than two positive observations).
TIMESFM 3.0: 80 ok, 1 unavailable (same RABO.AS history); non-commercial personal-use licence accepted by owner.
TOTO 2.0: 0 ok, 81 unavailable; local Toto2 weights exist, but installed toto-ts 0.2.0 implements Toto1.
TOTO PROOF: installed Toto rejects the owner config with seven missing architecture parameters; no Toto2 implementation in installed package.
TOTO SOURCE: https://github.com/DataDog/toto/blob/main/toto2/README.md specifies toto2.Toto2Model / toto-2.
GPU/RUNTIME: RTX 5070 Laptop GPU; real CUDA inference confirmed for both TimesFM models; full runs 36.827s and 41.423s.
CPU: real 512-observation AIR/60-day inference ok for both models (0.376s / 1.565s); auto CPU selection also mocked/tested.
SHADOW PROOF: 81 scoreboard rows exactly equal before/after for decision, final_label and all selected numeric score axes.
SHADOW PROOF: 81 signal scores/actions/research states/portfolio review states exactly equal; native scoreboard has no final_action column.
GOVERNANCE: optional owner rows model_allowed_in_score=false; existing weights/promotion gate unchanged; execution_allowed=false.
LEAKAGE: TimesFM3 windows through 2023-11-30 flagged possibly_leaked (Wikipedia Nov 2023; Trends Dec 2022); other cutoffs unknown.
LEAKAGE: all TimesFM2.5/Toto windows possibly_leaked; all new optional rows diagnostic-only, promotion_evidence_allowed=false.
FILES: model adapters/scores/registry/inventory/zoo; forecast service/catalogue bridge; model schema/config example; CLI; Forecast Lab labels; two Work-G test files.
TESTS: six new focused tests pass; 51 focused/affected tests pass; all 15 tests selected by timesfm or toto pass; existing tests unchanged.
REQUESTED SUITE: 47 pass / 9 parity failures; untouched base reproduces identical failed tests and difference counts (57-instrument fixtures vs 58).
EVIDENCE: .owner-root/work-g-evidence/{owner-run.log,device-proof.json,shadow-proof.json,scoreboard-before.csv,scoreboard-after.csv,parity-base-proof.json,tests.log,base-parity.log,focused-tests.log,correction-tests.log}.
NEEDS_OPUS_DECISION: compatible Toto2 runtime requires a forbidden package change; no package was installed, upgraded or downgraded.
NEEDS_OPUS_DECISION: pre-existing parity fixtures need separate repair authority outside this packet; no tests/fixtures/gates weakened.
WEIGHTS: .owner-root/models junction read only; no weight writes, downloads, broker writes, deployment, push or release.
