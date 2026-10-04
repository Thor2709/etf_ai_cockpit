from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application.economics_inputs import _etf_economics_snapshot_inputs
import etf_cockpit.application.backtest_service as backtest_service
import etf_cockpit.application.economics_inputs as economics_inputs
import etf_cockpit.application.structural_evidence as structural_evidence
from etf_cockpit.application import ui_facade
from etf_cockpit.data.etf_economics import (
    EtfEconomicsStore,
    import_etf_economics_artifact,
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
    economics_path = tmp_path / "economics.csv"
    imported_artifact = import_etf_economics_artifact(
        FIXTURE / "economics.csv",
        known_at=DECISION_TIME,
        dest=economics_path,
    )
    monkeypatch.setattr(economics_inputs, "ETF_ECONOMICS_PATH", economics_path)
    disclosure_checksum = _sha256(FIXTURE / "synthetic_disclosure.txt")
    assert manifest["data_status"] == "SYNTHETIC_NON_OFFICIAL_TEST_ONLY"
    assert manifest["disclosure_source_checksum"] == disclosure_checksum

    trusted_sources = {
        manifest["disclosure_source_id"]: disclosure_checksum,
    }
    loaded = load_etf_economics_records(
        economics_path,
        trusted_sources=trusted_sources,
    )
    base_records = (
        tuple(
            replace(
                item,
                artifact_source_path=imported_artifact["source_path"],
                artifact_sha256=imported_artifact["sha256"],
                artifact_known_at=imported_artifact["known_at"],
            )
            for item in records
        )
        if records is not None
        else EtfEconomicsStore(loaded).records
    )

    def economics_loader(path=None, **kwargs):
        if records is not None:
            return tuple(base_records)
        return load_etf_economics_records(path or economics_path, **kwargs)

    monkeypatch.setattr(economics_inputs, "load_etf_economics_records", economics_loader)
    for module in (economics_inputs, structural_evidence):
        monkeypatch.setattr(
            module,
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
        economics_inputs,
        "load_closure_proxy_policy",
        lambda: load_closure_proxy_policy(policy_path, trusted_sha256=_sha256(policy_path)),
    )

    root = tmp_path / "canonical-store"
    identity_path = root / "data" / "clean" / "identity.parquet"
    monkeypatch.setattr(backtest_service, "IDENTITY_PATH", identity_path)
    monkeypatch.setattr(economics_inputs, "IDENTITY_PATH", identity_path)
    with CorporateActionCoverageStore(root) as store:
        for value in manifest["corporate_action_coverage"]:
            store.append(CorporateActionCoverage(**value))

    price_frame = prices if prices is not None else pd.read_csv(FIXTURE / "prices.csv")
    records_out, fund, benchmark, policy = _etf_economics_snapshot_inputs(
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


def test_etf_economics_artifact_checksum_is_required_and_bound_to_import_lineage(
    tmp_path,
) -> None:
    source = FIXTURE / "economics.csv"
    artifact = tmp_path / "economics.csv"
    imported = import_etf_economics_artifact(
        source,
        known_at=DECISION_TIME,
        dest=artifact,
    )
    disclosure_checksum = _sha256(FIXTURE / "synthetic_disclosure.txt")
    trusted_sources = {"synthetic-disclosure-ie00b5bmr087": disclosure_checksum}

    records = load_etf_economics_records(artifact, trusted_sources=trusted_sources)
    assert records
    assert all(item.artifact_sha256 == imported["sha256"] for item in records)
    assert all(item.artifact_source_path == str(source.resolve()) for item in records)
    assert all(item.artifact_known_at == imported["known_at"] for item in records)

    artifact.write_text(
        artifact.read_text(encoding="utf-8").replace(",0.0022,0.0022,", ",0.0122,0.0122,"),
        encoding="utf-8",
    )
    untrusted_records = load_etf_economics_records(artifact, trusted_sources=trusted_sources)
    assert untrusted_records == ()
    unavailable = _visible_panel(
        untrusted_records,
        None,
        None,
        None,
    )
    assert unavailable["status"] == "unavailable"
    assert "fund_economics" in unavailable["missing_evidence"]

    no_manifest = tmp_path / "unmanifested.csv"
    no_manifest.write_bytes(source.read_bytes())
    assert load_etf_economics_records(no_manifest, trusted_sources=trusted_sources) == ()


def test_etf_economics_real_shareclass_e2e(monkeypatch, tmp_path) -> None:
    records, fund, benchmark, policy, _prices = _load_production_inputs(monkeypatch, tmp_path)

    assert fund is not None and benchmark is not None
    assert records and all(item.artifact_sha256 is not None for item in records)
    panel = _visible_panel(records, fund, benchmark, policy)

    assert panel["instrument_id"] == INSTRUMENT_ID
    assert panel["status"] == "available", panel["missing_evidence"]
    assert panel["tracking_status"] == "available"
    assert panel["fund_metrics"]["ter"] == 0.0022
    assert panel["share_class_metrics"][INSTRUMENT_ID]["ocf"] == 0.0022
    assert all(item["artifact_sha256"] is not None for item in panel["history"])
    assert all(item["artifact_source_path"] is not None for item in panel["history"])
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


def test_etf_economics_snapshot_keeps_return_evidence_instrument_keyed(
    monkeypatch, tmp_path
) -> None:
    base = load_etf_economics_records(
        FIXTURE / "economics.csv",
        trusted_sha256=_sha256(FIXTURE / "economics.csv"),
    )
    records = tuple(
        replace(item, as_of="2026-01-07", known_at="2026-01-07")
        if item.scope == "fund"
        else item
        for item in base
    )
    later_fund = replace(
        next(item for item in base if item.scope == "fund"),
        instrument_id="synthetic:later-fund",
        as_of=DECISION_TIME,
        known_at=DECISION_TIME,
        benchmark_id="synthetic:later-benchmark",
    )
    records = records + (later_fund,)

    loaded, fund, benchmark, policy, _prices = _load_production_inputs(
        monkeypatch, tmp_path, records=records
    )
    assert fund is not None and INSTRUMENT_ID in fund
    assert fund[INSTRUMENT_ID].instrument_id == INSTRUMENT_ID
    assert benchmark is not None and BENCHMARK_ID in benchmark
    panel = _visible_panel(loaded, fund, benchmark, policy)
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


@pytest.mark.parametrize("evidence_case", ["stale_aum", "missing_fees", "ceased_class_merger"])
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
        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        closure_case = pd.read_csv(FIXTURE / manifest["closure_merger_case"]["file"]).to_dict("records")
        records = EtfEconomicsStore(
            tuple(
                item
                for item in base
                if not (item.scope == "share_class" and item.share_class_id == INSTRUMENT_ID)
            )
            + tuple(closure_case)
        ).records

    loaded, fund, benchmark, policy, _prices = _load_production_inputs(
        monkeypatch, tmp_path, prices=prices, records=records
    )
    panel = _visible_panel(loaded, fund, benchmark, policy)

    if evidence_case == "stale_aum":
        assert panel["fund_metrics"]["aum"] == 100_000_000.0
        assert panel["fund_metrics"]["aum_as_of"] == "2025-12-08T00:00:00Z"
        assert panel["fund_metrics"]["aum_status"] == "stale"
        assert "31 days old" in panel["fund_metrics"]["aum_warning"]
        assert any("AUM evidence is 31 days old" in warning for warning in panel["warnings"])
        assert panel["status"] == "partial"
        assert "aum" not in panel["closure_risk_proxy"]["factors"]
        assert "aum_stale" in panel["closure_risk_proxy"]["missing_factors"]
        assert panel["closure_risk_proxy"]["status"] == "unavailable"
    elif evidence_case == "missing_fees":
        assert panel["fund_metrics"]["ter"] is None
        assert panel["fund_metrics"]["ocf"] is None
        assert panel["fee_evidence_label"] == "unavailable"
    else:
        assert panel["tracking_status"] == "unavailable"
        assert panel["tracking_difference"] is None
        assert panel["matched_rows"] == 0
        assert "share_class_closed" in panel["missing_evidence"]
        class_metrics = panel["share_class_metrics"][INSTRUMENT_ID]
        assert class_metrics["entity_status"] == "merged"
        assert class_metrics["economic_quality_status"] == "closed_share_class"
        assert class_metrics["closure_effective_date"] == "2026-01-07T00:00:00Z"
        assert class_metrics["successor_instrument_id"] == "synthetic:successor-share-class"
        assert panel["instrument_id"] == INSTRUMENT_ID
        assert "successor_total_return" in panel["missing_evidence"]
        assert any("successor returns are not attributed" in warning for warning in panel["warnings"])


def test_closure_policy_is_trusted_only_through_import_lineage(tmp_path) -> None:
    source = Path(__file__).parent / "fixtures" / "economics" / "closure-policy.json"
    destination = tmp_path / "closure-policy.json"

    destination.write_bytes(source.read_bytes())
    assert load_closure_proxy_policy(destination) is None

    import_etf_economics_artifact(source, known_at="2026-01-02T00:00:00Z", dest=destination)
    assert load_closure_proxy_policy(destination) is not None

    destination.write_bytes(source.read_bytes() + b"\n ")
    assert load_closure_proxy_policy(destination) is None
