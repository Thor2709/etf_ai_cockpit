"""Focused MCP worker integration, failure history, exclusion and shutdown."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from etf_cockpit.application import headless_session
from etf_cockpit.application.headless_session import HeadlessSession, HeadlessWriterBusyError
from etf_cockpit.mcp import server
from etf_cockpit.mcp.audit import AuditRecorder
from etf_cockpit.mcp.registry import CallContext, RateLimiter, invoke_tool
from etf_cockpit.mcp.worker import WorkflowWorker, start_server_worker


@pytest.fixture
def context(tmp_path, monkeypatch):
    # Keep the real guard, scheduler, API, confirmation and registry. Only the
    # refresh service is offline; no network or financial calculation is needed.
    monkeypatch.setattr(headless_session, "ROOT", tmp_path)
    monkeypatch.delenv("ETF_COCKPIT_MCP_WORKER_ENABLED", raising=False)
    session = HeadlessSession(SimpleNamespace(universe_revision="worker-fixture"), root=tmp_path)
    monkeypatch.setattr(session, "refresh", lambda: "offline refresh completed")
    return CallContext(
        session=session, profile="full", enabled_tiers=frozenset({"read", "edit"}),
        audit=AuditRecorder(sink=lambda _record: None),
        rate_limiter=RateLimiter(path=tmp_path / "quota.sqlite3"),
    )


def submit(context, *, years=1):
    arguments = {"source": "prices", "years": years, "rescore": False}
    preview = invoke_tool("data_refresh", arguments, context=context)
    return invoke_tool(
        "data_refresh", {**arguments, "confirm_token": preview["confirm_token"]}, context=context,
    )["job_id"]


def status(context, job_id):
    return invoke_tool("job_status", {"job_id": job_id}, context=context)["job"]


def terminal(context, job_id, *, timeout=10):
    deadline = time.monotonic() + timeout
    while True:
        job = status(context, job_id)
        if job.status.value in {"succeeded", "failed", "cancelled", "blocked"}:
            return job
        assert time.monotonic() < deadline, job
        time.sleep(0.02)


def test_registry_job_reaches_terminal_through_server_worker(context, monkeypatch):
    class SDKServer:
        def __init__(self, *_args, **_kwargs):
            pass

        def add_tool(self, *_args, **_kwargs):
            pass

        def resource(self, *_args, **_kwargs):
            return lambda handler: handler

        prompt = resource

        def run(self, **_kwargs):
            return "stopped"

    monkeypatch.setattr(server, "_load_sdk", lambda: (SDKServer, RuntimeError, lambda **kw: kw))
    job_id = submit(context)
    assert status(context, job_id).status.value == "queued"
    active = server.create_server(profile="full", tiers="read,edit", session=context.session)
    try:
        assert active.workflow_worker.thread.daemon
        assert terminal(context, job_id).status.value == "succeeded"
        with pytest.raises(RuntimeError, match="already running"):
            WorkflowWorker(context.session).start()
    finally:
        assert active.run(transport="stdio") == "stopped"
    assert not active.workflow_worker.thread.is_alive()
    synchronous = WorkflowWorker(context.session)
    second = submit(context, years=2)
    assert synchronous.drain_once().workflow_id == second
    assert synchronous.drain_until_idle(timeout=2) == 0


def test_worker_retries_after_another_process_releases_writer_guard(context):
    job_id = submit(context)
    code = (
        "from pathlib import Path; import sys; "
        "from etf_cockpit.application.headless_session import cross_process_writer_guard; "
        "guard = cross_process_writer_guard(Path(sys.argv[1])); guard.__enter__(); "
        "print('held', flush=True); sys.stdin.readline(); guard.__exit__(None, None, None)"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", code, str(context.session.root)],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    worker = WorkflowWorker(context.session)
    try:
        assert process.stdout.readline().strip() == "held"
        with pytest.raises(HeadlessWriterBusyError):
            worker.drain_once()
        with pytest.raises(TimeoutError, match="did not become idle"):
            worker.drain_until_idle(timeout=0.05)
        worker.start()
        time.sleep(0.65)  # Observe an initial attempt and a 500-ms contention retry.
        assert status(context, job_id).status.value == "queued"
        assert not any(event.event_type == "job_started"
                       for event in context.session._scheduler().list_events(job_id))
        process.communicate("\n", timeout=20)
        assert process.returncode == 0
        assert terminal(context, job_id).status.value == "succeeded"
    finally:
        if process.poll() is None:
            process.communicate("\n", timeout=20)
        worker.stop()


def test_handler_failure_is_durable_and_worker_serves_next_job(context, monkeypatch):
    first = submit(context)
    second = submit(context, years=2)
    attempts = []

    def refresh():
        attempts.append(True)
        if len(attempts) == 1:
            raise ValueError("offline handler failure")
        return "next refresh succeeded"

    monkeypatch.setattr(context.session, "refresh", refresh)
    worker = WorkflowWorker(context.session).start()
    try:
        failed = terminal(context, first)
        assert failed.status.value == "failed"
        assert "offline handler failure" in failed.error_message
        events = context.session._scheduler().list_events(first)
        assert any(event.event_type == "job_failed" and event.status.value == "failed" for event in events)
        assert context.session._scheduler().verify_event_chain(first)
        assert terminal(context, second).status.value == "succeeded"
        assert worker.thread.is_alive()
        assert len(attempts) == 2
    finally:
        worker.stop()


def test_shutdown_stops_thread_within_bound(context, monkeypatch):
    monkeypatch.setenv("ETF_COCKPIT_MCP_WORKER_ENABLED", "false")
    assert start_server_worker(SimpleNamespace(), context.session) is None
    monkeypatch.delenv("ETF_COCKPIT_MCP_WORKER_ENABLED")

    @asynccontextmanager
    async def original_lifespan(_app):
        yield {"sdk": "active"}

    app = SimpleNamespace(router=SimpleNamespace(lifespan_context=original_lifespan))
    sdk_server = SimpleNamespace(run=lambda: None, streamable_http_app=lambda: app)
    worker = start_server_worker(sdk_server, context.session)
    try:
        assert worker.thread.is_alive()

        async def serve():
            active_app = sdk_server.streamable_http_app()
            async with active_app.router.lifespan_context(active_app) as state:
                assert state == {"sdk": "active"}

        start = time.monotonic()
        asyncio.run(serve())
        assert time.monotonic() - start < 2
        assert not worker.thread.is_alive()
        worker.stop(timeout=1)  # Repeated shutdown is harmless.
    finally:
        worker.stop()
