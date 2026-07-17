from __future__ import annotations

from etf_cockpit.app.pages.help_glossary import help_glossary_page
from etf_cockpit.app.pages.onboarding import onboarding_page
from etf_cockpit.app.pages.settings import settings_page
from etf_cockpit.app.pages.trust_evidence import provider_status_page
from etf_cockpit.app.state import AppState
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for child in getattr(control, "controls", []) or []:
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _text(control) -> str:
    return "\n".join(str(getattr(item, "value", "") or getattr(item, "text", "")) for item in _walk(control))


def test_provider_status_exposes_terms_and_restricted_export_boundaries() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    text = _text(provider_status_page(None, state))

    assert "Legal terms and export boundaries" in text
    assert "Restricted sources are local-only or metadata-only" in text
    assert "yfinance" in text


def test_user_facing_surfaces_show_disclaimer_and_terms_acknowledgement() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)
    disclaimer = "Research and education only. Not financial or tax advice. No broker execution or order transmission."

    assert disclaimer in _text(onboarding_page(None, state))
    assert "Terms acknowledgement" in _text(onboarding_page(None, state))
    assert disclaimer in _text(settings_page(None, state))
    assert "restricted sources are not redistributed" in _text(help_glossary_page(None, state))
