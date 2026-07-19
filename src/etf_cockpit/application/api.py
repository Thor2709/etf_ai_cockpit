"""Local in-process application API for typed queries and safe commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import hashlib
import math
from pathlib import Path
import threading
from typing import TypeVar
import uuid

import pandas as pd

from etf_cockpit.application.contracts import (
    ApiStatus,
    ApplicationCommand,
    CancelWorkflowCommand,
    CommandResult,
    ForecastViewModel,
    InstrumentViewModel,
    JobViewModel,
    OperationViewModel,
    PageRequest,
    PageView,
    PaperViewModel,
    PortfolioViewModel,
    ProposalGateViewModel,
    ProposalReviewRequest,
    ProposalViewModel,
    QueryRequest,
    RefreshDataCommand,
    ScoreViewModel,
    SubmitWorkflowCommand,
)
from etf_cockpit.core.job_scheduler import DurableJobScheduler, JobSpec
from etf_cockpit.core.paths import ROOT


SnapshotProvider = Callable[[], object]
RevisionProvider = Callable[[], str]
CommandHandler = Callable[[ApplicationCommand], Mapping[str, object] | None]
PageItemT = TypeVar("PageItemT")


@dataclass(frozen=True)
class _LedgerEntry:
    fingerprint: str
    result: CommandResult


class LocalApplicationApi:
    """Typed, local-first query and command boundary.

    Queries only adapt already cached snapshot data and therefore do not run
    provider, feature, model or portfolio calculations during page rendering.
    Commands are serialised in-process, check an optional snapshot revision and
    retain idempotency results for the lifetime of this application instance.
    """

    def __init__(
        self,
        snapshot_provider: SnapshotProvider,
        *,
        scheduler: DurableJobScheduler | None = None,
        revision_provider: RevisionProvider | None = None,
        command_handlers: Mapping[str, CommandHandler] | None = None,
        root: Path = ROOT,
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._root = root
        self._scheduler = scheduler or DurableJobScheduler(root)
        self._revision_provider = revision_provider
        self._command_handlers = dict(command_handlers or {})
        self._ledger: dict[str, _LedgerEntry] = {}
        self._lock = threading.RLock()

    def query(self, request: QueryRequest) -> PageView[object]:
        queries: dict[str, Callable[[PageRequest], PageView[object]]] = {
            "universe": self.get_universe,
            "instruments": self.get_instruments,
            "scores": self.get_scores,
            "forecasts": self.get_forecasts,
            "portfolios": self.get_portfolios,
            "jobs": self.get_jobs,
            "paper": self.get_paper,
            "proposals": self.get_proposals,
            "operations": self.get_operations,
        }
        return queries[request.resource](request.page)

    def get_universe(self, page: PageRequest = PageRequest()) -> PageView[InstrumentViewModel]:
        snapshot = self._snapshot()
        records = []
        universe = getattr(getattr(snapshot, "config", None), "universe", None)
        for item in getattr(universe, "etfs", ()):
            records.append(
                InstrumentViewModel(
                    instrument_id=str(item.id),
                    name=str(item.name),
                    ticker=str(item.ticker),
                    asset_class=str(getattr(item, "asset_class", "")),
                    region=_optional_text(getattr(item, "region", None)),
                    currency=str(getattr(item, "currency", "EUR")),
                    status="enabled" if bool(getattr(item, "enabled", False)) else "disabled",
                    as_of=_snapshot_as_of(snapshot),
                )
            )
        return _page(tuple(sorted(records, key=lambda item: item.instrument_id)), page)

    def get_instruments(self, page: PageRequest = PageRequest()) -> PageView[InstrumentViewModel]:
        snapshot = self._snapshot()
        available = _frame_ids(getattr(snapshot, "prices", pd.DataFrame()))
        instruments = self.get_universe(PageRequest(offset=0, limit=500)).items
        rows = tuple(item.model_copy(update={"status": "available" if item.instrument_id in available else "unavailable"}) for item in instruments)
        return _page(rows, page)

    def get_scores(self, page: PageRequest = PageRequest()) -> PageView[ScoreViewModel]:
        snapshot = self._snapshot()
        latest: dict[str, object] = {}
        for signal in getattr(snapshot, "signals", ()):
            instrument_id = str(getattr(signal, "etf_id", ""))
            prior = latest.get(instrument_id)
            if prior is None or str(getattr(signal, "signal_date", "")) >= str(getattr(prior, "signal_date", "")):
                latest[instrument_id] = signal
        rows = tuple(
            ScoreViewModel(
                instrument_id=instrument_id,
                score=_finite(getattr(signal, "total_score", None)),
                state=str(getattr(signal, "research_state", "unavailable")),
                confidence=_finite(getattr(signal, "confidence", None)),
                status=str(getattr(signal, "status", "unavailable")),
                as_of=_date_text(getattr(signal, "signal_date", None)),
            )
            for instrument_id, signal in sorted(latest.items())
        )
        return _page(rows, page)

    def get_forecasts(self, page: PageRequest = PageRequest()) -> PageView[ForecastViewModel]:
        frame = _frame(getattr(self._snapshot(), "forecasts", pd.DataFrame()))
        rows: list[ForecastViewModel] = []
        for _, row in frame.iterrows():
            rows.append(
                ForecastViewModel(
                    instrument_id=str(row.get("etf_id", "")),
                    model=str(row.get("model_name", row.get("model", "unknown"))),
                    horizon_days=_integer(row.get("horizon_days")),
                    expected_return=_finite(row.get("expected_return")),
                    status=str(row.get("status", "unavailable")),
                    as_of=_date_text(row.get("forecast_date")),
                )
            )
        return _page(tuple(rows), page)

    def get_portfolios(self, page: PageRequest = PageRequest()) -> PageView[PortfolioViewModel]:
        frame = _frame(getattr(self._snapshot(), "holdings", pd.DataFrame()))
        rows = tuple(
            PortfolioViewModel(
                instrument_id=str(row.get("etf_id", row.get("instrument_id", ""))),
                current_weight=_finite(row.get("current_weight")),
                target_weight=_finite(row.get("target_weight")),
                market_value=_finite(row.get("market_value_eur", row.get("market_value"))),
                currency=_optional_text(row.get("currency")),
                status="available",
            )
            for _, row in frame.iterrows()
        )
        return _page(rows, page)

    def get_jobs(self, page: PageRequest = PageRequest()) -> PageView[JobViewModel]:
        rows: list[JobViewModel] = []
        try:
            for workflow in self._scheduler.list_workflows():
                jobs = self._scheduler.list_jobs(workflow.workflow_id)
                rows.append(
                    JobViewModel(
                        workflow_id=workflow.workflow_id,
                        label=workflow.label,
                        status=workflow.status.value,
                        created_at=workflow.created_at,
                        finished_at=workflow.finished_at,
                        job_count=len(jobs),
                        active=workflow.status.value in {"queued", "running"},
                        hash_chain_valid=self._scheduler.verify_event_chain(workflow.workflow_id),
                        error_message=workflow.error_message,
                    )
                )
        except Exception:
            rows = []
        return _page(tuple(sorted(rows, key=lambda item: item.created_at, reverse=True)), page)

    def get_paper(self, page: PageRequest = PageRequest()) -> PageView[PaperViewModel]:
        snapshot = self._snapshot()
        source = getattr(snapshot, "paper_accounts", ())
        rows = tuple(
            PaperViewModel(
                account_id=str(item.get("account_id", "")),
                status=str(item.get("status", "unavailable")),
                as_of=_date_text(item.get("as_of")),
                equity=_finite(item.get("equity")),
                message=str(item.get("message", "")),
            )
            for item in source
            if isinstance(item, Mapping)
        )
        if not rows:
            rows = (PaperViewModel(account_id="local-paper", status="unavailable", message="No paper account is configured."),)
        return _page(rows, page)

    def get_operations(self, page: PageRequest = PageRequest()) -> PageView[OperationViewModel]:
        operations = getattr(self._snapshot(), "operations", ())
        rows = tuple(
            OperationViewModel(
                operation_id=str(item.get("operation_id", "")),
                operation_type=str(item.get("operation_type", "unknown")),
                status=str(item.get("status", "unavailable")),
                occurred_at=str(item.get("occurred_at", "")),
                message=str(item.get("message", "")),
            )
            for item in operations
            if isinstance(item, Mapping)
        )
        return _page(rows, page)

    def get_proposals(self, page: PageRequest = PageRequest()) -> PageView[ProposalViewModel]:
        from etf_cockpit.portfolio.proposal_policy import load_proposal_records

        rows: list[ProposalViewModel] = []
        for item in load_proposal_records(directory=self._root / "data" / "operations" / "proposals"):
            rows.append(_proposal_view_model(item))
        return _page(tuple(rows), page)

    def get_authority_policy_checksum(self) -> str:
        from etf_cockpit.portfolio.proposal_policy import current_authority_policy_checksum

        return current_authority_policy_checksum()

    def review_proposal(self, request: ProposalReviewRequest) -> ProposalViewModel:
        """Create and persist one non-executable proposal review decision."""

        from etf_cockpit.portfolio.proposal_policy import (
            GateEvidence,
            ProposalRequest,
            build_proposal_decision,
            save_proposal_decision,
        )

        decision = build_proposal_decision(
            ProposalRequest(
                instrument_id=request.instrument_id,
                current_quantity=request.current_quantity,
                target_quantity=request.target_quantity,
                strategy_id=request.strategy_id,
                strategy_stage=request.strategy_stage,
                model_id=request.model_id,
                model_stage=request.model_stage,
                account_id=request.account_id,
                account_stage=request.account_stage,
                optimiser_output_id=request.optimiser_output_id,
                portfolio_revision=request.portfolio_revision,
                data_revision=request.data_revision,
                as_of=request.as_of,
                expires_at=request.expires_at,
                authority_policy_checksum=request.authority_policy_checksum,
                gate_evidence=tuple(
                    GateEvidence(item.gate_id, item.passed, item.reason, item.blocker)
                    for item in request.gate_evidence
                ),
                rationale=request.rationale,
            )
        )
        save_proposal_decision(decision, directory=self._root / "data" / "operations" / "proposals")
        return _proposal_view_model(decision.to_payload())

    def execute(self, command: ApplicationCommand) -> CommandResult:
        fingerprint = hashlib.sha256(command.model_dump_json().encode("utf-8")).hexdigest()
        with self._lock:
            prior = self._ledger.get(command.idempotency_key)
            if prior is not None:
                if prior.fingerprint != fingerprint:
                    return _result(
                        command,
                        ApiStatus.CONFLICT,
                        revision=self.revision,
                        error_code="idempotency_key_reused",
                        error_message="The idempotency key was already used for a different command.",
                    )
                return prior.result.model_copy(update={"status": ApiStatus.REPLAYED, "replayed": True})
            if command.expected_revision is not None and command.expected_revision != self.revision:
                result = _result(
                    command,
                    ApiStatus.CONFLICT,
                    revision=self.revision,
                    error_code="revision_conflict",
                    error_message=f"Expected revision {command.expected_revision}, current revision is {self.revision}.",
                )
                self._ledger[command.idempotency_key] = _LedgerEntry(fingerprint, result)
                return result
            result = self._execute_new(command)
            self._ledger[command.idempotency_key] = _LedgerEntry(fingerprint, result)
            return result

    def run_next_job(self, runner: Callable[[object], object]) -> object:
        return self._scheduler.run_once(runner)

    def recover_expired_leases(self) -> tuple[object, ...]:
        return self._scheduler.recover_expired_leases()

    def verify_event_chain(self, workflow_id: str | None = None) -> bool:
        return self._scheduler.verify_event_chain(workflow_id)

    @property
    def revision(self) -> str:
        if self._revision_provider is not None:
            return str(self._revision_provider())
        snapshot = self._snapshot()
        return str(getattr(snapshot, "universe_revision", "") or "unknown")

    def _execute_new(self, command: ApplicationCommand) -> CommandResult:
        handler = self._command_handlers.get(command.kind)
        if handler is not None:
            try:
                details = _details(handler(command))
                return _result(command, ApiStatus.ACCEPTED, revision=self.revision, details=details)
            except Exception as exc:
                return _result(command, ApiStatus.FAILED, revision=self.revision, error_code="command_failed", error_message=f"{type(exc).__name__}: {exc}")
        if isinstance(command, SubmitWorkflowCommand):
            try:
                workflow = self._scheduler.submit(
                    command.workflow_type,
                    command.label,
                    tuple(JobSpec(key, f"{command.label}: {key}") for key in command.job_keys),
                    input_payload=command.input_payload,
                    dedupe_key=command.dedupe_key or command.idempotency_key,
                )
                return _result(command, ApiStatus.ACCEPTED, revision=self.revision, resource_id=workflow.workflow_id, details=(("status", workflow.status.value),))
            except Exception as exc:
                return _result(command, ApiStatus.FAILED, revision=self.revision, error_code="workflow_submit_failed", error_message=f"{type(exc).__name__}: {exc}")
        if isinstance(command, CancelWorkflowCommand):
            try:
                jobs = self._scheduler.cancel(command.workflow_id)
                return _result(command, ApiStatus.ACCEPTED, revision=self.revision, resource_id=command.workflow_id, details=(("cancelled_jobs", str(len(jobs))),))
            except Exception as exc:
                return _result(command, ApiStatus.FAILED, revision=self.revision, error_code="workflow_cancel_failed", error_message=f"{type(exc).__name__}: {exc}")
        if isinstance(command, RefreshDataCommand):
            return _result(command, ApiStatus.UNAVAILABLE, revision=self.revision, error_code="refresh_handler_unavailable", error_message="No refresh handler is registered on the local application boundary.")
        return _result(command, ApiStatus.FAILED, revision=self.revision, error_code="unknown_command", error_message="The command is not supported by this application boundary.")

    def _snapshot(self) -> object:
        return self._snapshot_provider()


def _proposal_view_model(item: Mapping[str, object]) -> ProposalViewModel:
    raw_gates = item.get("gates", ())
    gates = tuple(
        ProposalGateViewModel(
            gate_id=str(gate.get("gate_id", "")),
            passed=bool(gate.get("passed", False)),
            reason=str(gate.get("reason", "")),
            blocker=bool(gate.get("blocker", True)),
        )
        for gate in raw_gates
        if isinstance(gate, Mapping)
    ) if isinstance(raw_gates, (tuple, list)) else ()
    raw_alternatives = item.get("alternatives", ())
    alternatives = tuple(
        str(alternative.get("name", ""))
        for alternative in raw_alternatives
        if isinstance(alternative, Mapping)
    ) if isinstance(raw_alternatives, (tuple, list)) else ()
    return ProposalViewModel(
        proposal_id=str(item.get("proposal_id", "")),
        instrument_id=str(item.get("instrument_id", "")),
        outcome=str(item.get("outcome", "manual_review")),
        authority_stage=str(item.get("authority_stage", "disabled")),
        proposal_allowed=bool(item.get("proposal_allowed", False)),
        execution_allowed=False,
        quantity_delta=float(item.get("quantity_delta", 0.0)),
        rationale=str(item.get("rationale", "")),
        as_of=str(item.get("as_of", "")),
        expires_at=str(item.get("expires_at", "")),
        gate_count=len(gates),
        failed_gate_count=sum(not gate.passed for gate in gates),
        alternatives=alternatives,
        input_checksum=str(item.get("input_checksum", "")),
        gates=gates,
        authority_policy_checksum=str(item.get("authority_policy_checksum", "")),
        gate_policy_version=str(item.get("gate_policy_version", "")),
        gate_policy_checksum=str(item.get("gate_policy_checksum", "")),
    )


def _page(items: Sequence[PageItemT], page: PageRequest) -> PageView[PageItemT]:
    total = len(items)
    end = min(page.offset + page.limit, total)
    next_offset = end if end < total else None
    return PageView(items=tuple(items[page.offset:end]), total=total, offset=page.offset, limit=page.limit, next_offset=next_offset)

def _frame(value: object) -> pd.DataFrame:
    return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _frame_ids(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "etf_id" not in frame.columns:
        return set()
    return {str(value) for value in frame["etf_id"].dropna().tolist()}


def _finite(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: object) -> int | None:
    number = _finite(value)
    return None if number is None else int(number)


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _date_text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (date,)):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _snapshot_as_of(snapshot: object) -> str | None:
    report = getattr(snapshot, "data_report", None)
    return _date_text(getattr(report, "as_of_date", None))


def _details(value: Mapping[str, object] | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(item)) for key, item in (value or {}).items()))


def _result(
    command: ApplicationCommand,
    status: ApiStatus,
    *,
    revision: str,
    resource_id: str | None = None,
    details: tuple[tuple[str, str], ...] = (),
    error_code: str | None = None,
    error_message: str | None = None,
) -> CommandResult:
    return CommandResult(
        status=status,
        command_id=f"cmd_{uuid.uuid4().hex}",
        idempotency_key=command.idempotency_key,
        revision=revision,
        resource_id=resource_id,
        details=details,
        error_code=error_code,
        error_message=error_message,
    )


__all__ = ["LocalApplicationApi"]
