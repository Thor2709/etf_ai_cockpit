from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.contracts import (
    PaperAccountOpenRequest,
    PaperFillRequest,
    PaperPositionMarkRequest,
    PaperProposalAcceptRequest,
)
from etf_cockpit.core.atomic_io import verify_backup_manifest
from etf_cockpit.core.config import ProviderSection
from etf_cockpit.core.job_scheduler import DurableJobScheduler
from etf_cockpit.core.migrations import MigrationContext, run_migrations
from etf_cockpit.core.resource_profiles import HardwareSnapshot, ResourcePolicy
from etf_cockpit.data.providers import ManualLocalFileProvider
from etf_cockpit.data.universe_store import UniverseRecord, load_universe, save_universe
from etf_cockpit.data.yfinance_provider import YFinanceProvider
from etf_cockpit.features.training_centre import LocalTrainingRegistry
import etf_cockpit.features.training_centre as training_centre
from etf_cockpit.governance.product_scope import load_gate_policy
from etf_cockpit.operations.recovery import recover_incomplete_transactions
from etf_cockpit.portfolio.paper_trading import PaperLedgerError
from tests.operations.test_recovery import _interrupted_transaction

from tests.issue0014._support import (
    ROOT,
    copy_repository_runtime,
    isolated_environment,
    paper_proposal,
    sha256_text,
    write_paper_proposal,
)


def _api_snapshot() -> SimpleNamespace:
    instrument = SimpleNamespace(
        id="VWCE",
        name="Fixture ETF",
        ticker="VWCE.DE",
        asset_class="equity",
        region="EU",
        currency="EUR",
        enabled=True,
    )
    return SimpleNamespace(
        config=SimpleNamespace(universe=SimpleNamespace(etfs=[instrument])),
        prices=pd.DataFrame(),
        holdings=pd.DataFrame(),
        forecasts=pd.DataFrame(),
        signals=[],
        universe_revision="issue0014",
    )


def test_clean_offline_workflow_uses_local_fixture_and_keeps_authority_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ETF_COCKPIT_OFFLINE", "1")
    prices = tmp_path / "prices.csv"
    pd.DataFrame(
        [{"symbol": "VWCE", "date": "2026-01-02", "adjusted_close": 101.0, "currency": "EUR"}]
    ).to_csv(prices, index=False)

    result = ManualLocalFileProvider().import_file(prices, "prices")

    assert result.status == "ok"
    assert result.metadata is not None
    assert result.metadata.as_of_date == date(2026, 1, 2)
    assert result.metadata.provider_or_manual_source == str(prices)
    assert prices.is_relative_to(tmp_path)


def test_optional_yfinance_transport_timeout_is_visible_and_non_destructive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def timeout(symbol: str, **_kwargs: object) -> pd.DataFrame:
        calls.append(symbol)
        raise TimeoutError("fixture transport timeout")

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=timeout))
    provider = YFinanceProvider(ProviderSection(symbols_map={"VWCE": "VWCE.DE"}))
    before = tuple(tmp_path.rglob("*"))

    result = provider.fetch_prices([], date(2026, 1, 1), date(2026, 2, 1))

    assert calls == ["VWCE.DE"]
    assert result.status == "error"
    assert "TimeoutError" in result.message
    assert result.data is None
    assert tuple(tmp_path.rglob("*")) == before
    policy = load_gate_policy()
    assert policy.policy is not None and policy.policy.execution_allowed is False


def test_complete_suite_denies_non_loopback_sockets() -> None:
    with pytest.raises(PermissionError, match="denied non-loopback"):
        socket.create_connection(("198.51.100.1", 443), timeout=0.01)


def test_migration_backs_up_managed_legacy_data_and_large_universe_repeats(tmp_path: Path) -> None:
    managed = tmp_path / "data" / "provider_status.json"
    managed.parent.mkdir(parents=True)
    legacy_payload = b'{"provider":"yfinance","state":"legacy","observations":17}'
    managed.write_bytes(legacy_payload)
    legacy_sha = hashlib.sha256(legacy_payload).hexdigest()
    context = MigrationContext(
        root=tmp_path,
        backup_root=tmp_path / "backups",
        managed_paths=(managed,),
    )

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
    assert second.applied_versions == () and second.backup_manifest is None
    assert first.backup_manifest is not None and verify_backup_manifest(first.backup_manifest)
    entry = next(item for item in first.backup_manifest.entries if item.source_path == managed.resolve())
    assert entry.sha256 == legacy_sha
    assert entry.backup_path.read_bytes() == legacy_payload
    assert managed.read_bytes() == legacy_payload
    assert saved.record_count == 250
    assert loaded.records == records


def test_training_journey_runs_locally_replays_lineage_and_cannot_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_paper_journey_uses_application_api_persisted_proposal_and_restarts(tmp_path: Path) -> None:
    proposal = paper_proposal()
    write_paper_proposal(tmp_path, proposal)
    api = LocalApplicationApi(_api_snapshot, root=tmp_path)

    opened = api.open_paper_account(PaperAccountOpenRequest(initial_cash=1_000))
    order = api.accept_paper_proposal(
        PaperProposalAcceptRequest(proposal_id=str(proposal["proposal_id"]), execution_price=10)
    )
    filled = api.fill_paper_order(
        PaperFillRequest(order_id=order.order_id, quantity=10, price=10)
    )
    marked = api.mark_paper_position(
        PaperPositionMarkRequest(
            instrument_id="VWCE",
            adjusted_close=12,
            as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
            source_authority="issue0014-adjusted-close",
            source_checksum="a" * 64,
        )
    )
    restarted = LocalApplicationApi(_api_snapshot, root=tmp_path).get_paper().items[0]

    assert opened.execution_allowed is False
    assert order.execution_allowed is False and filled.execution_allowed is False
    assert marked.execution_allowed is False
    assert restarted.model_dump() == marked.model_dump()


@pytest.mark.parametrize("tamper", ["execution", "missing", "authority"])
def test_paper_application_api_rejects_unsafe_or_unvalidated_proposals(
    tmp_path: Path, tamper: str
) -> None:
    proposal = paper_proposal()
    proposal_id = str(proposal["proposal_id"])
    if tamper == "execution":
        proposal["execution_allowed"] = True
        write_paper_proposal(tmp_path, proposal)
    elif tamper == "authority":
        proposal["authority_policy_checksum"] = "0" * 64
        write_paper_proposal(tmp_path, proposal)
    api = LocalApplicationApi(_api_snapshot, root=tmp_path)
    api.open_paper_account(PaperAccountOpenRequest(initial_cash=1_000))

    with pytest.raises(PaperLedgerError, match="Validated proposal not found"):
        api.accept_paper_proposal(
            PaperProposalAcceptRequest(proposal_id=proposal_id, execution_price=10)
        )


def test_recovery_restores_valid_interrupted_generation_and_writes_audit_event(tmp_path: Path) -> None:
    destination = _interrupted_transaction(tmp_path, "committing")
    event_path = tmp_path / "logs" / "session.jsonl"
    unrelated = tmp_path / "data" / "unrelated.bin"
    unrelated.write_bytes(b"preserve")

    outcome = recover_incomplete_transactions(tmp_path, event_path=event_path)
    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[-1])

    assert outcome[0].state == "rolled_back"
    assert outcome[0].startup_mode == "normal"
    assert destination.read_bytes() == b"old"
    assert unrelated.read_bytes() == b"preserve"
    assert outcome[0].evidence_checksums["journal_sha256"]
    assert event["event_type"] == "write_transaction_recovery"
    assert event["status"] == "rolled_back"
    assert event["transaction_id"] == "tx-committing"
    assert event["event_hash"]


def test_canonical_main_workflow_composes_real_local_apis_without_network(tmp_path: Path) -> None:
    runtime_root = copy_repository_runtime(tmp_path / "runtime")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "issue0014" / "workflow_probe.py"), "main"],
        cwd=runtime_root,
        env=isolated_environment(runtime_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout.splitlines()[-1])
    assert payload["download_calls"] > 0
    candidate_fixture = Path(payload["candidate_fixture"])
    assert candidate_fixture.is_file() and candidate_fixture.is_relative_to(runtime_root)
    assert "Validated and committed" in payload["refresh"]
    assert "Scoreboard updated" in payload["algorithms"]
    assert payload["forecast_state"] in {"available", "unavailable"}
    assert payload["forecasts"].strip()
    assert payload["scoreboard_exists"] is True
    assert payload["audit_exists"] is True
    assert payload["execution_allowed"] is False
    assert Path(payload["scoreboard"]).is_relative_to(runtime_root)
    assert Path(payload["audit"]).is_relative_to(runtime_root)
