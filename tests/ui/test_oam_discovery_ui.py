from __future__ import annotations

import json
from pathlib import Path

from etf_cockpit.app.pages.trust_evidence import filings_page
from etf_cockpit.app.state import AppState
import etf_cockpit.app.state as app_state_module
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_filings_page_exposes_national_oam_discovery_control() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = filings_page(None, state)
    buttons = [item for item in _walk(page) if item.__class__.__name__ == "OutlinedButton"]
    controls = list(_walk(page))

    assert any(getattr(item, "key", None) == "filings.discover-oam" for item in buttons)
    assert any(getattr(item, "content", None) == "Discover official filings" for item in buttons)
    assert any(getattr(item, "key", None) == "filings.import-manual-official" for item in buttons)
    assert any(getattr(item, "key", None) == "filings.import-local-oam" for item in buttons)
    assert any(getattr(item, "content", None) == "Import local OAM export" for item in buttons)
    country = next(item for item in controls if getattr(item, "label", None) == "Official filing country")
    assert {option.key for option in country.options} == {"DK", "FI", "FR", "GB", "NL", "NO", "SE"}
    api_key = next(item for item in controls if getattr(item, "label", None) == "Companies House API key")
    assert api_key.password is True
    assert api_key.can_reveal_password is False


def test_app_state_imports_local_oam_without_network_and_publishes_manual_evidence(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "oam.json"
    source.write_text(
        json.dumps({"records": [{"issuer": "Local BV", "isin": "NL0000000120", "title": "Report"}]}),
        encoding="utf-8",
    )
    registry = tmp_path / "oam.parquet"
    coverage = tmp_path / "coverage.parquet"
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        app_state_module,
        "write_oam_discovery_registry",
        lambda result, **_kwargs: (observed.update(registry_result=result) or registry),
    )
    monkeypatch.setattr(
        app_state_module,
        "write_filing_coverage",
        lambda result, **_kwargs: (observed.update(coverage_result=result) or coverage),
    )
    monkeypatch.setattr(
        "etf_cockpit.data.oam_adapters.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("local import attempted network I/O")),
    )
    state = AppState(snapshot=build_snapshot(), selected_etf="VWCE")

    message = state.import_local_oam(source, "NL", isin="NL0000000120", cache_dir=tmp_path / "cache")

    assert "source_authority=local_user_import" in message
    assert "manual_review=true" in message
    assert "execution_allowed=false" in message
    result = observed["registry_result"]
    assert result.records[0].source_authority == "local_user_import"
    assert result.records[0].execution_allowed is False
    assert result.coverage["source_authority"] == "local_user_import"
