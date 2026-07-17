from __future__ import annotations

import inspect

from etf_cockpit.app.pages.catalogue import catalogue_page
from etf_cockpit.app.router import PAGES


def test_catalogue_workspace_is_registered_and_declares_safe_boundaries() -> None:
    assert PAGES["/catalogue"][0] == "Data Catalogue"
    source = inspect.getsource(catalogue_page)
    for label in ("Registered datasets", "Immutable snapshots", "Instrument provenance explorer", "Execution allowed: false"):
        assert label in source
    assert "remote fetch" in source
