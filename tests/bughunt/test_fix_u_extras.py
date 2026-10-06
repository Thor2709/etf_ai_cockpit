from unittest.mock import Mock

from etf_cockpit.application.api import LocalApplicationApi


def test_run_next_job_forwards_requested_workflow() -> None:
    scheduler = Mock()
    scheduler.run_once.return_value = None
    api = LocalApplicationApi(lambda: object(), scheduler=scheduler)

    api.run_next_job(lambda _context: {}, workflow_id="workflow-own")

    assert scheduler.run_once.call_args.kwargs["workflow_id"] == "workflow-own"
