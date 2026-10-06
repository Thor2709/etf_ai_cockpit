from __future__ import annotations

from etf_cockpit.core.runtime import configure_runtime_environment

configure_runtime_environment()

from etf_cockpit.app.flet_app import run  # noqa: E402


if __name__ == "__main__":
    run()
