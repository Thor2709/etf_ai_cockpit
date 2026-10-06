"""Explicit matching and append-only adjustments for imported statements.

Portfolio import records are source evidence only.  This module is the adapter
between that evidence and the canonical journal replay; it never calculates a
second set of holdings or cash balances.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import sqlite3
from typing import Any, Mapping, Sequence

from etf_cockpit.portfolio.ledger import Ledger, LedgerAccount, LedgerEntry, LedgerPosting
from etf_cockpit.portfolio.ledger_projection import LedgerReplay, replay_ledger
from etf_cockpit.data.market_adjustments import FXObservationStore


ACCOUNT_MAPPING_TYPE = "portfolio_ledger_account_mapping_v1"
ADJUSTMENT_TYPE = "portfolio_ledger_adjustment_v1"
_SOURCE_ENTRY_PREFIX = "portfolio-import-"
_SOURCE_MARKER = "portfolio-source"


class ReconciliationError(ValueError):
    """Raised when source evidence cannot be safely matched or adjusted."""


@dataclass(frozen=True)
class LedgerAccountMapping:
    mapping_id: str
    authority: str
    source_account_id: str
    cash_account_id: str
    position_account_id: str
    clearing_account_id: str
    reviewer: str
    reason: str
    supersedes_mapping_id: str | None
    execution_allowed: bool = False


@dataclass(frozen=True)
class ReconciliationDiscrepancy:
    discrepancy_id: str
    kind: str
    event_id: str | None
    event_key: str | None
    record_type: str | None
    ledger_entry_id: str | None
    detail: str
    adjustment_available: bool


@dataclass(frozen=True)
class PortfolioReconciliation:
    authority: str
    as_of: str
    known_at: str
    replay: LedgerReplay
    active_source_rows: int
    matched_source_rows: int
    quarantined_source_rows: int
    source_events: tuple[dict[str, Any], ...]
    account_mappings: tuple[dict[str, Any], ...]
    journal_entries: tuple[dict[str, Any], ...]
    adjustments: tuple[dict[str, Any], ...]
    discrepancies: tuple[ReconciliationDiscrepancy, ...]
    execution_allowed: bool = False


@dataclass(frozen=True)
class PortfolioAdjustment:
    adjustment_id: str
    event_id: str
    ledger_entry_id: str
    reversed_entry_ids: tuple[str, ...]
    reviewer: str
    reason: str
    execution_allowed: bool = False


def map_source_account(
    connection: sqlite3.Connection,
    *,
    authority: str,
    source_account_id: str,
    cash_account_id: str,
    position_account_id: str,
    clearing_account_id: str,
    reviewer: str,
    reason: str,
    supersedes_mapping_id: str | None = None,
) -> LedgerAccountMapping:
    """Validate an explicit source-to-ledger mapping and return its proposal."""

    authority = _required(authority, "authority")
    if authority not in {"paper", "broker"}:
        raise ReconciliationError("authority must be 'paper' or 'broker'")
    source_account_id = _required(source_account_id, "source_account_id")
    cash_account_id = _required(cash_account_id, "cash_account_id")
    position_account_id = _required(position_account_id, "position_account_id")
    clearing_account_id = _required(clearing_account_id, "clearing_account_id")
    reviewer = _required(reviewer, "reviewer")
    reason = _required(reason, "reason")

    ledger = Ledger(connection)
    cash = ledger.get_account(cash_account_id, authority=authority)
    position = ledger.get_account(position_account_id, authority=authority)
    clearing = ledger.get_account(clearing_account_id, authority=authority)
    _require_role(cash, "cash", "cash_account_id")
    _require_role(position, "position", "position_account_id")
    _require_role(clearing, "general", "clearing_account_id")
    if len({cash_account_id, position_account_id, clearing_account_id}) != 3:
        raise ReconciliationError("cash, position and clearing accounts must be distinct")

    decision = {
        "authority": authority,
        "source_account_id": source_account_id.strip(),
        "cash_account_id": cash_account_id.strip(),
        "position_account_id": position_account_id.strip(),
        "clearing_account_id": clearing_account_id.strip(),
        "reviewer": reviewer.strip(),
        "reason": reason.strip(),
        "supersedes_mapping_id": supersedes_mapping_id,
        "execution_allowed": False,
    }
    mapping_id = _digest(decision)
    return LedgerAccountMapping(
        mapping_id=mapping_id,
        authority=authority,
        source_account_id=source_account_id.strip(),
        cash_account_id=cash_account_id.strip(),
        position_account_id=position_account_id.strip(),
        clearing_account_id=clearing_account_id.strip(),
        reviewer=reviewer.strip(),
        reason=reason.strip(),
        supersedes_mapping_id=supersedes_mapping_id,
    )


def store_account_mapping(store: Any, mapping: LedgerAccountMapping) -> LedgerAccountMapping:
    """Append a verified mapping decision to the transactional store."""

    payload = asdict(mapping)
    payload.pop("mapping_id")
    payload["mapping_hash"] = _digest(payload)
    transaction = nullcontext(store.connection) if store.connection.in_transaction else store.transaction()
    with transaction as connection:
        store.put_in_transaction(
            connection,
            ACCOUNT_MAPPING_TYPE,
            mapping.mapping_id,
            payload,
            immutable=True,
        )
    return mapping


def load_account_mappings(
    store: Any, *, authority: str, known_at: str | None = None
) -> dict[str, LedgerAccountMapping]:
    """Load the latest append-only mapping for each source account.

    With ``known_at`` only mappings recorded at or before that knowledge cutoff are
    eligible, so a historical query never selects a later remapping.
    """

    knowledge_cutoff = None if known_at is None else _instant(known_at, "known_at")
    latest: dict[str, tuple[tuple[str, str], LedgerAccountMapping]] = {}
    for record in store.list(ACCOUNT_MAPPING_TYPE):
        payload = dict(record.payload)
        stored_hash = str(payload.pop("mapping_hash", ""))
        if stored_hash != _digest(payload):
            raise ReconciliationError(f"account mapping integrity failure: {record.entity_id}")
        if payload.get("authority") != authority:
            continue
        if knowledge_cutoff is not None and _instant(record.created_at, "mapping created_at") > knowledge_cutoff:
            continue
        mapping = LedgerAccountMapping(mapping_id=record.entity_id, **payload)
        current = latest.get(mapping.source_account_id)
        if current is None or (record.created_at, record.entity_id) > current[0]:
            latest[mapping.source_account_id] = ((record.created_at, record.entity_id), mapping)
    return {key: value[1] for key, value in latest.items()}


def reconcile_imports(
    connection: sqlite3.Connection,
    source_rows: Sequence[Mapping[str, Any]],
    mappings: Mapping[str, LedgerAccountMapping],
    *,
    authority: str,
    as_of: str,
    known_at: str,
    fx_store: FXObservationStore | None = None,
    base_currency: str | None = None,
) -> PortfolioReconciliation:
    """Match visible statement facts to their journal entries and replay."""

    replay = replay_ledger(
        connection,
        authority=authority,
        as_of=as_of,
        known_at=known_at,
        fx_store=fx_store,
        base_currency=base_currency,
    )
    effective_cutoff = _instant(as_of, "as_of")
    knowledge_cutoff = _instant(known_at, "known_at")
    journal_entries: list[dict[str, Any]] = []
    entry_rows = connection.execute(
        """
        SELECT entry_id, effective_at, recorded_at
        FROM ledger_entries WHERE authority = ? AND status = 'posted'
        ORDER BY effective_at, entry_id
        """,
        (authority,),
    ).fetchall()
    ledger = Ledger(connection)
    for entry_row in entry_rows:
        if not _entry_visible(entry_row[1], entry_row[2], effective_cutoff, knowledge_cutoff):
            continue
        entry = ledger.get_entry(str(entry_row[0]), authority=authority)
        if entry is not None:
            journal_entries.append(_json_mapping(asdict(entry)))
    adjustment_rows: list[dict[str, Any]] = []
    for entity_id, payload_json in connection.execute(
        "SELECT entity_id, payload_json FROM transactional_records WHERE entity_type = ? AND deleted_at IS NULL ORDER BY entity_id",
        (ADJUSTMENT_TYPE,),
    ):
        try:
            payload = json.loads(str(payload_json))
            if not isinstance(payload, dict):
                raise ReconciliationError(f"adjustment integrity failure: {entity_id}")
            stored_hash = str(payload.pop("adjustment_hash", ""))
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            raise ReconciliationError(f"adjustment integrity failure: {entity_id}") from exc
        if (
            not isinstance(payload, dict)
            or str(payload.get("adjustment_id")) != str(entity_id)
            or stored_hash != _digest(payload)
        ):
            raise ReconciliationError(f"adjustment integrity failure: {entity_id}")
        if payload.get("authority") != authority:
            continue
        try:
            if _instant(str(payload.get("decision_time") or ""), "decision_time") > knowledge_cutoff:
                continue
        except ReconciliationError as exc:
            raise ReconciliationError(f"adjustment timing integrity failure: {entity_id}") from exc
        payload["adjustment_hash"] = stored_hash
        adjustment_rows.append(_json_mapping(payload))
    visible: list[Mapping[str, Any]] = []
    audit_rows: list[Mapping[str, Any]] = []
    discrepancies: list[ReconciliationDiscrepancy] = []
    present_ids: set[str] = set()
    matched = 0
    quarantined = 0
    reversed_ids = _reversed_entry_ids(
        connection, authority, effective_cutoff=effective_cutoff, knowledge_cutoff=knowledge_cutoff
    )
    for row in source_rows:
        event_id = str(row.get("event_id") or "") or None
        event_key = str(row.get("event_key") or "") or None
        record_type = str(row.get("record_type") or "") or None
        row_status = str(row.get("staging_status") or "")
        try:
            occurred = _instant(row.get("occurred_at"), "occurred_at")
            decision = _instant(row.get("decision_time"), "decision_time")
            effective_cutoff = _instant(as_of, "as_of")
            knowledge_cutoff = _instant(known_at, "known_at")
        except ReconciliationError as exc:
            discrepancies.append(_discrepancy("invalid_source_timing", event_id, event_key, record_type, None, str(exc), False))
            continue
        if occurred > effective_cutoff or decision > knowledge_cutoff:
            continue
        audit_rows.append(row)
        if row_status == "quarantined":
            quarantined += 1
            discrepancies.append(
                _discrepancy(
                    "quarantined_source_evidence",
                    event_id,
                    event_key,
                    record_type,
                    None,
                    str(row.get("quarantine_reason") or "source row is quarantined"),
                    False,
                )
            )
            continue
        if row_status not in {"accepted", "correction"}:
            continue
        visible.append(row)
        mapping = mappings.get(str(row.get("account_id") or ""))
        if mapping is None:
            discrepancies.append(
                _discrepancy(
                    "missing_account_mapping",
                    event_id,
                    event_key,
                    record_type,
                    None,
                    "source account has no reviewer-approved ledger account mapping",
                    False,
                )
            )
            continue
        try:
            expected = expected_postings(row, mapping)
        except ReconciliationError as exc:
            discrepancies.append(
                _discrepancy(
                    "unsupported_source_mapping",
                    event_id,
                    event_key,
                    record_type,
                    None,
                    str(exc),
                    False,
                )
            )
            continue
        linked_entries = _source_entries(
            connection,
            authority,
            event_id or "",
            effective_cutoff=effective_cutoff,
            knowledge_cutoff=knowledge_cutoff,
        )
        active_entries = [entry for entry in linked_entries if entry.entry_id not in reversed_ids]
        if len(active_entries) > 1:
            discrepancies.append(
                _discrepancy(
                    "multiple_active_ledger_entries",
                    event_id,
                    event_key,
                    record_type,
                    None,
                    "source identity has multiple unreversed journal entries",
                    False,
                )
            )
            continue
        if not active_entries:
            discrepancies.append(
                _discrepancy(
                    "source_without_ledger_entry",
                    event_id,
                    event_key,
                    record_type,
                    source_entry_id(event_id or ""),
                    "accepted statement fact is not yet represented in the canonical journal",
                    True,
                )
            )
        else:
            present_ids.add(active_entries[0].entry_id)
        if active_entries and active_entries[0].postings != expected:
            discrepancies.append(
                _discrepancy(
                    "statement_ledger_mismatch",
                    event_id,
                    event_key,
                    record_type,
                    active_entries[0].entry_id,
                    "journal postings differ from the accepted source fact",
                    True,
                )
            )
        elif active_entries:
            matched += 1
    ledger_only = connection.execute(
        """
        SELECT entry_id, effective_at, description, reversal_of_entry_id
        FROM ledger_entries
        WHERE authority = ? AND status = 'posted' AND entry_id LIKE ?
        ORDER BY effective_at, entry_id
        """,
        (authority, f"{_SOURCE_ENTRY_PREFIX}%"),
    ).fetchall()
    for entry_id, effective_at, _description, reversal_of in ledger_only:
        if str(entry_id) in present_ids:
            continue
        if str(entry_id) in reversed_ids:
            continue
        try:
            if _instant(effective_at, "effective_at") > _instant(as_of, "as_of"):
                continue
            entry = Ledger(connection).get_entry(str(entry_id), authority=authority)
            if entry is None or _instant(entry.recorded_at, "recorded_at") > _instant(known_at, "known_at"):
                continue
        except ReconciliationError:
            continue
        if reversal_of is not None:
            continue
        discrepancies.append(
            _discrepancy(
                "ledger_without_active_source",
                None,
                None,
                None,
                str(entry_id),
                "posted source-linked journal entry has no visible active statement fact",
                True,
            )
        )

    discrepancies.sort(key=lambda item: (item.kind, item.event_id or "", item.ledger_entry_id or ""))
    return PortfolioReconciliation(
        authority=authority,
        as_of=as_of,
        known_at=known_at,
        replay=replay,
        active_source_rows=len(visible),
        matched_source_rows=matched,
        quarantined_source_rows=quarantined,
        source_events=tuple(_json_mapping(row) for row in audit_rows),
        account_mappings=tuple(
            _json_mapping(asdict(mapping))
            for mapping in sorted(mappings.values(), key=lambda item: item.source_account_id)
        ),
        journal_entries=tuple(journal_entries),
        adjustments=tuple(adjustment_rows),
        discrepancies=tuple(discrepancies),
        execution_allowed=False,
    )


def expected_postings(
    row: Mapping[str, Any], mapping: LedgerAccountMapping
) -> tuple[LedgerPosting, ...]:
    """Build journal lines only from explicit supported statement fields."""

    record_type = str(row.get("record_type") or "")
    currency = str(row.get("currency") or "").upper()
    if record_type == "transaction":
        instrument = _required(str(row.get("instrument_id") or ""), "instrument_id")
        quantity = _decimal(row.get("quantity"), "quantity")
        if quantity <= 0:
            raise ReconciliationError("transaction quantity must be positive")
        side = str(row.get("side") or "").lower()
        if side not in {"buy", "sell"}:
            raise ReconciliationError("transaction side is missing or unsupported")
        delta = quantity if side == "buy" else -quantity
        lot_id = _optional_text(row.get("lot_id"))
        lines = [
            _quantity_line(mapping.position_account_id, instrument, delta, lot_id),
            _quantity_line(mapping.clearing_account_id, instrument, -delta, lot_id),
        ]
        settlement = _decimal(row.get("settlement_cash"), "settlement_cash")
        _append_cash(lines, mapping, currency, settlement)
        return tuple(lines)
    if record_type in {"cash", "transfer", "fee", "tax", "income"}:
        amount = _decimal(row.get("cash_amount"), "cash_amount")
        cash_lines: list[LedgerPosting] = []
        _append_cash(cash_lines, mapping, currency, amount)
        return tuple(cash_lines)
    if record_type == "fx":
        from_currency = _required(str(row.get("from_currency") or "").upper(), "from_currency")
        to_currency = _required(str(row.get("to_currency") or "").upper(), "to_currency")
        fx_lines: list[LedgerPosting] = []
        _append_cash(fx_lines, mapping, from_currency, _decimal(row.get("from_amount"), "from_amount"))
        _append_cash(fx_lines, mapping, to_currency, _decimal(row.get("to_amount"), "to_amount"))
        return tuple(fx_lines)
    if record_type == "lot" and row.get("lot_role") == "opening_position":
        instrument = _required(str(row.get("instrument_id") or ""), "instrument_id")
        quantity = _decimal(row.get("quantity"), "quantity")
        if quantity <= 0:
            raise ReconciliationError("opening lot quantity must be positive")
        lot_id = _optional_text(row.get("lot_id"))
        return (
            _quantity_line(mapping.position_account_id, instrument, quantity, lot_id),
            _quantity_line(mapping.clearing_account_id, instrument, -quantity, lot_id),
        )
    if record_type == "corporate_action":
        raise ReconciliationError(
            "corporate-action source requires an explicit canonical CorporateActionStore mapping"
        )
    raise ReconciliationError(f"unsupported source record type: {record_type or 'missing'}")


def apply_source_adjustment(
    store: Any,
    row: Mapping[str, Any],
    mapping: LedgerAccountMapping,
    *,
    authority: str,
    reviewer: str,
    reason: str,
) -> PortfolioAdjustment:
    """Post a source fact, reversing a prior source revision when necessary."""

    _required(reviewer, "reviewer")
    _required(reason, "reason")
    event_id = _required(str(row.get("event_id") or ""), "event_id")
    event_key = _required(str(row.get("event_key") or ""), "event_key")
    postings = expected_postings(row, mapping)
    ledger = Ledger(store.connection)
    key_hash = hashlib.sha256(event_key.encode("utf-8")).hexdigest()
    reversed: list[str] = []
    transaction = nullcontext(store.connection) if store.connection.in_transaction else store.transaction()
    with transaction as connection:
        linked_entries = _source_entries(connection, authority, event_id)
        reversed_ids = _reversed_entry_ids(connection, authority)
        active_same_event = [entry for entry in linked_entries if entry.entry_id not in reversed_ids]
        if len(active_same_event) > 1:
            raise ReconciliationError("multiple unreversed journal entries exist for this source event")
        if active_same_event:
            if active_same_event[0].postings == postings:
                raise ReconciliationError("source evidence already has a canonical ledger entry")
            mismatched_entry = active_same_event[0]
            ledger.reverse(
                mismatched_entry.entry_id,
                entry_id=f"reverse-{event_id}-{hashlib.sha256(mismatched_entry.entry_id.encode()).hexdigest()[:16]}",
                authority=authority,
                effective_at=mismatched_entry.effective_at,
                description=f"Source discrepancy reversal reviewer={reviewer.strip()} reason={reason.strip()}",
            )
            reversed.append(mismatched_entry.entry_id)

        previous_rows = connection.execute(
            """
            SELECT entry_id, effective_at, reversal_of_entry_id
            FROM ledger_entries
            WHERE authority = ? AND status = 'posted' AND description LIKE ?
            ORDER BY recorded_at, entry_id
            """,
            (authority, f"%{_SOURCE_MARKER} event=% key={key_hash}%"),
        ).fetchall()
        reversed_ids = _reversed_entry_ids(connection, authority)
        active_prior = [item for item in previous_rows if str(item[0]) not in reversed_ids]
        if len(active_prior) > 1:
            raise ReconciliationError("multiple unreversed journal entries exist for this source identity")
        entry_id = _next_source_entry_id(connection, authority, event_id)
        adjustment_id = f"adjust-{entry_id}"
        if store.get(ADJUSTMENT_TYPE, adjustment_id) is not None:
            raise ReconciliationError("source adjustment has already been recorded")
        decision_time = _utc_now()
        if active_prior:
            prior_entry_id = str(active_prior[0][0])
            ledger.reverse(
                prior_entry_id,
                entry_id=f"reverse-{event_id}-{hashlib.sha256(prior_entry_id.encode()).hexdigest()[:16]}",
                authority=authority,
                effective_at=str(active_prior[0][1]),
                description=f"Source correction reversal reviewer={reviewer.strip()} reason={reason.strip()}",
            )
            reversed.append(prior_entry_id)
        source_hash = str(row.get("content_hash") or "")
        ledger.post(
            entry_id,
            authority=authority,
            effective_at=_required(str(row.get("occurred_at") or ""), "occurred_at"),
            settlement_at=None,
            postings=postings,
            description=(
                f"{_SOURCE_MARKER} event={event_id} key={key_hash} content={source_hash} "
                f"reviewer={reviewer.strip()} reason={reason.strip()}"
            ),
        )
        payload = {
            "adjustment_id": adjustment_id,
            "event_id": event_id,
            "event_key_hash": key_hash,
            "ledger_entry_id": entry_id,
            "reversed_entry_ids": reversed,
            "authority": authority,
            "reviewer": reviewer.strip(),
            "reason": reason.strip(),
            "decision_time": decision_time,
            "execution_allowed": False,
        }
        payload["adjustment_hash"] = _digest(payload)
        store.put_in_transaction(
            connection,
            ADJUSTMENT_TYPE,
            adjustment_id,
            payload,
            immutable=True,
        )
    return PortfolioAdjustment(
        adjustment_id=adjustment_id,
        event_id=event_id,
        ledger_entry_id=entry_id,
        reversed_entry_ids=tuple(reversed),
        reviewer=reviewer.strip(),
        reason=reason.strip(),
    )


def reverse_orphaned_source_entry(
    store: Any,
    *,
    entry_id: str,
    authority: str,
    reviewer: str,
    reason: str,
) -> str:
    """Explicitly reverse a source-linked entry whose source is no longer active."""

    _required(reviewer, "reviewer")
    _required(reason, "reason")
    ledger = Ledger(store.connection)
    original = ledger.get_entry(entry_id, authority=authority)
    if original is None or _SOURCE_MARKER not in original.description:
        raise ReconciliationError("only an existing source-linked posted entry can be reversed here")
    if original.reversal_of_entry_id is not None:
        raise ReconciliationError("a reversal entry cannot be reversed by this workflow")
    if store.connection.execute(
        "SELECT 1 FROM ledger_entries WHERE authority = ? AND reversal_of_entry_id = ?",
        (authority, entry_id),
    ).fetchone():
        raise ReconciliationError("source-linked entry already has a reversing entry")

    audit_key = hashlib.sha256(
        f"{entry_id}\0{authority}\0{reviewer.strip()}\0{reason.strip()}".encode("utf-8")
    ).hexdigest()
    adjustment_id = f"reverse-adjust-{audit_key}"
    reversal_id = f"reverse-source-{audit_key}"
    if store.get(ADJUSTMENT_TYPE, adjustment_id) is not None:
        raise ReconciliationError("source reversal adjustment has already been recorded")
    payload = {
        "adjustment_id": adjustment_id,
        "event_id": "",
        "event_key_hash": "",
        "ledger_entry_id": reversal_id,
        "reversed_entry_ids": [entry_id],
        "authority": authority,
        "reviewer": reviewer.strip(),
        "reason": reason.strip(),
        "decision_time": _utc_now(),
        "execution_allowed": False,
    }
    payload["adjustment_hash"] = _digest(payload)
    transaction = nullcontext(store.connection) if store.connection.in_transaction else store.transaction()
    with transaction as connection:
        ledger.reverse(
            entry_id,
            entry_id=reversal_id,
            authority=authority,
            effective_at=original.effective_at,
            description=f"Source discrepancy reversal reviewer={reviewer.strip()} reason={reason.strip()}",
        )
        store.put_in_transaction(
            connection,
            ADJUSTMENT_TYPE,
            adjustment_id,
            payload,
            immutable=True,
        )
    return reversal_id


def source_entry_id(event_id: str) -> str:
    return f"{_SOURCE_ENTRY_PREFIX}{_required(event_id, 'event_id')}"


def _entry_visible(
    effective_at: object,
    recorded_at: object,
    effective_cutoff: datetime | None,
    knowledge_cutoff: datetime | None,
) -> bool:
    """Whether a journal row is inside both cutoffs; unparsable timing is never visible."""

    try:
        if effective_cutoff is not None and _instant(str(effective_at), "effective_at") > effective_cutoff:
            return False
        if knowledge_cutoff is not None and _instant(str(recorded_at), "recorded_at") > knowledge_cutoff:
            return False
    except ReconciliationError:
        return False
    return True


def _source_entries(
    connection: sqlite3.Connection,
    authority: str,
    event_id: str,
    *,
    effective_cutoff: datetime | None = None,
    knowledge_cutoff: datetime | None = None,
) -> tuple[LedgerEntry, ...]:
    """Source-linked entries; with cutoffs, only those effective and recorded by then."""

    base = source_entry_id(event_id)
    rows = connection.execute(
        """
        SELECT entry_id, effective_at, recorded_at FROM ledger_entries
        WHERE authority = ? AND status = 'posted'
          AND (entry_id = ? OR entry_id LIKE ?)
        ORDER BY entry_id
        """,
        (authority, base, f"{base}-revision-%"),
    ).fetchall()
    ledger = Ledger(connection)
    entries = tuple(
        entry
        for row in rows
        if _entry_visible(row[1], row[2], effective_cutoff, knowledge_cutoff)
        and (entry := ledger.get_entry(str(row[0]), authority=authority)) is not None
    )
    return entries


def _reversed_entry_ids(
    connection: sqlite3.Connection,
    authority: str,
    *,
    effective_cutoff: datetime | None = None,
    knowledge_cutoff: datetime | None = None,
) -> set[str]:
    """Reversed entry ids; with cutoffs, only reversals effective and recorded by then."""

    return {
        str(row[0])
        for row in connection.execute(
            """
            SELECT reversal_of_entry_id, effective_at, recorded_at FROM ledger_entries
            WHERE authority = ? AND reversal_of_entry_id IS NOT NULL
            """,
            (authority,),
        )
        if _entry_visible(row[1], row[2], effective_cutoff, knowledge_cutoff)
    }


def _next_source_entry_id(
    connection: sqlite3.Connection, authority: str, event_id: str
) -> str:
    base = source_entry_id(event_id)
    entries = connection.execute(
        """
        SELECT entry_id FROM ledger_entries
        WHERE authority = ? AND status = 'posted'
          AND (entry_id = ? OR entry_id LIKE ?)
        ORDER BY entry_id
        """,
        (authority, base, f"{base}-revision-%"),
    ).fetchall()
    if not entries:
        return base
    revision = len(entries) + 1
    while connection.execute(
        "SELECT 1 FROM ledger_entries WHERE authority = ? AND entry_id = ?",
        (authority, f"{base}-revision-{revision}"),
    ).fetchone():
        revision += 1
    return f"{base}-revision-{revision}"


def _append_cash(
    lines: list[LedgerPosting],
    mapping: LedgerAccountMapping,
    currency: str,
    movement: Decimal,
) -> None:
    if not currency or len(currency) != 3 or not currency.isupper():
        raise ReconciliationError("cash posting requires an explicit uppercase currency")
    if movement == 0:
        raise ReconciliationError("zero cash movement cannot be represented as a journal line")
    lines.append(_money_line(mapping.cash_account_id, currency, movement))
    lines.append(_money_line(mapping.clearing_account_id, currency, -movement))


def _money_line(account_id: str, currency: str, movement: Decimal) -> LedgerPosting:
    if movement > 0:
        return LedgerPosting(account_id, currency, debit=movement)
    return LedgerPosting(account_id, currency, credit=-movement)


def _quantity_line(
    account_id: str, instrument_id: str, quantity: Decimal, lot_id: str | None
) -> LedgerPosting:
    return LedgerPosting(
        account_id,
        None,
        instrument_id=instrument_id,
        quantity_delta=quantity,
        lot_id=lot_id,
    )


def _require_role(account: LedgerAccount | None, role: str, field: str) -> None:
    if account is None or account.account_role != role:
        raise ReconciliationError(f"{field} must reference an existing {role} ledger account")


def _discrepancy(
    kind: str,
    event_id: str | None,
    event_key: str | None,
    record_type: str | None,
    ledger_entry_id: str | None,
    detail: str,
    adjustment_available: bool,
) -> ReconciliationDiscrepancy:
    identity = "\0".join((kind, event_id or "", ledger_entry_id or "", detail))
    discrepancy_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return ReconciliationDiscrepancy(
        discrepancy_id,
        kind,
        event_id,
        event_key,
        record_type,
        ledger_entry_id,
        detail,
        adjustment_available,
    )


def _decimal(value: object, field: str) -> Decimal:
    if value is None or str(value).strip() == "":
        raise ReconciliationError(f"{field} is missing")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ReconciliationError(f"{field} is not a decimal") from exc
    if not result.is_finite():
        raise ReconciliationError(f"{field} must be finite")
    return result


def _instant(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ReconciliationError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ReconciliationError(f"{field} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReconciliationError(f"{field} is required")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit_document(reconciliation: PortfolioReconciliation) -> dict[str, Any]:
    """Return a stable JSON-compatible representation without export-time facts."""

    return {
        "contract": "portfolio-reconciliation-audit.v1",
        "authority": reconciliation.authority,
        "as_of": reconciliation.as_of,
        "known_at": reconciliation.known_at,
        "active_source_rows": reconciliation.active_source_rows,
        "matched_source_rows": reconciliation.matched_source_rows,
        "quarantined_source_rows": reconciliation.quarantined_source_rows,
        "source_events": list(reconciliation.source_events),
        "account_mappings": list(reconciliation.account_mappings),
        "journal_entries": list(reconciliation.journal_entries),
        "adjustments": list(reconciliation.adjustments),
        "discrepancies": [_json_mapping(asdict(item)) for item in reconciliation.discrepancies],
        "replay": _json_mapping(asdict(reconciliation.replay)),
        "execution_allowed": False,
    }


def _json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(item) for key, item in value.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return _json_mapping(value)
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return _json_value(value.item())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
