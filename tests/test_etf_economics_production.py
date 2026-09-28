from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import etf_cockpit.services as services
from etf_cockpit.application import ui_facade
from etf_cockpit.data.etf_economics import (
    EtfEconomicsStore,
    load_closure_proxy_policy,
    load_etf_economics_records,
)
from etf_cockpit.data.market_adjustments import (
    CorporateActionCoverage,
    CorporateActionCoverageStore,
)


FIXTURE = Path(__file__).parent / "fixtures" / "economics"
INSTRUMENT_ID = "IE00B5BMR087"
BENCHMARK_ID = "synthetic:world-index"
DECISION_TIME = "2026-01-08"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_production_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    prices: pd.DataFrame | None = None,
    records: tuple[object, ...] | None = None,
):
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    economics_path = FIXTURE / "economics.csv"
    disclosure_checksum = _sha256(FIXTURE / "synthetic_disclosure.txt")
    assert manifest["data_status"] == "SYNTHETIC_NON_OFFICIAL_TEST_ONLY"
    assert manifest["disclosure_source_checksum"] == disclosure_checksum

    trusted_sources = {
        manifest["disclosure_source_id"]: disclosure_checksum,
    }
    loaded = load_etf_economics_records(
        economics_path,
        trusted_sha256=_sha256(economics_path),
        trusted_sources=trusted_sources,
    )
    base_records = records if records is not None else EtfEconomicsStore(loaded).records

    def economics_loader(**kwargs):
        if records is not None:
            return tuple(base_records)
        return load_etf_economics_records(
            economics_path,
            trusted_sha256=_sha256(economics_path),
            **kwargs,
        )

    monkeypatch.setattr(services, "load_etf_economics_records", economics_loader)
    monkeypatch.setattr(
        services,
        "read_etf_report_records",
        lambda: pd.DataFrame(
            [
                {
                    "source_id": manifest["disclosure_source_id"],
                    "source_sha256": disclosure_checksum,
                    "source_authority": "issuer_document",
                    "verification_status": "verified",
                    "evidence_eligible": True,
                }
            ]
        ),
    )
    policy_path = FIXTURE / "closure-policy.json"
    monkeypatch.setattr(
        services,
        "load_closure_proxy_policy",
        lambda: load_closure_proxy_policy(policy_path, trusted_sha256=_sha256(policy_path)),
    )

    root = tmp_path / "canonical-store"
    monkeypatch.setattr(services, "IDENTITY_PATH", root / "data" / "clean" / "identity.parquet")
    with CorporateActionCoverageStore(root) as store:
        for value in manifest["corporate_action_coverage"]:
            store.append(CorporateActionCoverage(**value))

    price_frame = prices if prices is not None else pd.read_csv(FIXTURE / "prices.csv")
    records_out, fund, benchmark, policy = services._etf_economics_snapshot_inputs(
        price_frame, DECISION_TIME
    )
    return records_out, fund, benchmark, policy, price_frame


def _visible_panel(records, fund, benchmark, policy, *, horizon_days: int = 3):
    snapshot = SimpleNamespace(
        etf_economics_records=records,
        etf_fund_total_return=fund,
        etf_benchmark_total_return=benchmark,
        etf_closure_policy=policy,
        data_report=SimpleNamespace(as_of_date=DECISION_TIME),
    )
    return ui_facade.load_etf_economics_projection(
        snapshot,
        INSTRUMENT_ID,
        horizon_days=horizon_days,
    )


def test_etf_economics_real_shareclass_e2e(monkeypatch, tmp_path) -> None:
    records, fund, benchmark, policy, _prices = _load_production_inputs(monkeypatch, tmp_path)

    assert fund is not None and benchmark is not None
    panel = _visible_panel(records, fund, benchmark, policy)

    assert panel["instrument_id"] == INSTRUMENT_ID
    assert panel["status"] == "available", panel["missing_evidence"]
    assert panel["tracking_status"] == "available"
    assert panel["fund_metrics"]["ter"] == 0.0022
    assert panel["share_class_metrics"][INSTRUMENT_ID]["ocf"] == 0.0022
    assert panel["closure_risk_proxy"]["status"] == "available"
    assert panel["fund_corporate_action_coverage"]["source_id"] == "synthetic-action-coverage-fund"
    assert panel["execution_allowed"] is False


@pytest.mark.parametrize("misalignment", ["currency", "calendar"])
def test_etf_economics_currency_calendar_misalignment(
    monkeypatch, tmp_path, misalignment: str
) -> None:
    prices = pd.read_csv(FIXTURE / "prices.csv")
    benchmark_rows = prices["instrument_id"].eq(BENCHMARK_ID)
    if misalignment == "currency":
        prices.loc[benchmark_rows, "currency"] = "USD"
    else:
        prices = prices.loc[~(benchmark_rows & prices["date"].eq("2026-01-06"))].copy()

    records, fund, benchmark, policy, _prices = _load_production_inputs(
        monkeypatch, tmp_path, prices=prices
    )
    panel = _visible_panel(records, fund, benchmark, policy)

    assert panel["tracking_status"] == "unavailable"
    assert panel["tracking_difference"] is None
    if misalignment == "currency":
        assert benchmark is None
        assert "benchmark_total_return" in panel["missing_evidence"]
    else:
        assert benchmark is not None
        assert panel["matched_rows"] == 3
        assert panel["coverage_ratio"] == 0.75


def test_etf_economics_provider_vs_calculated_label(monkeypatch, tmp_path) -> None:
    records, fund, benchmark, policy, _prices = _load_production_inputs(monkeypatch, tmp_path)
    panel = _visible_panel(records, fund, benchmark, policy)

    assert panel["fee_evidence_label"] == "disclosure-reported"
    assert panel["share_class_metrics"][INSTRUMENT_ID]["value_origin"] == "disclosure-reported"
    assert panel["tracking_evidence_label"] == "calculated from matched canonical total-return evidence"
    assert panel["tracking_status"] == "available"


@pytest.mark.parametrize("mismatch", ["share_class", "benchmark"])
def test_etf_economics_identity_mismatch_stays_unavailable(
    monkeypatch, tmp_path, mismatch: str
) -> None:
    prices = pd.read_csv(FIXTURE / "prices.csv")
    base = load_etf_economics_records(
        FIXTURE / "economics.csv",
        trusted_sha256=_sha256(FIXTURE / "economics.csv"),
    )
    if mismatch == "share_class":
        prices.loc[prices["instrument_id"].eq(INSTRUMENT_ID), "instrument_id"] = "synthetic:other-share-class"
        records = tuple(base)
    else:
        records = tuple(
            replace(item, benchmark_id="synthetic:other-benchmark")
            if item.scope == "fund" else item
            for item in base
        )

    loaded, fund, benchmark, policy, _prices = _load_production_inputs(
        monkeypatch, tmp_path, prices=prices, records=records
    )
    panel = _visible_panel(loaded, fund, benchmark, policy)

    assert panel["tracking_status"] == "unavailable"
    assert panel["tracking_difference"] is None
    if mismatch == "share_class":
        assert fund is None
    else:
        assert panel["benchmark_id"] == "synthetic:other-benchmark"
        assert benchmark is None


def test_etf_economics_insufficient_history_and_restatement_are_point_in_time(
    monkeypatch, tmp_path
) -> None:
    prices = pd.read_csv(FIXTURE / "prices.csv")
    prices = prices.loc[prices["date"].isin({"2026-01-05", "2026-01-06"})].copy()
    base = load_etf_economics_records(
        FIXTURE / "economics.csv",
        trusted_sha256=_sha256(FIXTURE / "economics.csv"),
    )
    restatement = replace(
        next(item for item in base if item.scope == "fund"),
        as_of=DECISION_TIME,
        known_at="2026-01-09",
        ter=0.009,
        ocf=0.009,
        revision_id="synthetic-later-restatement",
    )
    records, fund, benchmark, policy, _prices = _load_production_inputs(
        monkeypatch, tmp_path, prices=prices, records=tuple(base) + (restatement,)
    )
    panel = _visible_panel(records, fund, benchmark, policy)

    assert panel["tracking_status"] == "unavailable"
    assert panel["tracking_difference"] is None
    assert panel["fund_metrics"]["ter"] == 0.0022
    cutoff = pd.Timestamp(DECISION_TIME, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    assert all(pd.Timestamp(item["known_at"]) <= cutoff for item in panel["history"])


@pytest.mark.parametrize("evidence_case", ["stale_aum", "missing_fees", "ceased_class_history"])
def test_etf_economics_stale_or_unsupported_evidence_stays_traceable(
    monkeypatch, tmp_path, evidence_case: str
) -> None:
    base = load_etf_economics_records(
        FIXTURE / "economics.csv",
        trusted_sha256=_sha256(FIXTURE / "economics.csv"),
        trusted_sources={
            "synthetic-disclosure-ie00b5bmr087": _sha256(FIXTURE / "synthetic_disclosure.txt")
        },
    )
    prices = pd.read_csv(FIXTURE / "prices.csv")
    records = tuple(base)
    if evidence_case == "stale_aum":
        records = tuple(
            replace(item, as_of="2025-12-08", known_at="2025-12-08")
            for item in base
        )
    elif evidence_case == "missing_fees":
        records = tuple(replace(item, ter=None, ocf=None) for item in base)
    else:
        # A hypothetical closure/merger stops this share class's price history;
        # no successor identity or zero-filled observations are introduced.
        prices = prices.loc[
            ~(
                prices["instrument_id"].eq(INSTRUMENT_ID)
                & prices["date"].isin({"2026-01-07", "2026-01-08"})
            )
        ].copy()

    loaded, fund, benchmark, policy, _prices = _load_production_inputs(
        monkeypatch, tmp_path, prices=prices, records=records
    )
    panel = _visible_panel(loaded, fund, benchmark, policy)

    if evidence_case == "stale_aum":
        assert panel["fund_metrics"]["aum"] == 100_000_000.0
        assert panel["fund_metrics"]["aum_as_of"] == "2025-12-08T00:00:00Z"
    elif evidence_case == "missing_fees":
        assert panel["fund_metrics"]["ter"] is None
        assert panel["fund_metrics"]["ocf"] is None
        assert panel["fee_evidence_label"] == "unavailable"
    else:
        assert panel["tracking_status"] == "unavailable"
        assert panel["tracking_difference"] is None
        assert panel["matched_rows"] == 2
