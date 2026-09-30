"""Fail-closed, paper-only canary stages and promotion gates.

The authority ladder is capped in code at ``capped_automatic``. That stage
means automatic paper simulation only; the owner decision D6 and the authority
matrix keep every live submission disabled. An account-specific loss limit is
required before promotion and is never inferred from portfolio data.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
from types import MappingProxyType
from typing import Iterator, Literal, Mapping


CANARY_AUDIT_SCHEMA = "paper_canary_audit.v1"
_ZERO_HASH = "0" * 64
_ALLOWED_CONFIG_STAGES = frozenset(
    {
        "research",
        "shadow_proposal",
        "paper",
        "broker_read_only",
        "draft_order",
        "capped_automatic",
        "disabled",
        "live",
    }
)
_PERSISTED_STAGES = frozenset({"disabled", "paper", "capped_automatic"})
_STAGE_EVENTS = frozenset({"stage_promoted", "auto_demoted", "emergency_shutdown", "rollback"})


class CanaryError(ValueError):
    """Invalid canary configuration, evidence, or journal state."""


@dataclass(frozen=True)
class CanaryConfig:
    """Explicit local opt-in; no stage or account risk limit is enabled by default."""

    enabled: bool = False
    stage_flags: Mapping[str, bool] = field(default_factory=dict)
    loss_limit: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise CanaryError("Canary opt-in must be a boolean.")
        if not isinstance(self.stage_flags, Mapping):
            raise CanaryError("Canary stage flags must be a mapping.")
        flags: dict[str, bool] = {}
        for stage, enabled in self.stage_flags.items():
            if stage not in _ALLOWED_CONFIG_STAGES or not isinstance(enabled, bool):
                raise CanaryError("Canary stage flags contain an unknown stage or non-boolean value.")
            flags[str(stage)] = enabled
        object.__setattr__(self, "stage_flags", MappingProxyType(flags))
        if self.loss_limit is not None:
            if isinstance(self.loss_limit, bool):
                raise CanaryError("The loss limit must be a finite positive number.")
            try:
                loss_limit = Decimal(str(self.loss_limit))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise CanaryError("The loss limit must be a finite positive number.") from exc
            if not loss_limit.is_finite() or loss_limit <= 0:
                raise CanaryError("The loss limit must be a finite positive number.")
            object.__setattr__(self, "loss_limit", loss_limit)


@dataclass(frozen=True)
class SealedEvidence:
    """Canonical JSON evidence paired with its SHA-256 content seal."""

    canonical_json: str
    sha256: str

    @property
    def payload(self) -> dict[str, object]:
        value = json.loads(self.canonical_json)
        if not isinstance(value, dict):
            raise CanaryError("Sealed evidence must contain a JSON object.")
        return value


@dataclass(frozen=True)
class CanaryGate:
    allowed: bool
    stage: str
    unmet_dependencies: tuple[str, ...] = ()
    execution_allowed: Literal[False] = False


def seal_evidence(payload: Mapping[str, object]) -> SealedEvidence:
    """Freeze a JSON object and hash its canonical representation."""

    if not isinstance(payload, Mapping):
        raise CanaryError("Evidence must be a JSON object.")
    try:
        canonical = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        decoded = json.loads(canonical)
    except (TypeError, ValueError) as exc:
        raise CanaryError("Evidence must be JSON serializable.") from exc
    if not isinstance(decoded, dict):
        raise CanaryError("Evidence must be a JSON object.")
    return SealedEvidence(canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest())


class CanaryController:
    """Manage a durable paper-canary state and route accepted orders to PaperLedger."""

    def __init__(
        self,
        root: Path,
        *,
        account_id: str = "local-paper",
        config: CanaryConfig | None = None,
    ) -> None:
        self.root = Path(root)
        self.account_id = _clean_id(account_id, "account_id")
        self.config = config or CanaryConfig()
        self.audit_path = self.root / "data" / "operations" / "canary" / self.account_id / "audit.jsonl"
        self._lock = threading.RLock()

    def audit_events(self) -> tuple[dict[str, object], ...]:
        """Read and verify the append-only canary audit chain."""

        return tuple(_json_copy(event) for event in self._read_events())

    def status(self) -> dict[str, object]:
        """Return a read-only, distinct application status projection."""

        events = self._read_events()
        stage = self._current_stage(events)
        active_break = _active_reconciliation_break(events)
        last_shutdown = next(
            (event for event in reversed(events) if event["event_type"] == "emergency_shutdown"), None
        )
        rolled_back_after_shutdown = bool(
            last_shutdown
            and any(event["event_type"] == "rollback" and event["sequence"] > last_shutdown["sequence"] for event in events)
        )
        if active_break:
            state = "reconciliation_blocked"
        elif last_shutdown and not rolled_back_after_shutdown and stage == "disabled":
            state = "emergency_shutdown"
        elif stage == "capped_automatic":
            state = "capped_automatic_paper"
        elif stage == "paper":
            state = "paper_canary"
        else:
            state = "disabled"
        live_gate = self.evaluate_live_submission()
        return {
            "state": state,
            "stage": stage,
            "opted_in": self.config.enabled and self.config.stage_flags.get("paper", False),
            "active_reconciliation_break": active_break,
            "live_submission": "blocked",
            "live_unmet_dependencies": list(live_gate.unmet_dependencies),
            "execution_allowed": False,
        }

    def paper_order_gate(self) -> CanaryGate:
        events = self._read_events()
        stage = self._current_stage(events)
        unmet: list[str] = []
        if not self.config.enabled:
            unmet.append("canary_opt_in_missing")
        if stage not in {"paper", "capped_automatic"}:
            unmet.append("paper_canary_stage_disabled")
        if _active_reconciliation_break(events):
            unmet.append("reconciliation_break_active")
        return CanaryGate(not unmet, stage, tuple(unmet))

    def evaluate_live_submission(self) -> CanaryGate:
        """Always deny live submission and report all unavailable dependencies."""

        events = self._read_events()
        stage = self._current_stage(events)
        unmet = [
            "owner_decision_d6_live_submission_disabled",
            "code_authority_cap_capped_automatic",
            "ISSUE-0132_independent_controls_activation_evidence_missing",
            "ISSUE-0152_final_release_certification_missing",
            "explicit_live_operator_enablement_missing",
        ]
        try:
            from etf_cockpit.governance.product_scope import load_authority_matrix

            matrix = load_authority_matrix()
            policy = matrix.policy
            if policy is None:
                unmet.append("authority_matrix_unavailable")
            else:
                capped = next(
                    (item for item in policy.authority_stages if item.stage_id == "capped_automatic"), None
                )
                if capped is None or capped.execution_allowed is not False:
                    unmet.append("authority_matrix_capped_stage_invalid")
                if matrix.execution_allowed is not False:
                    unmet.append("authority_matrix_execution_allowed_not_false")
                if matrix.diagnostic_mode:
                    unmet.append("authority_matrix_diagnostic_mode")
        except (OSError, ValueError, TypeError):
            unmet.append("authority_matrix_unavailable")
        if self.config.stage_flags.get("live", False):
            unmet.append("live_stage_flag_cannot_grant_authority")
        return CanaryGate(False, stage, tuple(dict.fromkeys(unmet)))

    def promote(
        self,
        target_stage: str,
        *,
        operator_enabled: bool,
        promotion_evidence: SealedEvidence | None,
        occurred_at: datetime | None = None,
    ) -> CanaryGate:
        """Promote paper to bounded automatic paper only after explicit gates."""

        events = self._read_events()
        current = self._current_stage(events)
        blockers: list[str] = []
        if target_stage != "capped_automatic":
            blockers.append("code_authority_cap_capped_automatic")
        if not self.config.enabled or not self.config.stage_flags.get("paper", False):
            blockers.append("canary_opt_in_missing")
        if not self.config.stage_flags.get("capped_automatic", False):
            blockers.append("capped_automatic_stage_not_enabled")
        if current != "paper":
            blockers.append("promotion_requires_paper_stage")
        if operator_enabled is not True:
            blockers.append("explicit_operator_enablement_missing")
        if self.config.loss_limit is None:
            blockers.append("account_loss_limit_missing")
        try:
            from etf_cockpit.governance.product_scope import load_authority_matrix

            matrix = load_authority_matrix()
            policy = matrix.policy
            capped = None if policy is None else next(
                (item for item in policy.authority_stages if item.stage_id == "capped_automatic"), None
            )
            if matrix.diagnostic_mode or capped is None:
                blockers.append("authority_matrix_capped_stage_unavailable")
        except (OSError, ValueError, TypeError):
            blockers.append("authority_matrix_capped_stage_unavailable")
        evidence = _verified_payload(promotion_evidence)
        if evidence is None:
            blockers.append("sealed_promotion_evidence_missing_or_invalid")
        else:
            for gate in ("controls_passed", "release_certified", "reconciliation_clear", "rollback_tested"):
                if evidence.get(gate) is not True:
                    blockers.append(f"promotion_gate_{gate}_unmet")
        if blockers:
            self._append_event(
                "promotion_blocked",
                {"from_stage": current, "target_stage": str(target_stage), "unmet_dependencies": blockers},
                occurred_at,
            )
            return CanaryGate(False, current, tuple(blockers))
        self._append_event(
            "stage_promoted",
            {"previous_stage": current, "next_stage": "capped_automatic", "execution_allowed": False},
            occurred_at,
        )
        return CanaryGate(True, "capped_automatic")

    def emergency_shutdown(self, *, reason: str, occurred_at: datetime | None = None) -> CanaryGate:
        text = _clean_text(reason, "reason", 500)
        events = self._read_events()
        previous = self._current_stage(events)
        self._append_event(
            "emergency_shutdown",
            {"previous_stage": previous, "next_stage": "disabled", "reason": text, "execution_allowed": False},
            occurred_at,
        )
        return CanaryGate(False, "disabled", ("emergency_shutdown_active",))

    def rollback(self, *, reason: str, occurred_at: datetime | None = None) -> CanaryGate:
        text = _clean_text(reason, "reason", 500)
        events = self._read_events()
        current = self._current_stage(events)
        stage_event = next((event for event in reversed(events) if event["event_type"] in _STAGE_EVENTS), None)
        if stage_event is None:
            raise CanaryError("No canary stage transition is available to roll back.")
        target = str(stage_event["details"].get("previous_stage", ""))
        if target not in _PERSISTED_STAGES:
            raise CanaryError("The previous canary stage is unavailable for rollback.")
        if target == "capped_automatic" and not self.config.stage_flags.get("capped_automatic", False):
            target = "paper"
        self._append_event(
            "rollback",
            {"previous_stage": current, "next_stage": target, "reason": text, "execution_allowed": False},
            occurred_at,
        )
        return CanaryGate(target in {"paper", "capped_automatic"}, target)

    def observe_loss(self, loss_amount: object, *, occurred_at: datetime | None = None) -> CanaryGate:
        loss = _non_negative_decimal(loss_amount, "loss_amount")
        events = self._read_events()
        current = self._current_stage(events)
        limit = self.config.loss_limit
        breached = limit is None or loss > limit
        next_stage = "paper" if current == "capped_automatic" and breached else current
        event_type = "auto_demoted" if next_stage == "paper" and current == "capped_automatic" else "loss_observed"
        details: dict[str, object] = {
            "previous_stage": current,
            "next_stage": next_stage,
            "loss_amount": str(loss),
            "loss_limit": None if limit is None else str(limit),
            "breach": breached,
            "reason": "loss_limit_breach" if breached else "within_loss_limit",
            "execution_allowed": False,
        }
        self._append_event(event_type, details, occurred_at)
        return CanaryGate(not breached, next_stage, () if not breached else ("loss_limit_breach",))

    def observe_reconciliation(self, *, reconciled: bool, occurred_at: datetime | None = None) -> CanaryGate:
        if not isinstance(reconciled, bool):
            raise CanaryError("Reconciliation status must be a boolean.")
        events = self._read_events()
        current = self._current_stage(events)
        if reconciled:
            self._append_event(
                "reconciliation_matched",
                {"previous_stage": current, "next_stage": current, "execution_allowed": False},
                occurred_at,
            )
            return CanaryGate(True, current)
        next_stage = "paper" if current == "capped_automatic" else current
        self._append_event(
            "reconciliation_break",
            {
                "previous_stage": current,
                "next_stage": next_stage,
                "execution_allowed": False,
                "demoted": current == "capped_automatic",
            },
            occurred_at,
        )
        if next_stage != current:
            self._append_event(
                "auto_demoted",
                {
                    "previous_stage": current,
                    "next_stage": "paper",
                    "reason": "reconciliation_break",
                    "execution_allowed": False,
                },
                occurred_at,
            )
        return CanaryGate(False, next_stage, ("reconciliation_break_active",))

    def accept_paper_order(
        self,
        *,
        proposal: SealedEvidence | None,
        control_evidence: SealedEvidence | None,
        execution_price: object,
        fee: object = 0,
        fx_rate: object = 1,
        occurred_at: datetime | None = None,
    ) -> dict[str, object]:
        """Accept only a sealed, control-linked order through the local PaperLedger."""

        gate = self.paper_order_gate()
        if not gate.allowed:
            self._block_order("paper_canary_gate_blocked", gate.unmet_dependencies, occurred_at)
            raise CanaryError("Paper canary order is blocked: " + ", ".join(gate.unmet_dependencies))
        proposal_payload = _verified_payload(proposal)
        control_payload = _verified_payload(control_evidence)
        if proposal_payload is None or control_payload is None:
            self._block_order("sealed_proposal_or_control_evidence_missing", (), occurred_at)
            raise CanaryError("A sealed proposal and sealed control evidence are required.")
        proposal_hash = proposal.sha256
        control_hash = control_evidence.sha256
        proposal_id = proposal_payload.get("proposal_id")
        if (
            not isinstance(proposal_id, str)
            or proposal_payload.get("execution_allowed") is not False
            or control_payload.get("proposal_id") != proposal_id
            or control_payload.get("proposal_hash") != proposal_hash
            or control_payload.get("allowed") is not True
            or control_payload.get("execution_allowed") is not False
        ):
            self._block_order("sealed_control_evidence_does_not_match_proposal", (), occurred_at)
            raise CanaryError("Sealed control evidence does not approve this paper proposal.")

        stage = gate.stage
        self._append_event(
            "paper_order_acceptance_intent",
            {
                "proposal_id": proposal_id,
                "proposal_hash": proposal_hash,
                "control_hash": control_hash,
                "proposal": proposal_payload,
                "control_evidence": control_payload,
                "stage": stage,
                "execution_allowed": False,
            },
            occurred_at,
        )
        try:
            from etf_cockpit.portfolio.paper_trading import PaperLedger

            order = PaperLedger(self.root, account_id=self.account_id).accept_proposal(
                proposal_payload,
                execution_price=float(execution_price),
                fee=float(fee),
                fx_rate=float(fx_rate),
                decision_mode="auto_paper" if stage == "capped_automatic" else "manual_accept",
                occurred_at=occurred_at,
            )
        except (ImportError, OSError, ValueError, TypeError) as exc:
            self._block_order("paper_ledger_rejected_order", (str(exc),), occurred_at)
            raise CanaryError("The local paper ledger rejected the canary order.") from exc
        self._append_event(
            "paper_order_accepted",
            {
                "order_id": str(order["order_id"]),
                "proposal_id": proposal_id,
                "proposal_hash": proposal_hash,
                "control_hash": control_hash,
                "execution_allowed": False,
            },
            occurred_at,
        )
        return dict(order)

    def _current_stage(self, events: tuple[dict[str, object], ...] | list[dict[str, object]]) -> str:
        if not self.config.enabled or not self.config.stage_flags.get("paper", False):
            return "disabled"
        stage = "paper"
        for event in events:
            if event["event_type"] in _STAGE_EVENTS:
                next_stage = event["details"].get("next_stage")
                if next_stage not in _PERSISTED_STAGES:
                    raise CanaryError("Canary audit journal contains an unsupported stage.")
                stage = str(next_stage)
        if stage == "capped_automatic" and not self.config.stage_flags.get("capped_automatic", False):
            return "paper"
        return stage

    def _block_order(self, reason: str, dependencies: tuple[str, ...], occurred_at: datetime | None) -> None:
        self._append_event(
            "paper_order_blocked",
            {"reason": reason, "unmet_dependencies": list(dependencies), "execution_allowed": False},
            occurred_at,
        )

    def _append_event(
        self,
        event_type: str,
        details: Mapping[str, object],
        occurred_at: datetime | None,
    ) -> dict[str, object]:
        timestamp = _timestamp(occurred_at)
        copied = _json_copy(details)
        with self._lock, self._file_lock():
            events = self._read_events()
            event: dict[str, object] = {
                "schema_version": CANARY_AUDIT_SCHEMA,
                "account_id": self.account_id,
                "sequence": len(events) + 1,
                "event_type": _clean_text(event_type, "event_type", 80),
                "occurred_at": timestamp,
                "details": copied,
                "prior_hash": str(events[-1]["event_hash"]) if events else _ZERO_HASH,
                "execution_allowed": False,
            }
            event["event_hash"] = _digest(event)
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return event

    def _read_events(self) -> tuple[dict[str, object], ...]:
        if not self.audit_path.exists():
            return ()
        try:
            rows = self.audit_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise CanaryError("Canary audit journal cannot be read.") from exc
        events: list[dict[str, object]] = []
        previous_hash = _ZERO_HASH
        for sequence, row in enumerate(rows, start=1):
            try:
                event = json.loads(row)
                if (
                    not isinstance(event, dict)
                    or event.get("schema_version") != CANARY_AUDIT_SCHEMA
                    or event.get("account_id") != self.account_id
                    or event.get("sequence") != sequence
                    or event.get("prior_hash") != previous_hash
                    or event.get("execution_allowed") is not False
                    or not isinstance(event.get("details"), dict)
                ):
                    raise ValueError("invalid event shape")
                supplied_hash = event.get("event_hash")
                canonical = {key: value for key, value in event.items() if key != "event_hash"}
                expected_hash = _digest(canonical)
                if not isinstance(supplied_hash, str) or not hmac.compare_digest(supplied_hash, expected_hash):
                    raise ValueError("invalid event hash")
                previous_hash = supplied_hash
                events.append(event)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise CanaryError("Canary audit journal is malformed or changed.") from exc
        return tuple(events)

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        lock_path = self.audit_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _verified_payload(evidence: SealedEvidence | None) -> dict[str, object] | None:
    if not isinstance(evidence, SealedEvidence):
        return None
    if not isinstance(evidence.canonical_json, str) or not isinstance(evidence.sha256, str):
        return None
    try:
        payload = json.loads(evidence.canonical_json)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or canonical != evidence.canonical_json:
        return None
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload if hmac.compare_digest(expected, evidence.sha256) else None


def _active_reconciliation_break(events: tuple[dict[str, object], ...] | list[dict[str, object]]) -> bool:
    active = False
    for event in events:
        if event["event_type"] == "reconciliation_break":
            active = True
        elif event["event_type"] == "reconciliation_matched":
            active = False
    return active


def _clean_id(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise CanaryError(f"{label} must be text.")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 120 or any(not (char.isalnum() or char in "-_:") for char in cleaned):
        raise CanaryError(f"{label} is invalid.")
    return cleaned


def _clean_text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise CanaryError(f"{label} must be text.")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum or any(ord(char) < 32 for char in cleaned):
        raise CanaryError(f"{label} is invalid.")
    return cleaned


def _non_negative_decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise CanaryError(f"{label} must be a finite non-negative number.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanaryError(f"{label} must be a finite non-negative number.") from exc
    if not result.is_finite() or result < 0:
        raise CanaryError(f"{label} must be a finite non-negative number.")
    return result


def _timestamp(value: datetime | None) -> str:
    instant = datetime.now(timezone.utc) if value is None else value
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise CanaryError("Audit timestamps must be timezone-aware.")
    return instant.astimezone(timezone.utc).isoformat()


def _json_copy(value: Mapping[str, object]) -> dict[str, object]:
    try:
        copied = json.loads(json.dumps(dict(value), sort_keys=True, separators=(",", ":"), default=str))
    except (TypeError, ValueError) as exc:
        raise CanaryError("Canary audit details must be JSON serializable.") from exc
    if not isinstance(copied, dict):
        raise CanaryError("Canary audit details must be an object.")
    return copied


def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = [
    "CANARY_AUDIT_SCHEMA",
    "CanaryConfig",
    "CanaryController",
    "CanaryError",
    "CanaryGate",
    "SealedEvidence",
    "seal_evidence",
]
