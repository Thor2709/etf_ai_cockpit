from __future__ import annotations

from datetime import date

import pandas as pd

from etf_cockpit.core.values import years_before
from tests.application.test_incremental_price_refresh import (
    _TODAY,
    _FakeProvider,
    _bar,
    _price_frame,
    _result,
    _run_real_validation,
    _stored,
)


def test_new_instrument_with_only_stale_bars_is_left_out_and_the_batch_commits(monkeypatch, tmp_path):
    # TKMEF on the max-history refetch: no stored rows, one fetched bar 39 business days old, blocked every instrument.
    floor = years_before(_TODAY, 5)
    shared = date(2026, 10, 30)
    stored = _price_frame("LIVE", [_bar(floor), _bar(shared)])
    window = pd.concat(
        [_price_frame("LIVE", [_bar(floor), _bar(shared), _bar(_TODAY)]), _price_frame("NEW", [_bar(date(2026, 10, 19))])],
        ignore_index=True,
    )
    provider = _FakeProvider(("LIVE", "NEW"), [_result(window)])

    clean_path, message = _run_real_validation(provider, monkeypatch, tmp_path, stored, incremental=False)

    final = _stored(clean_path)
    assert _TODAY in set(final.loc[final.etf_id.eq("LIVE"), "date"])
    assert not final.etf_id.eq("NEW").any()
    assert "Validated and committed" in message
    assert "New instrument with only stale bars, not committed: NEW." in message
    assert "PARTIAL refresh, not ok: no price data for NEW." in message
