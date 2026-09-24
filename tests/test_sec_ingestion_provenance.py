from __future__ import annotations

import json
import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
from etf_cockpit.parsers.contracts import RawDocument


def _state(state_module):
    state = state_module.AppState.__new__(state_module.AppState)
    state.last_message = "Ready"
    state.selected_etf = "SELECTED_ETF"
    state.snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=[])))
    return state


def _payload() -> bytes:
    return json.dumps(
        {
            "cik": "0000789019",
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {
                                    "val": 10,
                                    "end": "2024-12-31",
                                    "form": "10-K",
                                    "filed": "2025-02-01",
                                }
                            ]
                        }
                    }
                }
            },
        }
    ).encode("utf-8")


def _document(path: Path) -> RawDocument:
    return RawDocument(
        path,
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json",
        datetime.now(timezone.utc),
        hashlib.sha256(path.read_bytes()).hexdigest(),
        "sec_edgar",
        "sec_companyfacts",
        "application/json",
        200,
    )


def test_fetch_companyfacts_preserves_fresh_and_revalidated_document_provenance(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    cache_dir = tmp_path / "cache"
    responses = [(_payload(), 200, {"ETag": '"facts-v1"'}), (b"", 304, {})]
    provider = SecEdgarProvider(
        "ETF AI Cockpit provenance tests research@company.org",
        cache_dir=cache_dir,
        transport=lambda _url, _headers: responses.pop(0),
        rate_limit_seconds=0,
    )
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "inventory.parquet")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    state = _state(state_module)

    first_message = state.fetch_sec_companyfacts("789019", cache_dir=cache_dir, user_agent=provider.user_agent)
    metadata = json.loads((cache_dir / "companyfacts_0000789019.json.meta.json").read_text(encoding="utf-8"))
    first_inventory = pd.read_parquet(tmp_path / "inventory.parquet")

    second_message = state.fetch_sec_companyfacts("789019", cache_dir=cache_dir, user_agent=provider.user_agent)
    second_inventory = pd.read_parquet(tmp_path / "inventory.parquet")

    assert "complete" in first_message
    assert "complete" in second_message
    assert len(first_inventory) == len(second_inventory) == 1
    row = second_inventory.iloc[0]
    assert row["source_url"] == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json"
    captured_path = Path(row["path"])
    assert captured_path != Path(metadata["raw_path"])
    assert captured_path.read_bytes() == Path(metadata["raw_path"]).read_bytes()
    assert row["checksum"] == metadata["sha256"]
    assert row["ingested_at"] == metadata["retrieved_at"]
    assert row["document_type"] == "sec_companyfacts"


def test_import_companyfacts_rejects_inconsistent_supplied_document_before_publish(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    payload_path = tmp_path / "facts.json"
    payload_path.write_bytes(_payload())
    document = replace(_document(payload_path), sha256="0" * 64)
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "inventory.parquet")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    state = _state(state_module)

    message = state.import_sec_companyfacts(payload_path, document=document)

    assert "No data changed" in message
    assert not (tmp_path / "facts.parquet").exists()
    assert not (tmp_path / "inventory.parquet").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("retrieved_at", datetime(2026, 9, 3)),
        ("provider_id", "untrusted_provider"),
        ("document_type", "sec_submissions"),
        ("media_type", "text/plain"),
        ("source_url", "https://data.sec.gov/not-companyfacts.json"),
        ("source_url", "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"),
        ("http_status", 201),
        ("http_status", True),
    ],
)
def test_import_companyfacts_rejects_invalid_supplied_provenance_before_publish(tmp_path, monkeypatch, field, value) -> None:
    from etf_cockpit.app import state as state_module

    payload_path = tmp_path / "facts.json"
    payload_path.write_bytes(_payload())
    document = _document(payload_path)
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "inventory.parquet")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    state = _state(state_module)

    message = state.import_sec_companyfacts(payload_path, document=replace(document, **{field: value}))

    assert "No data changed" in message
    assert not (tmp_path / "facts.parquet").exists()
    assert not (tmp_path / "inventory.parquet").exists()


def test_import_companyfacts_rejects_document_path_mismatch_without_changing_existing_evidence(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    payload_path = tmp_path / "facts.json"
    payload_path.write_bytes(_payload())
    other_path = tmp_path / "other-facts.json"
    other_path.write_bytes(_payload().replace(b'"val": 10', b'"val": 11'))
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "inventory.parquet")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    state = _state(state_module)
    assert "complete" in state.import_sec_companyfacts(payload_path)
    facts_before = (tmp_path / "facts.parquet").read_bytes()
    inventory_before = (tmp_path / "inventory.parquet").read_bytes()

    message = state.import_sec_companyfacts(payload_path, document=_document(other_path))

    assert "No data changed" in message
    assert (tmp_path / "facts.parquet").read_bytes() == facts_before
    assert (tmp_path / "inventory.parquet").read_bytes() == inventory_before


def test_import_companyfacts_rejects_changed_file_before_publication(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    payload_path = tmp_path / "facts.json"
    payload_path.write_bytes(_payload())
    document = _document(payload_path)
    original_parse = state_module.parse_companyfacts

    def parse_after_file_change(path, identity):
        path.write_bytes(_payload().replace(b'"val": 10', b'"val": 11'))
        return original_parse(path, identity)

    monkeypatch.setattr(state_module, "parse_companyfacts", parse_after_file_change)
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "inventory.parquet")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    state = _state(state_module)

    message = state.import_sec_companyfacts(payload_path, document=document)

    assert "No data changed" in message
    assert not (tmp_path / "facts.parquet").exists()
    assert not (tmp_path / "inventory.parquet").exists()


def test_import_companyfacts_captures_provider_generation_before_boundary_mutation(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    original_bytes = _payload()
    source_sha256 = hashlib.sha256(original_bytes).hexdigest()
    payload_path = tmp_path / f"companyfacts_0000789019_{source_sha256[:16]}.json"
    payload_path.write_bytes(original_bytes)
    document = _document(payload_path)
    replacement_bytes = original_bytes.replace(b'"val": 10', b'"val": 11')
    original_writer = state_module.write_statement_evidence

    def mutate_source_then_publish(source, records, facts_destination, inventory_destination, **kwargs):
        payload_path.write_bytes(replacement_bytes)
        return original_writer(source, records, facts_destination, inventory_destination, **kwargs)

    monkeypatch.setattr(state_module, "write_statement_evidence", mutate_source_then_publish)
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "inventory.parquet")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    state = _state(state_module)

    message = state.import_sec_companyfacts(payload_path, document=document)

    assert "complete" in message
    row = pd.read_parquet(tmp_path / "inventory.parquet").iloc[0]
    captured_path = Path(row["path"])
    assert captured_path != payload_path
    assert captured_path.read_bytes() == original_bytes
    assert hashlib.sha256(captured_path.read_bytes()).hexdigest() == row["checksum"]
    assert payload_path.read_bytes() == replacement_bytes


def test_import_companyfacts_rejects_parser_checksum_mismatch_before_publication(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    payload_path = tmp_path / "facts.json"
    payload_path.write_bytes(_payload())
    document = _document(payload_path)
    original_parse = state_module.parse_companyfacts

    def parse_with_wrong_checksum(path, identity):
        return replace(original_parse(path, identity), source_sha256="f" * 64)

    monkeypatch.setattr(state_module, "parse_companyfacts", parse_with_wrong_checksum)
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "inventory.parquet")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    state = _state(state_module)

    message = state.import_sec_companyfacts(payload_path, document=document)

    assert "No data changed" in message
    assert not (tmp_path / "facts.parquet").exists()
    assert not (tmp_path / "inventory.parquet").exists()


def test_path_import_keeps_local_compatibility_provenance(tmp_path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    payload_path = tmp_path / "facts.json"
    payload_path.write_bytes(_payload())
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "inventory.parquet")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    state = _state(state_module)

    message = state.import_sec_companyfacts(payload_path)
    row = pd.read_parquet(tmp_path / "inventory.parquet").iloc[0]

    assert "complete" in message
    assert row["source_url"] == payload_path.resolve().as_uri()
    assert row["source_authority"] == "official_regulator"
