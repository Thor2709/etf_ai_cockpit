# Chronos-2 Models

Local checkpoint for the optional, shadow-only Chronos-2 forecast adapter. The app stays baseline-only when this folder is empty or the `chronos-forecasting` package is absent. Nothing is downloaded at run time: the adapter loads from this folder only (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `local_files_only`). Weights are not in git.

Expected folder (`configs/model_settings.yaml`, `models.chronos2.model_path`):

- `models/chronos/chronos-2/model.safetensors`
- `models/chronos/chronos-2/config.json`

## Weight inventory (one row per file)

| File | Repository | Revision | SHA-256 | Bytes | Licence | Conversion |
| --- | --- | --- | --- | --- | --- | --- |
| `model.safetensors` | `amazon/chronos-2` | `29ec3766d36d6f73f0696f85560a422f50e8498c` | `ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42` | 477930472 | Apache-2.0 | none (as published; no ONNX) |
| `config.json` | `amazon/chronos-2` | `29ec3766d36d6f73f0696f85560a422f50e8498c` | `ef1143bfdc9c0376d9a056eefca46cb4b1ec3d0ffacd541ff56feb40fb708031` | 1067 | Apache-2.0 | none |

## Training cut-off

Unknown. Neither the model card nor the paper (arXiv 2510.15821) states one. The card names the training data as a subset of the Chronos datasets, a subset of GIFT-Eval Pretrain and synthetic data. The cut-off is recorded as `unknown`, so every forecast origin is flagged `possibly_leaked` and the model cannot count toward a score until its first verified local run has produced matured out-of-sample evidence against the baseline.
