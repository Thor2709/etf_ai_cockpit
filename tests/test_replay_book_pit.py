"""D2 call site: the replay price book reads bars under the reconstructed PIT rule and carries ``pit_basis``."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.portfolio import paper_bots_execution as execution
from tests._pit_listing import verified_listing_history  # noqa: F401 (autouse)
from tests.test_paper_bots_execution import _allow, _book, _exec_config, _history_with_columns
from tests.test_paper_bots import _rows

pytestmark = pytest.mark.usefixtures("readiness_pass")

_FETCHED = "2026-12-01T13:00:00Z"  # a later bulk fetch stamped every bar after the replay cutoff


def _write_prices(root: Path) -> None:
    frame = _book()._frame.drop(columns=["_instrument"]).assign(known_at=_FETCHED, available_at=_FETCHED)
    path = root / execution.PRICE_FILE_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def test_the_replay_book_reads_bars_at_their_session_close(tmp_path: Path) -> None:
    _write_prices(tmp_path)
    day, known_by = date(2026, 10, 6), datetime(2026, 10, 7, 12, tzinfo=timezone.utc)

    stored = execution.PriceBook.from_root(tmp_path)
    reconstructed = execution.PriceBook.from_root(tmp_path, reconstructed=True)

    assert stored.bar("AAA", day, known_by=known_by) is None and stored.pit_basis is None
    assert reconstructed.bar("AAA", day, known_by=known_by) is not None
    assert reconstructed.pit_basis == "reconstructed"


def test_the_historical_replay_uses_the_reconstructed_book_and_carries_pit_basis(tmp_path: Path) -> None:
    from etf_cockpit.portfolio.paper_bots_replay import run_historical_replay

    _write_prices(tmp_path)
    october = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    as_of = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
    _allow(tmp_path, execution.replay_track(tmp_path, _exec_config()))

    result = run_historical_replay(as_of, root=tmp_path, history=pd.DataFrame(_history_with_columns(_rows(october))), now=as_of)

    assert result.status in {"available", "partial"}, (result.reason, result.warnings)
    assert result.pit_basis == "reconstructed"
