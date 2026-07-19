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

    unavailable = build_digest({"alerts": [{"status": "unavailable", "title": "No alert feed", "rationale": "The local feed is missing.", "provenance": "alerts:missing"}]})
    assert dict(unavailable.source_status)["alerts"] == "unavailable"


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
            {"proposal_id": "proposal-1", "outcome": "approved", "rationale": "Risk gates passed", "input_checksum": "a" * 64},
        ),
    )

    assert {item.source for item in digest.items} >= {"data_health", "events", "proposal_state"}
    assert any(item.status == "manual_review" for item in digest.items)
    assert any(item.source == "proposal_state" and item.status == "available" for item in digest.items)
    assert any(item.source == "proposal_state" and item.provenance == "a" * 64 for item in digest.items)
    assert digest.as_of == "2026-07-19"


def test_snapshot_adapter_preserves_all_local_digest_sources() -> None:
    sources = {
        source: ({
            "item_id": f"{source}-1",
            "title": f"{source} evidence",
            "rationale": "A local source record is available.",
            "status": "available",
            "provenance": f"{source}:checksum",
        },)
        for source in (
            "alerts",
            "source_revisions",
            "events",
            "model_drift",
            "portfolio_risk",
            "paper_incidents",
            "recovery_export",
        )
    }
    snapshot = SimpleNamespace(
        data_report=SimpleNamespace(status="Clean", as_of_date="2026-07-19"),
        digest_records=sources,
    )

    digest = build_digest_from_snapshot(snapshot)

    assert {item.source for item in digest.items} >= {"data_health", *sources}
    assert all(item.execution_allowed is False for item in digest.items)


def test_digest_is_available_through_the_typed_application_query() -> None:
    snapshot = SimpleNamespace(data_report=SimpleNamespace(status="Clean", as_of_date="2026-07-19"))
    api = LocalApplicationApi(lambda: snapshot)

    result = api.query(QueryRequest(resource="digest"))

    assert isinstance(result, DigestViewModel)
    assert result.items[0].source == "data_health"


def test_digest_does_not_mix_snapshot_and_api_roots(tmp_path) -> None:
    snapshot = SimpleNamespace(
        data_report=SimpleNamespace(status="Clean", as_of_date="2026-07-19"),
        digest_root=str(tmp_path / "other-workspace"),
        digest_records={
            "alerts": (
                {
                    "item_id": "wrong-root-alert",
                    "title": "Wrong root evidence",
                    "rationale": "This record must not cross workspace boundaries.",
                    "status": "available",
                    "provenance": "wrong-root:checksum",
                },
            )
        },
    )
    api = LocalApplicationApi(lambda: snapshot, root=tmp_path)

    digest = api.get_digest()

    assert dict(digest.source_status)["alerts"] == "unavailable"
    assert dict(digest.source_status)["source_revisions"] == "manual_review"
    assert any(item.item_id == "digest:root-mismatch" for item in digest.items)


def test_digest_retains_malformed_proposal_as_manual_review(tmp_path) -> None:
    proposal_dir = tmp_path / "data" / "operations" / "proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "proposal_bad.json").write_text("{not-json", encoding="utf-8")
    snapshot = SimpleNamespace(data_report=SimpleNamespace(status="Clean", as_of_date="2026-07-19"))
    api = LocalApplicationApi(lambda: snapshot, root=tmp_path)

    digest = api.get_digest()

    assert dict(digest.source_status)["proposal_state"] == "manual_review"
    assert any(item.source == "proposal_state" and "proposal_bad.json" in item.title for item in digest.items)


def test_dashboard_digest_has_stable_acceptance_key() -> None:
    class Api:
        def get_digest(self) -> DigestViewModel:
            return build_digest({}, as_of=None)

    control = _what_matters_today(SimpleNamespace(application_api=Api()))
    assert control.key == "dashboard.what-matters-today"
    rendered = "\n".join(_text_values(control))
    assert "What matters today" in rendered
    assert "No local evidence" in rendered
    assert "execution_allowed=false" in rendered


def test_dashboard_digest_failure_is_readable_and_fail_closed() -> None:
    class Api:
        def get_digest(self) -> DigestViewModel:
            raise ValueError("digest source unavailable")

    rendered = "\n".join(_text_values(_what_matters_today(SimpleNamespace(application_api=Api()))))
    assert "Digest unavailable" in rendered
    assert "manual review required" in rendered
    assert "execution_allowed=false" in rendered


def _text_values(node: object) -> list[str]:
    values: list[str] = []
    value = getattr(node, "value", None)
    if isinstance(value, str):
        values.append(value)
    for child in getattr(node, "controls", []) or []:
        values.extend(_text_values(child))
    content = getattr(node, "content", None)
    if content is not None:
        values.extend(_text_values(content))
    return values
