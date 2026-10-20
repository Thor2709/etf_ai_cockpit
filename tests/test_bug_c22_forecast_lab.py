"""Bughunt C22 (#933): Forecast Lab out-of-sample labelling, as-of availability and denominators."""

from __future__ import annotations

import pandas as pd
import pytest

from etf_cockpit.application.forecast_service import forecast_lab_inputs
from etf_cockpit.features.forecast_lab import build_forecast_lab_report
from etf_cockpit.models.coverage_audit import (
    CURRENT_CONFIGURATION,
    POINT_IN_TIME_MEMBERSHIP,
    POINT_IN_TIME_UNAVAILABLE,
    build_coverage_audit,
)

DATES = pd.bdate_range("2026-01-05", periods=8)


def _prices(etf_id: str = "AAA") -> pd.DataFrame:
    # Log return of exactly 0.0 each day is not possible with growth; use a flat series so actual == 0.
    return pd.DataFrame({"etf_id": etf_id, "date": DATES, "adjusted_close": 100.0})


def _row(model: str, etf_id: str, day: pd.Timestamp, expected: float, status: str = "ok") -> dict[str, object]:
    return {
        "run_id": "run-1",
        "model_name": model,
        "etf_id": etf_id,
        "forecast_date": day,
        "horizon_days": 1,
        "expected_return": expected,
        "status": status,
    }


def _models(report: dict[str, object]) -> pd.DataFrame:
    return report["models"].set_index("model_name")  # type: ignore[union-attr]


def test_overview_is_labelled_all_matured_and_oos_uses_test_folds_only() -> None:
    # Flat prices: actual return 0. First 3 dates perfect (expected 0), last 3 poor (expected 0.30).
    forecasts = pd.DataFrame(
        [_row("baseline", "AAA", day, 0.0 if index < 3 else 0.30) for index, day in enumerate(DATES[:6])]
    )

    row = _models(build_forecast_lab_report(forecasts, _prices(), as_of_date=DATES[-1])).loc["baseline"]

    assert row["mae"] == pytest.approx(0.15)  # overview mixes the reserved pre-test rows in
    assert row["all_matured_mae"] == pytest.approx(0.15)
    assert row["all_matured_rows"] == 6
    assert "descriptive" in row["all_matured_label"] and "not validation" in row["all_matured_label"]
    assert row["oos_mae"] == pytest.approx(0.30)
    assert row["oos_rows"] == 3
    assert "out-of-sample" in row["oos_label"]


def test_oos_is_pending_without_a_test_fold() -> None:
    forecasts = pd.DataFrame([_row("baseline", "AAA", day, 0.1) for day in DATES[:3]])

    row = _models(build_forecast_lab_report(forecasts, _prices(), as_of_date=DATES[-1])).loc["baseline"]

    assert row["matured_rows"] == 3
    assert row["oos_rows"] == 0 and row["oos_mae"] is None
    assert row["oos_net_value_status"] == "oos_pending"


@pytest.mark.parametrize("model", ["timesfm", "timesfm3", "toto"])
def test_historical_as_of_before_first_optional_row_is_unavailable(model: str) -> None:
    forecasts = pd.DataFrame(
        [_row("baseline", "AAA", day, 0.0) for day in DATES[:6]]
        + [_row(model, "AAA", DATES[5], 0.01)]  # first optional-model row is late
    )

    historical = build_forecast_lab_report(forecasts, _prices(), as_of_date=DATES[3])
    latest = build_forecast_lab_report(forecasts, _prices())

    state = historical["model_catalogue"].set_index("model_id").loc[model, "state"]
    status = historical["optional_model_status"].set_index("model_id").loc[model]
    assert state == "unavailable"
    assert bool(status["artefact_available"]) is False and status["first_ok_forecast_date"] is None
    assert latest["model_catalogue"].set_index("model_id").loc[model, "state"] == "available"
    assert latest["optional_model_status"].set_index("model_id").loc[model, "first_ok_forecast_date"] == (
        DATES[5].date().isoformat()
    )


def test_artefact_availability_is_kept_apart_from_runtime_installed() -> None:
    forecasts = pd.DataFrame([_row("baseline", "AAA", day, 0.0) for day in DATES[:4]] + [_row("toto", "AAA", DATES[1], 0.0)])

    report = build_forecast_lab_report(forecasts, _prices(), runtime_installed={"toto": False, "timesfm": True})
    status = report["optional_model_status"].set_index("model_id")

    assert bool(status.loc["toto", "artefact_available"]) is True and status.loc["toto", "runtime_installed"] is False
    assert bool(status.loc["timesfm", "artefact_available"]) is False and status.loc["timesfm", "runtime_installed"] is True
    assert status.loc["timesfm3", "runtime_installed"] is None  # unknown is never guessed


def test_forecast_for_a_delisted_instrument_stays_excluded_and_in_the_denominator() -> None:
    latest = pd.DataFrame([_row("baseline", "AAA", day, 0.0) for day in DATES[:4]])
    history = pd.DataFrame([_row("baseline", "GONE", day, 0.2) for day in DATES[:2]])
    prices = _prices()  # no GONE series

    inputs = forecast_lab_inputs(latest, history, prices)
    report = build_forecast_lab_report(inputs, prices, as_of_date=DATES[-1])

    assert set(inputs["etf_id"]) == {"AAA", "GONE"}
    excluded = report["excluded"]
    assert len(excluded) == 2 and set(excluded["reason"]) == {"missing_price_series"}
    assert set(excluded["etf_id"]) == {"GONE"}
    assert report["completeness"]["forecast_rows"] == 6
    assert report["completeness"]["excluded_rows"] == 2 and report["completeness"]["gradable_rows"] == 4
    row = _models(report).loc["baseline"]
    assert row["forecast_rows"] == 6 and row["excluded_rows"] == 2
    assert row["matured_rows"] == 4  # nothing was fabricated for GONE
    assert not report["forecast_outcomes"].loc[report["forecast_outcomes"]["etf_id"].eq("GONE"), "actual_return"].notna().any()


class _Instrument:
    def __init__(self, instrument_id: str, sector: str = "tech", enabled: bool = True) -> None:
        self.id, self.sector, self.enabled = instrument_id, sector, enabled
        self.geography, self.size, self.currency, self.listing = "us", "large", "USD", "NYSE"


def _membership(*rows: tuple[str, str, str | None, str, bool]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "instrument_id": instrument,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "known_at": f"{snapshot}T00:00:00+00:00",
                "snapshot_date": snapshot,
                "snapshot_complete": complete,
            }
            for instrument, valid_from, valid_to, snapshot, complete in rows
        ]
    )


def _coverage_prices() -> pd.DataFrame:
    ids = ["AAA", "BBB", "CCC"]
    return pd.DataFrame(
        [{"etf_id": i, "date": day, "adjusted_close": 100.0} for i in ids for day in DATES]
    )


def test_historical_coverage_is_point_in_time_and_invariant_to_later_membership_changes() -> None:
    universe = [_Instrument("AAA"), _Instrument("BBB"), _Instrument("CCC")]  # CCC joined later
    as_of = DATES[5].date().isoformat()
    before = _membership(("AAA", "2025-01-01", None, "2026-01-05", True), ("BBB", "2025-01-01", None, "2026-01-05", True))
    after = pd.concat(
        [before, _membership(("CCC", "2026-03-01", None, "2026-03-02", True), ("AAA", "2025-01-01", None, "2026-03-02", True))],
        ignore_index=True,
    )

    first = build_coverage_audit(universe, _coverage_prices(), as_of_date=as_of, membership=before).to_dict()
    replay = build_coverage_audit(universe, _coverage_prices(), as_of_date=as_of, membership=after).to_dict()
    current = build_coverage_audit(universe, _coverage_prices(), as_of_date=as_of).to_dict()

    assert first["universe_count"] == 2 and first["provenance"]["universe_basis"] == POINT_IN_TIME_MEMBERSHIP
    assert first["groups"] == replay["groups"] and first["universe_count"] == replay["universe_count"]
    assert current["universe_count"] == 3 and current["provenance"]["universe_basis"] == CURRENT_CONFIGURATION


def test_point_in_time_coverage_fails_closed_without_a_usable_snapshot() -> None:
    universe = [_Instrument("AAA")]
    as_of = DATES[5].date().isoformat()
    late = _membership(("AAA", "2025-01-01", None, "2026-06-01", True))
    incomplete = _membership(("AAA", "2025-01-01", None, "2026-01-05", False))

    for membership in (late, incomplete, pd.DataFrame()):
        audit = build_coverage_audit(universe, _coverage_prices(), as_of_date=as_of, membership=membership)
        assert audit.provenance["universe_basis"] == POINT_IN_TIME_UNAVAILABLE
        assert audit.universe_count == 0 and audit.authority == "unavailable"


def test_report_labels_coverage_basis_current_configuration_or_point_in_time() -> None:
    forecasts = pd.DataFrame([_row("naive_drift", "AAA", day, 0.0) for day in DATES[:6]])
    universe = [_Instrument("AAA"), _Instrument("BBB")]
    membership = _membership(("AAA", "2025-01-01", None, "2026-01-05", True))
    prices = _prices()
    as_of = DATES[5]

    historical = build_forecast_lab_report(
        forecasts, prices, as_of_date=as_of, subgroup_universe=universe, subgroup_membership=membership
    )
    no_membership = build_forecast_lab_report(forecasts, prices, as_of_date=as_of, subgroup_universe=universe)
    latest = build_forecast_lab_report(forecasts, prices, subgroup_universe=universe, subgroup_membership=membership)

    assert historical["coverage_basis"] == POINT_IN_TIME_MEMBERSHIP
    assert no_membership["coverage_basis"] == CURRENT_CONFIGURATION
    assert latest["coverage_basis"] == CURRENT_CONFIGURATION  # no as-of requested: current view, labelled so
    assert any("current configuration" in note for note in no_membership["notes"])
    assert any("point-in-time" in note for note in historical["notes"])
    groups = historical["model_catalogue"].set_index("model_id").loc["naive_drift", "subgroup_results"]
    assert all(group["universe_count"] <= 1 for group in groups)

    # Fail-closed path: the only snapshot post-dates the as-of, so the label must say unavailable.
    late = _membership(("AAA", "2025-01-01", None, "2026-12-01", True))
    unavailable = build_forecast_lab_report(
        forecasts, prices, as_of_date=as_of, subgroup_universe=universe, subgroup_membership=late
    )
    assert unavailable["coverage_basis"] == POINT_IN_TIME_UNAVAILABLE
    assert any("unavailable" in note and "Subgroup coverage" in note for note in unavailable["notes"])
    assert not any("captured point-in-time universe membership" in note for note in unavailable["notes"])


def test_forecast_lab_page_governance_reads_the_as_of_filtered_availability() -> None:
    """E113-N001: the governance card must show the report's as-of-bounded availability, not the live registry."""

    from types import SimpleNamespace

    from etf_cockpit.app.pages import forecast_lab as page

    forecasts = pd.DataFrame([_row("baseline", "AAA", day, 0.0) for day in DATES[:6]] + [_row("timesfm", "AAA", DATES[5], 0.01)])
    report = build_forecast_lab_report(forecasts, _prices(), as_of_date=DATES[3], runtime_installed={"timesfm": True})
    state = SimpleNamespace(snapshot=SimpleNamespace(model_status={"timesfm": True, "baseline": True}))

    catalogue = report["model_catalogue"]
    card = page._governance_card(
        SimpleNamespace(span_width=lambda _span: 600),
        state,
        report,
        ["baseline", "timesfm"],
        catalogue,
        report["models"],
    )
    text = repr(card.__dict__) if hasattr(card, "__dict__") else str(card)
    assert "Artefact as of 2026-01-08" in text
    assert "Unavailable" in text  # live registry says timesfm=True, but there was no timesfm row by the as-of
