from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
import json
import os
import time

import pytest

from etf_cockpit.application.screening import ScreenFilter, ScreenQuery, bind_query, run_screen
from etf_cockpit.data import screen_store
from etf_cockpit.data.screen_store import export_screen_csv, list_saved_screens, load_screen, save_screen


def _query() -> ScreenQuery:
    return ScreenQuery(
        filters=(ScreenFilter("region", "eq", "Europe"),),
        as_of="2026-07-18",
        universe_revision="universe-7",
        formula_version="score-v2",
        dataset_checksums=(("fundamentals", "abc"),),
    )


def test_saved_screen_revisions_are_immutable_and_replayable(tmp_path) -> None:
    first = save_screen("Europe quality", _query(), directory=tmp_path)
    second = save_screen("Europe quality", _query(), directory=tmp_path)
    assert first.name == "000001.json"
    assert second.name == "000002.json"
    assert load_screen("Europe quality", 1, directory=tmp_path) == _query()
    assert load_screen("Europe quality", directory=tmp_path) == _query()
    assert list_saved_screens(directory=tmp_path) == ("Europe quality",)


def test_saved_screen_names_do_not_collide_after_path_normalisation(tmp_path) -> None:
    first = save_screen("A B", _query(), directory=tmp_path)
    second = save_screen("A_B", _query(), directory=tmp_path)
    assert first.parent != second.parent
    assert list_saved_screens(directory=tmp_path) == ("A B", "A_B")


def test_concurrent_screen_saves_allocate_unique_revisions(tmp_path) -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _index: save_screen("Concurrent", _query(), directory=tmp_path), range(8)))
    assert sorted(path.name for path in paths) == [f"{revision:06d}.json" for revision in range(1, 9)]
    assert load_screen("Concurrent", directory=tmp_path) == _query()


@pytest.mark.parametrize("name", ["../escape", "a/b", "a\\b", ".", "", "name.json"])
def test_saved_screen_rejects_unsafe_names(tmp_path, name: str) -> None:
    with pytest.raises(ValueError):
        save_screen(name, _query(), directory=tmp_path)


def test_saved_screen_fails_closed_on_corruption_or_tampering(tmp_path) -> None:
    path = save_screen("trusted", _query(), directory=tmp_path)
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(ValueError, match="unreadable"):
        load_screen("trusted", directory=tmp_path)

    path = save_screen("tampered", _query(), directory=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["execution_allowed"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_screen("tampered", directory=tmp_path)


def test_csv_export_is_deterministic_safe_and_contains_lineage(tmp_path) -> None:
    records = [
        {"instrument_id": "SAFE", "region": "Europe", "note": "normal"},
        {"instrument_id": "FORMULA", "region": "Europe", "note": " =HYPERLINK('x')"},
    ]
    query = bind_query(records, _query())
    result = run_screen(records, query)
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    export_screen_csv(result, query, first)
    export_screen_csv(result, query, second)
    assert first.read_bytes() == second.read_bytes()
    with first.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[1]["note"].startswith("'")
    assert rows[0]["screen_query_checksum"] == query.checksum
    assert rows[0]["screen_execution_allowed"] == "False"
    assert rows[0]["screen_as_of"] == "2026-07-18"


def test_csv_export_requires_explicit_csv_destination(tmp_path) -> None:
    with pytest.raises(ValueError, match=".csv"):
        export_screen_csv(run_screen([], _query()), _query(), tmp_path / "screen.txt")


def test_csv_export_rejects_mismatched_result_and_query(tmp_path) -> None:
    result = run_screen([], _query())
    other = ScreenQuery(as_of="different")
    with pytest.raises(ValueError, match="does not match"):
        export_screen_csv(result, other, tmp_path / "screen.csv")


def test_csv_export_neutralises_headers_and_lineage_formulae(tmp_path) -> None:
    records = [{"=danger": "@cmd", "instrument_id": "SAFE"}]
    query = bind_query(records, ScreenQuery(as_of=" =HYPERLINK('x')", formula_version="+SUM(1,1)"))
    result = run_screen(records, query)
    path = export_screen_csv(result, query, tmp_path / "screen.csv")
    text = path.read_text(encoding="utf-8")
    assert "'=danger" in text
    assert "'@cmd" in text
    assert "' =HYPERLINK" in text
    assert "'+SUM" in text


def test_csv_export_rejects_result_from_a_different_input_dataset(tmp_path) -> None:
    query = bind_query([{"instrument_id": "A"}], ScreenQuery())
    result = run_screen([{"instrument_id": "B"}], query)
    with pytest.raises(ValueError, match="input dataset"):
        export_screen_csv(result, query, tmp_path / "screen.csv")


def test_saved_screen_rejects_oversized_deep_or_boolean_revision_records(tmp_path) -> None:
    path = save_screen("oversized", _query(), directory=tmp_path)
    path.write_bytes(b"{" + b" " * (1024 * 1024))
    with pytest.raises(ValueError, match="size limit"):
        load_screen("oversized", directory=tmp_path)

    path = save_screen("deep", _query(), directory=tmp_path)
    path.write_text('{"nested":' * 1100 + "null" + "}" * 1100, encoding="utf-8")
    with pytest.raises(ValueError, match="saved screen"):
        load_screen("deep", directory=tmp_path)

    path = save_screen("boolean revision", _query(), directory=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["revision"] = True
    payload.pop("record_checksum")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    import hashlib

    payload["record_checksum"] = hashlib.sha256(encoded).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid types"):
        load_screen("boolean revision", directory=tmp_path)


def test_revision_lock_retries_one_shot_windows_open_sharing_violation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "screen"
    directory.mkdir()
    real_open = screen_store.os.open
    lock = directory / ".revision.lock"
    calls = 0

    def flaky_open(path, flags, mode=0o777):
        nonlocal calls
        calls += 1
        if calls == 1:
            lock.write_text("{}", encoding="ascii")
            raise PermissionError("sharing violation")
        lock.unlink(missing_ok=True)
        return real_open(path, flags, mode)

    monkeypatch.setattr(screen_store.os, "open", flaky_open)
    with screen_store._revision_lock(directory):
        assert (directory / ".revision.lock").read_text(encoding="ascii").strip() == str(os.getpid())
    assert calls == 2
    assert not (directory / ".revision.lock").exists()


def test_revision_lock_persistent_open_sharing_violation_times_out(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "screen"
    directory.mkdir()
    (directory / ".revision.lock").write_text("{}", encoding="ascii")
    monkeypatch.setattr(screen_store, "_pid_alive", lambda _pid: True)
    ticks = iter((10.0, 15.0))
    monkeypatch.setattr(screen_store.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(screen_store.os, "open", lambda *_args: (_ for _ in ()).throw(PermissionError("sharing violation")))
    with pytest.raises(TimeoutError):
        with screen_store._revision_lock(directory):
            pass


def test_revision_lock_absent_open_permission_error_propagates(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "screen"
    directory.mkdir()
    monkeypatch.setattr(
        screen_store.os,
        "open",
        lambda *_args: (_ for _ in ()).throw(PermissionError("ACL denied")),
    )
    with pytest.raises(PermissionError, match="ACL denied"):
        with screen_store._revision_lock(directory):
            pass


@pytest.mark.parametrize(
    "owner_text",
    ["not-a-pid", str(os.getpid())],
    ids=["malformed-owner", "live-owner"],
)
def test_revision_lock_does_not_reclaim_malformed_or_live_stale_owner(
    tmp_path, owner_text: str, monkeypatch, request: pytest.FixtureRequest
) -> None:
    assert str(os.getpid()) not in request.node.nodeid
    directory = tmp_path / "screen"
    directory.mkdir()
    lock = directory / ".revision.lock"
    lock.write_text(owner_text + "\n", encoding="ascii")
    stale = time.time() - 60
    os.utime(lock, (stale, stale))
    ticks = iter((10.0, 15.0))
    monkeypatch.setattr(screen_store.time, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError):
        with screen_store._revision_lock(directory):
            pass
    assert lock.exists()


def test_revision_lock_reclaims_only_dead_stale_owner(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "screen"
    directory.mkdir()
    lock = directory / ".revision.lock"
    lock.write_text("999999\n", encoding="ascii")
    stale = time.time() - 60
    os.utime(lock, (stale, stale))
    monkeypatch.setattr(screen_store, "_pid_alive", lambda pid: pid != 999999)
    with screen_store._revision_lock(directory):
        assert lock.read_text(encoding="ascii").strip() == str(os.getpid())


def test_revision_lock_ownership_write_failure_cleans_owned_lock(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "screen"
    directory.mkdir()
    monkeypatch.setattr(screen_store.os, "write", lambda *_args: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(PermissionError):
        with screen_store._revision_lock(directory):
            pass
    assert not (directory / ".revision.lock").exists()
