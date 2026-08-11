from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

import pandas as pd
import pytest

from etf_cockpit.app.pages.instrument_detail import render_event_calendar_panel
from etf_cockpit.app.router import PAGES
from etf_cockpit.app.selectors.instrument_detail import build_instrument_detail
from etf_cockpit.data.event_calendar import EVENT_COLUMNS, EVENT_SCHEMA_VERSION, EVENT_TYPES, CalendarEvent, events_available_as_of, load_calendar_events, normalise_event_decision_time, persist_calendar_events, validate_event
from etf_cockpit.services import build_snapshot


def _event(**changes: str) -> CalendarEvent:
    values = {
        "event_id": "earnings-msft-2026q2",
        "instrument_id": "MSFT",
        "event_type": "earnings",
        "event_date": "2026-07-30",
        "available_at": "2026-07-01T09:00:00+00:00",
        "ingested_at": "2026-07-01T09:01:00+00:00",
        "source_id": "issuer-calendar",
        "source_authority": "issuer",
        "source_url": "https://example.invalid/events/msft",
        "title": "Quarterly earnings",
        "risk_level": "high",
    }
    values.update(changes)
    return CalendarEvent(**values)


def _canonical_row(event: CalendarEvent, **changes: object) -> dict[str, object]:
    payload = {
        **event.__dict__,
        "schema_version": EVENT_SCHEMA_VERSION,
        "context_only": True,
        "execution_allowed": False,
        "executable_authority": False,
    }
    checksum = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    validation = validate_event(event)
    row = {
        **event.__dict__,
        "schema_version": EVENT_SCHEMA_VERSION,
        "validation_status": validation.status,
        "validation_reason": validation.reason,
        "backtest_eligible": validation.backtest_eligible,
        "context_only": True,
        "execution_allowed": False,
        "executable_authority": False,
        "raw_path": f"raw/event_calendar/{event.event_id}-{checksum[:16]}.json",
        "event_checksum": checksum,
    }
    row.update(changes)
    return {column: row.get(column, "") for column in EVENT_COLUMNS}


def test_event_validation_requires_point_in_time_provenance_and_keeps_context_only() -> None:
    valid = validate_event(_event(), datetime(2026, 7, 2, tzinfo=timezone.utc))
    assert valid.status == "valid_context"
    assert valid.backtest_eligible is True
    assert valid.context_only is True
    assert valid.execution_allowed is False

    assert validate_event(_event(available_at="2026-07-01")).status == "ambiguous_availability"
    assert validate_event(_event(event_time="2026-07-30T08:00:00", precision="minute")).status == "ambiguous_event_time"
    assert validate_event(_event(event_time="2026-07-30T08:00:00+00:00", precision="date")).status == "unexpected_event_time"
    assert validate_event(_event(), datetime(2026, 6, 30, tzinfo=timezone.utc)).status == "after_decision_time"


@pytest.mark.parametrize("event_date", ["2026-07-30T00:00:00+00:00", "2026-7-30", "2026-07-30Z", "2026-02-30"])
def test_event_validation_requires_exact_lexical_calendar_dates(event_date: str) -> None:
    assert validate_event(_event(event_date=event_date)).status == "invalid_event_date"


@pytest.mark.parametrize("event_type", sorted(EVENT_TYPES))
def test_event_validation_accepts_every_required_context_event_type(event_type: str) -> None:
    assert validate_event(_event(event_type=event_type), datetime(2026, 7, 2, tzinfo=timezone.utc)).status == "valid_context"


def test_event_validation_rejects_blank_or_invalid_timezone_metadata() -> None:
    assert validate_event(_event(timezone_name="")).status == "invalid_timezone"
    assert validate_event(_event(timezone_name="Not/IANA")).status == "invalid_timezone"
    assert validate_event(_event(timezone_name="America/New_York")).status == "valid_context"
    invalid_row = pd.DataFrame([_canonical_row(_event(), timezone_name="Not/IANA")])
    assert events_available_as_of(invalid_row, datetime(2026, 7, 2, tzinfo=timezone.utc), "MSFT").empty


def test_event_decision_time_normalisation_rejects_ambiguous_datetimes() -> None:
    assert normalise_event_decision_time("2026-07-02") == pd.Timestamp("2026-07-02T23:59:59Z")
    assert normalise_event_decision_time("2026-07-02T12:00:00+02:00") == pd.Timestamp("2026-07-02T10:00:00Z")
    assert normalise_event_decision_time("2026-07-02T12:00:00") is None


def test_event_availability_applies_both_cutoffs_and_identity() -> None:
    frame = pd.DataFrame([
        _canonical_row(_event(event_id="a")),
        _canonical_row(_event(event_id="late-ingest", ingested_at="2026-07-03T09:01:00+00:00")),
        _canonical_row(_event(event_id="other", instrument_id="OTHER")),
    ])
    result = events_available_as_of(frame, datetime(2026, 7, 2, tzinfo=timezone.utc), "MSFT")
    assert list(result["event_id"]) == ["a"]


@pytest.mark.parametrize(
    ("field", "value"),
    (("event_checksum", "tampered"), ("validation_reason", "untrusted"), ("context_only", False), ("executable_authority", True)),
)
def test_event_availability_rejects_inconsistent_canonical_rows(field: str, value: object) -> None:
    row = _canonical_row(_event())
    row[field] = value
    assert events_available_as_of(pd.DataFrame([row]), datetime(2026, 7, 2, tzinfo=timezone.utc), "MSFT").empty


def test_event_availability_rejects_incomplete_canonical_schema() -> None:
    row = _canonical_row(_event())
    frame = pd.DataFrame([{key: value for key, value in row.items() if key != "source_authority"}])
    assert events_available_as_of(frame, datetime(2026, 7, 2, tzinfo=timezone.utc), "MSFT").empty


def test_event_persistence_is_idempotent_and_atomic(tmp_path) -> None:
    event = _event()
    first = persist_calendar_events([event], raw_dir=tmp_path / "raw" / "event_calendar", clean_path=tmp_path / "clean.parquet")
    second = persist_calendar_events([event], raw_dir=tmp_path / "raw" / "event_calendar", clean_path=tmp_path / "clean.parquet")
    assert first.rows == second.rows == 1
    assert second.idempotent is True
    assert len(load_calendar_events(tmp_path / "clean.parquet")) == 1
    assert len(list((tmp_path / "raw" / "event_calendar").glob("*.json"))) == 1

    with pytest.raises(ValueError, match="Conflicting observations"):
        persist_calendar_events([_event(title="Changed")], raw_dir=tmp_path / "raw" / "event_calendar", clean_path=tmp_path / "clean.parquet")
    assert len(load_calendar_events(tmp_path / "clean.parquet")) == 1


def test_event_persistence_serializes_concurrent_append_transactions(tmp_path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    raw_dir = tmp_path / "raw" / "event_calendar"
    clean_path = tmp_path / "clean.parquet"
    audit_path = tmp_path / "clean_audit.json"
    start = Barrier(2)

    def append(event: CalendarEvent):
        start.wait()
        return persist_calendar_events([event], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(append, (_event(event_id="concurrent-a"), _event(event_id="concurrent-b"))))

    frame = load_calendar_events(clean_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert set(frame["event_id"]) == {"concurrent-a", "concurrent-b"}
    assert len(events_available_as_of(frame, datetime(2026, 7, 2, tzinfo=timezone.utc))) == 2
    assert any(result.rows == 2 for result in results)
    assert audit["rows"] == len(frame) == 2
    assert audit["checksum"] == next(result.checksum for result in results if result.rows == 2)


def test_event_persistence_does_not_launder_an_integrity_invalid_existing_ledger(tmp_path) -> None:
    raw_dir = tmp_path / "raw" / "event_calendar"
    clean_path = tmp_path / "clean.parquet"
    persist_calendar_events([_event(event_id="original")], raw_dir=raw_dir, clean_path=clean_path)
    tampered = pd.read_parquet(clean_path)
    tampered.loc[0, "title"] = "Tampered without checksum update"
    tampered.to_parquet(clean_path, index=False)

    assert load_calendar_events(clean_path).empty
    with pytest.raises(ValueError, match="malformed or inconsistent"):
        persist_calendar_events([_event(event_id="new-event")], raw_dir=raw_dir, clean_path=clean_path)
    raw_paths = list(raw_dir.glob("*.json"))
    assert len(raw_paths) == 1
    assert raw_paths[0].name.startswith("original-")
    assert pd.read_parquet(clean_path).loc[0, "title"] == "Tampered without checksum update"


@pytest.mark.parametrize("tamper", ["escaped_raw_path", "wrong_raw_name", "corrupt_raw", "missing_raw", "missing_audit", "bad_audit_rows", "bad_audit_checksum", "bad_audit_flags"])
def test_event_persistence_binds_the_triad_and_appends_with_no_write_on_tamper(tmp_path, tamper: str) -> None:
    raw_dir = tmp_path / "raw" / "event_calendar"
    clean_path = tmp_path / "clean.parquet"
    audit_path = tmp_path / "clean_audit.json"
    persist_calendar_events([_event()], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)

    if tamper in {"escaped_raw_path", "wrong_raw_name"}:
        frame = pd.read_parquet(clean_path)
        frame.loc[0, "raw_path"] = "../outside.json" if tamper == "escaped_raw_path" else "raw/event_calendar/wrong-name.json"
        frame.to_parquet(clean_path, index=False)
    elif tamper == "corrupt_raw":
        next(raw_dir.glob("*.json")).write_text("{}\n", encoding="utf-8")
    elif tamper == "missing_raw":
        next(raw_dir.glob("*.json")).unlink()
    elif tamper == "missing_audit":
        audit_path.unlink()
    else:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if tamper == "bad_audit_rows":
            audit["rows"] = 99
        elif tamper == "bad_audit_checksum":
            audit["checksum"] = "tampered"
        else:
            audit["context_only"] = False
        audit_path.write_text(json.dumps(audit, sort_keys=True) + "\n", encoding="utf-8")

    clean_before = clean_path.read_bytes()
    audit_before = audit_path.read_bytes() if audit_path.exists() else None
    raw_before = {path.name: path.read_bytes() for path in raw_dir.glob("*")}
    assert load_calendar_events(clean_path, raw_dir=raw_dir, audit_path=audit_path).empty
    with pytest.raises(ValueError, match="Canonical event"):
        persist_calendar_events([_event(event_id="new-event")], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)
    assert clean_path.read_bytes() == clean_before
    assert (audit_path.read_bytes() if audit_path.exists() else None) == audit_before
    assert {path.name: path.read_bytes() for path in raw_dir.glob("*")} == raw_before


def test_event_persistence_rejects_tampered_audit_validation_without_writes(tmp_path) -> None:
    raw_dir = tmp_path / "raw" / "event_calendar"
    clean_path = tmp_path / "clean.parquet"
    audit_path = tmp_path / "clean_audit.json"
    persist_calendar_events([_event()], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["validations"][0]["execution_allowed"] = True
    audit_path.write_text(json.dumps(audit, sort_keys=True) + "\n", encoding="utf-8")
    clean_before = clean_path.read_bytes()
    audit_before = audit_path.read_bytes()
    raw_before = {path.name: path.read_bytes() for path in raw_dir.iterdir()}

    assert load_calendar_events(clean_path, raw_dir=raw_dir, audit_path=audit_path).empty
    with pytest.raises(ValueError, match="audit record is inconsistent"):
        persist_calendar_events([_event(event_id="new-event")], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)
    assert clean_path.read_bytes() == clean_before
    assert audit_path.read_bytes() == audit_before
    assert {path.name: path.read_bytes() for path in raw_dir.iterdir()} == raw_before


def test_event_persistence_rejects_nested_raw_evidence_without_writes(tmp_path) -> None:
    raw_dir = tmp_path / "raw" / "event_calendar"
    clean_path = tmp_path / "clean.parquet"
    audit_path = tmp_path / "clean_audit.json"
    persist_calendar_events([_event()], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)
    nested = raw_dir / "unexpected"
    nested.mkdir()
    (nested / "extra.json").write_text("{}\n", encoding="utf-8")
    clean_before = clean_path.read_bytes()
    audit_before = audit_path.read_bytes()

    assert load_calendar_events(clean_path, raw_dir=raw_dir, audit_path=audit_path).empty
    with pytest.raises(ValueError, match="nested or linked evidence"):
        persist_calendar_events([_event(event_id="new-event")], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)
    assert clean_path.read_bytes() == clean_before
    assert audit_path.read_bytes() == audit_before
    assert (nested / "extra.json").read_text(encoding="utf-8") == "{}\n"


def test_event_persistence_rejects_extra_non_json_raw_evidence_without_writes(tmp_path) -> None:
    raw_dir = tmp_path / "raw" / "event_calendar"
    clean_path = tmp_path / "clean.parquet"
    audit_path = tmp_path / "clean_audit.json"
    persist_calendar_events([_event()], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)
    extra = raw_dir / "unrelated.txt"
    extra.write_text("unrelated\n", encoding="utf-8")
    clean_before = clean_path.read_bytes()
    audit_before = audit_path.read_bytes()
    raw_before = {path.name: path.read_bytes() for path in raw_dir.iterdir()}

    assert load_calendar_events(clean_path, raw_dir=raw_dir, audit_path=audit_path).empty
    with pytest.raises(ValueError, match="does not match the clean ledger"):
        persist_calendar_events([_event(event_id="new-event")], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)
    assert clean_path.read_bytes() == clean_before
    assert audit_path.read_bytes() == audit_before
    assert {path.name: path.read_bytes() for path in raw_dir.iterdir()} == raw_before


@pytest.mark.parametrize("entry_kind", ["nested", "non_json"])
def test_event_persistence_rejects_any_raw_evidence_without_clean_ledger(tmp_path, entry_kind: str) -> None:
    raw_dir = tmp_path / "raw" / "event_calendar"
    raw_dir.mkdir(parents=True)
    if entry_kind == "nested":
        unexpected = raw_dir / "unexpected"
        unexpected.mkdir()
        (unexpected / "extra.json").write_text("{}\n", encoding="utf-8")
    else:
        unexpected = raw_dir / "unrelated.txt"
        unexpected.write_text("unrelated\n", encoding="utf-8")
    clean_path = tmp_path / "clean.parquet"
    audit_path = tmp_path / "clean_audit.json"

    with pytest.raises(ValueError, match="incomplete without the clean ledger"):
        persist_calendar_events([_event(event_id="new-event")], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)
    assert not clean_path.exists()
    assert not audit_path.exists()
    assert not any(path.name.startswith("new-event-") for path in raw_dir.iterdir())
    assert unexpected.exists()


def test_event_persistence_rejects_orphan_raw_without_clean_ledger(tmp_path) -> None:
    raw_dir = tmp_path / "raw" / "event_calendar"
    raw_dir.mkdir(parents=True)
    orphan = raw_dir / "orphan.json"
    orphan.write_text("{}\n", encoding="utf-8")
    clean_path = tmp_path / "clean.parquet"

    with pytest.raises(ValueError, match="incomplete without the clean ledger"):
        persist_calendar_events([_event(event_id="new-event")], raw_dir=raw_dir, clean_path=clean_path)
    assert not clean_path.exists()
    assert orphan.read_text(encoding="utf-8") == "{}\n"


def test_event_load_rejects_exact_duplicate_canonical_rows(tmp_path) -> None:
    raw_dir = tmp_path / "raw" / "event_calendar"
    clean_path = tmp_path / "clean.parquet"
    audit_path = tmp_path / "clean_audit.json"
    persist_calendar_events([_event()], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)
    frame = pd.read_parquet(clean_path)
    duplicated = pd.concat([frame, frame], ignore_index=True)
    duplicated.to_parquet(clean_path, index=False)
    stable = duplicated.sort_index(axis=1).astype(str).sort_values(list(duplicated.columns), kind="stable")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit.update({"rows": 2, "checksum": hashlib.sha256(stable.to_csv(index=False).encode("utf-8")).hexdigest()})
    audit_path.write_text(json.dumps(audit, sort_keys=True) + "\n", encoding="utf-8")

    assert load_calendar_events(clean_path, raw_dir=raw_dir, audit_path=audit_path).empty


def test_conflicting_valid_observations_fail_load_disclosure_and_both_ui_surfaces(monkeypatch, tmp_path) -> None:
    raw_dir = tmp_path / "raw" / "event_calendar"
    clean_path = tmp_path / "clean.parquet"
    audit_path = tmp_path / "clean_audit.json"
    persist_calendar_events([_event()], raw_dir=raw_dir, clean_path=clean_path, audit_path=audit_path)
    conflict = _event(title="Changed")
    payload = {**conflict.__dict__, "schema_version": EVENT_SCHEMA_VERSION, "context_only": True, "execution_allowed": False, "executable_authority": False}
    checksum = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    (raw_dir / f"{conflict.event_id}-{checksum[:16]}.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    frame = pd.concat([pd.read_parquet(clean_path), pd.DataFrame([_canonical_row(conflict)])], ignore_index=True)
    frame.to_parquet(clean_path, index=False)
    stable = frame.sort_index(axis=1).astype(str)
    stable = stable.sort_values(list(stable.columns), kind="stable")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit.update({"rows": len(frame), "checksum": hashlib.sha256(stable.to_csv(index=False).encode("utf-8")).hexdigest()})
    audit_path.write_text(json.dumps(audit, sort_keys=True) + "\n", encoding="utf-8")

    assert load_calendar_events(clean_path, raw_dir=raw_dir, audit_path=audit_path).empty
    assert events_available_as_of(frame, datetime(2026, 7, 2, tzinfo=timezone.utc)).empty

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    ui_frame = pd.DataFrame([_canonical_row(_event(event_id="ui-a", instrument_id=instrument_id)), _canonical_row(_event(event_id="ui-a", instrument_id=instrument_id, title="Changed"))])
    model = build_instrument_detail(snapshot, instrument_id, events=ui_frame)
    assert model.sections["events"]["status"] == "unavailable"

    import etf_cockpit.app.pages.trust_evidence as trust_evidence
    monkeypatch.setattr(trust_evidence, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(trust_evidence, "load_calendar_events", lambda _path: ui_frame)
    state = type("State", (), {"snapshot": snapshot})()
    rendered = trust_evidence._news_context_extra(state)
    values: list[str] = []

    def collect(node: object) -> None:
        value = getattr(node, "value", None)
        if value:
            values.append(str(value))
        for child_name in ("controls", "content"):
            children = getattr(node, child_name, None)
            if isinstance(children, (list, tuple)):
                for child in children:
                    collect(child)
            elif children is not None:
                collect(children)

    collect(rendered)
    assert "event records are available at decision_time=" not in "\n".join(values)


def test_event_ui_surfaces_available_and_unavailable_states(monkeypatch) -> None:
    import etf_cockpit.app.selectors.instrument_detail as selector

    snapshot = build_snapshot()
    events = pd.DataFrame([_canonical_row(_event(instrument_id="VWCE"))])
    model = build_instrument_detail(snapshot, "VWCE", events=events)
    assert model.sections["events"]["status"] == "available"
    assert model.sections["events"]["events"][0]["execution_allowed"] is False
    rendered = render_event_calendar_panel(model)
    assert rendered is not None

    monkeypatch.setattr(selector, "EVENT_CLEAN_PATH", selector.EVENT_CLEAN_PATH.with_name("missing-event-calendar.parquet"))
    unavailable = build_instrument_detail(snapshot, "VWCE")
    assert unavailable.sections["events"]["status"] == "unavailable"


def test_instrument_detail_filters_events_at_snapshot_decision_time_and_exposes_truth() -> None:
    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    cutoff = pd.Timestamp(snapshot.data_report.as_of_date).tz_localize("UTC")
    events = pd.DataFrame([
        {
            **_canonical_row(_event(
                event_id="known-event",
                instrument_id=instrument_id,
                available_at=(cutoff - pd.Timedelta(days=2)).isoformat(),
                ingested_at=(cutoff - pd.Timedelta(days=2) + pd.Timedelta(minutes=1)).isoformat(),
            )),
        },
        {
            **_canonical_row(_event(
                event_id="future-event",
                instrument_id=instrument_id,
                available_at=(cutoff + pd.Timedelta(days=1)).isoformat(),
                ingested_at=(cutoff + pd.Timedelta(days=1, minutes=1)).isoformat(),
            )),
        },
    ])

    model = build_instrument_detail(snapshot, instrument_id, events=events)

    panel = model.sections["events"]
    assert panel["decision_time_available"] is True
    assert panel["available_at_decision_time"] is True
    assert [item["event_id"] for item in panel["events"]] == ["known-event"]
    assert panel["events"][0]["available_at_decision_time"] is True
    assert panel["events"][0]["timezone_name"] == "UTC"
    assert panel["events"][0]["source_url"] == "https://example.invalid/events/msft"

    rendered = render_event_calendar_panel(model)
    assert rendered is not None


def test_news_context_event_presentation_filters_to_snapshot_and_shows_provenance(monkeypatch) -> None:
    import etf_cockpit.app.pages.trust_evidence as trust_evidence

    snapshot = build_snapshot()
    cutoff = pd.Timestamp(snapshot.data_report.as_of_date).tz_localize("UTC")
    events = pd.DataFrame([
        _canonical_row(_event(
            event_id="known-event",
            instrument_id=snapshot.config.universe.enabled_ids[0],
            event_type="dividend",
            event_date="2026-07-01",
            available_at=(cutoff - pd.Timedelta(days=1)).isoformat(),
            ingested_at=(cutoff - pd.Timedelta(days=1, minutes=-1)).isoformat(),
            source_url="https://example.invalid/dividend",
            timezone_name="Europe/Oslo",
        )),
        _canonical_row(_event(
            event_id="future-event",
            instrument_id=snapshot.config.universe.enabled_ids[0],
            event_type="split",
            event_date="2026-08-01",
            available_at=(cutoff + pd.Timedelta(days=1)).isoformat(),
            ingested_at=(cutoff + pd.Timedelta(days=1, minutes=1)).isoformat(),
            source_url="https://example.invalid/split",
        )),
    ])
    monkeypatch.setattr(trust_evidence, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(trust_evidence, "load_calendar_events", lambda _path: events)
    state = type("State", (), {"snapshot": snapshot})()

    rendered = trust_evidence._news_context_extra(state)
    values: list[str] = []

    def collect(node: object) -> None:
        value = getattr(node, "value", None)
        if value:
            values.append(str(value))
        for child_name in ("controls", "content"):
            children = getattr(node, child_name, None)
            if isinstance(children, (list, tuple)):
                for child in children:
                    collect(child)
            elif children is not None:
                collect(children)

    collect(rendered)
    text = "\n".join(values)
    assert "1 event records are available at decision_time=" in text
    assert "source_url=https://example.invalid/dividend" in text
    assert "timezone_name=Europe/Oslo" in text
    assert "available_at_decision_time=True" in text
    assert "future-event" not in text


def test_news_context_page_exposes_event_calendar_status(monkeypatch) -> None:
    import etf_cockpit.app.pages.trust_evidence as trust_evidence

    monkeypatch.setattr(trust_evidence, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(trust_evidence, "load_calendar_events", lambda _path: pd.DataFrame([{"event_id": "e1"}]))
    state = type("State", (), {"snapshot": type("Snapshot", (), {"prices": pd.DataFrame()})()})()
    rendered = trust_evidence._news_context_extra(state)
    values: list[str] = []

    def collect(node: object) -> None:
        value = getattr(node, "value", None)
        if value:
            values.append(str(value))
        for child_name in ("controls", "content"):
            children = getattr(node, child_name, None)
            if isinstance(children, (list, tuple)):
                for child in children:
                    collect(child)
            elif children is not None:
                collect(children)

    collect(rendered)
    text = "\n".join(values)
    assert "Event calendar status" in text
    assert "snapshot decision time is unavailable" in text


def test_public_news_context_route_composes_event_calendar_panel(monkeypatch) -> None:
    import etf_cockpit.app.pages.trust_evidence as trust_evidence

    snapshot = build_snapshot()
    monkeypatch.setattr(trust_evidence, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(trust_evidence, "load_calendar_events", lambda _path: pd.DataFrame([{"event_id": "malformed"}]))
    state = type("State", (), {"snapshot": snapshot})()

    rendered = PAGES["/news-context"][1](None, state)
    values: list[str] = []

    def collect(node: object) -> None:
        value = getattr(node, "value", None)
        if value:
            values.append(str(value))
        for child_name in ("controls", "content"):
            children = getattr(node, child_name, None)
            if isinstance(children, (list, tuple)):
                for child in children:
                    collect(child)
            elif children is not None:
                collect(children)

    collect(rendered)
    assert "Event calendar status" in "\n".join(values)


def test_malformed_event_ledger_is_unavailable_in_both_ui_surfaces(monkeypatch) -> None:
    import etf_cockpit.app.pages.trust_evidence as trust_evidence

    snapshot = build_snapshot()
    instrument_id = snapshot.config.universe.enabled_ids[0]
    malformed = pd.DataFrame([{"event_id": "missing-canonical-columns", "instrument_id": instrument_id}])
    model = build_instrument_detail(snapshot, instrument_id, events=malformed)
    assert model.sections["events"]["status"] == "unavailable"

    monkeypatch.setattr(trust_evidence, "load_news_items", lambda _path: pd.DataFrame())
    monkeypatch.setattr(trust_evidence, "load_calendar_events", lambda _path: malformed)
    state = type("State", (), {"snapshot": snapshot})()
    rendered = trust_evidence._news_context_extra(state)
    values: list[str] = []

    def collect(node: object) -> None:
        value = getattr(node, "value", None)
        if value:
            values.append(str(value))
        for child_name in ("controls", "content"):
            children = getattr(node, child_name, None)
            if isinstance(children, (list, tuple)):
                for child in children:
                    collect(child)
            elif children is not None:
                collect(children)

    collect(rendered)
    assert "event records are available at decision_time=" not in "\n".join(values)
