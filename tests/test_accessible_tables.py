from __future__ import annotations

import pandas as pd

from etf_cockpit.data.export_tables import table_columns


def test_export_table_contract_has_stable_columns_and_textual_status() -> None:
    frame = pd.DataFrame({"instrument_id": ["A"], "status": ["unavailable"]})
    assert table_columns(frame) == ("instrument_id", "status")
