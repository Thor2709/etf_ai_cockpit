from __future__ import annotations

from importlib import metadata
import os
from pathlib import Path
import re

from etf_cockpit.core.paths import LOG_DIR, ROOT, ensure_project_dirs


FLET_UNSUPPORTED_FROM_MAJOR = 1
"""The UI is written for the Flet 0.x API; Flet 1.x is a breaking rewrite (#949) and is not supported."""


class UnsupportedFletVersionError(RuntimeError):
    """The installed Flet is outside the supported ``>=0.28,<1.0`` range."""


def check_flet_version(version_text: str | None) -> None:
    """Reject Flet 1.x or newer (and any unreadable version) with a clear, actionable message."""

    match = re.match(r"\s*(\d+)", version_text or "")
    if match is None or int(match.group(1)) >= FLET_UNSUPPORTED_FROM_MAJOR:
        raise UnsupportedFletVersionError(
            f"Unsupported Flet version {version_text!r}: ETF AI Cockpit requires Flet below 1.0 "
            "(the locked release uses 0.85.3). Reinstall the pinned dependencies with "
            "'python -m pip install -r requirements.txt'; do not upgrade Flet to 1.x."
        )


def ensure_supported_flet_version() -> None:
    """Check the installed ``flet`` distribution; a frozen build without package metadata is skipped."""

    try:
        installed = metadata.version("flet")
    except metadata.PackageNotFoundError:
        return
    check_flet_version(installed)


def configure_runtime_environment() -> Path:
    """Use project-local runtime folders so Flet web assets stay writable."""
    ensure_supported_flet_version()
    ensure_project_dirs()
    from etf_cockpit.core.install_defaults import ensure_install_defaults

    ensure_install_defaults(ROOT)
    runtime_tmp = LOG_DIR / "runtime_tmp"
    runtime_tmp.mkdir(parents=True, exist_ok=True)

    # Keep Flet/browser cache state local to the project/package instead of the
    # user profile. Flet's static-web temp creation is patched separately in
    # the app layer because Python's tempfile.mkdtemp can create inaccessible
    # directories on some locked-down Windows sessions.
    runtime_path = str(runtime_tmp)
    os.environ.setdefault("FLET_CACHE_DIR", runtime_path)
    os.environ.setdefault("FLET_WEB_TEMP_DIR", runtime_path)
    os.environ.setdefault("PYTHONPYCACHEPREFIX", str(runtime_tmp / "pycache"))
    return runtime_tmp
