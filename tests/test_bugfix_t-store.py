from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.core.job_scheduler import DurableJobScheduler, JobSpec
from etf_cockpit.data import duckdb_store, score_history
from etf_cockpit.data.bitemporal import BitemporalStore
from etf_cockpit.data.import_export import ImportService, validate_import
from etf_cockpit.data.local_storage import TransactionalStore
from etf_cockpit.features.training_centre import LocalTrainingRegistry, TrainingRegistryError
from etf_cockpit.portfolio.paper_trading import PaperLedger, PaperLedgerError
from etf_cockpit.security import credentials
from etf_cockpit.security.credentials import CredentialVault


_CHECKSUM = "a" * 64
_RUN_HASHES = {
    "dataset_hash": "b" * 64,
    "feature_hash": "c" * 64,
    "code_hash": "d" * 64,
    "environment_hash": "e" * 64,
}


def _record_bitemporal(
    store: BitemporalStore,
    *,
    entity_id: str,
    stable_id: str,
    source_id: str,
    revision: int,
    available_at: str,
    value: str,
    valid_from: str = "2025-12-31T00:00:00Z",
    valid_to: str | None = "2026-12-31T00:00:00Z",
):
    return store.record_observation(
        dataset_id="fundamentals",
        entity_id=entity_id,
        stable_id=stable_id,
        run_id=f"run-{entity_id}-{source_id}-{revision}-{value}",
        value={"value": value},
        valid_from=valid_from,
        valid_to=valid_to,
        published_at=available_at,
        available_at=available_at,
        observed_at=available_at,
        ingested_at=available_at,
        revised_at=available_at if revision > 1 else None,
        revision=revision,
        source_id=source_id,
        source_checksum=_CHECKSUM,
        timezone_confidence="exact",
        availability_confidence="exact",
    )


def _training_registry(root: Path) -> tuple[LocalTrainingRegistry, str]:
    registry = LocalTrainingRegistry(root)
    experiment = registry.create_experiment("bugfix test", experiment_id="exp-bugfix")
    return registry, str(experiment["experiment_id"])


def _create_training_run(
    registry: LocalTrainingRegistry,
    experiment_id: str,
    *,
    run_id: str,
    parameters: dict[str, object] | None = None,
) -> dict[str, object]:
    return registry.create_run(
        experiment_id,
        run_id=run_id,
        parameters=parameters,
        **_RUN_HASHES,
    )


def test_chat_p08_n002_verifies_the_full_event_chain(tmp_path: Path) -> None:
    # Each queued one-job workflow contributes two events, exceeding the UI cap.
    scheduler = DurableJobScheduler(tmp_path)
    for index in range(501):
        scheduler.submit(
            "test",
            "Chain test",
            (JobSpec("job", "Queued job"),),
            workflow_id=f"workflow-{index}",
            dedupe_key=f"dedupe-{index}",
        )

    assert scheduler.verify_event_chain()
    with TransactionalStore(tmp_path) as store:
        with store.transaction() as connection:
            assert connection.execute("SELECT COUNT(*) FROM durable_job_events").fetchone()[0] >= 1001
            connection.execute("UPDATE durable_job_events SET event_type = 'tampered' WHERE event_id = 500")
    assert not scheduler.verify_event_chain()


def test_p02_n001_as_of_keeps_same_stable_id_for_each_entity(tmp_path: Path) -> None:
    with BitemporalStore(tmp_path) as store:
        _record_bitemporal(
            store,
            entity_id="ETF-A",
            stable_id="metric:earnings",
            source_id="source:A",
            revision=1,
            available_at="2026-01-02T10:00:00Z",
            value="A",
        )
        _record_bitemporal(
            store,
            entity_id="ETF-B",
            stable_id="metric:earnings",
            source_id="source:B",
            revision=1,
            available_at="2026-01-02T10:00:00Z",
            value="B",
        )

        view = store.as_of("fundamentals", "2026-01-03T00:00:00Z")

    assert set(view["entity_id"]) == {"ETF-A", "ETF-B"}
    assert set(view["value"].map(lambda value: value["value"])) == {"A", "B"}


@pytest.mark.parametrize("newer_source", ["source:A", "source:B"])
def test_p02_n002_retracting_an_older_revision_keeps_the_newer_one(
    tmp_path: Path,
    newer_source: str,
) -> None:
    with BitemporalStore(tmp_path) as store:
        first = _record_bitemporal(
            store,
            entity_id="ETF-A",
            stable_id="metric:earnings",
            source_id="source:A",
            revision=1,
            available_at="2026-01-02T10:00:00Z",
            value="first",
        )
        second = _record_bitemporal(
            store,
            entity_id="ETF-A",
            stable_id="metric:earnings",
            source_id=newer_source,
            revision=2,
            available_at="2026-02-02T10:00:00Z",
            value="second",
        )

        marker = store.record_retraction(
            first.observation_id,
            available_at="2026-03-02T10:00:00Z",
            run_id="run-retraction",
            reason="withdrawn older observation",
        )
        view = store.as_of("fundamentals", "2026-03-03T00:00:00Z")

    assert marker.revision == (3 if newer_source == "source:A" else 2)
    assert len(view) == 1
    assert view.iloc[0]["observation_id"] == second.observation_id


@pytest.mark.parametrize(
    ("valid_from", "valid_to"),
    [
        ("2026-02-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    ],
)
def test_p02_n007_rejects_non_positive_validity_intervals(
    tmp_path: Path,
    valid_from: str,
    valid_to: str,
) -> None:
    with BitemporalStore(tmp_path) as store:
        with pytest.raises(ValueError, match="valid_to must be after valid_from"):
            _record_bitemporal(
                store,
                entity_id="ETF-A",
                stable_id="metric:earnings",
                source_id="source:A",
                revision=1,
                available_at="2026-01-02T10:00:00Z",
                value="invalid",
                valid_from=valid_from,
                valid_to=valid_to,
            )


def test_p02_n008_custom_missing_paths_do_not_bootstrap_default_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(duckdb_store, "initialise_store", lambda: calls.append(True))

    for loader in (duckdb_store.load_prices, duckdb_store.load_holdings):
        with pytest.raises(FileNotFoundError):
            loader(tmp_path / f"missing-{loader.__name__}")

    assert calls == []


def test_p02_n010_score_cache_key_includes_formula_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pyarrow.parquet as parquet

    root = tmp_path / "root"
    path = root / "data" / "derived" / "score_history.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"test placeholder")
    columns = [
        "instrument_id",
        "run_id",
        "final_combined_score_10",
        "coverage",
        "missing_components",
        "data_as_of_date",
        "formula_version",
    ]
    monkeypatch.setattr(parquet, "read_schema", lambda _path: SimpleNamespace(names=columns))
    monkeypatch.setattr(
        score_history.pd,
        "read_parquet",
        lambda *_args, **_kwargs: pd.DataFrame(
            [
                {"instrument_id": "ETF-A", "run_id": "sparebank:ETF-A:1", "final_combined_score_10": 1.0, "coverage": 1.0, "missing_components": [], "data_as_of_date": "2026-01-01", "formula_version": "formula-v1"},
                {"instrument_id": "ETF-A", "run_id": "sparebank:ETF-A:2", "final_combined_score_10": 2.0, "coverage": 1.0, "missing_components": [], "data_as_of_date": "2026-01-02", "formula_version": "formula-v2"},
            ]
        ),
    )
    current = {"value": "formula-v1"}
    monkeypatch.setattr(score_history, "_current_sparebank_formula_version", lambda: current["value"])
    score_history._SPAREBANK_CACHE.clear()

    first = score_history.latest_sparebank_scores(root=root)
    current["value"] = "formula-v2"
    second = score_history.latest_sparebank_scores(root=root)

    assert first["ETF-A"]["final_combined_score_10"] == 1.0
    assert second["ETF-A"]["final_combined_score_10"] == 2.0


def test_p02_n011_mixed_holdings_dates_are_rejected_without_writing(tmp_path: Path) -> None:
    source = tmp_path / "mixed-dates.csv"
    pd.DataFrame(
        {
            "as_of_date": ["2026-07-10", "2026-07-11"],
            "etf_id": ["ETF-A", "ETF-A"],
            "holding_name": ["Issuer A", "Issuer B"],
            "weight": [0.5, 0.5],
        }
    ).to_csv(source, index=False)
    preview = validate_import("etf_holdings", source)
    service = ImportService(tmp_path)
    service.register(preview)

    assert preview.valid is False
    assert "multiple_as_of_dates_not_allowed:as_of_date" in preview.errors
    with pytest.raises(ValueError, match="valid import preview"):
        service.commit(preview.preview_id)
    assert not (tmp_path / "data" / "clean" / "fund_holdings.parquet").exists()


@pytest.mark.parametrize("next_status", ["running", "queued"])
def test_p04_n013_terminal_training_run_cannot_be_reactivated(
    tmp_path: Path,
    next_status: str,
) -> None:
    registry, experiment_id = _training_registry(tmp_path)
    _create_training_run(registry, experiment_id, run_id="run-terminal")
    registry.update_run("run-terminal", status="completed")

    with pytest.raises(TrainingRegistryError, match="terminal run status cannot be changed"):
        registry.update_run("run-terminal", status=next_status)  # type: ignore[arg-type]


def test_p04_n017_auto_run_id_includes_canonical_non_empty_parameters(tmp_path: Path) -> None:
    registry, experiment_id = _training_registry(tmp_path)

    first = registry.create_run(experiment_id, parameters={"lr": 0.1, "batch": 16}, **_RUN_HASHES)
    same = registry.create_run(experiment_id, parameters={"batch": 16, "lr": 0.1}, **_RUN_HASHES)
    different = registry.create_run(experiment_id, parameters={"lr": 0.01, "batch": 16}, **_RUN_HASHES)

    assert first["run_id"] == same["run_id"]
    assert first["run_id"] != different["run_id"]


def test_p07_n019_corrupt_paper_ledger_raises_and_empty_ledger_is_empty(tmp_path: Path) -> None:
    api = LocalApplicationApi(lambda: None, root=tmp_path)
    assert api.get_paper_orders().total == 0

    ledger = PaperLedger(tmp_path)
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    ledger.path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(PaperLedgerError):
        api.get_paper_orders()


def test_p08_n004_concurrent_credential_sets_keep_both_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def transform(payload: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in payload)

    monkeypatch.setattr(credentials, "_protect", transform)
    monkeypatch.setattr(credentials, "_unprotect", transform)
    monkeypatch.setattr(credentials, "_dpapi_available", lambda: True)
    monkeypatch.setattr(credentials, "_invalidate_probe_cache", lambda _name: None)
    vault = CredentialVault(tmp_path / "vault.dpapi")
    vault.set("seed", "existing")
    original_read = CredentialVault._read_entries

    def slow_read(path: Path) -> dict[str, str]:
        entries = original_read(path)
        time.sleep(0.05)
        return entries

    monkeypatch.setattr(CredentialVault, "_read_entries", staticmethod(slow_read))
    barrier = Barrier(2)

    def set_credential(account: str, value: str) -> None:
        barrier.wait()
        vault.set(account, value)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(set_credential, "account-a", "value-a")
        second = pool.submit(set_credential, "account-b", "value-b")
        first.result()
        second.result()

    assert vault.get("account-a") == "value-a"
    assert vault.get("account-b") == "value-b"
