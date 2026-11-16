"""Point-in-time cross-sectional research panel (ISSUE-0182).

This module composes the existing feature store, as-known membership, replay
return calculation and validation protocol. The panel is research-only;
outcome columns must never be passed into the inference feature matrix.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from numbers import Integral
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from etf_cockpit.analysis.decision.rank_validation import _aware_timestamp, _date_value, _forward_return
from etf_cockpit.core.pandas_values import bool_like_or_none
from etf_cockpit.data.universe_membership import membership_frame
from etf_cockpit.features.feature_store import LocalFeatureStore, _timestamps, labels_available_by
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


def _observed_instants(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values.map(_aware_timestamp), errors="coerce", utc=True)


def _decisions(values: Iterable[str | date | datetime]) -> list[pd.Timestamp]:
    parsed = pd.to_datetime(list(values), format="mixed", errors="coerce", utc=True)
    if pd.isna(parsed).any():
        raise PanelContractError("decision times must be valid, explicit timestamps")
    return sorted(set(pd.Timestamp(item) for item in parsed))


def _membership_rows(
    membership: pd.DataFrame | str, decisions: Sequence[pd.Timestamp], root: Path,
) -> tuple[pd.DataFrame, dict[str, str]]:
    if isinstance(membership, str):
        snapshots = [
            _membership_rows(
                membership_frame(membership, cutoff, root=root).assign(pit_grade="observed"),
                (cutoff,), root,
            )
            for cutoff in decisions
        ]
        return (
            pd.concat([rows for rows, _ in snapshots], ignore_index=True),
            {key: reason for _, excluded in snapshots for key, reason in excluded.items()},
        )
    if not _MEMBERSHIP_COLUMNS.issubset(membership.columns):
        raise PanelContractError(
            "membership needs dated complete snapshots, known_at and observed PIT grade"
        )
    frame = membership.copy()
    frame["_snapshot"] = frame["snapshot_date"].map(_date_value)
    frame["_start"] = frame["valid_from"].map(_date_value)
    frame["_end"] = frame["valid_to"].map(_date_value)
    frame["_known"] = _observed_instants(frame["known_at"])
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
            or (snapshot["valid_to"].notna() & snapshot["_end"].isna()).any()
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
    membership: pd.DataFrame | str,
    feature_ids: Sequence[str],
    horizons: Sequence[int] = (63, 126),
    *,
    inputs: PITPanelInputs,
) -> pd.DataFrame:
    """Build one deterministic row per as-known decision date and instrument.

    Pass local membership rows or a scope in the local membership ledger.
    Use explicit adjusted EUR prices and observed VWCE session opens. An
    unobserved input or a label unavailable at its next open stays null.
    """
    decisions = _decisions(decision_times)
    if not decisions:
        raise PanelContractError("at least one decision time is required")
    if not horizons or any(isinstance(value, bool) or not isinstance(value, Integral) or value <= 0 for value in horizons):
        raise PanelContractError("horizons must contain positive session counts")
    horizons = tuple(sorted(set(int(value) for value in horizons)))
    if len(set(feature_ids)) != len(feature_ids):
        raise PanelContractError("feature ids must be unique")
    definitions = {item.feature_id: item for item in inputs.feature_store.feature_catalogue()}
    unknown = set(feature_ids).difference(definitions)
    if unknown:
        raise PanelContractError(f"unregistered features: {', '.join(sorted(unknown))}")
    panel, insufficient = _membership_rows(membership, decisions, inputs.feature_store.root)
    if panel.empty:
        raise PanelContractError(f"no complete observed membership snapshots: {insufficient}")
    source = inputs.features.copy()
    if not {"instrument_id", "date", "pit_grade"}.issubset(source.columns):
        raise PanelContractError("feature observations require instrument_id, date and pit_grade")
    time_columns = [name for name in ("available_at", "known_at") if name in source]
    if not time_columns:
        raise PanelContractError("feature observations require publication/knowledge timestamps")
    stamps = source[time_columns].apply(_observed_instants)
    source["available_at"] = stamps.max(axis=1, skipna=False)
    source = source.loc[
        source["pit_grade"].eq("observed") & source["available_at"].notna() & source["instrument_id"].notna()
    ].copy()
    if not source.empty:
        vintage_dates = _timestamps(source["date"], normalize=False)
        vintages = source.groupby([source["instrument_id"], vintage_dates, source["available_at"]], sort=False)
        for column in sorted({definitions[feature].source_column for feature in feature_ids} & set(source)):
            source.loc[vintages[column].transform("nunique").gt(1), column] = None
    by_group: dict[str, list[str]] = {}
    for feature in feature_ids:
        by_group.setdefault(definitions[feature].source_dataset, []).append(feature)
    if feature_ids and not source.empty:
        matrix = inputs.feature_store.materialise(
            source, decisions, feature_ids=feature_ids, entity_column="instrument_id",
            include_feature_availability=True,
        )
        matrix["decision_time"] = pd.to_datetime(
            matrix["decision_time"], format="mixed", errors="coerce", utc=True
        ).map(lambda value: value.isoformat() if not pd.isna(value) else None)
        for feature in feature_ids:
            matrix[feature] = matrix[feature].mask(matrix[f"missing_{feature}"])
        groups = []
        for group, ids in sorted(by_group.items()):
            field = f"{group}_available_at"
            times = matrix[[f"{feature}_available_at" for feature in ids]].apply(
                lambda values: pd.to_datetime(values, format="mixed", errors="coerce", utc=True)
            )
            matrix[field] = times.max(axis=1).map(lambda stamp: stamp.isoformat() if pd.notna(stamp) else None)
            groups.append(field)
        panel = panel.merge(
            matrix[["instrument_id", "decision_time", *feature_ids, *groups]],
            on=["instrument_id", "decision_time"],
            how="left", validate="one_to_one",
        )
    else:
        for column in [*feature_ids, *(f"{group}_available_at" for group in sorted(by_group))]:
            panel[column] = None
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

    price_frame = pd.concat([prices.loc[prices["instrument_id"].ne("VWCE")], benchmark], ignore_index=True)
    price_frame["_date"] = price_frame["date"].map(_date_value)
    if price_frame["_date"].isna().any():
        raise PanelContractError("price session dates must be valid")
    price_by_instrument = {
        instrument: rows
        for instrument, rows in price_frame.groupby(price_frame["instrument_id"].astype(str), sort=False)
    }
    empty_prices = price_frame.iloc[:0]
    openings = pd.DataFrame({"date": benchmark["date"].map(_date_value),
                             "open_at": _observed_instants(benchmark["session_open_at"])})
    openings = openings.loc[openings["open_at"].dt.date.eq(openings["date"])].drop_duplicates()
    opens = openings.loc[~openings["date"].duplicated(keep=False)].set_index("date")["open_at"]
    sessions = sorted(benchmark["date"].map(_date_value).unique())
    first_forward = {
        day: bisect_right(sessions, day)
        for day in set(pd.Timestamp(value).date() for value in panel["decision_time"])
    }
    delisted = pd.Series(False, index=panel.index)
    for horizon in horizons:
        returns: list[float | None] = []
        excesses: list[float | None] = []
        statuses: list[str] = []
        starts: list[str | None] = []
        ends: list[str | None] = []
        maturities: list[str | None] = []
        baselines: dict[pd.Timestamp, tuple[float | None, str]] = {}
        for row, item in enumerate(panel.itertuples(index=False)):
            cutoff = pd.Timestamp(item.decision_time)
            position = first_forward[cutoff.date()] + horizon - 1
            if position >= len(sessions):
                returns.append(None)
                excesses.append(None)
                statuses.append("forward_price_window_not_matured")
                starts.append(cutoff.date().isoformat())
                ends.append(None)
                maturities.append(None)
                continue
            end = sessions[position]
            next_open = opens.get(sessions[position + 1]) if position + 1 < len(sessions) else None
            if next_open is None:
                candidate, baseline, status, benchmark_status = None, None, "next_session_open_unavailable", "available"
            else:
                instrument = str(item.instrument_id)
                candidate, status = _forward_return(
                    price_by_instrument.get(instrument, empty_prices), instrument, cutoff, horizon,
                    target_session=end, outcome_known_by=next_open,
                )
                if cutoff not in baselines:
                    baselines[cutoff] = _forward_return(
                        price_by_instrument.get("VWCE", empty_prices), "VWCE", cutoff, horizon,
                        target_session=end, outcome_known_by=next_open,
                    )
                baseline, benchmark_status = baselines[cutoff]
            delisted.iloc[row] |= "delist" in status
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
            maturities.append(next_open.isoformat() if next_open is not None and candidate is not None and baseline is not None else None)
        panel[f"fwd_total_{horizon}"] = returns
        panel[f"fwd_excess_{horizon}"] = excesses
        panel[f"fwd_status_{horizon}"] = statuses
        panel[f"label_start_{horizon}"] = starts
        panel[f"label_end_{horizon}"] = ends
        panel[f"label_available_at_{horizon}"] = maturities
    panel["delisted"] = delisted
    panel["label_start"] = panel["decision_date"]
    panel["label_end"] = panel[f"label_end_{horizons[-1]}"]
    # All model features are unavailable until their individual publication
    # cut-offs; the combined label is mature only when *all* horizons are.
    availability_columns = [f"label_available_at_{h}" for h in horizons]
    panel["label_available_at"] = (
        pd.to_datetime(panel[availability_columns].stack(), format="mixed", errors="coerce", utc=True)
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
            f"universe_membership:{membership}" if isinstance(membership, str)
            else str(membership["source"].iloc[0])
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
        key=lambda values: pd.to_datetime(values, format="mixed", errors="coerce", utc=True)
        if values.name == "decision_time" else values.astype(str),
    ).reset_index(drop=True)


def date_grouped_folds(panel: pd.DataFrame, spec: ValidationSpec) -> tuple[DateGroupedFold, ...]:
    """Split unique dates and purge labels; row indices reference canonical_panel_rows(panel)."""
    if not {"decision_time", "instrument_id", "label_available_at"}.issubset(panel):
        raise PanelContractError("folds require decision_time, instrument_id and label_available_at")
    source = panel.copy()
    source["_decision"] = pd.to_datetime(source["decision_time"], format="mixed", errors="coerce", utc=True)
    source["_date"] = source["_decision"].dt.date
    if source["_decision"].isna().any() or source["instrument_id"].isna().any():
        raise PanelContractError("invalid date or security in panel")
    if source.duplicated(["_decision", "instrument_id"]).any():
        raise PanelContractError("multiple rows for a single decision time and instrument")
    dates = tuple(sorted(source["_date"].unique()))
    ordered = canonical_panel_rows(source)
    raw = build_walk_forward_splits(
        n_samples=len(dates), spec=spec, strict_label_purge=True,
    )
    result: list[DateGroupedFold] = []
    for fold in raw:
        train_days = {dates[pos] for pos in fold.train_indices}
        validation_days = {dates[pos] for pos in fold.validation_indices}
        valid = ordered.index[ordered["_date"].isin(validation_days)]
        validation_start = ordered.loc[valid, "_decision"].min()
        train = ordered.index[
            ordered["_date"].isin(train_days)
            & labels_available_by(_observed_instants(ordered["label_available_at"]), validation_start)
        ]
        result.append(DateGroupedFold(
            fold=fold.fold,
            train_rows=tuple(int(i) for i in train),
            validation_rows=tuple(int(i) for i in valid),
            train_dates=tuple(day.isoformat() for day in sorted(set(ordered.loc[train, "_date"]))),
            validation_dates=tuple(date.isoformat() for date in sorted(validation_days)),
            purged_dates=tuple(dates[pos].isoformat() for pos in fold.purged_indices),
            embargoed_dates=tuple(dates[pos].isoformat() for pos in fold.embargoed_indices),
        ))
    return tuple(result)


def panel_evidence_inventory(
    panel: pd.DataFrame, *, folds: Sequence[DateGroupedFold] = (),
) -> dict[str, object]:
    """Conservative descriptive statistics for evidence sufficiency, not promotion."""
    if not {"decision_time", "instrument_id"}.issubset(panel):
        raise PanelContractError("panel evidence inventory needs decision_time and instrument_id")
    if panel.empty:
        return {
            "decision_dates": 0, "instruments_per_date": {}, "matured_labels": {},
            "matured_labels_by_fold": {},
            "non_overlapping_periods": {}, "delisted_share": None,
            "membership_source": panel.attrs.get("membership_source", "unknown"),
            "membership_pit_grade": panel.attrs.get("membership_pit_grade", "unknown"),
        }
    panel = canonical_panel_rows(panel)
    decision_dates = pd.to_datetime(panel["decision_time"], format="mixed", errors="coerce", utc=True).dt.date
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
    matured_by_fold: dict[int, dict[str, dict[str, int]]] = {fold.fold: {} for fold in folds}
    for horizon in horizons:
        label = f"fwd_total_{horizon}"
        maturity = f"label_available_at_{horizon}"
        end = f"label_end_{horizon}"
        eligible = (
            panel[label].notna()
            & _observed_instants(panel[maturity]).le(as_of)
        ) if maturity in panel else pd.Series(False, index=panel.index)
        if f"fwd_excess_{horizon}" in panel:
            eligible &= panel[f"fwd_excess_{horizon}"].notna()
        matured[str(horizon)] = int(eligible.sum())
        for fold in folds:
            matured_by_fold[fold.fold][str(horizon)] = {
                "train": int(eligible.iloc[list(fold.train_rows)].sum()),
                "validation": int(eligible.iloc[list(fold.validation_rows)].sum()),
            }
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
        "matured_labels_by_fold": matured_by_fold,
        "non_overlapping_periods": independent,
        "delisted_share": delisted,
        "membership_source": panel.attrs.get("membership_source", "unknown"),
        "membership_pit_grade": panel.attrs.get("membership_pit_grade", "unknown"),
    }
