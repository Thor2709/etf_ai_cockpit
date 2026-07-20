from __future__ import annotations

import inspect

from etf_cockpit.app.pages.jobs import jobs_page
from etf_cockpit.app.pages.onboarding import onboarding_page


def test_onboarding_exposes_hardware_profile_and_cpu_only_limitations() -> None:
    source = inspect.getsource(onboarding_page)

    assert "Hardware and resource readiness" in source
    assert "resource_profile_report" in source
    assert "CPU-only baseline" in source
    assert "execution_allowed=false" in source


def test_jobs_exposes_pre_job_resource_estimate_and_limit_status() -> None:
    source = inspect.getsource(jobs_page)

    assert "Resource readiness" in source
    assert "estimate_workflow_resources" in source
    assert "limits are local" in source
    assert "jobs.resource-cache-cleanup" in source
    assert "reproducible file(s)" in source
    assert "execution_allowed=false" in source
