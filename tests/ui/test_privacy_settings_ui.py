from __future__ import annotations

from etf_cockpit.app.pages.settings import settings_page
from etf_cockpit.app.state import AppState
from etf_cockpit.application.snapshot_builder import build_snapshot


def _walk(control):
    yield control
    page_body = getattr(control, "body", None)
    if page_body is not None and page_body is not control:
        yield from _walk(page_body)
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def test_settings_exposes_privacy_backup_and_recovery_controls() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    page = settings_page(None, state)
    page.chrome.segment_groups[0].on_change("Privacy")
    controls = list(_walk(page))
    keys = {getattr(control, "key", None) for control in controls}
    labels = {getattr(control, "value", None) or getattr(control, "text", None) for control in controls}
    assert {"settings.backup-create", "settings.backup-validate", "settings.recovery-drill", "settings.delete-private"} <= keys
    assert "Privacy, backup and recovery" in labels
