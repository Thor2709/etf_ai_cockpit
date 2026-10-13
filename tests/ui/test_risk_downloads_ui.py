from __future__ import annotations

from etf_cockpit.app.pages import risk as risk_module
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


class _Page:
    def update(self) -> None:
        pass


def _walk(control):
    yield control
    page_body = getattr(control, "body", None)  # PageView wraps the page body
    if page_body is not None and page_body is not control:
        yield from _walk(page_body)
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)
    for item in getattr(control, "items", []) or []:  # card menu entries
        yield from _walk(item)


def _page_controls():
    """Controls of every view/dimension the segments offer (the page shows one view at a time)."""

    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    view = risk_module.risk_page(_Page(), state)
    groups = {group.key: group for group in view.chrome.segment_groups}
    controls = []
    for name in groups["risk-view"].items:
        groups["risk-view"].on_change(name)
        for dimension in groups["risk-dimension"].items:
            groups["risk-dimension"].on_change(dimension)
            controls.extend(_walk(view.body))
    return controls


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
    assert names == ["risk_exposure_region.csv"]


def test_download_actions_are_labelled_and_local() -> None:
    items = [c for c in _page_controls() if str(getattr(c, "key", "")).startswith("risk.download-")]
    assert items
    assert all("local file only" in str(item.tooltip) for item in items)
