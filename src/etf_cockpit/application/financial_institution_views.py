"""Financial-institution (bank) evidence read model for Instrument Detail (application; ADR-0002)."""

from collections.abc import Mapping
import json
import math
from numbers import Real
from pathlib import Path
import pandas as pd

from etf_cockpit.data.classification import read_instrument_context
from etf_cockpit.analysis.financial_sector_adapters import (
    FinancialAdapterError,
    FinancialInstitutionProjection,
    build_financial_institution_projection,
    financial_adapter_definition,
    unavailable_financial_projection,
    verify_financial_projection,
)
from etf_cockpit.analysis.peer_cohorts import AdapterRegistry
from etf_cockpit.signals.feature_drivers import _source_vintage_hash
from etf_cockpit.analysis.bank_metric_facts import (
    _financial_metric_facts,
)


def load_financial_institution_projection(
    instrument_id: str,
    *,
    projection: FinancialInstitutionProjection | Mapping[str, object] | None = None,
    storage_root: Path | None = None,
    universe_root: Path | None = None,
    decision_time: str | None = None,
    effective_at: str | None = None,
    context: object | None = None,
    tactical_evidence: Mapping[str, object] | None = None,
    record_history: bool = False,
) -> dict[str, object]:
    """Load a verified projection, or build one from local point-in-time evidence.

    Views are read-only; only the Sparebank refresh passes ``record_history=True`` to store the score.
    """

    # A cached projection for another instrument (stale UI selection) is ignored and rebuilt.
    if isinstance(projection, Mapping) and str(projection.get("instrument_id")) != str(instrument_id):
        projection = None
    if projection is None:
        try:
            return _build_financial_projection_from_evidence(
                instrument_id,
                storage_root=storage_root,
                universe_root=universe_root,
                decision_time=decision_time,
                effective_at=effective_at,
                context=context,
                tactical_evidence=tactical_evidence,
                record_history=record_history,
            )
        except (FinancialAdapterError, OSError, TypeError, ValueError, KeyError):
            return unavailable_financial_projection(
                instrument_id, "financial_evidence_invalid"
            )
    try:
        payload = verify_financial_projection(projection)
        if payload.get("instrument_id") != str(instrument_id):
            raise FinancialAdapterError("financial projection identity mismatch")
        return payload
    except (FinancialAdapterError, TypeError, ValueError):
        return unavailable_financial_projection(
            instrument_id, "financial_evidence_invalid"
        )


def _build_financial_projection_from_evidence(
    instrument_id: str,
    *,
    storage_root: Path | None,
    universe_root: Path | None,
    decision_time: str | None,
    effective_at: str | None,
    context: object | None,
    tactical_evidence: Mapping[str, object] | None = None,
    record_history: bool = False,
) -> dict[str, object]:
    """Adapt #699's persisted statement/EC artifacts to the domain adapter."""
    from datetime import datetime, timezone
    from etf_cockpit.core.paths import ROOT

    root = Path(storage_root or ROOT).resolve()
    identity = _read_json_artifact(root, "identity.json", instrument_id=instrument_id) or {}
    if context is None and not decision_time:
        from etf_cockpit.application.identity_views import load_classification_projection

        load_classification_projection(
            instrument_id,
            storage_root=root,
            universe_root=universe_root,
        )
    # The live view decides "as of now"; the filing's known_at only bounds which evidence is eligible.
    cutoff = str(decision_time or "").strip()
    if not cutoff:
        from etf_cockpit.data.universe_store import load_sparebank_records

        configured = next(
            (
                record
                for record in load_sparebank_records(universe_root or ROOT)
                if record.instrument_id == str(instrument_id)
            ),
            None,
        )
        if configured is None:
            return unavailable_financial_projection(instrument_id, "financial_decision_time_unavailable")
        cutoff = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    decision = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    cutoff = decision.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    effective = str(effective_at or identity.get("effective_at") or cutoff).strip()
    requested_period = str(effective_at or identity.get("effective_at") or "").strip() or None
    if len(effective) == 10:
        effective = f"{effective}T00:00:00Z"

    if context is None:
        from etf_cockpit.application.identity_views import load_classification_projection

        load_classification_projection(
            instrument_id,
            storage_root=root,
            universe_root=universe_root,
            effective_at=effective,
            decision_time=cutoff,
        )
        context = read_instrument_context(
            root,
            instrument_id,
            effective_at=effective,
            decision_time=cutoff,
        )
    if str(getattr(context, "sector", "") or "").casefold() != "financials":
        return unavailable_financial_projection(instrument_id, "financial_classification_unavailable")

    frame = _read_financial_statement_frame(root, instrument_id=instrument_id)
    rows = _financial_rows_for_instrument(frame, instrument_id, decision)
    facts = _financial_metric_facts(rows, context, cutoff, target_period=requested_period)

    registry = AdapterRegistry([financial_adapter_definition()])
    result = build_financial_institution_projection(
        context,
        tuple(facts),
        registry=registry,
        decision_time=cutoff,
        shocks={},
    )
    ec_payload = _read_json_artifact(root, "ec_facts.json", instrument_id=instrument_id) or {}
    ec_revision = _select_ec_revision(ec_payload, instrument_id, decision)
    ec_facts = ec_revision.get("facts", {}) if isinstance(ec_revision, Mapping) else {}
    from etf_cockpit.analysis.sparebank import analyse_sparebank_ec
    route_evidence = {
        "facts": ec_facts,
        "instrument_id": instrument_id,
        "jurisdiction": getattr(context, "operating_country", None)
        or getattr(context, "regulatory_country", None)
        or getattr(context, "legal_domicile", None),
        "legal_form": getattr(context, "issuer_type", None) or ec_revision.get("legal_form"),
        "instrument_subtype": getattr(context, "instrument_subtype", None) or ec_revision.get("instrument_subtype"),
        "capital_class": getattr(context, "share_class_id", None) or ec_revision.get("capital_class"),
        "known_at": ec_revision.get("known_at") or next(
            (value.get("known_at") for value in ec_facts.values() if isinstance(value, Mapping) and value.get("known_at")),
            ec_payload.get("known_at"),
        ),
        "effective_at": ec_revision.get("effective_at") or next(
            (value.get("effective_at") for value in ec_facts.values() if isinstance(value, Mapping) and value.get("effective_at")),
            ec_payload.get("effective_at"),
        ),
        "source_url": ec_revision.get("source_url") or ec_revision.get("source") or ec_payload.get("source_url"),
        "source_id": ec_revision.get("source_id") or ec_payload.get("source_id"),
        "sha256": ec_revision.get("sha256") or ec_payload.get("sha256"),
        "filing_version": ec_revision.get("filing_version") or ec_payload.get("filing_version"),
        "revision_id": ec_revision.get("revision_id") or ec_payload.get("revision_id"),
    }
    valuation_assumptions = ec_revision.get("valuation_assumptions")
    valuation_assumptions = valuation_assumptions if isinstance(valuation_assumptions, Mapping) else None
    valuation_currency = _valuation_currency(valuation_assumptions, context, ec_facts)
    price_path = root / "data" / "clean" / "prices.parquet"
    decision_price = None
    market_data_prices = None
    decision_price_projection: dict[str, object] = {
        "status": "unavailable",
        "reason_code": "decision_price_store_missing",
        "execution_allowed": False,
    }
    if price_path.is_file():
        try:
            from etf_cockpit.data.duckdb_store import load_prices

            prices = load_prices(price_path)
            instrument_column = "instrument_id" if "instrument_id" in prices.columns else "etf_id" if "etf_id" in prices.columns else None
            if instrument_column is None or not {"date", "close", "currency"}.issubset(prices.columns):
                decision_price_projection["reason_code"] = "decision_price_store_invalid"
            else:
                market_data_prices = prices
                eligible = prices.loc[prices[instrument_column].astype(str).eq(str(instrument_id))].copy()
                eligible["_price_date"] = pd.to_datetime(eligible["date"], errors="coerce", utc=True)
                available_at = eligible["_price_date"].where(
                    eligible["_price_date"].ne(eligible["_price_date"].dt.normalize()),
                    eligible["_price_date"].dt.normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59),
                )
                if "known_at" in eligible.columns:
                    known_at = pd.to_datetime(eligible["known_at"], errors="coerce", utc=True)
                    available_at = pd.concat([available_at, known_at], axis=1).max(axis=1, skipna=False)
                eligible = eligible.loc[
                    eligible["_price_date"].notna()
                    & available_at.notna()
                    & eligible["_price_date"].le(pd.Timestamp(decision))
                    & available_at.le(pd.Timestamp(decision))
                ]
                if eligible.empty:
                    decision_price_projection["reason_code"] = "decision_price_unavailable_as_of_decision"
                else:
                    price_row = eligible.sort_values("_price_date", kind="stable").iloc[-1]
                    close = pd.to_numeric(pd.Series([price_row["close"]]), errors="coerce").iloc[0]
                    currency_value = price_row["currency"]
                    price_currency = "" if pd.isna(currency_value) else str(currency_value).strip().upper()
                    if pd.isna(close) or not math.isfinite(float(close)) or float(close) <= 0:
                        decision_price_projection["reason_code"] = "decision_price_invalid"
                    elif not valuation_currency or not price_currency:
                        decision_price_projection["reason_code"] = "decision_price_currency_unavailable"
                    elif price_currency != valuation_currency:
                        decision_price_projection.update(
                            reason_code="decision_price_currency_mismatch",
                            date=price_row["_price_date"].date().isoformat(),
                            currency=price_currency,
                            valuation_currency=valuation_currency,
                        )
                    else:
                        decision_price = float(close)
                        decision_price_projection = {
                            "status": "available",
                            "price": decision_price,
                            "date": price_row["_price_date"].date().isoformat(),
                            "currency": price_currency,
                            "valuation_currency": valuation_currency,
                            "execution_allowed": False,
                        }
        except Exception:
            decision_price_projection["reason_code"] = "decision_price_store_invalid"
    sparebank_analysis = analyse_sparebank_ec(
        route_evidence,
        decision_time=cutoff,
        price=decision_price,
        bank_metrics=result.metrics,
        bank_economics_evidence=(ec_revision.get("bank_economics_evidence") if isinstance(ec_revision, Mapping) else None),
        events=(ec_revision.get("events", ()) if isinstance(ec_revision, Mapping) else ()),
        valuation_assumptions=_with_local_marketability(
            root,
            instrument_id,
            decision,
            market_data_prices,
            valuation_assumptions,
        ),
        tactical_evidence=tactical_evidence,
    )
    if sparebank_analysis.routing.applies or (isinstance(ec_facts, Mapping) and ec_facts):
        from dataclasses import asdict, replace
        identity_payload = dict(result.share_class_identity) if isinstance(result.share_class_identity, Mapping) else {}
        identity_payload["facts"] = {
            name: {
                "available": bool(value.get("available")) if isinstance(value, Mapping) else False,
                "value": value.get("value") if isinstance(value, Mapping) else None,
                "unit": value.get("unit") if isinstance(value, Mapping) else None,
                "period": value.get("period") if isinstance(value, Mapping) else None,
                "concept": value.get("concept") if isinstance(value, Mapping) else None,
                "context": value.get("context") if isinstance(value, Mapping) else None,
                "sha256": value.get("sha256") if isinstance(value, Mapping) else None,
                "known_at": value.get("known_at") if isinstance(value, Mapping) else None,
                "source": value.get("source_url") if isinstance(value, Mapping) else None,
            }
            for name, value in ec_facts.items()
            if isinstance(ec_facts, Mapping)
        }
        sparebank_payload = asdict(sparebank_analysis)
        sparebank_payload["decision_price"] = decision_price_projection
        source_vintage_hash = _source_vintage_hash(route_evidence.get("sha256")) or "unavailable"
        sparebank_payload["source_vintage_hash"] = source_vintage_hash
        scorecard = sparebank_analysis.scorecard
        composite = getattr(scorecard, "composite_10", None)
        if not record_history:
            history_status = {"status": "not_requested", "reason": "read_only_view"}
        elif isinstance(composite, Real) and not isinstance(composite, bool) and math.isfinite(float(composite)):
            try:
                from etf_cockpit.data.score_history import append_score_run

                append_score_run(
                    pd.DataFrame(
                        [
                            {
                                "instrument_id": str(instrument_id),
                                "final_combined_score_10": float(composite),
                                "coverage": getattr(scorecard, "composite_coverage", None),
                                "missing_components": "|".join(getattr(scorecard, "missing_axes", ()) or ()),
                                "price_as_of_date": decision_price_projection.get("date", ""),
                                "data_as_of_date": decision.date().isoformat(),
                                "formula_version": getattr(scorecard, "formula_version", "unavailable"),
                                "formula_checksum": getattr(scorecard, "formula_checksum", "unavailable"),
                                "source_vintage_hash": source_vintage_hash,
                            }
                        ]
                    ),
                    f"sparebank:{instrument_id}:{cutoff}",
                    cutoff,
                    root=root,
                )
                # Partial scores are recorded (owner 2026-10-09); a missing decision price is kept as the reason.
                history_status = {"status": "written", "reason": decision_price_projection.get("reason_code")}
            except Exception:
                history_status = {"status": "not_written", "reason": "score_history_write_failed"}
        else:
            reason = decision_price_projection.get("reason_code")
            if not reason:
                reason = "scorecard_blocked" if getattr(scorecard, "status", None) == "BLOCKED" else "scorecard_composite_unavailable"
            history_status = {"status": "not_written", "reason": reason}
        sparebank_payload["history_status"] = history_status
        identity_payload["sparebank_analysis"] = sparebank_payload
        identity_payload["native_suite"] = sparebank_analysis.contract if sparebank_analysis.routing.applies else None
        identity_payload["claim_status"] = sparebank_analysis.claim_state.claim_status
        identity_payload["generic_valuation_status"] = sparebank_analysis.generic_valuation_status
        identity_payload["generic_valuation_reason"] = sparebank_analysis.generic_valuation_reason
        if sparebank_analysis.generic_valuation_status == "inapplicable":
            result = replace(
                result,
                limitations=tuple(sorted({*result.limitations, "generic_bank_valuation:inapplicable_sparebank_claim"})),
            )
        result = replace(result, share_class_identity=identity_payload)
        from etf_cockpit.analysis.financial_sector_adapters import _hash as _financial_hash
        payload = result.__dict__.copy()
        payload.pop("result_hash", None)
        result = replace(result, result_hash=_financial_hash(payload))
    return verify_financial_projection(result)


def _evidence_roots(root: Path, instrument_id: str = "") -> tuple[Path, ...]:
    canonical = root / "evidence" / "norway"
    roots: list[Path] = [root]
    if instrument_id:
        prefix = f"{str(instrument_id).strip().upper()}-"
        try:
            roots.extend(sorted((item for item in canonical.iterdir() if item.is_dir() and item.name.upper().startswith(prefix)), key=lambda item: item.name))
        except OSError:
            pass
    roots.extend((canonical, root / "evidence"))
    return tuple(dict.fromkeys(roots))


def _select_ec_revision(payload: Mapping[str, object], instrument_id: str, decision: object) -> Mapping[str, object]:
    """Return the complete identity-bound EC revision envelope at the cutoff."""

    cutoff = pd.Timestamp(decision)
    revisions = payload.get("revisions")
    eligible: list[Mapping[str, object]] = []
    if isinstance(revisions, list):
        for revision in revisions:
            if not isinstance(revision, Mapping) or str(revision.get("instrument_id") or "") != str(instrument_id):
                continue
            known = pd.to_datetime(revision.get("known_at"), errors="coerce", utc=True)
            if pd.isna(known) or known > cutoff:
                continue
            facts = revision.get("facts")
            if isinstance(facts, Mapping):
                eligible.append(revision)
    if eligible:
        selected = max(eligible, key=lambda item: pd.Timestamp(item.get("known_at")))
        return selected
    # Backward-compatible read of a single pre-revision artifact, still bound
    # to the requested instrument and point-in-time cutoff.
    if str(payload.get("instrument_id") or instrument_id) != str(instrument_id):
        return {}
    known = pd.to_datetime(payload.get("known_at"), errors="coerce", utc=True)
    facts = payload.get("facts")
    return payload if isinstance(facts, Mapping) and not pd.isna(known) and known <= cutoff else {}


def _read_json_artifact(root: Path, name: str, *, instrument_id: str = "") -> dict[str, object] | None:
    import json

    candidates = tuple(item / name for item in _evidence_roots(root, instrument_id))
    for candidate in candidates:
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _read_financial_statement_frame(root: Path, *, instrument_id: str = "") -> pd.DataFrame:
    candidates = tuple(item / "statement_facts.parquet" for item in _evidence_roots(root, instrument_id)) + (
        root / "data" / "clean" / "statement_facts.parquet",
        root / "normalised_statements.parquet",
    )
    for candidate in candidates:
        try:
            if candidate.exists():
                frame = pd.read_parquet(candidate)
                if isinstance(frame, pd.DataFrame) and not frame.empty:
                    return frame
        except (OSError, ValueError, ImportError):
            continue
    return pd.DataFrame()


def _financial_rows_for_instrument(
    frame: pd.DataFrame, instrument_id: str, decision: object
) -> list[dict[str, object]]:
    if frame.empty or "instrument_id" not in frame.columns:
        return []
    scoped = frame.loc[frame["instrument_id"].astype(str).eq(str(instrument_id))]
    cutoff = pd.Timestamp(decision)
    rows: list[dict[str, object]] = []
    for row in scoped.to_dict("records"):
        known_raw = row.get("known_at") or row.get("available_at") or row.get("filed")
        effective_raw = row.get("effective_at") or row.get("end") or row.get("instant")
        known = pd.to_datetime(known_raw, errors="coerce", utc=True)
        effective = pd.to_datetime(effective_raw, errors="coerce", utc=True)
        if pd.isna(known) or known > cutoff or pd.isna(effective) or effective > cutoff:
            continue
        row["_known"] = known
        row["_effective"] = effective
        rows.append(row)
    return rows


def _with_local_marketability(
    root: Path,
    instrument_id: str,
    decision: object,
    prices: pd.DataFrame | None,
    assumptions: Mapping[str, object] | None,
) -> dict[str, object]:
    result = dict(assumptions or {})
    marketability = dict(result.get("marketability", {})) if isinstance(result.get("marketability"), Mapping) else {}
    report, report_name = _candidate_report_as_of(root, instrument_id, decision)
    price_rows = _market_prices_as_of(prices, instrument_id, decision)
    volume: float | None = None
    if not price_rows.empty and "volume" in price_rows.columns:
        volume_values = pd.to_numeric(price_rows["volume"], errors="coerce").dropna()
        if not volume_values.empty:
            volume = float(volume_values.tail(60).median())
    if volume is None and report is not None:
        volume = _finite_number(report.get("median_volume_60d"))

    quantity = _finite_number(report.get("shares")) if report is not None else None
    if quantity is None or quantity <= 0:
        quantity = _finite_number(marketability.get("order_quantity", marketability.get("quantity")))
    from etf_cockpit.analysis.sparebank import load_sparebank_scorecard_policy
    from etf_cockpit.analysis.sparebank.valuation import days_to_trade

    policy = load_sparebank_scorecard_policy()
    policy_marketability = policy.scorecard.get("marketability", {})
    participation = _finite_number(policy_marketability.get("participation_rate")) if isinstance(policy_marketability, Mapping) else None
    days = None
    if quantity is not None and quantity > 0 and volume is not None and volume > 0 and participation is not None:
        calculated = days_to_trade(quantity, volume, participation)
        days = _finite_number(calculated)
    marketability.update(order_quantity=quantity, participation_rate=participation)
    if days is not None:
        marketability["days_to_trade"] = days
    if volume is not None:
        marketability["median_volume_60d"] = volume
    if report_name is not None:
        marketability["candidate_report"] = report_name
    if not price_rows.empty:
        marketability["market_data_as_of"] = price_rows["_price_date"].max().date().isoformat()
    result["marketability"] = marketability
    return result


def _candidate_report_as_of(
    root: Path, instrument_id: str, decision: object
) -> tuple[Mapping[str, object] | None, str | None]:
    reports = root / "data" / "reports"
    if not reports.is_dir():
        return None, None
    cutoff = pd.Timestamp(decision)
    selected: tuple[pd.Timestamp, Mapping[str, object], str] | None = None
    for path in reports.glob("yfinance_trade_candidate_analysis_*"):
        suffix = path.stem.removeprefix("yfinance_trade_candidate_analysis_")
        generated = pd.to_datetime(suffix, format="%Y%m%dT%H%M%SZ", errors="coerce", utc=True)
        if pd.isna(generated) or generated > cutoff:
            continue
        try:
            if path.suffix.casefold() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
                rows = payload if isinstance(payload, list) else payload.get("candidates", payload.get("rows", ())) if isinstance(payload, Mapping) else ()
            elif path.suffix.casefold() == ".csv":
                rows = pd.read_csv(path).to_dict("records")
            else:
                continue
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(rows, (tuple, list)):
            continue
        for row in rows:
            if not isinstance(row, Mapping) or str(row.get("instrument_id") or "") != str(instrument_id):
                continue
            latest = pd.to_datetime(row.get("latest_date"), errors="coerce", utc=True)
            if pd.isna(latest) or latest.normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1) > cutoff:
                continue
            candidate = (generated, dict(row), path.name)
            if selected is None or candidate[0] > selected[0]:
                selected = candidate
    if selected is None:
        return None, None
    return selected[1], selected[2]


def _market_prices_as_of(
    prices: pd.DataFrame | None, instrument_id: str, decision: object
) -> pd.DataFrame:
    if prices is None or prices.empty:
        return pd.DataFrame()
    instrument_column = "instrument_id" if "instrument_id" in prices.columns else "etf_id" if "etf_id" in prices.columns else None
    if instrument_column is None or not {"date", "volume"}.issubset(prices.columns):
        return pd.DataFrame()
    eligible = prices.loc[prices[instrument_column].astype(str).eq(str(instrument_id))].copy()
    if eligible.empty:
        return eligible
    eligible["_price_date"] = pd.to_datetime(eligible["date"], errors="coerce", utc=True)
    available_at = eligible["_price_date"].where(
        eligible["_price_date"].ne(eligible["_price_date"].dt.normalize()),
        eligible["_price_date"].dt.normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59),
    )
    if "known_at" in eligible.columns:
        known_at = pd.to_datetime(eligible["known_at"], errors="coerce", utc=True)
        available_at = pd.concat([available_at, known_at], axis=1).max(axis=1, skipna=False)
    cutoff = pd.Timestamp(decision)
    eligible = eligible.loc[
        eligible["_price_date"].notna()
        & available_at.notna()
        & eligible["_price_date"].le(cutoff)
        & available_at.le(cutoff)
    ]
    return eligible.sort_values("_price_date", kind="stable")


def _finite_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _valuation_currency(
    assumptions: Mapping[str, object] | None,
    context: object,
    facts: object,
) -> str:
    """Resolve the listed price currency from explicit or filing evidence."""

    for value in (
        (assumptions or {}).get("currency"),
        (assumptions or {}).get("output_currency"),
        _record_value(context, "share_class_currency"),
        _record_value(context, "trading_currency"),
        _record_value(context, "reporting_currency"),
    ):
        currency = _currency_code(value)
        if currency:
            return currency
    if not isinstance(facts, Mapping):
        return ""
    currencies = {
        currency
        for name in ("owner_attributable_book", "ec_capital", "overkursfond", "utjevningsfond")
        if isinstance(facts.get(name), Mapping)
        and (currency := _currency_code(facts[name].get("unit")))
    }
    return next(iter(currencies)) if len(currencies) == 1 else ""


def _record_value(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _currency_code(value: object) -> str:
    currency = str(value or "").strip().upper()
    return currency if len(currency) == 3 and currency.isalpha() else ""
