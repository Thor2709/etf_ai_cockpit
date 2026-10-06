from __future__ import annotations

import os
from pathlib import Path

from etf_cockpit.core.paths import LOG_DIR, ensure_project_dirs


def configure_runtime_environment() -> Path:
    """Use project-local runtime folders so Flet web assets stay writable."""
    ensure_project_dirs()
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
