from __future__ import annotations

from etf_cockpit.app.pages.instrument_detail import _render_evidence_section
from etf_cockpit.services import build_snapshot


def _walk(control):
    yield control
    for child in getattr(control, "controls", ()) or ():
        yield from _walk(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk(content)


def _projection(instrument_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract": "fixed-income-terms.v1",
        "status": "available",
        "instrument_id": instrument_id,
        "terms": {
            "coupon_type": "fixed_rate",
            "coupon_rate": "0.05",
            "maturity_date": "2026-01-15",
            "source_id": "official:prospectus",
            "source_checksum": "a" * 64,
            "known_at": "2024-01-02T00:00:00Z",
            "retrieved_at": "2024-01-03T00:00:00Z",
            "conflict_ids": [],
            "overlay_of": None,
        },
        "coupon_schedule": [
            {
                "payment_date": "2025-07-15",
                "amount": "25.00",
                "currency": "USD",
                "source_version_id": "terms-v1",
            }
        ],
        "redemption_schedule": [
            {
                "payment_date": "2026-01-15",
                "amount": "1000",
                "currency": "USD",
                "source_version_id": "terms-v1",
            }
        ],
        "history": [],
        "reason_codes": [],
        "capability_flags": {
            "contractual_schedule_available": True,
            "pricing_allowed": False,
            "screening_allowed": False,
            "proposal_allowed": False,
            "execution_allowed": False,
        },
        "execution_allowed": False,
    }


def test_instrument_detail_selector_uses_read_only_terms_facade(monkeypatch) -> None:
    from etf_cockpit.app.selectors import instrument_detail as selector

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    captured: dict[str, object] = {}

    def load(selected: str, **kwargs: object) -> dict[str, object]:
        captured.update({"instrument_id": selected, **kwargs})
        return _projection(selected)

    monkeypatch.setattr(selector, "load_fixed_income_terms_projection", load)
    monkeypatch.setattr(
        selector,
        "load_fixed_income_analytics_projection",
        lambda selected, **_kwargs: {
            "status": "available",
            "instrument_id": selected,
            "clean_price": "99.5",
            "curve_dirty_value": "100.7",
            "curve_model_value": "99.5",
            "execution_allowed": False,
        },
    )
    model = selector.build_instrument_detail(snapshot, instrument_id)

    assert captured["instrument_id"] == instrument_id
    assert captured["decision_time"] == captured["effective_at"]
    assert model.sections["fixed_income_terms"]["terms"]["source_id"] == (
        "official:prospectus"
    )
    assert model.sections["fixed_income_terms"]["execution_allowed"] is False
    assert model.sections["fixed_income_analytics"]["curve_model_value"] == "99.5"
    assert model.sections["fixed_income_analytics"]["execution_allowed"] is False


def test_fixed_income_panel_has_acceptance_key_lineage_and_authority_warning() -> None:
    control = _render_evidence_section(
        "Fixed-income terms and contractual cash flows",
        _projection("BOND-1"),
        subtitle="Terms, schedules, source lineage; execution_allowed=false.",
        key="instrument-detail.fixed-income-terms",
    )
    controls = tuple(_walk(control))
    keys = {getattr(item, "key", None) for item in controls}
    text = " ".join(str(getattr(item, "value", "")) for item in controls)

    assert "instrument-detail.fixed-income-terms" in keys
    assert "official:prospectus" in text
    assert "retrieved_at" in text
    assert "execution_allowed" in text


def test_fixed_income_analytics_panel_exposes_clean_model_without_authority() -> None:
    control = _render_evidence_section(
        "Fixed-income analytics",
        {
            "status": "available",
            "clean_price": "99.5",
            "curve_dirty_value": "100.75",
            "curve_model_value": "99.5",
            "observed_clean_price": "99.0",
            "execution_allowed": False,
        },
        subtitle="Clean and dirty model evidence; execution_allowed=false.",
        key="instrument-detail.fixed-income-analytics",
    )
    controls = tuple(_walk(control))
    assert "instrument-detail.fixed-income-analytics" in {
        getattr(item, "key", None) for item in controls
    }
    assert "execution_allowed" in " ".join(
        str(getattr(item, "value", "")) for item in controls
    )
