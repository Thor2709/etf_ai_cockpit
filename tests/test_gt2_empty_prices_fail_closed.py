"""GT2: empty price evidence fails closed (no crash), and the synthetic demo path is an explicit test opt-in."""

import sys
from datetime import date

import pandas as pd
import pytest

from etf_cockpit.core.config import load_config
from etf_cockpit.data.duckdb_store import load_prices


def test_generate_signals_without_prices_is_unavailable_with_a_reason_not_a_crash() -> None:
    from etf_cockpit.application.signal_service import SignalService

    config = load_config()
    assert config.data.allow_synthetic_sample_data is False  # product default: no synthetic prices
    assert load_prices(config=config).empty

    service = SignalService(config)
    assert service.generate_signals() == []  # was: ValueError "max() iterable argument is empty"
    assert service.last_unavailable_reason == "no price data; synthetic sample data disabled"


def test_run_forecasts_without_a_dated_observation_is_unavailable_not_a_date_parse_error(tmp_path) -> None:
    from etf_cockpit.application.forecast_service import ForecastService, _config_with_optional_models_disabled

    config = _config_with_optional_models_disabled(load_config())
    prices = load_prices(config=config)
    assert prices.empty
    no_as_of = pd.to_datetime(prices["date"]).max()  # NaT: nothing to forecast from
    assert pd.isna(no_as_of)

    with pytest.raises(ValueError, match="forecast_as_of_date_unavailable"):
        ForecastService(config).run_forecasts(no_as_of, config.universe.enabled_ids[:1], prices, output_path=tmp_path / "f.csv")
    assert not (tmp_path / "f.csv").exists()


def test_synthetic_opt_in_is_scoped_to_the_test_that_requests_it() -> None:
    harness = sys.modules["conftest"]
    assert load_config().data.allow_synthetic_sample_data is False
    scope = harness._synthetic_sample_opt_in_scope()
    next(scope)
    assert load_config().data.allow_synthetic_sample_data is True
    scope.close()
    assert load_config().data.allow_synthetic_sample_data is False


@pytest.mark.usefixtures("synthetic_sample_opt_in")
def test_opted_in_test_sees_the_seeded_demo_prices_labelled_synthetic() -> None:
    prices = load_prices()
    assert not prices.empty
    assert set(prices["source"]) <= {"synthetic_sample", "sample_generator"}
    assert isinstance(pd.to_datetime(prices["date"]).max().date(), date)
