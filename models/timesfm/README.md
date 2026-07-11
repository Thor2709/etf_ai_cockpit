# TimesFM Models

Place TimesFM 2.5 model files here after downloading them from the official source. The app remains usable in baseline-only mode when this folder is empty.

The supplied TimesFM source archive has been extracted to `models/source_archives/timesfm-2.0.1` for reference. It is source code and examples, not local model weights.

The optional live adapter supports the Hugging Face Transformers implementation documented at:

- `https://huggingface.co/docs/transformers/model_doc/timesfm2_5`
- `https://huggingface.co/google/timesfm-2.5-200m-transformers`

Expected local checkpoint folder for the default configuration:

- `models/timesfm/timesfm-2.5-200m-transformers`

Current local checkpoint layout:

- `models/timesfm/timesfm-2.5-200m-transformers/model.safetensors`
- `models/timesfm/timesfm-2.5-200m-transformers/config.json`

The adapter also has a secondary backend for the official TimesFM PyTorch package and checkpoint:

- `https://huggingface.co/google/timesfm-2.5-200m-pytorch`

The default config points at the local Transformers checkpoint folder because the uploaded safetensors use Transformers-style key names. The original uploaded file has been preserved as `model.original_ff_keys.safetensors`; the runtime `model.safetensors` was converted from legacy `mlp.ff0`/`mlp.ff1` key names to the `mlp.fc1`/`mlp.fc2` names expected by the installed Transformers backend.

With the current `.venv`, TimesFM 2.5 reports `live_ready` and a live smoke forecast has passed. If you recreate the environment, install `requirements-models.txt` before expecting live inference. Source archives or README-only folders are not treated as available models.
