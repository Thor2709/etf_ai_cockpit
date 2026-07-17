from __future__ import annotations

from etf_cockpit.app.pages.onboarding import onboarding_page
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


def test_provider_status_shows_source_tier_cache_and_quota_policy() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    text = _text(provider_status_page(None, state))

    assert "Mandatory source tiers" in text
    assert "Cache status describes the local replay path" in text
    assert "no-network" in text


def test_onboarding_shows_source_policy_before_any_online_validation() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    text = _text(onboarding_page(None, state))

    assert "Data source policy" in text
    assert "network=not required" in text
    assert "mandatory-compatible" in text
