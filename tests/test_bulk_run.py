from etf_cockpit.core import job_scheduler
from etf_cockpit.application.bulk_run import BulkAnalysisService
from etf_cockpit.core.job_scheduler import JobStatus


def test_bulk_run_resume_preserves_hashes(tmp_path):
    service = BulkAnalysisService(tmp_path)
    inputs = {"ETF.A": {"period": "daily"}, "ETF.B": {"period": "weekly"}}
    calls = {}

    def analyze(instrument_id, analysis_input):
        calls[instrument_id] = calls.get(instrument_id, 0) + 1
        return {"instrument_id": instrument_id, "period": analysis_input["period"]}

    partial = service.start(inputs, analyze, max_jobs=1)
    assert partial.coverage_completed == 1
    assert partial.coverage_total == 2
    completed_id = next(iter(partial.results))
    completed_result = partial.results[completed_id]

    resumed = service.resume(partial.run_id, analyze)

    assert resumed.hashes == partial.hashes
    assert resumed.results[completed_id] == completed_result
    assert calls[completed_id] == 1
    assert resumed.coverage_completed == resumed.coverage_total == 2


def test_bulk_vs_individual_parity(tmp_path):
    service = BulkAnalysisService(tmp_path)

    def analyze(instrument_id, analysis_input):
        return {"instrument_id": instrument_id, "score": analysis_input["score"]}

    analysis_input = {"score": 0.75}
    bulk = service.start({"ETF.A": analysis_input}, analyze)
    single = service.analyze_individual("ETF.A", analysis_input, analyze)

    assert bulk.results["ETF.A"] == single


def test_bulk_failure_isolation(tmp_path):
    service = BulkAnalysisService(tmp_path)

    def analyze(instrument_id, analysis_input):
        if instrument_id == "ETF.BAD":
            raise RuntimeError("provider unavailable")
        return {"instrument_id": instrument_id, "value": analysis_input["value"]}

    run = service.start(
        {
            "ETF.BAD": {"value": 1},
            "ETF.GOOD.A": {"value": 2},
            "ETF.GOOD.B": {"value": 3},
        },
        analyze,
    )

    assert run.states["ETF.BAD"] == JobStatus.FAILED.value
    assert "provider unavailable" in run.failures["ETF.BAD"]
    assert run.states["ETF.GOOD.A"] == JobStatus.SUCCEEDED.value
    assert run.states["ETF.GOOD.B"] == JobStatus.SUCCEEDED.value
    assert set(run.results) == {"ETF.GOOD.A", "ETF.GOOD.B"}
    assert run.coverage_completed == run.coverage_total == 3


def test_bulk_run_creates_new_history(tmp_path):
    service = BulkAnalysisService(tmp_path)
    inputs = {"ETF.A": {"period": "daily"}}

    def analyze(instrument_id, analysis_input):
        return {"instrument_id": instrument_id, "period": analysis_input["period"]}

    first = service.start(inputs, analyze)
    second = service.start(inputs, analyze)

    assert second.run_id != first.run_id
    assert service.get_run(first.run_id).results == first.results
    assert service.get_run(second.run_id).results == second.results


def test_bulk_execution_claims_only_its_workflow(tmp_path, monkeypatch):
    service = BulkAnalysisService(tmp_path)
    current_tick = 0

    def next_timestamp():
        nonlocal current_tick
        current_tick += 1
        return f"2026-01-01T00:00:00.{current_tick:03d}+00:00"

    monkeypatch.setattr(job_scheduler, "_utc_now", next_timestamp)

    def analyze(instrument_id, analysis_input):
        return {"instrument_id": instrument_id, "value": analysis_input["value"]}

    older = service.start({"ETF.OLDER": {"value": 1}}, analyze, max_jobs=0)
    current = service.start({"ETF.CURRENT": {"value": 2}}, analyze)

    assert current.results == {"ETF.CURRENT": {"instrument_id": "ETF.CURRENT", "value": 2}}
    assert service.get_run(older.run_id).states == {"ETF.OLDER": JobStatus.QUEUED.value}
