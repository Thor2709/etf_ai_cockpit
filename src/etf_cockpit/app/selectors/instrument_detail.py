from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from etf_cockpit.application.ui_facade import (
    BENCHMARK_ATTRIBUTION_PATH,
    CORRELATION_CLUSTERS_PATH,
    FEATURE_DRIVERS_PATH,
    EVENT_CLEAN_PATH,
    FUNDAMENTAL_CLEAN_PATH,
    FUND_HOLDINGS_PATH,
    ETF_METADATA_CLEAN_PATH,
    MANUAL_NEWS_CLEAN_PATH,
    NEWS_CLEAN_PATH,
    assess_fundamental_row,
    build_market_clock_diagnostics,
    calculate_etf_economics,
    build_direct_overlap_view,
    build_document_inventory,
    compare_runs,
    direct_overlap_payload,
    latest_fundamental_rows,
    load_fundamental_evidence,
    load_news_items,
    load_calendar_events,
    events_available_as_of,
    normalise_event_decision_time,
    load_classification_projection,
    load_identity_projection,
    load_fixed_income_terms_projection,
    load_fixed_income_risk_projection,
    load_fixed_income_market_data_projection,
    load_fixed_income_analytics_projection,
    load_etf_structure_projection,
    load_local_structural_evidence,
    load_manual_news,
    load_simple_scoreboard,
    load_statement_evidence,
    load_paper_trade_rows,
    read_document_registry,
    read_etf_report_records,
    read_index_methodology_records,
    read_priips_kid_records,
    score_history_frame,
    sort_news_items,
)
from etf_cockpit.core.paths import DERIVED_DIR
from etf_cockpit.core.paths import ETF_QUOTES_PATH
from etf_cockpit.features.etf_economics import calculate_etf_liquidity
from etf_cockpit.services import CockpitSnapshot
from etf_cockpit.application.ui_facade import SimpleInstrumentScore
from etf_cockpit.application.ui_facade import load_peer_cohort_projection
from etf_cockpit.application.ui_facade import load_financial_institution_projection
from etf_cockpit.application.ui_facade import load_real_asset_projection
from etf_cockpit.application.ui_facade import load_cyclical_projection
from etf_cockpit.application.ui_facade import load_innovation_projection
from etf_cockpit.audit.thesis_diary import (
    ThesisDiaryIntegrityError,
    ThesisDiaryStore,
    disclosure_safe_entry,
    disclosure_safe_outcome,
    disclosure_safe_review,
)
from etf_cockpit.core.paths import DATA_DIR


@dataclass(frozen=True)
class InstrumentDetailViewModel:
    instrument_id: str
    display_name: str
    status: str
    identity: dict[str, Any]
    sections: dict[str, Any]


_SECTION_NAMES = (
    "identity",
    "price",
    "market_clock",
    "fixed_income_terms",
    "fixed_income_market_data",
    "fixed_income_analytics",
    "fixed_income_risk",
    "peer_cohort",
    "financial_institutions",
    "real_assets",
    "cyclicals",
    "innovation",
    "etf_liquidity",
    "etf_economics",
    "scores",
    "feature_drivers",
    "risk",
    "attribution",
    "fundamentals",
    "etf_disclosures",
    "etf_structure",
    "etf_holdings",
    "etf_overlap",
    "news",
    "events",
    "forecasts",
    "backtests",
    "paper_trades",
    "history",
    "journal",
    "thesis_diary",
    "run_changes",
)
SCOREBOARD_PATH = DERIVED_DIR / "scoreboard.parquet"
PAPER_TRADES_PATH = DERIVED_DIR / "paper_trades.parquet"
_KNOWN_FRESHNESS_STATES = frozenset({"ok", "fresh", "warning", "stale", "stale_block", "missing", "missing_or_pending", "unknown", "not_checked", "unavailable"})
_KNOWN_BACKTEST_QUALITIES = frozenset({"low", "medium", "high", "not_evaluated", "not_backtested_candidate", "unverified_backtest", "usable_low_authority", "weak_or_low_quality", "model_claim_unverified", "stale_universe", "unavailable"})
_KNOWN_FUNDAMENTAL_ELIGIBILITY = frozenset({"eligible", "eligible_negative_evidence", "not_score_eligible"})


def _unavailable(message: str) -> dict[str, Any]:
    """Return a consistent, non-authoritative unavailable panel."""

    return {"status": "unavailable", "message": message, "execution_allowed": False}


def _safe_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_datetime_scalar(value: object) -> pd.Timestamp | None:
    """Parse only scalar date evidence; containers are malformed."""

    if not pd.api.types.is_scalar(value) or _is_missing_scalar(value):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True, format="mixed")
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(parsed, pd.Timestamp) and not pd.isna(parsed):
        return parsed
    return None


def _safe_frame(frame: object) -> pd.DataFrame:
    return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _is_missing_scalar(value: object) -> bool:
    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    try:
        return bool(missing) if not hasattr(missing, "__len__") else False
    except (TypeError, ValueError):
        return False


def _value_or(value: object, fallback: object = "unavailable") -> object:
    if _is_missing_scalar(value):
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
    return value


def _safe_text(value: object) -> str | None:
    """Return non-empty textual evidence without stringifying containers."""

    if _is_missing_scalar(value) or not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _safe_known_text(value: object, allowed: frozenset[str]) -> str | None:
    text = _safe_text(value)
    if text is None:
        return None
    normalised = text.casefold()
    return normalised if normalised in allowed else None


def _safe_scalar_bool(value: object) -> tuple[bool, bool]:
    """Return a boolean plus validity without coercing containers."""

    if _is_missing_scalar(value):
        return False, False
    try:
        if pd.api.types.is_bool(value):
            return bool(value), True
    except (TypeError, ValueError):
        return False, False
    if isinstance(value, str):
        normalised = value.strip().casefold()
        if normalised in {"1", "true", "yes", "y", "on"}:
            return True, True
        if normalised in {"0", "false", "no", "n", "off"}:
            return False, True
    return False, False


def _safe_backtest_quality(value: object) -> str | None:
    text = _safe_text(value)
    if text is None:
        return None
    normalised = text.casefold()
    if normalised in _KNOWN_BACKTEST_QUALITIES:
        return normalised
    if normalised.startswith(("low trust:", "medium trust:", "backtest trust pending:", "candidate not backtested:")):
        return text
    return None


def _first_value(row: Mapping[str, Any], columns: tuple[str, ...], fallback: object = "unavailable") -> object:
    for column in columns:
        value = row.get(column)
        if not _is_missing_scalar(value) and (not isinstance(value, str) or value.strip()):
            return value
    return fallback


def _provenance_fields(row: Any) -> dict[str, Any]:
    """Carry canonical provenance fields through a panel without fabricating values."""

    getter = getattr(row, "get", None)
    if not callable(getter):
        return {"source_id": "unavailable", "source_authority": "unavailable", "conflict_id": "unavailable"}
    return {
        "source_id": _value_or(getter("source_id"), "unavailable"),
        "source_authority": _value_or(getter("source_authority", getter("authority")), "unavailable"),
        "conflict_id": _value_or(getter("conflict_id", getter("conflict_status")), "unavailable"),
    }


def _normalise_identifier(value: object) -> str | None:
    value = _value_or(value, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


_CANONICAL_ID_COLUMNS = ("instrument_id", "etf_id", "display_id")


def _scope_identifier_rows(frame: pd.DataFrame, instrument_id: str) -> tuple[pd.DataFrame, bool]:
    """Scope canonical IDs and reject rows that carry contradictory identity."""

    if bool(frame.columns.duplicated().any()):
        return frame.iloc[0:0].copy(), True
    columns = [column for column in _CANONICAL_ID_COLUMNS if column in frame.columns]
    if not columns:
        return frame.iloc[0:0].copy(), True
    target = str(instrument_id).strip()
    identifiers = pd.DataFrame(
        {column: frame[column].map(_normalise_identifier) for column in columns},
        index=frame.index,
    )
    populated = identifiers.notna().any(axis=1)
    matches = identifiers.eq(target).any(axis=1)
    contradictory = identifiers.apply(
        lambda row: any(not _is_missing_scalar(value) and value != target for value in row),
        axis=1,
    ) & matches
    malformed = ~populated
    if bool((contradictory | malformed).any()):
        return frame.iloc[0:0].copy(), True
    return frame.loc[matches & ~contradictory].copy(), False


def _safe_bool(value: object, default: bool = False) -> bool:
    if _is_missing_scalar(value):
        return default
    try:
        if pd.api.types.is_bool(value):
            return bool(value)
    except (TypeError, ValueError):
        return default
    if isinstance(value, str):
        normalised = value.strip().casefold()
        if normalised in {"1", "true", "yes", "y", "on"}:
            return True
        if normalised in {"0", "false", "no", "n", "off"}:
            return False
        return default
    return default


def _safe_sequence(value: object) -> tuple[object, ...]:
    """Return an iterable value without evaluating nullable scalars as booleans."""

    if _is_missing_scalar(value):
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ()


def _load_parquet(path: object) -> pd.DataFrame:
    candidate = path
    if candidate is None:
        return pd.DataFrame()
    candidates = [candidate]
    try:
        candidates.append(candidate.with_suffix(".csv"))  # type: ignore[union-attr]
    except (AttributeError, TypeError, ValueError):
        pass
    for source in candidates:
        try:
            if not source.exists():  # type: ignore[union-attr]
                continue
            frame = pd.read_parquet(source) if source.suffix.lower() == ".parquet" else pd.read_csv(source)  # type: ignore[union-attr]
            if frame.empty and source.suffix.lower() == ".parquet":
                continue
            return frame
        except Exception:
            continue
    return pd.DataFrame()


def _instrument_rows(frame: object, instrument_id: str, *, columns: tuple[str, ...] = _CANONICAL_ID_COLUMNS) -> pd.DataFrame:
    """Return rows whose populated supported IDs all resolve to ``instrument_id``.

    A row is eligible when at least one supported identifier matches and no
    populated supported identifier disagrees.  Rows containing only another
    instrument's identifiers, or no usable identifier, are ignored.
    """

    source = _safe_frame(frame)
    if source.empty:
        return source
    if bool(source.columns.duplicated().any()):
        return source.iloc[0:0].copy()
    available = [column for column in columns if column in source.columns]
    if not available:
        return source.iloc[0:0].copy()
    target = _normalise_identifier(instrument_id)
    if target is None:
        return source.iloc[0:0].copy()
    identifiers = pd.DataFrame(
        {column: source[column].map(_normalise_identifier) for column in available},
        index=source.index,
    )
    matches = identifiers.eq(target).any(axis=1)
    contradictory = identifiers.apply(
        lambda row: any(not _is_missing_scalar(value) and value != target for value in row),
        axis=1,
    )
    return source.loc[matches & ~contradictory].copy()


def _feature_driver_panel(instrument_id: str) -> dict[str, Any]:
    try:
        frame = pd.read_parquet(FEATURE_DRIVERS_PATH) if FEATURE_DRIVERS_PATH.exists() else pd.DataFrame()
    except Exception:
        frame = pd.DataFrame()
    frame = _normalise_feature_driver_frame(frame)
    if frame.empty or "instrument_id" not in frame.columns:
        return {"status": "unavailable", "rows": [], "message": "Feature drivers unavailable; no local component history is registered.", "execution_allowed": False}
    scoped = _instrument_rows(frame, instrument_id)
    if scoped.empty:
        return {"status": "unavailable", "rows": [], "message": "Feature drivers unavailable for this instrument.", "execution_allowed": False}
    scoped["_score_sort"] = pd.to_numeric(scoped.get("normalised_score"), errors="coerce")
    rows = scoped.drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    positive = scoped.loc[scoped["direction"].astype(str).eq("positive")].sort_values(["_score_sort", "component"], ascending=[False, True], kind="stable").drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    negative = scoped.loc[scoped["direction"].astype(str).eq("negative")].sort_values(["_score_sort", "component"], ascending=[True, True], kind="stable").drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    missing = scoped.loc[scoped["direction"].astype(str).eq("missing")].sort_values(["component"], kind="stable").drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    low_authority = scoped.loc[scoped["flags"].astype(str).str.contains("low_authority", na=False)].sort_values(["component"], kind="stable").drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    stale_or_partial = scoped.loc[scoped["flags"].astype(str).str.contains("stale|partial", na=False, regex=True)].sort_values(["component"], kind="stable").drop(columns=["_score_sort"], errors="ignore").to_dict(orient="records")
    return {
        "status": "available",
        "rows": rows,
        "top_positive": positive[:3],
        "top_negative": negative[:3],
        "missing_or_na": missing,
        "low_authority": low_authority,
        "stale_or_partial": stale_or_partial,
        "execution_allowed": False,
        **_provenance_fields(scoped.iloc[-1]),
    }


def _normalise_feature_driver_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Add modern feature-driver columns when reading a legacy local store."""

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    if "instrument_id" not in result.columns and "instrument" in result.columns:
        result["instrument_id"] = result["instrument"]
    if "instrument" not in result.columns and "instrument_id" in result.columns:
        result["instrument"] = result["instrument_id"]
    if "normalised_score" not in result.columns:
        result["normalised_score"] = result.get("normalised_score_10")
    if "raw_metric" not in result.columns:
        result["raw_metric"] = result.get("raw_metric_value")
    for column, default in (
        ("component", "unknown"),
        ("source_id", "unavailable"),
        ("authority", "unknown"),
        ("driver_text", "Feature driver unavailable; informational only."),
        ("source_dataset", "unavailable"),
        ("as_of_date", "unavailable"),
        ("freshness_status", "unknown"),
        ("classification", "unclassified"),
        ("authority_classification", "unknown"),
        ("freshness_classification", "unknown"),
        ("flags", "none"),
        ("execution_allowed", False),
    ):
        if column not in result.columns:
            result[column] = default
    if "direction" not in result.columns:
        score = pd.to_numeric(result["normalised_score"], errors="coerce")
        result["direction"] = score.map(lambda value: "missing" if pd.isna(value) else "positive" if value >= 6 else "negative" if value <= 4 else "mixed")
    result["flags"] = result["flags"].fillna("none").astype(str)
    derived_flags = result["flags"].eq("none")
    result.loc[derived_flags & result["direction"].astype(str).eq("missing"), "flags"] = "missing"
    result.loc[derived_flags & result["authority_classification"].astype(str).str.contains("low", case=False, na=False), "flags"] = "low_authority"
    result.loc[derived_flags & result["freshness_classification"].astype(str).str.contains("stale|partial", case=False, na=False, regex=True), "flags"] = "stale"
    return result


def _fundamentals_panel(instrument_id: str, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    try:
        statement_evidence = load_statement_evidence(instrument_id=instrument_id)
    except Exception:
        statement_evidence = {
            "status": "unavailable",
            "message": "Canonical statement evidence unavailable; the local statement store is malformed.",
            "statement_history": [],
            "execution_allowed": False,
        }
    try:
        source = frame if isinstance(frame, pd.DataFrame) else load_fundamental_evidence(FUNDAMENTAL_CLEAN_PATH)
    except Exception:
        return _unavailable("Fundamental evidence unavailable; the optional local store is missing or corrupt.") | {"score_eligible": False, **_statement_panel_fields(statement_evidence)}
    if source.empty or "instrument_id" not in source.columns:
        return _unavailable("Fundamental evidence unavailable; no complete local five-section record is registered.") | {"score_eligible": False, **_statement_panel_fields(statement_evidence)}
    try:
        scoped = latest_fundamental_rows(_instrument_rows(source, instrument_id))
    except Exception:
        return _unavailable("Fundamental evidence unavailable; the optional local store is malformed.") | {"score_eligible": False, **_statement_panel_fields(statement_evidence)}
    if scoped.empty:
        return _unavailable("Fundamental evidence unavailable for this instrument.") | {"score_eligible": False, **_statement_panel_fields(statement_evidence)}
    row = scoped.iloc[-1]
    eligibility = _safe_known_text(row.get("eligibility"), _KNOWN_FUNDAMENTAL_ELIGIBILITY)
    score_eligible, score_eligible_valid = _safe_scalar_bool(row.get("score_eligible"))
    manual_review = _safe_bool(row.get("manual_review"), default=True) if "manual_review" in row.index else False
    assessment = assess_fundamental_row(row)
    values = dict(assessment.values)
    warnings = _safe_text(row.get("warnings")) or ""
    stale_fields = _safe_text(row.get("stale_fields")) or ""
    temporal_warning = any(
        token in {"ambiguous_as_of", "future_as_of", "stale_fundamentals"}
        for token in warnings.split("|")
    )
    section_metadata = dict(assessment.sections)
    metadata_valid = eligibility is not None and score_eligible_valid and assessment.score_eligible
    if manual_review or not metadata_valid or temporal_warning:
        manual_review = True
        score_eligible = False
    return {
        "status": "available" if score_eligible and eligibility in {"eligible", "eligible_negative_evidence"} and not manual_review else "manual_review",
        "eligibility": eligibility or "unavailable",
        "score_eligible": score_eligible,
        "manual_review": manual_review,
        "source": row.get("source", row.get("source_authority", "unavailable")),
        "source_id": row.get("source_id", "unavailable"),
        "source_authority": row.get("source_authority", "unavailable"),
        "conflict_id": row.get("conflict_id", "unavailable"),
        "as_of": row.get("as_of_date", "unavailable"),
        "freshness_status": assessment.freshness_status,
        "freshness_days": assessment.freshness_days,
        "review_reasons": assessment.reasons,
        "values": values,
        "section_metadata": section_metadata,
        "missing_fields": str(row.get("missing_fields", "")),
        "warnings": warnings,
        "stale_fields": stale_fields,
        "limitations": str(row.get("limitations", "unavailable")),
        "sector_relative_status": row.get("sector_relative_status", "unavailable"),
        "sector_relative_value": row.get("sector_relative_value", "unavailable"),
        "sector_relative_peer": row.get("sector_relative_peer", "unavailable"),
        "sector_relative_benchmark": row.get("sector_relative_benchmark", "unavailable"),
        "sector_relative_delta": row.get("sector_relative_delta", "unavailable"),
        "sector_relative_limitation": row.get("sector_relative_limitation", "No sector-relative comparison evidence supplied."),
        "executable_authority": False,
        "execution_allowed": False,
        **_statement_panel_fields(statement_evidence),
    }


def _statement_panel_fields(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        "statement_history": evidence.get("statement_history", []),
        "statement_coverage": evidence.get("coverage", {"status": "unavailable"}),
        "statement_reconciliation": evidence.get("reconciliation", {"status": "unavailable"}),
        "statement_status": evidence.get("status", "unavailable"),
    }


def _news_panel(instrument_id: str, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    source_error: str | None = None
    try:
        source = frame if isinstance(frame, pd.DataFrame) else load_news_items(NEWS_CLEAN_PATH)
    except Exception:
        source = pd.DataFrame()
        source_error = "News unavailable; the optional local store is missing or corrupt."
    items: list[dict[str, Any]] = []
    if not source.empty and "instrument_id" in source.columns:
        try:
            scoped = sort_news_items(_instrument_rows(source, instrument_id))
            items.extend(_news_item_record(row) for row in scoped.tail(20).to_dict("records"))
        except Exception:
            source_error = "News unavailable; the optional local store is malformed."
    manual_error: str | None = None
    try:
        manual = load_manual_news(MANUAL_NEWS_CLEAN_PATH)
        if not manual.empty and "etf_id" in manual.columns:
            manual_scoped = manual.loc[manual["etf_id"].astype(str).eq(str(instrument_id))]
            manual_scoped = manual_scoped.sort_values("as_of_date", kind="stable").tail(20)
            items.extend(_manual_news_item_record(row) for row in manual_scoped.to_dict("records"))
    except Exception as exc:
        manual_error = type(exc).__name__
    if manual_error is not None:
        items.append(_manual_news_unavailable_record(manual_error))
    if not items:
        return _unavailable(source_error or ("News unavailable; no timestamp-validated local items are registered." if source.empty else "News unavailable for this instrument.")) | {"items": [], "context_only": True, "executable_authority": False}
    return {"status": "available", "message": "News is context-only and cannot change deterministic scores.", "items": items, "context_only": True, "executable_authority": False, "execution_allowed": False}


def _event_calendar_panel(
    instrument_id: str,
    frame: pd.DataFrame | None = None,
    *,
    decision_time: object = None,
) -> dict[str, Any]:
    """Return upcoming event evidence without allowing it into score paths."""

    cutoff = normalise_event_decision_time(decision_time)
    decision_label = cutoff.isoformat() if cutoff is not None else "unavailable"
    panel_metadata = {
        "decision_time": decision_label,
        "decision_time_available": cutoff is not None,
        "available_at_decision_time": cutoff is not None,
        "context_only": True,
        "executable_authority": False,
        "execution_allowed": False,
    }

    def unavailable(message: str) -> dict[str, Any]:
        return _unavailable(message) | {"events": [], **panel_metadata}

    if cutoff is None:
        return unavailable("Event calendar unavailable; snapshot decision time is unavailable, so event availability is not asserted.")

    try:
        source = frame if isinstance(frame, pd.DataFrame) else load_calendar_events(EVENT_CLEAN_PATH)
    except Exception:
        return unavailable("Event calendar unavailable; the optional local store is missing or corrupt.")
    if source.empty or "instrument_id" not in source.columns:
        return unavailable("Event calendar unavailable; no local earnings, dividend or action records are registered.")
    try:
        scoped = events_available_as_of(source, cutoff, instrument_id)
    except Exception:
        return unavailable("Event calendar unavailable; the local store is malformed.")
    if scoped.empty:
        return unavailable("Event calendar unavailable; no records were available for this instrument at the snapshot decision time.")
    events = []
    for row in scoped.to_dict("records")[:30]:
        item = dict(row)
        item.update(
            {
                "available_at_decision_time": True,
                "decision_time": decision_label,
                "context_only": True,
                "execution_allowed": False,
                "executable_authority": False,
            }
        )
        events.append(item)
    return {"status": "available", "message": "Events are context-only risk evidence and cannot change deterministic scores or actions.", "events": events, **panel_metadata}
def _news_item_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise every row to the provenance fields rendered by Instrument Detail."""

    item = dict(row)
    item.update(
        {
            "source_url": _first_value(item, ("source_url", "url")),
            "published_at": _value_or(item.get("published_at"), "unavailable"),
            "ingested_at": _value_or(item.get("ingested_at"), "unavailable"),
            "provider_name": _first_value(item, ("provider_name", "provider")),
            "credibility": _value_or(item.get("credibility"), "unverified"),
            "instrument_mapping_method": _value_or(item.get("instrument_mapping_method"), "unavailable"),
            "available_at_decision_time": _safe_bool(item.get("available_at_decision_time"), default=False),
            "timestamp_status": _first_value(item, ("timestamp_status", "timestamp_confidence")),
            "context_only": True,
            "executable_authority": False,
        }
    )
    return item


def _manual_news_item_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt a local manual note to the existing context-only news renderer."""

    item = dict(row)
    item.update(
        {
            "headline": _value_or(item.get("title"), "Untitled manual note"),
            "source_url": _value_or(item.get("source_url"), "unavailable"),
            "published_at": _value_or(item.get("as_of_date"), "unavailable"),
            "ingested_at": _value_or(item.get("imported_at"), "unavailable"),
            "provider_name": _value_or(item.get("source"), "manual_import"),
            "credibility": _value_or(item.get("source_credibility"), "unverified"),
            "instrument_mapping_method": "manual_note_etf_id",
            "available_at_decision_time": False,
            "timestamp_status": "dated_only",
            "manual_note": True,
            "context_only": True,
            "executable_authority": False,
        }
    )
    return item


def _manual_news_unavailable_record(error_name: str) -> dict[str, Any]:
    return {
        "headline": "Manual note credibility evidence unavailable; manual review required",
        "source_url": "unavailable",
        "published_at": "unavailable",
        "ingested_at": "unavailable",
        "provider_name": "manual_import",
        "credibility": "unavailable",
        "credibility_flag_status": "unavailable",
        "credibility_flags": "unknown",
        "credibility_reason_codes": f"read_error:{error_name}",
        "instrument_mapping_method": "manual_note_etf_id",
        "available_at_decision_time": False,
        "timestamp_status": "unavailable",
        "manual_note": True,
        "context_only": True,
        "executable_authority": False,
    }


def _etf_disclosure_panel(
    instrument_id: str,
    *,
    document_registry: pd.DataFrame | None = None,
    holdings: pd.DataFrame | None = None,
    kid_records: pd.DataFrame | None = None,
    methodology_records: pd.DataFrame | None = None,
) -> dict[str, Any]:
    try:
        registry = document_registry.copy() if isinstance(document_registry, pd.DataFrame) else read_document_registry()
    except Exception:
        registry = pd.DataFrame()
    registry_manual_review = False
    registry_message = ""
    registry_had_rows = not registry.empty
    if not registry.empty:
        registry, registry_manual_review = _scope_identifier_rows(registry, instrument_id)
        if registry_manual_review:
            registry_manual_review = True
            registry_message = "ETF disclosure registry has missing or contradictory canonical IDs; manual review is required."
            inventory = pd.DataFrame()
    if not registry_manual_review and registry.empty and not registry_had_rows:
        try:
            inventory = build_document_inventory([instrument_id])
        except Exception:
            inventory = pd.DataFrame()
    elif not registry_manual_review and registry.empty:
        inventory = pd.DataFrame()
    elif not registry_manual_review:
        inventory = registry
    document_rows = []
    for row in inventory.to_dict("records"):
        document_rows.append(
            {
                "document_type": str(_value_or(row.get("document_type"), "")),
                "coverage_status": str(_value_or(row.get("coverage_status"))),
                "document_date": _first_value(row, ("document_date",)),
                "source": _first_value(row, ("source_url", "authority")),
                "checksum": _first_value(row, ("checksum", "sha256")),
                "source_id": _first_value(row, ("source_id",)),
            }
        )

    if holdings is None:
        holdings = _load_parquet(FUND_HOLDINGS_PATH)
    holdings_frame = holdings.copy() if isinstance(holdings, pd.DataFrame) else pd.DataFrame()
    holdings_manual_review = False
    holdings_message = ""
    if not holdings_frame.empty:
        holdings_frame, holdings_manual_review = _scope_identifier_rows(holdings_frame, instrument_id)
        if holdings_manual_review:
            holdings_manual_review = True
            holdings_message = "ETF holdings have missing or contradictory canonical IDs; manual review is required."
            holdings_frame = pd.DataFrame()
    if holdings_frame.empty:
        holdings_summary: dict[str, Any] = {
            "status": "manual_review" if holdings_manual_review else "unavailable",
            "message": holdings_message or "No normalised holdings are available.",
            "manual_review": holdings_manual_review,
            "as_of": "unavailable",
            "completeness": "unavailable",
            "freshness": "unavailable",
            "confidence": "unavailable",
            "source": "unavailable",
            "authority": "unavailable",
            "score_eligible": False,
            "rows": [],
        }
    else:
        as_of_values = holdings_frame.apply(
            lambda row: _first_value(row, ("as_of", "as_of_date"), None),
            axis=1,
        )
        parsed_dates = pd.to_datetime(as_of_values, errors="coerce", utc=True, format="mixed")
        if bool(parsed_dates.isna().any()):
            holdings_summary = {
                "status": "manual_review",
                "message": "ETF holdings have missing or malformed as_of metadata; manual review is required.",
                "manual_review": True,
                "as_of": "unavailable",
                "completeness": "unavailable",
                "freshness": "unavailable",
                "confidence": "unavailable",
                "source": "unavailable",
                "authority": "unavailable",
                "score_eligible": False,
                "rows": [],
            }
            holdings_manual_review = True
        else:
            holdings_frame = holdings_frame.assign(_as_of_sort=parsed_dates).sort_values("_as_of_sort", kind="stable").drop(columns=["_as_of_sort"])
            row = holdings_frame.iloc[-1]
            confidence = _safe_float(row.get("confidence"))
            holdings_summary = {
                "status": "available",
                "as_of": _first_value(row, ("as_of", "as_of_date")),
                "completeness": _value_or(row.get("completeness")),
                "freshness": _value_or(row.get("freshness")),
                "confidence": confidence if confidence is not None else "unavailable",
                "source": _value_or(row.get("source")),
                "authority": _value_or(row.get("authority")),
                "score_eligible": _safe_bool(row.get("score_eligible")),
                "manual_review": False,
                "rows": holdings_frame.where(pd.notna(holdings_frame), None).to_dict("records"),
                **_provenance_fields(row),
            }
    try:
        kid_frame = kid_records.copy() if isinstance(kid_records, pd.DataFrame) else read_priips_kid_records()
    except Exception:
        kid_frame = pd.DataFrame()
    try:
        methodology_frame = methodology_records.copy() if isinstance(methodology_records, pd.DataFrame) else read_index_methodology_records()
    except Exception:
        methodology_frame = pd.DataFrame()
    kid = _parsed_kid_panel(kid_frame, instrument_id)
    methodology = _parsed_methodology_panel(methodology_frame, instrument_id)
    has_registered_document = any(row["coverage_status"] in {"available", "imported", "mapped"} for row in document_rows)
    return {
        "status": "manual_review" if registry_manual_review or holdings_manual_review else "available" if has_registered_document or kid["status"] == "available" or methodology["status"] == "available" else "unavailable",
        "message": registry_message or holdings_message or "ETF disclosure evidence is shown from canonical instrument-linked local records.",
        "manual_review": registry_manual_review or holdings_manual_review,
        "document_inventory": document_rows,
        "holdings": holdings_summary,
        "exposure": {
            "status": holdings_summary.get("status", "unavailable"),
            "rows": holdings_summary.get("rows", []),
            "message": holdings_summary.get("message", "ETF holdings/exposure unavailable."),
        },
        "kid": kid,
        "methodology": methodology,
        "execution_allowed": False,
    }


def _parsed_kid_panel(frame: pd.DataFrame, instrument_id: str) -> dict[str, Any]:
    return _parsed_panel(frame, instrument_id, "kid", ("product", "isin", "manufacturer", "sri", "cost_fields", "holding_period_years", "scenarios", "document_date", "extraction_confidence"))


def _parsed_methodology_panel(frame: pd.DataFrame, instrument_id: str) -> dict[str, Any]:
    return _parsed_panel(frame, instrument_id, "methodology", ("provider", "index_series", "version", "document_date", "eligibility_rules", "weighting_rules", "review_frequency", "caps", "confidence"))


def _parsed_panel(frame: pd.DataFrame, instrument_id: str, kind: str, fields: tuple[str, ...]) -> dict[str, Any]:
    if frame.empty or "instrument_id" not in frame.columns:
        return {"status": "unavailable", "manual_review": True, "score_eligible": False, "message": f"Parsed {kind} evidence unavailable; manual review required."}
    scoped = _instrument_rows(frame, instrument_id)
    if scoped.empty:
        return {"status": "unavailable", "manual_review": True, "score_eligible": False, "message": f"Parsed {kind} evidence unavailable; manual review required."}
    row = scoped.sort_values("imported_at", kind="stable").iloc[-1] if "imported_at" in scoped.columns else scoped.iloc[-1]
    payload: dict[str, Any] = {field: row.get(field) for field in fields}
    payload.update({field: row.get(field) for field in ("source_pages", "warnings") if field in row.index})
    for field in ("source_pages", "warnings", "cost_fields", "scenarios", "eligibility_rules", "weighting_rules", "caps"):
        value = payload.get(field)
        if isinstance(value, str):
            try:
                import json
                payload[field] = json.loads(value)
            except (TypeError, ValueError):
                payload[field] = [value] if field != "cost_fields" else {"raw": value}
    success = _safe_bool(row.get("success"), default=False)
    manual_review = _safe_bool(row.get("manual_review"), default=True)
    score_eligible = _safe_bool(row.get("score_eligible"), default=False)
    freshness_raw = row.get("freshness_status", "ok")
    freshness_text = _safe_known_text(freshness_raw, _KNOWN_FRESHNESS_STATES)
    freshness_valid = freshness_text is not None
    available = success and not manual_review and freshness_valid and freshness_text not in {"stale_block", "missing_or_pending", "unknown", "unavailable"}
    payload.update(
        {
            "status": "available" if available else "manual_review",
            "source_id": row.get("source_id", "unavailable"),
            "source_sha256": row.get("source_sha256", "unavailable"),
            "parser_version": row.get("parser_version", "unavailable"),
            "conflict_id": row.get("conflict_id", "unavailable"),
            "manual_review": manual_review or not available,
            "score_eligible": score_eligible if available else False,
            "source_authority": row.get("source_authority", "issuer_document"),
            "freshness_status": freshness_text or "unavailable",
        }
    )
    return payload


def build_etf_disclosure_panel(model: InstrumentDetailViewModel) -> dict[str, Any]:
    """Return the reusable ETF disclosure model shown on Instrument Detail."""
    value = model.sections.get("etf_disclosures")
    return value if isinstance(value, dict) else {"status": "unavailable", "document_inventory": [], "holdings": {"status": "unavailable"}, "kid": {"status": "unavailable"}, "methodology": {"status": "unavailable"}}


def build_etf_structure_panel(model: InstrumentDetailViewModel) -> dict[str, Any]:
    """Return the reusable structural/legal ETF panel model."""

    value = model.sections.get("etf_structure")
    return value if isinstance(value, dict) else {"status": "unavailable", "fields": {}, "documents": {}, "versions": [], "flags": ["structure_evidence_unavailable"], "execution_allowed": False}


def _etf_structure_panel(
    instrument_id: str,
    *,
    document_registry: pd.DataFrame | None = None,
    report_records: pd.DataFrame | None = None,
    supplemental_rows: object = None,
    holdings: pd.DataFrame | None = None,
    decision_time: object = None,
) -> dict[str, Any]:
    try:
        evidence = None
        if any(value is None for value in (document_registry, report_records, supplemental_rows, holdings)):
            evidence = load_local_structural_evidence(
                registry_reader=(lambda: document_registry) if document_registry is not None else read_document_registry,
                report_reader=(lambda: report_records) if report_records is not None else read_etf_report_records,
                factsheet_path=ETF_METADATA_CLEAN_PATH,
                holdings_path=FUND_HOLDINGS_PATH,
            )
        local_registry = document_registry if document_registry is not None else evidence.document_registry
        local_reports = report_records if report_records is not None else evidence.report_records
        local_factsheet_rows = supplemental_rows if supplemental_rows is not None else evidence.supplemental_rows
        local_holdings_rows = holdings if holdings is not None else evidence.holdings
        return load_etf_structure_projection(
            instrument_id,
            document_registry=local_registry,
            report_records=local_reports,
            supplemental_rows=local_factsheet_rows,
            holdings=local_holdings_rows,
            decision_time=decision_time,
        )
    except Exception:
        return {
            "contract": "etf-structure-documents.v1",
            "instrument_id": str(instrument_id),
            "status": "unavailable",
            "fields": {},
            "documents": {family: {"status": "unknown", "execution_allowed": False} for family in ("factsheet", "prospectus", "holdings")},
            "versions": [],
            "flags": ["structure_evidence_invalid"],
            "evidence_confidence_cap": 0.0,
            "execution_allowed": False,
        }


def _friction_panel(instrument_id: str, *, candidate_score: SimpleInstrumentScore | None = None) -> dict[str, Any]:
    fields = (
        "gross_expected_edge_bps",
        "estimated_total_cost_bps",
        "net_expected_edge_bps",
        "edge_to_cost_ratio",
        "gross_expected_return",
        "q10_expected_return",
        "q50_expected_return",
        "q90_expected_return",
        "expected_return_horizon_days",
        "net_q10_expected_return",
        "net_expected_return",
        "net_q90_expected_return",
        "expected_return_order_value_eur",
        "expected_return_cost_bps",
        "expected_return_cost_eur",
        "expected_return_cost_ratio",
    )
    empty = {field: None for field in fields}
    empty.update(
        {
            "cost_stress_scenario": "unavailable",
            "friction_reason": "Friction-adjusted return unavailable.",
            "expected_return_distribution_version": "expected-return-distribution.v1",
            "expected_return_source_dataset": "forecast_return_distribution",
            "status": "unavailable",
            "execution_allowed": False,
        }
    )
    if candidate_score is not None and str(candidate_score.display_id).strip() == str(instrument_id).strip():
        row = pd.Series(
            {
                **{field: getattr(candidate_score, field, None) for field in fields},
                "cost_stress_scenario": candidate_score.cost_stress_scenario,
                "friction_reason": candidate_score.friction_reason,
                "expected_return_distribution_version": candidate_score.expected_return_distribution_version,
                "expected_return_source_dataset": candidate_score.expected_return_source_dataset,
                "source_id": candidate_score.instrument_key,
                "source_authority": "score_row",
            }
        )
    else:
        if not SCOREBOARD_PATH.exists():
            return empty
        frame = load_simple_scoreboard(SCOREBOARD_PATH)
        if frame.empty:
            return empty
        rows = _instrument_rows(frame, instrument_id, columns=("display_id", "instrument_id", "etf_id"))
        if rows.empty:
            return empty
        row = rows.iloc[-1]
    def _finite(value: object) -> float | None:
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    result = {field: _finite(row.get(field)) if field in row.index else None for field in fields}
    scenario_text = _safe_known_text(
        row.get("cost_stress_scenario"),
        frozenset({"low", "base", "high", "base_order_size"}),
    )
    scenario_valid = scenario_text is not None
    if not scenario_valid:
        scenario_text = "unavailable"
    legacy_complete = all(
        result[field] is not None
        for field in ("gross_expected_edge_bps", "estimated_total_cost_bps", "net_expected_edge_bps")
    )
    distribution_complete = all(
        result[field] is not None
        for field in (
            "q10_expected_return",
            "q50_expected_return",
            "q90_expected_return",
            "expected_return_horizon_days",
            "net_q10_expected_return",
            "net_expected_return",
            "net_q90_expected_return",
            "expected_return_order_value_eur",
            "expected_return_cost_bps",
            "expected_return_cost_eur",
        )
    )
    complete = legacy_complete or distribution_complete
    has_numeric = any(result[field] is not None for field in fields)
    result.update(
        {
            "cost_stress_scenario": scenario_text,
            "friction_reason": str(row.get("friction_reason") or "Friction-adjusted return unavailable."),
            "expected_return_distribution_version": str(
                row.get("expected_return_distribution_version") or "expected-return-distribution.v1"
            ),
            "expected_return_source_dataset": str(
                row.get("expected_return_source_dataset") or "forecast_return_distribution"
            ),
            "status": "available" if complete and scenario_valid else "manual_review" if has_numeric else "unavailable",
            "manual_review": has_numeric and not (complete and scenario_valid),
            "execution_allowed": False,
            **_provenance_fields(row),
        }
    )
    return result


def _price_panel(snapshot: CockpitSnapshot, instrument_id: str, *, candidate_score: SimpleInstrumentScore | None = None) -> dict[str, Any]:
    rows = _instrument_rows(getattr(snapshot, "prices", None), instrument_id)
    if rows.empty:
        if _candidate_score_matches(candidate_score, instrument_id):
            candidate_price = _safe_float(candidate_score.latest_price)  # type: ignore[union-attr]
            candidate_date = _safe_text(candidate_score.latest_date)  # type: ignore[union-attr]
            candidate_timestamp = _safe_datetime_scalar(candidate_date)
            if candidate_price is not None or candidate_timestamp is not None:
                return {
                    "status": "available" if candidate_price is not None and candidate_timestamp is not None else "manual_review",
                    "rows": 0,
                    "history": [],
                    "latest_price": candidate_price,
                    "latest_date": candidate_date if candidate_timestamp is not None else "unavailable",
                    "as_of": candidate_date if candidate_timestamp is not None else "unavailable",
                    "freshness": _candidate_freshness(candidate_score) if candidate_timestamp is not None else "unavailable",  # type: ignore[arg-type]
                    "source": "score_row",
                    "currency": "unavailable",
                    "execution_allowed": False,
                    "source_id": candidate_score.instrument_key,  # type: ignore[union-attr]
                    "source_authority": "score_row",
                    "conflict_id": "unavailable",
                }
        return _unavailable("Price history unavailable for this instrument.") | {"rows": [], "history": []}
    date_column = "date" if "date" in rows.columns else "as_of_date" if "as_of_date" in rows.columns else None
    if date_column is None:
        return _unavailable("Price history unavailable; no validated date column is present.") | {"rows": [], "history": [], "freshness": "unavailable"}
    rows["_date_sort"] = pd.to_datetime(rows[date_column], errors="coerce", utc=True, format="mixed")
    rows = rows.loc[rows["_date_sort"].notna()].sort_values("_date_sort", kind="stable")
    if rows.empty:
        return _unavailable("Price history unavailable; no valid dated observations are registered.") | {"rows": [], "history": [], "freshness": "unavailable"}
    rows = rows.drop(columns=["_date_sort"])
    latest = rows.iloc[-1]
    price = latest.get("adjusted_close")
    if _safe_float(price) is None:
        price = latest.get("close")
    latest_date = latest.get(date_column) if date_column else None
    latest_text = str(latest_date)
    freshness = "unknown"
    if latest_text != "unavailable":
        freshness = "fresh"
        try:
            reference = pd.to_datetime(getattr(getattr(snapshot, "data_report", None), "as_of_date", None), errors="coerce", utc=True, format="mixed")
            observed = pd.to_datetime(latest_date, errors="coerce", utc=True, format="mixed")
            if pd.notna(reference) and pd.notna(observed) and (reference - observed).days > 5:
                freshness = "stale"
        except Exception:
            freshness = "unknown"
    records = rows.tail(500).where(pd.notna(rows.tail(500)), None).to_dict("records")
    return {
        "status": "available",
        "rows": len(rows),
        "history": records,
        "latest_price": _safe_float(price),
        "latest_date": latest_text,
        "as_of": latest_text,
        "freshness": freshness,
        "source": latest.get("source", "unavailable"),
        "currency": latest.get("currency", "unavailable"),
        "execution_allowed": False,
        **_provenance_fields(latest),
    }


def _candidate_score_matches(candidate_score: SimpleInstrumentScore | None, instrument_id: str) -> bool:
    return candidate_score is not None and str(getattr(candidate_score, "display_id", "")).strip() == str(instrument_id).strip()


def _candidate_freshness(candidate_score: SimpleInstrumentScore) -> str:
    for component in candidate_score.components:
        status = _safe_known_text(getattr(component, "freshness_status", None), _KNOWN_FRESHNESS_STATES)
        if status is not None:
            return status
    return "unknown"


def _candidate_scoreboard(candidate_score: SimpleInstrumentScore) -> dict[str, Any]:
    canonical = candidate_score.canonical_score
    return {
        "display_id": candidate_score.display_id,
        "instrument_id": candidate_score.display_id,
        "evidence_score_10": candidate_score.evidence_score_10,
        "evidence_quality_10": candidate_score.evidence_quality_10,
        "final_label": candidate_score.final_label,
        "final_action": candidate_score.final_action,
        "one_line_reason": candidate_score.one_line_reason,
        "freshness_status": _candidate_freshness(candidate_score),
        "source_id": candidate_score.instrument_key,
        "source_authority": "score_row",
        "canonical_attractiveness_10": canonical.attractiveness_10 if canonical else None,
        "canonical_expected_return_10": canonical.expected_return_10 if canonical else None,
        "canonical_risk_implementation_10": canonical.risk_implementation_10 if canonical else None,
        "canonical_evidence_confidence_10": canonical.evidence_confidence_10 if canonical else None,
        "canonical_coverage": canonical.coverage if canonical else 0.0,
        "formula_version": canonical.formula_version if canonical else "unavailable",
        "formula_checksum": canonical.formula_checksum if canonical else "unavailable",
        "source_vintage_hash": canonical.source_vintage_hash if canonical else "unavailable",
    }


def _load_quote_evidence() -> pd.DataFrame:
    """Load optional local quote evidence without making provider calls."""

    candidates = (ETF_QUOTES_PATH.with_suffix(".parquet"), ETF_QUOTES_PATH)
    for path in candidates:
        try:
            if path.suffix.casefold() == ".parquet" and path.exists():
                return pd.read_parquet(path)
            if path.suffix.casefold() == ".csv" and path.exists():
                return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def build_etf_liquidity_panel(
    snapshot: CockpitSnapshot,
    instrument_id: str,
    *,
    order_value_eur: float = 10_000.0,
    horizon_days: int = 1,
    stress_multiplier: float = 1.0,
    quote_evidence: pd.DataFrame | Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Return the read-only ETF liquidity and capacity panel model."""

    quotes = _load_quote_evidence() if quote_evidence is None else quote_evidence
    report = calculate_etf_liquidity(
        snapshot.config,
        getattr(snapshot, "prices", pd.DataFrame()),
        instrument_id,
        order_value_eur=order_value_eur,
        horizon_days=horizon_days,
        quote_evidence=quotes,
        as_of=getattr(getattr(snapshot, "data_report", None), "as_of_date", None),
        stress_multiplier=stress_multiplier,
    )
    return report.as_dict()


def build_etf_economics_panel(
    snapshot: CockpitSnapshot,
    instrument_id: str,
    *,
    records: object = None,
    fund_total_return: object = None,
    benchmark_total_return: object = None,
    as_of: object = None,
    horizon_days: int = 252,
    benchmark_id: str | None = None,
    currency: str | None = None,
    closure_policy: object = None,
) -> dict[str, Any]:
    """Return the local ETF economics read model without provider access."""

    supplied_records = records
    if supplied_records is None:
        for name in ("etf_economics", "etf_economics_records", "economics_records"):
            candidate = getattr(snapshot, name, None)
            if candidate is not None:
                supplied_records = candidate
                break
    supplied_fund = fund_total_return
    if supplied_fund is None:
        for name in ("etf_fund_total_return", "fund_total_return"):
            candidate = getattr(snapshot, name, None)
            if candidate is not None:
                supplied_fund = candidate
                break
    supplied_benchmark = benchmark_total_return
    if supplied_benchmark is None:
        for name in ("etf_benchmark_total_return", "benchmark_total_return"):
            candidate = getattr(snapshot, name, None)
            if candidate is not None:
                supplied_benchmark = candidate
                break
    supplied_policy = closure_policy
    if supplied_policy is None:
        supplied_policy = getattr(snapshot, "etf_closure_policy", None)
    decision_time = as_of if as_of is not None else getattr(getattr(snapshot, "data_report", None), "as_of_date", None)
    report = calculate_etf_economics(
        instrument_id,
        supplied_records if supplied_records is not None else (),
        fund_total_return=supplied_fund,
        benchmark_total_return=supplied_benchmark,
        as_of=decision_time,
        horizon_days=horizon_days,
        benchmark_id=benchmark_id,
        currency=currency,
        closure_policy=supplied_policy,
    )
    return report.as_dict()


def _scoreboard_row(instrument_id: str, *, candidate_score: SimpleInstrumentScore | None = None) -> dict[str, Any]:
    if _candidate_score_matches(candidate_score, instrument_id):
        return _candidate_scoreboard(candidate_score)  # type: ignore[arg-type]
    frame = load_simple_scoreboard(SCOREBOARD_PATH)
    rows = _instrument_rows(frame, instrument_id, columns=("instrument_id", "display_id", "etf_id"))
    return rows.iloc[-1].to_dict() if not rows.empty else {}


def _score_panel(signal: Any, scoreboard: Mapping[str, Any], derived: Mapping[str, Any], friction: Mapping[str, Any]) -> dict[str, Any]:
    if signal is None and not scoreboard:
        return _unavailable("Score evidence unavailable for this instrument.") | {"crowding": derived["crowding"], "friction": friction}
    gates: list[str] = []
    for value in _safe_sequence(getattr(signal, "blocked_by", ())):
        gate_id = _normalise_identifier(value)
        if gate_id is not None and gate_id not in gates:
            gates.append(gate_id)
    decision = getattr(signal, "authority_decision", None)
    for gate in _safe_sequence(getattr(decision, "gates", ())):
        gate_id = _normalise_identifier(getattr(gate, "gate_id", None)) or "unavailable"
        if not _safe_bool(getattr(gate, "passed", True), default=False) and gate_id not in gates:
            gates.append(gate_id)
    evidence_score = next((_safe_float(scoreboard.get(key)) for key in ("evidence_score_10", "evidence_score", "final_combined_score_10") if _safe_float(scoreboard.get(key)) is not None), None)
    quality = next((_safe_float(scoreboard.get(key)) for key in ("evidence_quality_10", "evidence_quality") if _safe_float(scoreboard.get(key)) is not None), None)
    label = next((_safe_text(scoreboard.get(key)) for key in ("final_label", "final_action") if _safe_text(scoreboard.get(key)) is not None), None)
    if label is None:
        label = _safe_text(getattr(signal, "research_state", None))
    label_valid = label is not None
    label = label or "manual_review"
    reason = next((_safe_text(scoreboard.get(key)) for key in ("one_line_reason", "reason") if _safe_text(scoreboard.get(key)) is not None), None)
    if reason is None:
        reason = _safe_text(getattr(signal, "reason_long", None))
    reason_valid = reason is not None
    reason = reason or "Score reason unavailable."
    signal_score = _safe_float(getattr(signal, "total_score", None))
    canonical = getattr(signal, "canonical_score", None)
    canonical_payload = canonical.as_dict() if canonical is not None else {}
    signal_metrics = getattr(signal, "supporting_metrics", {})
    signal_confidence = (
        _safe_float(signal_metrics.get("canonical_evidence_confidence_10"))
        if isinstance(signal_metrics, Mapping)
        else None
    )
    canonical_confidence = _safe_float(canonical_payload.get("evidence_confidence_10"))
    scoreboard_confidence = _safe_float(scoreboard.get("canonical_evidence_confidence_10"))
    freshness = _safe_text(scoreboard.get("freshness_status"))
    freshness_valid = freshness is not None
    numeric_available = any(value is not None for value in (evidence_score, quality, signal_score))
    status = "available" if numeric_available and label_valid and reason_valid and freshness_valid else "manual_review"
    return {
        "status": status,
        "evidence_score": evidence_score,
        "evidence_quality": quality,
        "signal_score": signal_score,
        "canonical_attractiveness_10": _safe_float(scoreboard.get("canonical_attractiveness_10")) or _safe_float(canonical_payload.get("attractiveness_10")),
        "canonical_expected_return_10": _safe_float(scoreboard.get("canonical_expected_return_10")) or _safe_float(canonical_payload.get("expected_return_10")),
        "canonical_risk_implementation_10": _safe_float(scoreboard.get("canonical_risk_implementation_10")) or _safe_float(canonical_payload.get("risk_implementation_10")),
        "canonical_evidence_confidence_10": (
            signal_confidence
            if signal_confidence is not None
            else canonical_confidence
            if canonical_confidence is not None
            else scoreboard_confidence
        ),
        "canonical_coverage": _safe_float(scoreboard.get("canonical_coverage")) or _safe_float(canonical_payload.get("coverage")) or 0.0,
        "formula_version": scoreboard.get("formula_version") or canonical_payload.get("formula_version", "unavailable"),
        "formula_checksum": scoreboard.get("formula_checksum") or canonical_payload.get("formula_checksum", "unavailable"),
        "source_vintage_hash": scoreboard.get("source_vintage_hash") or canonical_payload.get("source_vintage_hash", "unavailable"),
        "final_label": label,
        "final_reason": reason,
        "reason": reason,
        "blocked_gates": gates,
        "warnings": list(_safe_sequence(getattr(signal, "warnings", ()))),
        "freshness": freshness or "unavailable",
        "crowding": derived["crowding"],
        "friction": friction,
        "execution_allowed": False,
        **_provenance_fields(scoreboard),
    }


def _risk_panel(features: object, friction: Mapping[str, Any], crowding: Mapping[str, Any]) -> dict[str, Any]:
    rows = _safe_frame(features)
    if rows.empty:
        return _unavailable("Risk and feature evidence unavailable for this instrument.") | {"crowding": crowding, "cost": friction}
    row = rows.iloc[-1]
    values = {str(key): _safe_float(row.get(key)) for key in row.index}
    momentum = {key: values.get(key) for key in ("momentum_20d", "momentum_60d", "momentum_120d", "momentum_180d")}
    trend = {key: values.get(key) for key in ("trend_100", "trend_200", "trend_slope")}
    relative = {key: values.get(key) for key in ("relative_strength_60d", "relative_strength_120d")}
    volatility = {key: values.get(key) for key in ("vol_20d_ann", "vol_60d_ann", "vol_120d_ann", "ewma_vol_ann")}
    drawdown = {key: values.get(key) for key in ("drawdown_current", "drawdown_60d_max", "drawdown_120d_max")}
    liquidity = {"liquidity_score": values.get("liquidity_score")}
    as_of_raw = row.get("date", row.get("as_of_date"))
    as_of_timestamp = _safe_datetime_scalar(as_of_raw)
    required_values = [*momentum.values(), *trend.values(), *relative.values(), *volatility.values(), *drawdown.values(), liquidity["liquidity_score"]]
    if pd.isna(as_of_timestamp) or not any(value is not None for value in required_values):
        return _unavailable("Risk and feature evidence unavailable; no valid dated risk dimensions are registered.") | {"crowding": crowding, "cost": friction}
    return {
        "status": "available",
        "as_of": str(as_of_timestamp),
        "momentum": momentum,
        "momentum_60d": momentum["momentum_60d"],
        "trend": trend,
        "trend_200": trend["trend_200"],
        "relative_strength": relative,
        "relative_strength_60d": relative["relative_strength_60d"],
        "volatility": volatility,
        "drawdown": drawdown,
        "liquidity": liquidity,
        "cost": friction,
        "crowding": crowding,
        "execution_allowed": False,
        **_provenance_fields(row),
    }


def _attribution_panel(derived: Mapping[str, Any], scoreboard: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(derived.get("attribution", {}))
    aliases = {
        "alpha": ("alpha", "alpha_proxy"),
        "beta": ("beta", "benchmark_beta"),
        "correlation": ("correlation", "benchmark_correlation"),
    }
    for target, names in aliases.items():
        value[target] = next(
            (
                _safe_float(scoreboard.get(name))
                for name in names
                if _safe_float(scoreboard.get(name)) is not None
            ),
            next((_safe_float(value.get(name)) for name in names if _safe_float(value.get(name)) is not None), None),
        )
    value.setdefault("status", "available" if any(value.get(key) is not None for key in ("alpha", "beta", "correlation")) else "unavailable")
    for key, metadata in _provenance_fields(scoreboard).items():
        value.setdefault(key, metadata)
    value["execution_allowed"] = False
    return value


def _forecast_panel(snapshot: CockpitSnapshot, instrument_id: str) -> dict[str, Any]:
    rows = _instrument_rows(getattr(snapshot, "forecasts", None), instrument_id)
    if rows.empty:
        return _unavailable("Forecast evidence unavailable; no valid local forecast rows are registered.") | {"rows": []}
    return {"status": "available", "rows": rows.where(pd.notna(rows), None).to_dict("records"), "execution_allowed": False, **_provenance_fields(rows.iloc[-1])}


def _backtest_panel(snapshot: CockpitSnapshot, instrument_id: str, scoreboard: Mapping[str, Any]) -> dict[str, Any]:
    llm_backtest_fields = {
        "llm_backtest_validity": "unknown",
        "llm_backtest_reason": "LLM diary output is unknown historical evidence unless strict forward-only decision-time markers exist.",
        "llm_output_authority": "excluded_from_backtest",
    }
    report = getattr(snapshot, "backtest", None)
    signal_log = _instrument_rows(getattr(report, "signal_log", None), instrument_id)
    trade_log = _instrument_rows(getattr(report, "trade_log", None), instrument_id)
    quality_raw = None
    quality_present = False
    scoreboard_quality_seen = False
    for key in ("backtest_trust_label", "backtest_validity"):
        if key in scoreboard:
            scoreboard_quality_seen = True
        if key in scoreboard and not _is_missing_scalar(scoreboard.get(key)):
            quality_raw = scoreboard.get(key)
            quality_present = True
            break
    quality = _safe_backtest_quality(quality_raw)
    report_quality_raw = getattr(report, "quality_label", None)
    if not quality_present and not scoreboard_quality_seen and report is not None and (not signal_log.empty or not trade_log.empty) and not _is_missing_scalar(report_quality_raw):
        quality_raw = report_quality_raw
        quality_present = True
        quality = _safe_backtest_quality(report_quality_raw)
    if signal_log.empty and trade_log.empty and not quality_present:
        return _unavailable("Backtest trust unavailable for this instrument.") | {"trust": "unavailable", "signal_rows": [], "trade_rows": [], **llm_backtest_fields}
    metadata_source = scoreboard or (signal_log.iloc[-1] if not signal_log.empty else trade_log.iloc[-1])
    trust = quality or "unavailable"
    return {"status": "available" if quality is not None else "manual_review", "trust": trust, "signal_rows": signal_log.to_dict("records"), "trade_rows": trade_log.to_dict("records"), "execution_allowed": False, **llm_backtest_fields, **_provenance_fields(metadata_source)}


def _paper_trade_panel(instrument_id: str, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    source = frame if isinstance(frame, pd.DataFrame) else _load_parquet(PAPER_TRADES_PATH)
    if not isinstance(frame, pd.DataFrame) and source.empty:
        source = pd.DataFrame(load_paper_trade_rows(PAPER_TRADES_PATH.parents[1].parent))
    rows = _instrument_rows(source, instrument_id)
    if rows.empty:
        return _unavailable("Paper-trade history unavailable; no local paper-trade records are registered.") | {"rows": []}
    return {"status": "available", "rows": rows.to_dict("records"), "execution_allowed": False, **_provenance_fields(rows.iloc[-1])}


def _history_panel(instrument_id: str, history: pd.DataFrame | None = None) -> dict[str, Any]:
    try:
        source = history if isinstance(history, pd.DataFrame) else score_history_frame()
    except Exception:
        source = pd.DataFrame()
    rows = _instrument_rows(source, instrument_id)
    if rows.empty:
        return _unavailable("Score history unavailable; a second local score run is required.") | {"rows": []}
    return {"status": "available", "rows": rows.to_dict("records"), "execution_allowed": False, **_provenance_fields(rows.iloc[-1])}


def _run_changes_panel(instrument_id: str, history: pd.DataFrame | None = None) -> dict[str, Any]:
    try:
        source = history if isinstance(history, pd.DataFrame) else score_history_frame()
        source = _instrument_rows(source, instrument_id)
        if not isinstance(source, pd.DataFrame) or source.empty or "run_id" not in source.columns:
            raise ValueError("no score history")
        runs = list(dict.fromkeys(source["run_id"].astype(str).tolist()))
        current = runs[-1]
        previous = runs[-2] if len(runs) > 1 else None
        report = compare_runs(source, current, previous)
        changes = [change.__dict__ for change in report.changes if change.instrument_id == instrument_id]
        return {"status": "available", "current_run_id": current, "previous_run_id": previous, "changes": changes, "execution_allowed": False, **_provenance_fields(source.iloc[-1])}
    except Exception:
        return _unavailable("What changed since the last run is unavailable until comparable score history exists.") | {"changes": []}


def _journal_panel(instrument_id: str, frame: pd.DataFrame | None = None) -> dict[str, Any]:
    rows = _instrument_rows(frame, instrument_id) if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    if rows.empty:
        return _unavailable("Decision journal entries unavailable for this instrument.") | {"entries": []}
    return {"status": "available", "entries": rows.to_dict("records"), "execution_allowed": False, **_provenance_fields(rows.iloc[-1])}


def _thesis_diary_panel(instrument_id: str, *, root: Path | None = None) -> dict[str, Any]:
    """Project only the selected instrument's non-authoritative LLM diary rows."""

    try:
        store = ThesisDiaryStore(root or DATA_DIR)
        entries = [entry for entry in store.list_entries() if entry.instrument_id == instrument_id]
        records: list[dict[str, Any]] = []
        for entry in entries:
            state = store.replay(entry.thesis_id)
            outcomes = dict(entry.outcomes)
            for event in state.outcomes:
                horizon = event.get("horizon")
                if horizon in outcomes:
                    outcomes[horizon] = dict(event)
            currently_redacted = state.redaction_state == "redacted"
            display_entry = disclosure_safe_entry(entry) if currently_redacted else entry
            record = display_entry.model_dump(mode="json")
            record.update(
                {
                    "human_review_status": state.human_review.get("status", entry.human_review_status),
                    "human_review": disclosure_safe_review(state.human_review) if currently_redacted else dict(state.human_review),
                    "redaction_state": state.redaction_state,
                    "expires_at": state.expires_at,
                    "expired": state.expired,
                    "replayed_at": state.replayed_at,
                    "applied_event_ids": list(state.applied_event_ids),
                    "outcomes": {
                        horizon: disclosure_safe_outcome(value) if currently_redacted and isinstance(value, dict) else value
                        for horizon, value in outcomes.items()
                    },
                    "outcome_events": [
                        disclosure_safe_outcome(value) if currently_redacted else value
                        for value in state.outcomes
                    ],
                    "execution_allowed": False,
                    "executable_authority": False,
                    "score_eligible": False,
                    "action_authority": False,
                    "risk_gate_authority": False,
                }
            )
            records.append(record)
    except (ThesisDiaryIntegrityError, OSError, ValueError) as exc:
        return _unavailable(f"LLM thesis diary unavailable; manual review required ({type(exc).__name__}).") | {
            "entries": [],
            "score_eligible": False,
            "action_authority": False,
            "risk_gate_authority": False,
        }
    if not records:
        return _unavailable("No persisted LLM thesis diary entries are available for this instrument.") | {
            "entries": [],
            "score_eligible": False,
            "action_authority": False,
            "risk_gate_authority": False,
        }
    return {
        "status": "available",
        "instrument_id": instrument_id,
        "entries": records,
        "message": "LLM theses are context-only and cannot affect scores, actions, risk gates or trade proposals.",
        "execution_allowed": False,
        "executable_authority": False,
        "score_eligible": False,
        "action_authority": False,
        "risk_gate_authority": False,
    }


def _candidate_identity_panel(instrument_id: str, candidate_score: SimpleInstrumentScore) -> dict[str, Any]:
    source_group = _safe_text(candidate_score.source_group) or "unavailable"
    analysis_tier = _safe_text(candidate_score.analysis_tier) or "unavailable"
    asset_type = _safe_text(candidate_score.asset_type) or "unavailable"
    return {
        "status": "available",
        "instrument_id": instrument_id,
        "name": _safe_text(candidate_score.name) or instrument_id,
        "ticker": _safe_text(candidate_score.yahoo_symbol) or "unavailable",
        "isin": _safe_text(candidate_score.isin) or "needs_verification",
        "asset_type": asset_type,
        "asset_class": "unavailable",
        "group": source_group,
        "analysis_tier": analysis_tier,
        "exchange": "unavailable",
        "currency": "unavailable",
        "region": "unavailable",
        "sector": "unavailable",
        "theme": "unavailable",
        "source_id": candidate_score.instrument_key,
        "source_authority": "score_row",
        "conflict_id": "unavailable",
        "execution_allowed": False,
    }


def build_instrument_detail(
    snapshot: CockpitSnapshot,
    instrument_id: str,
    *,
    document_registry: pd.DataFrame | None = None,
    holdings: pd.DataFrame | None = None,
    kid_records: pd.DataFrame | None = None,
    methodology_records: pd.DataFrame | None = None,
    report_records: pd.DataFrame | None = None,
    structure_rows: object = None,
    fundamentals: pd.DataFrame | None = None,
    news: pd.DataFrame | None = None,
    events: pd.DataFrame | None = None,
    score_history: pd.DataFrame | None = None,
    paper_trades: pd.DataFrame | None = None,
    journal: pd.DataFrame | None = None,
    thesis_diary_root: Path | None = None,
    candidate_score: SimpleInstrumentScore | None = None,
    financial_projection: Mapping[str, object] | None = None,
    real_asset_projection: Mapping[str, object] | None = None,
    cyclical_projection: Mapping[str, object] | None = None,
    cyclical_source_digest: str | None = None,
    innovation_projection: Mapping[str, object] | None = None,
    innovation_source_digest: str | None = None,
    economics_records: object = None,
    fund_total_return: object = None,
    benchmark_total_return: object = None,
    economics_as_of: object = None,
    economics_horizon_days: int = 252,
) -> InstrumentDetailViewModel:
    identity = next((item for item in snapshot.config.universe.etfs if item.id == instrument_id), None)
    # Configured identities remain backed by canonical snapshot stores.  The
    # score-row context is only a fallback for secondary/Sparebanken rows that
    # are intentionally absent from the configured universe.
    candidate = candidate_score if identity is None and _candidate_score_matches(candidate_score, instrument_id) else None
    if identity is None and candidate is None:
        return InstrumentDetailViewModel(instrument_id, instrument_id, "unavailable", {"instrument_id": instrument_id}, {name: "unavailable" for name in _SECTION_NAMES})
    signal = next((item for item in getattr(snapshot, "signals", ()) if item.etf_id == instrument_id), None)
    features = _instrument_rows(getattr(snapshot, "latest_features", None), instrument_id)
    if features.empty:
        all_features = _instrument_rows(getattr(snapshot, "features", None), instrument_id)
        if not all_features.empty and "date" in all_features.columns:
            features = all_features.sort_values("date", kind="stable").tail(1)
    derived = _derived_evidence_panel(instrument_id)
    friction = _friction_panel(instrument_id, candidate_score=candidate)
    scoreboard = _scoreboard_row(instrument_id, candidate_score=candidate)
    decision_time = getattr(getattr(snapshot, "data_report", None), "as_of_date", None)
    projection_time = str(decision_time or "").strip()
    if len(projection_time) == 10:
        projection_time = f"{projection_time}T23:59:59Z"
    identity_evidence: dict[str, object] = {
        "status": "unavailable",
        "instrument_id": instrument_id,
        "reason_code": "identity_master_evidence_unavailable",
        "execution_allowed": False,
    }
    if candidate is not None:
        identity_panel = _candidate_identity_panel(instrument_id, candidate)
        display_name = identity_panel["name"]
    else:
        group = str(getattr(identity, "source_group", "") or ("Sparebanken" if str(identity.instrument_type).casefold() in {"equity_certificate", "certificate"} else identity.analysis_tier or "unavailable"))
        identity_panel = {
            "status": "available",
            "instrument_id": instrument_id,
            "name": identity.name,
            "ticker": identity.ticker,
            "isin": identity.isin or "needs_verification",
            "asset_type": identity.instrument_type or identity.asset_class,
            "asset_class": identity.asset_class,
            "group": group,
            "exchange": identity.exchange or "unavailable",
            "currency": identity.currency or "unavailable",
            "region": identity.region or "unavailable",
            "sector": identity.sector or "unavailable",
            "theme": identity.theme or "unavailable",
            "source_id": f"config:universe:{instrument_id}",
            "execution_allowed": False,
        }
        identity_evidence = load_identity_projection(
            instrument_id,
            effective_at=projection_time or None,
            decision_time=projection_time or None,
        )
        if identity_evidence.get("status") == "available":
            identity_panel.update(
                {
                    "identity_confidence": identity_evidence.get("identity_confidence", "unavailable"),
                    "identity_status": identity_evidence.get("identity_status", "unavailable"),
                    "identity_decision_id": identity_evidence.get("identity_decision_id", "unavailable"),
                    "identity_conflict_ids": identity_evidence.get("identity_conflict_ids", "unavailable"),
                    "identity_resolution_state": identity_evidence.get("identity_resolution_state", "unavailable"),
                    "identity_effective_at": identity_evidence.get("identity_effective_at", "unavailable"),
                    "identity_decision_time": identity_evidence.get("identity_decision_time", "unavailable"),
                    "identity_objects": identity_evidence.get("identity_objects", "unavailable"),
                    "identity_history": identity_evidence.get("identity_history", "unavailable"),
                    "identity_conflicts": identity_evidence.get("identity_conflicts", "unavailable"),
                    "identity_reviews": identity_evidence.get("identity_reviews", "unavailable"),
                    "identity_warnings": identity_evidence.get("warnings", "unavailable"),
                }
            )
        else:
            identity_panel.update(
                {
                    "identity_resolution_state": identity_evidence.get("status", "unavailable"),
                    "identity_reason_code": identity_evidence.get("reason_code", "identity_evidence_unavailable"),
                }
            )
        display_name = identity.name
    classification_evidence = load_classification_projection(instrument_id)
    if classification_evidence.get("status") in {"available", "unresolved"}:
        classification = classification_evidence.get("classification", {})
        route = classification_evidence.get("sector_adapter_route", {})
        identity_panel.update(
            {
                "classification_status": classification_evidence.get("status", "unresolved"),
                "classification": classification,
                "classification_confidence": (
                    classification.get("classification_confidence", 0.0)
                    if isinstance(classification, Mapping)
                    else 0.0
                ),
                "classification_version_id": (
                    classification.get("version_id", "unavailable")
                    if isinstance(classification, Mapping)
                    else "unavailable"
                ),
                "classification_fallback_path": (
                    classification.get("fallback_path", ())
                    if isinstance(classification, Mapping)
                    else ()
                ),
                "classification_sector_route": route,
            }
        )
    else:
        identity_panel.update(
            {
                "classification_status": "unavailable",
                "classification_reason_code": classification_evidence.get(
                    "reason_code", "classification_evidence_unavailable"
                ),
            }
        )
    disclosure = _etf_disclosure_panel(instrument_id, document_registry=document_registry, holdings=holdings, kid_records=kid_records, methodology_records=methodology_records)
    structure = _etf_structure_panel(
        instrument_id,
        document_registry=document_registry,
        report_records=report_records,
        supplemental_rows=structure_rows,
        holdings=holdings,
        decision_time=decision_time,
    )
    overlap = build_direct_overlap_view(
        snapshot,
        [str(item.id) for item in snapshot.config.universe.etfs if bool(item.enabled)],
        focus_instrument_id=instrument_id,
        holdings=holdings,
    )
    liquidity = build_etf_liquidity_panel(snapshot, instrument_id)
    economics = build_etf_economics_panel(
        snapshot,
        instrument_id,
        records=economics_records,
        fund_total_return=fund_total_return,
        benchmark_total_return=benchmark_total_return,
        as_of=economics_as_of,
        horizon_days=economics_horizon_days,
    )
    price = _price_panel(snapshot, instrument_id, candidate_score=candidate)
    observed_at = price.get("latest_date") if isinstance(price, Mapping) else None
    market_clock = build_market_clock_diagnostics(
        identity_evidence,
        decision_time=projection_time or decision_time or "",
        observed_at=observed_at if observed_at not in {None, "unavailable"} else None,
    )
    fixed_income_terms = load_fixed_income_terms_projection(
        instrument_id,
        effective_at=projection_time or None,
        decision_time=projection_time or None,
    )
    fixed_income_market_data = load_fixed_income_market_data_projection(
        instrument_id,
        effective_at=projection_time or None,
        decision_time=projection_time or None,
    )
    fixed_income_analytics = load_fixed_income_analytics_projection(
        instrument_id,
        decision_time=projection_time or None,
    )
    fixed_income_risk = load_fixed_income_risk_projection(
        instrument_id,
        decision_time=projection_time or None,
    )
    peer_cohort = load_peer_cohort_projection(
        instrument_id,
        decision_time=projection_time or None,
    )
    financial_institutions = load_financial_institution_projection(
        instrument_id, projection=financial_projection
    )
    real_assets = load_real_asset_projection(
        instrument_id, projection=real_asset_projection
    )
    cyclicals = load_cyclical_projection(
        instrument_id,
        projection=cyclical_projection,
        expected_source_digest=cyclical_source_digest,
    )
    innovation = load_innovation_projection(
        instrument_id,
        projection=innovation_projection,
        expected_source_digest=innovation_source_digest,
    )
    return InstrumentDetailViewModel(
        instrument_id,
        display_name,
        "ready",
        identity_panel,
        {
            "identity": identity_panel,
            "price": price,
            "market_clock": market_clock,
            "fixed_income_terms": fixed_income_terms,
            "fixed_income_market_data": fixed_income_market_data,
            "fixed_income_analytics": fixed_income_analytics,
            "fixed_income_risk": fixed_income_risk,
            "peer_cohort": peer_cohort,
            "financial_institutions": financial_institutions,
            "real_assets": real_assets,
            "cyclicals": cyclicals,
            "innovation": innovation,
            "etf_liquidity": liquidity,
            "etf_economics": economics,
            "scores": _score_panel(signal, scoreboard, derived, friction),
            "feature_drivers": _feature_driver_panel(instrument_id),
            "risk": _risk_panel(features, friction, derived["crowding"]),
            "attribution": _attribution_panel(derived, scoreboard),
            "fundamentals": _fundamentals_panel(instrument_id, fundamentals),
            "etf_disclosures": disclosure,
            "etf_structure": structure,
            "etf_holdings": disclosure.get("exposure", _unavailable("ETF holdings/exposure unavailable.")),
            "etf_overlap": direct_overlap_payload(overlap),
            "news": _news_panel(instrument_id, news),
            "events": _event_calendar_panel(instrument_id, events, decision_time=projection_time or decision_time),
            "forecasts": _forecast_panel(snapshot, instrument_id),
            "backtests": _backtest_panel(snapshot, instrument_id, scoreboard),
            "paper_trades": _paper_trade_panel(instrument_id, paper_trades),
            "history": _history_panel(instrument_id, score_history),
            "journal": _journal_panel(instrument_id, journal),
            "thesis_diary": _thesis_diary_panel(instrument_id, root=thesis_diary_root),
            "run_changes": _run_changes_panel(instrument_id, score_history),
        },
    )


def _derived_evidence_panel(instrument_id: str) -> dict[str, dict[str, Any]]:
    """Load persisted crowding/attribution evidence without recalculating UI authority."""

    crowding: dict[str, Any] = {"status": "unavailable", "message": "Correlation cluster evidence is unavailable.", "execution_allowed": False}
    attribution: dict[str, Any] = {"status": "unavailable", "message": "Benchmark attribution evidence is unavailable.", "sector_attribution_status": "N/A", "execution_allowed": False}
    try:
        if CORRELATION_CLUSTERS_PATH.exists():
            frame = pd.read_parquet(CORRELATION_CLUSTERS_PATH)
            rows = _instrument_rows(frame, instrument_id)
            if not rows.empty:
                crowding = {**rows.iloc[-1].to_dict(), "status": str(rows.iloc[-1].get("status", "available")), "execution_allowed": False}
    except Exception:
        pass
    try:
        if BENCHMARK_ATTRIBUTION_PATH.exists():
            frame = pd.read_parquet(BENCHMARK_ATTRIBUTION_PATH)
            rows = _instrument_rows(frame, instrument_id)
            if not rows.empty:
                attribution = {**rows.iloc[-1].to_dict(), "status": str(rows.iloc[-1].get("status", "available")), "execution_allowed": False}
    except Exception:
        pass
    return {"crowding": crowding, "attribution": attribution}
