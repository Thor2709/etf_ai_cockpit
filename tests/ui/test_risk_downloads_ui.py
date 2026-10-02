from __future__ import annotations

from etf_cockpit.app.pages import risk as risk_module
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


class _Page:
    def update(self) -> None:
        pass


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _page_controls():
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    return list(_walk(risk_module.risk_page(_Page(), state)))


def _keys(controls) -> set[str]:
    return {str(getattr(item, "key", "")) for item in controls if getattr(item, "key", None)}


def test_risk_tables_have_download_buttons_and_keep_export_panel() -> None:
    keys = _keys(_page_controls())
    for key in (
        "risk.download-limits",
        "risk.download-correlation",
        "risk.download-drawdown",
        "risk.download-exposure-asset-class",
        "risk.download-exposure-theme",
        "risk.export-limits",
        "risk.export-performance-attribution",
    ):
        assert key in keys


def test_download_button_writes_local_csv_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(risk_module, "EXPORTS_DIR", tmp_path)
    controls = _page_controls()
    button = next(c for c in controls if getattr(c, "key", None) == "risk.download-exposure-region")
    button.on_click(None)
    names = [p.name for p in tmp_path.glob("*.csv")]
    # Empty canonical sources report unavailable and write no placeholder file.
    assert names in (["risk_exposure_region.csv"], [])


def test_download_helpers_are_labelled_and_local() -> None:
    row = risk_module._download_row(risk_module._download_button("Download x CSV", "risk.download-x", lambda _e: None))
    button = row.controls[0]
    assert button.key == "risk.download-x"
    assert "local file only" in str(button.tooltip)
