"""Application facade for portfolio import staging and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from etf_cockpit.data.import_export import ImportPreview
from etf_cockpit.data.portfolio_imports import (
    PortfolioCommitResult,
    PortfolioImportStore,
    PortfolioRebuild,
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

    def reconcile(self) -> PortfolioRebuild:
        return self._store.rebuild()

    def export_canonical(self, destination: Path) -> Path:
        return self._store.export_canonical(destination)

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

    def summary(self) -> PortfolioImportSummary:
        rebuilt = self.reconcile()
        batches = self._store.batches()
        status = (
            "unbalanced"
            if not rebuilt.balanced
            else ("manual_review" if not rebuilt.quarantined.empty else "balanced")
        )
        return PortfolioImportSummary(
            status=status,
            batches=len(batches),
            active_rows=len(rebuilt.active_events),
            quarantined_rows=len(rebuilt.quarantined),
            holding_positions=len(rebuilt.holdings),
            cash_balances=len(rebuilt.cash),
        )

    def batches(self) -> tuple[dict[str, object], ...]:
        return self._store.batches()
