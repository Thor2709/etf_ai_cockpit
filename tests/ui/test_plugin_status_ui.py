from __future__ import annotations

from etf_cockpit.app.pages.data_models import data_models_page
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


def test_provider_status_page_exposes_one_provider_model_and_broker_capability_contract() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    text = _text(provider_status_page(None, state))

    assert "Capability registry" in text
    assert "plugin:builtin.baseline-model" in text
    assert "plugin:builtin.paper-broker" in text
    assert "execution authority" in text


def test_data_models_page_reuses_the_same_plugin_status_representation() -> None:
    snapshot = build_snapshot()
    state = AppState(snapshot=snapshot, selected_etf=snapshot.config.ui.default_etf)

    text = _text(data_models_page(None, state))

    assert "Unified plugin capability status" in text
    assert "plugin:builtin.baseline-model" in text
    assert "plugin:builtin.paper-broker" in text
