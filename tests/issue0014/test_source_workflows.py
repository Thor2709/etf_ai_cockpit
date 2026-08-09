from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.core.config import DataProvidersConfig, ProviderSection
from etf_cockpit.core.migrations import MigrationContext, run_migrations
from etf_cockpit.data.providers import ManualLocalFileProvider
from etf_cockpit.data.provider_registry import ProviderRegistry
from etf_cockpit.data.universe_store import UniverseRecord, load_universe, save_universe
from etf_cockpit.features.training_centre import LocalTrainingRegistry
import etf_cockpit.features.training_centre as training_centre
from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.operations.recovery import recover_incomplete_transactions
from etf_cockpit.portfolio.paper_trading import EXECUTION_ALLOWED, NETWORK_ACCESS_ALLOWED, PaperLedger
from etf_cockpit.core.job_scheduler import DurableJobScheduler
from etf_cockpit.core.resource_profiles import HardwareSnapshot, ResourcePolicy

from tests.issue0014._support import paper_proposal, sha256_text, write_paper_proposal


def test_clean_offline_workflow_uses_local_fixture_and_keeps_authority_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ETF_COCKPIT_OFFLINE", "1")
    prices = tmp_path / "prices.csv"
    pd.DataFrame(
        [{"symbol": "VWCE", "date": "2026-01-02", "adjusted_close": 101.0, "currency": "EUR"}]
    ).to_csv(prices, index=False)

    result = ManualLocalFileProvider().import_file(prices, "prices")
    policy = load_gate_policy()

    assert result.status == "ok"
    assert result.metadata is not None
    assert result.metadata.as_of_date == date(2026, 1, 2)
    assert policy.policy is not None and policy.policy.execution_allowed is False
    assert os.getenv("ETF_COCKPIT_OFFLINE") == "1"


def test_best_effort_online_timeout_is_visible_non_destructive_and_non_executable(
    tmp_path: Path,
) -> None:
    config = DataProvidersConfig(
        providers={"prices": ProviderSection(active_provider="stooq", base_url="https://example.invalid")}
    )
    registry = ProviderRegistry(config)
    registry.register_probe("prices", lambda: (_ for _ in ()).throw(TimeoutError("fixture timeout")))
    before = tuple(sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")))

    capability = next(item for item in registry.probe_all() if item.provider_id == "prices")
    rows = registry.status_rows((capability,))
    after = tuple(sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")))

    assert capability.status == "timeout"
    assert "probe failed" in capability.message.lower()
    assert rows[0]["executable_authority"] is False
    assert before == after


def test_migration_and_large_universe_journey_is_repeatable(tmp_path: Path) -> None:
    context = MigrationContext(root=tmp_path, backup_root=tmp_path / "backups")
    first = run_migrations(context)
    second = run_migrations(context)
    records = tuple(
        UniverseRecord(
            instrument_id=f"ETF-{index:04d}",
            name=f"Fixture ETF {index:04d}",
            isin=f"NO{index:010d}",
            ticker=f"ETF{index:04d}",
            tier="primary" if index < 100 else "secondary",
        )
        for index in range(250)
    )
    saved = save_universe(records, expected_revision="", root=tmp_path)
    loaded = load_universe(tmp_path)

    assert first.applied_versions == (1, 2, 3, 4)
    assert second.applied_versions == ()
    assert json.loads((tmp_path / "data" / ".migration_state.json").read_text())["schema_version"] == 4
    assert saved.record_count == 250
    assert loaded.records == records
    assert all(record.enabled for record in loaded.records)


def test_training_journey_runs_locally_replays_lineage_and_cannot_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The durable scheduler normally chooses a host profile. Pin the fixture to
    # the deterministic minimum profile so it is runnable on small CI workers.
    snapshot = HardwareSnapshot(
        platform="fixture",
        cpu_cores=2,
        memory_total_mb=4096,
        memory_available_mb=4096,
        disk_free_mb=10000,
        gpu_available=False,
        gpu_label="",
        source="issue0014-fixture",
    )

    def fixture_scheduler(root: Path, **kwargs: object) -> DurableJobScheduler:
        return DurableJobScheduler(
            root,
            resource_policy=ResourcePolicy(root, requested_profile="minimum", snapshot=snapshot),
            **kwargs,
        )

    monkeypatch.setattr(training_centre, "DurableJobScheduler", fixture_scheduler)
    registry = LocalTrainingRegistry(tmp_path)
    hashes = {name: sha256_text(name) for name in ("dataset", "features", "code", "environment")}
    experiment = registry.create_experiment("issue0014")
    run = registry.create_run(
        str(experiment["experiment_id"]),
        dataset_hash=hashes["dataset"],
        feature_hash=hashes["features"],
        code_hash=hashes["code"],
        environment_hash=hashes["environment"],
        run_id="run_issue0014",
    )
    registry.submit_run(str(run["run_id"]))
    registry.run_next_job(lambda _context: {"metric": 0.25})
    completed = registry.get("training.run", "run_issue0014")
    replay = registry.replay(
        "run_issue0014",
        dataset_hash=hashes["dataset"],
        feature_hash=hashes["features"],
        code_hash=hashes["code"],
        environment_hash=hashes["environment"],
    )

    assert completed is not None and completed["status"] == "completed"
    assert completed["execution_allowed"] is False
    assert replay.replayable is True
    assert registry.execution_allowed is False


def test_paper_broker_journey_is_restartable_and_never_networked(tmp_path: Path) -> None:
    proposal = paper_proposal()
    write_paper_proposal(tmp_path, proposal)
    ledger = PaperLedger(tmp_path)
    opened = ledger.open_account(initial_cash=1_000)
    order = ledger.accept_proposal(proposal, execution_price=10)
    ledger.record_fill(str(order["order_id"]), quantity=10, price=10)
    marked = ledger.mark("VWCE", adjusted_close=12, source_checksum="a" * 64)
    restarted = PaperLedger(tmp_path).snapshot()

    assert opened.status == "ready"
    assert marked.to_payload()["execution_allowed"] is False
    assert restarted.to_payload() == marked.to_payload()
    assert EXECUTION_ALLOWED is False
    assert NETWORK_ACCESS_ALLOWED is False


def test_recovery_journey_rolls_back_to_the_last_complete_generation(tmp_path: Path) -> None:
    destination = tmp_path / "data" / "current.bin"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    transaction_root = tmp_path / ".atomic-transactions" / "issue0014"
    transaction_root.mkdir(parents=True)
    (transaction_root / "journal.json").write_text("{\"transaction_id\":", encoding="utf-8")

    outcome = recover_incomplete_transactions(tmp_path, event_path=tmp_path / "logs" / "session.jsonl")

    assert outcome[0].startup_mode == "read_only"
    assert outcome[0].state == "recovery_required"
    assert destination.read_bytes() == b"old"
