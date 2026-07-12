"""Deterministic v1.x signal/action to governance schema 2.0 migration.

The migration is intentionally a pure adapter.  It never mutates a supplied
record and does not replace a source catalogue.  Callers can validate the
returned versioned rows before publishing a pointer or writing an export.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field

from etf_cockpit.core.paths import CONFIG_DIR
from etf_cockpit.signals.research_states import (
    AnalysisStatus,
    PortfolioReviewState,
    ResearchState,
    research_state_for_legacy_action,
)


V1_SCHEMA_PREFIXES = ("1", "1.")
V2_SCHEMA_VERSION = "2.0"
MIGRATION_VERSION = "2.0"
GATE_POLICY_PATH = CONFIG_DIR / "gate_policy.yaml"


class ResearchStateMigration(BaseModel):
    """Canonical v2 row returned by :func:`migrate_legacy_action`."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    research_state: ResearchState
    portfolio_review_state: PortfolioReviewState = PortfolioReviewState.NOT_APPLICABLE
    analysis_status: AnalysisStatus = "unavailable"
    research_promotion_allowed: bool = False
    portfolio_review_allowed: bool = False
    execution_allowed: Literal[False] = Field(default=False, frozen=True)
    legacy_action: str | None = None
    migration_semantics: str = "lossy"
    migration_version: str = MIGRATION_VERSION
    gate_policy_version: str = "unavailable"
    gate_policy_checksum: str = "unavailable"
    schema_version: str = V2_SCHEMA_VERSION

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        """Default to JSON-compatible enum values for stable idempotency."""

        kwargs.setdefault("mode", "json")
        return super().model_dump(*args, **kwargs)

    def to_v2_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_public_dict(self) -> dict[str, Any]:
        return self.to_v2_dict()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value: object) -> str:
    payload = value if isinstance(value, bytes) else _canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
    text = str(value or "").strip().casefold()
    return text if text in {"complete", "partial", "unavailable"} else fallback  # type: ignore[return-value]


def _snapshot_mapping(record: Mapping[str, object]) -> Mapping[str, object] | None:
    """Return an explicitly contemporaneous portfolio snapshot, if present."""

    for key in ("portfolio_snapshot", "portfolio_context", "holdings_snapshot"):
        candidate = record.get(key)
        if not isinstance(candidate, Mapping):
            continue
        # A free-form ``portfolio: {notes: ...}`` block is not snapshot
        # evidence.  Require a timestamp/date, holdings/weights, or an
        # explicit review state to avoid inferring portfolio authority.
        markers = {
            "as_of_date",
            "as_of",
            "snapshot_at",
            "timestamp",
            "holdings",
            "positions",
            "current_weight",
            "target_weight",
            "portfolio_review_state",
            "review_state",
        }
        if markers.intersection(str(item) for item in candidate):
            return candidate
    return None


def _portfolio_state(record: Mapping[str, object]) -> tuple[PortfolioReviewState, bool]:
    snapshot = _snapshot_mapping(record)
    if snapshot is None:
        return PortfolioReviewState.NOT_APPLICABLE, False

    raw_state = snapshot.get("portfolio_review_state", snapshot.get("review_state", snapshot.get("state")))
    if raw_state is not None:
        text = str(raw_state).strip().casefold()
        try:
            return PortfolioReviewState(text), text != PortfolioReviewState.NOT_APPLICABLE.value
        except ValueError:
            # Legacy portfolio verbs are context only; use a safe review row.
            if text in {"buy", "add", "add_candidate", "increase", "increase_exposure"}:
                return PortfolioReviewState.INCREASE_EXPOSURE_REVIEW, True
            if text in {"trim", "trim_candidate", "decrease", "reduce", "reduce_exposure"}:
                return PortfolioReviewState.REDUCE_EXPOSURE_REVIEW, True
            if text in {"sell", "exit", "close"}:
                return PortfolioReviewState.EXIT_THESIS_REVIEW, True
            if text in {"hold", "maintain", "no_trade"}:
                return PortfolioReviewState.MAINTAIN_REVIEW, True
            return PortfolioReviewState.CONSTRAINTS_BLOCKED, True
    return PortfolioReviewState.MAINTAIN_REVIEW, True


def _legacy_text(record: Mapping[str, object]) -> str | None:
    value = record.get("legacy_action") if "legacy_action" in record else record.get("action", record.get("final_action"))
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _already_v2(record: Mapping[str, object]) -> bool:
    return str(record.get("schema_version") or "").strip() == V2_SCHEMA_VERSION and "research_state" in record


def migrate_legacy_action(record: Mapping[str, object]) -> ResearchStateMigration:
    """Map one v1.x row to a canonical v2 governance row.

    Unknown/missing actions are explicitly mapped to ``manual_review``.  A v2
    row is normalised again rather than returned by reference, making repeated
    migration semantically and byte-equivalent.
    """

    if not isinstance(record, Mapping):
        raise TypeError("legacy record must be a mapping")

    gate_version, gate_checksum = _gate_policy_metadata()
    if _already_v2(record):
        raw_state = record.get("research_state")
        try:
            state = ResearchState(str(raw_state))
        except ValueError:
            state = ResearchState.MANUAL_REVIEW
        portfolio_state, context_allowed = _portfolio_state(record)
        try:
            portfolio_state = PortfolioReviewState(str(record.get("portfolio_review_state") or portfolio_state.value))
        except ValueError:
            portfolio_state = PortfolioReviewState.NOT_APPLICABLE
        analysis_status = _valid_analysis_status(record.get("analysis_status"), fallback="unavailable")
        legacy_action = _legacy_text(record)
        semantics = str(record.get("migration_semantics") or "lossy").strip().casefold()
        if semantics not in {"lossless", "lossy"}:
            semantics = "lossy"
        return ResearchStateMigration(
            research_state=state,
            portfolio_review_state=portfolio_state,
            analysis_status=analysis_status,
            research_promotion_allowed=bool(record.get("research_promotion_allowed", False)) and state is not ResearchState.MANUAL_REVIEW,
            portfolio_review_allowed=bool(record.get("portfolio_review_allowed", context_allowed)) and context_allowed,
            execution_allowed=False,
            legacy_action=legacy_action,
            migration_semantics=semantics,
            migration_version=str(record.get("migration_version") or MIGRATION_VERSION),
            gate_policy_version=str(record.get("gate_policy_version") or gate_version),
            gate_policy_checksum=str(record.get("gate_policy_checksum") or gate_checksum),
            schema_version=V2_SCHEMA_VERSION,
        )

    legacy_action = _legacy_text(record)
    state = research_state_for_legacy_action(legacy_action)
    action_key = legacy_action.casefold() if legacy_action is not None else ""
    # Transactional decrease/exit intent cannot be reconstructed as a public
    # action; those rows are explicitly marked lossy.  Unknown/missing rows
    # also retain a lossy marker because no positive interpretation is safe.
    semantics = "lossy" if action_key in {"trim", "trim_candidate", "sell", "", "unknown"} else "lossless"
    portfolio_state, portfolio_allowed = _portfolio_state(record)
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
    return ResearchStateMigration(
        research_state=state,
        portfolio_review_state=portfolio_state,
        analysis_status=analysis_status,
        research_promotion_allowed=False,
        portfolio_review_allowed=portfolio_allowed,
        execution_allowed=False,
        legacy_action=legacy_action,
        migration_semantics=semantics,
        migration_version=MIGRATION_VERSION,
        gate_policy_version=str(record.get("gate_policy_version") or gate_version),
        gate_policy_checksum=str(record.get("gate_policy_checksum") or gate_checksum),
        schema_version=V2_SCHEMA_VERSION,
    )


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
    "MIGRATION_VERSION",
    "ResearchStateMigration",
    "V2_SCHEMA_VERSION",
    "migrate_legacy_action",
    "migrate_records",
    "log_migration_event",
    "write_migration_report",
]
