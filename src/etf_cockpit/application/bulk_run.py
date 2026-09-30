"""Resumable application orchestration for independent instrument analyses."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import uuid

from etf_cockpit.application.contracts import BulkAnalysisRun
from etf_cockpit.core.job_scheduler import (
    TERMINAL_JOB_STATUSES,
    DurableJobScheduler,
    JobContext,
    JobRecord,
    JobSpec,
    JobStatus,
    _safe_outputs,
)


AnalysisFunction = Callable[[str, object], object]


class BulkAnalysisService:
    """Persist and run independent instrument analyses through the job scheduler."""

    workflow_type = "bulk_analysis"

    def __init__(self, root: Path) -> None:
        self.scheduler = DurableJobScheduler(Path(root))

    def start(
        self,
        inputs: Mapping[str, object],
        analyze: AnalysisFunction,
        *,
        analyzer_id: str,
        max_jobs: int | None = None,
    ) -> BulkAnalysisRun:
        """Create a run with a stable analyzer implementation/version identifier."""
        analyzer_id = self._validate_execution(analyze, analyzer_id, max_jobs)
        if not inputs:
            raise ValueError("bulk analysis requires at least one instrument")
        if any(not isinstance(instrument_id, str) or not instrument_id.strip() for instrument_id in inputs):
            raise ValueError("instrument identifiers must be non-blank strings")

        run_id = f"bulk_{uuid.uuid4().hex}"
        jobs = tuple(
            JobSpec(
                key=f"instrument-{index:06d}",
                label=f"Analyze instrument {index + 1}",
                input_payload={"instrument_id": instrument_id, "analysis_input": analysis_input},
            )
            for index, (instrument_id, analysis_input) in enumerate(sorted(inputs.items()))
        )
        self.scheduler.submit(
            self.workflow_type,
            "Bulk instrument analysis",
            jobs,
            input_payload={"instrument_count": len(jobs), "analyzer_id": analyzer_id},
            dedupe_key=run_id,
            workflow_id=run_id,
        )
        return self._execute(run_id, analyze, max_jobs)

    def resume(
        self,
        run_id: str,
        analyze: AnalysisFunction,
        *,
        analyzer_id: str,
        max_jobs: int | None = None,
    ) -> BulkAnalysisRun:
        """Continue queued work only with the stored analyzer implementation/version."""
        analyzer_id = self._validate_execution(analyze, analyzer_id, max_jobs)
        workflow = self._require_run(run_id)
        if self._stored_analyzer_id(workflow) != analyzer_id:
            raise ValueError("analyzer identifier does not match the stored bulk run")
        return self._execute(run_id, analyze, max_jobs)

    def get_run(self, run_id: str) -> BulkAnalysisRun:
        """Return the durable manifest, outcomes and exact completed/total coverage."""
        workflow = self._require_run(run_id)
        jobs = self.scheduler.list_jobs(run_id)
        hashes: dict[str, str] = {}
        states: dict[str, str] = {}
        results: dict[str, object] = {}
        failures: dict[str, str] = {}
        completed = 0

        for job in jobs:
            instrument_id = self._instrument_id(job)
            if instrument_id in hashes:
                raise ValueError(f"run manifest contains duplicate instrument {instrument_id!r}")
            hashes[instrument_id] = job.input_hash
            states[instrument_id] = job.status.value
            if job.status in TERMINAL_JOB_STATUSES:
                completed += 1
            if job.status is JobStatus.SUCCEEDED:
                results[instrument_id] = job.outputs
            elif job.status in TERMINAL_JOB_STATUSES:
                failures[instrument_id] = job.error_message or job.status.value

        if any(job.status is JobStatus.RUNNING for job in jobs):
            status = JobStatus.RUNNING
        elif any(job.status is JobStatus.QUEUED for job in jobs):
            status = JobStatus.QUEUED
        else:
            status = workflow.status

        return BulkAnalysisRun(
            run_id=run_id,
            analyzer_id=self._stored_analyzer_id(workflow),
            status=status.value,
            hashes=hashes,
            states=states,
            results=results,
            failures=failures,
            coverage_completed=completed,
            coverage_total=len(jobs),
        )

    @staticmethod
    def analyze_individual(
        instrument_id: str,
        analysis_input: object,
        analyze: AnalysisFunction,
    ) -> object:
        """Run one instrument through the same analyzer and output contract."""
        return _safe_outputs(analyze(instrument_id, analysis_input))

    def _execute(
        self,
        run_id: str,
        analyze: AnalysisFunction,
        max_jobs: int | None,
    ) -> BulkAnalysisRun:
        executed = 0
        while max_jobs is None or executed < max_jobs:
            job = self.scheduler.run_once(
                lambda context: self._analyze_job(context, analyze),
                workflow_id=run_id,
            )
            if job is None:
                break
            executed += 1
        return self.get_run(run_id)

    def _analyze_job(self, context: JobContext, analyze: AnalysisFunction) -> object:
        job = self.scheduler.get_job(context.job_id)
        if job is None or not isinstance(job.inputs, Mapping):
            raise ValueError("bulk analysis job input is unavailable")
        instrument_id = self._instrument_id(job)
        if "analysis_input" not in job.inputs:
            raise ValueError(f"analysis input is unavailable for {instrument_id}")
        return self.analyze_individual(instrument_id, job.inputs["analysis_input"], analyze)

    def _require_run(self, run_id: str):
        workflow = self.scheduler.get_workflow(run_id)
        if workflow is None or workflow.workflow_type != self.workflow_type:
            raise KeyError(f"bulk analysis run {run_id!r} was not found")
        return workflow

    @staticmethod
    def _stored_analyzer_id(workflow) -> str:
        if not isinstance(workflow.inputs, Mapping):
            raise ValueError("bulk analysis run manifest is unavailable")
        analyzer_id = workflow.inputs.get("analyzer_id")
        if not isinstance(analyzer_id, str) or not analyzer_id.strip():
            raise ValueError("bulk analysis run manifest has no analyzer identifier")
        return analyzer_id

    @staticmethod
    def _instrument_id(job: JobRecord) -> str:
        if not isinstance(job.inputs, Mapping):
            raise ValueError(f"bulk analysis input is unavailable for job {job.job_id}")
        instrument_id = job.inputs.get("instrument_id")
        if not isinstance(instrument_id, str) or not instrument_id.strip():
            raise ValueError(f"bulk analysis instrument identifier is unavailable for job {job.job_id}")
        return instrument_id

    @staticmethod
    def _validate_execution(
        analyze: AnalysisFunction,
        analyzer_id: str,
        max_jobs: int | None,
    ) -> str:
        if not callable(analyze):
            raise TypeError("analyze must be callable")
        if (
            not isinstance(analyzer_id, str)
            or not analyzer_id.strip()
            or len(analyzer_id) > 160
            or any(char in analyzer_id for char in "\r\n")
        ):
            raise ValueError("analyzer_id must be a bounded single-line identifier")
        if max_jobs is not None and (isinstance(max_jobs, bool) or max_jobs < 0):
            raise ValueError("max_jobs must be a non-negative integer")
        return analyzer_id.strip()


__all__ = ["AnalysisFunction", "BulkAnalysisService"]
