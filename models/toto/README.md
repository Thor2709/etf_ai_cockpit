# Toto Models

Place Toto 2.0 model files here after downloading them from the official source. The app remains usable in baseline-only mode when this folder is empty.

The supplied Toto source archive has been extracted to `models/source_archives/toto-toto-models-v1.0.0` for reference. It is source code, benchmark material and examples, not local model weights.

The optional live adapter follows the Hugging Face model cards from the Datadog Toto 2.0 collection:

- `https://huggingface.co/collections/Datadog/toto-20`
- `https://huggingface.co/Datadog/Toto-2.0-4m`
- `https://huggingface.co/Datadog/Toto-2.0-22m`
- `https://huggingface.co/Datadog/Toto-2.0-313m`
- `https://huggingface.co/Datadog/Toto-2.0-1B`
- `https://huggingface.co/Datadog/Toto-2.0-2.5B`

Active local checkpoint folder:

- `models/toto/Toto-2.0-1B`

Current local checkpoint layout:

- `models/toto/Toto-2.0-4m/model.safetensors`
- `models/toto/Toto-2.0-4m/config.json`
- `models/toto/Toto-2.0-1B/model.safetensors`
- `models/toto/Toto-2.0-1B/config.json`

The adapter expects the `toto2` runtime from the `toto-models` package and calls `Toto2Model.from_pretrained(...)`. The current `.venv` has this optional runtime installed. Source archives or README-only folders are not treated as available models.

`configs/model_settings.yaml` now defaults to the 1B checkpoint. The 4M checkpoint remains installed as a small fallback/smoke-test checkpoint.
