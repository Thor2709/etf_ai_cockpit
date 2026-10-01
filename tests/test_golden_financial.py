from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.analysis import fixed_income_analytics
from etf_cockpit.portfolio.performance_series import build_portfolio_performance_series
from test_fixed_income_analytics import _bond
from test_portfolio_performance_series import _snapshots


_GOLDEN_ROOT = Path(__file__).parent / "fixtures" / "golden"
_APPROVED_VERSION = 1
_APPROVED_VALUES = {
    "bond_pricing": {
        "clean_price": "100",
        "dirty_price": "100",
        "yield_to_maturity": "0.05",
    },
    "portfolio_performance": {
        "quarter_twr_returns": [0.0, 0.1],
        "quarter_investment_pnl": [0.0, 10.0],
    },
}


def _load_manifest() -> dict[str, object]:
    return json.loads((_GOLDEN_ROOT / "manifest.json").read_text(encoding="utf-8"))


def _load_fixture(manifest: dict[str, object], name: str) -> tuple[dict[str, object], int]:
    fixtures = manifest.get("fixtures")
    assert isinstance(fixtures, dict)
    file_name = fixtures.get(name)
    assert isinstance(file_name, str)
    path = (_GOLDEN_ROOT / file_name).resolve()
    assert path.parent == _GOLDEN_ROOT.resolve()
    fixture = json.loads(path.read_text(encoding="utf-8"))
    manifest_version = int(manifest["version"])
    version = int(fixture["version"])
    # A fixture keeps its own version; only changed fixtures are bumped with the manifest.
    assert 1 <= version <= manifest_version
    assert f"_v{version}" in path.stem
    return fixture, version


def _numerical_change_approved(name: str, expected: object, version: int, approval_note: object) -> bool:
    if name not in _APPROVED_VALUES:
        return False
    if expected == _APPROVED_VALUES[name]:
        return version >= _APPROVED_VERSION
    return version > _APPROVED_VERSION and isinstance(approval_note, str) and bool(approval_note.strip())


def _assert_bond_matches_golden() -> None:
    manifest = _load_manifest()
    fixture, version = _load_fixture(manifest, "bond_pricing")
    expected = fixture["expected"]
    assert _numerical_change_approved("bond_pricing", expected, version, manifest.get("approval_note"))
    assert fixture["instrument_id"] == "BOND-1"
    result = fixed_income_analytics.calculate_fixed_income_analytics(_bond())
    assert result.instrument_id == fixture["instrument_id"]
    for field, expected_value in expected.items():
        tolerance = Decimal(fixture["tolerances"][field])
        actual = getattr(result, field)
        assert actual is not None
        assert abs(Decimal(str(actual)) - Decimal(expected_value)) <= tolerance


def test_golden_debt_pricing_matches_analytic_reference() -> None:
    manifest = _load_manifest()
    assert manifest["source"]
    assert manifest["reviewer"] == "pending-owner-review"
    _assert_bond_matches_golden()


def test_golden_portfolio_performance_matches_versioned_fixture() -> None:
    manifest = _load_manifest()
    fixture, version = _load_fixture(manifest, "portfolio_performance")
    expected = fixture["expected"]
    assert _numerical_change_approved(
        "portfolio_performance", expected, version, manifest.get("approval_note")
    )
    dates = pd.DatetimeIndex(pd.to_datetime(fixture["dates"]))
    snapshots = _snapshots(dates, fixture["total_values"], fixture["external_flows"])

    returns = build_portfolio_performance_series(
        snapshots, metric="twr_return", aggregation="quarter"
    )
    pnl = build_portfolio_performance_series(
        snapshots, metric="investment_pnl", aggregation="quarter"
    )

    assert returns.status == "available"
    assert pnl.status == "available"
    assert [point.value for point in returns.points] == pytest.approx(
        expected["quarter_twr_returns"], abs=1e-9
    )
    assert [point.value for point in pnl.points] == pytest.approx(
        expected["quarter_investment_pnl"], abs=1e-9
    )


def test_numerical_golden_change_requires_version_bump_and_approval_note() -> None:
    changed = {**_APPROVED_VALUES["bond_pricing"], "clean_price": "100.01"}

    assert not _numerical_change_approved("bond_pricing", changed, 1, "")
    assert not _numerical_change_approved("bond_pricing", changed, 2, "")
    assert _numerical_change_approved("bond_pricing", changed, 2, "Owner approval recorded.")


def test_mixed_update_keeps_unchanged_goldens_valid() -> None:
    changed = {**_APPROVED_VALUES["bond_pricing"], "_marker": "changed"} if isinstance(_APPROVED_VALUES["bond_pricing"], dict) else "changed"
    later = _APPROVED_VERSION + 1
    # Unchanged fixture values stay valid after another fixture's approved bump.
    assert _numerical_change_approved("portfolio_performance", _APPROVED_VALUES["portfolio_performance"], later, None)
    # A changed value still needs a version bump and a non-empty approval note.
    assert not _numerical_change_approved("bond_pricing", changed, _APPROVED_VERSION, "note")
    assert not _numerical_change_approved("bond_pricing", changed, later, "  ")
    assert _numerical_change_approved("bond_pricing", changed, later, "owner approved new day-count")
