from __future__ import annotations

import inspect

from etf_cockpit.app.pages.import_export import import_export_page
from etf_cockpit.core.ui_acceptance import load_ui_acceptance_contracts


def test_portfolio_import_controls_are_registered_and_non_executable() -> None:
    keys = {item.key for item in load_ui_acceptance_contracts()}
    assert {
        "import-export.portfolio-reconcile",
        "import-export.portfolio-apply-mapping",
        "import-export.portfolio-rollback",
        "import-export.portfolio-export",
    } <= keys
    source = inspect.getsource(import_export_page)
    assert 'value="portfolio_history"' in source
    assert "execution_allowed=false" in source
    assert "Rebuilt from zero" in source
    assert "Identity ambiguities remain quarantined" in source
    assert "identity_candidates" in source
    assert "mapping decision is checksum-bound and immutable" in source
