from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd



@dataclass(frozen=True)
class ModelInput:
    etf_id: str
    as_of_date: date
    series: pd.DataFrame
