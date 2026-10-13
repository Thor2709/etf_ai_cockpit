"""Bughunt D22 (#934): settings bundle torn reads, mixed generations, false failure after commit."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest
import yaml

from etf_cockpit.core import settings_bundle, ui_preferences
from etf_cockpit.core.settings_bundle import (
    SettingsError,
    _universe_summary,
    load_settings_bundle,
    save_settings,
)

_STORE = "universe_store.json"


def _store_bytes(ids: tuple[str, ...]) -> bytes:
    records = [{"instrument_id": item} for item in ids]
    return (json.dumps({"records": records}, indent=2) + "\n").encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()


def _install_read_hook(monkeypatch: pytest.MonkeyPatch, name: str, after_read) -> None:
    """Run ``after_read(n)`` after the n-th read (text or bytes) of the file called ``name``."""

    counter = {"n": 0}
    original_text = Path.read_text
    original_bytes = Path.read_bytes

    def fired(path: Path) -> bool:
        return path.name == name

    def read_text(self: Path, *args, **kwargs):
        value = original_text(self, *args, **kwargs)
        if fired(self):
            counter["n"] += 1
            after_read(counter["n"])
        return value

    def read_bytes(self: Path):
        value = original_bytes(self)
        if fired(self):
            counter["n"] += 1
            after_read(counter["n"])
        return value

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)


@pytest.mark.parametrize("swap_after_read", [1, 2])
def test_universe_identity_and_digest_always_come_from_one_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap_after_read: int
) -> None:
    config = tmp_path / "configs"
    config.mkdir()
    store = config / _STORE
    generation_a = _store_bytes(("AAA", "AAB"))
    generation_b = _store_bytes(("BBB",))
    store.write_bytes(generation_a)

    def swap(read_number: int) -> None:
        if read_number == swap_after_read:
            store.write_bytes(generation_b)

    _install_read_hook(monkeypatch, _STORE, swap)
    summary = _universe_summary(tmp_path)
    monkeypatch.undo()

    allowed = {
        (("AAA", "AAB"), _sha(generation_a)),
        (("BBB",), _sha(generation_b)),
    }
    assert (tuple(summary["instrument_ids"]), summary["revision"]) in allowed


def _cost_candidate(root: Path, *, bps: float):
    current = load_settings_bundle(root)
    costs = dict(current.costs)
    costs["broker"] = f"broker-{bps}"
    return current, current.model_copy(update={"costs": costs})


def test_reader_paused_mid_group_commit_gets_a_coherent_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, candidate = _cost_candidate(tmp_path, bps=11.0)
    state = {"committing": False, "yaml_calls": 0}
    outcome: dict[str, object] = {}
    real_group = settings_bundle.atomic_write_group
    real_validate_yaml = settings_bundle._validate_yaml

    def reader() -> None:
        try:
            outcome["bundle"] = load_settings_bundle(tmp_path)
        except BaseException as error:  # noqa: BLE001 - recorded for the assertion
            outcome["error"] = error

    reader_thread = threading.Thread(target=reader)

    def group(requests, *, lifecycle_hook=None, precondition=None):
        def hook(name, journal):
            if name == "committing":
                state["committing"] = True
            if lifecycle_hook is not None:
                lifecycle_hook(name, journal)

        return real_group(requests, lifecycle_hook=hook, precondition=precondition)

    def validate_yaml(path: Path) -> None:
        real_validate_yaml(path)
        if state["committing"]:
            state["yaml_calls"] += 1
            if state["yaml_calls"] == 3 and not reader_thread.is_alive():
                # Part of the group is already replaced; read now.
                reader_thread.start()
                reader_thread.join(0.4)

    monkeypatch.setattr(settings_bundle, "atomic_write_group", group)
    monkeypatch.setattr(settings_bundle, "_validate_yaml", validate_yaml)
    result = save_settings(candidate, expected_revision=old.revision, root=tmp_path)
    reader_thread.join(10)

    assert reader_thread.ident is not None, "the mid-commit read never ran"
    assert "error" not in outcome, outcome.get("error")
    assert outcome["bundle"].revision in {old.revision, result.revision}


def test_two_barrier_synchronised_saves_both_report_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = load_settings_bundle(tmp_path)
    first_candidate = base.model_copy(update={"costs": {**base.costs, "broker": "broker-11"}})
    first_preview = settings_bundle.preview_settings(first_candidate, expected_revision=base.revision, root=tmp_path)
    second_candidate = first_candidate.model_copy(update={"costs": {**first_candidate.costs, "broker": "broker-12"}})

    first_committed = threading.Event()
    second_done = threading.Event()
    real_group = settings_bundle.atomic_write_group
    main_thread = threading.current_thread()

    def group(requests, **kwargs):
        written = real_group(requests, **kwargs)
        if threading.current_thread() is not main_thread:
            first_committed.set()
            assert second_done.wait(30)
        return written

    monkeypatch.setattr(settings_bundle, "atomic_write_group", group)
    results: dict[str, object] = {}

    def run_first() -> None:
        try:
            results["first"] = save_settings(first_candidate, expected_revision=base.revision, root=tmp_path)
        except BaseException as error:  # noqa: BLE001
            results["first_error"] = error

    worker = threading.Thread(target=run_first)
    worker.start()
    assert first_committed.wait(30)
    try:
        second = save_settings(second_candidate, expected_revision=first_preview.after_revision, root=tmp_path)
    finally:
        second_done.set()
        worker.join(30)

    assert "first_error" not in results, results.get("first_error")
    first = results["first"]
    assert first.saved and first.committed and first.superseded
    assert second.saved and second.committed and not second.superseded
    versions = tmp_path / "data" / "derived" / "settings_versions"
    assert len(list(versions.glob("1-*.json"))) == 1
    assert len(list(versions.glob("2-*.json"))) == 1
    assert load_settings_bundle(tmp_path).revision == second.revision


def test_a_normal_save_is_unchanged(tmp_path: Path) -> None:
    old, candidate = _cost_candidate(tmp_path, bps=9.0)
    result = save_settings(candidate, expected_revision=old.revision, root=tmp_path)

    assert result.saved and result.committed and not result.superseded
    assert result.settings_version == 1
    assert result.execution_allowed is False
    assert load_settings_bundle(tmp_path).revision == result.revision
    snapshot = tmp_path / result.snapshot_path
    assert json.loads(snapshot.read_text(encoding="utf-8"))["revision"] == result.revision
    with pytest.raises(SettingsError) as error:
        save_settings(candidate, expected_revision=old.revision, root=tmp_path)
    assert error.value.code == "SETTINGS_REVISION_CONFLICT"


def test_ui_preference_saves_from_two_writers_do_not_lose_an_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D022-N003: a concurrent writer between read and write must not be overwritten."""

    ui_preferences.save_preference(ui_preferences.MISSING_DATA_PENALTY, False, root=tmp_path)
    first_read = threading.Event()
    second_saved = threading.Event()
    state = {"paused": False}
    holder = threading.current_thread()

    def after_read(_: int) -> None:
        if threading.current_thread() is not holder and not state["paused"]:
            state["paused"] = True
            first_read.set()
            second_saved.wait(30)

    _install_read_hook(monkeypatch, "ui_preferences.json", after_read)
    errors: list[BaseException] = []

    def first_writer() -> None:
        try:
            ui_preferences.save_preference(ui_preferences.MISSING_DATA_PENALTY, True, root=tmp_path)
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    worker = threading.Thread(target=first_writer)
    worker.start()
    assert first_read.wait(30)
    ui_preferences.save_preference(ui_preferences.SPAREBANK_PEERS, {"AAA": ["BBB"]}, root=tmp_path)
    second_saved.set()
    worker.join(60)
    monkeypatch.undo()

    assert not errors, errors
    stored = json.loads((tmp_path / "data" / "ui_preferences.json").read_text(encoding="utf-8"))
    assert stored[ui_preferences.MISSING_DATA_PENALTY] is True
    assert stored[ui_preferences.SPAREBANK_PEERS] == {"AAA": ["BBB"]}


def test_provider_settings_writer_goes_through_the_settings_revision(tmp_path: Path) -> None:
    """D022-N004: a direct data_providers.yaml write must not desynchronise the revision."""

    from etf_cockpit.core.config import save_provider_settings

    old, candidate = _cost_candidate(tmp_path, bps=8.0)
    saved = save_settings(candidate, expected_revision=old.revision, root=tmp_path)
    assert saved.settings_version == 1

    save_provider_settings(
        "prices",
        active_provider="yfinance",
        base_url="https://prices.example.invalid",
        api_key="",
        config_dir=tmp_path / "configs",
    )

    reloaded = load_settings_bundle(tmp_path)
    assert reloaded.settings_version == 2
    assert reloaded.providers["providers"]["prices"]["active_provider"] == "yfinance"
    written = yaml.safe_load((tmp_path / "configs" / "data_providers.yaml").read_text(encoding="utf-8"))
    assert written["providers"]["prices"]["base_url"] == "https://prices.example.invalid"
