from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.analysis.look_through import calculate_look_through
from etf_cockpit.app.pages.instrument_detail import _render_etf_look_through
from etf_cockpit.application import market_views
from etf_cockpit.application.market_views import load_etf_look_through
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.identity_master import IdentityMasterStore
from etf_cockpit.data.instrument_identity import IdentityClaim


DECISION_TIME = "2026-07-15T16:00:00Z"
HOLDINGS_DATE = "2026-07-01"
APPLE_ISIN = "US0378331005"
MICROSOFT_ISIN = "US5949181045"


def _holding(isin: str, weight: float, *, sector: str, industry: str | None = None, factor: str | None = None) -> dict[str, object]:
    return {
        "security": isin,
        "isin": isin,
        "weight": weight,
        "currency": "USD",
        "exposure_type": "security",
        "instrument_id": "TESTETF",
        "as_of": HOLDINGS_DATE,
        "source": "official_fixture",
        "source_id": "official:holdings:1",
        "known_at": "2026-07-02T12:00:00Z",
        "revision": "revision-1",
        "sector": sector,
        "industry": industry,
        "factor": factor,
    }


def _fundamental(instrument_id: str, pe_ratio: float, roic: float) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "identity": instrument_id,
        "pe_ratio": pe_ratio,
        "roic": roic,
        "currency": "USD",
        "as_of_date": "2026-06-30",
        "available_at": "2026-07-10T10:00:00Z",
        "source_id": f"fundamental:{instrument_id}",
    }


def _identity_claim(instrument_id: str, isin: str, source_id: str, available_at: str) -> IdentityClaim:
    return IdentityClaim(
        instrument_id=instrument_id,
        field="isin",
        value=isin,
        source="fixture",
        authority=SourceAuthority.OFFICIAL,
        source_id=source_id,
        valid_from="2024-01-01T00:00:00Z",
        available_at=available_at,
    )


def _install_identity_index(monkeypatch: pytest.MonkeyPatch, root: Path, ids: list[str]) -> None:
    identity_path = root / "data" / "clean" / "instrument_identity.parquet"
    monkeypatch.setattr(market_views, "IDENTITY_PATH", identity_path)
    original = market_views.pd.read_parquet

    def read_parquet(path: object, *args: object, **kwargs: object) -> pd.DataFrame:
        if Path(path) == identity_path:
            return pd.DataFrame({"instrument_id": ids})
        return original(path, *args, **kwargs)

    monkeypatch.setattr(market_views.pd, "read_parquet", read_parquet)


def test_pit_identity_master_mapping_uses_only_known_unambiguous_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate_ids = ["SEC-APPLE", "SEC-FUTURE"]
    _install_identity_index(monkeypatch, tmp_path, candidate_ids)
    with IdentityMasterStore(tmp_path) as master:
        master.append_claims(
            [
                _identity_claim("SEC-APPLE", APPLE_ISIN, "fixture:apple", "2026-07-02T00:00:00Z"),
                IdentityClaim("SEC-APPLE", "ticker", "AAPL", "fixture", SourceAuthority.OFFICIAL, "fixture:apple:ticker", valid_from="2024-01-01T00:00:00Z", available_at="2026-07-02T00:00:00Z"),
                IdentityClaim("SEC-APPLE", "exchange", "XNAS", "fixture", SourceAuthority.OFFICIAL, "fixture:apple:exchange", valid_from="2024-01-01T00:00:00Z", available_at="2026-07-02T00:00:00Z"),
                _identity_claim("SEC-FUTURE", MICROSOFT_ISIN, "fixture:future", "2026-07-16T00:00:00Z"),
            ]
        )
        projection = master.projection(
            "SEC-APPLE", effective_at=f"{HOLDINGS_DATE}T23:59:59.999999Z", decision_time=DECISION_TIME
        )
        assert projection["identity_status"] == "resolved", projection
        assert any(item["fields"].get("isin") == APPLE_ISIN for item in projection["identity_objects"]), projection

    pit_map, pit_evidence = market_views._pit_identity_map(
        analysis_date=HOLDINGS_DATE,
        decision_time=DECISION_TIME,
        holdings=pd.DataFrame([_holding(APPLE_ISIN, 1.0, sector="Technology")]),
        fundamentals=pd.DataFrame([_fundamental("SEC-APPLE", 20.0, 0.1)]),
    )
    assert pit_evidence["candidate_count"] == 2, pit_evidence
    assert pit_evidence["resolved_candidate_count"] == 1, pit_evidence
    assert pit_evidence["manual_review_candidate_count"] == 0, pit_evidence
    assert pit_map[f"isin:{APPLE_ISIN.casefold()}"] == "SEC-APPLE"
    assert f"isin:{MICROSOFT_ISIN.casefold()}" not in pit_map

    result = load_etf_look_through(
        "TESTETF",
        decision_time=DECISION_TIME,
        analysis_date=HOLDINGS_DATE,
        holdings_frame=pd.DataFrame([_holding(APPLE_ISIN, 1.0, sector="Technology")]),
        fundamentals_frame=pd.DataFrame([_fundamental("SEC-APPLE", 20.0, 0.1)]),
        require_canonical_identity=True,
    )

    assert result["mapped_weight"] == pytest.approx(1.0)
    assert result["status"] == "available", (result.get("lineage", {}).get("identity_resolution"), result.get("limitations"))
    assert result["concentration"]["top_holdings"][0]["identity"] == "sec-apple"
    assert result["lineage"]["identity_resolution"]["effective_at"] == f"{HOLDINGS_DATE}T23:59:59.999999+00:00"
    assert result["lineage"]["identity_resolution"]["decision_time"] == DECISION_TIME.replace("Z", "+00:00")
    assert result["lineage"]["identity_resolution"]["mapped_identity_count"] == 2

    candidate_ids.append("SEC-DUPLICATE")
    with IdentityMasterStore(tmp_path) as master:
        master.append_claims(
            [
                _identity_claim("SEC-DUPLICATE", APPLE_ISIN, "fixture:duplicate", "2026-07-02T00:00:00Z"),
                IdentityClaim("SEC-DUPLICATE", "ticker", "AAPL", "fixture", SourceAuthority.OFFICIAL, "fixture:duplicate:ticker", valid_from="2024-01-01T00:00:00Z", available_at="2026-07-02T00:00:00Z"),
                IdentityClaim("SEC-DUPLICATE", "exchange", "XNAS", "fixture", SourceAuthority.OFFICIAL, "fixture:duplicate:exchange", valid_from="2024-01-01T00:00:00Z", available_at="2026-07-02T00:00:00Z"),
            ]
        )
    ambiguous_map, ambiguity = market_views._pit_identity_map(
        analysis_date=HOLDINGS_DATE,
        decision_time=DECISION_TIME,
        holdings=pd.DataFrame([_holding(APPLE_ISIN, 1.0, sector="Technology")]),
        fundamentals=pd.DataFrame([_fundamental("SEC-APPLE", 20.0, 0.1)]),
    )
    assert f"isin:{APPLE_ISIN.casefold()}" not in ambiguous_map
    assert ambiguity["manual_review_candidate_count"] >= 1


def test_strict_supplied_identity_map_requires_dated_master_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supplied_map = {f"isin:{APPLE_ISIN.casefold()}": "SEC-APPLE"}
    for case, valid_from, available_at, expected_available in (
        ("missing_master", None, None, False),
        ("future_known", "2024-01-01T00:00:00Z", "2026-07-16T00:00:00Z", False),
        ("future_effective", "2026-07-16T00:00:00Z", "2026-07-02T00:00:00Z", False),
        ("missing_effective", None, "2026-07-02T00:00:00Z", False),
        ("missing_known", "2024-01-01T00:00:00Z", None, False),
        ("dated_prior", "2024-01-01T00:00:00Z", "2026-07-02T00:00:00Z", True),
    ):
        root = tmp_path / case
        with monkeypatch.context() as patch:
            _install_identity_index(patch, root, ["SEC-APPLE"])
            if case != "missing_master":
                with IdentityMasterStore(root) as master:
                    master.append_claims(
                        IdentityClaim(
                            "SEC-APPLE", field, value, "fixture",
                            SourceAuthority.OFFICIAL, f"fixture:apple:{field}",
                            valid_from=valid_from, available_at=available_at,
                        )
                        for field, value in (("isin", APPLE_ISIN), ("ticker", "AAPL"), ("exchange", "XNAS"))
                    )
            result = load_etf_look_through(
                "TESTETF",
                decision_time=DECISION_TIME,
                analysis_date=HOLDINGS_DATE,
                holdings_frame=pd.DataFrame([_holding(APPLE_ISIN, 1.0, sector="Technology")]),
                fundamentals_frame=pd.DataFrame([_fundamental("SEC-APPLE", 20.0, 0.1)]),
                identity_map=supplied_map,
                require_canonical_identity=True,
            )
        assert result["execution_allowed"] is False, case
        if case == "missing_master":
            assert result["status"] == "unavailable", case
            assert result["reason_code"] == "canonical_identity_master_unavailable", case
            assert "calculated_metrics" not in result, case
            continue
        evidence = result["lineage"]["identity_resolution"]
        assert evidence["decision_time"] == DECISION_TIME.replace("Z", "+00:00"), case
        assert result["status"] == ("available" if expected_available else "unavailable"), (case, result)
        assert result["mapped_weight"] == (1.0 if expected_available else 0.0), case
        assert result["unresolved_weight"] == (0.0 if expected_available else 1.0), case
        for metric, expected_value in (("pe_ratio", 20.0), ("roic", 0.1)):
            calculated = result["calculated_metrics"][metric]
            assert calculated["status"] == ("available" if expected_available else "unavailable"), case
            assert calculated["value"] == (expected_value if expected_available else None), case
        if expected_available:
            assert result["concentration"]["top_holdings"][0]["identity"] == "sec-apple", case
        else:
            assert result["concentration"]["status"] == "unavailable", case
            assert result["concentration"]["hhi"] is None, case
            assert result["lineage"]["unresolved_holdings"][0]["reason_code"] == "canonical_identity_mapping_unavailable_or_ambiguous", case


def test_low_coverage_and_conflicting_dimensions_withhold_aggregates() -> None:
    summary = calculate_look_through(
        pd.DataFrame(
            [
                _holding(APPLE_ISIN, 0.5, sector="Technology", industry="Software", factor="Value"),
                _holding(MICROSOFT_ISIN, 0.5, sector="Financials"),
            ]
        ),
        instrument_id="TESTETF",
        decision_time=DECISION_TIME,
        analysis_date=HOLDINGS_DATE,
        constituent_fundamentals=pd.DataFrame([_fundamental("SEC-APPLE", 20.0, 0.1)]),
        identity_map={f"isin:{APPLE_ISIN.casefold()}": "SEC-APPLE", f"isin:{MICROSOFT_ISIN.casefold()}": "SEC-MSFT"},
        require_canonical_identity=True,
    )

    assert summary.calculated_metrics["pe_ratio"]["status"] == "unavailable"
    assert summary.calculated_metrics["pe_ratio"]["value"] is None
    assert summary.calculated_metrics["pe_ratio"]["reason_code"] == "minimum_aggregate_coverage_not_met"
    assert summary.fundamental_data_coverage["pe_ratio"]["coverage_fraction"] == pytest.approx(0.5)
    assert summary.exposures["industry"]["Software"] == pytest.approx(0.5)
    assert summary.normalized_exposures["industry"] == {}
    assert summary.normalized_exposures["sector"] == {"Financials": 0.5, "Technology": 0.5}
    assert summary.exposure_coverage["industry"]["aggregate_status"] == "partial"

    underreported = calculate_look_through(
        pd.DataFrame([_holding(APPLE_ISIN, 0.5, sector="Technology", industry="Software")]),
        instrument_id="TESTETF",
        decision_time=DECISION_TIME,
        analysis_date=HOLDINGS_DATE,
        constituent_fundamentals=pd.DataFrame([_fundamental("SEC-APPLE", 20.0, 0.1)]),
        identity_map={f"isin:{APPLE_ISIN.casefold()}": "SEC-APPLE"},
        require_canonical_identity=True,
    )
    assert underreported.fundamental_data_coverage["pe_ratio"]["coverage_fraction"] == pytest.approx(1.0)
    assert underreported.fundamental_data_coverage["pe_ratio"]["portfolio_coverage_fraction"] == pytest.approx(0.5)
    assert underreported.calculated_metrics["pe_ratio"]["status"] == "unavailable"
    assert underreported.concentration["status"] == "partial"
    assert underreported.normalized_exposures["sector"] == {}

    # A valid nondefault threshold is honoured; invalid thresholds fail closed.
    relaxed = calculate_look_through(
        pd.DataFrame([_holding(APPLE_ISIN, 1.0, sector="Technology")]),
        instrument_id="TESTETF",
        decision_time=DECISION_TIME,
        analysis_date=HOLDINGS_DATE,
        constituent_fundamentals=pd.DataFrame([_fundamental("SEC-APPLE", 20.0, 0.1)]),
        identity_map={f"isin:{APPLE_ISIN.casefold()}": "SEC-APPLE"},
        require_canonical_identity=True,
        minimum_aggregate_coverage=0.99,
    )
    assert relaxed.minimum_aggregate_coverage == pytest.approx(0.99)
    assert relaxed.calculated_metrics["pe_ratio"]["value"] == pytest.approx(20.0)
    for bad in (-0.1, 1.5, float("nan"), True, "0.8"):
        rejected = calculate_look_through(
            pd.DataFrame([_holding(APPLE_ISIN, 1.0, sector="Technology")]),
            instrument_id="TESTETF",
            decision_time=DECISION_TIME,
            analysis_date=HOLDINGS_DATE,
            minimum_aggregate_coverage=bad,
        )
        assert rejected.status == "unavailable"
        assert rejected.calculated_metrics["pe_ratio"]["value"] is None
        assert any("Minimum aggregate coverage" in item for item in rejected.limitations)

    # Mixed evidence on one ISIN covers only the reporting weight.
    mixed = calculate_look_through(
        pd.DataFrame(
            [
                {**_holding(APPLE_ISIN, 0.5, sector="Technology", industry="Software"), "security": "Apple Inc. A"},
                {**_holding(APPLE_ISIN, 0.5, sector="Technology"), "security": "Apple Inc. B"},
            ]
        ),
        instrument_id="TESTETF",
        decision_time=DECISION_TIME,
        analysis_date=HOLDINGS_DATE,
        identity_map={f"isin:{APPLE_ISIN.casefold()}": "SEC-APPLE"},
        require_canonical_identity=True,
    )

    assert mixed.mapped_weight == pytest.approx(1.0)
    assert mixed.exposures["industry"] == {"Software": pytest.approx(0.5)}
    assert mixed.exposure_coverage["industry"]["aggregate_status"] == "partial"
    assert mixed.normalized_exposures["industry"] == {}

    # Conflicting dimension claims on identical rows are excluded in any row order.
    conflict_rows = [
        {**_holding(APPLE_ISIN, 1.0, sector="Technology", industry="Software")},
        {**_holding(APPLE_ISIN, 1.0, sector="Technology", industry="Hardware")},
    ]
    for rows in (conflict_rows, conflict_rows[::-1]):
        conflicted = calculate_look_through(
            pd.DataFrame(rows),
            instrument_id="TESTETF",
            decision_time=DECISION_TIME,
            analysis_date=HOLDINGS_DATE,
            identity_map={f"isin:{APPLE_ISIN.casefold()}": "SEC-APPLE"},
            require_canonical_identity=True,
        )
        assert conflicted.exposures["industry"] == {}
        assert conflicted.mapped_weight == pytest.approx(1.0)
        assert any("Conflicting reported industry" in item for item in conflicted.limitations)

    # Below the coverage gate normalised concentration is withheld; gross weights stay.
    assert underreported.concentration["hhi"] is None
    assert underreported.concentration["effective_number_of_holdings"] is None
    assert underreported.concentration["top_5_share_covered"] is None
    assert underreported.concentration["top_5_share"] == pytest.approx(0.5)
    assert underreported.concentration["coverage_fraction"] == pytest.approx(0.5)


def test_full_coverage_exposes_dimensions_and_currency_evidence_gates_metrics() -> None:
    summary = calculate_look_through(
        pd.DataFrame(
            [
                _holding(APPLE_ISIN, 0.5, sector="Technology", industry="Software", factor="Value"),
                _holding(MICROSOFT_ISIN, 0.5, sector="Financials", industry="Software", factor="Growth"),
            ]
        ),
        instrument_id="TESTETF",
        decision_time=DECISION_TIME,
        analysis_date=HOLDINGS_DATE,
        constituent_fundamentals=pd.DataFrame(
            [_fundamental("SEC-APPLE", 10.0, 0.1), _fundamental("SEC-MSFT", 20.0, 0.2)]
        ),
        identity_map={f"isin:{APPLE_ISIN.casefold()}": "SEC-APPLE", f"isin:{MICROSOFT_ISIN.casefold()}": "SEC-MSFT"},
        require_canonical_identity=True,
    )

    assert summary.minimum_aggregate_coverage == pytest.approx(0.8)
    assert summary.calculated_metrics["pe_ratio"]["status"] == "available"
    assert summary.calculated_metrics["pe_ratio"]["value"] == pytest.approx(1 / (0.5 / 10 + 0.5 / 20))
    assert summary.calculated_metrics["roic"]["value"] == pytest.approx(0.15)
    assert summary.normalized_exposures["industry"] == {"Software": 1.0}
    assert summary.normalized_exposures["factor"] == {"Growth": 0.5, "Value": 0.5}
    assert summary.lineage["exposure_evidence"]["factor"]["label"] == "provider_reported_holdings_dimension"

    # HL1 (#953): P/E and ROIC are dimensionless, so mismatched, missing or ambiguous currency evidence
    # no longer withholds them.
    holdings = pd.DataFrame([_holding(APPLE_ISIN, 1.0, sector="Technology")])
    mixed_currency = pd.DataFrame(
        [
            _holding(APPLE_ISIN, 0.5, sector="Technology"),
            {**_holding(MICROSOFT_ISIN, 0.5, sector="Technology"), "currency": "EUR"},
        ]
    )
    cases = {
        "mismatch": (holdings, {**_fundamental("SEC-APPLE", 10.0, 0.1), "currency": "EUR"}),
        "missing": (holdings, {**_fundamental("SEC-APPLE", 10.0, 0.1), "currency": ""}),
        "ambiguous": (mixed_currency, _fundamental("SEC-APPLE", 10.0, 0.1)),
    }
    for name, (frame, fact) in cases.items():
        result = calculate_look_through(
            frame,
            instrument_id="TESTETF",
            decision_time=DECISION_TIME,
            analysis_date=HOLDINGS_DATE,
            constituent_fundamentals=pd.DataFrame([fact]),
            identity_map={
                f"isin:{APPLE_ISIN.casefold()}": "SEC-APPLE",
                f"isin:{MICROSOFT_ISIN.casefold()}": "SEC-APPLE",
            },
            require_canonical_identity=True,
        )
        assert result.calculated_metrics["pe_ratio"]["value"] == pytest.approx(10.0), name
        assert result.calculated_metrics["roic"]["value"] == pytest.approx(0.1), name

    # Missing holding currency on any listing or merged row withholds the metrics.
    missing_listing = pd.DataFrame(
        [
            _holding(APPLE_ISIN, 0.5, sector="Technology"),
            {**_holding(MICROSOFT_ISIN, 0.5, sector="Technology"), "currency": None},
        ]
    )
    missing_merged_row = pd.DataFrame(
        [
            {**_holding(APPLE_ISIN, 0.5, sector="Technology"), "security": "Apple Inc. A"},
            {**_holding(APPLE_ISIN, 0.5, sector="Technology"), "security": "Apple Inc. B", "currency": None},
        ]
    )
    for name, frame in {"listing": missing_listing, "merged_row": missing_merged_row}.items():
        result = calculate_look_through(
            frame,
            instrument_id="TESTETF",
            decision_time=DECISION_TIME,
            analysis_date=HOLDINGS_DATE,
            constituent_fundamentals=pd.DataFrame([_fundamental("SEC-APPLE", 10.0, 0.1)]),
            identity_map={
                f"isin:{APPLE_ISIN.casefold()}": "SEC-APPLE",
                f"isin:{MICROSOFT_ISIN.casefold()}": "SEC-APPLE",
            },
            require_canonical_identity=True,
        )
        assert result.calculated_metrics["pe_ratio"]["value"] == pytest.approx(10.0), name
        assert result.calculated_metrics["roic"]["value"] == pytest.approx(0.1), name
        assert result.fundamental_data_coverage["pe_ratio"]["covered_weight"] == pytest.approx(1.0), name


def test_missing_canonical_identity_evidence_is_unavailable_or_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_identity_index(monkeypatch, tmp_path, ["SEC-APPLE"])
    result = load_etf_look_through(
        "TESTETF",
        decision_time=DECISION_TIME,
        holdings_frame=pd.DataFrame([_holding(APPLE_ISIN, 1.0, sector="Technology")]),
        fundamentals_frame=pd.DataFrame([_fundamental("SEC-APPLE", 20.0, 0.1)]),
        require_canonical_identity=True,
    )

    assert result["status"] == "unavailable"
    assert result["reason_code"] == "canonical_identity_master_unavailable"
    assert "calculated_metrics" not in result
    assert result["execution_allowed"] is False

    # Unmapped canonical identity weight stays unresolved.
    unmapped = calculate_look_through(
        pd.DataFrame(
            [
                _holding(APPLE_ISIN, 0.6, sector="Technology"),
                _holding(MICROSOFT_ISIN, 0.4, sector="Technology"),
            ]
        ),
        instrument_id="TESTETF",
        decision_time=DECISION_TIME,
        analysis_date=HOLDINGS_DATE,
        identity_map={f"isin:{APPLE_ISIN.casefold()}": "SEC-APPLE"},
        require_canonical_identity=True,
    )

    assert unmapped.mapped_weight == pytest.approx(0.6)
    assert unmapped.unresolved_weight == pytest.approx(0.4)
    assert unmapped.reconciliation_delta == pytest.approx(0.0)
    assert unmapped.lineage["unresolved_holdings"][0]["identity"] == f"isin:{MICROSOFT_ISIN}"
    assert unmapped.lineage["unresolved_holdings"][0]["reason_code"] == "canonical_identity_mapping_unavailable_or_ambiguous"
    assert unmapped.concentration["status"] == "partial"

    # Strict identity unavailability wins over an overreported total.
    overreported = calculate_look_through(
        pd.DataFrame(
            [_holding(APPLE_ISIN, 0.5, sector="Technology"), _holding(MICROSOFT_ISIN, 0.505, sector="Technology")]
        ),
        instrument_id="TESTETF",
        decision_time=DECISION_TIME,
        analysis_date=HOLDINGS_DATE,
        identity_map={"isin:unrelated": "SEC-OTHER"},
        require_canonical_identity=True,
    )
    assert overreported.total_weight_status == "over_100"
    assert overreported.status == "unavailable"
    assert overreported.mapped_weight == 0.0


def test_detail_look_through_panel_shows_coverage_and_drill_down() -> None:
    summary = calculate_look_through(
        pd.DataFrame([_holding(APPLE_ISIN, 1.0, sector="Technology", industry="Software", factor="Value")]),
        instrument_id="TESTETF",
        decision_time=DECISION_TIME,
        analysis_date=HOLDINGS_DATE,
        identity_map={f"isin:{APPLE_ISIN.casefold()}": "SEC-APPLE"},
        require_canonical_identity=True,
    )
    card = _render_etf_look_through(
        {
            **summary.__dict__,
            "calculated_metrics": {"pe_ratio": {"status": "unavailable", "value": None, "method": "covered earnings yield"}},
            "fundamental_data_coverage": {"pe_ratio": {"covered_weight": 0.0, "mapped_weight": 1.0, "coverage_fraction": 0.0}},
        }
    )

    controls = list(_walk_controls(card))
    labels = {control.data.get("label") for control in controls if isinstance(getattr(control, "data", None), dict)}
    assert card.key == "instrument-detail.etf-look-through"
    assert "Exposure buckets, denominators and coverage" in labels
    assert "Sources, formulas, lineage, limitations and unavailable reasons" in labels


def _walk_controls(control: object):
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk_controls(content)
