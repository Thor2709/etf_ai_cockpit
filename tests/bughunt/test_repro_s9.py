"""Slice 9 reproduction tests."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from etf_cockpit.analysis import sparebank
from etf_cockpit.application import financial_institution_views, valuation_views
from etf_cockpit.application.analysis_depth import AnalysisTimingRecord, append_timing_records
from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.contracts import PageRequest
from etf_cockpit.application.onboarding_profile import (
    OnboardingProfile,
    _merge_records,
    _onboarding_records,
)
from etf_cockpit.application.overlap import build_direct_overlap_view
from etf_cockpit.application.portfolio_sandbox import _resolve_capability_decision
from etf_cockpit.data.classification import (
    ClassificationEvidence,
    _context_projection,
    resolve_instrument_context,
)
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.universe_store import UniverseRecord
from etf_cockpit.governance.product_scope import load_strategy_scope


def test_s9_01_onboarding_preserves_verified_identity():
    old = UniverseRecord(
        "MSFT",
        "Microsoft",
        isin="US5949181045",
        isin_status="verified",
        ticker="MSFT",
        currency="USD",
        tier="primary",
    )
    profile = OnboardingProfile("EUR", "Europe", ("stock",), "medium", "1M", tickers=("MSFT",))
    merged = _merge_records((old,), _onboarding_records(profile, ()))
    assert merged[0].isin == old.isin
    assert merged[0].isin_status == "verified"
    assert merged[0].currency == "USD"
    assert merged[0].tier == "primary"


def test_s9_02_missing_stock_evidence_stays_unavailable():
    policy = load_strategy_scope().policy
    configured = SimpleNamespace(instrument_type="stock")
    decision, _ = _resolve_capability_decision({}, configured, policy)
    assert decision is None or decision.state == "unavailable"


def test_s9_03_bank_rejects_price_known_after_cutoff(monkeypatch):
    quotes = pd.DataFrame([
        {
            "instrument_id": "MING",
            "date": "2025-03-03",
            "close": 200.0,
            "currency": "NOK",
            "known_at": "2025-03-04T17:00:00Z",
        }
    ])
    ec = {
        "instrument_id": "MING",
        "known_at": "2025-01-01T00:00:00Z",
        "facts": {},
        "valuation_assumptions": {"currency": "NOK"},
    }
    monkeypatch.setattr(
        financial_institution_views,
        "_read_json_artifact",
        lambda root, name, **kw: ec if name == "ec_facts.json" else {},
    )
    monkeypatch.setattr(
        financial_institution_views,
        "_read_financial_statement_frame",
        lambda *a, **kw: pd.DataFrame(),
    )
    monkeypatch.setattr(
        financial_institution_views,
        "_financial_metric_facts",
        lambda *a, **kw: [object()],
    )
    monkeypatch.setattr(
        financial_institution_views,
        "build_financial_institution_projection",
        lambda *a, **kw: SimpleNamespace(metrics=()),
    )
    monkeypatch.setattr(
        financial_institution_views,
        "verify_financial_projection",
        lambda _: {},
    )
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    monkeypatch.setattr("etf_cockpit.data.duckdb_store.load_prices", lambda *a: quotes)
    probe = Mock(return_value=SimpleNamespace(routing=SimpleNamespace(applies=False)))
    monkeypatch.setattr(sparebank, "analyse_sparebank_ec", probe)
    financial_institution_views.load_financial_institution_projection(
        "MING",
        decision_time="2025-03-03T23:59:59Z",
        context=SimpleNamespace(sector="financials"),
    )
    assert probe.call_args.kwargs["price"] is None


def test_s9_04_stock_context_excludes_future_classification():
    values = {
        "instrument_type": "stock",
        "asset_class": "equity",
        "sector": "technology",
        "operating_country": "US",
    }
    evidence = tuple(
        ClassificationEvidence(
            evidence_id=f"X:{k}",
            instrument_id="X",
            field=k,
            value=value,
            source="fixture",
            authority=SourceAuthority.OFFICIAL,
            source_id=f"fixture:{k}",
            confidence=0.99,
            valid_from="2025-06-01T00:00:00Z",
            available_at="2025-06-02T00:00:00Z",
        )
        for k, value in values.items()
    )

    def classify(instrument_id, **kw):
        c = resolve_instrument_context(
            evidence,
            instrument_id=instrument_id,
            decision_time=kw.get("decision_time"),
            effective_at=kw.get("effective_at"),
        )
        return _context_projection(c, min_leaf_confidence=0.75)

    with (
        patch.object(valuation_views, "load_classification_projection", side_effect=classify),
        patch.object(valuation_views, "load_peer_cohort_projection", return_value={"status": "unavailable"}),
        patch("etf_cockpit.data.stock_research.load_stock_research_frame", return_value=pd.DataFrame()),
        patch.object(valuation_views, "load_valuation_market_inputs", return_value={"status": "unavailable"}),
    ):
        result = valuation_views.load_stock_research_context("X", decision_time="2025-03-01T00:00:00Z")
    assert result["classification_status"] != "available"


def test_s9_05_overlap_uses_snapshot_knowledge_cutoff():
    rows = pd.DataFrame([
        {
            "instrument_id": i,
            "as_of": "2025-02-28",
            "known_at": "2025-06-01T00:00:00Z",
            "isin": "US5949181045",
            "weight": 1.0,
            "source_id": "issuer",
            "authority": "issuer",
            "completeness": "full",
        }
        for i in ("A", "B")
    ])
    snapshot = SimpleNamespace(data_report=SimpleNamespace(as_of_date="2025-03-01"), holdings=pd.DataFrame())
    report = build_direct_overlap_view(snapshot, ["A", "B"], holdings=rows)
    assert all(item.status == "missing" for item in report.coverage)
    assert report.pairs[0].observed_overlap_weight is None


def test_s9_06_timing_append_failure_preserves_history(tmp_path, monkeypatch):
    old = AnalysisTimingRecord("old", "quick", "stage", "identity_gate", 1.0, "warm")
    path = append_timing_records(tmp_path, [old])
    before = path.read_bytes()

    def interrupted_write(self, destination, **kwargs):
        destination.write_bytes(b"PAR1")
        raise OSError("disk full after truncation")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", interrupted_write)
    new = AnalysisTimingRecord("new", "quick", "stage", "identity_gate", 2.0, "warm")
    with pytest.raises(OSError):
        append_timing_records(tmp_path, [new])
    assert path.read_bytes() == before


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="S9-07: Instrument queries silently truncate universes at 500 entries",
)
def test_s9_07_instruments_page_after_first_500():
    items = tuple(SimpleNamespace(id=f"I{i:04}", name=str(i), ticker=str(i)) for i in range(501))
    snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=items)))
    api = LocalApplicationApi(lambda: snapshot, scheduler=object())
    page = api.get_instruments(PageRequest(offset=500, limit=1))
    assert page.total == 501
    assert len(page.items) == 1
    assert page.items[0].instrument_id == "I0500"
