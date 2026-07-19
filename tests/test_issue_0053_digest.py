from __future__ import annotations

from types import SimpleNamespace

from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.contracts import DigestViewModel, QueryRequest
from etf_cockpit.application.digest import build_digest, build_digest_from_snapshot
from etf_cockpit.app.pages.dashboard import _what_matters_today


def test_digest_is_deterministic_prioritised_and_deduplicated() -> None:
    records = {
        "alerts": [
            {
                "item_id": "risk-1",
                "category": "portfolio_risk",
                "severity": "warning",
                "status": "manual_review",
                "title": "Concentration requires review",
                "rationale": "A hard band was exceeded.",
                "as_of": "2026-07-19",
                "provenance": "risk:abc",
            },
            {
                "item_id": "risk-1",
                "category": "portfolio_risk",
                "severity": "critical",
                "status": "manual_review",
                "title": "Concentration requires urgent review",
                "rationale": "A hard band was exceeded.",
                "as_of": "2026-07-19",
                "provenance": "risk:def",
            },
        ],
        "events": [
            {
                "item_id": "event-1",
                "title": "Recovery completed",
                "rationale": "The local event chain was recovered.",
                "status": "available",
                "provenance": "event:123",
            }
        ],
    }

    first = build_digest(records, as_of="2026-07-19")
    second = build_digest(records, as_of="2026-07-19")

    assert first == second
    assert [item.item_id for item in first.items[:2]] == ["risk-1", "event-1"]
    assert first.items[0].severity == "critical"
    assert all(item.execution_allowed is False for item in first.items)
    assert dict(first.source_status)["alerts"] == "manual_review"


def test_digest_exposes_missing_inputs_and_incomplete_records() -> None:
    digest = build_digest(
        {
            "alerts": [{"item_id": "missing-provenance", "title": "Needs evidence", "rationale": "No checksum."}],
        },
        as_of=None,
    )

    assert digest.items[0].status == "manual_review"
    assert digest.items[0].provenance == "unavailable"
    assert dict(digest.source_status)["alerts"] == "manual_review"
    assert dict(digest.source_status)["events"] == "unavailable"


def test_empty_digest_is_an_explicit_manual_review_state() -> None:
    digest = build_digest({}, as_of=None)

    assert len(digest.items) == 1
    assert digest.items[0].status == "manual_review"
    assert "No local evidence" in digest.items[0].title
    assert all(status == "unavailable" for _, status in digest.source_status)


def test_malformed_source_is_manual_review_not_silently_empty() -> None:
    digest = build_digest({"events": [object()]})

    assert dict(digest.source_status)["events"] == "manual_review"
    assert digest.items[0].status == "manual_review"
    assert "Malformed" in digest.items[0].title


def test_snapshot_adapter_includes_data_health_and_proposals() -> None:
    snapshot = SimpleNamespace(
        data_report=SimpleNamespace(status="Blocked", as_of_date="2026-07-19"),
        operations=({"item_id": "op-1", "title": "Failed refresh", "message": "Retry manually", "status": "failed", "provenance": "op:1"},),
    )
    digest = build_digest_from_snapshot(
        snapshot,
        proposal_records=(
            {"proposal_id": "proposal-1", "outcome": "blocked", "rationale": "Risk gate failed", "input_checksum": "a" * 64},
        ),
    )

    assert {item.source for item in digest.items} >= {"data_health", "events", "proposal_state"}
    assert any(item.status == "manual_review" for item in digest.items)
    assert digest.as_of == "2026-07-19"


def test_digest_is_available_through_the_typed_application_query() -> None:
    snapshot = SimpleNamespace(data_report=SimpleNamespace(status="Clean", as_of_date="2026-07-19"))
    api = LocalApplicationApi(lambda: snapshot)

    result = api.query(QueryRequest(resource="digest"))

    assert isinstance(result, DigestViewModel)
    assert result.items[0].source == "data_health"


def test_dashboard_digest_has_stable_acceptance_key() -> None:
    class Api:
        def get_digest(self) -> DigestViewModel:
            return build_digest({}, as_of=None)

    control = _what_matters_today(SimpleNamespace(application_api=Api()))
    assert control.key == "dashboard.what-matters-today"
