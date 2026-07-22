"""Durable, point-in-time identity master built on the local ACID store.

The master persists source rows, claims and review decisions as immutable
records.  Resolution remains delegated to :mod:`instrument_identity`; this
module adds durable ingestion, exact identifier matching, cross-instrument
duplicate quarantine and presentation-safe projections without creating a
second arbitration path.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.instrument_identity import (
    IdentityClaim,
    IdentityConflict,
    IdentityResolution,
    IdentityResolutionError,
    IdentityReviewDecision,
    resolve_identity,
)
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageSchemaError,
    TransactionalStore,
    storage_layout,
)


IDENTITY_MASTER_SCHEMA_VERSION = 1
IDENTITY_MASTER_CONTRACT = "identity-master.v1"

_META_TYPE = "identity_master_meta"
_META_ID = "schema"
_ROW_TYPE = "identity_source_row_v1"
_CLAIM_TYPE = "identity_claim_v1"
_REVIEW_TYPE = "identity_review_v1"

_OBJECT_TYPES = frozenset(
    {
        "entity",
        "legal_entity",
        "issuer",
        "guarantor",
        "instrument",
        "security",
        "debt_series",
        "fund_vehicle",
        "legal_vehicle",
        "umbrella",
        "subfund",
        "sub_fund",
        "share_class",
        "fund_share_class",
        "listing",
        "quotation",
        "dealing",
        "dealing_channel",
        "broker",
        "broker_contract",
    }
)

# These identifiers identify a security, share class, quotation or broker
# contract and therefore must not be assigned to two canonical instruments.
# Entity-level LEI/CIK values are deliberately excluded: multiple securities
# may lawfully share their issuer's entity identifier.
_UNIQUE_INSTRUMENT_IDENTIFIERS = frozenset(
    {
        "isin",
        "cusip",
        "sedol",
        "figi",
        "national_security_id",
        "broker_contract_id",
    }
)
_EXACT_MATCH_IDENTIFIERS = _UNIQUE_INSTRUMENT_IDENTIFIERS | frozenset({"lei", "cik", "national_id"})


class IdentityMasterSchemaError(RuntimeError):
    """Raised when identity-master evidence cannot be decoded safely."""


@dataclass(frozen=True)
class IdentitySourceRow:
    """One immutable provider or user identity row.

    An empty ``instrument_id`` is permitted at ingestion.  It is assigned only
    when an existing exact identifier maps to one and only one instrument;
    otherwise the row remains explicit unresolved evidence.
    """

    row_id: str
    instrument_id: str
    object_type: str
    object_id: str
    parent_object_id: str | None
    relationship: str | None
    identifiers: Mapping[str, str]
    attributes: Mapping[str, str]
    source: str
    authority: SourceAuthority
    source_id: str
    valid_from: str | None = None
    valid_to: str | None = None
    available_at: str | None = None
    revision: int = 1
    event_type: str = "observation"
    source_checksum: str = ""
    retrieved_at: str | None = None
    manual_override: bool = False


@dataclass(frozen=True)
class IdentityImportResult:
    resolved_row_ids: tuple[str, ...]
    unresolved_row_ids: tuple[str, ...]
    quarantined_row_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]
    execution_allowed: bool = False


class IdentityMasterStore:
    """Append-only identity repository sharing the canonical local store."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        try:
            self._store = TransactionalStore(self.root)
        except (StorageSchemaError, sqlite3.DatabaseError, OSError) as exc:
            raise IdentityMasterSchemaError(f"identity master storage is unavailable: {exc}") from exc
        try:
            self._ensure_schema()
        except Exception:
            self._store.close()
            raise

    def __enter__(self) -> IdentityMasterStore:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self._store.close()

    def import_rows(self, rows: Iterable[IdentitySourceRow]) -> IdentityImportResult:
        """Validate and atomically persist source rows plus derived claims."""

        incoming = tuple(self._normalise_row(row) for row in rows)
        if not incoming:
            return IdentityImportResult((), (), (), (), False)
        row_ids = [row.row_id for row in incoming]
        if len(row_ids) != len(set(row_ids)):
            raise IdentityMasterSchemaError("identity import contains duplicate row_id values")

        try:
            with self._store.transaction() as connection:
                records, result = self._prepare_import(incoming)
                _write_immutable_records(connection, records)
        except (StorageRevisionConflict, sqlite3.DatabaseError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise IdentityMasterSchemaError(f"identity import rejected: {exc}") from exc
        return result

    def _prepare_import(
        self,
        incoming: tuple[IdentitySourceRow, ...],
    ) -> tuple[list[tuple[str, str, Mapping[str, Any]]], IdentityImportResult]:
        """Classify one import while the caller holds the store write lock."""

        existing_claims = self._load_claims()
        explicit_claims = tuple(
            claim
            for row in incoming
            if row.instrument_id and (row.identifiers or row.attributes)
            for claim in self._claims_for_row(row)
        )
        match_claims = existing_claims + explicit_claims

        resolved_rows: list[IdentitySourceRow] = []
        unresolved_ids: list[str] = []
        ambiguous_ids: set[str] = set()
        ambiguous_matches: dict[str, tuple[str, ...]] = {}
        for row in incoming:
            if not row.identifiers and not row.attributes:
                unresolved_ids.append(row.row_id)
                continue
            if row.instrument_id:
                resolved_rows.append(row)
                continue
            candidates = self._exact_match_candidates(row, match_claims)
            if len(candidates) == 1:
                instrument_id = next(iter(candidates))
                resolved_rows.append(
                    replace(
                        row,
                        instrument_id=instrument_id,
                        object_id=row.object_id or instrument_id,
                    )
                )
            elif len(candidates) > 1:
                ambiguous_ids.add(row.row_id)
                ambiguous_matches[row.row_id] = tuple(sorted(candidates))
            else:
                unresolved_ids.append(row.row_id)

        resolved_by_id = {row.row_id: row for row in resolved_rows}
        persisted_rows = tuple(resolved_by_id.get(row.row_id, row) for row in incoming)
        new_claims = tuple(claim for row in resolved_rows for claim in self._claims_for_row(row))
        all_claims = existing_claims + new_claims
        duplicate_groups = _duplicate_identifier_groups(all_claims)

        quarantined_ids = set(ambiguous_ids)
        conflict_ids: set[str] = {
            _hash(
                {
                    "kind": "ambiguous_exact_identity_match",
                    "row_id": row_id,
                    "candidate_instruments": candidates,
                }
            )[:20]
            for row_id, candidates in ambiguous_matches.items()
        }
        for row in persisted_rows:
            if not row.instrument_id:
                continue
            for field, raw_value in row.identifiers.items():
                key = (_field(field), _identifier_value(field, raw_value))
                instruments = duplicate_groups.get(key, ())
                if len(instruments) > 1 and _field(field) in _UNIQUE_INSTRUMENT_IDENTIFIERS:
                    quarantined_ids.add(row.row_id)
                    conflict_ids.add(_duplicate_conflict_id(key[0], key[1], instruments))

        records: list[tuple[str, str, Mapping[str, Any]]] = []
        records.extend((_ROW_TYPE, row.row_id, _row_payload(row)) for row in persisted_rows)
        records.extend((_CLAIM_TYPE, _claim_key(claim), _claim_payload(claim)) for claim in new_claims)

        resolved_row_id_set = {row.row_id for row in resolved_rows}
        resolved_ids = tuple(
            row.row_id
            for row in persisted_rows
            if row.row_id in resolved_row_id_set and row.row_id not in quarantined_ids
        )
        return (
            records,
            IdentityImportResult(
                resolved_row_ids=resolved_ids,
                unresolved_row_ids=tuple(unresolved_ids),
                quarantined_row_ids=tuple(row.row_id for row in persisted_rows if row.row_id in quarantined_ids),
                conflict_ids=tuple(sorted(conflict_ids)),
                execution_allowed=False,
            ),
        )

    def append_claims(self, claims: Iterable[IdentityClaim]) -> tuple[str, ...]:
        """Persist validated claims atomically and idempotently."""

        items = tuple(_normalise_claim(claim) for claim in claims)
        if not items:
            return ()
        records = tuple((_CLAIM_TYPE, _claim_key(claim), _claim_payload(claim)) for claim in items)
        try:
            self._store.put_many(records, immutable=True)
        except (StorageRevisionConflict, sqlite3.DatabaseError, ValueError, TypeError) as exc:
            raise IdentityMasterSchemaError(f"identity claims rejected: {exc}") from exc
        return tuple(record_id for _, record_id, _ in records)

    def append_reviews(self, decisions: Iterable[IdentityReviewDecision]) -> tuple[str, ...]:
        """Persist human review decisions as immutable conflict revisions."""

        items = tuple(_normalise_review(decision) for decision in decisions)
        if not items:
            return ()
        records = tuple((_REVIEW_TYPE, _review_key(item), _review_payload(item)) for item in items)
        try:
            self._store.put_many(records, immutable=True)
        except (StorageRevisionConflict, sqlite3.DatabaseError, ValueError, TypeError) as exc:
            raise IdentityMasterSchemaError(f"identity reviews rejected: {exc}") from exc
        return tuple(record_id for _, record_id, _ in records)

    def resolve(
        self,
        instrument_id: str,
        *,
        effective_at: str | datetime | None = None,
        decision_time: str | datetime | None = None,
    ) -> IdentityResolution:
        """Resolve one instrument and apply persisted reviews at the cut-off."""

        canonical_id = str(instrument_id).strip()
        if not canonical_id:
            raise ValueError("instrument_id must be non-empty")
        all_claims = self._load_claims()
        claims = tuple(claim for claim in all_claims if claim.instrument_id == canonical_id)
        if not claims:
            raise KeyError(f"identity evidence unavailable for {canonical_id}")

        initial = resolve_identity(
            claims,
            effective_at=effective_at,
            decision_time=decision_time,
        )
        conflict_ids = {item.conflict_id for item in initial.conflicts}
        reviews = tuple(item for item in self._load_reviews() if item.conflict_id in conflict_ids)
        resolution = (
            resolve_identity(
                claims,
                effective_at=effective_at,
                decision_time=decision_time,
                review_decisions=reviews,
            )
            if reviews
            else initial
        )
        duplicates = self._duplicate_conflicts(
            canonical_id,
            all_claims,
            effective_at=effective_at,
            decision_time=decision_time,
        )
        return _with_duplicate_conflicts(resolution, duplicates)

    def projection(
        self,
        instrument_id: str,
        *,
        effective_at: str | datetime | None = None,
        decision_time: str | datetime | None = None,
    ) -> dict[str, object]:
        """Return a read-only graph/conflict/history projection for the UI."""

        resolution = self.resolve(
            instrument_id,
            effective_at=effective_at,
            decision_time=decision_time,
        )
        known_reviews = _known_reviews(
            self._load_reviews(),
            {conflict.conflict_id for conflict in resolution.conflicts},
            decision_time,
        )
        return {
            "status": "available",
            "instrument_id": resolution.identity.instrument_id,
            "identity_confidence": resolution.identity.confidence,
            "identity_status": "manual_review" if resolution.requires_manual_review else "resolved",
            "identity_resolution_state": resolution.resolution_state,
            "identity_decision_id": resolution.decision_id,
            "identity_conflict_ids": [item.conflict_id for item in resolution.conflicts],
            "identity_effective_at": resolution.effective_at or "latest",
            "identity_decision_time": resolution.decision_time or "latest",
            "identity_objects": [asdict(item) for item in resolution.objects],
            "identity_history": [asdict(item) for item in resolution.history],
            "identity_conflicts": [asdict(item) for item in resolution.conflicts],
            "identity_reviews": [asdict(item) | {"decision_id": item.decision_id} for item in known_reviews],
            "warnings": list(resolution.warnings),
            "execution_allowed": False,
        }

    def _ensure_schema(self) -> None:
        expected = {"schema_version": IDENTITY_MASTER_SCHEMA_VERSION, "contract": IDENTITY_MASTER_CONTRACT}
        try:
            record = self._store.get(_META_TYPE, _META_ID)
        except (sqlite3.DatabaseError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise IdentityMasterSchemaError(f"identity master schema marker is corrupt: {exc}") from exc
        if record is None:
            try:
                self._store.put_many(((_META_TYPE, _META_ID, expected),), immutable=True)
                record = self._store.get(_META_TYPE, _META_ID)
            except (StorageRevisionConflict, sqlite3.DatabaseError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise IdentityMasterSchemaError(f"identity master schema marker is unavailable: {exc}") from exc
        if record is None or not isinstance(record.payload, dict):
            raise IdentityMasterSchemaError("identity master schema marker is unavailable")
        try:
            version = int(record.payload["schema_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityMasterSchemaError("identity master schema marker is corrupt") from exc
        if version > IDENTITY_MASTER_SCHEMA_VERSION:
            raise IdentityMasterSchemaError(
                f"identity master schema {version} is newer than supported version {IDENTITY_MASTER_SCHEMA_VERSION}"
            )
        if version != IDENTITY_MASTER_SCHEMA_VERSION or record.payload.get("contract") != IDENTITY_MASTER_CONTRACT:
            raise IdentityMasterSchemaError("identity master schema marker is unsupported or corrupt")
        try:
            for stored in self._store.list(_ROW_TYPE):
                self._normalise_row(IdentitySourceRow(**_payload_body(stored.payload, "row")))
            for stored in self._store.list(_CLAIM_TYPE):
                _claim_from_payload(stored.payload)
            for stored in self._store.list(_REVIEW_TYPE):
                _review_from_payload(stored.payload)
        except IdentityMasterSchemaError:
            raise
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise IdentityMasterSchemaError(f"identity master record is corrupt: {exc}") from exc

    def _normalise_row(self, row: IdentitySourceRow) -> IdentitySourceRow:
        if not isinstance(row, IdentitySourceRow):
            raise IdentityMasterSchemaError("identity imports must contain IdentitySourceRow values")
        try:
            authority = row.authority if isinstance(row.authority, SourceAuthority) else SourceAuthority(str(row.authority))
        except ValueError as exc:
            raise IdentityMasterSchemaError(f"unknown identity authority: {row.authority!r}") from exc
        row_id = str(row.row_id).strip()
        instrument_id = str(row.instrument_id).strip()
        object_type = str(row.object_type).strip().lower()
        object_id = str(row.object_id).strip()
        if not row_id or not object_type:
            raise IdentityMasterSchemaError("identity row_id and object_type must be non-empty")
        if object_type not in _OBJECT_TYPES:
            raise IdentityMasterSchemaError(f"unsupported identity object_type: {object_type}")
        if instrument_id and not object_id:
            object_id = instrument_id
        if not isinstance(row.identifiers, Mapping) or not isinstance(row.attributes, Mapping):
            raise IdentityMasterSchemaError("identity identifiers and attributes must be mappings")
        identifiers = _string_mapping(row.identifiers, "identifier")
        attributes = _string_mapping(row.attributes, "attribute")
        if set(identifiers).intersection(attributes):
            raise IdentityMasterSchemaError("identity row duplicates a field across identifiers and attributes")
        source = str(row.source).strip()
        source_id = str(row.source_id).strip()
        if not source or not source_id:
            raise IdentityMasterSchemaError("identity source and source_id must be non-empty")
        revision = _positive_revision(row.revision)
        valid_from = _optional_timestamp(row.valid_from, "valid_from")
        valid_to = _optional_timestamp(row.valid_to, "valid_to")
        available_at = _optional_timestamp(row.available_at, "available_at", require_timezone=True)
        retrieved_at = _optional_timestamp(row.retrieved_at, "retrieved_at", require_timezone=True)
        if valid_from and valid_to and _as_datetime(valid_to) <= _as_datetime(valid_from):
            raise IdentityMasterSchemaError("identity valid_to must be later than valid_from")
        parent = str(row.parent_object_id).strip() if row.parent_object_id else None
        relationship = str(row.relationship).strip().lower() if row.relationship else None
        if parent == object_id and parent:
            raise IdentityMasterSchemaError("identity object cannot be its own parent")
        if parent and not relationship:
            raise IdentityMasterSchemaError("identity parent_object_id requires a relationship")
        source_checksum = str(row.source_checksum or "").strip().lower()
        if source_checksum and (
            len(source_checksum) != 64 or any(character not in "0123456789abcdef" for character in source_checksum)
        ):
            raise IdentityMasterSchemaError("identity source_checksum must be a SHA-256 hex digest")
        return IdentitySourceRow(
            row_id=row_id,
            instrument_id=instrument_id,
            object_type=object_type,
            object_id=object_id,
            parent_object_id=parent,
            relationship=relationship,
            identifiers=identifiers,
            attributes=attributes,
            source=source,
            authority=authority,
            source_id=source_id,
            valid_from=valid_from,
            valid_to=valid_to,
            available_at=available_at,
            revision=revision,
            event_type=str(row.event_type or "observation").strip().lower(),
            source_checksum=source_checksum,
            retrieved_at=retrieved_at,
            manual_override=bool(row.manual_override),
        )

    @staticmethod
    def _claims_for_row(row: IdentitySourceRow) -> tuple[IdentityClaim, ...]:
        if not row.instrument_id:
            return ()
        values = dict(row.identifiers) | dict(row.attributes)
        return tuple(
            IdentityClaim(
                instrument_id=row.instrument_id,
                field=field,
                value=value,
                source=row.source,
                authority=row.authority,
                source_id=row.source_id,
                manual_override=row.manual_override,
                object_type=row.object_type,
                object_id=row.object_id or row.instrument_id,
                parent_object_id=row.parent_object_id,
                relationship=row.relationship,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                available_at=row.available_at,
                revision=row.revision,
                event_type=row.event_type,
            )
            for field, value in sorted(values.items())
            if value
        )

    @staticmethod
    def _exact_match_candidates(row: IdentitySourceRow, claims: tuple[IdentityClaim, ...]) -> set[str]:
        # Automatic assignment requires a decision-time boundary.  Without it,
        # a later claim could silently become evidence for an earlier row.
        if row.available_at is None:
            return set()
        effective_at = row.valid_from or row.available_at
        candidates: set[str] = set()
        for field, value in row.identifiers.items():
            canonical_field = _field(field)
            if canonical_field not in _EXACT_MATCH_IDENTIFIERS or not value:
                continue
            normalised = _identifier_value(canonical_field, value)
            matching = tuple(
                claim
                for claim in claims
                if _field(claim.field) == canonical_field
                and _identifier_value(canonical_field, claim.value) == normalised
            )
            try:
                eligible = tuple(
                    claim
                    for claim in matching
                    if _claim_is_eligible(
                        claim,
                        effective_at=effective_at,
                        decision_time=row.available_at,
                    )
                )
            except IdentityResolutionError:
                # Ambiguous availability is not permission to choose the other
                # candidate.  Keep the importing row explicitly unresolved.
                return set()
            candidates.update(claim.instrument_id for claim in eligible)
        return candidates

    def _load_claims(self) -> tuple[IdentityClaim, ...]:
        try:
            records = self._store.list(_CLAIM_TYPE)
            return tuple(_claim_from_payload(record.payload) for record in records)
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise IdentityMasterSchemaError(f"identity claim store is corrupt: {exc}") from exc

    def _load_reviews(self) -> tuple[IdentityReviewDecision, ...]:
        try:
            records = self._store.list(_REVIEW_TYPE)
            return tuple(_review_from_payload(record.payload) for record in records)
        except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise IdentityMasterSchemaError(f"identity review store is corrupt: {exc}") from exc

    @staticmethod
    def _duplicate_conflicts(
        instrument_id: str,
        claims: tuple[IdentityClaim, ...],
        *,
        effective_at: str | datetime | None,
        decision_time: str | datetime | None,
    ) -> tuple[IdentityConflict, ...]:
        eligible = tuple(
            claim
            for claim in claims
            if _claim_is_eligible(claim, effective_at=effective_at, decision_time=decision_time)
        )
        groups = _duplicate_identifier_groups(eligible)
        conflicts: list[IdentityConflict] = []
        for (field, value), instruments in sorted(groups.items()):
            if instrument_id not in instruments or len(instruments) < 2:
                continue
            candidates = tuple(
                claim
                for claim in eligible
                if _field(claim.field) == field and _identifier_value(field, claim.value) == value
            )
            conflict_id = _duplicate_conflict_id(field, value, instruments)
            conflicts.append(
                IdentityConflict(
                    instrument_id=instrument_id,
                    field=field,
                    values=(value,),
                    source_ids=tuple(sorted({claim.source_id or "unknown" for claim in candidates})),
                    canonical_value="",
                    requires_manual_review=True,
                    reason=(
                        f"Duplicate {field} {value!r} is retained for instruments "
                        f"{', '.join(instruments)}; automatic identity merge is forbidden."
                    ),
                    conflict_id=conflict_id,
                    object_type="identity_master",
                    object_id=instrument_id,
                    reason_code="duplicate_identity",
                    resolution_status="quarantined",
                )
            )
        return tuple(conflicts)


def identity_master_exists(root: Path) -> bool:
    """Return whether a root already contains an identity-master marker.

    The check is read-only so a presentation read never creates a database or
    mutates an unrelated transactional store.  An unreadable existing store is
    an explicit error rather than permission to fall back to stale evidence.
    """

    path = storage_layout(root).transactional_path
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'transactional_records'"
            ).fetchone()
            if table is None:
                return False
            marker = connection.execute(
                "SELECT 1 FROM transactional_records WHERE entity_type = ? AND entity_id = ? AND deleted_at IS NULL",
                (_META_TYPE, _META_ID),
            ).fetchone()
            return marker is not None
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise IdentityMasterSchemaError(f"identity master store is unreadable: {exc}") from exc


def _normalise_claim(claim: IdentityClaim) -> IdentityClaim:
    if not isinstance(claim, IdentityClaim):
        raise IdentityMasterSchemaError("identity claims must be IdentityClaim values")
    try:
        authority = claim.authority if isinstance(claim.authority, SourceAuthority) else SourceAuthority(str(claim.authority))
    except ValueError as exc:
        raise IdentityMasterSchemaError(f"unknown identity authority: {claim.authority!r}") from exc
    instrument_id = str(claim.instrument_id).strip()
    field = _field(claim.field)
    object_type = str(claim.object_type or "instrument").strip().lower()
    object_id = str(claim.object_id or instrument_id).strip()
    if not instrument_id or not field or not object_id:
        raise IdentityMasterSchemaError("identity claim instrument, field and object must be non-empty")
    if object_type not in _OBJECT_TYPES:
        raise IdentityMasterSchemaError(f"unsupported identity object_type: {object_type}")
    source = str(claim.source).strip()
    source_id = str(claim.source_id).strip()
    if not source or not source_id:
        raise IdentityMasterSchemaError("identity claims require source and source_id")
    revision = _positive_revision(claim.revision)
    valid_from = _optional_timestamp(claim.valid_from, "valid_from")
    valid_to = _optional_timestamp(claim.valid_to, "valid_to")
    available_at = _optional_timestamp(claim.available_at, "available_at", require_timezone=True)
    if valid_from and valid_to and _as_datetime(valid_to) <= _as_datetime(valid_from):
        raise IdentityMasterSchemaError("identity valid_to must be later than valid_from")
    parent = str(claim.parent_object_id).strip() if claim.parent_object_id else None
    relationship = str(claim.relationship).strip().lower() if claim.relationship else None
    if parent == object_id and parent:
        raise IdentityMasterSchemaError("identity object cannot be its own parent")
    return IdentityClaim(
        instrument_id=instrument_id,
        field=field,
        value=str(claim.value or "").strip(),
        source=source,
        authority=authority,
        source_id=source_id,
        as_of=claim.as_of,
        manual_override=bool(claim.manual_override),
        object_type=object_type,
        object_id=object_id,
        parent_object_id=parent,
        relationship=relationship,
        valid_from=valid_from,
        valid_to=valid_to,
        available_at=available_at,
        revision=revision,
        event_type=str(claim.event_type or "observation").strip().lower(),
    )


def _normalise_review(decision: IdentityReviewDecision) -> IdentityReviewDecision:
    if not isinstance(decision, IdentityReviewDecision):
        raise IdentityMasterSchemaError("identity reviews must be IdentityReviewDecision values")
    conflict_id = str(decision.conflict_id).strip()
    source_id = str(decision.selected_source_id).strip()
    reviewer = str(decision.reviewer).strip()
    reason = str(decision.reason).strip()
    if not all((conflict_id, source_id, reviewer, reason)):
        raise IdentityMasterSchemaError("identity review requires conflict, candidate, reviewer and reason")
    return IdentityReviewDecision(
        conflict_id=conflict_id,
        selected_source_id=source_id,
        reviewer=reviewer,
        reviewed_at=_timestamp(decision.reviewed_at, "reviewed_at", require_timezone=True),
        reason=reason,
        revision=_positive_revision(decision.revision),
    )


def _write_immutable_records(
    connection: sqlite3.Connection,
    records: Iterable[tuple[str, str, Mapping[str, Any]]],
) -> None:
    """Write already-validated identity records inside an existing transaction."""

    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    for entity_type, entity_id, payload in records:
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        previous = connection.execute(
            "SELECT payload_json FROM transactional_records WHERE entity_type = ? AND entity_id = ?",
            (entity_type, entity_id),
        ).fetchone()
        if previous is not None:
            if dict(json.loads(str(previous[0]))) != dict(payload):
                raise StorageRevisionConflict(
                    f"immutable record already exists with different content: {entity_id}"
                )
            continue
        connection.execute(
            """
            INSERT INTO transactional_records
                (entity_type, entity_id, payload_json, revision, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, 1, ?, ?, NULL)
            """,
            (entity_type, entity_id, encoded, now, now),
        )


def _row_payload(row: IdentitySourceRow) -> dict[str, Any]:
    payload = asdict(row)
    payload["authority"] = row.authority.value
    return {"schema_version": IDENTITY_MASTER_SCHEMA_VERSION, "contract": IDENTITY_MASTER_CONTRACT, "row": payload}


def _claim_payload(claim: IdentityClaim) -> dict[str, Any]:
    payload = asdict(claim)
    payload["authority"] = claim.authority.value
    return {"schema_version": IDENTITY_MASTER_SCHEMA_VERSION, "contract": IDENTITY_MASTER_CONTRACT, "claim": payload}


def _review_payload(decision: IdentityReviewDecision) -> dict[str, Any]:
    return {
        "schema_version": IDENTITY_MASTER_SCHEMA_VERSION,
        "contract": IDENTITY_MASTER_CONTRACT,
        "review": asdict(decision),
    }


def _claim_from_payload(payload: Mapping[str, Any]) -> IdentityClaim:
    body = _payload_body(payload, "claim")
    return _normalise_claim(IdentityClaim(**body))


def _review_from_payload(payload: Mapping[str, Any]) -> IdentityReviewDecision:
    body = _payload_body(payload, "review")
    return _normalise_review(IdentityReviewDecision(**body))


def _payload_body(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise IdentityMasterSchemaError("identity record payload is not a mapping")
    try:
        version = int(payload["schema_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise IdentityMasterSchemaError("identity record schema version is missing") from exc
    if version > IDENTITY_MASTER_SCHEMA_VERSION:
        raise IdentityMasterSchemaError(f"identity record schema {version} is newer than supported")
    if version != IDENTITY_MASTER_SCHEMA_VERSION or payload.get("contract") != IDENTITY_MASTER_CONTRACT:
        raise IdentityMasterSchemaError("identity record contract is unsupported")
    body = payload.get(key)
    if not isinstance(body, Mapping):
        raise IdentityMasterSchemaError(f"identity record is missing {key}")
    return dict(body)


def _claim_key(claim: IdentityClaim) -> str:
    logical = {
        "instrument_id": claim.instrument_id,
        "object_type": claim.object_type,
        "object_id": claim.object_id,
        "field": _field(claim.field),
        "source_id": claim.source_id,
        "revision": claim.revision,
    }
    return _hash(logical)


def _review_key(decision: IdentityReviewDecision) -> str:
    return _hash({"conflict_id": decision.conflict_id, "revision": decision.revision})


def _duplicate_identifier_groups(
    claims: Iterable[IdentityClaim],
) -> dict[tuple[str, str], tuple[str, ...]]:
    groups: dict[tuple[str, str], set[str]] = {}
    for claim in claims:
        field = _field(claim.field)
        if field not in _UNIQUE_INSTRUMENT_IDENTIFIERS:
            continue
        value = _identifier_value(field, claim.value)
        if not value:
            continue
        groups.setdefault((field, value), set()).add(claim.instrument_id)
    return {key: tuple(sorted(instruments)) for key, instruments in groups.items() if len(instruments) > 1}


def _duplicate_conflict_id(field: str, value: str, instruments: tuple[str, ...]) -> str:
    return _hash({"kind": "duplicate_identity", "field": field, "value": value, "instruments": instruments})[:20]


def _with_duplicate_conflicts(
    resolution: IdentityResolution,
    duplicate_conflicts: tuple[IdentityConflict, ...],
) -> IdentityResolution:
    if not duplicate_conflicts:
        return resolution
    conflicts = resolution.conflicts + duplicate_conflicts
    warnings = tuple(dict.fromkeys((*resolution.warnings, "duplicate_identity_requires_manual_review")))
    identity = replace(
        resolution.identity,
        confidence="manual_review",
        warnings=tuple(dict.fromkeys((*resolution.identity.warnings, "duplicate_identity_requires_manual_review"))),
    )
    decision_id = _hash(
        {
            "base_decision_id": resolution.decision_id,
            "duplicate_conflict_ids": [item.conflict_id for item in duplicate_conflicts],
        }
    )
    return replace(
        resolution,
        identity=identity,
        conflicts=conflicts,
        requires_manual_review=True,
        warnings=warnings,
        decision_id=decision_id,
        resolution_state="quarantined",
        execution_allowed=False,
    )


def _known_reviews(
    decisions: tuple[IdentityReviewDecision, ...],
    conflict_ids: set[str],
    decision_time: str | datetime | None,
) -> tuple[IdentityReviewDecision, ...]:
    cutoff = _cutoff(decision_time)
    return tuple(
        decision
        for decision in decisions
        if decision.conflict_id in conflict_ids
        and (cutoff is None or _as_datetime(decision.reviewed_at) <= cutoff)
    )


def _claim_is_eligible(
    claim: IdentityClaim,
    *,
    effective_at: str | datetime | None,
    decision_time: str | datetime | None,
) -> bool:
    effective = _cutoff(effective_at)
    decision = _cutoff(decision_time)
    if effective is None and decision is not None:
        effective = decision
    if decision is None and effective is not None:
        decision = effective
    if decision is not None:
        if claim.available_at is None:
            raise IdentityResolutionError("point-in-time identity claims require available_at")
        if claim.valid_from is None:
            raise IdentityResolutionError("point-in-time identity claims require valid_from")
        if _as_datetime(claim.available_at) > decision:
            return False
    if effective is not None:
        if claim.valid_from and _as_datetime(claim.valid_from) > effective:
            return False
        if claim.valid_to and _as_datetime(claim.valid_to) <= effective:
            return False
    return True


def _field(value: object) -> str:
    aliases = {
        "symbol": "ticker",
        "mic_code": "mic",
        "shareclass": "share_class",
        "share-class": "share_class",
        "listing_id": "listing",
    }
    field = str(value or "").strip().lower()
    return aliases.get(field, field)


def _identifier_value(field: object, value: object) -> str:
    text = str(value or "").strip()
    return text.upper() if _field(field) in _EXACT_MATCH_IDENTIFIERS else text


def _string_mapping(mapping: Mapping[str, object], label: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for raw_key, raw_value in mapping.items():
        key = _field(raw_key)
        if not key:
            raise IdentityMasterSchemaError(f"identity {label} name must be non-empty")
        value = str(raw_value or "").strip()
        if value:
            output[key] = _identifier_value(key, value) if label == "identifier" else value
    return dict(sorted(output.items()))


def _positive_revision(value: object) -> int:
    if isinstance(value, bool):
        raise IdentityMasterSchemaError("identity revision must be a positive integer")
    try:
        revision = int(str(value))
    except (TypeError, ValueError) as exc:
        raise IdentityMasterSchemaError("identity revision must be a positive integer") from exc
    if revision < 1:
        raise IdentityMasterSchemaError("identity revision must be a positive integer")
    return revision


def _optional_timestamp(value: str | datetime | None, field: str, *, require_timezone: bool = False) -> str | None:
    return None if value is None or str(value).strip() == "" else _timestamp(value, field, require_timezone=require_timezone)


def _timestamp(value: str | datetime, field: str, *, require_timezone: bool = False) -> str:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise IdentityMasterSchemaError(f"identity {field} must be an ISO timestamp") from exc
    if require_timezone and parsed.tzinfo is None:
        raise IdentityMasterSchemaError(f"identity {field} must include a timezone")
    if parsed.tzinfo is None:
        return parsed.isoformat()
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cutoff(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    return _as_datetime(_timestamp(value, "cutoff", require_timezone=True))


def _hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
