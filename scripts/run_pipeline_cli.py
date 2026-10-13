"""Fail-closed boundaries shared by the local data pipeline commands."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path


def require_cached_inputs(*paths: Path) -> None:
    """Require real cached inputs before a loader can initialise sample data."""
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Cached input unavailable: {path}. Import or refresh real data first.")


def run_cli(main: Callable[[], int], *, record_paper_bots: bool = False) -> int:
    """Reject invalid roots; with ``record_paper_bots`` record decisions after a successful full pipeline run."""
    try:
        explicit_root = os.getenv("ETF_COCKPIT_ROOT")
        recorder_root = None
        if explicit_root:
            recorder_root = Path(explicit_root).expanduser().resolve()
            if not (recorder_root / "configs" / "universe.yaml").is_file() or not (recorder_root / "data").is_dir():
                raise ValueError(
                    f"Invalid ETF_COCKPIT_ROOT: {recorder_root}. Expected an application root "
                    "containing configs/universe.yaml and data/."
                )
        result = main()
        if result == 0 and record_paper_bots:
            try:
                from etf_cockpit.portfolio.paper_bots import run_paper_bots

                paper_result = run_paper_bots(datetime.now(timezone.utc), root=recorder_root)
                for warning in paper_result.warnings:
                    print(f"Paper bots warning: {warning}")
                if paper_result.status != "available":
                    print(
                        "Paper bots "
                        + paper_result.status
                        + ": "
                        + (paper_result.reason or "one or more decision records are unavailable.")
                    )
            except Exception as exc:
                print(f"Paper bots unavailable: {type(exc).__name__}.")
        return result
    except (OSError, ValueError, KeyError) as exc:
        from etf_cockpit.core.session_log import redact_text

        print(f"Pipeline unavailable: {redact_text(str(exc))}")
        return 1
