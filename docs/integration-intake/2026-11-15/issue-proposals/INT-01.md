# INT-01 — Optional extras, lock files, intake records, offline boundary

**Status: proposal only; not a canonical GitHub issue.**

- Priority: `P0`; gate `G2`; lane `X`; estimated size `small`
- Logical prerequisites: `-`; source-file serialization: `-`
- Readiness: `READY for quant and pypdf (U1 approved 2026-11-15); other extras on later approval`
- Intended files: `pyproject.toml; configs/supply_chain_intake.yaml; packaging/THIRD_PARTY_NOTICES.md; plugins/builtins.py`
- Baseline: `Thor2709/etf_ai_cockpit@1afe17c09fb53299f7c46459254d94ce8323acd1`
- Authority: canonical issue admission must be reviewed by project root and generated via the repository's guarded control process.

## Proposed technical issue

Optional extras, lock files, intake records, offline boundary
- Gate G2 | Priority P0 | Size small | Depends on: none | Features: F0202, F0203
- Authority: U1 approved for `quant` and `pypdf`. This issue adds those now. It adds `sec`, `documents`, `retrieval` and `chronos-forecasting` (same steps) only after the owner approves each.
- Targets: `pyproject.toml`, `requirements-quant.txt` (new), `requirements-sec.txt` (new), `requirements-documents.txt` (new), `requirements-retrieval.txt` (new), `configs/supply_chain_intake.yaml`, `packaging/THIRD_PARTY_NOTICES.md`, `plugins/builtins.py` (`default_plugin_registry:112`), `models/local_weights.py` (weight inventory `:48`).
- Exact pins: `skfolio==1.12.9`, `arch==9.0.0`, `statsmodels==0.15.0`, `lightgbm==4.7.0`, `scipy` (extra `quant`); `edgartools==6.1.0` (extra `sec`; tag `c7ae63b5`, the needed modules are confirmed at the tag); `docling-slim[format-pdf,models-local,feat-ocr-rapidocr-onnx,feat-chunking]==2.150.0` (extra `documents`); `fastembed==0.9.1` (extra `retrieval`); `chronos-forecasting==2.3.2` (added to `models`); `pypdf` declared in `parsers` (imported at `data/pillar3_extract.py:200`, declared nowhere). Lock files record the hash of every wheel.
- Steps:
  1. Resolve each extra against the release lock on Windows for Python 3.11 and 3.12 (pandas 2.3.3, numpy 2.4.4, scikit-learn 1.9.0, pyarrow 25.0.0, plotly 6.9.0). Known bump: `lxml` 6.1.1 to >= 6.1.3. Record whether `cvxpy-base` and `clarabel` have wheels.
  2. One intake record per project with all required fields; `review_status: approved` only after the licence file is read at the pinned release.
  3. Model weights: one inventory row per weight **file** (repository, revision hash, sha256, licence, source of any ONNX conversion). A weight without a confirmed licence stays disabled.
  4. Offline boundary: set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` for the app and its child processes; no download at run time; one socket-denial test per engine.
  5. One disabled-by-default status row per engine in `default_plugin_registry` (health = package and weights present).
- Acceptance: `python scripts/check_supply_chain_intake.py` passes; a base install starts cleanly; each extra installs without a downgrade of a locked package; the socket-denial tests pass.
- Out of scope: any product code that imports the packages. FinanceToolkit is not installed and not copied.
