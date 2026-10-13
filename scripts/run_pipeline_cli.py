"""Fail-closed boundaries shared by the local data pipeline commands."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path


def require_cached_inputs(*paths: Path) -> None:
    """Require real cached inputs before a loader can initialise sample data."""
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Cached input unavailable: {path}. Import or refresh real data first.")


def run_cli(main: Callable[[], int]) -> int:
    """Reject an invalid explicit root and report expected input failures."""
    try:
        explicit_root = os.getenv("ETF_COCKPIT_ROOT")
        if explicit_root:
            root = Path(explicit_root).expanduser().resolve()
            if not (root / "configs" / "universe.yaml").is_file() or not (root / "data").is_dir():
                raise ValueError(
                    f"Invalid ETF_COCKPIT_ROOT: {root}. Expected an application root "
                    "containing configs/universe.yaml and data/."
                )
        return main()
    except (OSError, ValueError, KeyError) as exc:
        from etf_cockpit.core.session_log import redact_text

        print(f"Pipeline unavailable: {redact_text(str(exc))}")
        return 1
