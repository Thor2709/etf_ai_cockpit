from etf_cockpit.signals import simple_scores as ss


def test_plain_certificate_is_not_a_sparebank_equity_certificate():
    assert ss._is_sparebank_ec_asset_type("Equity certificate")
    assert ss._is_sparebank_ec_asset_type("egenkapitalbevis")
    assert not ss._is_sparebank_ec_asset_type("Certificate")


def test_sparebank_row_carries_latest_price_and_date():
    kwargs = dict(
        instrument_key="configured:NONG",
        display_id="NONG",
        name="SpareBank 1 Nord-Norge",
        yahoo_symbol="NONG.OL",
        asset_type="Equity certificate",
        instrument_currency="NOK",
        isin="NO0006000801",
        data_policy="daily",
    )
    row = ss._sparebank_scorecard_status(**kwargs, latest={"date": "2026-10-08", "price": 151.2})
    assert (row.latest_date, row.latest_price) == ("2026-10-08", 151.2)
    missing = ss._sparebank_scorecard_status(**kwargs)
    assert (missing.latest_date, missing.latest_price) == ("unavailable", None)
