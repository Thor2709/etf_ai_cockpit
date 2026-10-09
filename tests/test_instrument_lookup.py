"""Add by ISIN or ticker (free sources, injectable) and the delisted/merged flag that keeps history."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import etf_cockpit.app.pages.universe_manager as manager
from etf_cockpit.application import stock_service
from etf_cockpit.data import instrument_lookup as lk
from etf_cockpit.data.stock_fundamentals import targets_from_universe
from etf_cockpit.data.universe_store import UniverseRecord, UniverseStoreSnapshot, load_universe, save_universe, validate_universe
from tests.test_universe_manager import _Page, _fill, _keyed, _state, _texts

MSFT_ISIN = "US5949181045"
QUOTE = {"symbol": "MSFT", "longname": "Microsoft Corporation", "exchDisp": "NASDAQ", "quoteType": "EQUITY", "sector": "Technology"}
INFO = {"currency": "USD", "country": "United States", "sector": "Technology", "industry": "Software - Infrastructure", "quoteType": "EQUITY", "longName": "Microsoft Corporation"}


def _sources(quotes, figi=None, info=INFO):
    return dict(
        get_json=lambda _url: {"quotes": quotes},
        post_json=lambda _url, _payload: figi if figi is not None else [{"data": [{"name": "MICROSOFT CORP", "ticker": "MSFT", "exchCode": "US"}]}],
        ticker_factory=lambda _symbol: SimpleNamespace(info=info),
    )


def test_identifiers_are_classified_and_a_wrong_isin_check_digit_is_refused() -> None:
    assert lk.isin_checksum_ok(MSFT_ISIN) and not lk.isin_checksum_ok("US5949181046")
    assert lk.classify(MSFT_ISIN) == ("isin", MSFT_ISIN)
    assert lk.classify("asml.as") == ("ticker", "ASML.AS")
    kind, reason = lk.classify("US5949181046")
    assert kind == "invalid" and "check digit" in reason
    assert lk.classify("no way!")[0] == "invalid" and lk.classify("")[0] == "invalid"


def test_isin_is_verified_only_when_openfigi_knows_it_and_the_name_agrees() -> None:
    ok = lk.resolve(MSFT_ISIN, **_sources([QUOTE]))
    assert ok.status == "ok" and ok.chosen.symbol == "MSFT" and ok.chosen.currency == "USD"
    assert ok.isin_status == "verified" and "agrees" in ok.isin_note
    other = lk.resolve(MSFT_ISIN, **_sources([QUOTE], figi=[{"data": [{"name": "SOMETHING ELSE LTD", "ticker": "X", "exchCode": "LN"}]}]))
    assert other.isin_status == "needs_verification"
    unknown = lk.resolve(MSFT_ISIN, **_sources([QUOTE], figi=[{"warning": "No identifier found."}]))
    assert unknown.isin_status == "needs_verification" and "OpenFIGI has no record" in unknown.isin_note


def test_several_listings_are_ambiguous_until_the_user_picks_one_that_was_offered() -> None:
    quotes = [QUOTE, {**QUOTE, "symbol": "MSF.DE", "exchDisp": "XETRA"}]
    result = lk.resolve("MSFT", **_sources(quotes))
    assert result.status == "ok" and result.chosen.symbol == "MSFT"  # an exact ticker match wins
    ambiguous = lk.resolve(MSFT_ISIN, **_sources(quotes))
    assert ambiguous.status == "ambiguous" and len(ambiguous.candidates) == 2 and "pick" in ambiguous.reason
    assert lk.choose(ambiguous, "MSF.DE").chosen.exchange == "XETRA"
    assert lk.choose(ambiguous, "NOPE").status == "invalid"


def test_failures_state_their_reason_and_never_invent_a_listing() -> None:
    empty = lk.resolve("ZZZZ", **_sources([]))
    assert empty.status == "not_found" and "lists no equity or ETF" in empty.reason and empty.chosen is None

    def broken(_url):
        raise OSError("offline")

    down = lk.resolve("MSFT", get_json=broken)
    assert down.status == "error" and "nothing was added" in down.reason
    bond = lk.resolve("XYZ", **_sources([{**QUOTE, "quoteType": "BOND"}]))
    assert bond.status == "not_found"  # unsupported types are filtered out, not guessed


def test_unmatched_ticker_stays_unresolved_with_candidates() -> None:
    result = lk.resolve("MSF", **_sources([QUOTE]))
    assert result.status == "ambiguous" and result.chosen is None
    assert [candidate.symbol for candidate in result.candidates] == ["MSFT"]


def test_share_class_name_mismatch_does_not_verify_an_isin() -> None:
    class_b = {**QUOTE, "longname": "Acme Class B"}
    figi = [{"data": [{"name": "Acme Class A", "ticker": "MSFT", "exchCode": "US"}]}]
    result = lk.resolve(MSFT_ISIN, **_sources([class_b], figi=figi, info={**INFO, "longName": "Acme Class B"}))
    assert result.chosen.symbol == "MSFT" and result.isin_status == "needs_verification"


def test_unsupported_enriched_quote_type_is_rejected() -> None:
    result = lk.resolve("MSFT", **_sources([QUOTE], info={**INFO, "quoteType": "OPTION"}))
    assert result.status == "unsupported" and result.chosen is None and not result.candidates


def test_universe_values_never_default_the_currency_and_keep_unverified_isins_unverified() -> None:
    result = lk.resolve("ASML.AS", **_sources([{**QUOTE, "symbol": "ASML.AS"}], info={**INFO, "currency": "EUR", "country": "Netherlands"}))
    values = stock_service.universe_values(result, ["ASML_AS_OLD"])
    assert values["instrument_id"] == "ASML" and values["currency"] == "EUR" and values["isin"] == "needs_verification" and values["tier"] == "secondary"
    assert stock_service.universe_values(result, ["ASML"])["instrument_id"] == "ASML_AS"  # taken id: the full symbol
    nocurrency = lk.resolve("MSFT", **_sources([QUOTE], info={"quoteType": "EQUITY"}))
    with pytest.raises(ValueError, match="no currency"):
        stock_service.universe_values(nocurrency, [])
    UniverseRecord(**values)  # every key is a real universe field


def test_lifecycle_flag_is_validated_persisted_and_stops_fetching_but_keeps_the_record(tmp_path: Path) -> None:
    ok = UniverseRecord("OLD", "Old Co", "needs_verification", "needs_verification", "OLD.AS", "stock", "secondary", enabled=False, lifecycle="delisted")
    assert validate_universe([ok]).valid
    assert not validate_universe([UniverseRecord("X", "X", "needs_verification", "needs_verification", "X", lifecycle="gone")]).valid
    (tmp_path / "configs").mkdir()
    save_universe([ok], "", root=tmp_path)
    assert load_universe(tmp_path).records[0].lifecycle == "delisted"  # survives the store round trip
    live = {"id": "LIVE", "instrument_type": "stock", "enabled": True, "ticker": "LIVE", "sector": "Tech"}
    flagged = {**live, "id": "OLD", "lifecycle": "delisted"}
    assert [t.instrument_id for t in targets_from_universe([live, flagged], excluded_sectors=[])] == ["LIVE"]


def test_the_owner_universe_flags_the_taken_over_and_merged_names() -> None:
    rows = {row["id"]: row for row in yaml.safe_load(Path("configs/universe.yaml").read_text(encoding="utf-8"))["etfs"]}
    assert rows["JEDI"]["lifecycle"] == "delisted" and rows["SADG"]["lifecycle"] == "merged"
    assert all("lifecycle" not in row for key, row in rows.items() if key not in {"JEDI", "SADG"})


def test_universe_page_adds_a_looked_up_listing_to_the_pending_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    record = UniverseRecord("A", "Alpha", "NO0000000001", "verified", "A", "stock", "primary")
    monkeypatch.setattr(manager, "load_universe", lambda *_a: UniverseStoreSnapshot((record,), "rev", Path("store.json")))
    monkeypatch.setattr(stock_service, "lookup_instrument", lambda text: lk.resolve(text, **_sources([QUOTE])))
    monkeypatch.setattr(manager.threading, "Thread", lambda target, **_k: SimpleNamespace(start=target))
    page = _Page()
    root = manager.universe_manager_page(page, _state()).body
    _keyed(root)["universe.lookup"].on_click(None)
    dialog = page.overlay[-1]
    _fill(dialog, **{"universe.field.lookup": MSFT_ISIN})
    _keyed(dialog)["universe.lookup-search"].on_click(None)
    assert "Microsoft Corporation" in _texts(dialog) and "USD" in _texts(dialog)
    _keyed(dialog)["universe.lookup-stage"].on_click(None)
    assert "universe.identity.MSFT" in _keyed(root)  # staged next to the existing record, saved only by Save


def test_universe_table_flags_a_delisted_record_with_its_meaning(monkeypatch: pytest.MonkeyPatch) -> None:
    gone = UniverseRecord("OLD", "Old Co", "needs_verification", "needs_verification", "OLD.AS", "stock", "secondary", enabled=False, lifecycle="delisted")
    monkeypatch.setattr(manager, "load_universe", lambda *_a: UniverseStoreSnapshot((gone,), "rev", Path("store.json")))
    root = manager.universe_manager_page(_Page(), _state()).body
    assert "Delisted" in _texts(root)
    from tests.test_universe_manager import _walk

    assert any("are kept" in str(getattr(c, "tooltip", "")) and "no new data" in str(getattr(c, "tooltip", "")) for c in _walk(root))


def test_a_config_loaded_universe_keeps_the_flag_when_the_page_saves_it() -> None:
    from etf_cockpit.core.config import ETFConfig

    state = _state()
    state.snapshot.config.universe.etfs.append(ETFConfig(id="OLD", name="Old", ticker="OLD", role="watchlist", enabled=False, lifecycle="merged"))
    assert {r.instrument_id: r.lifecycle for r in manager.records_from_config(state)} == {"A": "", "OLD": "merged"}
