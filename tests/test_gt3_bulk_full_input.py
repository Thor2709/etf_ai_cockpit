"""GT3: bulk analysis must never run on the scheduler's bounded (100-item) copy of an input."""

from etf_cockpit.application.bulk_run import BulkAnalysisService

LONG_INPUT = {"values": tuple(range(1, 131)), "weights": {f"k{index:03d}": index for index in range(120)}}
EXPECTED = {"count": 130, "total": sum(range(1, 131)), "weights": 120}


def _analyze(_instrument_id, analysis_input):
    return {
        "count": len(analysis_input["values"]),
        "total": sum(analysis_input["values"]),
        "weights": len(analysis_input["weights"]),
    }


def test_input_larger_than_the_persisted_bound_is_analysed_in_full(tmp_path):
    service = BulkAnalysisService(tmp_path)
    run = service.start({"ETF.LONG": LONG_INPUT}, _analyze, analyzer_id="tests.gt3.full.v1")

    assert run.status == "succeeded", run.failures
    assert run.results["ETF.LONG"] == EXPECTED
    # The persisted/displayed payload stays bounded and marked (JB1).
    stored = service.scheduler.list_jobs(run.run_id)[0].inputs["analysis_input"]
    assert len(stored["values"]) == 101 and "__truncated__" in stored["values"][-1]


def test_bounded_only_copy_fails_closed_without_running_the_analyzer(tmp_path):
    first = BulkAnalysisService(tmp_path)
    run = first.start(
        {"ETF.LONG": LONG_INPUT, "ETF.SHORT": {"values": (1, 2, 3), "weights": {}}},
        _analyze,
        analyzer_id="tests.gt3.bounded.v1",
        max_jobs=0,
    )
    calls = []

    def recording_analyze(instrument_id, analysis_input):
        calls.append(instrument_id)
        return _analyze(instrument_id, analysis_input)

    # A fresh service (restart) only has the bounded stored copy of the long input.
    resumed = BulkAnalysisService(tmp_path).resume(run.run_id, recording_analyze, analyzer_id="tests.gt3.bounded.v1")

    assert "truncated data" in resumed.failures["ETF.LONG"]
    assert "ETF.LONG" not in calls
    assert "ETF.LONG" not in resumed.results
    assert resumed.results["ETF.SHORT"] == {"count": 3, "total": 6, "weights": 0}
