from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from etf_cockpit.core.types import ForecastResult


@dataclass(frozen=True)
class ModelInput:
    etf_id: str
    as_of_date: date
    series: pd.DataFrame


class ForecastAdapter:
    model_name: str
    model_version: str

    def is_available(self) -> bool:
        raise NotImplementedError

    def load_model(self) -> None:
        raise NotImplementedError

    def unload_model(self) -> None:
        raise NotImplementedError

    def forecast_series(self, series: pd.Series, horizons: list[int]) -> list[ForecastResult]:
        raise NotImplementedError
