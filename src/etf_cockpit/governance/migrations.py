"""Deterministic v1.x signal/action to governance schema 2.0 migration.

The migration is intentionally a pure adapter.  It never mutates a supplied
record and does not replace a source catalogue.  Callers can validate the
returned versioned rows before publishing a pointer or writing an export.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, datetime
from math import isfinite
from pathlib import Path
import re
from typing import Any, Iterable, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.signals.research_states import (
    AnalysisStatus,
    MigrationSemantics,
    PortfolioReviewState,
    ResearchState,
    normalise_analysis_status,
    research_state_for_legacy_action,
)


V1_SCHEMA_PREFIXES = ("1", "1.")
V2_SCHEMA_VERSION = "2.0"
MIGRATION_VERSION = "2.0"
GATE_POLICY_PATH = CONFIG_DIR / "gate_policy.yaml"
LegacyAction = Literal[
    "buy",
    "add",
    "hold",
    "trim",
    "sell",
    "no_trade",
    "manual_review",
    "add_candidate",
    "trim_candidate",
]


class ResearchStateMigration(BaseModel):
    """Canonical v2 row returned by :func:`migrate_legacy_action`."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    research_state: ResearchState
    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
    analysis_status: AnalysisStatus = "unavailable"
    research_promotion_allowed: bool = False
    portfolio_review_allowed: bool = False
    # A generated marker preserves validated portfolio context across a
    # second migration without trusting a caller's positive review flag.  The
    # source snapshot and its deterministic checksum are retained so the
    # marker is only valid when its evidence can be revalidated.
    portfolio_snapshot_validated: bool = False
    portfolio_snapshot_provenance: Literal["validated_snapshot", "unavailable"] = "unavailable"
    portfolio_snapshot: dict[str, object] | None = None
    portfolio_snapshot_checksum: str = "unavailable"
    execution_allowed: Literal[False] = Field(default=False, frozen=True)
    legacy_action: str | None = None
    migration_semantics: MigrationSemantics = "lossy"
    migration_version: Literal["2.0"] = "2.0"
    gate_policy_version: str = "unavailable"
    gate_policy_checksum: str = "unavailable"
    schema_version: Literal["2.0"] = "2.0"
    _validated_portfolio_contract: bool = PrivateAttr(default=False)

    @field_validator("research_promotion_allowed", "portfolio_review_allowed", mode="before")
    @classmethod
    def _force_compatibility_authority_false(cls, _value: object) -> bool:
        """Direct construction cannot mint a positive v2 authority flag."""

        return False

    @classmethod
    def from_validated_snapshot(
        cls,
        *,
        portfolio_snapshot: Mapping[str, object],
        portfolio_snapshot_checksum: str,
        **values: object,
    ) -> "ResearchStateMigration":
        """Build the sole migration row that may carry portfolio authority.

        The caller must provide a snapshot that passes the same temporal and
        payload validation as the migration seam plus its matching checksum.
        This explicit constructor is the validated context contract; ordinary
        direct model construction remains fail-closed.
        """

        snapshot = dict(portfolio_snapshot)
        if not _snapshot_payload_is_valid(snapshot):
            raise ValueError("portfolio snapshot is not valid contemporaneous evidence")
        expected_checksum = _snapshot_checksum(snapshot)
        if str(portfolio_snapshot_checksum).strip().casefold() != expected_checksum:
            raise ValueError("portfolio snapshot checksum does not match evidence")
        values = dict(values)
        values["portfolio_snapshot"] = snapshot
        values["portfolio_snapshot_checksum"] = expected_checksum
        values["portfolio_snapshot_validated"] = True
        values["portfolio_snapshot_provenance"] = "validated_snapshot"
        values["portfolio_review_allowed"] = False
        instance = cls(**values)
        object.__setattr__(instance, "_validated_portfolio_contract", True)
        object.__setattr__(instance, "portfolio_review_allowed", True)
        return instance

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        """Default to JSON-compatible enum values for stable idempotency."""

        kwargs.setdefault("mode", "json")
        payload = super().model_dump(*args, **kwargs)
        # Even model_copy/model_construct compatibility seams cannot emit
        # positive authority unless the explicit validated contract above was
        # used and the retained evidence still matches its checksum.
        payload["research_promotion_allowed"] = False
        contract_valid = (
            self._validated_portfolio_contract
            and self.portfolio_snapshot_validated
            and self.portfolio_snapshot_provenance == "validated_snapshot"
            and self.portfolio_snapshot is not None
            and self.portfolio_snapshot_checksum == _snapshot_checksum(self.portfolio_snapshot)
        )
        payload["portfolio_review_allowed"] = bool(contract_valid)
        return payload

    def to_v2_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_public_dict(self) -> dict[str, Any]:
        return self.to_v2_dict()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value: object) -> str:
    payload = value if isinstance(value, bytes) else _canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _snapshot_checksum(snapshot: Mapping[str, object]) -> str:
    """Return the deterministic integrity checksum for validated evidence."""

    return _sha256({"portfolio_snapshot": dict(snapshot)})


def _gate_policy_metadata() -> tuple[str, str]:
    """Read only deterministic gate metadata; unavailable is fail-closed."""

    try:
        raw = GATE_POLICY_PATH.read_bytes()
        payload = yaml.safe_load(raw.decode("utf-8"))
        version = str(payload.get("policy_version") or payload.get("schema_version") or "unavailable") if isinstance(payload, Mapping) else "unavailable"
        return version, hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeError, yaml.YAMLError):
        return "unavailable", "unavailable"


def _valid_analysis_status(value: object, *, fallback: AnalysisStatus) -> AnalysisStatus:
    return normalise_analysis_status(value, fallback=fallback)


def _valid_snapshot_timestamp(value: object) -> bool:
    if isinstance(value, datetime | date):
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return isfinite(float(value))
    text = str(value or "").strip()
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        try:
            date.fromisoformat(text)
            return True
        except ValueError:
            return False


def _portfolio_state_from_value(value: object) -> PortfolioReviewState | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    if not text:
        return None
    try:
        return PortfolioReviewState(text)
    except ValueError:
        # Legacy portfolio verbs are context-only compatibility values.
        if text in {"buy", "add", "add_candidate", "increase", "increase_exposure"}:
            return PortfolioReviewState.INCREASE_EXPOSURE_REVIEW
        if text in {"trim", "trim_candidate", "decrease", "reduce", "reduce_exposure"}:
            return PortfolioReviewState.REDUCE_EXPOSURE_REVIEW
        if text in {"sell", "exit", "close"}:
            return PortfolioReviewState.EXIT_THESIS_REVIEW
        if text in {"hold", "maintain", "no_trade"}:
            return PortfolioReviewState.MAINTAIN_REVIEW
    return None


def _snapshot_payload_is_valid(candidate: Mapping[str, object]) -> bool:
    timestamp = next(
        (
            candidate.get(key)
            for key in ("as_of_date", "as_of", "snapshot_at", "snapshot_date", "timestamp", "date")
            if key in candidate
        ),
        None,
    )
    if not _valid_snapshot_timestamp(timestamp):
        return False

    state_keys = ("portfolio_review_state", "review_state", "state")
    state_present = any(key in candidate for key in state_keys)
    if state_present and _portfolio_state_from_value(next(candidate.get(key) for key in state_keys if key in candidate)) is None:
        return False

    payload_present = False
    for key in ("holdings", "positions", "weights", "portfolio_weights"):
        if key not in candidate:
            continue
        value = candidate.get(key)
        if isinstance(value, Mapping):
            payload_present = bool(value)
        elif isinstance(value, (list, tuple)):
            payload_present = bool(value)
        if not payload_present:
            return False
        break
    for key in ("current_weight", "target_weight"):
        if key not in candidate:
            continue
        try:
            payload_present = isfinite(float(candidate[key]))
        except (TypeError, ValueError):
            return False
        if not payload_present:
            return False
        break

    # A contemporaneous snapshot may carry a validated review state, or a
    # holdings/weights payload from which the conservative maintain review is
    # derived.  Timestamp alone is never enough.
    return state_present or payload_present


def _snapshot_mapping(record: Mapping[str, object]) -> Mapping[str, object] | None:
    """Return an explicitly contemporaneous portfolio snapshot, if present."""

    for key in ("portfolio_snapshot", "portfolio_context", "holdings_snapshot"):
        candidate = record.get(key)
        if isinstance(candidate, Mapping) and _snapshot_payload_is_valid(candidate):
            return candidate
    # Score-history persistence uses a canonical JSON text column so parquet
    # readers never need to reconstruct arbitrary object values.
    encoded = record.get("portfolio_snapshot_json")
    if isinstance(encoded, str) and encoded.strip():
        try:
            candidate = json.loads(encoded)
        except json.JSONDecodeError:
            candidate = None
        if isinstance(candidate, Mapping) and _snapshot_payload_is_valid(candidate):
            return candidate
    return None


def validated_portfolio_snapshot(record: Mapping[str, object]) -> Mapping[str, object] | None:
    """Return snapshot evidence only when timestamp and payload validate."""

    return _snapshot_mapping(record)


def _portfolio_state(record: Mapping[str, object], snapshot: Mapping[str, object] | None = None) -> tuple[PortfolioReviewState, bool]:
    snapshot = snapshot if snapshot is not None else _snapshot_mapping(record)
    if snapshot is None:
        return PortfolioReviewState.NOT_APPLICABLE, False

    raw_state = snapshot.get("portfolio_review_state", snapshot.get("review_state", snapshot.get("state")))
    state = _portfolio_state_from_value(raw_state)
    if state is None:
        # Valid holdings/weights without an explicit state are conservative
        # context only and do not imply a transaction-shaped recommendation.
        state = PortfolioReviewState.MAINTAIN_REVIEW
    return state, state is not PortfolioReviewState.NOT_APPLICABLE


def _legacy_text(record: Mapping[str, object]) -> str | None:
    value = record.get("legacy_action") if "legacy_action" in record else record.get("action", record.get("final_action"))
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _schema_version(record: Mapping[str, object]) -> Literal["1.x", "2.0"]:
    raw = record.get("schema_version")
    text = str(raw).strip() if raw is not None else ""
    if text == V2_SCHEMA_VERSION:
        return "2.0"
    if re.fullmatch(r"1(?:\.\d+)?", text):
        return "1.x"
    raise ValueError(f"unsupported schema_version: {text or '<missing>'}")


def _already_v2(record: Mapping[str, object]) -> bool:
    return _schema_version(record) == "2.0" and "research_state" in record


def _v2_context_marker(record: Mapping[str, object]) -> bool:
    try:
        validated = bool(record.get("portfolio_snapshot_validated"))
    except (TypeError, ValueError):
        validated = False
    snapshot = _snapshot_mapping(record)
    supplied_checksum = str(record.get("portfolio_snapshot_checksum") or "").strip().casefold()
    return (
        validated
        and str(record.get("portfolio_snapshot_provenance") or "").strip().casefold() == "validated_snapshot"
        and snapshot is not None
        and supplied_checksum == _snapshot_checksum(snapshot)
    )


def migrate_legacy_action(record: Mapping[str, object]) -> ResearchStateMigration:
    """Map one v1.x row to a canonical v2 governance row.

    Unknown/missing actions are explicitly mapped to ``manual_review``.  A v2
    row is normalised again rather than returned by reference, making repeated
    migration semantically and byte-equivalent.
    """

    if not isinstance(record, Mapping):
        raise TypeError("legacy record must be a mapping")

    gate_version, gate_checksum = _gate_policy_metadata()
    schema = _schema_version(record)
    if _already_v2(record):
        raw_state = record.get("research_state")
        try:
            state = ResearchState(str(raw_state))
        except ValueError:
            state = ResearchState.MANUAL_REVIEW
        snapshot = _snapshot_mapping(record)
        supplied_checksum = str(record.get("portfolio_snapshot_checksum") or "").strip().casefold()
        snapshot_checksum = _snapshot_checksum(snapshot) if snapshot is not None else "unavailable"
        marker_validated = _v2_context_marker(record)
        if snapshot is not None:
            portfolio_state, source_context_allowed = _portfolio_state(record, snapshot)
            # A fresh source snapshot is evidence in its own right.  When a
            # marker is carried from a prior migration, require its checksum;
            # a mismatched supplied checksum is treated as tampering.
            checksum_ok = not supplied_checksum or supplied_checksum == "unavailable" or supplied_checksum == snapshot_checksum
            context_allowed = source_context_allowed and checksum_ok
        else:
            try:
                portfolio_state = PortfolioReviewState(str(record.get("portfolio_review_state") or PortfolioReviewState.NOT_APPLICABLE.value))
            except ValueError:
                portfolio_state = PortfolioReviewState.NOT_APPLICABLE
            context_allowed = False
        try:
            stored_portfolio_state = PortfolioReviewState(str(record.get("portfolio_review_state") or portfolio_state.value))
        except ValueError:
            stored_portfolio_state = portfolio_state
        if snapshot is None and not marker_validated:
            # Preserve a v2 state as review data, but do not infer portfolio
            # authority from the state or caller-supplied positive flag.
            stored_portfolio_state = stored_portfolio_state
        analysis_status = _valid_analysis_status(record.get("analysis_status"), fallback="unavailable")
        legacy_action = _legacy_text(record)
        semantics = str(record.get("migration_semantics") or "lossy").strip().casefold()
        if semantics not in {"lossless", "lossy"}:
            semantics = "lossy"
        values: dict[str, object] = {
            "research_state": state,
            "portfolio_review_state": stored_portfolio_state,
            "analysis_status": analysis_status,
            "research_promotion_allowed": False,
            "portfolio_review_allowed": False,
            "portfolio_snapshot_validated": context_allowed,
            "portfolio_snapshot_provenance": "validated_snapshot" if context_allowed else "unavailable",
            "portfolio_snapshot": dict(snapshot) if context_allowed and snapshot is not None else None,
            "portfolio_snapshot_checksum": snapshot_checksum if context_allowed else "unavailable",
            "execution_allowed": False,
            "legacy_action": legacy_action,
            "migration_semantics": semantics,
            "migration_version": str(record.get("migration_version") or MIGRATION_VERSION),
            "gate_policy_version": str(record.get("gate_policy_version") or gate_version),
            "gate_policy_checksum": str(record.get("gate_policy_checksum") or gate_checksum),
            "schema_version": V2_SCHEMA_VERSION,
        }
        if context_allowed and snapshot is not None:
            contract_values = dict(values)
            contract_values.pop("portfolio_snapshot", None)
            contract_values.pop("portfolio_snapshot_checksum", None)
            return ResearchStateMigration.from_validated_snapshot(
                portfolio_snapshot=snapshot,
                portfolio_snapshot_checksum=snapshot_checksum,
                **contract_values,
            )
        return ResearchStateMigration(**values)

    if schema != "1.x":
        raise ValueError(f"unsupported schema_version: {record.get('schema_version')!r}")

    legacy_action = _legacy_text(record)
    state = research_state_for_legacy_action(legacy_action)
    action_key = legacy_action.casefold() if legacy_action is not None else ""
    # Transactional decrease/exit intent cannot be reconstructed as a public
    # action; those rows are explicitly marked lossy.  Unknown/missing rows
    # also retain a lossy marker because no positive interpretation is safe.
    semantics = "lossless" if action_key in {
        "buy",
        "add",
        "add_candidate",
        "hold",
        "no_trade",
        "manual_review",
    } else "lossy"
    portfolio_state, portfolio_allowed = _portfolio_state(record)
    snapshot = _snapshot_mapping(record)
    snapshot_validated = snapshot is not None and portfolio_allowed
    snapshot_checksum = _snapshot_checksum(snapshot) if snapshot_validated and snapshot is not None else "unavailable"
    status_fallback: AnalysisStatus = "partial" if legacy_action is not None and action_key in {
        "buy",
        "add",
        "add_candidate",
        "hold",
        "trim",
        "trim_candidate",
        "sell",
        "no_trade",
        "manual_review",
    } else "unavailable"
    analysis_status = _valid_analysis_status(record.get("analysis_status"), fallback=status_fallback)
    # Promotion remains false until the policy-driven resolver (Task 3) has
    # checked the complete evidence/gate set.
    values: dict[str, object] = {
        "research_state": state,
        "portfolio_review_state": portfolio_state,
        "analysis_status": analysis_status,
        "research_promotion_allowed": False,
        "portfolio_review_allowed": False,
        "portfolio_snapshot_validated": snapshot_validated,
        "portfolio_snapshot_provenance": "validated_snapshot" if snapshot_validated else "unavailable",
        "portfolio_snapshot": dict(snapshot) if snapshot_validated and snapshot is not None else None,
        "portfolio_snapshot_checksum": snapshot_checksum,
        "execution_allowed": False,
        "legacy_action": legacy_action,
        "migration_semantics": semantics,
        "migration_version": MIGRATION_VERSION,
        "gate_policy_version": str(record.get("gate_policy_version") or gate_version),
        "gate_policy_checksum": str(record.get("gate_policy_checksum") or gate_checksum),
        "schema_version": V2_SCHEMA_VERSION,
    }
    if snapshot_validated and snapshot is not None:
        contract_values = dict(values)
        contract_values.pop("portfolio_snapshot", None)
        contract_values.pop("portfolio_snapshot_checksum", None)
        return ResearchStateMigration.from_validated_snapshot(
            portfolio_snapshot=snapshot,
            portfolio_snapshot_checksum=snapshot_checksum,
            **contract_values,
        )
    return ResearchStateMigration(**values)


def migrate_records(records: Iterable[Mapping[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Migrate rows and return canonical rows plus deterministic evidence."""

    source_rows = [dict(record) for record in records]
    migrated = [migrate_legacy_action(record).to_v2_dict() for record in source_rows]
    actions = [_legacy_text(record) for record in source_rows]
    known = Counter(action.casefold() for action in actions if action and action.casefold() in {
        "buy",
        "add",
        "add_candidate",
        "hold",
        "trim",
        "trim_candidate",
        "sell",
        "no_trade",
        "manual_review",
    })
    unknown = sorted({action for action in (action.casefold() if action else "<missing>" for action in actions) if action not in known})
    report: dict[str, object] = {
        "schema_version": V2_SCHEMA_VERSION,
        "migration_version": MIGRATION_VERSION,
        "source_schema_version": "1.x",
        "target_schema_version": V2_SCHEMA_VERSION,
        "row_count": len(source_rows),
        "mapped_row_count": sum(known.values()),
        "unmapped_row_count": len(source_rows) - sum(known.values()),
        "mapped_values": dict(sorted(known.items())),
        "unmapped_values": unknown,
        "old_checksum": _sha256(source_rows),
        "new_checksum": _sha256(migrated),
        "legacy_preservation": "Source rows are never mutated; legacy_action is retained in validated v2 rows.",
        "portfolio_context_rule": "portfolio_review_state remains not_applicable unless a contemporaneous snapshot is explicit.",
        "lossy_values": ["trim", "trim_candidate", "sell", "unknown", "<missing>"],
        "lossless_values": [
            "buy",
            "add",
            "add_candidate",
            "hold",
            "no_trade",
            "manual_review",
        ],
    }
    report["migration_checksum"] = _sha256(report)
    return migrated, report


def write_migration_report(
    records: Iterable[Mapping[str, object]],
    path: Path,
) -> dict[str, object]:
    """Write deterministic migration evidence without deleting source rows."""

    _, report = migrate_records(records)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def log_migration_event(report: Mapping[str, object], *, path: Path | None = None) -> None:
    """Record a redacted operational migration event on the existing trace."""

    try:
        from etf_cockpit.core.session_log import log_event

        log_event(
            event_type="research_state_migration",
            component="governance.migrations",
            operation="migrate_v1_to_v2",
            status="complete",
            row_counts={
                "rows": int(report.get("row_count", 0)),
                "mapped": int(report.get("mapped_row_count", 0)),
                "unmapped": int(report.get("unmapped_row_count", 0)),
            },
            checksums={
                key: str(report[key])
                for key in ("old_checksum", "new_checksum", "migration_checksum")
                if report.get(key)
            },
            path=path,
        )
    except Exception:
        # Migration evidence must never be blocked by an unavailable log.
        return


__all__ = [
    "GATE_POLICY_PATH",
    "LegacyAction",
    "MIGRATION_VERSION",
    "MigrationSemantics",
    "ResearchStateMigration",
    "V2_SCHEMA_VERSION",
    "migrate_legacy_action",
    "migrate_records",
    "log_migration_event",
    "_snapshot_checksum",
    "validated_portfolio_snapshot",
    "write_migration_report",
]
