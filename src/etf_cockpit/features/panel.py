"""Point-in-time cross-sectional research panel (ISSUE-0182).

This module composes the existing feature store, as-known membership, replay
return calculation and validation protocol. The panel is research-only;
outcome columns must never be passed into the inference feature matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Sequence

import pandas as pd

from etf_cockpit.core.pandas_values import bool_like_or_none
from etf_cockpit.features.feature_store import LocalFeatureStore
from etf_cockpit.validation.protocol import ValidationSpec, build_walk_forward_splits


PANEL_VERSION = "pit-cross-sectional.v1"
LABEL_VERSION = "total-excess-return.v1"
_MEMBERSHIP_COLUMNS = frozenset({
    "instrument_id", "snapshot_date", "snapshot_complete",
    "valid_from", "valid_to", "known_at", "pit_grade",
})


class PanelContractError(ValueError):
    """Required historical evidence is missing, ambiguous or not as-known."""


@dataclass(frozen=True)
class PITPanelInputs:
    """Explicit local data sources; no hidden live provider or network access."""

    feature_store: LocalFeatureStore
    features: pd.DataFrame
    prices: pd.DataFrame
    benchmark_prices: pd.DataFrame


@dataclass(frozen=True)
class DateGroupedFold:
    fold: int
    train_rows: tuple[int, ...]
    validation_rows: tuple[int, ...]
    train_dates: tuple[str, ...]
    validation_dates: tuple[str, ...]
    purged_dates: tuple[str, ...]
    embargoed_dates: tuple[str, ...]


def _timestamps(values: Iterable[object]) -> pd.Series:
    return pd.to_datetime(pd.Series(list(values)), errors="coerce", utc=True)


def _decisions(values: Iterable[str | date | datetime]) -> list[pd.Timestamp]:
    parsed = pd.to_datetime(list(values), errors="coerce", utc=True)
    if pd.isna(parsed).any():
        raise PanelContractError("decision times must be valid, explicit timestamps")
    return sorted(set(pd.Timestamp(item) for item in parsed))


def _membership_rows(
    membership: pd.DataFrame, decisions: Sequence[pd.Timestamp],
) -> tuple[pd.DataFrame, dict[str, str]]:
    if not _MEMBERSHIP_COLUMNS.issubset(membership.columns):
        raise PanelContractError(
            "membership needs dated complete snapshots, known_at and observed PIT grade"
        )
    frame = membership.copy()
    frame["_snapshot"] = pd.to_datetime(frame["snapshot_date"], errors="coerce").dt.date
    frame["_start"] = pd.to_datetime(frame["valid_from"], errors="coerce").dt.date
    frame["_end"] = pd.to_datetime(frame["valid_to"], errors="coerce").dt.date
    frame["_known"] = pd.to_datetime(frame["known_at"], errors="coerce", utc=True)
    frame["_complete"] = frame["snapshot_complete"].map(bool_like_or_none).eq(True)
    frame["_observed"] = frame["pit_grade"].eq("observed")
    rows: list[dict[str, object]] = []
    insufficient: dict[str, str] = {}
    for cutoff in decisions:
        key = cutoff.isoformat()
        day = cutoff.date()
        snapshot = frame.loc[frame["_snapshot"].eq(day)]
        if snapshot.empty:
            insufficient[key] = "complete_membership_snapshot_missing"
            continue
        if (
            not snapshot["_complete"].all()
            or not snapshot["_observed"].all()
            or snapshot["_known"].isna().any()
            or snapshot["_known"].gt(cutoff).any()
            or snapshot["_start"].isna().any()
            or snapshot["instrument_id"].isna().any()
            or snapshot["instrument_id"].astype(str).duplicated().any()
        ):
            insufficient[key] = "membership_not_complete_observed_or_known_by_cutoff"
            continue
        active = snapshot.loc[
            snapshot["_start"].map(lambda value: value <= day)
            & snapshot["_end"].map(lambda value: pd.isna(value) or value > day)
        ]
        for instrument in sorted(active["instrument_id"].astype(str)):
            rows.append({
                "decision_time": key,
                "decision_date": day.isoformat(),
                "instrument_id": instrument,
            })
    return pd.DataFrame(rows, columns=["decision_time", "decision_date", "instrument_id"]), insufficient


def build_pit_panel(
    decision_times: Iterable[str | date | datetime],
    membership: pd.DataFrame,
    feature_ids: Sequence[str],
    horizons: Sequence[int] = (63, 126),
    *,
    inputs: PITPanelInputs,
) -> pd.DataFrame:
    """Build one deterministic row per as-known decision date and instrument.

    All sources are explicit because otherwise a four-argument call could
    silently consult present-day membership or data. A feature with a missing
    publication timestamp or approximated PIT grade is unavailable. Label
    availability requires an observed next-session `session_open_at` for
    the VWCE benchmark; without it labels cannot enter model training.
    """
    decisions = _decisions(decision_times)
    horizons = tuple(sorted(set(int(value) for value in horizons)))
    if not horizons or any(value <= 0 for value in horizons):
        raise PanelContractError("horizons must contain positive session counts")
    if len(set(feature_ids)) != len(feature_ids):
        raise PanelContractError("feature ids must be unique")
    definitions = {item.feature_id: item for item in inputs.feature_store.feature_catalogue()}
    unknown = set(feature_ids).difference(definitions)
    if unknown:
        raise PanelContractError(f"unregistered features: {', '.join(sorted(unknown))}")
    panel, insufficient = _membership_rows(membership, decisions)
    if panel.empty:
        raise PanelContractError(f"no complete observed membership snapshots: {insufficient}")
    source = inputs.features.copy()
    if not {"instrument_id", "date", "pit_grade"}.issubset(source.columns):
        raise PanelContractError("feature observations require instrument_id, date and pit_grade")
    if "available_at" not in source:
        if "known_at" not in source:
            raise PanelContractError("feature observations require publication/knowledge timestamps")
        source["available_at"] = source["known_at"]
    source = source.loc[
        source["pit_grade"].eq("observed")
        & pd.to_datetime(source["available_at"], errors="coerce", utc=True).notna()
    ].copy()
    by_group: dict[str, list[str]] = {}
    for feature in feature_ids:
        by_group.setdefault(definitions[feature].source_dataset, []).append(feature)
    for group, ids in sorted(by_group.items()):
        # Existing materialisation selects the newest allowed vintage for
        # each feature. The grouping preserves its separately audited time.
        if source.empty:
            for feature in ids:
                panel[feature] = None
            panel[f"{group}_available_at"] = None
            continue
        matrix = inputs.feature_store.materialise(
            source,
            decisions,
            feature_ids=ids,
            entity_column="instrument_id",
            date_column="date",
            mode="offline",
        )
        if matrix.empty:
            for feature in ids:
                panel[feature] = None
            panel[f"{group}_available_at"] = None
            continue
        matrix = matrix[["instrument_id", "decision_time", "available_at", *ids]].copy()
        matrix["decision_time"] = pd.to_datetime(
            matrix["decision_time"], errors="coerce", utc=True
        ).map(lambda value: value.isoformat() if not pd.isna(value) else None)
        matrix.rename(columns={"available_at": f"{group}_available_at"}, inplace=True)
        panel = panel.merge(
            matrix, on=["instrument_id", "decision_time"],
            how="left", validate="one_to_one",
        )
    for feature in feature_ids:
        if feature not in panel:
            panel[feature] = None
    # Per-date transformations are computed solely from that date's
    # as-known cross-section; no future date contributes to a feature.
    for pair, name in (
        (("quality_score", "value_score"), "quality_x_value"),
        (("value_score", "momentum_score"), "value_x_momentum"),
    ):
        if all(value in panel for value in pair):
            ranks = [
                panel.groupby("decision_time", sort=True)[value].transform(
                    lambda series: pd.to_numeric(series, errors="coerce").rank(pct=True)
                ) for value in pair
            ]
            panel[name] = ranks[0] * ranks[1]

    prices = inputs.prices.copy()
    benchmark = inputs.benchmark_prices.copy()
    needed_prices = {"instrument_id", "date", "known_at", "adjusted_close"}
    if not needed_prices.issubset(prices) or not {
        "date", "known_at", "adjusted_close", "session_open_at"
    }.issubset(benchmark):
        raise PanelContractError(
            "adjusted prices require identity, dates and knowledge timestamps; "
            "VWCE also needs observed next-session open times"
        )
    if "instrument_id" not in benchmark:
        benchmark["instrument_id"] = "VWCE"
    if not benchmark["instrument_id"].astype(str).eq("VWCE").all():
        raise PanelContractError("benchmark must be VWCE")
    for frame in (prices, benchmark):
        if "is_adjusted" not in frame or not frame["is_adjusted"].map(bool_like_or_none).eq(True).all():
            raise PanelContractError("all research prices must be adjusted")
    if "currency" not in prices or "currency" not in benchmark:
        raise PanelContractError("prices require explicit EUR currency for the VWCE-relative label")
    if not prices["currency"].eq("EUR").all() or not benchmark["currency"].eq("EUR").all():
        raise PanelContractError("label prices must use EUR with an explicit FX conversion upstream")

    # Reuse the existing delisting-aware forward return logic unchanged.
    from etf_cockpit.analysis.decision.rank_validation import _forward_return
    price_frame = pd.concat([prices, benchmark], ignore_index=True)
    price_frame["_date"] = pd.to_datetime(price_frame["date"], errors="coerce").dt.date
    if price_frame["_date"].isna().any():
        raise PanelContractError("price session dates must be valid")
    sessions = sorted(benchmark["date"].map(lambda value: pd.Timestamp(value).date()).unique())
    # The inherited forward-return helper indexes sessions from the whole
    # frame. Refuse mismatched calendars rather than change the label horizon.
    if set(price_frame["_date"]) != set(sessions):
        raise PanelContractError("candidate sessions must match the VWCE calendar for labels")
    openings = benchmark.copy()
    openings["_date"] = openings["date"].map(lambda value: pd.Timestamp(value).date())
    if openings["session_open_at"].map(
        lambda value: pd.notna(value) and pd.Timestamp(value).tzinfo is not None
    ).eq(False).any():
        raise PanelContractError("market opening instants must have explicit UTC offsets")
    openings["_open"] = pd.to_datetime(openings["session_open_at"], errors="coerce", utc=True)
    if openings["_date"].duplicated().any() or openings["_open"].isna().any():
        raise PanelContractError("VWCE sessions require unique and observed market opening instants")
    opens = dict(zip(openings["_date"], openings["_open"], strict=True))
    panel["delisted"] = False
    for horizon in horizons:
        returns: list[float | None] = []
        excesses: list[float | None] = []
        statuses: list[str] = []
        starts: list[str | None] = []
        ends: list[str | None] = []
        maturities: list[str | None] = []
        for item in panel.itertuples(index=False):
            cutoff = pd.Timestamp(item.decision_time)
            future = [session for session in sessions if session > cutoff.date()]
            if len(future) < horizon:
                returns.append(None)
                excesses.append(None)
                statuses.append("forward_price_window_not_matured")
                starts.append(cutoff.date().isoformat())
                ends.append(None)
                maturities.append(None)
                continue
            end = future[horizon - 1]
            later = [session for session in sessions if session > end]
            available_at = opens[later[0]].isoformat() if later else None
            candidate, status = _forward_return(price_frame, str(item.instrument_id), cutoff, horizon)
            baseline, benchmark_status = _forward_return(price_frame, "VWCE", cutoff, horizon)
            returns.append(candidate)
            excesses.append(
                candidate - baseline
                if candidate is not None and baseline is not None else None
            )
            statuses.append(
                status if benchmark_status.startswith("available")
                else f"benchmark:{benchmark_status}"
            )
            starts.append(cutoff.date().isoformat())
            ends.append(end.isoformat())
            maturities.append(available_at)
        panel[f"fwd_total_{horizon}"] = returns
        panel[f"fwd_excess_{horizon}"] = excesses
        panel[f"fwd_status_{horizon}"] = statuses
        panel[f"label_start_{horizon}"] = starts
        panel[f"label_end_{horizon}"] = ends
        panel[f"label_available_at_{horizon}"] = maturities
    panel["delisted"] = panel[
        [f"fwd_status_{h}" for h in horizons]
    ].astype(str).apply(lambda row: any("delist" in status for status in row), axis=1)
    # All model features are unavailable until their individual publication
    # cut-offs; the combined label is mature only when *all* horizons are.
    availability_columns = [f"label_available_at_{h}" for h in horizons]
    panel["label_available_at"] = (
        pd.to_datetime(panel[availability_columns].stack(), errors="coerce", utc=True)
        .groupby(level=0).max().reindex(panel.index).map(
            lambda value: value.isoformat() if not pd.isna(value) else None
        )
    )
    if panel[availability_columns].isna().any(axis=1).any():
        panel.loc[panel[availability_columns].isna().any(axis=1), "label_available_at"] = None
    panel["panel_version"] = PANEL_VERSION
    panel["feature_set_version"] = inputs.feature_store.definition_hash(
        [definitions[item] for item in feature_ids]
    )
    panel["label_version"] = LABEL_VERSION
    panel["execution_allowed"] = False
    panel = panel.sort_values(["decision_time", "instrument_id"], kind="stable").reset_index(drop=True)
    panel.attrs.update({
        "execution_allowed": False,
        "insufficient_decision_times": insufficient,
        "membership_pit_grade": "observed",
        "membership_source": (
            str(membership["source"].iloc[0])
            if "source" in membership and membership["source"].nunique() == 1
            else "mixed_or_unknown"
        ),
        "as_of": max(decisions).isoformat(),
        "horizons": horizons,
        "panel_version": PANEL_VERSION,
    })
    return panel


def canonical_panel_rows(panel: pd.DataFrame) -> pd.DataFrame:
    """Canonical input order for the row positions returned by date_grouped_folds.

    Applying the fold indices directly to an unsorted input frame is unsafe.
    Model callers must index this canonical frame, not the original order.
    """
    if not {"decision_time", "instrument_id"}.issubset(panel):
        raise PanelContractError("canonical panel needs decision_time and instrument_id")
    return panel.sort_values(
        ["decision_time", "instrument_id"], kind="stable",
    ).reset_index(drop=True)


def date_grouped_folds(panel: pd.DataFrame, spec: ValidationSpec) -> tuple[DateGroupedFold, ...]:
    """Split unique dates and purge labels; row indices reference canonical_panel_rows(panel)."""
    if not {"decision_time", "instrument_id", "label_available_at"}.issubset(panel):
        raise PanelContractError("folds require decision_time, instrument_id and label_available_at")
    source = panel.copy()
    source["_date"] = pd.to_datetime(source["decision_time"], errors="coerce", utc=True).dt.date
    if source["_date"].isna().any() or source["instrument_id"].isna().any():
        raise PanelContractError("invalid date or security in panel")
    if source.duplicated(["_date", "instrument_id"]).any():
        raise PanelContractError("multiple rows for a single decision date and instrument")
    dates = tuple(sorted(source["_date"].unique()))
    ordered = canonical_panel_rows(source)
    ordered["_available"] = pd.to_datetime(ordered["label_available_at"], errors="coerce", utc=True)
    raw = build_walk_forward_splits(
        n_samples=len(dates), spec=spec, strict_label_purge=True,
    )
    result: list[DateGroupedFold] = []
    for fold in raw:
        train_days = {dates[pos] for pos in fold.train_indices}
        validation_days = {dates[pos] for pos in fold.validation_indices}
        validation_start = pd.Timestamp(min(validation_days), tz="UTC")
        train = ordered.index[
            ordered["_date"].isin(train_days)
            & ordered["_available"].notna()
            & ordered["_available"].le(validation_start)
        ]
        valid = ordered.index[ordered["_date"].isin(validation_days)]
        result.append(DateGroupedFold(
            fold=fold.fold,
            train_rows=tuple(int(i) for i in train),
            validation_rows=tuple(int(i) for i in valid),
            train_dates=tuple(date.isoformat() for date in sorted(train_days)),
            validation_dates=tuple(date.isoformat() for date in sorted(validation_days)),
            purged_dates=tuple(dates[pos].isoformat() for pos in fold.purged_indices),
            embargoed_dates=tuple(dates[pos].isoformat() for pos in fold.embargoed_indices),
        ))
    return tuple(result)


def panel_evidence_inventory(panel: pd.DataFrame) -> dict[str, object]:
    """Conservative descriptive statistics for evidence sufficiency, not promotion."""
    if not {"decision_time", "instrument_id"}.issubset(panel):
        raise PanelContractError("panel evidence inventory needs decision_time and instrument_id")
    if panel.empty:
        return {
            "decision_dates": 0, "instruments_per_date": {}, "matured_labels": {},
            "non_overlapping_periods": {}, "delisted_share": None,
            "membership_source": panel.attrs.get("membership_source", "unknown"),
            "membership_pit_grade": panel.attrs.get("membership_pit_grade", "unknown"),
        }
    decision_dates = pd.to_datetime(panel["decision_time"], errors="coerce", utc=True).dt.date
    as_of = pd.Timestamp(panel.attrs.get("as_of", panel["decision_time"].max()))
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    else:
        as_of = as_of.tz_convert("UTC")
    horizons = sorted(
        int(column.rsplit("_", 1)[-1])
        for column in panel if column.startswith("fwd_total_")
        and column.rsplit("_", 1)[-1].isdigit()
    )
    matured, independent = {}, {}
    for horizon in horizons:
        label = f"fwd_total_{horizon}"
        maturity = f"label_available_at_{horizon}"
        end = f"label_end_{horizon}"
        eligible = (
            panel[label].notna()
            & pd.to_datetime(panel[maturity], errors="coerce", utc=True).le(as_of)
        ) if maturity in panel else pd.Series(False, index=panel.index)
        matured[str(horizon)] = int(eligible.sum())
        intervals = sorted(set(
            (decision_dates.loc[index], pd.Timestamp(panel.loc[index, end]).date())
            for index in panel.index[eligible]
            if end in panel and pd.notna(panel.loc[index, end])
        ))
        # Count distinct non-overlapping windows, not the many securities
        # sharing the same market window.
        last_end, count = None, 0
        for begin, finish in intervals:
            if last_end is None or begin > last_end:
                count += 1
                last_end = finish
        independent[str(horizon)] = count
    distinct = panel["instrument_id"].nunique()
    delisted = (
        int(panel.loc[panel["delisted"].map(bool_like_or_none).eq(True), "instrument_id"].nunique()) / distinct
        if "delisted" in panel and distinct else None
    )
    return {
        "decision_dates": int(decision_dates.nunique()),
        "instruments_per_date": {
            day.isoformat(): int(count)
            for day, count in panel.groupby(decision_dates)["instrument_id"].nunique().items()
        },
        "matured_labels": matured,
        "non_overlapping_periods": independent,
        "delisted_share": delisted,
        "membership_source": panel.attrs.get("membership_source", "unknown"),
        "membership_pit_grade": panel.attrs.get("membership_pit_grade", "unknown"),
    }
