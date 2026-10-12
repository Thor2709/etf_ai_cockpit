from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.analysis.look_through import calculate_look_through
from etf_cockpit.app.pages.instrument_detail import instrument_detail_page
from etf_cockpit.application import instrument_detail_view
from etf_cockpit.application.market_views import load_etf_look_through
from etf_cockpit.application.snapshot_builder import build_snapshot


DECISION_TIME = "2026-07-15T16:00:00Z"
HOLDINGS_DATE = "2026-07-01"


def _holding(
    security: str,
    isin: str,
    weight: float,
    issuer: str,
    **reported: object,
) -> dict[str, object]:
    return {
        "security": security,
        "isin": isin,
        "weight": weight,
        "issuer": issuer,
        "company": issuer,
        "currency": "USD",
        "instrument_id": "TESTETF",
        "as_of": HOLDINGS_DATE,
        "source": "issuer",
        "source_id": "issuer:holdings-v1",
        "known_at": "2026-07-02T12:00:00Z",
        "revision": "revision-1",
        **reported,
    }


def _fundamental(identity: str, **values: object) -> dict[str, object]:
    return {
        "identity": identity,
        "currency": "USD",
        "as_of_date": "2026-06-30",
        "available_at": "2026-07-10T10:00:00Z",
        "source_id": f"fundamental:{identity}",
        **values,
    }


def _analyze(
    holdings: list[dict[str, object]],
    fundamentals: list[dict[str, object]] | None = None,
    **kwargs: object,
):
    return calculate_look_through(
        pd.DataFrame(holdings),
        instrument_id="TESTETF",
        decision_time=DECISION_TIME,
        constituent_fundamentals=pd.DataFrame(fundamentals or []),
        **kwargs,
    )


def test_explicit_holdings_exposures_include_industry_domicile_currency_and_factor_buckets() -> None:
    summary = _analyze(
        [
            _holding(
                "Alpha",
                "US0378331005",
                0.6,
                "alpha",
                industry="Software",
                domicile="US",
                economic_currency="USD",
                factor="quality",
                cap_bucket="large",
            ),
            _holding(
                "Beta",
                "US5949181045",
                0.4,
                "beta",
                industry="Semiconductors",
                domicile="NL",
                economic_currency="EUR",
                factor="value",
                cap_bucket="mid",
            ),
        ]
    )

    assert summary.exposures["industry"] == {"Semiconductors": pytest.approx(0.4), "Software": pytest.approx(0.6)}
    assert summary.exposures["domicile"] == {"NL": pytest.approx(0.4), "US": pytest.approx(0.6)}
    assert summary.exposures["economic_currency"] == {"EUR": pytest.approx(0.4), "USD": pytest.approx(0.6)}
    assert summary.exposures["factor"] == {"quality": pytest.approx(0.6), "value": pytest.approx(0.4)}
    assert summary.exposures["cap_bucket"] == {"large": pytest.approx(0.6), "mid": pytest.approx(0.4)}
    assert summary.exposure_coverage["industry"]["status"] == "available"
    assert summary.exposure_coverage["factor"]["coverage_fraction"] == 1.0


def test_conflicting_or_missing_reported_dimensions_are_unavailable_not_zero_filled() -> None:
    summary = _analyze(
        [
            _holding("Alpha", "US0378331005", 0.5, "alpha", industry="Software"),
            _holding("Alpha alternate line", "US0378331005", 0.5, "alpha", industry="Hardware"),
        ]
    )

    assert summary.exposures["industry"] == {}
    assert summary.exposure_coverage["industry"]["status"] == "unavailable"
    assert summary.exposure_coverage["industry"]["reason_code"] == "reported_dimension_evidence_unavailable"
    assert summary.exposure_coverage["industry"]["covered_weight"] == 0.0
    assert any("Conflicting reported industry" in item for item in summary.limitations)

    # Two listings of one company: only one reports a classification, so only
    # that listing's weight is evidenced, not the whole company weight.
    mixed = _analyze(
        [
            _holding("Alpha", "US0378331005", 0.5, "alpha", industry="Software", domicile="US"),
            _holding("Alpha alternate line", "US5949181045", 0.5, "alpha"),
        ]
    )
    assert mixed.exposures["issuer"] == {"alpha": pytest.approx(1.0)}
    assert mixed.exposures["industry"] == {"Software": pytest.approx(0.5)}
    assert mixed.exposures["domicile"] == {"US": pytest.approx(0.5)}
    assert mixed.exposure_coverage["industry"]["status"] == "partial"
    assert mixed.exposure_coverage["industry"]["covered_weight"] == pytest.approx(0.5)
    assert mixed.exposure_coverage["industry"]["coverage_fraction"] == pytest.approx(0.5)
    assert mixed.exposure_coverage["factor"]["status"] == "unavailable"


def test_valuation_and_quality_use_only_point_in_time_covered_constituents() -> None:
    summary = _analyze(
        [
            _holding("Alpha", "US0378331005", 0.5, "alpha"),
            _holding("Beta", "US5949181045", 0.5, "beta"),
        ],
        [
            _fundamental("alpha", pe_ratio=10.0, roic=0.12),
            _fundamental(
                "beta",
                pe_ratio=8.0,
                roic=0.3,
                available_at="2026-07-16T10:00:00Z",
            ),
        ],
        minimum_aggregate_coverage=0.5,
    )

    assert summary.calculated_metrics["pe_ratio"]["value"] == pytest.approx(10.0)
    assert [item["identity"] for item in summary.calculated_metrics["pe_ratio"]["contributors"]] == ["alpha"]
    assert [item["identity"] for item in summary.calculated_metrics["roic"]["contributors"]] == ["alpha"]
    assert summary.calculated_metrics["roic"]["value"] == pytest.approx(0.12)
    assert summary.fundamental_data_coverage["pe_ratio"]["covered_weight"] == pytest.approx(0.5)
    assert summary.fundamental_data_coverage["roic"]["coverage_fraction"] == pytest.approx(0.5)
    assert any("ROIC is an arithmetic weight-average" in item for item in summary.aggregation_conventions)


def test_missing_look_through_evidence_has_unavailable_metrics_without_values() -> None:
    result = load_etf_look_through(
        "TESTETF",
        decision_time=DECISION_TIME,
        analysis_date="2026-07-15",
        holdings_frame=pd.DataFrame(),
        fundamentals_frame=pd.DataFrame(),
    )

    assert result["status"] == "unavailable"
    for metric in ("pe_ratio", "roic"):
        assert result["calculated_metrics"][metric]["status"] == "unavailable"
        assert result["calculated_metrics"][metric]["value"] is None


def test_strict_identity_without_matching_alias_publishes_no_concentration_zeros() -> None:
    summary = _analyze(
        [_holding("Alpha", "US0378331005", 1.0, "alpha")],
        identity_map={"isin:us5949181045": "SEC-OTHER"},
        require_canonical_identity=True,
    )

    assert summary.status == "unavailable"
    assert summary.mapped_weight == 0.0
    concentration = summary.concentration
    assert concentration["status"] == "unavailable"
    assert concentration["reason_code"] == "look_through_evidence_unavailable"
    for name in ("top_5_share", "top_10_share", "top_5_share_covered", "hhi", "effective_number_of_holdings"):
        assert concentration[name] is None


def test_instrument_detail_loads_and_renders_the_safe_point_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = build_snapshot()
    instrument_id = str(snapshot.config.universe.etfs[0].id)
    captured: dict[str, object] = {}

    def fake_look_through(selected: str, **kwargs: object) -> dict[str, object]:
        captured.update({"instrument_id": selected, **kwargs})
        return {"instrument_id": selected, "status": "available", "execution_allowed": False}

    monkeypatch.setattr(instrument_detail_view, "load_etf_look_through", fake_look_through)
    holdings = pd.DataFrame([_holding("Alpha", "US0378331005", 1.0, "alpha")])
    fundamentals = pd.DataFrame([_fundamental("alpha", pe_ratio=10.0, roic=0.12)])
    model = instrument_detail_view.build_instrument_detail(
        snapshot,
        instrument_id,
        holdings=holdings,
        fundamentals=fundamentals,
    )

    assert model.sections["etf_look_through"]["status"] == "available"
    assert captured["instrument_id"] == instrument_id
    assert captured["holdings_frame"] is holdings
    assert captured["fundamentals_frame"] is fundamentals
    assert captured["analysis_date"] is not None

    page = instrument_detail_page(None, SimpleNamespace(snapshot=snapshot, selected_etf=instrument_id))
    visible_text: list[str] = []

    def collect(control: object) -> None:
        for name in ("value", "text"):
            value = getattr(control, name, None)
            if value:
                visible_text.append(str(value))
        content = getattr(control, "content", None)
        if content is not None:
            collect(content)
        for child in getattr(control, "controls", ()) or ():
            collect(child)

    collect(page)
    assert "ETF look-through" in visible_text
