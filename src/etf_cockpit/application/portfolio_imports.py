"""Application facade for portfolio import staging and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from etf_cockpit.core.atomic_io import atomic_write_bytes
from etf_cockpit.data.import_export import ImportPreview
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.data.portfolio_imports import (
    PortfolioCommitResult,
    PortfolioImportStore,
)
from etf_cockpit.data.market_adjustments import FXObservationStore
from etf_cockpit.portfolio.reconciliation import (
    LedgerAccountMapping,
    PortfolioAdjustment,
    PortfolioReconciliation,
    apply_source_adjustment,
    audit_document,
    load_account_mappings,
    map_source_account,
    reconcile_imports,
    reverse_orphaned_source_entry,
    store_account_mapping,
)


@dataclass(frozen=True)
class PortfolioImportSummary:
    status: str
    batches: int
    active_rows: int
    quarantined_rows: int
    holding_positions: int
    cash_balances: int
    execution_allowed: bool = False


class PortfolioImportApplication:
    """Presentation-safe orchestration for local portfolio evidence."""

    def __init__(self, root: Path):
        self._store = PortfolioImportStore(root)

    def preview(
        self,
        path: Path,
        *,
        source_format: str = "canonical",
        numeric_locale: str = "en_US",
        source_system: str | None = None,
        provider_id: str | None = None,
    ) -> ImportPreview:
        return self._store.preview(
            path,
            source_format=source_format,
            numeric_locale=numeric_locale,
            source_system=source_system,
            provider_id=provider_id,
        )

    def commit(self, preview: ImportPreview | str) -> PortfolioCommitResult:
        return self._store.commit(preview)

    def rollback(self, batch_id: str, *, reason: str) -> bool:
        return self._store.rollback(batch_id, reason=reason)

    def reconcile(
        self,
        *,
        authority: str = "broker",
        as_of: str,
        known_at: str,
        fx_store: FXObservationStore | None = None,
        base_currency: str | None = None,
    ) -> PortfolioReconciliation:
        with TransactionalStore(self._store.root) as store:
            with store.read_transaction():
                source_events = self._store.source_events(
                    as_of=as_of, known_at=known_at, store=store
                )
                mappings = load_account_mappings(store, authority=authority)
                return reconcile_imports(
                    store.connection,
                    source_events.to_dict(orient="records"),
                    mappings,
                    authority=authority,
                    as_of=as_of,
                    known_at=known_at,
                    fx_store=fx_store,
                    base_currency=base_currency,
                )

    def map_source_account(
        self,
        *,
        authority: str,
        source_account_id: str,
        cash_account_id: str,
        position_account_id: str,
        clearing_account_id: str,
        reviewer: str,
        reason: str,
    ) -> LedgerAccountMapping:
        with TransactionalStore(self._store.root) as store:
            with store.transaction():
                current = load_account_mappings(store, authority=authority).get(source_account_id)
                mapping = map_source_account(
                    store.connection,
                    authority=authority,
                    source_account_id=source_account_id,
                    cash_account_id=cash_account_id,
                    position_account_id=position_account_id,
                    clearing_account_id=clearing_account_id,
                    reviewer=reviewer,
                    reason=reason,
                    supersedes_mapping_id=None if current is None else current.mapping_id,
                )
                return store_account_mapping(store, mapping)

    def apply_adjustment(
        self,
        event_id: str,
        *,
        authority: str,
        as_of: str,
        known_at: str,
        reviewer: str,
        reason: str,
    ) -> PortfolioAdjustment:
        with TransactionalStore(self._store.root) as store:
            with store.transaction():
                visible = self._store.source_events(
                    as_of=as_of, known_at=known_at, store=store
                )
                if "event_id" not in visible.columns:
                    raise ValueError("adjustment requires one active, visible source event")
                rows = visible.loc[
                    visible["event_id"].astype(str).eq(str(event_id))
                    & visible["staging_status"].isin(["accepted", "correction"])
                ]
                if len(rows) != 1:
                    raise ValueError("adjustment requires one active, visible source event")
                row = rows.iloc[0].to_dict()
                mappings = load_account_mappings(store, authority=authority)
                mapping = mappings.get(str(row.get("account_id") or ""))
                if mapping is None:
                    raise ValueError("adjustment requires a reviewer-approved source account mapping")
                return apply_source_adjustment(
                    store,
                    row,
                    mapping,
                    authority=authority,
                    reviewer=reviewer,
                    reason=reason,
                )

    def reverse_orphaned_entry(
        self,
        entry_id: str,
        *,
        authority: str,
        reviewer: str,
        reason: str,
    ) -> str:
        with TransactionalStore(self._store.root) as store:
            with store.transaction():
                from etf_cockpit.portfolio.ledger import Ledger

                entry = Ledger(store.connection).get_entry(entry_id, authority=authority)
                if entry is None:
                    raise ValueError("orphan reversal requires an existing source-linked journal entry")
                event_marker = " event="
                source_event_id = ""
                if event_marker in entry.description:
                    source_event_id = entry.description.split(event_marker, 1)[1].split(" ", 1)[0]
                active_events = self._store.source_events(store=store)
                active_ids = (
                    set(active_events["event_id"].astype(str).tolist())
                    if "event_id" in active_events.columns
                    else set()
                )
                if source_event_id and source_event_id in active_ids:
                    raise ValueError("active source evidence requires an explicit correction, not an orphan reversal")
                return reverse_orphaned_source_entry(
                    store,
                    entry_id=entry_id,
                    authority=authority,
                    reviewer=reviewer,
                    reason=reason,
                )

    def export_canonical(self, destination: Path) -> Path:
        return self._store.export_canonical(destination)

    def export_reconciliation_audit(
        self,
        destination: Path,
        *,
        authority: str,
        as_of: str,
        known_at: str,
        fx_store: FXObservationStore | None = None,
        base_currency: str | None = None,
    ) -> Path:
        result = self.reconcile(
            authority=authority,
            as_of=as_of,
            known_at=known_at,
            fx_store=fx_store,
            base_currency=base_currency,
        )
        payload = json.dumps(
            audit_document(result),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8") + b"\n"
        target = Path(destination)
        atomic_write_bytes(target, payload, lambda path: json.loads(path.read_text(encoding="utf-8")))
        return target

    def apply_mapping(
        self,
        preview_id: str,
        *,
        source_identity: str,
        canonical_instrument_id: str,
        reviewer: str,
        reason: str,
    ) -> ImportPreview:
        return self._store.apply_mapping(
            preview_id,
            source_identity=source_identity,
            canonical_instrument_id=canonical_instrument_id,
            reviewer=reviewer,
            reason=reason,
        )

    def summary(self, *, as_of: str, known_at: str) -> PortfolioImportSummary:
        rebuilt = self.reconcile(as_of=as_of, known_at=known_at)
        batches = self._store.batches()
        status = (
            "manual_review"
            if rebuilt.discrepancies or rebuilt.replay.missing_lot_identity
            else ("balanced" if rebuilt.replay.trial_balance_balanced else "unbalanced")
        )
        return PortfolioImportSummary(
            status=status,
            batches=len(batches),
            active_rows=rebuilt.active_source_rows,
            quarantined_rows=rebuilt.quarantined_source_rows,
            holding_positions=len(rebuilt.replay.positions),
            cash_balances=len(rebuilt.replay.cash),
        )

    def batches(self) -> tuple[dict[str, object], ...]:
        return self._store.batches()
