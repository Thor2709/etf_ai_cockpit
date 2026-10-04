"""Runtime services the desktop session composes: durable job scheduler and startup migrations (application; ADR-0002)."""

from __future__ import annotations

from etf_cockpit.core.job_scheduler import DurableJobScheduler as DurableJobScheduler
from etf_cockpit.core.migrations import run_startup_migrations as run_startup_migrations
