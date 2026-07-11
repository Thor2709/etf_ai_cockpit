from __future__ import annotations

from etf_cockpit.data.fred_provider import FredProvider
from etf_cockpit.data.rss_provider import RssProvider


def test_optional_providers_are_disabled_by_default() -> None:
    assert FredProvider().probe().status == "unavailable"
    assert RssProvider().probe().status == "unavailable"
