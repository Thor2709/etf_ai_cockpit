"""Single-writer nightly paper workflow (forward paper path, SDD docs/architecture/forward-paper-path.md §3).

Order, all under the shared app/MCP writer lock (acquired without waiting):

a. S&P 500 capture (a failure is logged; tomorrow's readiness then fails).
b. S = the latest VWCE session before today and no later than the stored snapshot's report date. No new session
   (S already has a forward run from an earlier night) skips b-f with stage ``no_new_session``. Otherwise
   t_S = clock and the forward score run of S is stored with ``run_completed_at`` = t_S; its feature vintage follows.
c. Readiness of S on that run (H). A FAIL skips d-f.
d. Paper enabled and kill switch off? Otherwise skip e-f (stage ``paper_disabled`` / ``paper_kill_switch_active``).
e. Recorder bound to (S, H); f. execution and the AI paper account (``ai-paper``, EUR 40,000, EUR 0 monthly).
g. Refresh, rescore and publish (UI only) run whatever b-f did; a b-f failure keeps a non-zero exit code.

``--dry-run`` runs a-c and g and skips d-f. Synthetic sample data is disabled for this workflow. The external AI
client remains responsible for AI proposals through the existing MCP paper controls.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping

import pandas as pd

from etf_cockpit.application import data_readiness
from etf_cockpit.application.feature_observations import record_feature_observations
from etf_cockpit.application.headless_session import (
    HeadlessSession,
    HeadlessWriterBusyError,
    cross_process_writer_guard,
)
from etf_cockpit.application.paper_manual_order import load_paper_controls_status
from etf_cockpit.application.score_backfill import CALENDAR_INSTRUMENT_ID, backfill_score_history
from etf_cockpit.core.config import load_config
from etf_cockpit.core.session_log import redact_text
from etf_cockpit.core.settings_bundle import load_settings_bundle
from etf_cockpit.data import sp500_capture
from etf_cockpit.data.score_history_backfill import FORWARD_PROVENANCE, STORE_PROVENANCES, load_backfill_score_history
from etf_cockpit.portfolio.paper_bot_challengers import build_challenger_engines
from etf_cockpit.portfolio.paper_bots import run_paper_bots
from etf_cockpit.portfolio.paper_bots_execution import LEDGER_PRICE_BASIS, run_paper_bot_execution
from etf_cockpit.portfolio.paper_trading import PaperLedger


AI_ACCOUNT_ID = "ai-paper"
AI_INITIAL_CASH_EUR = 40_000.0
# SDD C8: a partial recorder run is accepted only for these challengers when they make no new trade.
_PARTIAL_FAMILIES = frozenset({"B1-r", "B2-o"})
_NO_NEW_TRADE = "NO_NEW_TRADE"


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


def _refresh(
    root: Path,
    *,
    incremental: bool = False,
    include_fundamentals: bool = True,
    include_fx: bool = False,
) -> tuple[HeadlessSession, str]:
    session = _new_session(root)
    service = session.data_service_factory(session.snapshot.config)
    if incremental or not include_fundamentals or include_fx:
        refresh_options = {
            "incremental": incremental,
            "include_fundamentals": include_fundamentals,
            # Without fundamentals (nightly) skip reference metadata (~2 Yahoo calls per ETF);
            # the full weekly refresh_stock_fundamentals.py run refreshes it.
            "include_reference_data": include_fundamentals,
        }
        if include_fx:
            refresh_options["include_fx"] = True
        message = service.refresh_yfinance_data(publish_guard=session.activity_publication, **refresh_options)
    else:
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


def _capture(root: Path, clock: Callable[[], datetime]) -> dict[str, Any]:
    """Step a: fetch first, so the capture is stamped after the page is in hand; a failure is only logged."""

    try:
        page = sp500_capture._fetch(sp500_capture.WIKI_CONSTITUENTS)
        return asdict(sp500_capture.capture_sp500(root, now=clock(), fetch=lambda _url: page))
    except sp500_capture.Sp500CaptureError as exc:
        return {"status": "failed", "reason": redact_text(str(exc))[:400]}
    except Exception as exc:
        return {"status": "failed", "reason": redact_text(f"capture failed: {type(exc).__name__}: {exc}")[:400]}


def _latest_completed_session(inputs: data_readiness.ReadinessInputs, snapshot: object, now: datetime) -> date:
    frame = inputs.prices
    if not isinstance(frame, pd.DataFrame) or frame.empty or not {"etf_id", "date"}.issubset(frame.columns):
        raise ValueError("No usable benchmark prices are available for the readiness gate.")
    benchmark = frame.loc[frame["etf_id"].astype(str).eq(CALENDAR_INSTRUMENT_ID), "date"]
    dates = pd.to_datetime(benchmark, errors="coerce", utc=True).dropna().dt.date
    report_date = _as_day(getattr(getattr(snapshot, "data_report", None), "as_of_date", None))
    if report_date is None:
        raise ValueError("The stored snapshot has no verified decision date.")
    completed = [day for day in dates if day < now.astimezone(timezone.utc).date() and day <= report_date]
    if not completed:
        raise ValueError("No completed benchmark decision session is available.")
    return max(completed)


def _is_new_session(history: pd.DataFrame, session: date) -> bool:
    """False when S <= the session of the latest stored forward run (SDD §3 step b, C8: ``no_new_session``)."""

    if history.empty or not {"provenance", "as_of_date"}.issubset(history.columns):
        return True
    forward = history.loc[history["provenance"].astype(str).eq(FORWARD_PROVENANCE), "as_of_date"].astype(str)
    return forward.empty or session.isoformat() > str(forward.max())


def _decision_session(root: Path, clock: Callable[[], datetime]) -> tuple[date, bool]:
    """Step b: S from the stored data (no provider call), and whether S is a new session."""

    session = _new_session(root)
    session.refresh_snapshot()
    now = clock()
    day = _latest_completed_session(data_readiness.load_inputs(root), session.snapshot, now)
    return day, _is_new_session(load_backfill_score_history(root, STORE_PROVENANCES), day)


def _score_run(root: Path, session: date, completed_at: datetime) -> dict[str, Any]:
    result = backfill_score_history(root, session, session, every=1, completed_at=completed_at)
    if result.status != "available":
        raise ValueError(result.reason or "The forward score run is unavailable.")
    return {"status": result.status, "runs_written": result.runs_written, "runs_kept": result.runs_kept}


def _readiness_snapshot_id(inputs: data_readiness.ReadinessInputs, decision_session: date) -> tuple[str, str]:
    history = inputs.history
    if not isinstance(history, pd.DataFrame) or history.empty or not {"as_of_date", "snapshot_hash", "run_id"}.issubset(history.columns):
        raise ValueError("The readiness score run has no immutable snapshot id.")
    rows = history.loc[history["as_of_date"].astype(str).eq(decision_session.isoformat())]
    values = {(str(run_id), str(value).strip().lower()) for run_id, value in zip(rows["run_id"], rows["snapshot_hash"]) if pd.notna(value)}
    if len(values) != 1:
        raise ValueError("The readiness score run has no unique snapshot id.")
    run_id, snapshot_id = next(iter(values))
    if len(snapshot_id) != 64 or any(char not in "0123456789abcdef" for char in snapshot_id):
        raise ValueError("The readiness score run snapshot id is invalid.")
    return snapshot_id, run_id


def _validate_readiness(root: Path, decision_session: date) -> tuple[Any, str, str]:
    """Step c: the readiness report of S on the stored run, with that run's H and run id."""

    inputs = data_readiness.load_inputs(root)
    report = data_readiness.evaluate_readiness(
        inputs, decision_session, decision_session, data_readiness.load_thresholds(), every=1,
    )
    return (report, *_readiness_snapshot_id(inputs, decision_session))


def _paper_gate(root: Path) -> str | None:
    """Step d: None when the paper stages may run, else the skip stage. Unreadable controls raise."""

    if not load_settings_bundle(root).controls.paper.enabled:
        return "paper_disabled"
    controls = load_paper_controls_status(root, "local-paper")
    if controls.get("status") != "available":
        raise ValueError("Paper controls are unavailable.")
    return "paper_kill_switch_active" if controls.get("kill_switch_active") is True else None


def _open_ai_account(root: Path, account_id: str, initial_cash_eur: float):
    return PaperLedger(root, account_id=account_id).open_account(
        initial_cash=initial_cash_eur,
        base_currency="EUR",
    )


def _check_recorder(result: Any, snapshot_id: str) -> dict[str, Any]:
    """The recorder must bind to H (SDD C5) and be complete, or partial only for challengers without a new trade (C8)."""

    bots = [
        {key: item.get(key) for key in ("bot_family", "bot_id", "status", "reason")}
        for item in result.records
    ]
    if result.status == "unavailable":
        raise _failure("paper_bots", result.reason or "B0-B3 decision stage is unavailable.")
    if result.candidate_snapshot != snapshot_id:
        raise _failure("paper_bots", "recorded snapshot differs from H")
    if result.status != "available":
        rejected = [
            str(item["bot_family"]) for item in bots
            if item["status"] != "available"
            and not (item["bot_family"] in _PARTIAL_FAMILIES and str(item["reason"] or "").startswith(_NO_NEW_TRADE))
        ]
        if result.status != "partial" or rejected:
            raise _failure("paper_bots", f"partial not accepted: {', '.join(rejected) or result.status}")
    return {"status": result.status, "appended": result.appended, "bots": bots}


def run_daily_paper(
    root: Path,
    *,
    ai_account: str = AI_ACCOUNT_ID,
    initial_cash_eur: Decimal | float = AI_INITIAL_CASH_EUR,
    monthly_contribution_eur: float = 0,
    dry_run: bool = False,
    incremental_prices: bool = False,
    skip_fundamentals: bool = False,
    refresh_fx: bool = False,
    now: datetime | None = None,
) -> DailyPaperResult:
    """Capture, score and gate session S, run the paper stages bound to it, then refresh and publish."""

    if ai_account != AI_ACCOUNT_ID:
        raise ValueError(f"Daily paper requires AI account id {AI_ACCOUNT_ID!r}.")
    if initial_cash_eur != AI_INITIAL_CASH_EUR:
        raise ValueError(f"Daily paper requires opening cash of exactly EUR {AI_INITIAL_CASH_EUR:,.0f}.")
    resolved_root = Path(root).expanduser().resolve()
    if (
        isinstance(monthly_contribution_eur, bool)
        or not math.isfinite(float(monthly_contribution_eur))
        or monthly_contribution_eur != 0
    ):
        return DailyPaperResult(
            "blocked", "configuration", {"error": "The AI paper account supports only a EUR 0 monthly contribution."}
        )
    if now is not None and now.tzinfo is None:
        return DailyPaperResult("blocked", "configuration", {"error": "The driver clock must be timezone-aware."})

    def clock() -> datetime:
        return now if now is not None else datetime.now(timezone.utc)

    refresh_options: dict[str, bool] = {}
    if incremental_prices or skip_fundamentals or refresh_fx:
        refresh_options = {"incremental": incremental_prices, "include_fundamentals": not skip_fundamentals}
        if refresh_fx:
            refresh_options["include_fx"] = True
    details: dict[str, Any] = {}
    try:
        with cross_process_writer_guard(resolved_root):
            failure: _StageFailure | None = None
            try:
                stage = _paper_stages(resolved_root, clock, details, dry_run, ai_account, float(initial_cash_eur))
            except Exception as exc:  # any paper-stage error still lets step g run
                failure = exc if isinstance(exc, _StageFailure) else _failure("paper_stages", exc)
                stage = failure.stage
            try:  # step g runs whatever the paper stages did (SDD C8)
                session, details["refresh"] = _call("refresh", lambda: _refresh(resolved_root, **refresh_options))
                details["rescore"] = _call("rescore", lambda: _rescore(session))
                _call("publish", lambda: _publish(session))
            except _StageFailure as exc:
                failure = failure or exc
            if failure is not None:
                return DailyPaperResult("blocked", failure.stage, {**details, "error": failure.reason})
            return DailyPaperResult("available", stage, details)
    except HeadlessWriterBusyError as exc:
        return DailyPaperResult("blocked", "lock", {"error": redact_text(str(exc))})
    except Exception as exc:
        return DailyPaperResult("blocked", "lock", {"error": redact_text(f"{type(exc).__name__}: {exc}")[:1200]})


def _paper_stages(
    root: Path, clock: Callable[[], datetime], details: dict[str, Any], dry_run: bool, ai_account: str, initial_cash_eur: float,
) -> str:
    """Steps a-f; fills ``details`` and returns the run stage, or raises ``_StageFailure``."""

    details["capture"] = _capture(root, clock)
    decision_session, is_new = _call("decision_session", lambda: _decision_session(root, clock))
    if not is_new:
        details["decision_session"] = decision_session.isoformat()
        return "no_new_session"
    completed_at = clock()  # t_S, read under the writer guard
    details["score_run"] = _call("score_run", lambda: _score_run(root, decision_session, completed_at))
    report, snapshot_id, run_id = _call("readiness", lambda: _validate_readiness(root, decision_session))
    try:
        record_feature_observations(root, decision_session, completed_at, run_id=run_id, snapshot_hash=snapshot_id)
        details["feature_vintage"] = {"status": "recorded"}
    except Exception as exc:  # SDD C9: logged, never blocks the run
        details["feature_vintage"] = {"status": "failed", "reason": redact_text(f"{type(exc).__name__}: {exc}")[:400]}
    details["readiness"] = {
        "status": "PASS" if report.passed else "FAIL",
        "decision_session": decision_session.isoformat(),
        "cadence_sessions": 1,
        "snapshot_id": snapshot_id,
        "run_id": run_id,
    }
    if not report.passed:
        raise _failure("readiness", report.format_text())
    if dry_run:
        return "dry_run"
    gate = _call("paper_gate", lambda: _paper_gate(root))
    details["paper_enabled"] = gate != "paper_disabled"
    if gate is not None:
        return gate
    cutoff = clock()
    engines, details["challengers"] = _call("challengers", lambda: build_challenger_engines(root, cutoff))
    recorded = _call(
        "paper_bots",
        lambda: run_paper_bots(
            cutoff, root=root, decision_session=decision_session, snapshot_hash=snapshot_id, challenger_engines=engines,
        ),
    )
    details["paper_bots"] = _check_recorder(recorded, snapshot_id)
    execution = _call("paper_bot_execution", lambda: run_paper_bot_execution(cutoff, root=root))
    if execution.status != "available":
        raise _failure("paper_bot_execution", execution.reason or "B0-B3 execution stage is unavailable.")
    details["paper_bot_execution"] = {
        "status": execution.status, "appended": execution.appended,
        "ledger_price_basis": LEDGER_PRICE_BASIS,
        "dividend_policy": "gross cash; no withholding or automatic reinvestment",
    }
    account = _call("ai_account", lambda: _open_ai_account(root, ai_account, initial_cash_eur))
    details["ai_account"] = {
        "account_id": account.account_id,
        "status": account.status,
        "base_currency": account.base_currency,
        "cash": account.cash,
        "event_count": account.event_count,
        "monthly_contribution_eur": 0,
    }
    return "complete"


__all__ = ["DailyPaperResult", "run_daily_paper"]
