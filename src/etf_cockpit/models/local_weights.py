from __future__ import annotations

import importlib.util
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from etf_cockpit.core.config import AppConfig
from etf_cockpit.core.paths import MODEL_DIR, ROOT


WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".ckpt")
SAFETENSORS_HEADER_LIMIT_BYTES = 50_000_000


@dataclass(frozen=True)
class SafetensorsSummary:
    metadata: dict[str, Any] = field(default_factory=dict)
    tensor_count: int = 0
    sample_keys: list[str] = field(default_factory=list)
    sample_shapes: dict[str, list[int]] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class LocalModelStatus:
    model_name: str
    model_id: str
    path: Path
    present: bool
    total_bytes: int
    weight_files: list[Path]
    has_config_json: bool
    runtime_packages: dict[str, bool]
    live_ready: bool
    status: str
    message: str
    safetensors: SafetensorsSummary | None = None

    @property
    def size_gb(self) -> float:
        return self.total_bytes / 1_000_000_000


def model_weight_inventory(config: AppConfig) -> list[LocalModelStatus]:
    return [
        _timesfm_status(config),
        _toto_status(config, "4m", "Toto-2.0-4m"),
        _toto_status(config, "1b", "Toto-2.0-1B"),
    ]


def format_model_inventory_line(status: LocalModelStatus) -> str:
    package_text = ", ".join(
        f"{name}={'yes' if available else 'no'}" for name, available in status.runtime_packages.items()
    )
    config_text = "config=yes" if status.has_config_json else "config=no"
    weight_text = f"weights={len(status.weight_files)} file(s), {status.size_gb:.2f} GB" if status.weight_files else "weights=no"
    tensor_text = ""
    if status.safetensors and status.safetensors.tensor_count:
        tensor_text = f", tensors={status.safetensors.tensor_count}"
    return (
        f"{status.model_id}: {status.status}; {weight_text}; {config_text}; "
        f"runtime[{package_text}]; path={status.path}{tensor_text}. {status.message}"
    )


def _timesfm_status(config: AppConfig) -> LocalModelStatus:
    runtime_config = config.models.runtime("timesfm")
    path = _resolve_model_path(runtime_config.model_path, MODEL_DIR / "timesfm" / "timesfm-2.5-200m-transformers")
    weight_files = _weight_files(path)
    packages = {
        "torch": _package_available("torch"),
        "timesfm": _package_available("timesfm"),
        "transformers": _package_available("transformers"),
    }
    backend = runtime_config.backend.lower()
    if backend in {"timesfm", "official"}:
        runtime_ready = packages["torch"] and packages["timesfm"]
        metadata_ready = (path / "model.safetensors").exists() if path.is_dir() else path.suffix == ".safetensors"
    elif backend == "transformers":
        runtime_ready = packages["torch"] and packages["transformers"]
        metadata_ready = path.is_dir() and (path / "config.json").exists() and bool(weight_files)
    else:
        runtime_ready = packages["torch"] and (packages["timesfm"] or packages["transformers"])
        metadata_ready = bool(weight_files)
    live_ready = runtime_config.enabled and runtime_config.mode == "live" and bool(weight_files) and metadata_ready and runtime_ready
    return LocalModelStatus(
        model_name="timesfm",
        model_id="TimesFM 2.5",
        path=path,
        present=bool(weight_files),
        total_bytes=sum(file.stat().st_size for file in weight_files),
        weight_files=weight_files,
        has_config_json=path.is_dir() and (path / "config.json").exists(),
        runtime_packages=packages,
        live_ready=live_ready,
        status="live_ready" if live_ready else ("weights_present" if weight_files else "missing_weights"),
        message=_readiness_message(
            enabled=runtime_config.enabled,
            mode=runtime_config.mode,
            weight_files=weight_files,
            runtime_ready=runtime_ready,
            metadata_ready=metadata_ready,
            runtime_hint="Install optional torch + timesfm runtime for the configured local PyTorch backend.",
        ),
        safetensors=_first_safetensors_summary(weight_files),
    )


def _toto_status(config: AppConfig, size_key: str, folder_name: str) -> LocalModelStatus:
    runtime_config = config.models.runtime("toto")
    configured_path = runtime_config.model_path if (runtime_config.model_size or "").lower() == size_key else None
    path = _resolve_model_path(configured_path, MODEL_DIR / "toto" / folder_name)
    weight_files = _weight_files(path)
    has_config = path.is_dir() and (path / "config.json").exists()
    packages = {"torch": _package_available("torch"), "toto2": _package_available("toto2")}
    runtime_ready = packages["torch"] and packages["toto2"]
    metadata_ready = path.is_dir() and has_config and ((path / "model.safetensors").exists() or (path / "model.safetensors.index.json").exists())
    live_configured = runtime_config.enabled and runtime_config.mode == "live" and (runtime_config.model_size or "").lower() == size_key
    live_ready = live_configured and bool(weight_files) and metadata_ready and runtime_ready
    return LocalModelStatus(
        model_name="toto",
        model_id=f"Toto 2.0 {size_key.upper()}",
        path=path,
        present=bool(weight_files),
        total_bytes=sum(file.stat().st_size for file in weight_files),
        weight_files=weight_files,
        has_config_json=has_config,
        runtime_packages=packages,
        live_ready=live_ready,
        status="live_ready" if live_ready else ("weights_present" if weight_files else "missing_weights"),
        message=_readiness_message(
            enabled=live_configured,
            mode=runtime_config.mode,
            weight_files=weight_files,
            runtime_ready=runtime_ready,
            metadata_ready=metadata_ready,
            runtime_hint="Install optional torch + toto2 runtime. Toto also requires config.json beside model.safetensors.",
        ),
        safetensors=_first_safetensors_summary(weight_files),
    )


def _readiness_message(
    *,
    enabled: bool,
    mode: str,
    weight_files: list[Path],
    runtime_ready: bool,
    metadata_ready: bool,
    runtime_hint: str,
) -> str:
    if not weight_files:
        return "No local weight file was found."
    if not metadata_ready:
        return "Local weights exist, but checkpoint metadata/layout is incomplete."
    if not enabled or mode != "live":
        return "Local checkpoint is installed but not enabled for live inference."
    if not runtime_ready:
        return f"Local checkpoint is installed, but runtime packages are missing. {runtime_hint}"
    return "Local checkpoint and runtime packages are ready for live inference."


def _resolve_model_path(configured_path: str | None, default_path: Path) -> Path:
    if not configured_path:
        return default_path
    path = Path(configured_path)
    return path if path.is_absolute() else ROOT / path


def _weight_files(path: Path) -> list[Path]:
    if path.is_file() and _is_runtime_weight_file(path):
        return [path]
    if not path.exists() or not path.is_dir():
        return []
    return sorted(file for file in path.rglob("*") if file.is_file() and _is_runtime_weight_file(file))


def _is_runtime_weight_file(path: Path) -> bool:
    lower_name = path.name.lower()
    if not lower_name.endswith(WEIGHT_SUFFIXES):
        return False
    return ".original" not in lower_name and ".backup" not in lower_name


def _first_safetensors_summary(weight_files: list[Path]) -> SafetensorsSummary | None:
    for file in weight_files:
        if file.suffix.lower() == ".safetensors":
            return read_safetensors_header(file)
    return None


def read_safetensors_header(path: Path, *, sample_limit: int = 12) -> SafetensorsSummary:
    try:
        with path.open("rb") as handle:
            raw_size = handle.read(8)
            if len(raw_size) != 8:
                return SafetensorsSummary(error="File is too short to contain a safetensors header.")
            header_size = struct.unpack("<Q", raw_size)[0]
            if header_size > SAFETENSORS_HEADER_LIMIT_BYTES:
                return SafetensorsSummary(error=f"Safetensors header is unexpectedly large: {header_size} bytes.")
            header = json.loads(handle.read(header_size))
    except Exception as exc:
        return SafetensorsSummary(error=f"{type(exc).__name__}: {exc}")

    tensor_keys = [key for key in header if key != "__metadata__"]
    sample_keys = tensor_keys[:sample_limit]
    sample_shapes = {
        key: list(header[key].get("shape", []))
        for key in sample_keys
        if isinstance(header.get(key), dict)
    }
    return SafetensorsSummary(
        metadata=header.get("__metadata__", {}),
        tensor_count=len(tensor_keys),
        sample_keys=sample_keys,
        sample_shapes=sample_shapes,
    )


def _package_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None
