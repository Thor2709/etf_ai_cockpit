from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import threading

import pandas as pd
import pytest

from etf_cockpit.core.workflow import WorkflowTransitionError

from etf_cockpit.parsers import sec_facts
from etf_cockpit.parsers.contracts import RawDocument
from etf_cockpit.parsers.sec_facts import StatementFact, write_statement_evidence, write_statement_facts, write_statement_inventory


def _record(cik: str, value: int) -> StatementFact:
    return StatementFact(
        instrument_id=f"I{cik}", cik=cik, taxonomy="us-gaap", concept="Assets", unit="USD", value=value,
        start=None, end="2024-12-31", instant="2024-12-31", filed="2025-01-01", form="10-K", accession=f"000000{cik}-24-000001",
        fiscal_year=2024, fiscal_period="FY", source_id=f"sec_edgar:{cik}:assets:{value}", canonical_metric="assets", mapping_status="mapped",
    )


def _source(tmp_path: Path, cik: str) -> RawDocument:
    path = tmp_path / f"{cik}.json"
    path.write_text(json.dumps({"cik": cik, "facts": {}}), encoding="utf-8")
    return RawDocument(path, f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", datetime.now(timezone.utc), hashlib.sha256(path.read_bytes()).hexdigest(), "sec_edgar", "sec_companyfacts", "application/json", 200)


def test_unserialised_read_modify_write_loses_a_record_demonstrating_risk(tmp_path: Path) -> None:
    destination = tmp_path / "facts.parquet"
    barrier = threading.Barrier(2)

    def unsafe(record: StatementFact) -> None:
        frame = sec_facts._ordered_statement_facts(sec_facts._statement_facts_write_frame((record,), destination, ()))
        barrier.wait(timeout=5)
        sec_facts.atomic_write_bytes(destination, sec_facts.parquet_payload(frame), sec_facts.validate_parquet_file)

    workers = [threading.Thread(target=unsafe, args=(_record(str(index), index),)) for index in (1, 2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive()

    assert len(pd.read_parquet(destination)) == 1


def test_statement_evidence_serializes_concurrent_read_modify_write(tmp_path: Path) -> None:
    facts_destination = tmp_path / "facts.parquet"
    inventory_destination = tmp_path / "inventory.parquet"
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def publish(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            source = _source(tmp_path, str(index))
            write_statement_evidence(source, (_record(str(index), index),), facts_destination, inventory_destination, instrument_id=f"I{index}")
        except BaseException as exc:
            errors.append(exc)

    workers = [threading.Thread(target=publish, args=(index,)) for index in (1, 2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive()

    assert errors == []
    assert set(pd.read_parquet(facts_destination)["instrument_id"]) == {"I1", "I2"}
    assert set(pd.read_parquet(inventory_destination)["instrument_id"]) == {"I1", "I2"}


def test_each_public_statement_writer_uses_durable_store_contract(tmp_path: Path) -> None:
    facts_destination = tmp_path / "facts.parquet"
    inventory_destination = tmp_path / "inventory.parquet"
    record = _record("1", 1)
    source = _source(tmp_path, "1")

    assert write_statement_facts((record,), facts_destination) == facts_destination
    assert write_statement_inventory(source, (record,), inventory_destination, instrument_id="I1") == inventory_destination
    assert write_statement_evidence(source, (record,), facts_destination, inventory_destination, instrument_id="I1") == (facts_destination, inventory_destination)

    assert len(pd.read_parquet(facts_destination)) == 1
    assert len(pd.read_parquet(inventory_destination)) == 1


def test_cross_writer_public_calls_serialize_stale_read_interleave(tmp_path: Path) -> None:
    facts_destination = tmp_path / "facts.parquet"
    inventory_destination = tmp_path / "inventory.parquet"
    barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def run_facts() -> None:
        try:
            barrier.wait(timeout=5)
            write_statement_facts((_record("1", 1),), facts_destination)
        except BaseException as exc:
            errors.append(exc)

    def run_inventory() -> None:
        try:
            barrier.wait(timeout=5)
            source = _source(tmp_path, "1")
            write_statement_inventory(source, (_record("1", 1),), inventory_destination, instrument_id="I1")
        except BaseException as exc:
            errors.append(exc)

    def run_evidence() -> None:
        try:
            barrier.wait(timeout=5)
            source = _source(tmp_path, "2")
            write_statement_evidence(source, (_record("2", 2),), facts_destination, inventory_destination, instrument_id="I2")
        except BaseException as exc:
            errors.append(exc)

    workers = [threading.Thread(target=target) for target in (run_facts, run_inventory, run_evidence)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive()

    assert errors == []
    assert set(pd.read_parquet(facts_destination)["instrument_id"]) == {"I1", "I2"}
    assert set(pd.read_parquet(inventory_destination)["instrument_id"]) == {"I1", "I2"}


def test_store_guard_order_deduplicates_resolved_destinations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entered: list[Path] = []
    exited: list[Path] = []

    @contextmanager
    def guard(path):
        entered.append(path)
        try:
            yield
        finally:
            exited.append(path)

    monkeypatch.setattr(sec_facts, "persistent_file_guard", guard)
    first = tmp_path / "A.parquet"
    last = tmp_path / "z.parquet"
    with sec_facts._statement_store_guards((last, first, tmp_path / "nested/../A.parquet")):
        assert entered == [first.with_suffix(".parquet.guard"), last.with_suffix(".parquet.guard")]
        assert exited == []
    assert exited == list(reversed(entered))


@pytest.mark.parametrize("failure_type", [WorkflowTransitionError, KeyboardInterrupt])
def test_failed_paired_publication_preserves_generation_and_releases_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_type,
) -> None:
    facts = tmp_path / "facts.parquet"
    inventory = tmp_path / "inventory.parquet"
    first = _source(tmp_path, "1")
    write_statement_evidence(first, (_record("1", 1),), facts, inventory, instrument_id="I1")
    before = (facts.read_bytes(), inventory.read_bytes())
    failure = failure_type("publication interrupted")
    original_publish = sec_facts.atomic_write_group

    def interrupt(*args, **kwargs):
        raise failure

    monkeypatch.setattr(sec_facts, "atomic_write_group", interrupt)
    with pytest.raises(failure_type) as caught:
        write_statement_evidence(_source(tmp_path, "2"), (_record("2", 2),), facts, inventory, instrument_id="I2")
    assert caught.value is failure
    assert (facts.read_bytes(), inventory.read_bytes()) == before
    monkeypatch.setattr(sec_facts, "atomic_write_group", original_publish)
    # A successful subsequent paired write proves that both non-reentrant
    # sidecars were released, including for BaseException cancellation.
    write_statement_evidence(_source(tmp_path, "2"), (_record("2", 2),), facts, inventory, instrument_id="I2")
    assert set(pd.read_parquet(facts)["instrument_id"]) == {"I1", "I2"}
    assert set(pd.read_parquet(inventory)["instrument_id"]) == {"I1", "I2"}

@pytest.mark.parametrize("next_operation", ["paired", "facts", "inventory", "trust", "checkpoint"])
def test_pending_partial_pair_recovers_before_read_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, next_operation: str,
) -> None:
    from etf_cockpit.core.atomic_io import AtomicWriteInterrupted
    from etf_cockpit.data import trust_artifacts

    facts = tmp_path / "facts.parquet"
    inventory = tmp_path / "inventory.parquet"
    write_statement_evidence(_source(tmp_path, "1"), (_record("1", 1),), facts, inventory, instrument_id="I1")
    original_replace = Path.replace

    def interrupt_after_facts(path, destination):
        result = original_replace(path, destination)
        if Path(destination) == facts:
            raise AtomicWriteInterrupted("crash after first replacement")
        return result

    with monkeypatch.context() as crash:
        crash.setattr(Path, "replace", interrupt_after_facts)
        with pytest.raises(AtomicWriteInterrupted):
            write_statement_evidence(_source(tmp_path, "2"), (_record("2", 2),), facts, inventory, instrument_id="I2")
    assert set(pd.read_parquet(facts)["instrument_id"]) == {"I1", "I2"}
    assert set(pd.read_parquet(inventory)["instrument_id"]) == {"I1"}
    source = _source(tmp_path, "3")
    if next_operation == "paired":
        write_statement_evidence(source, (_record("3", 3),), facts, inventory, instrument_id="I3")
    elif next_operation == "facts":
        write_statement_facts((_record("3", 3),), facts)
    elif next_operation == "inventory":
        write_statement_inventory(source, (_record("3", 3),), inventory, instrument_id="I3")
    elif next_operation == "trust":
        monkeypatch.setattr(trust_artifacts, "FILINGS_STATEMENTS_PATH", inventory)
        monkeypatch.setattr(trust_artifacts, "_local_document_inventory", lambda *_: pd.DataFrame([{"document_id": "local:3", "checksum": "3", "instrument_id": "I3"}]))
        trust_artifacts._append_filings_statement_inventory(pd.DataFrame())
    else:
        with sec_facts._statement_store_guards((facts, inventory)):
            assert set(pd.read_parquet(facts)["instrument_id"]) == {"I1"}
            assert set(pd.read_parquet(inventory)["instrument_id"]) == {"I1"}
    assert set(pd.read_parquet(facts)["instrument_id"]) == ({"I1", "I3"} if next_operation in {"paired", "facts"} else {"I1"})
    assert set(pd.read_parquet(inventory)["instrument_id"]) == ({"I1", "I3"} if next_operation in {"paired", "inventory", "trust"} else {"I1"})
    assert not list(tmp_path.rglob(".atomic-write-group.lock"))
