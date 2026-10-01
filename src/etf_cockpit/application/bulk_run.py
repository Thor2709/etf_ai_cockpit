"""Resumable application orchestration for independent instrument analyses."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import uuid

from etf_cockpit.application.analysis_depth import (
    AnalysisDepthError,
    AnalysisDepthProfile,
    MandatoryEvidenceError,
    MAX_PROFILE_DEPTH_WORKERS,
    AnalysisUpgradeLink,
    StageRunner,
    analysis_run_identity,
    append_timing_records,
    create_resource_plan,
    execute_profiled_stages,
    load_analysis_depth_profiles,
    profile_from_dict,
    resource_plan_from_dict,
    stage_cache_key,
    stage_output_hash,
)
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
from etf_cockpit.core.resource_profiles import ResourcePolicy


AnalysisFunction = Callable[[str, object], object]


class BulkAnalysisService:
    """Persist and run independent instrument analyses through the job scheduler."""

    workflow_type = "bulk_analysis"

    def __init__(
        self,
        root: Path,
        *,
        max_concurrency: int | None = None,
        resource_profile: str = "auto",
    ) -> None:
        resource_policy = ResourcePolicy(Path(root), requested_profile=resource_profile)
        hardware_limit = min(
            MAX_PROFILE_DEPTH_WORKERS,
            resource_policy.profile.job_cpu_limit,
            resource_policy.snapshot.cpu_cores,
        )
        scheduler_concurrency = hardware_limit if max_concurrency is None else max_concurrency
        self.scheduler = DurableJobScheduler(
            Path(root),
            max_concurrency=scheduler_concurrency,
            resource_policy=resource_policy,
        )
        self._stage_cache: dict[str, dict[str, object]] = {}
        self._stage_cache_lock = threading.Lock()

    def start(
        self,
        inputs: Mapping[str, object],
        analyze: AnalysisFunction | None = None,
        *,
        analyzer_id: str,
        max_jobs: int | None = None,
        depth_profile: str | None = None,
        stage_runner: StageRunner | None = None,
        hardware_profile: str = "auto",
        low_resource: bool = False,
        cache_state: str = "cold",
        horizons: Sequence[str] | None = None,
        seeds: Sequence[int] | None = None,
        _run_id: str | None = None,
        _upgrade_link: AnalysisUpgradeLink | None = None,
    ) -> BulkAnalysisRun:
        """Create a run, optionally freezing and executing an analysis-depth manifest."""
        if depth_profile is None:
            analyzer_id = self._validate_execution(analyze, analyzer_id, max_jobs)
            if stage_runner is not None or _upgrade_link is not None:
                raise ValueError("depth options require a depth_profile")
        else:
            analyzer_id = self._validate_execution(stage_runner, analyzer_id, max_jobs)
            if not callable(stage_runner):
                raise TypeError("stage_runner must be callable for a profile-depth run")
            if analyze is not None and not callable(analyze):
                raise TypeError("analyze must be callable when supplied")
            if cache_state not in {"cold", "warm"}:
                raise ValueError("cache_state must be cold or warm")
        if not inputs:
            raise ValueError("bulk analysis requires at least one instrument")
        if any(not isinstance(instrument_id, str) or not instrument_id.strip() for instrument_id in inputs):
            raise ValueError("instrument identifiers must be non-blank strings")

        run_id = _run_id or f"bulk_{uuid.uuid4().hex}"
        if depth_profile is None:
            analysis_depth_payload: dict[str, object] | None = None
            workflow_inputs: dict[str, object] = {
                "instrument_count": len(inputs),
                "analyzer_id": analyzer_id,
            }
            resource_plan = None
        else:
            profiles = load_analysis_depth_profiles()
            try:
                profile = profiles[depth_profile]
            except KeyError as exc:
                raise AnalysisDepthError(f"unknown analysis-depth profile {depth_profile!r}") from exc
            resolved_horizons = self._resolve_horizons(profile, horizons)
            resolved_seeds = self._resolve_seeds(profile, seeds)
            resource_plan = create_resource_plan(
                profile,
                hardware_profile=hardware_profile,
                low_resource=low_resource,
            )
            if resource_plan.compatibility_status == "blocked":
                reason = "; ".join(resource_plan.reasons) or "mandatory analysis stages exceed the selected hardware profile"
                raise AnalysisDepthError(
                    f"mandatory analysis stages do not fit hardware profile {resource_plan.hardware_profile_id}: {reason}"
                )
            run_identity = analysis_run_identity(
                inputs,
                analyzer_id,
                profile,
                horizons=resolved_horizons,
                seeds=resolved_seeds,
            )
            analysis_depth_payload = {
                "profile": profile.to_dict(),
                "manifest_hash": profile.manifest_hash,
                "horizons": list(resolved_horizons),
                "seeds": list(resolved_seeds),
                "run_identity": run_identity,
                "resource_plan": resource_plan.to_dict(),
                "cache_state": cache_state,
                "upgrade_link": _upgrade_link.to_dict() if _upgrade_link is not None else None,
            }
            workflow_inputs = {
                "instrument_count": len(inputs),
                "analyzer_id": analyzer_id,
                "analysis_depth": analysis_depth_payload,
            }
        jobs = tuple(
            JobSpec(
                key=f"instrument-{index:06d}",
                label=f"Analyze instrument {index + 1}",
                input_payload=self._job_input(
                    instrument_id,
                    analysis_input,
                    analysis_depth_payload,
                ),
                resources=(
                    {
                        "profile": resource_plan.hardware_profile_id,
                        "cpu": resource_plan.estimated_cpu,
                        "memory_mb": resource_plan.estimated_memory_mb,
                        "disk_mb": resource_plan.estimated_disk_mb,
                    }
                    if resource_plan is not None
                    else {}
                ),
            )
            for index, (instrument_id, analysis_input) in enumerate(sorted(inputs.items()))
        )
        self.scheduler.submit(
            self.workflow_type,
            "Bulk instrument analysis",
            jobs,
            input_payload=workflow_inputs,
            dedupe_key=run_id,
            workflow_id=run_id,
        )
        return self._execute(run_id, analyze, max_jobs, stage_runner)

    def resume(
        self,
        run_id: str,
        analyze: AnalysisFunction | None = None,
        *,
        analyzer_id: str,
        max_jobs: int | None = None,
        depth_profile: str | None = None,
        stage_runner: StageRunner | None = None,
    ) -> BulkAnalysisRun:
        """Continue queued work only with the stored analyzer implementation/version."""
        workflow = self._require_run(run_id)
        stored_depth = self._stored_depth_payload(workflow)
        if stored_depth is None:
            analyzer_id = self._validate_execution(analyze, analyzer_id, max_jobs)
            if depth_profile is not None or stage_runner is not None:
                raise ValueError("legacy bulk run has no frozen analysis-depth manifest")
        else:
            analyzer_id = self._validate_execution(stage_runner, analyzer_id, max_jobs)
            frozen_profile = profile_from_dict(stored_depth.get("profile"))
            if stored_depth.get("manifest_hash") != frozen_profile.manifest_hash:
                raise AnalysisDepthError("stored analysis-depth manifest hash does not match its frozen profile")
            if depth_profile is not None and depth_profile != frozen_profile.profile_id:
                raise ValueError("depth profile does not match the frozen bulk run manifest")
            if not callable(stage_runner):
                raise TypeError("stage_runner must be callable to resume a profile-depth run")
            if analyze is not None and not callable(analyze):
                raise TypeError("analyze must be callable when supplied")
        if self._stored_analyzer_id(workflow) != analyzer_id:
            raise ValueError("analyzer identifier does not match the stored bulk run")
        return self._execute(run_id, analyze, max_jobs, stage_runner)

    def upgrade(
        self,
        run_id: str,
        depth_profile: str,
        *,
        stage_runner: StageRunner,
        analyzer_id: str | None = None,
        max_jobs: int | None = None,
        hardware_profile: str = "auto",
        low_resource: bool = False,
        cache_state: str = "cold",
    ) -> BulkAnalysisRun:
        """Create a deeper linked run and reuse stage outputs by content hash."""

        parent = self._require_run(run_id)
        parent_depth = self._stored_depth_payload(parent)
        if parent_depth is None:
            raise ValueError("bulk run has no frozen analysis-depth manifest to upgrade")
        parent_profile = profile_from_dict(parent_depth.get("profile"))
        profiles = load_analysis_depth_profiles()
        try:
            target_profile = profiles[depth_profile]
        except KeyError as exc:
            raise AnalysisDepthError(f"unknown analysis-depth profile {depth_profile!r}") from exc
        if PROFILE_RANK[target_profile.profile_id] <= PROFILE_RANK[parent_profile.profile_id]:
            raise ValueError("upgrade profile must be deeper than the stored profile")
        source_run = self.get_run(run_id)
        if source_run.status != JobStatus.SUCCEEDED.value or source_run.failures:
            raise ValueError("only a completed run without failures can be upgraded")
        stored_analyzer_id = self._stored_analyzer_id(parent)
        target_analyzer_id = analyzer_id or stored_analyzer_id
        target_analyzer_id = self._validate_execution(stage_runner, target_analyzer_id, max_jobs)
        if not callable(stage_runner):
            raise TypeError("stage_runner must be callable for a profile-depth upgrade")
        parent_inputs = {
            job.inputs.get("instrument_id"): job.inputs["analysis_input"]
            for job in self.scheduler.list_jobs(run_id)
            if isinstance(job.inputs, Mapping)
            and isinstance(job.inputs.get("instrument_id"), str)
            and "analysis_input" in job.inputs
        }
        if set(parent_inputs) != set(source_run.hashes):
            raise AnalysisDepthError("completed parent run does not cover its frozen input manifest")
        inputs = {instrument_id: parent_inputs[instrument_id] for instrument_id in source_run.hashes}
        self._load_run_stage_cache(run_id, parent_profile, stored_analyzer_id)
        target_run_id = f"bulk_{uuid.uuid4().hex}"
        reused_hashes = self._reusable_stage_hashes(
            target_profile,
            inputs,
            target_analyzer_id,
            horizons=target_profile.horizons,
            seeds=target_profile.seeds,
        )
        link = AnalysisUpgradeLink(
            parent_run_id=run_id,
            child_run_id=target_run_id,
            from_profile=parent_profile.profile_id,
            to_profile=target_profile.profile_id,
            reused_stage_hashes=reused_hashes,
        )
        return self.start(
            inputs,
            analyzer_id=target_analyzer_id,
            max_jobs=max_jobs,
            depth_profile=target_profile.profile_id,
            stage_runner=stage_runner,
            hardware_profile=hardware_profile,
            low_resource=low_resource,
            cache_state=cache_state,
            _run_id=target_run_id,
            _upgrade_link=link,
        )

    def get_depth_manifest(self, run_id: str) -> dict[str, object] | None:
        """Return the frozen profile and resource plan stored at run start."""

        workflow = self._require_run(run_id)
        payload = self._stored_depth_payload(workflow)
        return dict(payload) if payload is not None else None

    def get_upgrade_link(self, run_id: str) -> AnalysisUpgradeLink | None:
        """Return the immutable parent/child link, when this run is an upgrade."""

        payload = self.get_depth_manifest(run_id)
        if payload is None or not isinstance(payload.get("upgrade_link"), Mapping):
            return None
        raw = payload["upgrade_link"]
        if raw.get("schema_version") != "analysis-upgrade-link.v1":
            raise AnalysisDepthError("stored upgrade link schema is unsupported")
        return AnalysisUpgradeLink(
            parent_run_id=str(raw.get("parent_run_id", "")),
            child_run_id=str(raw.get("child_run_id", "")),
            from_profile=str(raw.get("from_profile", "")),
            to_profile=str(raw.get("to_profile", "")),
            reused_stage_hashes=tuple(str(item) for item in raw.get("reused_stage_hashes", ())),
        )

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
        analyze: AnalysisFunction | None,
        max_jobs: int | None,
        stage_runner: StageRunner | None,
    ) -> BulkAnalysisRun:
        workflow = self._require_run(run_id)
        depth_payload = self._stored_depth_payload(workflow)
        if depth_payload is not None:
            plan = resource_plan_from_dict(depth_payload.get("resource_plan"))
            requested_workers = self.scheduler.max_concurrency if max_jobs is None else max_jobs
            worker_count = min(requested_workers, self.scheduler.max_concurrency, plan.concurrency_limit)
            if worker_count == 0:
                return self.get_run(run_id)
            dispatch_lock = threading.Lock()
            dispatched = 0

            def run_worker() -> None:
                nonlocal dispatched
                while True:
                    with dispatch_lock:
                        if max_jobs is not None and dispatched >= max_jobs:
                            return
                        dispatched += 1
                    try:
                        job = self.scheduler.run_once(
                            lambda context: self._analyze_job(context, analyze, stage_runner),
                            workflow_id=run_id,
                        )
                    except Exception:
                        with dispatch_lock:
                            dispatched -= 1
                        raise
                    if job is None:
                        with dispatch_lock:
                            dispatched -= 1
                        return

            if worker_count == 1:
                run_worker()
            else:
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    futures = [executor.submit(run_worker) for _ in range(worker_count)]
                    for future in futures:
                        future.result()
            return self.get_run(run_id)

        executed = 0
        while max_jobs is None or executed < max_jobs:
            job = self.scheduler.run_once(
                lambda context: self._analyze_job(context, analyze, stage_runner),
                workflow_id=run_id,
            )
            if job is None:
                break
            executed += 1
        return self.get_run(run_id)

    def _analyze_job(
        self,
        context: JobContext,
        analyze: AnalysisFunction | None,
        stage_runner: StageRunner | None,
    ) -> object:
        job = self.scheduler.get_job(context.job_id)
        if job is None or not isinstance(job.inputs, Mapping):
            raise ValueError("bulk analysis job input is unavailable")
        instrument_id = self._instrument_id(job)
        if "analysis_input" not in job.inputs:
            raise ValueError(f"analysis input is unavailable for {instrument_id}")
        workflow = self._require_run(context.workflow_id)
        depth_payload = self._stored_depth_payload(workflow)
        if depth_payload is None:
            if not callable(analyze):
                raise TypeError("analyze must be callable for a legacy bulk run")
            return self.analyze_individual(instrument_id, job.inputs["analysis_input"], analyze)
        if not callable(stage_runner):
            raise TypeError("stage_runner must be callable for a profile-depth run")
        profile = profile_from_dict(depth_payload.get("profile"))
        if depth_payload.get("manifest_hash") != profile.manifest_hash:
            raise AnalysisDepthError("stored analysis-depth manifest hash does not match its frozen profile")
        try:
            output, records = execute_profiled_stages(
                profile,
                instrument_id,
                job.inputs["analysis_input"],
                self._stored_analyzer_id(workflow),
                stage_runner,
                self._stage_cache,
                run_id=context.workflow_id,
                cache_state=str(depth_payload.get("cache_state", "cold")),
                resource_plan=resource_plan_from_dict(depth_payload.get("resource_plan")),
                horizons=tuple(str(item) for item in depth_payload.get("horizons", profile.horizons)),
                seeds=tuple(int(item) for item in depth_payload.get("seeds", profile.seeds)),
                is_cancel_requested=context.is_cancel_requested,
                cache_lock=self._stage_cache_lock,
            )
        except MandatoryEvidenceError as exc:
            append_timing_records(self.scheduler.root, exc.timing_records)
            raise
        append_timing_records(self.scheduler.root, records)
        return output

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

    @staticmethod
    def _job_input(
        instrument_id: str,
        analysis_input: object,
        depth_payload: Mapping[str, object] | None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "instrument_id": instrument_id,
            "analysis_input": analysis_input,
        }
        if depth_payload is not None:
            payload["depth_profile_id"] = depth_payload["profile"]["profile_id"]  # type: ignore[index]
            payload["manifest_hash"] = depth_payload["manifest_hash"]
            payload["run_identity"] = depth_payload["run_identity"]
        return payload

    @staticmethod
    def _resolve_horizons(
        profile: AnalysisDepthProfile,
        horizons: Sequence[str] | None,
    ) -> tuple[str, ...]:
        if horizons is None:
            return profile.horizons
        if not isinstance(horizons, (tuple, list)) or not horizons or any(not isinstance(item, str) or not item.strip() for item in horizons):
            raise ValueError("horizons must be a non-empty sequence of non-blank strings")
        resolved = tuple(item.strip() for item in horizons)
        if len(set(resolved)) != len(resolved):
            raise ValueError("horizons must not contain duplicates")
        if profile.horizons == ("selected",) and len(resolved) != 1:
            raise ValueError("this profile accepts exactly one selected horizon")
        if profile.horizons == ("all_supported",) and resolved != ("all_supported",):
            raise ValueError("Full freezes all supported horizons")
        return resolved

    @staticmethod
    def _resolve_seeds(profile: AnalysisDepthProfile, seeds: Sequence[int] | None) -> tuple[int, ...]:
        if seeds is None:
            return profile.seeds
        if not isinstance(seeds, (tuple, list)) or tuple(seeds) != profile.seeds:
            raise ValueError("seeds must match the immutable profile manifest")
        return tuple(seeds)

    @staticmethod
    def _stored_depth_payload(workflow) -> dict[str, object] | None:
        if not isinstance(workflow.inputs, Mapping):
            return None
        payload = workflow.inputs.get("analysis_depth")
        if payload is None:
            return None
        if not isinstance(payload, Mapping):
            raise AnalysisDepthError("stored analysis-depth run manifest is malformed")
        return dict(payload)

    def _load_run_stage_cache(
        self,
        run_id: str,
        profile: AnalysisDepthProfile,
        analyzer_id: str,
    ) -> None:
        workflow = self._require_run(run_id)
        depth_payload = self._stored_depth_payload(workflow)
        horizons = tuple(str(item) for item in depth_payload.get("horizons", profile.horizons)) if depth_payload else profile.horizons
        seeds = tuple(int(item) for item in depth_payload.get("seeds", profile.seeds)) if depth_payload else profile.seeds
        for job in self.scheduler.list_jobs(run_id):
            if not isinstance(job.inputs, Mapping) or not isinstance(job.outputs, Mapping):
                continue
            instrument_id = job.inputs.get("instrument_id")
            analysis_input = job.inputs.get("analysis_input")
            stage_outputs = job.outputs.get("stages")
            stage_hashes = job.outputs.get("stage_hashes")
            if not isinstance(instrument_id, str) or not isinstance(stage_outputs, Mapping) or not isinstance(stage_hashes, Mapping):
                continue
            for stage_id, output in stage_outputs.items():
                if not isinstance(stage_id, str) or stage_id not in {stage.stage_id for stage in profile.stages}:
                    continue
                metadata = stage_hashes.get(stage_id)
                if not isinstance(metadata, Mapping):
                    continue
                stage = profile.stage(stage_id)
                expected_key = stage_cache_key(
                    instrument_id,
                    analysis_input,
                    analyzer_id,
                    stage,
                    horizons=horizons,
                    seeds=seeds,
                )
                if metadata.get("cache_key") != expected_key or output is None:
                    continue
                content_hash = metadata.get("content_hash")
                if not isinstance(content_hash, str):
                    continue
                if stage_output_hash(output) == content_hash:
                    self._stage_cache[expected_key] = {"content_hash": content_hash, "result": output}

    def _reusable_stage_hashes(
        self,
        profile: AnalysisDepthProfile,
        inputs: Mapping[str, object],
        analyzer_id: str,
        *,
        horizons: tuple[str, ...],
        seeds: tuple[int, ...],
    ) -> tuple[str, ...]:
        hashes: set[str] = set()
        for instrument_id, analysis_input in inputs.items():
            for stage in profile.stages:
                cached = self._stage_cache.get(stage_cache_key(
                    instrument_id,
                    analysis_input,
                    analyzer_id,
                    stage,
                    horizons=horizons,
                    seeds=seeds,
                ))
                if isinstance(cached, Mapping) and isinstance(cached.get("content_hash"), str):
                    hashes.add(str(cached["content_hash"]))
        return tuple(sorted(hashes))


PROFILE_RANK = {"quick": 0, "medium": 1, "high": 2, "full": 3}


__all__ = ["AnalysisFunction", "BulkAnalysisService"]
