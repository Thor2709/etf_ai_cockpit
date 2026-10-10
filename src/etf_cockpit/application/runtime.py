"""Runtime services the desktop session composes: durable job scheduler and startup migrations (application; ADR-0002)."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from etf_cockpit.core.atomic_io import atomic_write_json as atomic_write_json
from etf_cockpit.core.process import pid_is_alive as pid_is_alive

if TYPE_CHECKING:
    from etf_cockpit.core.job_scheduler import DurableJobScheduler as DurableJobScheduler
    from etf_cockpit.core.migrations import run_startup_migrations as run_startup_migrations

# The scheduler and migrations pull in pandas/numpy; resolve them on first use so the
# loading shell (which only needs the light helpers above) starts without heavy imports.
_LAZY = {
    "DurableJobScheduler": "etf_cockpit.core.job_scheduler",
    "run_startup_migrations": "etf_cockpit.core.migrations",
}


def __getattr__(name: str) -> object:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value
