"""Trusted ETF economics records and canonical total-return inputs for the cockpit snapshot (application; ADR-0002)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import pandas as pd

from etf_cockpit.core.paths import (
    ETF_BENCHMARK_TOTAL_RETURN_PATH,
    ETF_FUND_TOTAL_RETURN_PATH,
)
from etf_cockpit.data.etf_economics import (
    ClosureProxyPolicy,
    ETF_ECONOMICS_PATH,
    EtfEconomicsObservation,
    TotalReturnEvidence,
    load_closure_proxy_policy,
    load_etf_economics_import_manifest,
    load_etf_economics_records,
    load_total_return_evidence,
)
from etf_cockpit.data.market_adjustments import (
    CorporateActionCoverageStore,
    CorporateActionStore,
    apply_total_return_adjustments,
)
from etf_cockpit.data.local_storage import storage_layout
from etf_cockpit.data.parsed_disclosures import read_etf_report_records
from etf_cockpit.data.trust_artifacts import IDENTITY_PATH


def _trusted_etf_economics_records() -> tuple[EtfEconomicsObservation, ...]:
    manifest = load_etf_economics_import_manifest(ETF_ECONOMICS_PATH)
    if manifest is None:
        return ()
    try:
        reports = read_etf_report_records()
    except (OSError, TypeError, ValueError):
        return ()
    required = {"source_id", "source_sha256", "source_authority", "verification_status", "evidence_eligible"}
    if reports.empty or not required.issubset(reports.columns):
        return ()
    eligible = (
        reports["source_authority"].astype(str).str.casefold().isin({"official_regulator", "issuer_document"})
        & reports["verification_status"].astype(str).str.casefold().eq("verified")
        & reports["evidence_eligible"].astype(str).str.casefold().isin({"true", "1", "yes"})
    )
    trusted = {
        str(row.source_id): str(row.source_sha256).casefold()
        for row in reports.loc[eligible, ["source_id", "source_sha256"]].itertuples(index=False)
        if str(row.source_id).strip() and str(row.source_sha256).strip()
    }
    if not trusted:
        return ()
    return load_etf_economics_records(
        ETF_ECONOMICS_PATH,
        trusted_sha256=manifest["sha256"],
        trusted_sources=trusted,
    )


def _canonical_total_return_from_prices(
    prices: pd.DataFrame,
    instrument_id: str,
    currency: str,
    decision_time: object,
) -> TotalReturnEvidence | None:
    """Bind persisted price rows to the canonical action-coverage ledger."""

    identity_column = "instrument_id" if "instrument_id" in prices.columns else "etf_id" if "etf_id" in prices.columns else None
    required = {"date", "close", "currency", "known_at", "source_id", "provenance"}
    if identity_column is None or not required.issubset(prices.columns):
        return None
    try:
        cutoff = pd.Timestamp(decision_time)
        if pd.isna(cutoff):
            return None
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("UTC")
        else:
            cutoff = cutoff.tz_convert("UTC")
        frame = prices.loc[prices[identity_column].astype(str).eq(instrument_id)].copy()
        if frame.empty:
            return None
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
        frame = frame.loc[frame["date"].notna() & frame["date"].le(cutoff)].copy()
        if frame.empty or frame[["known_at", "source_id", "provenance"]].isna().any().any():
            return None
        if frame[["source_id", "provenance"]].astype(str).apply(lambda column: column.str.strip().eq("")).any().any():
            return None
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
        frame["known_at"] = pd.to_datetime(frame["known_at"], errors="coerce", utc=True)
        if frame["known_at"].isna().any():
            return None
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.loc[
            frame["date"].notna()
            & frame["known_at"].notna()
            & frame["close"].notna()
            & frame["known_at"].le(cutoff)
            & frame["date"].le(cutoff)
            & frame["currency"].astype(str).eq(currency)
        ].sort_values(["date", "known_at"], kind="stable")
        if frame.duplicated(["date", "known_at"]).any():
            return None
        frame = frame.drop_duplicates(subset=["date"], keep="last")
        if len(frame) < 2:
            return None
        if frame["source_id"].isna().any() or frame["provenance"].isna().any():
            return None
        source_ids = set(frame["source_id"].astype(str).str.strip())
        provenances = set(frame["provenance"].astype(str).str.strip())
        if len(source_ids) != 1 or not next(iter(source_ids)).strip() or len(provenances) != 1 or not next(iter(provenances)).strip():
            return None
        identity_path = Path(IDENTITY_PATH).resolve()
        if len(identity_path.parents) < 3:
            return None
        root = identity_path.parents[2]
        if not storage_layout(root).transactional_path.is_file():
            return None
        as_of = frame["date"].max().isoformat().replace("+00:00", "Z")
        decision = cutoff.isoformat().replace("+00:00", "Z")
        with CorporateActionStore(root) as action_store, CorporateActionCoverageStore(root) as coverage_store:
            coverage = coverage_store.as_of(instrument_id, valid_at=as_of, known_at=decision)
            actions = action_store.replay(instrument_id, effective_at=as_of, known_at=decision)
        if not coverage:
            return None
        trusted_coverage = max(coverage, key=lambda item: (item.coverage_through, item.known_at))
        raw = frame[[identity_column, "date", "close", "currency", "source_id", "provenance", "known_at"]].copy()
        if identity_column != "instrument_id":
            raw = raw.rename(columns={identity_column: "instrument_id"})
        result = apply_total_return_adjustments(raw, actions)
        evidence_known_at = max(
            [pd.Timestamp(frame["known_at"].max()), pd.Timestamp(trusted_coverage.known_at), *(pd.Timestamp(item.known_at) for item in actions)],
        ).isoformat().replace("+00:00", "Z")
        return TotalReturnEvidence.from_adjustment_result(
            result,
            instrument_id=instrument_id,
            currency=currency,
            known_at=evidence_known_at,
            as_of=as_of,
            source_id=next(iter(source_ids)),
            provenance=next(iter(provenances)),
            corporate_action_coverage=trusted_coverage,
        )
    except (ArithmeticError, OSError, TypeError, ValueError, KeyError):
        return None


def _etf_economics_snapshot_inputs(
    prices: pd.DataFrame,
    decision_time: object,
) -> tuple[
    tuple[EtfEconomicsObservation, ...],
    Mapping[str, TotalReturnEvidence] | None,
    Mapping[str, TotalReturnEvidence] | None,
    ClosureProxyPolicy | None,
]:
    imported_records = _trusted_etf_economics_records()
    cutoff = pd.Timestamp(decision_time)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    records = tuple(
        item
        for item in imported_records
        if item.artifact_known_at is not None
        and pd.Timestamp(item.artifact_known_at) <= cutoff
    )
    eligible_funds = [
        item for item in records
        if item.scope == "fund"
        and pd.Timestamp(item.as_of) <= cutoff
        and pd.Timestamp(item.known_at) <= cutoff
    ]
    latest_by_instrument: dict[str, EtfEconomicsObservation] = {}
    for item in eligible_funds:
        current = latest_by_instrument.get(item.instrument_id)
        if current is None or (item.as_of, item.known_at or "") > (current.as_of, current.known_at or ""):
            latest_by_instrument[item.instrument_id] = item

    fund_returns: dict[str, TotalReturnEvidence] = {}
    benchmark_returns: dict[str, TotalReturnEvidence] = {}
    persisted_fund = load_total_return_evidence(ETF_FUND_TOTAL_RETURN_PATH)
    persisted_benchmark = load_total_return_evidence(ETF_BENCHMARK_TOTAL_RETURN_PATH)
    if persisted_fund is not None:
        fund_returns[persisted_fund.instrument_id] = persisted_fund
    if persisted_benchmark is not None:
        benchmark_returns[persisted_benchmark.instrument_id] = persisted_benchmark

    for item in latest_by_instrument.values():
        if item.instrument_id not in fund_returns and item.currency is not None:
            evidence = _canonical_total_return_from_prices(
                prices, item.instrument_id, item.currency, decision_time
            )
            if evidence is not None:
                fund_returns[item.instrument_id] = evidence
        if (
            item.benchmark_id
            and item.benchmark_currency
            and item.benchmark_id not in benchmark_returns
        ):
            evidence = _canonical_total_return_from_prices(
                prices, item.benchmark_id, item.benchmark_currency, decision_time
            )
            if evidence is not None:
                benchmark_returns[item.benchmark_id] = evidence
    return (
        records,
        fund_returns or None,
        benchmark_returns or None,
        load_closure_proxy_policy(),
    )
