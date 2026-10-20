"""Stage B of the paper bots: next-session paper execution through ``PaperLedger``.

Stage A freezes the monthly targets (``paper_bots.py``). This module turns each frozen decision into paper orders
that fill at the open of the first session strictly after the decision date, with the ``costs.py`` basis points, the
flat commission and the lot policy, through the same guarded ``PaperLedger`` order path the owner's paper account
uses. B0 is the cash-flow-matched VWCE shadow account of the ledger. A fill that cannot happen (no session data,
zero volume, a refused order, no settled cash) is stored as a ``missed`` record and its cash stays in the account, so
it affects wealth; nothing is hidden. Nothing here can place a real order: ``execution_allowed`` is false.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping

import pandas as pd
import yaml

from etf_cockpit.core.config import load_config
from etf_cockpit.core.paths import CONFIG_DIR, ROOT
from etf_cockpit.data.fx_data import build_fx_rate_snapshot, fx_cross_rate, load_fx_rates
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageSchemaError,
    TransactionalStore,
)
from etf_cockpit.data.provenance import metadata_from_frame
from etf_cockpit.portfolio import paper_bots as bots
from etf_cockpit.portfolio.benchmark_reference import (
    VwceReferenceSeriesCheck,
    validate_vwce_reference_series,
)
from etf_cockpit.portfolio.costs import estimate_execution_cost
from etf_cockpit.portfolio.paper_trading import (
    PaperLedger,
    PaperLedgerError,
    ShadowCostPolicy,
)
from etf_cockpit.portfolio.proposal_policy import (
    REQUIRED_GATES,
    GateEvidence,
    ProposalRequest,
    build_proposal_decision,
    current_authority_policy_checksum,
)
from etf_cockpit.signals.friction_edge import FrictionGateResult, evaluate_friction_gate

EXECUTION_CONFIG_PATH = CONFIG_DIR / "paper_bots_execution_v1.yaml"
FORWARD_PLAN_TYPE = "paper_bot_execution_plan"
FORWARD_RECORD_TYPE = "paper_bot_execution"
REPLAY_DECISION_TYPE = "paper_bot_replay_decision"
REPLAY_PLAN_TYPE = "paper_bot_replay_plan"
REPLAY_RECORD_TYPE = "paper_bot_replay_execution"
PRICE_FILE_RELATIVE = Path("data") / "validated" / "prices" / "prices_daily.parquet"
EXECUTION_ALLOWED = False
NETWORK_ACCESS_ALLOWED = False
_PENDING_SHADOW_MARKERS = ("No eligible benchmark session", "Benchmark execution close is unavailable")
_AVAILABLE_BUYING_POWER = re.compile(r"available buying power is ([0-9.]+)")
_MAX_WARNINGS = 12


@dataclass(frozen=True)
class Track:
    """Where one record stream lives. The replay track never shares a store, a ledger or an entity type with forward."""

    name: str
    label: str | None
    caveat: str | None
    store_root: Path
    ledger_root: Path
    decision_type: str
    plan_type: str
    record_type: str


def forward_track(root: Path) -> Track:
    return Track(
        "forward", None, None, root, root / "data" / "paper_bots" / "ledger",
        bots.DECISION_ENTITY_TYPE, FORWARD_PLAN_TYPE, FORWARD_RECORD_TYPE,
    )


def replay_track(root: Path, config: Mapping[str, Any]) -> Track:
    base = root / "data" / "paper_bots_replay"
    replay = config["replay"]
    return Track(
        "replay", str(replay["label"]), str(replay["caveat"]), base, base / "ledger",
        REPLAY_DECISION_TYPE, REPLAY_PLAN_TYPE, REPLAY_RECORD_TYPE,
    )


@dataclass(frozen=True)
class ExecutionRunResult:
    status: str
    track: str
    as_of: str | None
    records: tuple[dict[str, Any], ...] = ()
    appended: int = 0
    reason: str | None = None
    warnings: tuple[str, ...] = ()
    label: str | None = None


class PriceBook:
    """Point-in-time daily bars of every instrument; the benchmark calendar defines the sessions."""

    def __init__(self, frame: pd.DataFrame | None, *, known_at: datetime | None, benchmark_id: str = "VWCE", error: str | None = None) -> None:
        self.known_at = known_at.astimezone(timezone.utc) if isinstance(known_at, datetime) and known_at.tzinfo else None
        self.benchmark_id = benchmark_id
        self.error = error
        self._bars: dict[str, dict[date, dict[str, Any]]] = {}
        self._dates: dict[str, list[date]] = {}
        self._frame = pd.DataFrame()
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            self.error = self.error or "Price history is empty."
            return
        data = frame.copy()
        id_column = next((name for name in ("instrument_id", "etf_id") if name in data.columns), None)
        if id_column is None or not {"date", "close"}.issubset(data.columns):
            self.error = "Price history lacks the date, close or instrument columns."
            return
        data["_instrument"] = data[id_column].astype(str).str.strip().str.upper()
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        if getattr(data["date"].dt, "tz", None) is not None:
            data["date"] = data["date"].dt.tz_convert("UTC").dt.tz_localize(None)
        data["date"] = data["date"].dt.normalize()
        data = data.dropna(subset=["date"]).sort_values(["_instrument", "date"], kind="stable")
        if data.duplicated(["_instrument", "date"]).any():
            self.error = "Price history has duplicate instrument sessions."
            return
        self._frame = data.reset_index(drop=True)
        for instrument, group in self._frame.groupby("_instrument", sort=False):
            rows = {item["date"].date(): item for item in group.to_dict("records")}
            self._bars[str(instrument)] = rows
            self._dates[str(instrument)] = sorted(rows)

    @classmethod
    def from_root(cls, root: Path, *, benchmark_id: str = "VWCE") -> "PriceBook":
        path = Path(root) / PRICE_FILE_RELATIVE
        try:
            frame = pd.read_parquet(path)
            known_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except (OSError, ValueError) as exc:
            return cls(None, known_at=None, benchmark_id=benchmark_id, error=f"Price history unavailable: {type(exc).__name__}.")
        return cls(frame, known_at=known_at, benchmark_id=benchmark_id)

    @property
    def sessions(self) -> list[date]:
        return self._dates.get(self.benchmark_id.upper(), [])

    @property
    def usable(self) -> bool:
        return self.error is None and bool(self.sessions)

    def sessions_after(self, day: date) -> list[date]:
        sessions = self.sessions
        return sessions[bisect_right(sessions, day):]

    def first_session_on_or_after(self, day: date) -> date | None:
        sessions = self.sessions
        index = bisect_right(sessions, day - timedelta(days=1))
        return sessions[index] if index < len(sessions) else None

    def bar(self, instrument_id: str, day: date) -> dict[str, Any] | None:
        return self._bars.get(str(instrument_id).upper(), {}).get(day)

    def last_bar(self, instrument_id: str, day: date) -> dict[str, Any] | None:
        dates = self._dates.get(str(instrument_id).upper(), [])
        index = bisect_right(dates, day)
        return self._bars[str(instrument_id).upper()][dates[index - 1]] if index else None

    def benchmark_frame(self) -> pd.DataFrame:
        rows = self._frame.loc[self._frame["_instrument"] == self.benchmark_id.upper()] if not self._frame.empty else self._frame
        return rows.drop(columns=["_instrument"]).reset_index(drop=True)

    def benchmark_check(self, cutoff: datetime) -> tuple[pd.DataFrame, VwceReferenceSeriesCheck]:
        """The benchmark series as it was known at ``cutoff``: sessions from the cutoff day on are never used."""

        frame = self.benchmark_frame()
        if not frame.empty:
            frame = frame.loc[frame["date"].dt.date < cutoff.date()].reset_index(drop=True)
        known_at = None if self.known_at is None else min(self.known_at, cutoff)
        if self.error is not None or frame.empty or known_at is None:
            reason = self.error or "price_known_at_unavailable_or_no_session_before_the_cutoff"
            return frame, VwceReferenceSeriesCheck("unavailable", (reason,), None, None, len(frame), None, None)
        metadata = replace(
            metadata_from_frame(
                frame, source_name="yfinance", source_type="prices",
                as_of_date=frame["date"].max().date(), currency="EUR",
            ),
            ingested_at=known_at,
        )
        return frame, validate_vwce_reference_series(frame, known_at=known_at.isoformat(), provider_metadata=metadata)


def load_execution_config(path: Path | None = None) -> tuple[bytes, dict[str, Any]]:
    raw = Path(path or EXECUTION_CONFIG_PATH).read_bytes()
    payload = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "paper_bots_execution.v1":
        raise ValueError("unsupported paper bot execution specification")
    if payload.get("base_currency") != "EUR" or payload.get("fill_rule") != "next_session_open":
        raise ValueError("paper bots execute in EUR at the next session open only")
    for key in ("lot_size", "rebalance_tolerance_weight", "min_trade_value_eur", "max_buy_retry_sessions",
                "missed_fill_grace_calendar_days", "sizing_price_max_age_days", "max_stale_mark_sessions",
                "proposal_validity_days"):
        number = bots._finite_number(payload.get(key))
        if number is None or number < 0 or (key in {"lot_size", "proposal_validity_days"} and number <= 0):
            raise ValueError(f"invalid paper bot execution setting: {key}")
        payload[key] = number
    for key in ("rule_expected_benefit_bps", "rule_uncertainty_bps"):
        number = bots._finite_number(payload.get(key))  # an absent benefit stays None: every order then fails closed
        if payload.get(key) is not None and (number is None or number < 0):
            raise ValueError(f"invalid paper bot execution setting: {key}")
        payload[key] = number
    hour, _, minute = str(payload.get("fill_time_utc", "")).partition(":")
    payload["_fill_time"] = time(int(hour), int(minute))
    for key in ("cost_model", "uncertainty", "replay"):
        if not isinstance(payload.get(key), dict):
            raise ValueError(f"paper bot execution section is missing: {key}")
    if not isinstance(payload.get("paper_approvals"), list) or not payload["paper_approvals"]:
        raise ValueError("paper bot execution needs its paper approvals")
    return raw, payload


def _cost_policy(root: Path, config: Mapping[str, Any]) -> tuple[ShadowCostPolicy, dict[str, Any], tuple[str, ...], Any]:
    """Derive the account-wide commission and adverse basis points from ``configs/costs.yaml`` (costs.py model)."""

    config_dir = root / "configs" if (root / "configs" / "costs.yaml").is_file() else CONFIG_DIR
    app_config = load_config(config_dir)
    model = config["cost_model"]
    order_value = float(model["reference_order_value_eur"])
    base = estimate_execution_cost(app_config, str(model["reference_instrument"]), order_value, session="continuous")
    session = estimate_execution_cost(app_config, str(model["reference_instrument"]), order_value, session=str(model["session"]))
    fixed_bps = base.commission_eur / order_value * 10_000.0
    base_variable = base.total_cost_bps - fixed_bps
    session_variable = session.total_cost_bps - session.commission_eur / order_value * 10_000.0
    multiplier = session_variable / base_variable if base_variable > 0 else 1.0
    adverse = (base.spread_bps + base.slippage_bps + base.fx_bps + base.gap_bps) * multiplier
    policy = ShadowCostPolicy(
        commission=Decimal(str(round(base.commission_eur, 8))),
        adverse_bps=Decimal(str(round(adverse, 8))),
        lot_size=Decimal(str(config["lot_size"])),
    )
    evidence = {
        "model_id": base.model_id,
        "cost_policy": policy.to_payload(),
        "cost_policy_digest": policy.digest(),
        "spread_bps": base.spread_bps,
        "slippage_bps": base.slippage_bps,
        "fx_bps": base.fx_bps,
        "gap_bps": base.gap_bps,
        "session_multiplier": round(multiplier, 8),
        "market_impact_excluded": "no order-size or volume input exists for a paper bot; a retail-size order has none",
    }
    return policy, evidence, tuple(sorted(app_config.universe.by_id())), app_config


def _ensure_limits(track: Track, root: Path, universe_ids: tuple[str, ...]) -> None:
    """Give the bot ledger root its own pre-trade limits: the owner's numeric limits, the configured universe allowlist.

    A digest of the universe and the source limits sits beside the file: when either changes (an instrument was added to
    the universe, the owner edited a limit) the file is rewritten, so the allowlist never freezes at first creation. A file
    without a digest (written before it existed) is adopted as it is and refreshed on the next change.
    """

    target = track.ledger_root / "configs" / "pre_trade_limits_v1.yaml"
    marker = target.with_name("pre_trade_limits_v1.source-digest")
    local = root / "configs" / "pre_trade_limits_v1.yaml"
    source = local if local.is_file() else CONFIG_DIR / "pre_trade_limits_v1.yaml"
    source_bytes = source.read_bytes()
    digest = hashlib.sha256(
        json.dumps({"universe": sorted(item.upper() for item in universe_ids), "limits": hashlib.sha256(source_bytes).hexdigest()}).encode("utf-8")
    ).hexdigest()
    if target.is_file():
        if not marker.is_file():
            marker.write_text(digest, encoding="utf-8")
            return
        if marker.read_text(encoding="utf-8").strip() == digest:
            return
    limits = yaml.safe_load(source_bytes.decode("utf-8"))
    if not isinstance(limits, dict) or limits.get("schema_version") != "pre_trade_limits.v1":
        raise ValueError("pre-trade limits are unavailable for the paper bots")
    limits["allowed_instruments"] = sorted({*(item.upper() for item in universe_ids), "VWCE"})
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(limits, sort_keys=True), encoding="utf-8")
    marker.write_text(digest, encoding="utf-8")


def run_paper_bot_execution(
    as_of: datetime | date | str,
    *,
    root: Path | None = None,
    config_path: Path | None = None,
    execution_config_path: Path | None = None,
    price_book: PriceBook | None = None,
    now: datetime | None = None,
) -> ExecutionRunResult:
    """Execute every forward decision known at ``as_of`` whose next session has completed."""

    project_root = Path(root or ROOT).resolve()
    try:
        cutoff = bots._as_of_timestamp(as_of)
    except (TypeError, ValueError) as exc:
        return ExecutionRunResult("unavailable", "forward", None, reason=f"Invalid as_of: {exc}")
    clock = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    if cutoff > clock + timedelta(minutes=5):
        return ExecutionRunResult("unavailable", "forward", bots._time_text(cutoff), reason="as_of is in the future.")
    return _run(forward_track(project_root), project_root, cutoff, config_path, execution_config_path, price_book, None)


def _run(
    track: Track,
    root: Path,
    cutoff: datetime,
    config_path: Path | None,
    execution_config_path: Path | None,
    price_book: PriceBook | None,
    prepare: Callable[[TransactionalStore, Mapping[str, Any], str, PriceBook, list[str]], None] | None,
) -> ExecutionRunResult:
    as_of_text = bots._time_text(cutoff)
    try:
        bots_bytes, bots_config = bots._load_config(Path(config_path or _config_file(root, "paper_bots_v1.yaml", bots.PAPER_BOTS_CONFIG_PATH)))
        exec_bytes, config = load_execution_config(
            execution_config_path or _config_file(root, "paper_bots_execution_v1.yaml", EXECUTION_CONFIG_PATH)
        )
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        return ExecutionRunResult("unavailable", track.name, as_of_text, reason=f"Bot specification unavailable: {type(exc).__name__}.", label=track.label)
    config_hash = hashlib.sha256(bots_bytes).hexdigest()
    exec_hash = hashlib.sha256(exec_bytes).hexdigest()
    book = price_book if price_book is not None else PriceBook.from_root(root, benchmark_id=str(bots_config["benchmark"]["instrument_id"]))
    if not book.usable:
        return ExecutionRunResult("unavailable", track.name, as_of_text, reason=book.error or "No benchmark sessions are available.", label=track.label)
    try:
        policy, policy_evidence, universe_ids, app_config = _cost_policy(root, config)
        _ensure_limits(track, root, universe_ids)
    except Exception as exc:  # fail closed: costs, universe or limits unreadable
        return ExecutionRunResult("unavailable", track.name, as_of_text, reason=f"Cost model unavailable: {type(exc).__name__}.", label=track.label)

    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    appended = 0
    try:
        with TransactionalStore(track.store_root) as store:
            if prepare is not None:
                prepare(store, bots_config, config_hash, book, warnings)
            decisions = _load_decisions(store, track, cutoff, warnings)
            frame, check = book.benchmark_check(cutoff)
            context = _Context(
                track, root, cutoff, config, bots_config, config_hash, exec_hash, book, policy, policy_evidence, store, frame, check, warnings,
                app_config,
            )
            for bot_id, items in sorted(decisions.items()):
                try:
                    new_records = _execute_bot(context, bot_id, items)
                except (PaperLedgerError, OSError, ValueError, KeyError) as exc:
                    warnings.append(f"Bot {bot_id[:12]} execution stopped: {type(exc).__name__}: {str(exc)[:160]}")
                    continue
                appended += len(new_records)
                records.extend(new_records)
            for bot_id in sorted(decisions):
                _sync_shadow(context, bot_id)
    except (OSError, ValueError, KeyError, StorageSchemaError, StorageRevisionConflict) as exc:
        return ExecutionRunResult("unavailable", track.name, as_of_text, reason=f"Paper bot execution unavailable: {type(exc).__name__}.", warnings=tuple(warnings), label=track.label)
    if len(warnings) > _MAX_WARNINGS:
        warnings = [*warnings[:_MAX_WARNINGS], f"{len(warnings) - _MAX_WARNINGS} further warnings omitted."]
    status = "available" if decisions and not warnings else "partial" if decisions else "unavailable"
    reason = None if status == "available" else (
        "No decision is known at as_of." if not decisions else "Some bot executions reported warnings."
    )
    return ExecutionRunResult(status, track.name, as_of_text, tuple(records), appended, reason, tuple(warnings), track.label)


def _config_file(root: Path, name: str, packaged: Path) -> Path:
    local = root / "configs" / name
    return local if local.is_file() else packaged


@dataclass
class _Context:
    track: Track
    root: Path
    cutoff: datetime
    config: Mapping[str, Any]
    bots_config: Mapping[str, Any]
    config_hash: str
    exec_hash: str
    book: PriceBook
    policy: ShadowCostPolicy
    policy_evidence: Mapping[str, Any]
    store: TransactionalStore
    benchmark_frame: pd.DataFrame
    benchmark_check: VwceReferenceSeriesCheck
    warnings: list[str]
    app_config: Any
    by_intent: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    fx_cache: dict[Any, float | None] = field(default_factory=dict)


def _load_decisions(
    store: TransactionalStore, track: Track, cutoff: datetime, warnings: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Stage A decisions known at ``cutoff``; anything malformed or newer is ignored (never executed)."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    skipped = 0
    for record in store.list(track.decision_type):
        payload = dict(record.payload)
        if payload.get("status") != "available":
            continue
        known_at = bots._parse_timestamp(payload.get("known_at"))
        decided_at = bots._parse_timestamp(payload.get("as_of"))
        if known_at is None or decided_at is None or known_at > cutoff or decided_at > cutoff:
            continue
        targets = payload.get("targets")
        weights = [bots._finite_number(value) for value in targets.values()] if isinstance(targets, Mapping) else []
        if (
            payload.get("schema_version") != "paper_bot_decision.v1"
            or payload.get("execution_allowed") is not False
            or payload.get("authority_stage") != "paper"
            or not isinstance(payload.get("bot_id"), str)
            or not isinstance(payload.get("decision_id"), str)
            or not weights
            or any(value is None or value < 0 for value in weights)
            or not math.isclose(sum(value for value in weights if value is not None), 1.0, abs_tol=1e-9)
            or not isinstance(payload.get("prices_used"), Mapping)
        ):
            skipped += 1
            continue
        payload["_decided_at"] = decided_at
        payload["_known_at"] = known_at
        grouped.setdefault(str(payload["bot_id"]), []).append(payload)
    if skipped:
        warnings.append(f"Ignored {skipped} malformed stage A decision records.")
    for items in grouped.values():
        items.sort(key=lambda item: (item["_decided_at"], item["decision_id"]))
    return grouped


def account_id_for(bot_id: str) -> str:
    family, _, digest = str(bot_id).rpartition("-")
    return f"{family}-{digest[:20]}"


def shadow_id_for(bot_id: str) -> str:
    return f"{account_id_for(bot_id)}-vwce"


def _record_id(*parts: str) -> str:
    return bots._sha256_json({"parts": list(parts)})


def _fill_datetime(config: Mapping[str, Any], session: date) -> datetime:
    return datetime.combine(session, config["_fill_time"], tzinfo=timezone.utc)


def _floor_lot(quantity: Decimal, lot: Decimal) -> Decimal:
    return (quantity / lot).to_integral_value(rounding=ROUND_FLOOR) * lot


def _eur_per_unit(context: _Context, currency: str, when: datetime) -> float | None:
    """EUR per unit of ``currency`` known at ``when`` through the canonical FX path; ``None`` when no rate is available."""

    code = currency.upper()
    if code == "EUR":
        return 1.0
    key = (code, when.isoformat())
    if key not in context.fx_cache:
        rate = None
        try:
            if "frame" not in context.fx_cache:
                context.fx_cache["frame"] = load_fx_rates(context.root / "data" / "clean" / "fx.parquet")
            cross = fx_cross_rate(build_fx_rate_snapshot(context.fx_cache["frame"], decision_time=when, known_at=when), code, "EUR")
            if cross is not None and math.isfinite(cross.rate) and cross.rate > 0:
                rate = float(cross.rate)
        except (OSError, ValueError, KeyError):
            rate = None
        context.fx_cache[key] = rate
    return context.fx_cache[key]


def _quote_currency(context: _Context, decision: Mapping[str, Any], instrument_id: str, price_date: str | None) -> str | None:
    """The currency the decision captured for the instrument, else its sizing bar's; never assumed."""

    captured = decision["prices_used"].get(instrument_id)
    text = bots._real_text(captured.get("currency")) if isinstance(captured, Mapping) else None
    if text is None and price_date is not None:
        bar = context.book.bar(instrument_id, date.fromisoformat(price_date))
        text = bots._real_text(bar.get("currency")) if bar else None
    return None if text is None else text.upper()


def _execute_bot(context: _Context, bot_id: str, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledger = PaperLedger(context.track.ledger_root, account_id=account_id_for(bot_id))
    written: list[dict[str, Any]] = []
    for decision in decisions:
        decision_date = decision["_decided_at"].date()
        usable = [day for day in context.book.sessions_after(decision_date) if day < context.cutoff.date()]
        entry = context.book.first_session_on_or_after(decision_date)
        if not usable or entry is None:
            outage = (context.cutoff.date() - decision_date).days > int(context.config["missed_fill_grace_calendar_days"])
            if outage and decision.get("strategy") != "benchmark" and entry is not None:
                written.extend(_miss_unplanned(context, ledger, decision, "provider_outage_no_session_data_after_grace"))
            break
        _fund(context, ledger, decision, entry, initial=decision is decisions[0])
        if decision.get("strategy") == "benchmark":
            continue  # B0 trades through its cash-flow-matched shadow account
        plan = _plan(context, ledger, decision, decision_date)
        written.extend(_run_intents(context, ledger, decision, plan, usable))
    return written


def _fund(context: _Context, ledger: PaperLedger, decision: Mapping[str, Any], entry: date, *, initial: bool) -> None:
    amount = float(decision["initial_virtual_cash_eur"] if initial else decision["monthly_contribution_eur"])
    flow_at = datetime.combine(entry, time(0, 0), tzinfo=timezone.utc)
    ledger.open_account(initial_cash=0, cost_policy=context.policy, occurred_at=flow_at - timedelta(minutes=1))
    if amount <= 0:
        return
    flow_id = f"{ledger.account_id}:{'initial' if initial else decision['decision_month']}"
    ledger.record_external_flow(
        flow_id=flow_id, kind="contribution", amount=Decimal(str(amount)), flow_at=flow_at,
        source_authority="paper_bots_config", source_checksum=context.config_hash,
    )


def _sizing_price(context: _Context, decision: Mapping[str, Any], instrument_id: str, decision_date: date) -> tuple[Decimal, str] | None:
    """Last close known at the decision's ``known_at``: the captured price or a bar dated strictly before the decision day.

    The decision day's own close is not known when the decision is made, so the fallback never uses it.
    """

    captured = decision["prices_used"].get(instrument_id)
    if isinstance(captured, Mapping) and bots._finite_number(captured.get("price")) and captured.get("price_as_of"):
        return Decimal(str(captured["price"])), str(captured["price_as_of"])
    bar = context.book.last_bar(instrument_id, decision_date - timedelta(days=1))
    if bar is None:
        return None
    day = bar["date"].date()
    if (decision_date - day).days > int(context.config["sizing_price_max_age_days"]):
        return None
    close = bots._finite_number(bar.get("close"))
    return (Decimal(str(close)), day.isoformat()) if close and close > 0 else None


def _plan(context: _Context, ledger: PaperLedger, decision: Mapping[str, Any], decision_date: date) -> dict[str, Any]:
    plan_id = str(decision["decision_id"])
    existing = context.store.get(context.track.plan_type, plan_id)
    if existing is not None:
        return dict(existing.payload)
    policy = context.policy
    adverse = policy.adverse_bps / Decimal(10000)
    snapshot = ledger.snapshot()
    held = {item.instrument_id: Decimal(str(item.quantity)) for item in snapshot.positions if item.quantity > 0}
    cash = ledger.cash_balance(account_id=ledger.account_id, currency="EUR", as_of=context.cutoff)
    targets = {key: Decimal(str(value)) for key, value in decision["targets"].items() if key != "cash_weight"}
    prices: dict[str, tuple[Decimal, str] | None] = {
        instrument: _sizing_price(context, decision, instrument, decision_date) for instrument in {*held, *targets}
    }
    unusable: dict[str, str] = {}  # priced instruments whose currency or EUR rate is unknown: never sized on a guess
    quoted: dict[str, tuple[str, float]] = {}
    for instrument, entry in prices.items():
        if entry is None:
            continue
        currency = _quote_currency(context, decision, instrument, entry[1])
        rate = None if currency is None else _eur_per_unit(context, currency, decision["_known_at"])
        if currency is None or rate is None:
            unusable[instrument] = "currency_unavailable" if currency is None else "fx_unavailable"
        else:
            quoted[instrument] = (currency, rate)
    unpriced_held = sorted(instrument for instrument in held if prices[instrument] is None or instrument in unusable)
    reasons = {item["instrument_id"]: item["reason"] for item in decision.get("skipped_instruments", [])}
    plan: dict[str, Any] = {
        "schema_version": "paper_bot_execution_plan.v1", "plan_id": plan_id, "bot_id": decision["bot_id"],
        "decision_id": plan_id, "snapshot_hash": decision.get("snapshot_hash"), "decision_known_at": decision["known_at"],
        "decision_date": decision_date.isoformat(), "exec_config_hash": context.exec_hash,
        "cost": dict(context.policy_evidence), "cash_before": str(cash), "held_before": {k: str(v) for k, v in held.items()},
        "status": "planned", "intents": [], "within_tolerance": [], "execution_allowed": False,
    }
    if unpriced_held:
        plan["status"] = "unavailable"
        plan["reason"] = "No decision-time price for held instruments: " + ", ".join(unpriced_held)
        context.store.put_many([(context.track.plan_type, plan_id, plan)], immutable=True)
        return plan
    eur_prices = {
        instrument: entry[0] if quoted[instrument][0] == "EUR" else entry[0] * Decimal(str(quoted[instrument][1]))
        for instrument, entry in prices.items() if entry is not None and instrument in quoted
    }
    value = cash + sum((held[i] * eur_prices[i] for i in held), Decimal("0"))
    threshold = max(Decimal(str(context.config["min_trade_value_eur"])), Decimal(str(context.config["rebalance_tolerance_weight"])) * value)
    lot = policy.lot_size
    buys: list[dict[str, Any]] = []
    sells: list[dict[str, Any]] = []
    for instrument in sorted({*held, *targets}):
        weight = targets.get(instrument, Decimal("0"))
        price_entry = prices[instrument]
        have = held.get(instrument, Decimal("0"))
        if price_entry is None:
            buys.append(_intent(decision, instrument, "buy", Decimal("0"), weight, None, None, "no_decision_time_price"))
            continue
        if instrument in unusable:
            buys.append(_intent(decision, instrument, "buy", Decimal("0"), weight, None, None, unusable[instrument]))
            continue
        price = eur_prices[instrument]
        currency, rate = quoted[instrument]
        target_quantity = _floor_lot(weight * value / (price * (1 + adverse)), lot) if weight > 0 else Decimal("0")
        delta = target_quantity - have
        if delta == 0:
            continue
        exits = instrument not in targets
        if abs(delta) * price < threshold and not (exits and delta < 0):
            plan["within_tolerance"].append({"instrument_id": instrument, "delta_quantity": str(delta), "reason": "within_rebalance_tolerance"})
            continue
        if delta > 0:
            reason = (
                f"enter target weight {float(weight):.1%}" if have == 0 else f"increase to target weight {float(weight):.1%}"
            ) + f" ({decision['bot_family']}, decision {str(decision['snapshot_hash'])[:8]})"
            buys.append(_intent(decision, instrument, "buy", delta, weight, price_entry, currency, reason, rate))
        else:
            skipped_reason = reasons.get(instrument)
            reason = (
                f"exit: not in the target set ({skipped_reason})" if exits and skipped_reason
                else "exit: not in the target set" if exits
                else f"trim to target weight {float(weight):.1%}"
            ) + f" ({decision['bot_family']}, decision {str(decision['snapshot_hash'])[:8]})"
            sells.append(_intent(decision, instrument, "sell", -delta, weight, price_entry, currency, reason, rate))
    buys.sort(key=lambda item: (-float(item["target_weight"]), item["instrument_id"]))
    plan["intents"] = [*sells, *buys]
    plan["portfolio_value_before"] = str(value)
    context.store.put_many([(context.track.plan_type, plan_id, plan)], immutable=True)
    return plan


def _intent(
    decision: Mapping[str, Any], instrument: str, side: str, quantity: Decimal, weight: Decimal,
    price: tuple[Decimal, str] | None, currency: str | None, reason: str, fx_rate: float | None = None,
) -> dict[str, Any]:
    return {
        "intent_id": _record_id(str(decision["decision_id"]), instrument, side),
        "instrument_id": instrument, "side": side, "planned_quantity": str(quantity), "target_weight": str(weight),
        "sizing_price": None if price is None else str(price[0]), "sizing_price_date": None if price is None else price[1],
        "currency": currency, "sizing_fx_rate": fx_rate, "reason": reason,
        "unavailable_reason": reason if price is None else None,
    }


def _intent_records(context: _Context, intent_id: str) -> list[dict[str, Any]]:
    if not context.by_intent:
        for item in context.store.list(context.track.record_type):
            context.by_intent.setdefault(str(item.payload.get("intent_id")), []).append(dict(item.payload))
        context.by_intent.setdefault("", [])  # marks the index as loaded
    return context.by_intent.get(intent_id, [])


def _store_record(context: _Context, record: dict[str, Any]) -> None:
    _intent_records(context, str(record["intent_id"]))
    context.store.put_many([(context.track.record_type, record["record_id"], record)], immutable=True)
    context.by_intent.setdefault(str(record["intent_id"]), []).append(record)


def _run_intents(
    context: _Context, ledger: PaperLedger, decision: Mapping[str, Any], plan: Mapping[str, Any], usable: list[date]
) -> list[dict[str, Any]]:
    if plan.get("status") != "planned":
        return _miss_unplanned(context, ledger, decision, str(plan.get("reason") or "plan_unavailable"))
    retries = int(context.config["max_buy_retry_sessions"])
    state: dict[str, dict[str, Any]] = {}
    for intent in plan["intents"]:
        history = _intent_records(context, intent["intent_id"])
        final = next((item for item in history if item["status"] in {"filled", "missed"}), None)
        state[intent["intent_id"]] = {"intent": intent, "final": final, "attempts": sorted(item["session"] for item in history if item["status"] == "deferred")}
    written: list[dict[str, Any]] = []
    for index, session in enumerate(usable[: retries + 1]):
        for entry in state.values():
            intent = entry["intent"]
            if entry["final"] is not None or session.isoformat() in entry["attempts"]:
                continue
            if intent["side"] == "sell" and index > 0:
                continue
            final_session = index == retries
            record = _attempt(
                context, ledger, decision, intent, session, final_session=final_session,
                awaits_settlement=any(item['side'] == 'sell' for item in plan['intents']),
            )
            written.append(record)
            _store_record(context, record)
            if record["status"] == "deferred":
                entry["attempts"].append(record["session"])
            else:
                entry["final"] = record
    return written


def _miss_unplanned(context: _Context, ledger: PaperLedger, decision: Mapping[str, Any], reason: str) -> list[dict[str, Any]]:
    """Log every target of a decision as missed when it cannot even be planned (outage, no sizing price)."""

    written = []
    for instrument, weight in sorted(decision["targets"].items()):
        if instrument == "cash_weight":
            continue
        intent_id = _record_id(str(decision["decision_id"]), instrument, "buy")
        if _intent_records(context, intent_id):
            continue
        intent = {"intent_id": intent_id, "instrument_id": instrument, "side": "buy", "planned_quantity": "0",
                  "target_weight": str(weight), "sizing_price": None, "sizing_price_date": None,
                  "currency": _quote_currency(context, decision, instrument, None),
                  "reason": f"target weight {float(weight):.1%} ({decision['bot_family']})"}
        record = _record(context, decision, intent, None, "missed", reason)
        _store_record(context, record)
        written.append(record)
    return written


def _record(
    context: _Context, decision: Mapping[str, Any], intent: Mapping[str, Any], session: date | None, status: str, reason: str | None,
    **fields: Any,
) -> dict[str, Any]:
    record = {
        "schema_version": "paper_bot_execution.v1",
        "record_id": _record_id(str(intent["intent_id"]), session.isoformat() if session else "none", status),
        "intent_id": intent["intent_id"], "track": context.track.name, "label": context.track.label,
        "bot_id": decision["bot_id"], "bot_family": decision["bot_family"], "decision_id": decision["decision_id"],
        "decision_month": decision["decision_month"], "snapshot_hash": decision.get("snapshot_hash"),
        "instrument_id": intent["instrument_id"], "side": intent["side"], "planned_quantity": intent["planned_quantity"],
        "target_weight": intent["target_weight"], "trade_reason": intent["reason"],
        "session": None if session is None else session.isoformat(), "status": status, "reason": reason,
        "quantity": "0", "reference_open": None, "fill_price": None, "fee": "0", "spread_slippage_cost": "0",
        "fill_id": None, "order_id": None, "exec_config_hash": context.exec_hash, "execution_allowed": False,
    }
    record.update(fields)
    return record


def _rule_friction_gate(context: _Context, instrument_id: str, order_value_eur: Decimal) -> FrictionGateResult:
    """The friction gate of a frozen-rule order: the modelled cost of this order against the rule's expected benefit.

    The benefit is the explicit ``rule_expected_benefit_bps`` assumption of the execution config; without it the gate
    fails closed (``benefit_unavailable``) and no paper order is placed. The cost is ``costs.py`` at the order's size.
    """

    def unavailable(reason: str) -> FrictionGateResult:
        return FrictionGateResult("unavailable", False, None, None, None, None, None, None, reason)

    benefit = context.config.get("rule_expected_benefit_bps")
    if benefit is None:
        return unavailable("benefit_unavailable: the execution config states no expected benefit for the frozen rule.")
    order_value = float(order_value_eur)
    model = context.config["cost_model"]
    try:
        estimate = estimate_execution_cost(context.app_config, instrument_id, order_value, session=str(model["session"]))
    except Exception as exc:  # fail closed: no cost estimate, no gate
        return unavailable(f"cost_estimate_unavailable: {type(exc).__name__}")
    return evaluate_friction_gate(
        float(benefit), order_value_eur=order_value,
        cost_estimate={"order_value_eur": estimate.order_value_eur, "total_cost_bps": estimate.total_cost_bps, "spread_bps": estimate.spread_bps},
        uncertainty_bps=context.config.get("rule_uncertainty_bps") or 0.0,
    )


def _proposal(
    context: _Context, ledger: PaperLedger, decision: Mapping[str, Any], intent: Mapping[str, Any],
    held: Decimal, quantity: Decimal, session: date, *, friction: FrictionGateResult, bar: Mapping[str, Any], unit_price: Decimal,
) -> dict[str, object]:
    config = context.config
    decided_at: datetime = decision["_decided_at"]
    sign = 1 if intent["side"] == "buy" else -1
    note = f"{intent['reason']}; session {session.isoformat()}"
    fill_time = _fill_datetime(config, session)
    volume, opening = bots._finite_number(bar.get("volume")), bots._finite_number(bar.get("open"))
    after = held + sign * quantity
    exposure_limit = _limit(context, "max_position_exposure")
    exposure = after * unit_price
    policy = context.policy
    checks: dict[str, tuple[bool, str]] = {
        "optimizer_output": (
            decision.get("status") == "available" and decision.get("execution_allowed") is False and bool(decision.get("decision_id")),
            f"Frozen stage A decision {decision['decision_id'][:12]}.",
        ),
        "portfolio_state": (
            held >= 0 and after >= 0, f"Paper ledger {ledger.account_id} replayed before the order: holds {held}, holds {after} after it.",
        ),
        "data_freshness": (
            bool(decision.get("snapshot_hash")) and decision["_known_at"] <= fill_time and session > decided_at.date(),
            f"Published snapshot {str(decision.get('snapshot_hash'))[:12]} was known before the fill session {session.isoformat()}.",
        ),
        "model_confidence": (
            decision.get("strategy") == "benchmark" or bool(decision.get("score_lineage_hash")),
            "Deterministic rule pinned to its score lineage; no model forecast is used.",
        ),
        "liquidity": (
            volume is not None and volume > 0 and opening is not None and opening > 0,
            f"Session {session.isoformat()} traded a positive volume with a finite open.",
        ),
        "cost": (
            friction.required_bps is not None and math.isfinite(friction.required_bps) and policy.commission >= 0 and policy.adverse_bps >= 0,
            f"Commission and adverse basis points follow {context.policy_evidence['model_id']} ({policy.digest()[:12]}); "
            f"modelled order cost {friction.required_bps} bps.",
        ),
        "concentration": (
            exposure_limit is not None and exposure <= exposure_limit,
            f"Position after the order is {exposure:.2f} EUR against the limit {exposure_limit}.",
        ),
        "account_authority": (
            EXECUTION_ALLOWED is False and decision.get("authority_stage") == "paper" and bool(config["paper_approvals"]),
            "Local paper simulation under strategy:paper_portfolio; execution_allowed=false.",
        ),
    }
    request = ProposalRequest(
        instrument_id=str(intent["instrument_id"]), current_quantity=float(held), target_quantity=float(held + sign * quantity),
        strategy_id=str(config["strategy_id"]), strategy_stage="paper", model_id=str(config["model_id"]), model_stage="paper",
        account_id=str(config["account_capability"]), account_stage="paper",
        optimiser_output_id=str(decision["decision_id"]), portfolio_revision=f"{ledger.account_id}:{intent['intent_id']}:{session.isoformat()}",
        data_revision=str(decision.get("snapshot_hash")), as_of=decided_at,
        expires_at=decided_at + timedelta(days=float(config["proposal_validity_days"])),
        authority_policy_checksum=current_authority_policy_checksum(),
        gate_evidence=tuple(GateEvidence(gate, bool(checks[gate][0]), checks[gate][1]) for gate in REQUIRED_GATES),
        rationale=note, approvals=tuple(str(item) for item in config["paper_approvals"]),
        event_calendar_path=context.root / "data" / "clean" / "event_calendar.parquet",
        friction_gate=friction,
    )
    return build_proposal_decision(request).to_payload()


def _attempt(
    context: _Context, ledger: PaperLedger, decision: Mapping[str, Any], intent: Mapping[str, Any], session: date, *,
    final_session: bool, awaits_settlement: bool,
) -> dict[str, Any]:
    """One session's try at one planned order: a fill, a retryable deferral, or a final miss.

    The ledger and the record store are separate systems: the ledger fill is the source of truth, so a fill that
    exists without its record is rebuilt into the record and never ordered again.
    """

    def miss(reason: str) -> dict[str, Any]:
        return _record(context, decision, intent, session, "missed", reason)

    instrument = str(intent["instrument_id"])
    # One fill per intent and session: the ID is deterministic so a rerun after a lost store write finds the fill.
    fill_id = "botfill_" + _record_id(str(intent["intent_id"]), session.isoformat())[:20]
    recorded = next((row for row in ledger.trade_rows() if row["paper_trade_id"] == fill_id), None)
    if recorded is not None:
        return _recovered_fill(context, ledger, decision, intent, session, recorded)
    if intent["sizing_price"] is None:
        return miss(intent.get("unavailable_reason") or "no_decision_time_price")
    currency = bots._real_text(intent.get("currency"))
    if currency is None:
        return miss("currency_unavailable")
    currency = currency.upper()
    fill_time = _fill_datetime(context.config, session)
    fx = _eur_per_unit(context, currency, fill_time)
    if fx is None:
        return miss(f"fx_unavailable: no {currency}/EUR rate known at {fill_time.isoformat()}")
    ledger_fx = None if currency == "EUR" else fx  # EUR keeps the ledger's implicit unit rate
    to_eur = Decimal(1) if currency == "EUR" else Decimal(str(fx))
    bar = context.book.bar(instrument, session)
    if bar is None:
        return miss(f"no_session_data: provider outage, halt or missing bar on {session.isoformat()}")
    volume = bots._finite_number(bar.get("volume"))
    if volume is None or volume <= 0:
        return miss(f"zero_volume_session on {session.isoformat()}")
    opening = bots._finite_number(bar.get("open"))
    if opening is None or opening <= 0:
        return miss(f"invalid_open_price on {session.isoformat()}")
    bar_currency = bots._real_text(bar.get("currency"))
    if bar_currency is not None and bar_currency.upper() != currency:
        return miss(f"currency_mismatch: the session bar is quoted in {bar_currency}, the order in {currency}")

    policy = context.policy
    adverse = policy.adverse_bps / Decimal(10000)
    reference = Decimal(str(opening))
    side = str(intent["side"])
    price = reference * (1 + adverse if side == "buy" else 1 - adverse)
    held = next((Decimal(str(item.quantity)) for item in ledger.snapshot().positions if item.instrument_id == instrument), Decimal("0"))
    quantity = Decimal(str(intent["planned_quantity"]))
    if side == "sell":
        quantity = min(quantity, held)
        if quantity < policy.lot_size:
            return miss("position_not_held")
    unit = price * to_eur  # EUR per unit
    capped = False
    order_limit = _limit(context, "max_order_value")
    if order_limit is not None and quantity * unit > order_limit:  # the owner's hard limit: trade what fits, never breach it
        quantity = _floor_lot(order_limit / unit, policy.lot_size)
        capped = True
        if quantity < policy.lot_size:
            return miss("order_value_limit_below_one_lot")
    for tries in range(2):
        friction = _rule_friction_gate(context, instrument, quantity * unit)
        if not friction.propose:
            return miss(friction.reason if friction.status == "unavailable" else f"friction_gate_blocked: {friction.reason}")
        proposal = _proposal(context, ledger, decision, intent, held, quantity, session, friction=friction, bar=bar, unit_price=unit)
        if proposal.get("proposal_allowed") is not True:
            return miss(f"proposal_policy_refused: {str(proposal.get('rationale'))[:200]}")
        order_id = None
        try:
            order = ledger.auto_paper_proposal(
                proposal, execution_price=price, fee=policy.commission, occurred_at=fill_time,
                quote_currency=currency, fx_rate=ledger_fx, expiry_reference=fill_time,
            )
            order_id = str(order["order_id"])
            ledger.record_fill(
                order_id, fill_id=fill_id, quantity=quantity, price=price, fee=policy.commission,
                reference_price=reference, fx_rate=ledger_fx, occurred_at=fill_time,
            )
        except PaperLedgerError as exc:
            message = str(exc)
            if order_id is not None:
                try:
                    ledger.cancel_order(order_id, reason="paper bot fill failed", occurred_at=fill_time)
                except PaperLedgerError:
                    pass
            shortfall = _AVAILABLE_BUYING_POWER.search(message)
            if side == "buy" and shortfall is not None:
                if awaits_settlement and not final_session:
                    return _record(context, decision, intent, session, "deferred", "waiting for settled cash: " + message[:160])
                affordable = _floor_lot((Decimal(shortfall.group(1)) - policy.commission) / unit, policy.lot_size)
                if tries == 0 and affordable >= policy.lot_size and affordable < quantity:
                    quantity = affordable
                    continue
                return miss("insufficient_settled_cash after the retry sessions")
            return miss("ledger_refused: " + message[:200])
        cost = quantity * abs(price - reference) * to_eur
        return _record(
            context, decision, intent, session, "filled", intent["reason"] if quantity == Decimal(str(intent["planned_quantity"]))
            else f"{intent['reason']}; reduced to the order-value limit" if capped and quantity == _floor_lot(order_limit / unit, policy.lot_size)
            else f"{intent['reason']}; reduced to settled cash",
            quantity=str(quantity), reference_open=str(reference), fill_price=str(price), fee=str(policy.commission),
            spread_slippage_cost=str(cost), fill_id=fill_id, order_id=order_id,
            planned_quantity=str(intent["planned_quantity"]),
        )
    return miss("insufficient_settled_cash after the retry sessions")


def _recovered_fill(
    context: _Context, ledger: PaperLedger, decision: Mapping[str, Any], intent: Mapping[str, Any], session: date, row: Mapping[str, Any],
) -> dict[str, Any]:
    """The ``filled`` record of a fill the ledger already holds (its record write was lost)."""

    quantity, price, fee = (Decimal(str(row[key])) for key in ("quantity", "price", "fee"))
    order = next((item for item in ledger.orders() if item["order_id"] == row["order_id"]), {})
    order_fx = Decimal(str(order.get("fx_rate", 1)))
    bar = context.book.bar(str(intent["instrument_id"]), session)
    opening = None if bar is None else bots._finite_number(bar.get("open"))
    reference = Decimal(str(opening)) if opening else None
    return _record(
        context, decision, intent, session, "filled", f"{intent['reason']}; recovered from the paper ledger fill",
        quantity=str(quantity), reference_open=None if reference is None else str(reference), fill_price=str(price),
        fee=str(fee), spread_slippage_cost="0" if reference is None else str(quantity * abs(price - reference) * order_fx),
        fill_id=str(row["paper_trade_id"]), order_id=str(row["order_id"]), planned_quantity=str(intent["planned_quantity"]),
    )


def _limit(context: _Context, key: str) -> Decimal | None:
    """One numeric hard limit of the bot ledger root (the owner's pre-trade limits), ``None`` if unreadable."""

    path = context.track.ledger_root / "configs" / "pre_trade_limits_v1.yaml"
    try:
        limits = yaml.safe_load(path.read_text(encoding="utf-8"))
        value = Decimal(str(limits[key]))
    except (OSError, yaml.YAMLError, KeyError, TypeError, ArithmeticError, ValueError):
        return None
    return value if value > 0 else None


def _sync_shadow(context: _Context, bot_id: str) -> None:
    """Mirror the bot's external flows into its VWCE shadow account once their execution close has passed."""

    active = PaperLedger(context.track.ledger_root, account_id=account_id_for(bot_id))
    flows = active.external_flows()
    if not flows:
        return
    if context.benchmark_check.status != "available":
        context.warnings.append("VWCE reference series unavailable: " + ", ".join(context.benchmark_check.reasons))
        return
    shadow = PaperLedger(context.track.ledger_root, account_id=shadow_id_for(bot_id))
    try:
        shadow.open_benchmark_shadow_account(cost_policy=context.policy, active_account=active, occurred_at=context.cutoff)
        for flow in flows:
            try:
                shadow.record_shadow_flow(
                    flow_id=str(flow["flow_id"]), kind=str(flow["flow_kind"]), amount=Decimal(str(flow["amount"])),
                    flow_at=datetime.fromisoformat(str(flow["flow_at"])), prices=context.benchmark_frame,
                    series_check=context.benchmark_check, cost_policy=context.policy,
                    decision_time=context.cutoff, occurred_at=context.cutoff,
                )
            except PaperLedgerError as exc:
                if not any(marker in str(exc) for marker in _PENDING_SHADOW_MARKERS):
                    raise
    except PaperLedgerError as exc:
        context.warnings.append(f"Shadow account of {bot_id[:12]} not synchronised: {str(exc)[:160]}")


__all__ = [
    "EXECUTION_CONFIG_PATH",
    "ExecutionRunResult",
    "PriceBook",
    "Track",
    "account_id_for",
    "forward_track",
    "load_execution_config",
    "replay_track",
    "run_paper_bot_execution",
    "shadow_id_for",
]
