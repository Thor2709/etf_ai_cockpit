from datetime import datetime, timezone
from unittest.mock import Mock

from dataclasses import replace

from etf_cockpit.data import euronext_listing
from etf_cockpit.data.universe_membership import CaptureStatus


def test_s6_05_exact_duplicate_listing_row_is_harmless(monkeypatch):
    config = replace(euronext_listing.load_euronext_listing_config(), minimum_rows=1)
    payload = (
        b"Name;ISIN;Symbol;Market;Currency\n05 Oct 2026\nx\nx\n"
        b"A;US0378331005;AAPL;Euronext Growth Oslo;NOK\n"
        b"A;US0378331005;AAPL;Euronext Growth Oslo;NOK\n"
    )
    recorder = Mock(return_value=CaptureStatus("recorded", config.scope))
    monkeypatch.setattr(euronext_listing, "load_euronext_listing_config", lambda *args: config)
    monkeypatch.setattr(euronext_listing, "record_listing_capture", recorder)

    result = euronext_listing.capture_euronext_oslo_listing(
        transport=lambda *args: payload,
        clock=lambda: datetime(2026, 10, 5, 12, tzinfo=timezone.utc),
    )

    assert result.status == "recorded"
    recorder.assert_called_once()
