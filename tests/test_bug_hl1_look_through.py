"""HL1 (#953): ETF holdings look-through point-in-time, identity and currency regressions."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.analysis.decision.etf import compose_etf_decision
from etf_cockpit.analysis.look_through import calculate_look_through
from etf_cockpit.data.fund_adapters import parse_sec_nport_archive
from etf_cockpit.data.fund_holdings import _read_holdings_import
from etf_cockpit.features.overlap import _choose_source_group
from etf_cockpit.portfolio.exposure_cube import build_portfolio_exposure_cube


DECISION = "2026-07-15T16:00:00Z"
APPLE = "US0378331005"
MICROSOFT = "US5949181045"
AMAZON = "US0231351067"
APPLE_UK = "GB0000000009"


def _holding(
    security: str,
    isin: str,
    weight: float,
    issuer: str,
    *,
    currency: str = "USD",
    as_of: str = "2026-07-01",
    known_at: str | None = "2026-07-02T12:00:00Z",
    source: str = "issuer",
    source_id: str = "issuer:holdings-v1",
    authority: str | None = None,
    instrument_id: str | None = "TESTETF",
    **extra: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "security": security,
        "isin": isin,
        "weight": weight,
        "issuer": issuer,
        "company": issuer,
        "currency": currency,
        "exposure_type": "security",
        "as_of": as_of,
        "source": source,
        "source_id": source_id,
        "revision": "revision-1",
    }
    if instrument_id is not None:
        row["instrument_id"] = instrument_id
    if known_at is not None:
        row["known_at"] = known_at
    if authority is not None:
        row["authority"] = authority
    row.update(extra)
    return row


def _fundamental(identity: str, **values: object) -> dict[str, object]:
    row: dict[str, object] = {
        "identity": identity,
        "currency": "USD",
        "as_of_date": "2026-06-30",
        "available_at": "2026-07-10T10:00:00Z",
        "source_id": f"fundamental:{identity}:{values.get('available_at', 'a')}",
    }
    row.update(values)
    return row


def _run(rows: list[dict[str, object]], fundamentals: list[dict[str, object]] | None = None, **kwargs):
    kwargs.setdefault("decision_time", DECISION)
    kwargs.setdefault("instrument_id", "TESTETF")
    return calculate_look_through(
        pd.DataFrame(rows),
        constituent_fundamentals=pd.DataFrame(fundamentals or []),
        **kwargs,
    )


# --- point-in-time holdings -------------------------------------------------


def test_a011_n001_missing_known_at_fails_closed() -> None:
    summary = _run([_holding("Apple", APPLE, 1.0, "apple", known_at=None)])
    assert summary.status == "unavailable"
    assert summary.concentration["hhi"] is None
    assert any("known" in item.lower() for item in summary.limitations)


@pytest.mark.parametrize("known_at", ["2026-06-30T23:59:00Z", "2026-07-20T00:00:00Z"])
def test_a011_n006_and_future_known_holdings_are_rejected(known_at: str) -> None:
    summary = _run([_holding("Apple", APPLE, 1.0, "apple", known_at=known_at)])
    assert summary.status == "unavailable"
    assert summary.mapped_weight == 0.0


def test_b022_future_known_snapshot_does_not_hide_older_known_one() -> None:
    older = _holding("Apple", APPLE, 1.0, "apple", as_of="2026-06-01", known_at="2026-06-02T00:00:00Z", source_id="s-old")
    newer = _holding("Apple", APPLE, 1.0, "apple", as_of="2026-07-10", known_at="2026-07-30T00:00:00Z", source_id="s-new")
    summary = _run([older, newer])
    assert summary.holdings_date == "2026-06-01"
    assert summary.lineage["known_at"].startswith("2026-06-02")


def test_a111_n003_fundamentals_use_known_at_not_available_at() -> None:
    rows = [_holding("Apple", APPLE, 1.0, "apple")]
    future_known = _fundamental("apple", pe_ratio=20.0, roic=0.2, known_at="2026-07-30T00:00:00Z")
    summary = _run(rows, [future_known])
    assert summary.calculated_metrics["pe_ratio"]["status"] == "unavailable"
    assert summary.calculated_metrics["roic"]["status"] == "unavailable"
    past_known = _fundamental("apple", pe_ratio=20.0, roic=0.2, known_at="2026-07-10T10:00:00Z")
    assert _run(rows, [past_known]).calculated_metrics["pe_ratio"]["status"] == "available"


# --- stale holdings in the ETF decision --------------------------------------


def _drivers(look_through: dict[str, object]):
    from test_decision_etf import _context  # type: ignore[import-not-found]

    assessment = compose_etf_decision(
        "target", _context("target"), DECISION, look_through=look_through, strict_exposure_peers=False
    )
    return {item.metric_id: item for item in assessment.drivers}


def _stale_summary(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "status": "available",
        "freshness": "fresh",
        "holdings_date": "2026-07-01",
        "decision_time": DECISION,
        "source_id": "issuer:holdings-v1",
        "mapped_weight": 1.0,
        "reported_total_weight": 1.0,
        "provider_coverage": 1.0,
        "unresolved_weight": 0.0,
        "lineage": {"known_at": "2026-07-02T12:00:00Z", "authority": 1.0, "confidence": 1.0},
        "concentration": {"hhi": 0.3, "top_10_share": 0.9},
        "exposures": {"currency": {"USD": 0.5, "GBP": 0.5}},
        "calculated_metrics": {},
        "fundamental_data_coverage": {},
    }
    base.update(overrides)
    return base


def test_b011_n001_stale_holdings_make_vehicle_metrics_unavailable() -> None:
    fresh = _drivers(_stale_summary())
    assert fresh["look_through_hhi"].raw_value == pytest.approx(0.3)
    for overrides in ({"status": "stale", "freshness": "stale"}, {"freshness": "stale"}, {"status": "invalid"}):
        drivers = _drivers(_stale_summary(**overrides))
        for metric_id in ("look_through_hhi", "look_through_top_10_share", "currency_mismatch"):
            assert drivers[metric_id].raw_value is None, (overrides, metric_id)


def test_b011_n001_future_known_holdings_make_vehicle_metrics_unavailable() -> None:
    drivers = _drivers(_stale_summary(lineage={"known_at": "2026-08-01T00:00:00Z"}))
    assert drivers["look_through_hhi"].raw_value is None
    drivers = _drivers(_stale_summary(lineage={"known_at": "2026-06-01T00:00:00Z"}))
    assert drivers["look_through_hhi"].raw_value is None  # known before as-of is invalid chronology


# --- parent scoping and source selection --------------------------------------


def test_a111_n001_legacy_etf_id_only_rows_never_mix_two_etfs() -> None:
    rows = [
        {**_holding("Apple", APPLE, 0.5, "apple", instrument_id=None), "etf_id": "TESTETF"},
        {**_holding("Microsoft", MICROSOFT, 0.5, "microsoft", instrument_id=None), "etf_id": "OTHERETF"},
    ]
    summary = _run(rows)
    assert summary.reported_total_weight == pytest.approx(0.5)
    assert set(summary.exposures["issuer"]) == {"apple"}
    other = _run(rows, instrument_id="OTHERETF")
    assert other.reported_total_weight == pytest.approx(0.5)
    assert set(other.exposures["issuer"]) == {"microsoft"}


def test_a111_n001_conflicting_parent_columns_are_excluded() -> None:
    rows = [
        {**_holding("Apple", APPLE, 0.5, "apple"), "etf_id": "OTHERETF"},
        _holding("Microsoft", MICROSOFT, 0.5, "microsoft"),
    ]
    summary = _run(rows)
    assert summary.reported_total_weight == pytest.approx(0.5)


def test_a011_n002_official_sec_outranks_vendor_in_overlap_ranking() -> None:
    vendor = pd.DataFrame([{"authority": "vendor", "weight": 0.5}])
    official = pd.DataFrame([{"authority": "official", "weight": 0.5}])
    chosen, _ = _choose_source_group([("a-vendor", vendor), ("b-official", official)])
    assert chosen is not None and chosen[0] == "b-official"


def test_a011_n002_official_outranks_vendor_in_look_through() -> None:
    vendor = _holding("Apple", APPLE, 0.6, "apple", source="yfinance", source_id="vendor-1", authority="vendor")
    official = _holding("Apple", APPLE, 1.0, "apple", source="sec_nport", source_id="a-official", authority="official")
    summary = _run([vendor, official])
    assert summary.source_ids == ("a-official",)
    assert summary.reported_total_weight == pytest.approx(1.0)


def test_a011_n007_selection_is_authority_first_not_vintage_first() -> None:
    older_issuer = _holding(
        "Apple", APPLE, 1.0, "apple", as_of="2026-06-20", known_at="2026-06-21T00:00:00Z",
        source_id="issuer-old", authority="issuer",
    )
    newer_vendor = _holding(
        "Apple", APPLE, 0.6, "apple", as_of="2026-07-10", known_at="2026-07-11T00:00:00Z",
        source="yfinance", source_id="vendor-new", authority="vendor",
    )
    summary = _run([older_issuer, newer_vendor])
    assert summary.source_ids == ("issuer-old",)
    assert summary.holdings_date == "2026-06-20"


def test_a111_n002_explicit_source_does_not_combine_separate_snapshots() -> None:
    first = _holding("Apple", APPLE, 0.5, "apple", source_id="acq-1", known_at="2026-07-02T00:00:00Z")
    second = _holding("Microsoft", MICROSOFT, 0.5, "microsoft", source_id="acq-2", known_at="2026-07-03T00:00:00Z")
    summary = _run([first, second], source="issuer")
    assert summary.reported_total_weight == pytest.approx(0.5)
    assert len(summary.source_ids) == 1


def test_a111_n004_lineage_known_at_comes_from_selected_group() -> None:
    issuer = _holding("Apple", APPLE, 1.0, "apple", source_id="issuer-1", authority="issuer", known_at="2026-07-02T00:00:00Z")
    vendor = _holding(
        "Apple", APPLE, 0.6, "apple", source="yfinance", source_id="vendor-1", authority="vendor",
        known_at="2026-07-09T00:00:00Z",
    )
    summary = _run([issuer, vendor])
    assert summary.source_ids == ("issuer-1",)
    assert summary.lineage["known_at"].startswith("2026-07-02")
    assert summary.source_ids == ("issuer-1",)


def test_d04_c2_n001_several_vintages_are_not_summed_above_100() -> None:
    first = _holding("Apple", APPLE, 0.6, "apple", source_id="vintage-1", known_at="2026-07-02T00:00:00Z")
    second = _holding("Microsoft", MICROSOFT, 0.6, "microsoft", source_id="vintage-2", known_at="2026-07-03T00:00:00Z")
    summary = _run([first, second])
    assert summary.reported_total_weight <= 0.6 + 1e-9 or summary.status == "unavailable"
    assert summary.status != "overreported"


# --- fundamentals and currency ------------------------------------------------


def test_a011_n003_contradictory_typed_identity_is_not_matched_on_issuer_name() -> None:
    rows = [_holding("Apple", APPLE, 1.0, "apple")]
    contradictory = _fundamental("apple", isin=AMAZON, pe_ratio=20.0, roic=0.2)
    summary = _run(rows, [contradictory])
    assert summary.calculated_metrics["pe_ratio"]["status"] == "unavailable"
    assert summary.calculated_metrics["roic"]["status"] == "unavailable"
    matching = _fundamental("apple", isin=APPLE, pe_ratio=20.0, roic=0.2)
    assert _run(rows, [matching]).calculated_metrics["pe_ratio"]["status"] == "available"


def test_a011_n004_newer_roic_only_record_does_not_suppress_earlier_pe() -> None:
    rows = [_holding("Apple", APPLE, 1.0, "apple")]
    earlier = _fundamental("apple", pe_ratio=20.0, as_of_date="2026-03-31", available_at="2026-05-01T00:00:00Z")
    newer = _fundamental("apple", roic=0.15, as_of_date="2026-06-30", available_at="2026-07-10T00:00:00Z")
    summary = _run(rows, [earlier, newer])
    assert summary.calculated_metrics["pe_ratio"]["status"] == "available"
    assert summary.calculated_metrics["pe_ratio"]["value"] == pytest.approx(20.0)
    assert summary.calculated_metrics["roic"]["value"] == pytest.approx(0.15)


@pytest.mark.parametrize("fact_currency", ["EUR", "GBP", ""])
def test_a011_n005_b011_n003_currency_mismatch_keeps_dimensionless_metrics(fact_currency: str) -> None:
    rows = [_holding("Apple", APPLE, 1.0, "apple", currency="USD")]
    fundamentals = [_fundamental("apple", pe_ratio=20.0, roic=0.2, currency=fact_currency)]
    summary = _run(rows, fundamentals)
    assert summary.calculated_metrics["pe_ratio"]["status"] == "available"
    assert summary.calculated_metrics["roic"]["status"] == "available"


def test_b011_n002_same_issuer_listings_keep_usd_gbp_split() -> None:
    rows = [
        _holding("Apple US", APPLE, 0.6, "apple", currency="USD"),
        _holding("Apple UK", APPLE_UK, 0.4, "apple", currency="GBP"),
    ]
    summary = _run(rows)
    assert summary.exposures["currency"] == {"GBP": pytest.approx(0.4), "USD": pytest.approx(0.6)}
    assert summary.exposure_coverage["currency"]["status"] == "available"
    assert summary.normalized_exposures["currency"] == {"GBP": pytest.approx(0.4), "USD": pytest.approx(0.6)}


def test_b011_n002_split_reaches_currency_mismatch_metric() -> None:
    rows = [
        _holding("Apple US", APPLE, 0.6, "apple", currency="USD"),
        _holding("Apple UK", APPLE_UK, 0.4, "apple", currency="GBP"),
    ]
    summary = _run(rows)
    drivers = _drivers(summary)  # type: ignore[arg-type]
    assert drivers["currency_mismatch"].raw_value == pytest.approx(0.4)


# --- identity -----------------------------------------------------------------


@pytest.mark.parametrize(
    "identity",
    [{"ticker": "AAPL"}, {"isin": "US0378331004"}, {"security_id": "037833100"}],
)
def test_a07_c2_n001_unresolvable_typed_identity_never_reaches_mapped_exposure(identity: dict[str, str]) -> None:
    # Normalisation still treats these columns as explicit identifiers (existing storage contract, DEFERRED),
    # but the look-through never maps a holding without a resolvable typed identity.
    row = {k: v for k, v in _holding("Apple", "", 1.0, "apple").items() if k != "isin"}
    summary = _run([{**row, **identity}])
    assert summary.mapped_weight == 0.0
    assert summary.unresolved_weight == pytest.approx(1.0)
    assert summary.exposures["issuer"] == {}


def test_a107_leading_zero_cusip_survives_csv_import(tmp_path: Path) -> None:
    path = tmp_path / "holdings.csv"
    path.write_text("security,weight,security_id,security_id_namespace\nApple,1.0,037833100,CUSIP\n", encoding="utf-8")
    _, frame, _ = _read_holdings_import(path, "2026-07-01")
    assert frame["security_id"].tolist() == ["037833100"]


_NPORT_TABLES = {
    "REGISTRANT": "ACCESSION_NUMBER\tCIK\n0000000000-26-000001\t0000000001\n0000000000-26-000002\t0000000001\n",
    "SUBMISSION": (
        "ACCESSION_NUMBER\tFILING_DATE\tREPORT_DATE\n"
        "0000000000-26-000001\t2026-04-15\t2026-03-31\n"
        "0000000000-26-000002\t2026-07-15\t2026-06-30\n"
    ),
    "FUND_REPORTED_INFO": (
        "ACCESSION_NUMBER\tSERIES_ID\tNET_ASSETS\n"
        "0000000000-26-000001\tS000000001\t1000\n"
        "0000000000-26-000002\tS000000001\t1000\n"
    ),
    "FUND_REPORTED_HOLDING": (
        "ACCESSION_NUMBER\tHOLDING_ID\tISSUER_NAME\tISSUER_TITLE\tISSUER_CUSIP\tPERCENTAGE\tASSET_CAT\tINVESTMENT_COUNTRY\n"
        "0000000000-26-000001\t1\tIssuer A\tTitle A\t037833100\t60\tEC\tUS\n"
        "0000000000-26-000001\t2\tIssuer B\tTitle B\t000000000\t40\tEC\tUS\n"
        "0000000000-26-000002\t1\tIssuer C\tTitle C\t\t100\tEC\tUS\n"
    ),
    "IDENTIFIERS": (
        "HOLDING_ID\tIDENTIFIERS_ID\tIDENTIFIER_ISIN\tIDENTIFIER_TICKER\n"
        "1\t1\tUS0378331005\t\n"
        "1\t2\t\tAAPL\n"
    ),
}


def _nport_archive(tmp_path: Path, **overrides: str) -> Path:
    path = tmp_path / "nport.zip"
    tables = {**_NPORT_TABLES, **overrides}
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in tables.items():
            archive.writestr(f"{name}.tsv", text)
    return path


def _parse_nport(tmp_path: Path, **overrides: str):
    results, _nav, _coverage = parse_sec_nport_archive(
        _nport_archive(tmp_path, **overrides),
        {("1", "S000000001"): "TESTETF"},
        accepted_at_by_accession={
            "0000000000-26-000001": "2026-04-15T20:00:00+02:00",
            "0000000000-26-000002": "2026-07-15T20:00:00+00:00",
        },
        today="2026-07-20",
    )
    return {result.as_of: result for result in results if not result.frame.empty}


def test_a107_identifier_rows_never_erase_isin_and_cusip_keeps_leading_zero(tmp_path: Path) -> None:
    holdings = _NPORT_TABLES["FUND_REPORTED_HOLDING"].replace(
        "0000000000-26-000002\t1\t", "0000000000-26-000002\t11\t"
    )
    by_date = _parse_nport(tmp_path, FUND_REPORTED_HOLDING=holdings)
    first = by_date["2026-03-31"].frame
    row = first.loc[first["security"].eq("Issuer A")].iloc[0]
    # A later identifier row carrying only a ticker never erases the ISIN; the CUSIP keeps its zero.
    assert row["isin"] == "US0378331005"
    assert row["security_id"] == "037833100"
    # An all-zero CUSIP placeholder is not an identity.
    assert not first["security_id"].fillna("").eq("000000000").any()
    # Acceptance times are one canonical UTC representation.
    assert by_date["2026-03-31"].frame["known_at"].eq("2026-04-15T18:00:00+00:00").all()


def test_a107_shared_holding_id_across_filings_is_not_attributed_without_accession(tmp_path: Path) -> None:
    # HOLDING_ID 1 exists in both filings and the identifier rows carry no accession: withheld everywhere.
    by_date = _parse_nport(tmp_path)
    for result in by_date.values():
        assert not result.frame["isin"].fillna("").eq("US0378331005").any()
    # With an accession the identifier row binds to exactly its own filing.
    header = "\t".join(("ACCESSION_NUMBER", "HOLDING_ID", "IDENTIFIERS_ID", "IDENTIFIER_ISIN", "IDENTIFIER_TICKER"))
    isin_row = "\t".join(("0000000000-26-000001", "1", "1", "US0378331005", ""))
    ticker_row = "\t".join(("0000000000-26-000001", "1", "2", "", "AAPL"))
    bound = "\n".join((header, isin_row, ticker_row)) + "\n"
    by_date = _parse_nport(tmp_path, IDENTIFIERS=bound)
    first = by_date["2026-03-31"].frame
    assert first.loc[first["security"].eq("Issuer A"), "isin"].eq("US0378331005").all()
    second = by_date.get("2026-06-30")
    assert second is None or not second.frame["isin"].fillna("").eq("US0378331005").any()


# --- exposure cube ------------------------------------------------------------


def test_d04_c2_n004_colliding_metadata_keys_do_not_overwrite_exposure_type() -> None:
    holdings = pd.DataFrame([_holding("Apple", APPLE, 1.0, "apple", instrument_id="ETF-A", authority="issuer", completeness="full")])
    cube = build_portfolio_exposure_cube(
        holdings,
        {"ETF-A": 1.0},
        decision_time="2026-07-18T10:00:00Z",
        position_metadata={" ETF-A ": {"exposure_type": "fund"}, "ETF-A": {"exposure_type": "security"}},
    )
    # Conflicting classification is dropped: the position stays a fund and is looked through once.
    security = next(item for item in cube.dimensions if item.dimension == "security")
    assert sum(segment.percentage for segment in security.segments) == pytest.approx(100.0)
    assert any(segment.bucket.startswith("isin:") for segment in security.segments)


def test_d104_direct_and_look_through_rows_are_not_double_counted() -> None:
    holdings = pd.DataFrame([_holding("Apple", APPLE, 1.0, "apple", instrument_id="ETF-A", authority="issuer", completeness="full")])
    cube = build_portfolio_exposure_cube(
        holdings,
        {"ETF-A": 0.5, APPLE: 0.5},
        decision_time="2026-07-18T10:00:00Z",
        position_metadata={APPLE: {"exposure_type": "security", "asset_class": "equity"}},
    )
    for dimension in cube.dimensions:
        assert sum(segment.percentage for segment in dimension.segments) == pytest.approx(100.0, abs=1e-7)
    security = next(item for item in cube.dimensions if item.dimension == "security")
    apple = next(segment for segment in security.segments if segment.bucket == f"isin:{APPLE}")
    assert apple.percentage == pytest.approx(100.0)
