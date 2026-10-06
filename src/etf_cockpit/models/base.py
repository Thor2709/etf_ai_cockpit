"""Forecast adapter contract.

Unit contract (decision D5, master spec 9.1 "log returns internally"): every
forecast adapter emits ``expected_return`` and the ``q*_return`` quantiles as
horizon LOG returns, ``log(P[t+h] / P[t])``.  Calibration, coverage and MASE
compare forecasts with realised log returns and stay in log units.  Convert
with ``expm1`` to a simple return only at a monetary boundary, such as
subtracting a cost fraction or valuing an order in euros.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd



@dataclass(frozen=True)
class ModelInput:
    etf_id: str
    as_of_date: date
    series: pd.DataFrame
