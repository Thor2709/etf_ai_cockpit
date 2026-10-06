"""Fixed-income terms, market-data, analytics, risk and screener read models (application; ADR-0002)."""

from collections.abc import (
    Mapping,
    Sequence,
)
from dataclasses import asdict
from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import (
    Decimal,
    InvalidOperation,
)
import hashlib
import json
from pathlib import Path
import sqlite3

from etf_cockpit.core.paths import ROOT
from etf_cockpit.data.local_storage import (
    StorageRevisionConflict,
    StorageSchemaError,
    TransactionalStore,
)
from etf_cockpit.analysis.fixed_income_analytics import (
    FixedIncomeAnalyticsError,
    ObservedBondPrice,
    FixedIncomeValuationInput,
    calculate_fixed_income_analytics,
    valuation_input_from_terms,
)
from etf_cockpit.data.bond_analytics_store import (
    _input_from_payload,
    read_bond_analytics,
)
from etf_cockpit.analysis.fixed_income_risk import (
    FixedIncomeRiskError,
    FixedIncomeRiskInput,
    calculate_fixed_income_risk,
)
from etf_cockpit.data.fixed_income_risk_store import (
    _risk_input,
    read_fixed_income_risk,
)
from etf_cockpit.data.fixed_income_terms import (
    FixedIncomeTermsSchemaError,
    FixedIncomeTermsStore,
    fixed_income_terms_exists,
)
from etf_cockpit.data.fixed_income_market_data import (
    FixedIncomeMarketDataSchemaError,
    FixedIncomeMarketDataStore,
    fixed_income_market_data_exists,
)
from etf_cockpit.analysis.fixed_income_returns import FixedIncomeReturnInput
from etf_cockpit.analysis.fixed_income_screener import (
    FIXED_INCOME_SCREENER_CONFIG,
    FIXED_INCOME_SCREENER_CONTRACT,
    FixedIncomeScreenerError,
    FixedIncomeScreenerSecurity,
    FixedIncomeScreenerSnapshot,
    build_fixed_income_screener,
    load_fixed_income_screener_config,
)
from etf_cockpit.data.classification import (
    ClassificationSchemaError,
    classification_store_exists,
    read_instrument_context,
)


def load_fixed_income_terms_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return read-only contractual terms/schedules or an explicit unavailable state."""

    from datetime import datetime

    from etf_cockpit.core.paths import ROOT

    root = Path(storage_root or ROOT).resolve()
    unavailable = {
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_terms_unavailable"],
        "capability_flags": {
            "terms_available": False,
            "contractual_schedule_available": False,
            "pricing_allowed": False,
            "screening_allowed": False,
            "proposal_allowed": False,
            "execution_allowed": False,
        },
        "pricing_allowed": False,
        "screening_allowed": False,
        "proposal_allowed": False,
        "execution_allowed": False,
    }
    try:
        if not fixed_income_terms_exists(root):
            return unavailable
        effective = (
            datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
            if effective_at
            else None
        )
        decision = (
            datetime.fromisoformat(decision_time.replace("Z", "+00:00"))
            if decision_time
            else None
        )
        classification = (
            read_instrument_context(
                root,
                instrument_id,
                effective_at=effective,
                decision_time=decision,
            )
            if classification_store_exists(root)
            else None
        )
        with FixedIncomeTermsStore(root) as store:
            return store.projection(
                instrument_id,
                effective_at=effective,
                decision_time=decision,
                classification=classification,
            )
    except (
        ClassificationSchemaError,
        FixedIncomeTermsSchemaError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ):
        return unavailable | {"reason_codes": ["fixed_income_terms_invalid"]}


def load_fixed_income_market_data_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    effective_at: str | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Return read-only fixed-income market evidence for presentation."""

    from datetime import datetime
    from etf_cockpit.core.paths import ROOT

    root = Path(storage_root or ROOT).resolve()
    unavailable = {
        "contract": "fixed-income-market-data.v1",
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_market_data_unavailable"],
        "observations": [],
        "provider_coverage": {"status": "unavailable", "rows": []},
        "precise_liquidity_available": False,
        "execution_allowed": False,
    }
    try:
        if not fixed_income_market_data_exists(root):
            return unavailable
        effective = (
            datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
            if effective_at
            else None
        )
        decision = (
            datetime.fromisoformat(decision_time.replace("Z", "+00:00"))
            if decision_time
            else None
        )
        with FixedIncomeMarketDataStore(root) as store:
            return store.resolve(
                instrument_id,
                effective_at=effective,
                decision_time=decision,
            )
    except (FixedIncomeMarketDataSchemaError, OSError, TypeError, ValueError):
        return unavailable


def calculate_fixed_income_analytics_projection(
    valuation: FixedIncomeValuationInput,
) -> dict[str, object]:
    """Calculate and serialize analytics behind the application boundary."""

    from dataclasses import asdict

    projection = _analytics_jsonable(
        asdict(calculate_fixed_income_analytics(valuation))
    )
    if not isinstance(projection, dict):
        raise FixedIncomeAnalyticsError("analytics projection is invalid")
    return projection


def calculate_fixed_income_risk_projection(
    risk_input: FixedIncomeRiskInput,
) -> dict[str, object]:
    """Calculate a serialisable non-executable fixed-income risk projection."""

    from dataclasses import asdict

    projection = _analytics_jsonable(asdict(calculate_fixed_income_risk(risk_input)))
    if not isinstance(projection, dict):
        raise FixedIncomeRiskError("risk projection is invalid")
    return projection


def load_fixed_income_risk_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Load verified local risk evidence for presentation only."""

    from datetime import datetime
    from etf_cockpit.core.paths import ROOT

    unavailable = {
        "contract": "fixed-income-risk.v1",
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_risk_unavailable"],
        "execution_allowed": False,
    }
    path = Path(storage_root or ROOT) / "data" / "analytics" / "fixed_income_risk.parquet"
    if not path.exists():
        return unavailable
    try:
        cutoff = datetime.fromisoformat(decision_time.replace("Z", "+00:00")) if decision_time else None
        rows = [
            row for row in read_fixed_income_risk(path)
            if row["instrument_id"] == str(instrument_id)
            and (cutoff is None or datetime.fromisoformat(str(row["decision_time"])) <= cutoff)
        ]
        if not rows:
            return unavailable
        result = max(rows, key=lambda row: (str(row["decision_time"]), str(row["calculated_at"])))["result"]
        return dict(result) if isinstance(result, dict) else unavailable
    except (FixedIncomeRiskError, OSError, TypeError, ValueError):
        return unavailable | {"reason_codes": ["fixed_income_risk_invalid"]}


def load_fixed_income_analytics_projection(
    instrument_id: str,
    *,
    storage_root: Path | None = None,
    decision_time: str | None = None,
) -> dict[str, object]:
    """Load the latest local analytics record, failing closed when unavailable."""

    from datetime import datetime

    from etf_cockpit.core.paths import ROOT

    unavailable = {
        "status": "unavailable",
        "instrument_id": str(instrument_id),
        "reason_codes": ["fixed_income_analytics_unavailable"],
        "execution_allowed": False,
    }
    path = Path(storage_root or ROOT) / "data" / "analytics" / "bond_analytics.parquet"
    if not path.exists():
        return unavailable
    try:
        cutoff = (
            datetime.fromisoformat(decision_time.replace("Z", "+00:00"))
            if decision_time
            else None
        )
        matches = [
            row
            for row in read_bond_analytics(path)
            if row["instrument_id"] == str(instrument_id)
            and (
                cutoff is None
                or datetime.fromisoformat(str(row["decision_time"])) <= cutoff
            )
        ]
        if not matches:
            return unavailable
        latest = max(
            matches,
            key=lambda row: (
                str(row["decision_time"]),
                str(row["calculated_at"]),
                str(row["record_id"]),
            ),
        )
        result = latest["result"]
        return dict(result) if isinstance(result, dict) else unavailable
    except (FixedIncomeAnalyticsError, OSError, TypeError, ValueError):
        return unavailable | {"reason_codes": ["fixed_income_analytics_invalid"]}


def load_fixed_income_screener(
    *,
    storage_root: Path | None = None,
    decision_time: datetime | str | None = None,
    instrument_ids: Sequence[str] | None = None,
) -> dict[str, object]:
    """Build and persist a point-in-time fixed-income screen from local evidence."""

    root = Path(storage_root or ROOT).resolve()
    try:
        decision = _fixed_income_decision_time(decision_time)
        config = load_fixed_income_screener_config(root / FIXED_INCOME_SCREENER_CONFIG)
    except (FixedIncomeScreenerError, TypeError, ValueError, OSError) as exc:
        return {
            "contract": FIXED_INCOME_SCREENER_CONTRACT,
            "status": "unavailable",
            "decision_time": str(decision_time or ""),
            "rows": [],
            "top_n_instrument_ids": [],
            "reason_codes": [
                "fixed_income_screener_config_unavailable"
                if "config" in str(exc).casefold()
                else "fixed_income_screener_decision_time_invalid"
            ],
            "persistence_status": "not_attempted",
            "execution_allowed": False,
        }

    requested = (
        None
        if instrument_ids is None
        else {str(value).strip() for value in instrument_ids if str(value).strip()}
    )
    term_ids: set[str] = set()
    term_entities = ()
    if fixed_income_terms_exists(root):
        try:
            with TransactionalStore(root) as transaction:
                term_entities = transaction.list("fixed_income_terms_v1")
        except (StorageSchemaError, sqlite3.DatabaseError, OSError, ValueError):
            term_entities = ()
    for record in term_entities:
        payload = record.payload
        term = payload.get("terms") if isinstance(payload, Mapping) else None
        if not isinstance(term, Mapping):
            continue
        try:
            known_at = _fixed_income_datetime(term["known_at"])
            retrieved_at = _fixed_income_datetime(term["retrieved_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if known_at <= decision and retrieved_at <= decision:
            instrument_id = str(term.get("instrument_id") or "").strip()
            if instrument_id:
                term_ids.add(instrument_id)

    selected_ids = sorted(term_ids if requested is None else term_ids | requested)
    try:
        analytics_inputs = _fixed_income_saved_valuation_inputs(root, decision)
    except (FixedIncomeAnalyticsError, StorageSchemaError, sqlite3.DatabaseError, OSError, ValueError):
        analytics_inputs = {}
    try:
        risk_inputs = _fixed_income_saved_risk_inputs(root, decision)
    except (FixedIncomeRiskError, StorageSchemaError, sqlite3.DatabaseError, OSError, ValueError):
        risk_inputs = {}
    securities: list[FixedIncomeScreenerSecurity] = []
    try:
        if fixed_income_terms_exists(root):
            with FixedIncomeTermsStore(root) as terms_store:
                for instrument_id in selected_ids:
                    resolution = terms_store.resolve(
                        instrument_id,
                        effective_at=decision,
                        decision_time=decision,
                    )
                    terms = resolution.terms
                    reasons = list(resolution.reason_codes)
                    if resolution.status != "available" or terms is None:
                        securities.append(
                            _fixed_income_security(
                                instrument_id,
                                terms=terms,
                                return_input=None,
                                liquidity_bucket=None,
                                liquidity_status="unavailable",
                                reason_codes=tuple(reasons or ("fixed_income_terms_unavailable",)),
                                portfolio_fit=_portfolio_fit(instrument_id, requested),
                            )
                        )
                        continue

                    context = None
                    if classification_store_exists(root):
                        try:
                            context = read_instrument_context(
                                root,
                                instrument_id,
                                effective_at=decision,
                                decision_time=decision,
                            )
                        except (ClassificationSchemaError, KeyError, OSError, TypeError, ValueError):
                            reasons.append("fixed_income_classification_unavailable")

                    market = load_fixed_income_market_data_projection(
                        instrument_id,
                        storage_root=root,
                        effective_at=decision.isoformat(),
                        decision_time=decision.isoformat(),
                    )
                    liquidity_status, liquidity_row = _fixed_income_liquidity(
                        market,
                        decision,
                        config.maximum_observation_age_days,
                    )
                    saved_valuation = analytics_inputs.get(instrument_id)
                    valuation = None
                    if (
                        saved_valuation is not None
                        and saved_valuation.terms_version_id == terms.version_id
                        and _fixed_income_age_days(decision, saved_valuation.decision_time)
                        <= config.maximum_observation_age_days
                    ):
                        valuation = saved_valuation
                    elif saved_valuation is not None:
                        reasons.append("canonical_valuation_stale_or_terms_mismatch")

                    if valuation is None:
                        valuation = _fixed_income_market_valuation(
                            terms,
                            resolution.coupon_schedule,
                            resolution.redemption_schedule,
                            market,
                            decision,
                            saved_valuation.curve if saved_valuation is not None else None,
                            maximum_age_days=config.maximum_observation_age_days,
                        )
                    if valuation is None:
                        reasons.append("canonical_valuation_input_unavailable")

                    saved_risk = risk_inputs.get(instrument_id)
                    matched_risk = (
                        saved_risk
                        if saved_risk is not None
                        and valuation is not None
                        and saved_risk.valuation.input_hash == valuation.input_hash
                        else None
                    )
                    cost_bps = _fixed_income_liquidity_cost(liquidity_row)
                    if cost_bps is None and matched_risk is not None:
                        cost_bps = matched_risk.liquidity_cost_bps
                    fx_return = (
                        Decimal("0")
                        if terms.currency.upper() == config.base_currency
                        else None
                    )
                    return_input = (
                        FixedIncomeReturnInput(
                            valuation=valuation,
                            horizon_days=config.horizon_days,
                            rate_shock_bps=config.rate_shock_bps,
                            spread_shock_bps=config.spread_shock_bps,
                            default_probability=(
                                matched_risk.default_probability if matched_risk is not None else None
                            ),
                            recovery_rate=(matched_risk.recovery_rate if matched_risk is not None else None),
                            fx_return=fx_return,
                            cost_bps=cost_bps,
                        )
                        if valuation is not None
                        else None
                    )
                    lineage = [terms.version_id]
                    if valuation is not None:
                        lineage.append(valuation.input_hash)
                    if liquidity_row and liquidity_row.get("observation_id"):
                        lineage.append(str(liquidity_row["observation_id"]))
                    securities.append(
                        _fixed_income_security(
                            instrument_id,
                            terms=terms,
                            context=context,
                            return_input=return_input,
                            liquidity_bucket=_context_value(context, "liquidity_bucket"),
                            liquidity_status=liquidity_status,
                            reason_codes=tuple(dict.fromkeys(reasons)),
                            source_lineage=tuple(lineage),
                            portfolio_fit=_portfolio_fit(instrument_id, requested),
                        )
                    )
        else:
            for instrument_id in selected_ids:
                securities.append(
                    _fixed_income_security(
                        instrument_id,
                        terms=None,
                        return_input=None,
                        liquidity_bucket=None,
                        liquidity_status="unavailable",
                        reason_codes=("fixed_income_terms_unavailable_at_decision_time",),
                        portfolio_fit=_portfolio_fit(instrument_id, requested),
                    )
                )
    except (FixedIncomeTermsSchemaError, StorageSchemaError, sqlite3.DatabaseError, OSError, ValueError) as exc:
        return {
            "contract": FIXED_INCOME_SCREENER_CONTRACT,
            "status": "unavailable",
            "decision_time": decision.isoformat(),
            "rows": [],
            "top_n_instrument_ids": [],
            "reason_codes": ["fixed_income_terms_or_storage_invalid"],
            "detail": str(exc),
            "persistence_status": "not_attempted",
            "execution_allowed": False,
        }

    snapshot = build_fixed_income_screener(
        securities,
        decision_time=decision,
        config=config,
    )
    try:
        persistence_status = (
            "available" if _persist_fixed_income_screener_snapshot(root, snapshot) else "no_rows"
        )
    except (StorageRevisionConflict, StorageSchemaError, sqlite3.DatabaseError, OSError, TypeError, ValueError):
        persistence_status = "unavailable"

    rows = []
    for item in snapshot.rows:
        projected = _analytics_jsonable(asdict(item))
        rows.append(dict(projected) | {"persisted": persistence_status == "available"})
    reasons = list(snapshot.reason_codes)
    if persistence_status == "unavailable":
        reasons.append("fixed_income_screener_persistence_unavailable")
    if requested is not None and not selected_ids:
        reasons.append("no_fixed_income_holdings_selected")
    if requested is None and not selected_ids:
        reasons.append("fixed_income_terms_unavailable_at_decision_time")
    return {
        "contract": FIXED_INCOME_SCREENER_CONTRACT,
        "status": snapshot.status,
        "analysis_snapshot_id": snapshot.analysis_snapshot_id,
        "decision_time": snapshot.decision_time.isoformat(),
        "horizon_days": config.horizon_days,
        "base_currency": config.base_currency,
        "minimum_peer_support": config.minimum_peer_support,
        "top_n": config.top_n,
        "top_n_instrument_ids": list(snapshot.top_n_instrument_ids),
        "rows": rows,
        "reason_codes": list(dict.fromkeys(reasons)),
        "persistence_status": persistence_status,
        "execution_allowed": False,
    }


def _persist_fixed_income_screener_snapshot(
    root: Path, snapshot: FixedIncomeScreenerSnapshot
) -> bool:
    if not snapshot.rows:
        return False
    records = []
    for row in snapshot.rows:
        row_payload = _analytics_jsonable(asdict(row))
        encoded = json.dumps(row_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        records.append(
            (
                "fixed_income_screener_row_v1",
                row.record_id,
                {
                    "schema_version": 1,
                    "contract": FIXED_INCOME_SCREENER_CONTRACT,
                    "analysis_snapshot_id": snapshot.analysis_snapshot_id,
                    "instrument_id": row.instrument_id,
                    "decision_time": snapshot.decision_time.isoformat(),
                    "status": row.status,
                    "reason_codes": list(row.reason_codes),
                    "row_json": encoded,
                    "row_checksum": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                    "execution_allowed": False,
                },
            )
        )
    with TransactionalStore(root) as store:
        store.put_many(records, immutable=True)
        stored = {
            (item.entity_type, item.entity_id): item.payload
            for item in store.list("fixed_income_screener_row_v1")
        }
    return all(stored.get((kind, entity_id)) == payload for kind, entity_id, payload in records)


def _fixed_income_saved_valuation_inputs(
    root: Path, decision_time: datetime
) -> dict[str, FixedIncomeValuationInput]:
    path = root / "data" / "analytics" / "bond_analytics.parquet"
    if not path.is_file():
        return {}
    validated = read_bond_analytics(path)
    valid_by_id = {str(row["record_id"]): row for row in validated}
    with TransactionalStore(root) as store:
        stored = store.list("bond_analytics_v1")
    candidates: dict[str, list[tuple[datetime, datetime, str, FixedIncomeValuationInput]]] = {}
    for record in stored:
        payload = record.payload
        record_id = str(payload.get("record_id") or "")
        if record_id not in valid_by_id:
            continue
        try:
            decision = _fixed_income_datetime(payload["decision_time"])
            calculated = _fixed_income_datetime(payload["calculated_at"])
            if decision > decision_time or calculated > decision_time:
                continue
            valuation_payload = json.loads(str(payload["input_json"]))
            valuation = _input_from_payload(valuation_payload)
            if valuation.input_hash != valid_by_id[record_id]["input_hash"]:
                continue
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        candidates.setdefault(valuation.instrument_id, []).append(
            (decision, calculated, record_id, valuation)
        )
    return {
        instrument_id: max(values, key=lambda item: (item[0], item[1], item[2]))[3]
        for instrument_id, values in candidates.items()
    }


def _fixed_income_saved_risk_inputs(root: Path, decision_time: datetime) -> dict[str, FixedIncomeRiskInput]:
    path = root / "data" / "analytics" / "fixed_income_risk.parquet"
    if not path.is_file():
        return {}
    validated = read_fixed_income_risk(path)
    valid_by_id = {str(row["record_id"]): row for row in validated}
    with TransactionalStore(root) as store:
        stored = store.list("fixed_income_risk_v1")
    candidates: dict[str, list[tuple[datetime, datetime, str, FixedIncomeRiskInput]]] = {}
    for record in stored:
        payload = record.payload
        record_id = str(payload.get("record_id") or "")
        if record_id not in valid_by_id:
            continue
        try:
            decision = _fixed_income_datetime(payload["decision_time"])
            calculated = _fixed_income_datetime(payload["calculated_at"])
            if decision > decision_time or calculated > decision_time:
                continue
            risk_input = _risk_input(json.loads(str(payload["input_json"])))
            if risk_input.input_hash != valid_by_id[record_id]["input_hash"]:
                continue
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        candidates.setdefault(risk_input.valuation.instrument_id, []).append(
            (decision, calculated, record_id, risk_input)
        )
    return {
        instrument_id: max(values, key=lambda item: (item[0], item[1], item[2]))[3]
        for instrument_id, values in candidates.items()
    }


def _fixed_income_market_valuation(
    terms: object,
    coupon_schedule: object,
    redemption_schedule: object,
    market: Mapping[str, object],
    decision_time: datetime,
    saved_curve: object = None,
    *,
    maximum_age_days: int,
) -> FixedIncomeValuationInput | None:
    observations = market.get("observations")
    if not isinstance(observations, list):
        return None
    quotes = [
        row
        for row in observations
        if isinstance(row, Mapping) and row.get("observation_type") == "price"
    ]
    if not quotes:
        return None
    quote = max(quotes, key=lambda row: (str(row.get("valid_at", "")), str(row.get("provider_id", ""))))
    try:
        values = quote.get("values") if isinstance(quote.get("values"), Mapping) else {}
        settlement_raw = values.get("settlement_date")
        settlement = date.fromisoformat(str(settlement_raw))
        valid_at = _fixed_income_datetime(quote["valid_at"])
        known_at = _fixed_income_datetime(quote["known_at"])
        retrieved_at = _fixed_income_datetime(quote["retrieved_at"])
        if (
            valid_at > decision_time
            or known_at > decision_time
            or retrieved_at > decision_time
            or _fixed_income_age_days(decision_time, valid_at) > maximum_age_days
        ):
            return None
        price_unit = str(values.get("price_unit") or "")
        yield_unit = str(values.get("yield_unit") or "")
        clean_price = (
            Decimal(str(quote["clean_price"]))
            if quote.get("clean_price") is not None and price_unit == "per_100"
            else None
        )
        yield_value = (
            Decimal(str(quote["yield_value"]))
            if quote.get("yield_value") is not None and yield_unit == "decimal"
            else None
        )
        if clean_price is None and yield_value is None:
            return None
        observed_price = (
            ObservedBondPrice(
                clean_price=clean_price,
                currency=str(quote.get("currency") or ""),
                price_unit="per_100",
                source_id=str(quote.get("provider_id") or ""),
                source_checksum=str(quote.get("source_checksum") or ""),
                as_of=valid_at,
                retrieved_at=retrieved_at,
            )
            if clean_price is not None
            else None
        )
        curve = (
            saved_curve
            if getattr(saved_curve, "currency", None) == getattr(terms, "currency", None)
            and getattr(saved_curve, "decision_time", decision_time) <= decision_time
            and _fixed_income_age_days(decision_time, getattr(saved_curve, "as_of", decision_time))
            <= maximum_age_days
            else None
        )
        return valuation_input_from_terms(
            terms,
            coupon_schedule,
            redemption_schedule,
            settlement_date=settlement,
            decision_time=decision_time,
            clean_price=clean_price,
            yield_to_maturity=yield_value,
            curve=curve,
            observed_price=observed_price,
        )
    except (KeyError, InvalidOperation, TypeError, ValueError, FixedIncomeAnalyticsError):
        return None


def _fixed_income_liquidity(
    market: Mapping[str, object], decision_time: datetime, maximum_age_days: int
) -> tuple[str, Mapping[str, object] | None]:
    observations = market.get("observations")
    rows = [
        item
        for item in observations
        if isinstance(item, Mapping) and item.get("observation_type") == "bond_liquidity"
    ] if isinstance(observations, list) else []
    if market.get("status") != "available" or not market.get("precise_liquidity_available"):
        return "unavailable", rows[-1] if rows else None
    for row in rows:
        try:
            if (
                row.get("precise_liquidity_available")
                and _fixed_income_age_days(decision_time, _fixed_income_datetime(row["valid_at"]))
                <= maximum_age_days
            ):
                return "available", row
        except (KeyError, TypeError, ValueError):
            continue
    return "unavailable", rows[-1] if rows else None


def _fixed_income_liquidity_cost(row: Mapping[str, object] | None) -> Decimal | None:
    if row is None or row.get("bid") is None or row.get("ask") is None:
        return None
    try:
        bid = Decimal(str(row["bid"]))
        ask = Decimal(str(row["ask"]))
        midpoint = (bid + ask) / Decimal("2")
        if not bid.is_finite() or not ask.is_finite() or bid <= 0 or ask < bid or midpoint <= 0:
            return None
        return (ask - bid) / midpoint * Decimal("5000")
    except (InvalidOperation, TypeError, ValueError):
        return None


def _fixed_income_security(
    instrument_id: str,
    *,
    terms: object,
    return_input: FixedIncomeReturnInput | None,
    liquidity_bucket: object,
    liquidity_status: str,
    reason_codes: tuple[str, ...],
    context: object = None,
    source_lineage: tuple[str, ...] = (),
    portfolio_fit: str = "not_assessed",
) -> FixedIncomeScreenerSecurity:
    return FixedIncomeScreenerSecurity(
        instrument_id=instrument_id,
        security_type=_context_value(terms, "security_type"),
        issuer_id=_context_value(terms, "issuer_id"),
        issuer_sector=_context_value(context, "issuer_sector"),
        country=(_context_value(terms, "country") or _context_value(context, "regulatory_country")),
        currency=_context_value(terms, "currency"),
        seniority=_context_value(terms, "seniority"),
        rating=_context_value(context, "rating_bucket"),
        coupon_type=_context_value(terms, "coupon_type"),
        maturity_date=_context_value(terms, "maturity_date"),
        duration_years=None,
        liquidity_bucket=(str(liquidity_bucket) if liquidity_bucket else None),
        liquidity_status=liquidity_status,
        return_input=return_input,
        reason_codes=reason_codes,
        source_lineage=source_lineage,
        portfolio_fit=portfolio_fit,
    )


def _context_value(context: object, field: str) -> object:
    if isinstance(context, Mapping):
        return context.get(field)
    return getattr(context, field, None) if context is not None else None


def _portfolio_fit(instrument_id: str, selected: set[str] | None) -> str:
    if selected is None:
        return "not_assessed"
    return "current_holding" if instrument_id in selected else "not_in_selected_portfolio"


def _fixed_income_decision_time(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = _fixed_income_datetime(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _fixed_income_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _fixed_income_age_days(decision_time: datetime, value: object) -> int:
    timestamp = _fixed_income_datetime(value)
    seconds = (decision_time - timestamp).total_seconds()
    if seconds < 0:
        raise ValueError("evidence is future-known")
    return int(seconds // 86400)


def _analytics_jsonable(value: object) -> object:
    from datetime import date, datetime
    from decimal import Decimal
    from enum import Enum
    from collections.abc import Mapping

    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _analytics_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_analytics_jsonable(item) for item in value]
    return value
