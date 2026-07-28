"""Application query for local, non-executable direct ETF overlap evidence."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd

from etf_cockpit.core.paths import ROOT
from etf_cockpit.features.overlap import DirectOverlapReport, calculate_direct_overlap


def load_direct_holdings(*, root: Path = ROOT) -> pd.DataFrame:
    """Load only the configured local canonical holdings store.

    Environment and process-working-directory path discovery is deliberately
    excluded so an overlap query cannot cause UNC access or substitute an
    unrelated store.
    """

    base = Path(root).resolve()
    destination = (base / "data" / "clean" / "fund_holdings.parquet").resolve()
    try:
        destination.relative_to(base)
    except ValueError:
        return pd.DataFrame()
    if destination.drive.startswith("\\") or str(destination).startswith(("\\\\", "//")):
        return pd.DataFrame()
    csv_path = _contained_local_path(destination.with_suffix(".csv"), base)
    canonical_path = destination if destination.exists() else csv_path if csv_path is not None and csv_path.exists() else None
    canonical = pd.DataFrame()
    if canonical_path is not None:
        try:
            canonical = pd.read_parquet(canonical_path) if canonical_path.suffix == ".parquet" else pd.read_csv(canonical_path)
        except Exception:
            # A present but corrupt canonical store must not silently downgrade
            # to lower-authority legacy evidence.
            return pd.DataFrame()

    legacy = _contained_local_path(destination.with_name("etf_holdings.parquet"), base)
    legacy_csv = _contained_local_path(destination.with_name("etf_holdings.csv"), base)
    legacy_path = legacy if legacy is not None and legacy.exists() else legacy_csv if legacy_csv is not None and legacy_csv.exists() else None
    legacy_context = pd.DataFrame()
    if legacy_path is not None:
        try:
            raw_legacy = pd.read_parquet(legacy_path) if legacy_path.suffix == ".parquet" else pd.read_csv(legacy_path)
            legacy_context = _legacy_holdings(raw_legacy)
        except Exception:
            legacy_context = pd.DataFrame()
    if canonical.empty:
        return legacy_context
    if legacy_context.empty:
        return canonical
    parent_column = "instrument_id" if "instrument_id" in canonical.columns else "etf_id" if "etf_id" in canonical.columns else None
    if parent_column is None:
        return pd.DataFrame()
    canonical_ids = set(canonical[parent_column].dropna().astype(str).str.strip())
    legacy_only = legacy_context.loc[~legacy_context["instrument_id"].astype(str).str.strip().isin(canonical_ids)]
    return pd.concat([canonical, legacy_only], ignore_index=True, sort=False)


def _contained_local_path(path: Path, base: Path) -> Path | None:
    resolved = path.resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    if resolved.drive.startswith("\\") or str(resolved).startswith(("\\\\", "//")):
        return None
    return resolved


def _legacy_holdings(frame: pd.DataFrame) -> pd.DataFrame:
    """Adapt the pre-canonical store as explicitly unverified fallback evidence."""

    if frame.empty or not {"etf_id", "as_of_date", "weight"}.issubset(frame.columns):
        return pd.DataFrame()
    result = pd.DataFrame(
        {
            "instrument_id": frame["etf_id"],
            "as_of": frame["as_of_date"],
            "security": frame.get("holding_name", ""),
            "weight": frame["weight"],
            "source_id": "legacy-reference-import",
            "authority": "manual_unverified",
            "completeness": "partial",
            "freshness": frame.get("staleness_status", "unknown").map(
                {"ok": "fresh", "warning": "stale", "block": "stale"}
            ).fillna("unknown")
            if "staleness_status" in frame.columns
            else "unknown",
            "sector": frame.get("sector", ""),
            "region": frame.get("region", ""),
            "currency": frame.get("currency", ""),
        }
    )
    holding_ids = frame.get("holding_id")
    if holding_ids is not None:
        candidate = holding_ids.fillna("").astype(str).str.strip().str.upper()
        result["isin"] = candidate.where(candidate.str.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]"), "")
    return result


def build_direct_overlap_view(
    snapshot: object,
    instrument_ids: Sequence[str],
    *,
    current_weights: Mapping[str, float] | None = None,
    target_weights: Mapping[str, float] | None = None,
    focus_instrument_id: str | None = None,
    holdings: pd.DataFrame | None = None,
    root: Path = ROOT,
    known_at: datetime | None = None,
) -> DirectOverlapReport:
    evidence = holdings.copy() if isinstance(holdings, pd.DataFrame) else load_direct_holdings(root=root)
    current = dict(current_weights) if current_weights is not None else _snapshot_weights(snapshot)
    return calculate_direct_overlap(
        evidence,
        instrument_ids,
        current_weights=current,
        target_weights=target_weights or {},
        focus_instrument_id=focus_instrument_id,
        known_at=known_at,
    )


def direct_overlap_payload(report: DirectOverlapReport) -> dict[str, object]:
    return {
        "status": report.status,
        "methodology": report.methodology,
        "current_resolved_weight": report.current_resolved_weight,
        "target_resolved_weight": report.target_resolved_weight,
        "coverage": [
            {
                "instrument_id": item.instrument_id,
                "status": item.status,
                "freshness": item.freshness,
                "as_of": item.as_of or "N/A",
                "resolved_weight": item.resolved_weight,
                "unresolved_weight": item.unresolved_weight,
                "source_id": item.source_id or "N/A",
                "source_checksum": item.source_checksum or "N/A",
                "known_at": item.known_at or "N/A",
                "authority": item.authority or "N/A",
            }
            for item in report.coverage
        ],
        "pairs": [
            {
                "left": pair.left_instrument_id,
                "right": pair.right_instrument_id,
                "status": pair.status,
                "observed_overlap_weight": pair.observed_overlap_weight,
                "current_overlap_weight": pair.current_overlap_weight,
                "top_overlapping_companies": [
                    f"{holding.display_name} ({holding.shared_weight:.2%})" for holding in pair.top_holdings
                ],
            }
            for pair in report.pairs
        ],
        "concentrations": [
            {
                "dimension": item.dimension,
                "bucket": item.bucket,
                "current_weight": item.current_weight,
                "target_weight": item.target_weight,
            }
            for item in report.concentrations
        ],
        "lookthrough": {
            "input_weight": report.input_weight,
            "mapped_weight": report.mapped_weight,
            "unknown_weight": report.unknown_weight,
            "report_hash": report.report_hash,
            "exposures": [
                {
                    "dimension": item.dimension,
                    "bucket": item.bucket,
                    "direct_weight": item.direct_weight,
                    "indirect_weight": item.indirect_weight,
                    "combined_weight": item.combined_weight,
                    "contributors": [
                        {
                            "root_instrument_id": contributor.root_instrument_id,
                            "path": list(contributor.path),
                            "ownership": contributor.ownership,
                            "weight": contributor.weight,
                        }
                        for contributor in item.contributors
                    ],
                }
                for item in report.exposures
            ],
        },
        "warnings": list(report.warnings),
        "execution_allowed": False,
    }


def _snapshot_weights(snapshot: object) -> dict[str, float]:
    frame = getattr(snapshot, "holdings", pd.DataFrame())
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    result: dict[str, float] = {}
    for _, row in frame.iterrows():
        instrument_id = str(row.get("etf_id", row.get("instrument_id", ""))).strip()
        if not instrument_id:
            continue
        raw_weight = row.get("current_weight", 0.0)
        if pd.api.types.is_bool(raw_weight):
            continue
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(weight) or weight < 0 or weight > 1:
            continue
        result[instrument_id] = result.get(instrument_id, 0.0) + weight
    return result


__all__ = ["build_direct_overlap_view", "direct_overlap_payload", "load_direct_holdings"]
