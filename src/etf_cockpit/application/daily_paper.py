"""Single-writer daily paper workflow.

Defaults: the caller supplies the runtime ``--root``; the shared app/MCP writer
lock is acquired without waiting; price refresh uses the existing five-year
provider default; the readiness decision is the latest VWCE session strictly
before the current UTC date and no later than the refreshed snapshot; readiness
uses the existing policy with one selected decision session; the AI paper
account defaults to ``ai-paper`` with EUR 40,000 opening cash and EUR 0 monthly
contribution. ``--dry-run`` still refreshes, scores, checks and publishes, but
skips B0-B3 decisions/execution and opening the AI account. Synthetic sample
data is disabled for this workflow. The external AI client remains responsible
for AI proposals through the existing MCP paper controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pandas as pd

from etf_cockpit.application import data_readiness
from etf_cockpit.application.headless_session import (
    HeadlessSession,
    HeadlessWriterBusyError,
    cross_process_writer_guard,
)
from etf_cockpit.core.config import load_config
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.portfolio.paper_bots import run_paper_bots
from etf_cockpit.portfolio.paper_bots_execution import run_paper_bot_execution
from etf_cockpit.portfolio.paper_trading import PaperLedger
from etf_cockpit.application.scoreboard_publication import SCOREBOARD_PUBLICATION_BINDING_ENTITY_TYPE
from etf_cockpit.application.score_backfill import CALENDAR_INSTRUMENT_ID


@dataclass(frozen=True)
class DailyPaperResult:
    status: str
    stage: str
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 0 if self.status == "available" else 1

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stage": self.stage,
            **dict(self.details),
            "execution_allowed": False,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":"), default=str)


class _StageFailure(RuntimeError):
    def __init__(self, stage: str, reason: str) -> None:
        self.stage = stage
        self.reason = reason
        super().__init__(reason)


def _failure(stage: str, exc: BaseException | str) -> _StageFailure:
    if isinstance(exc, BaseException):
        message = f"{type(exc).__name__}: {exc}"
    else:
        message = str(exc)
    return _StageFailure(stage, redact_text(" ".join(message.split()))[:1200])


def _call(stage: str, operation):
    try:
        return operation()
    except _StageFailure:
        raise
    except Exception as exc:
        raise _failure(stage, exc) from exc


def _new_session(root: Path) -> HeadlessSession:
    config = load_config()
    if config.data.allow_synthetic_sample_data:
        raise ValueError("Synthetic sample data is enabled; daily paper requires real provider data.")
    return HeadlessSession(SimpleNamespace(config=config), root=root)


def _refresh(root: Path) -> tuple[HeadlessSession, str]:
    session = _new_session(root)
    service = session.data_service_factory(session.snapshot.config)
    message = service.refresh_yfinance_data(publish_guard=session.activity_publication)
    if not getattr(service, "last_operation_succeeded", True):
        raise RuntimeError(str(message))
    session.refresh_snapshot()
    return session, str(message)


def _rescore(session: HeadlessSession) -> str:
    message = session.data_service_factory(session.snapshot.config).run_yfinance_candidate_analysis(
        publish_guard=session.activity_publication
    )
    session.refresh_snapshot()
    return str(message)


def _publish(session: HeadlessSession) -> Path:
    path = session.publish()
    if session.score_history_warning:
        raise RuntimeError(session.score_history_warning)
    return path


def _as_day(value: object) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _latest_completed_session(inputs: data_readiness.ReadinessInputs, snapshot: object, now: datetime) -> date:
    frame = inputs.prices
    if not isinstance(frame, pd.DataFrame) or frame.empty or not {"etf_id", "date"}.issubset(frame.columns):
        raise ValueError("No usable benchmark prices are available for the readiness gate.")
    benchmark = frame.loc[frame["etf_id"].astype(str).eq(CALENDAR_INSTRUMENT_ID), "date"]
    dates = pd.to_datetime(benchmark, errors="coerce", utc=True).dropna().dt.date
    report_date = _as_day(getattr(getattr(snapshot, "data_report", None), "as_of_date", None))
    if report_date is None:
        raise ValueError("The refreshed snapshot has no verified decision date.")
    completed = [day for day in dates if day < now.astimezone(timezone.utc).date() and day <= report_date]
    if not completed:
        raise ValueError("No completed benchmark decision session is available.")
    return max(completed)


def _published_snapshot_id(root: Path) -> dict[str, str]:
    scoreboard_path = root / "data" / "derived" / "scoreboard.parquet"
    scoreboard_bytes = scoreboard_path.read_bytes()
    scoreboard_hash = hashlib.sha256(scoreboard_bytes).hexdigest()
    with TransactionalStore(root, read_only=True) as store:
        records = store.list(SCOREBOARD_PUBLICATION_BINDING_ENTITY_TYPE)
    matched = [
        record.payload
        for record in records
        if record.payload.get("schema_version") == "scoreboard_publication_binding.v1"
        and record.payload.get("scoreboard_sha256") == scoreboard_hash
        and record.payload.get("execution_allowed") is False
    ]
    if not matched:
        raise ValueError("The published scoreboard has no matching immutable snapshot binding.")
    newest_at = max(str(item.get("known_at") or "") for item in matched)
    newest = [item for item in matched if str(item.get("known_at") or "") == newest_at]
    identities = {
        (str(item.get("run_id") or ""), str(item.get("score_snapshot_hash") or ""))
        for item in newest
    }
    if len(identities) != 1:
        raise ValueError("The published scoreboard snapshot binding is ambiguous.")
    run_id, score_snapshot_hash = next(iter(identities))
    if not run_id or len(score_snapshot_hash) != 64 or any(char not in "0123456789abcdef" for char in score_snapshot_hash.lower()):
        raise ValueError("The published scoreboard snapshot identity is invalid.")
    return {"scoreboard_sha256": scoreboard_hash, "score_snapshot_hash": score_snapshot_hash.lower()}


def _readiness_snapshot_id(inputs: data_readiness.ReadinessInputs, decision_session: date) -> str:
    history = inputs.history
    if not isinstance(history, pd.DataFrame) or history.empty or not {"as_of_date", "snapshot_hash"}.issubset(history.columns):
        raise ValueError("The readiness score run has no immutable snapshot id.")
    rows = history.loc[history["as_of_date"].astype(str).eq(decision_session.isoformat())]
    values = {str(value).strip().lower() for value in rows["snapshot_hash"] if pd.notna(value)}
    if len(values) != 1:
        raise ValueError("The readiness score run has no unique snapshot id.")
    snapshot_id = next(iter(values))
    if len(snapshot_id) != 64 or any(char not in "0123456789abcdef" for char in snapshot_id):
        raise ValueError("The readiness score run snapshot id is invalid.")
    return snapshot_id


def _validate_readiness(root: Path, snapshot: object, now: datetime) -> tuple[date, str]:
    inputs = data_readiness.load_inputs(root)
    decision_session = _latest_completed_session(inputs, snapshot, now)
    report = data_readiness.evaluate_readiness(
        inputs,
        decision_session,
        decision_session,
        data_readiness.load_thresholds(),
        every=1,
    )
    if not report.passed:
        raise _failure("readiness", report.format_text())
    return decision_session, _readiness_snapshot_id(inputs, decision_session)


def _open_ai_account(root: Path, account_id: str, initial_cash_eur: float):
    return PaperLedger(root, account_id=account_id).open_account(
        initial_cash=initial_cash_eur,
        base_currency="EUR",
    )


def run_daily_paper(
    root: Path,
    *,
    ai_account: str = "ai-paper",
    initial_cash_eur: float = 40_000,
    monthly_contribution_eur: float = 0,
    dry_run: bool = False,
    now: datetime | None = None,
) -> DailyPaperResult:
    """Refresh and publish once, gate the newest completed session, and run paper-only stages."""

    resolved_root = Path(root).expanduser().resolve()
    if not ai_account.strip():
        return DailyPaperResult("blocked", "configuration", {"error": "AI account id must not be blank."})
    if isinstance(initial_cash_eur, bool) or not math.isfinite(float(initial_cash_eur)) or initial_cash_eur <= 0:
        return DailyPaperResult("blocked", "configuration", {"error": "Initial EUR cash must be finite and positive."})
    if (
        isinstance(monthly_contribution_eur, bool)
        or not math.isfinite(float(monthly_contribution_eur))
        or monthly_contribution_eur != 0
    ):
        return DailyPaperResult(
            "blocked", "configuration", {"error": "The AI paper account supports only a EUR 0 monthly contribution."}
        )
    cutoff = now or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        return DailyPaperResult("blocked", "configuration", {"error": "The driver clock must be timezone-aware."})
    try:
        with cross_process_writer_guard(resolved_root):
            session, refresh_message = _call("refresh", lambda: _refresh(resolved_root))
            rescore_message = _call("rescore", lambda: _rescore(session))
            decision_session, gate_snapshot_id = _call(
                "readiness", lambda: _validate_readiness(resolved_root, session.snapshot, cutoff)
            )
            _call("publish", lambda: _publish(session))
            published_snapshot_id = _call("publish", lambda: _published_snapshot_id(resolved_root))
            if gate_snapshot_id != published_snapshot_id["score_snapshot_hash"]:
                raise _failure("readiness", "The readiness PASS is bound to an older published snapshot id.")
            readiness_summary = {
                "status": "PASS",
                "decision_session": decision_session.isoformat(),
                "cadence_sessions": 1,
                "snapshot_id": published_snapshot_id["score_snapshot_hash"],
                "scoreboard_sha256": published_snapshot_id["scoreboard_sha256"],
            }
            if dry_run:
                return DailyPaperResult(
                    "available",
                    "dry_run",
                    {
                        "refresh": refresh_message,
                        "rescore": rescore_message,
                        "readiness": readiness_summary,
                        "paper_bots": "skipped",
                        "ai_account": "skipped",
                    },
                )
            paper_bots = _call(
                "paper_bots",
                lambda: run_paper_bots(cutoff, root=resolved_root),
            )
            if paper_bots.status != "available":
                raise _failure("paper_bots", paper_bots.reason or "B0-B3 decision stage is unavailable.")
            execution = _call(
                "paper_bot_execution",
                lambda: run_paper_bot_execution(cutoff, root=resolved_root),
            )
            if execution.status != "available":
                raise _failure("paper_bot_execution", execution.reason or "B0-B3 execution stage is unavailable.")
            account = _call(
                "ai_account",
                lambda: _open_ai_account(resolved_root, ai_account, float(initial_cash_eur)),
            )
            return DailyPaperResult(
                "available",
                "complete",
                {
                    "refresh": refresh_message,
                    "rescore": rescore_message,
                    "readiness": readiness_summary,
                    "paper_bots": {"status": paper_bots.status, "appended": paper_bots.appended},
                    "paper_bot_execution": {"status": execution.status, "appended": execution.appended},
                    "ai_account": {
                        "account_id": account.account_id,
                        "status": account.status,
                        "base_currency": account.base_currency,
                        "cash": account.cash,
                        "event_count": account.event_count,
                        "monthly_contribution_eur": 0,
                    },
                },
            )
    except HeadlessWriterBusyError as exc:
        return DailyPaperResult("blocked", "lock", {"error": redact_text(str(exc))})
    except _StageFailure as exc:
        return DailyPaperResult("blocked", exc.stage, {"error": exc.reason})
    except Exception as exc:
        return DailyPaperResult("blocked", "lock", {"error": redact_text(f"{type(exc).__name__}: {exc}")[:1200]})


__all__ = ["DailyPaperResult", "run_daily_paper"]
