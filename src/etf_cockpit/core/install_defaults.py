"""Add shipped upgrade configs without replacing an owner's configuration."""

from pathlib import Path

import yaml

from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group


UPGRADE_CONFIGS = (
    "analysis_depth_profiles.yaml",
    "euronext_listing_v1.yaml",
    "fund_analysis_v1.yaml",
    "stock_fundamentals_v1.yaml",
    "universe_membership_v1.yaml",
    "esef_extension_concepts.yaml",
    "sparebank_scorecard_v1.yaml",
)


def _bundled_default(name: str, owner_configs: Path) -> Path:
    # Source and portable layouts keep pristine configs beside src, or in app/configs of a portable
    # package. The owner's own configs folder is never its own source of defaults.
    owner = owner_configs.resolve()
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "configs"
        if candidate.resolve() != owner and (candidate / name).is_file():
            return candidate / name
    raise FileNotFoundError(f"The application bundle lacks the required upgrade config: {name}")


def ensure_install_defaults(root: Path) -> tuple[Path, ...]:
    """Publish only absent defaults as a recoverable atomic group; no data edits."""
    missing = tuple(root / "configs" / name for name in UPGRADE_CONFIGS
                    if not (root / "configs" / name).exists())
    if not missing:
        return ()
    sources = {path: _bundled_default(path.name, root / "configs") for path in missing}

    def validate(path: Path) -> None:
        if not isinstance(yaml.safe_load(path.read_text(encoding="utf-8")), dict):
            raise ValueError(f"Upgrade config must be a YAML mapping: {path.name}")

    def still_missing() -> None:
        if any(path.exists() for path in missing):
            raise FileExistsError("An upgrade config appeared during startup; retry without overwriting it")

    requests = tuple(AtomicWriteRequest(path, sources[path].read_bytes(), validate)
                     for path in missing)
    atomic_write_group(requests, precondition=still_missing)
    return missing
