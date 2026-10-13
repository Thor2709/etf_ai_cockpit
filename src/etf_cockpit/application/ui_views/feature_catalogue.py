"""Read-only view model for the Feature Catalogue page (spec 7.20, section 8).

Plain values only: nothing here changes a feature, score or gate. Missing values stay ``None`` with a reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from etf_cockpit.application.feature_service import LocalFeatureStore

COVERAGE_WARN_BELOW = 0.80
SAMPLE_ROWS = 8
SAMPLE_COLUMNS = ("date", "etf_id", "return_1d_log", "return_20d_log", "momentum_60d", "vol_20d_ann", "drawdown_current")


@dataclass(frozen=True)
class FeatureDefinitionRow:
    feature_id: str
    source_column: str
    lookback: str
    units: str
    missing_policy: str


@dataclass(frozen=True)
class CoverageRow:
    feature: str
    coverage_pct: float | None


@dataclass(frozen=True)
class FeatureCatalogueView:
    definitions: tuple[FeatureDefinitionRow, ...]
    targets: tuple[str, ...]
    preview_rows: int | None
    missing_rows: int | None
    coverage: tuple[CoverageRow, ...]
    sample_columns: tuple[str, ...]
    sample_rows: tuple[Mapping[str, object], ...]
    unavailable_reason: str | None

    @property
    def lowest_coverage(self) -> CoverageRow | None:
        known = [row for row in self.coverage if row.coverage_pct is not None]
        return min(known, key=lambda row: row.coverage_pct or 0.0) if known else None


def build_feature_catalogue_view(root: Path, features: object | None) -> FeatureCatalogueView:
    store = LocalFeatureStore(root)
    definitions = tuple(
        FeatureDefinitionRow(
            item.feature_id,
            item.source_column,
            f"{item.lookback_days}d / +{item.availability_delay_days}d",
            item.units,
            item.missing_policy,
        )
        for item in store.feature_catalogue()
    )
    targets = tuple(
        f"{item.target_id}: {item.kind}, horizon={item.horizon_days}d, embargo={item.embargo_days}d"
        for item in store.target_catalogue()
    )
    empty = features is None or bool(getattr(features, "empty", True))
    if empty:
        return FeatureCatalogueView(
            definitions, targets, None, None, (), (), (), "No local feature snapshot has been built yet."
        )
    summary = store.coverage(features)  # type: ignore[arg-type]
    coverage_map = summary.get("coverage", {})
    coverage = tuple(
        CoverageRow(str(name), None if value is None else round(float(value) * 100.0, 1))
        for name, value in dict(coverage_map).items()
        if name != "date"
    )
    columns = tuple(name for name in SAMPLE_COLUMNS if name in getattr(features, "columns", ()))
    tail = features.tail(SAMPLE_ROWS)  # type: ignore[attr-defined]
    sample = tuple({name: row[name] for name in columns} for _, row in tail[list(columns)].iterrows()) if columns else ()
    return FeatureCatalogueView(
        definitions,
        targets,
        int(summary.get("rows", 0)),
        int(summary.get("missing_rows", 0)),
        coverage,
        columns,
        sample,
        None,
    )
