"""Read-only holding projections over explicitly bound portfolio evidence.

This module only formats and joins saved facts. It does not revalue positions,
rebuild forecasts, or infer missing cost basis, activity, or instrument data.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import math
from numbers import Real

import pandas as pd


_QUANTILES = (5, 10, 25, 50, 75, 90, 95)
_ASSET_FIELDS = {
    "stock": ("shares", "sector"),
    "equity": ("shares", "sector"),
    "etf": ("issuer", "expense_ratio", "distribution_policy"),
    "bond": ("face_value", "coupon_rate", "maturity_date"),
}
_SORT_FIELDS = frozenset(
    {
        "instrument_id",
        "asset_type",
        "quantity",
        "local_value",
        "value",
        "weight",
        "cost_basis",
        "realised_pnl",
        "unrealised_pnl",
        "income",
        "fees",
        "action",
        "peer_rank",
        "expected_return",
    }
)


def build_portfolio_holdings_table(
    holdings: pd.DataFrame | None,
    *,
    portfolio_snapshot: Mapping[str, object] | None,
    performance_snapshot: Mapping[str, object] | None,
    analysis_snapshot: Mapping[str, object] | None,
    horizon_days: int,
    output_currency: str,
    currency_projection: object | None,
    search: str = "",
    asset_type: str | None = None,
    sort_by: str = "instrument_id",
    descending: bool = False,
    column_preset: str = "full",
) -> dict[str, object]:
    """Join bound snapshots and an exact run; absent facts remain unavailable.

    Snapshot reconciliation is deliberately exact: if the supplied saved
    holding values do not equal the selected performance snapshot's securities
    value, the projection reports a conflict instead of applying a tolerance.
    Forecast gains use only the selected stored distribution quantiles and the
    canonical currency projection supplied by the application layer.
    """

    target_currency = str(output_currency or "").strip().upper()
    selected_horizon = _positive_integer(horizon_days)
    reasons: list[str] = []
    conflicts: list[str] = []

    portfolio_id = _text(_member(portfolio_snapshot, "portfolio_id"))
    snapshot_id = _text(_member(portfolio_snapshot, "snapshot_id"))
    portfolio_decision_time = _member(portfolio_snapshot, "as_of")
    analysis_decision_time = _member(analysis_snapshot, "decision_time")
    portfolio_cutoff = _decision_timestamp(portfolio_decision_time)
    analysis_cutoff = _decision_timestamp(analysis_decision_time)
    analysis_postdates_snapshot = bool(
        portfolio_cutoff is not None
        and analysis_cutoff is not None
        and analysis_cutoff > portfolio_cutoff
    )
    portfolio_date = _date_key(portfolio_decision_time)
    performance_date = _date_key(_member(performance_snapshot, "date"))
    performance_snapshot_id = _text(_member(performance_snapshot, "snapshot_id"))
    run_id = _text(_member(analysis_snapshot, "analysis_run_id"))
    artifact_run_id = _text(_member(analysis_snapshot, "run_id"))
    analysis_date = _date_key(analysis_decision_time)
    portfolio_policy = _text(_member(portfolio_snapshot, "policy_id"))
    performance_policy = _text(_member(performance_snapshot, "policy_id"))
    analysis_policy = _text(_member(analysis_snapshot, "policy_id"))

    if not portfolio_id or not snapshot_id or not portfolio_date:
        reasons.append("portfolio_snapshot_identity_or_date_unavailable")
    if not performance_date:
        reasons.append("performance_snapshot_unavailable")
    elif portfolio_date and performance_date != portfolio_date:
        conflicts.append("portfolio_performance_snapshot_date_mismatch")
    if performance_snapshot_id and snapshot_id and performance_snapshot_id != snapshot_id:
        conflicts.append("portfolio_performance_snapshot_identity_mismatch")
    if not run_id or not artifact_run_id:
        reasons.append("analysis_run_id_unavailable")
    elif run_id != artifact_run_id:
        conflicts.append("analysis_run_id_mismatch")
    if analysis_snapshot is None or str(_member(analysis_snapshot, "status", "unavailable")) != "complete":
        reasons.append("analysis_missing_or_incomplete")
    if not analysis_date:
        reasons.append("analysis_date_unavailable")
    elif portfolio_date and analysis_date != portfolio_date:
        conflicts.append("portfolio_analysis_date_mismatch")
    if portfolio_cutoff is not None and analysis_cutoff is None:
        reasons.append("analysis_decision_timestamp_unavailable")
    elif analysis_postdates_snapshot:
        conflicts.append("portfolio_analysis_postdates_snapshot")
    if not analysis_policy:
        reasons.append("analysis_policy_unavailable")
    if analysis_policy and portfolio_policy and analysis_policy != portfolio_policy:
        conflicts.append("portfolio_analysis_policy_mismatch")
    if analysis_policy and performance_policy and analysis_policy != performance_policy:
        conflicts.append("performance_analysis_policy_mismatch")
    if selected_horizon is None:
        reasons.append("forecast_horizon_invalid")
    if len(target_currency) != 3 or not target_currency.isascii() or not target_currency.isalpha():
        reasons.append("output_currency_invalid")

    projection_currency = _text(_member(currency_projection, "currency"))
    projection_rate = _finite(_member(currency_projection, "reference_rate"))
    projection_date = _date_key(_member(currency_projection, "decision_time"))
    projection_available = (
        _member(currency_projection, "available") is True
        and projection_currency == target_currency
        and projection_rate is not None
        and projection_rate > 0
        and (not portfolio_date or not projection_date or projection_date == portfolio_date)
    )
    currency_reason = (
        None
        if projection_available
        else _text(_member(currency_projection, "reason"))
        or "canonical_output_currency_projection_unavailable"
    )
    if not projection_available:
        reasons.append(currency_reason or "canonical_output_currency_projection_unavailable")

    frame = holdings if isinstance(holdings, pd.DataFrame) else pd.DataFrame()
    identity_column = next((name for name in ("instrument_id", "etf_id") if name in frame.columns), None)
    if identity_column is None:
        reasons.append("canonical_holding_identity_unavailable")
    raw_rows = frame.to_dict("records") if identity_column is not None else []
    identities = [_text(row.get(identity_column)) for row in raw_rows]
    identity_counts = Counter(value for value in identities if value)
    duplicates = {value for value, count in identity_counts.items() if count > 1}
    if any(not value for value in identities):
        conflicts.append("canonical_holding_identity_unavailable")
    if any(
        row_date and portfolio_date and row_date != portfolio_date
        for row in raw_rows
        if (row_date := _date_key(row.get("as_of_date"))) is not None
    ):
        conflicts.append("holding_snapshot_date_mismatch")
    if duplicates:
        conflicts.append("duplicate_canonical_holding_identity")

    performance_value = _finite(_member(performance_snapshot, "securities_value"))
    performance_cash_value = _finite(_member(performance_snapshot, "cash_value"))
    performance_total_value = _finite(_member(performance_snapshot, "total_value"))
    holding_values = [_finite(_first_present(row, "market_value_eur", "value_eur")) for row in raw_rows]
    if not raw_rows or performance_value is None or any(value is None for value in holding_values):
        reconciliation = _cell(None, "selected_snapshot_value_reconciliation_unavailable")
    else:
        held_total = math.fsum(value for value in holding_values if value is not None)
        if held_total == performance_value:
            reconciliation = _cell(True)
        else:
            reconciliation = _cell(None, "holding_values_do_not_reconcile_to_performance_snapshot")
            conflicts.append("holding_values_do_not_reconcile_to_performance_snapshot")
    if performance_value is None or performance_cash_value is None or performance_total_value is None:
        portfolio_value_reconciliation = _cell(None, "canonical_security_cash_total_values_unavailable")
    elif performance_value + performance_cash_value != performance_total_value:
        portfolio_value_reconciliation = _cell(None, "canonical_security_cash_total_values_do_not_reconcile")
        conflicts.append("canonical_security_cash_total_values_do_not_reconcile")
    else:
        portfolio_value_reconciliation = _cell(True)

    analysis_rows, analysis_identity_conflicts = _index_analysis_rows(analysis_snapshot)
    if analysis_identity_conflicts:
        conflicts.append("analysis_canonical_identity_conflict")
    for identity, row in tuple(analysis_rows.items()):
        row_run_id = _text(_member(row, "analysis_run_id"))
        row_policy_id = _text(_member(row, "policy_id"))
        if not row_run_id:
            analysis_rows.pop(identity, None)
            reasons.append("analysis_row_run_id_unavailable")
        elif row_run_id != run_id:
            analysis_rows.pop(identity, None)
            conflicts.append("analysis_row_run_id_mismatch")
        elif row_policy_id and analysis_policy and row_policy_id != analysis_policy:
            analysis_rows.pop(identity, None)
            conflicts.append("analysis_row_policy_mismatch")
    distributions = _member(analysis_snapshot, "distributions", {})
    output_rows: list[dict[str, object]] = []
    for identity, raw in zip(identities, raw_rows, strict=True):
        if not identity:
            continue
        asset = _text(raw.get("asset_type")) or "unavailable"
        analysis_row = analysis_rows.get(identity)
        if identity in duplicates:
            analysis_row = None
        projected_row = _holding_row(
                identity,
                raw,
                asset_type=asset,
                analysis_row=analysis_row,
                distributions=distributions,
                horizon_days=selected_horizon,
                portfolio_date=portfolio_date,
                portfolio_cutoff=portfolio_cutoff,
                output_currency=target_currency,
                currency_rate=projection_rate if projection_available else None,
                currency_reason=currency_reason,
                duplicate=identity in duplicates,
            )
        selected_distribution = _distribution_for(distributions, identity, selected_horizon)
        model_decision_time = _member(selected_distribution, "decision_time")
        model_cutoff = _decision_timestamp(model_decision_time)
        model_postdates_snapshot = bool(
            portfolio_cutoff is not None
            and model_cutoff is not None
            and model_cutoff > portfolio_cutoff
        )
        model_date = _date_key(model_decision_time)
        if portfolio_cutoff is not None and model_cutoff is None:
            conflicts.append("forecast_distribution_decision_timestamp_unavailable")
        elif model_postdates_snapshot:
            conflicts.append("forecast_distribution_postdates_portfolio_snapshot")
        elif model_date and portfolio_date and model_date > portfolio_date:
            conflicts.append("forecast_distribution_postdates_portfolio_snapshot")
        projected_row.update(
            {
                "data_as_of": _cell(_date_key(raw.get("as_of_date")) or portfolio_date, "holding_data_as_of_unavailable"),
                "performance_as_of": _cell(performance_date, "performance_snapshot_as_of_unavailable"),
                "analysis_as_of": _cell(analysis_date, "analysis_as_of_unavailable"),
                "model_as_of": _cell(model_date, "model_forecast_as_of_unavailable"),
                "analysis_stale": (
                    _cell(analysis_date != portfolio_date)
                    if analysis_date and portfolio_date
                    else _cell(None, "analysis_staleness_unavailable")
                ),
                "policy_ids": _cell(dict(_mapping(_member(analysis_snapshot, "policy_ids"))), "analysis_policy_identity_unavailable"),
                "portfolio_snapshot_id": snapshot_id,
                "performance_snapshot_date": performance_date,
                "analysis_run_id": run_id,
            }
        )
        output_rows.append(projected_row)

    total_rows = len(output_rows)
    filtered = [row for row in output_rows if _matches(row, search, asset_type)]
    selected_sort = sort_by if sort_by in _SORT_FIELDS else "instrument_id"
    filtered = _sort_rows(filtered, selected_sort, descending)
    if column_preset not in {"full", "values", "analysis"}:
        reasons.append("column_preset_invalid")

    valid_binding = bool(
        portfolio_id
        and snapshot_id
        and portfolio_date
        and performance_date == portfolio_date
        and not any("snapshot_identity_mismatch" in item or "snapshot_date_mismatch" in item for item in conflicts)
    )
    policy_consistent = not any("policy_mismatch" in item for item in conflicts)
    analysis_current = bool(
        analysis_snapshot is not None
        and run_id
        and run_id == artifact_run_id
        and analysis_date == portfolio_date
        and (portfolio_cutoff is None or (analysis_cutoff is not None and analysis_cutoff <= portfolio_cutoff))
        and analysis_policy is not None
        and str(_member(analysis_snapshot, "status", "unavailable")) == "complete"
        and _member(analysis_snapshot, "policy_status", "unavailable") == "available"
    )
    proposal_allowed = bool(
        valid_binding
        and analysis_current
        and policy_consistent
        and not conflicts
        and reconciliation["status"] == "available"
        and not duplicates
    )
    if not proposal_allowed and not reasons and not conflicts:
        reasons.append("analysis_is_not_current_for_selected_snapshot")

    status = "available" if proposal_allowed else "partial" if output_rows else "unavailable"
    return {
        "status": status,
        "reason": reasons[0] if reasons else conflicts[0] if conflicts else None,
        "reasons": tuple(dict.fromkeys(reasons)),
        "conflicts": tuple(dict.fromkeys(conflicts)),
        "portfolio_snapshot": {
            "portfolio_id": portfolio_id,
            "snapshot_id": snapshot_id,
            "as_of": portfolio_date,
            "source_checksum": _text(_member(portfolio_snapshot, "source_checksum")),
        },
        "performance_snapshot": {
            "date": performance_date,
            "snapshot_id": performance_snapshot_id,
            "securities_value": performance_value,
            "cash_value": performance_cash_value,
            "total_value": performance_total_value,
            "securities_value_output_currency": _converted_cell(
                performance_value,
                projection_rate if projection_available else None,
                target_currency,
                currency_reason,
                "performance_securities_value_unavailable",
            ),
            "cash_value_output_currency": _converted_cell(
                performance_cash_value,
                projection_rate if projection_available else None,
                target_currency,
                currency_reason,
                "performance_cash_value_unavailable",
            ),
            "total_value_output_currency": _converted_cell(
                performance_total_value,
                projection_rate if projection_available else None,
                target_currency,
                currency_reason,
                "performance_total_value_unavailable",
            ),
            "portfolio_value_reconciliation": portfolio_value_reconciliation,
            "reconciliation": reconciliation,
        },
        "analysis_run_id": run_id,
        "analysis_date": analysis_date,
        "analysis_policy_id": analysis_policy,
        "analysis_policy_ids": dict(_mapping(_member(analysis_snapshot, "policy_ids"))),
        "analysis_current": analysis_current,
        "horizon_days": selected_horizon,
        "output_currency": target_currency,
        "proposal_handoff_allowed": proposal_allowed,
        "proposal_handoff_reason": None if proposal_allowed else (conflicts[0] if conflicts else reasons[0] if reasons else "analysis_is_not_current_for_selected_snapshot"),
        "row_count": len(filtered),
        "total_rows": total_rows,
        "sort_by": selected_sort,
        "descending": bool(descending),
        "column_preset": column_preset,
        "rows": filtered,
        "execution_allowed": False,
    }


def _holding_row(
    identity: str,
    raw: Mapping[str, object],
    *,
    asset_type: str,
    analysis_row: Mapping[str, object] | None,
    distributions: object,
    horizon_days: int | None,
    portfolio_date: str | None,
    portfolio_cutoff: pd.Timestamp | None,
    output_currency: str,
    currency_rate: float | None,
    currency_reason: str | None,
    duplicate: bool,
) -> dict[str, object]:
    market_value = _finite(_first_present(raw, "market_value_eur", "value_eur"))
    value = (
        _cell(market_value * currency_rate)
        if market_value is not None and currency_rate is not None
        else _cell(None, currency_reason or "holding_value_unavailable")
    )
    details = {
        field: _cell(raw.get(field), f"{field}_unavailable")
        for field in _ASSET_FIELDS.get(_asset_group(asset_type), ())
    }
    row: dict[str, object] = {
        "instrument_id": identity,
        "name": _cell(_first_present(raw, "name", "display_name"), "instrument_name_unavailable"),
        "asset_type": _cell(asset_type if asset_type != "unavailable" else None, "asset_type_unavailable"),
        "quantity": _cell(_first_present(raw, "quantity", "units"), "quantity_or_face_unavailable"),
        "face_value": _cell(raw.get("face_value"), "face_value_unavailable"),
        "local_currency": _cell(raw.get("currency"), "local_currency_unavailable"),
        "local_value": _cell(raw.get("local_value"), "local_currency_value_unavailable"),
        "value": value,
        "value_currency": output_currency,
        "weight": _cell(_first_present(raw, "current_weight", "weight"), "holding_weight_unavailable"),
        "cost_basis": _converted_cell(raw.get("cost_basis_eur"), currency_rate, output_currency, currency_reason, "cost_basis_unavailable"),
        "realised_pnl": _converted_cell(_first_present(raw, "realised_pnl_eur", "realized_pnl_eur"), currency_rate, output_currency, currency_reason, "realised_pnl_unavailable"),
        "unrealised_pnl": _converted_cell(_first_present(raw, "unrealised_pnl_eur", "unrealized_pnl_eur"), currency_rate, output_currency, currency_reason, "unrealised_pnl_unavailable"),
        "income": _converted_cell(raw.get("income_eur"), currency_rate, output_currency, currency_reason, "income_unavailable"),
        "fees": _converted_cell(raw.get("fees_eur"), currency_rate, output_currency, currency_reason, "fees_unavailable"),
        "asset_details": details,
        "transactions": _cell(raw.get("transactions"), "transactions_not_bound_to_holding_snapshot"),
        "lots": _cell(raw.get("lots"), "lots_not_bound_to_holding_snapshot"),
        "events": _cell(raw.get("events"), "events_not_bound_to_holding_snapshot"),
        "portfolio_impact": _cell(raw.get("portfolio_impact"), "portfolio_impact_not_bound_to_analysis"),
    }
    if analysis_row is None:
        unavailable_reason = "analysis_identity_missing_or_conflicted" if duplicate else "analysis_row_unavailable_for_identity"
        row.update(
            {
                "scores": _unavailable_scores(unavailable_reason),
                "rank": _cell(None, unavailable_reason),
                "peer_rank": _cell(None, unavailable_reason),
                "action": _cell(None, unavailable_reason),
                "blockers": _cell(None, unavailable_reason),
                "coverage": _cell(None, unavailable_reason),
                "expected_return": _cell(None, unavailable_reason),
                "forecast_quantiles": _unavailable_quantiles(unavailable_reason),
                "expected_gain_loss": _unavailable_quantiles(unavailable_reason),
            }
        )
        return row

    row["scores"] = {
        name: _cell(value, f"{name}_score_unavailable")
        for name, value in _mapping(_member(analysis_row, "scores")).items()
    }
    for name in ("evidence", "quality", "risk"):
        row["scores"].setdefault(name, _cell(None, f"{name}_score_unavailable"))
    row["rank"] = _cell(_member(analysis_row, "rank"), "universe_rank_unavailable")
    row["peer_rank"] = _cell(_member(analysis_row, "peer_rank"), "peer_rank_unavailable")
    row["action"] = _cell(_member(analysis_row, "action"), "action_unavailable")
    row["blockers"] = _cell(_member(analysis_row, "blockers"), "blockers_unavailable")
    row["coverage"] = _cell(_member(analysis_row, "coverage"), "analysis_coverage_unavailable")

    distribution = _distribution_for(distributions, identity, horizon_days)
    model_decision_time = _member(distribution, "decision_time")
    model_cutoff = _decision_timestamp(model_decision_time)
    model_postdates_snapshot = bool(
        portfolio_cutoff is not None
        and model_cutoff is not None
        and model_cutoff > portfolio_cutoff
    )
    model_date = _date_key(model_decision_time)
    if distribution is not None and (
        model_date is None
        or (portfolio_cutoff is not None and model_cutoff is None)
        or model_postdates_snapshot
        or (portfolio_cutoff is None and portfolio_date and model_date > portfolio_date)
    ):
        distribution = None
    forecast_quantiles: dict[str, object] = {}
    expected_gain_loss: dict[str, object] = {}
    if distribution is None:
        distribution_reason = "stored_distribution_as_of_or_exact_horizon_unavailable"
        forecast_quantiles = _unavailable_quantiles(distribution_reason)
        expected_gain_loss = _unavailable_quantiles(distribution_reason)
        row["expected_return"] = _cell(None, distribution_reason)
    elif str(_member(distribution, "status", "unavailable")) != "available" or _positive_integer(_member(distribution, "horizon_days")) != horizon_days:
        distribution_reason = _text(_member(distribution, "reason")) or "stored_distribution_for_exact_horizon_unavailable"
        forecast_quantiles = _unavailable_quantiles(distribution_reason)
        expected_gain_loss = _unavailable_quantiles(distribution_reason)
        row["expected_return"] = _cell(None, distribution_reason)
    else:
        gross = _mapping(_member(distribution, "gross_quantiles"))
        net = _mapping(_member(distribution, "net_quantiles"))
        net_status = str(_member(distribution, "net_status", "unavailable"))
        return_components = _mapping(_member(distribution, "return_components"))
        fx_scenario_available = _finite(return_components.get("fx_return")) is not None
        expected = net.get("q50_return") if net_status == "available" else None
        row["expected_return"] = _cell(expected, _text(_member(distribution, "net_reason")) or "net_expected_return_unavailable")
        for level in _QUANTILES:
            field = f"q{level:02d}_return"
            forecast_quantiles[f"gross_{field}"] = _cell(gross.get(field), f"gross_{field}_unavailable")
            forecast_quantiles[f"net_{field}"] = _cell(net.get(field), _text(_member(distribution, "net_reason")) or f"net_{field}_unavailable")
            scenario_reason = None if fx_scenario_available else "stored_fx_scenario_unavailable"
            expected_gain_loss[f"gross_{field}"] = _impact_cell(gross.get(field), value, currency_reason or scenario_reason)
            expected_gain_loss[f"net_{field}"] = _impact_cell(net.get(field), value, currency_reason or scenario_reason)
        row["distribution_return_components"] = _cell(
            return_components if fx_scenario_available else None,
            "stored_fx_scenario_or_return_components_unavailable",
        )
    row["forecast_quantiles"] = forecast_quantiles
    row["expected_gain_loss"] = expected_gain_loss
    row["horizon_days"] = horizon_days
    return row


def _impact_cell(quantile: object, value: Mapping[str, object], currency_reason: str | None) -> dict[str, object]:
    if currency_reason:
        return _cell(None, currency_reason)
    amount = _finite(_member(value, "value"))
    return_value = _finite(quantile)
    if amount is None or return_value is None:
        reason = _text(_member(value, "reason")) or "stored_return_quantile_or_output_value_unavailable"
        return _cell(None, reason)
    return _cell(amount * return_value)


def _converted_cell(
    value: object,
    rate: float | None,
    currency: str,
    currency_reason: str | None,
    missing_reason: str,
) -> dict[str, object]:
    amount = _finite(value)
    if amount is None:
        return _cell(None, missing_reason)
    if rate is None:
        return _cell(None, currency_reason or "canonical_output_currency_projection_unavailable")
    return {"status": "available", "value": amount * rate, "currency": currency, "reason": None}


def _distribution_for(distributions: object, identity: str, horizon_days: int | None) -> Mapping[str, object] | None:
    if horizon_days is None or not isinstance(distributions, Mapping):
        return None
    rows = distributions.get(identity)
    if isinstance(rows, Mapping) and any(str(key).isdigit() for key in rows):
        row = rows.get(horizon_days, rows.get(str(horizon_days)))
    else:
        row = rows
    return row if isinstance(row, Mapping) and _positive_integer(row.get("horizon_days")) == horizon_days else None


def _index_analysis_rows(
    snapshot: Mapping[str, object] | None,
) -> tuple[dict[str, Mapping[str, object]], set[str]]:
    if not isinstance(snapshot, Mapping):
        return {}, set()
    rows = snapshot.get("rows", {})
    if isinstance(rows, Mapping):
        indexed: dict[str, Mapping[str, object]] = {}
        conflicts: set[str] = set()
        for key, value in rows.items():
            identity = str(key).strip()
            row_identity = _text(_member(value, "instrument_id")) if isinstance(value, Mapping) else None
            if not identity or not isinstance(value, Mapping) or row_identity != identity:
                if identity:
                    conflicts.add(identity)
                continue
            indexed[identity] = value
        return indexed, conflicts
    if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
        indexed: dict[str, Mapping[str, object]] = {}
        conflicts: set[str] = set()
        for row in rows:
            if isinstance(row, Mapping):
                identity = _text(_member(row, "instrument_id"))
                if identity:
                    if identity in indexed:
                        indexed.pop(identity, None)
                        conflicts.add(identity)
                        continue
                    if identity in conflicts:
                        continue
                    indexed[identity] = row
        return indexed, conflicts
    return {}, set()


def _matches(row: Mapping[str, object], search: str, asset_type: str | None) -> bool:
    requested_asset = str(asset_type or "all").strip().casefold()
    actual_asset = _asset_group(_text(_member(row.get("asset_type"), "value")) or "")
    if requested_asset not in {"", "all"} and _asset_group(requested_asset) != actual_asset:
        return False
    needle = str(search or "").strip().casefold()
    if not needle:
        return True
    return needle in str(row.get("instrument_id", "")).casefold() or needle in str(
        _member(row.get("name"), "value", "")
    ).casefold()


def _sort_rows(rows: list[dict[str, object]], field: str, descending: bool) -> list[dict[str, object]]:
    if field == "instrument_id":
        known = sorted(rows, key=lambda row: str(row.get(field, "")).casefold(), reverse=descending)
        return known
    known: list[dict[str, object]] = []
    missing: list[dict[str, object]] = []
    for row in rows:
        value = row.get(field)
        if isinstance(value, Mapping):
            value = value.get("value") if value.get("status") == "available" else None
        if value is None:
            missing.append(row)
        else:
            known.append(row)
    known.sort(key=lambda row: _sort_value(row.get(field)), reverse=descending)
    missing.sort(key=lambda row: str(row.get("instrument_id", "")).casefold())
    return [*known, *missing]


def _sort_value(value: object) -> tuple[int, object]:
    if isinstance(value, Mapping):
        value = value.get("value")
    if isinstance(value, Real) and not isinstance(value, bool):
        return 0, float(value)
    return 1, str(value).casefold()


def _asset_group(value: str) -> str:
    cleaned = value.strip().casefold().replace("-", "_").replace(" ", "_")
    if cleaned in {"stock", "equity", "equity_certificate"}:
        return "stock"
    if cleaned in {"etf", "fund", "exchange_traded_fund"}:
        return "etf"
    if cleaned in {"bond", "fixed_income", "debt"}:
        return "bond"
    return cleaned


def _unavailable_scores(reason: str) -> dict[str, object]:
    return {name: _cell(None, reason) for name in ("evidence", "quality", "risk")}


def _unavailable_quantiles(reason: str) -> dict[str, object]:
    return {
        f"{kind}_q{level:02d}_return": _cell(None, reason)
        for kind in ("gross", "net")
        for level in _QUANTILES
    }


def _cell(value: object, reason: str | None = None) -> dict[str, object]:
    if value is None:
        return {"status": "unavailable", "value": None, "reason": reason or "source_value_unavailable"}
    if isinstance(value, Real) and not isinstance(value, bool) and not math.isfinite(float(value)):
        return {"status": "unavailable", "value": None, "reason": reason or "source_value_not_finite"}
    return {"status": "available", "value": value, "reason": None}


def _member(value: object, key: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _first_present(value: Mapping[str, object], *keys: str) -> object:
    return next((value[key] for key in keys if key in value and value[key] is not None), None)


def _text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _positive_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result > 0 and result == value else None


def _date_key(value: object) -> str | None:
    if value is None:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert("UTC")
    return parsed.date().isoformat()


def _decision_timestamp(value: object) -> pd.Timestamp | None:
    """Keep precise timezone-aware evidence times for point-in-time checks."""

    if value is None:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed) or parsed.tzinfo is None:
        return None
    return parsed.tz_convert("UTC")
