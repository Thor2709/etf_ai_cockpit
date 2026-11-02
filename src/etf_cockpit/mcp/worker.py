"""One local MCP queue worker, using the session's guarded scheduler runner.

Idle queues poll every 100 ms; writer contention and infrastructure errors back
off for 500 ms. Handler failures are recorded by DurableJobScheduler.run_once
in job/workflow history before the next job is served. Infrastructure failures
are logged and retried, never converted into a successful/empty drain.

Set ETF_COCKPIT_MCP_WORKER_ENABLED=false to disable automatic draining (default
on). Shutdown waits for the current handler to finish; handlers are never killed
while holding the writer guard. Synchronous drains share the worker's run lock.
"""

from __future__ import annotations

import atexit
from contextlib import asynccontextmanager
from functools import wraps
import logging
import os
import threading
import time
from typing import Any

from etf_cockpit.application.headless_session import HeadlessWriterBusyError


POLL_INTERVAL_SECONDS = 0.1
BACKOFF_SECONDS = 0.5
_LOG = logging.getLogger(__name__)
_WORKER_LOCK = threading.Lock()
_WORKER: WorkflowWorker | None = None


class WorkflowWorker:
    """Drain the session queue serially, without bypassing its writer guard."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self._stop = threading.Event()
        self._drain_lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, name="mcp-workflows", daemon=True)

    def start(self) -> WorkflowWorker:
        """Start at most one daemon worker in this server process."""
        global _WORKER
        with _WORKER_LOCK:
            if _WORKER is not None and _WORKER.thread.is_alive():
                if _WORKER is not self:
                    raise RuntimeError("An MCP workflow worker is already running in this process")
                return self
            if self._stop.is_set():
                raise RuntimeError("A stopped MCP workflow worker cannot be restarted")
            _WORKER = self
            self.thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        """Interrupt idle/backoff waits and join; fail visibly if a handler is busy."""
        self._stop.set()
        if self.thread.ident is not None:
            self.thread.join(timeout)
            if self.thread.is_alive():
                raise TimeoutError("MCP workflow handler has not finished during shutdown")

    def drain_once(self) -> Any:
        """Run one job synchronously; propagate guard contention and runner errors."""
        with self._drain_lock:
            if self._stop.is_set():
                return None
            return self.session.run_next_workflow()

    def drain_until_idle(self, timeout: float) -> int:
        """Drain synchronously, bounding waits/between-job retries, not handler time."""
        deadline = time.monotonic() + timeout
        drained = 0
        while not self._stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("MCP workflow queue did not become idle")
            try:
                job = self.drain_once()
            except HeadlessWriterBusyError:
                self._stop.wait(min(BACKOFF_SECONDS, remaining))
                continue
            if job is None:
                return drained
            drained += 1
        return drained

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.drain_once()
            except HeadlessWriterBusyError:
                self._stop.wait(BACKOFF_SECONDS)
            except Exception:
                _LOG.exception("MCP workflow drain failed; retrying after backoff")
                self._stop.wait(BACKOFF_SECONDS)
            else:
                if job is None:
                    self._stop.wait(POLL_INTERVAL_SECONDS)


def start_server_worker(server: Any, session: Any) -> WorkflowWorker | None:
    """Start the process worker and bind shutdown to stdio/HTTP server lifetime.

    Read-only session adapters without a workflow runner have no queue to drain;
    registration-only server adapters without a run entry own no worker lifetime.
    HTTP wraps the ASGI app lifetime, since stateless SDK request lifetimes are
    shorter than the server lifetime.
    """
    enabled = os.environ.get("ETF_COCKPIT_MCP_WORKER_ENABLED", "true").strip().lower()
    if enabled not in {"true", "false", "1", "0"}:
        raise ValueError("ETF_COCKPIT_MCP_WORKER_ENABLED must be true/false or 1/0")
    if enabled in {"false", "0"} or not callable(getattr(session, "run_next_workflow", None)):
        return None
    original_run = getattr(server, "run", None)
    if not callable(original_run):
        return None
    worker = WorkflowWorker(session)
    server.workflow_worker = worker

    @wraps(original_run)
    def run(*args: Any, **kwargs: Any) -> Any:
        try:
            return original_run(*args, **kwargs)
        finally:
            worker.stop()

    server.run = run
    original_app = getattr(server, "streamable_http_app", None)
    if callable(original_app):
        @wraps(original_app)
        def http_app(*args: Any, **kwargs: Any) -> Any:
            app = original_app(*args, **kwargs)
            original_lifespan = app.router.lifespan_context

            @asynccontextmanager
            async def lifespan(app: Any):
                try:
                    async with original_lifespan(app) as state:
                        yield state
                finally:
                    worker.stop()

            app.router.lifespan_context = lifespan
            return app

        server.streamable_http_app = http_app
    worker.start()
    atexit.register(worker.stop)
    return worker
