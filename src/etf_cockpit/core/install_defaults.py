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


def _bundled_configs() -> Path:
    # Source and portable layouts keep configs beside src, or above app/src.
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "configs"
        if all((candidate / name).is_file() for name in UPGRADE_CONFIGS):
            return candidate
    raise FileNotFoundError("The application bundle lacks the required upgrade configs")


def ensure_install_defaults(root: Path) -> tuple[Path, ...]:
    """Publish only absent defaults as a recoverable atomic group; no data edits."""
    missing = tuple(root / "configs" / name for name in UPGRADE_CONFIGS
                    if not (root / "configs" / name).exists())
    if not missing:
        return ()
    bundled = _bundled_configs()

    def validate(path: Path) -> None:
        if not isinstance(yaml.safe_load(path.read_text(encoding="utf-8")), dict):
            raise ValueError(f"Upgrade config must be a YAML mapping: {path.name}")

    def still_missing() -> None:
        if any(path.exists() for path in missing):
            raise FileExistsError("An upgrade config appeared during startup; retry without overwriting it")

    requests = tuple(AtomicWriteRequest(path, (bundled / path.name).read_bytes(), validate)
                     for path in missing)
    atomic_write_group(requests, precondition=still_missing)
    return missing
