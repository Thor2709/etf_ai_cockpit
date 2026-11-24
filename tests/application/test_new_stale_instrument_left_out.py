from __future__ import annotations

from datetime import date

import pandas as pd

from etf_cockpit.application import data_service
from etf_cockpit.application.data_service import DataService
from etf_cockpit.core.values import years_before
from tests.application.test_incremental_price_refresh import (
    _TODAY,
    _FakeProvider,
    _bar,
    _prepare,
    _price_frame,
    _result,
    _run_real_validation,
    _stored,
)

_real_validate = data_service.validate_prices


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


def test_only_new_stale_instruments_block_and_keep_the_store(monkeypatch, tmp_path):
    # Every fetched id is new and stale: nothing remains to commit, so the run blocks and the store is untouched.
    floor = years_before(_TODAY, 5)
    stored = _price_frame("LIVE", [_bar(floor), _bar(date(2026, 10, 30))])
    window = pd.concat(
        [_price_frame("NEW", [_bar(date(2026, 10, 19))]), _price_frame("OLD", [_bar(date(2026, 10, 16))])],
        ignore_index=True,
    )
    provider = _FakeProvider(("NEW", "OLD"), [_result(window)])
    clean_path = _prepare(monkeypatch, tmp_path, provider, stored)
    monkeypatch.setattr(data_service, "validate_prices", _real_validate)
    commits: list[object] = []
    monkeypatch.setattr(data_service, "commit_price_import", lambda result: commits.append(result))
    before = clean_path.read_bytes()
    service = DataService(config=None)

    message = service.refresh_yfinance_data(include_reference_data=False, include_fundamentals=False, incremental=False)

    assert commits == []
    assert clean_path.read_bytes() == before
    assert not list((tmp_path / "data").glob("staging/*.parquet"))
    assert service.last_operation_succeeded is False
    assert "ALL: No price rows remain to commit." in message
    assert "New instrument with only stale bars, not committed: NEW, OLD." in message
