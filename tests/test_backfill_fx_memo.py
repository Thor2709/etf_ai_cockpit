"""S6 (OD-14): one FX cross-rate memo per backfill run; sessions equal plain score_as_of and see no later quote day."""

from datetime import date

import pandas as pd

from etf_cockpit.application import score_backfill
from etf_cockpit.data import fx_data
from etf_cockpit.data import score_history_backfill as store
from etf_cockpit.data.replay_membership import ListingHistory
from tests._pit_listing import verified_listing_history  # noqa: F401 (autouse)
from tests.test_score_backfill import CALENDAR, _config, _fx, _prices, _series


def test_backfill_run_validates_each_fx_day_once_and_equals_plain_sessions(tmp_path, monkeypatch):
    config = _config()
    nok = next(item.id for item in config.universe.etfs if item.currency == "NOK" and item.id in config.universe.enabled_ids)
    prices = pd.concat([_prices(config), _series(nok, CALENDAR, 7, currency="NOK")], ignore_index=True)
    fx = _fx(0.1).assign(ingested_at=lambda frame: frame["available_at"])  # known at each quote day's close
    window = (date(2022, 6, 1), date(2022, 6, 30))

    validated: list[date] = []
    original_validate = fx_data.EurRateBook._validate_quote_day
    monkeypatch.setattr(fx_data.EurRateBook, "_validate_quote_day", staticmethod(
        lambda dated, quote_day: (validated.append(quote_day), original_validate(dated, quote_day))[1]
    ))
    leaks: list[tuple[date, date]] = []
    plain_score = score_backfill.score_as_of

    def checked(config, prices, as_of, **kwargs):
        memo = fx_data._CROSS_RATE_MEMO.get() or {}
        leaks.extend((key[0], as_of) for key in memo if key[0] > as_of)  # a quote day after the session
        return plain_score(config, prices, as_of, **kwargs)

    monkeypatch.setattr(score_backfill, "score_as_of", checked)
    result = score_backfill.backfill_score_history(tmp_path, *window, every=10, config=config, prices=prices, fx_rates=fx)
    run_validations = len(validated)
    assert result.status == "available" and not leaks

    history = store.load_backfill_score_history(tmp_path)
    sessions = sorted(set(history["as_of_date"].astype(str)))
    assert len(sessions) >= 2
    validated.clear()
    membership = ListingHistory.from_root(tmp_path, reconstructed=True)
    for session in sessions:
        run, _ = plain_score(config, prices, date.fromisoformat(session), fx_rates=fx, membership=membership)
        stored = history.loc[history["as_of_date"].astype(str).eq(session), run.columns].reset_index(drop=True)
        pd.testing.assert_frame_equal(stored, run.reset_index(drop=True), check_dtype=False)
    assert 0 < run_validations < len(validated)  # quote days shared by the sessions are validated once per run
