from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pandas as pd
import pytest

from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.data.sec_edgar_bulk import COMPANYFACTS_BULK_URL, SecEdgarBulkUnavailable
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
from etf_cockpit.parsers.contracts import RawDocument


def _state(state_module):
    state = state_module.AppState.__new__(state_module.AppState)
    state.last_message = "Ready"
    state.selected_etf = "SELECTED_ETF"
    state.snapshot = SimpleNamespace(config=SimpleNamespace(universe=SimpleNamespace(etfs=[])))
    return state


def _identity() -> CanonicalIdentity:
    return CanonicalIdentity("ONE", "One", None, "needs_verification", "", None, None, "stock", {}, "manual_review", (), "1")


def _facts() -> bytes:
    return json.dumps({
        "cik": 1,
        "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": 10, "end": "2024-12-31", "form": "10-K", "filed": "2025-01-01"}]}}}},
    }).encode()


def _archive(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("CIK0000000001.json", _facts())
    return path


def _configure_state(state_module, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(state_module, "STATEMENT_FACTS_PATH", tmp_path / "facts.parquet")
    monkeypatch.setattr(state_module, "FILINGS_STATEMENTS_PATH", tmp_path / "inventory.parquet")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    monkeypatch.delenv("ETF_COCKPIT_SEC_EDGAR_USER_AGENT", raising=False)


def _persisted_identity(path: Path, instrument_id: str = "ONE") -> None:
    pd.DataFrame([{"cik": "0000000001", "instrument_id": instrument_id}]).to_parquet(path, index=False)


def test_plain_local_bulk_entrypoint_needs_no_user_agent_or_network(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    archive = _archive(tmp_path / "companyfacts.zip")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("local import must not create a provider")))

    result = _state(state_module).import_sec_companyfacts_bulk(
        archive,
        identity=_identity(),
        cache_dir=tmp_path / "cache",
    )

    assert "SEC bulk import complete" in result
    assert "execution_allowed=false" in result
    assert pd.read_parquet(tmp_path / "facts.parquet")["instrument_id"].eq("ONE").all()
    assert pd.read_parquet(tmp_path / "inventory.parquet")["source_authority"].eq("manual_review").all()


def test_same_session_cached_bulk_is_preferred_without_ua_or_network(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    identity_path = tmp_path / "identity.parquet"
    _persisted_identity(identity_path)
    monkeypatch.setattr(state_module, "IDENTITY_PATH", identity_path)
    payload = _archive(tmp_path / "source.zip").read_bytes()
    provider = SecEdgarProvider(
        "ETF Research owner@company.eu",
        cache_dir=tmp_path / "cache",
        transport=lambda _url, _headers: (payload, 200, {"ETag": '"bulk-v1"'}),
        rate_limit_seconds=0,
    )
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *_args, **_kwargs: provider)
    state = _state(state_module)
    state.fetch_sec_companyfacts_bulk("1", instrument_id="ONE", user_agent=provider.user_agent, cache_dir=tmp_path / "cache")
    provider.transport = lambda *_: pytest.fail("cache-only must not request network")
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("validated cache should win before provider construction")))

    result = state.fetch_sec_companyfacts("1", cache_dir=tmp_path / "cache", instrument_id="ONE")

    assert "SEC cached bulk import complete" in result
    assert "freshness unverified" in result
    row = pd.read_parquet(tmp_path / "inventory.parquet").iloc[0]
    assert row["source_url"] == COMPANYFACTS_BULK_URL
    assert row["source_authority"] == "official_regulator"
    assert row["source_authority"] == "official_regulator"


def test_explicit_bulk_import_keeps_public_206_and_304_manual(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    archive = _archive(tmp_path / "companyfacts.zip")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    state = _state(state_module)
    for status, hour in ((206, 1), (304, 2)):
        provenance = RawDocument(
            archive,
            COMPANYFACTS_BULK_URL,
            datetime(2026, 9, 3, hour, tzinfo=timezone.utc),
            digest,
            "sec_edgar",
            "sec_companyfacts_bulk",
            "application/zip",
            status,
        )
        result = state.import_sec_companyfacts_bulk(archive, identity=_identity(), cache_dir=tmp_path / f"cache-{status}", provenance=provenance)
        assert "complete" in result
    checkpoints = list((tmp_path / "cache-304" / "sec_companyfacts_bulk" / "checkpoints").glob("*.json"))
    checkpoint = json.loads(checkpoints[0].read_text(encoding="utf-8"))
    assert checkpoint["entries"]["0000000001"]["http_status"] == 200


def test_cache_miss_without_ua_reports_truthful_fallback_reason(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    state = _state(state_module)

    result = state.fetch_sec_companyfacts("1", cache_dir=tmp_path / "missing-cache")

    assert "validated SEC bulk cache unavailable" in result
    assert "configure ETF_COCKPIT_SEC_EDGAR_USER_AGENT" in result
    assert not (tmp_path / "facts.parquet").exists()


def test_supplied_bulk_identity_conflict_is_rejected_before_archive_or_writes(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    _persisted_identity(tmp_path / "identity.parquet")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    facts = tmp_path / "facts.parquet"
    inventory = tmp_path / "inventory.parquet"
    facts.write_bytes(b"prior-facts")
    inventory.write_bytes(b"prior-inventory")
    archive = _archive(tmp_path / "companyfacts.zip")
    before = (facts.read_bytes(), inventory.read_bytes(), archive.stat().st_mtime_ns)

    result = _state(state_module).import_sec_companyfacts_bulk(
        archive,
        identity=CanonicalIdentity("WRONG", "Wrong", None, "needs_verification", "", None, None, "stock", {}, "manual_review", (), "1"),
        cache_dir=tmp_path / "cache",
    )

    assert "conflicts with persisted" in result
    assert (facts.read_bytes(), inventory.read_bytes(), archive.stat().st_mtime_ns) == before
    assert not (tmp_path / "cache").exists()


def test_supplied_bulk_identity_ambiguity_is_rejected_before_archive(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    pd.DataFrame([{"cik": "0000000001", "instrument_id": "ONE"}, {"cik": "1", "instrument_id": "TWO"}]).to_parquet(tmp_path / "identity.parquet", index=False)
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    archive = _archive(tmp_path / "companyfacts.zip")
    result = _state(state_module).import_sec_companyfacts_bulk(archive, identity=_identity(), cache_dir=tmp_path / "cache")

    assert "ambiguous" in result
    assert not (tmp_path / "cache").exists()


def test_actual_provider_200_206_304_bulk_provenance_reaches_appstate(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "missing-identity.parquet")
    payload = _archive(tmp_path / "source.zip").read_bytes()

    class Response:
        def __init__(self, body: bytes, status: int, headers: dict[str, str], fail_after: int | None = None) -> None:
            self.body, self.status, self.headers = body, status, headers
            self.offset, self.fail_after = 0, fail_after

        def read(self, size: int = -1) -> bytes:
            if self.fail_after is not None and self.offset >= self.fail_after:
                raise OSError("interrupted test response")
            take = min(size if size >= 0 else len(self.body), 7)
            if self.fail_after is not None:
                take = min(take, self.fail_after - self.offset)
            result = self.body[self.offset:self.offset + take]
            self.offset += len(result)
            return result

        def close(self) -> None:
            return None

    responses: list[object] = [Response(payload, 200, {"ETag": '"stable"', "Content-Length": str(len(payload))}, 14)]

    def transport(_url: str, _headers: dict[str, str]) -> object:
        return responses.pop(0)

    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=tmp_path / "cache", transport=transport, rate_limit_seconds=0, max_retries=0)
    with pytest.raises(SecEdgarBulkUnavailable):
        provider.fetch_companyfacts_bulk()
    partial = tmp_path / "cache" / "sec_edgar_bulk" / "partials" / "companyfacts.part"
    offset = partial.stat().st_size
    responses.append(Response(payload[offset:], 206, {"ETag": '"stable"', "Content-Range": f"bytes {offset}-{len(payload)-1}/{len(payload)}"}))
    resumed = provider.fetch_companyfacts_bulk()
    assert resumed.http_status == 206

    first_time = resumed.retrieved_at
    responses.append((b"", 304, {}))
    revalidated = provider.fetch_companyfacts_bulk()
    assert revalidated.http_status == 304
    assert revalidated.retrieved_at == first_time

    state = _state(state_module)
    result = state.import_sec_companyfacts_bulk(resumed.path, identity=_identity(), cache_dir=tmp_path / "app-cache", provenance=resumed)
    assert "complete" in result
    state.import_sec_companyfacts_bulk(revalidated.path, identity=_identity(), cache_dir=tmp_path / "app-cache", provenance=revalidated)
    row = pd.read_parquet(tmp_path / "inventory.parquet").iloc[0]
    assert row["source_url"].startswith("file:")
    assert row["source_authority"] == "manual_review"
    assert row["document_type"] == "sec_companyfacts_bulk"
    assert row["ingested_at"] != first_time.isoformat()


def test_explicit_refresh_routes_actual_provider_document_to_canonical_stores(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    identity_path = tmp_path / "identity.parquet"
    _persisted_identity(identity_path)
    monkeypatch.setattr(state_module, "IDENTITY_PATH", identity_path)
    archive = _archive(tmp_path / "source.zip")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    provenance = RawDocument(archive, COMPANYFACTS_BULK_URL, datetime(2026, 9, 3, 4, tzinfo=timezone.utc), digest, "sec_edgar", "sec_companyfacts_bulk", "application/zip", 200)
    calls = 0

    class Provider(SecEdgarProvider):
        def __init__(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            super().__init__(*_args, **_kwargs, transport=lambda *_: (archive.read_bytes(), 200, {}), rate_limit_seconds=0)

    monkeypatch.setattr(state_module, "SecEdgarProvider", Provider)
    result = _state(state_module).fetch_sec_companyfacts_bulk("1", instrument_id="ONE", user_agent="ETF Research owner@company.eu", cache_dir=tmp_path / "cache")

    assert "SEC bulk import complete" in result
    assert calls == 1
    row = pd.read_parquet(tmp_path / "inventory.parquet").iloc[0]
    assert row["source_url"] == COMPANYFACTS_BULK_URL
    assert row["source_authority"] == "official_regulator"
    assert row["ingested_at"] != provenance.retrieved_at.isoformat()


def test_cancellation_preserves_existing_bulk_stores(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module
    from etf_cockpit.core.workflow import WorkflowTransitionError

    _configure_state(state_module, tmp_path, monkeypatch)
    archive = _archive(tmp_path / "companyfacts.zip")
    facts, inventory = tmp_path / "facts.parquet", tmp_path / "inventory.parquet"
    facts.write_bytes(b"prior-facts")
    inventory.write_bytes(b"prior-inventory")
    before = (facts.read_bytes(), inventory.read_bytes())

    def cancel():
        raise WorkflowTransitionError("cancelled before publication")

    with pytest.raises(WorkflowTransitionError):
        _state(state_module).import_sec_companyfacts_bulk(archive, identity=_identity(), cache_dir=tmp_path / "cache", publish_guard=cancel)
    assert (facts.read_bytes(), inventory.read_bytes()) == before


def test_explicit_bulk_refresh_validates_identity_before_provider(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    identity_path = tmp_path / "identity.parquet"
    _persisted_identity(identity_path)
    monkeypatch.setattr(state_module, "IDENTITY_PATH", identity_path)
    calls = 0

    class Provider:
        def __init__(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1

        def fetch_companyfacts_bulk(self, **_kwargs):
            raise AssertionError("invalid selection must not acquire")

    monkeypatch.setattr(state_module, "SecEdgarProvider", Provider)
    result = _state(state_module).fetch_sec_companyfacts_bulk("1", instrument_id="WRONG", user_agent="ETF Research owner@company.eu", cache_dir=tmp_path / "cache")

    assert "conflicts with persisted" in result
    assert calls == 0


def test_json_fallback_preserves_bounded_http429_quota_detail(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    provider = SecEdgarProvider(
        "ETF Research owner@company.eu",
        cache_dir=tmp_path / "cache",
        transport=lambda _url, _headers: (b"", 429, {}),
        rate_limit_seconds=0,
        max_retries=0,
    )
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *_args, **_kwargs: provider)

    result = _state(state_module).fetch_sec_companyfacts("1", cache_dir=tmp_path / "cache", user_agent="ETF Research owner@company.eu")

    assert "HTTP 429" in result
    assert "rate limit/quota" in result
    assert not (tmp_path / "facts.parquet").exists()


@pytest.mark.parametrize("rows,supplied_id", [
    ([{"cik": "2", "instrument_id": "ONE"}], "ONE"),
    ([{"cik": "invalid", "instrument_id": "ONE"}], "ONE"),
    ([{"cik": "1", "instrument_id": None}], "ONE"),
    ([{"cik": "1", "instrument_id": ""}], "ONE"),
    ([{"cik": "1", "instrument_id": "ONE"}, {"cik": "2", "instrument_id": "ONE"}], "ONE"),
    ([{"cik": "1", "instrument_id": "ONE"}], " ONE "),
], ids=["inverse", "malformed-cik", "null-id", "empty-id", "inverse-collision", "noncanonical-id"])
def test_registry_integrity_rejects_before_bulk_import(tmp_path: Path, monkeypatch, rows, supplied_id) -> None:
    from dataclasses import replace
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    pd.DataFrame(rows).to_parquet(tmp_path / "identity.parquet", index=False)
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    facts, inventory = tmp_path / "facts.parquet", tmp_path / "inventory.parquet"
    facts.write_bytes(b"existing-facts")
    inventory.write_bytes(b"existing-inventory")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("identity rejection must precede archive import")

    monkeypatch.setattr(state_module, "_import_sec_companyfacts_bulk", forbidden)
    result = _state(state_module).import_sec_companyfacts_bulk(
        tmp_path / "never-open.zip", identity=replace(_identity(), instrument_id=supplied_id), cache_dir=tmp_path / "cache",
    )
    assert "unavailable" in result
    assert calls == []
    assert facts.read_bytes() == b"existing-facts"
    assert inventory.read_bytes() == b"existing-inventory"
    assert not (tmp_path / "cache").exists()


def test_null_persisted_identity_cannot_construct_provider(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    pd.DataFrame([{"cik": "1", "instrument_id": None}]).to_parquet(tmp_path / "identity.parquet", index=False)
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("null instrument must not acquire")

    monkeypatch.setattr(state_module, "SecEdgarProvider", forbidden)
    result = _state(state_module).fetch_sec_companyfacts_bulk("1", user_agent="ETF Research owner@company.eu", cache_dir=tmp_path / "cache")
    assert "unavailable" in result
    assert calls == []
    assert not (tmp_path / "cache").exists()


def test_real_wrapped_http_error_reports_quota(tmp_path: Path, monkeypatch) -> None:
    from urllib.error import HTTPError
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "missing-identity.parquet")

    def transport(url, headers):
        raise HTTPError(url, 429, "Too Many Requests", {}, None)

    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=tmp_path / "cache", transport=transport, rate_limit_seconds=0, max_retries=0)
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *args, **kwargs: provider)
    result = _state(state_module).fetch_sec_companyfacts("1", user_agent=provider.user_agent, cache_dir=tmp_path / "cache")
    assert "HTTP 429" in result
    assert "rate limit/quota" in result


def test_controlled_bulk_errors_keep_actionable_reason() -> None:
    from etf_cockpit.app import state as state_module
    from etf_cockpit.data.sec_edgar_bulk import SecEdgarBulkEndpointError, SecEdgarBulkResumeError

    assert "endpoint changed" in state_module._sec_failure_detail(SecEdgarBulkEndpointError("endpoint changed"))
    assert "validator changed" in state_module._sec_failure_detail(SecEdgarBulkResumeError("validator changed"))


def test_warning_message_is_bounded_with_checkpoint_detail() -> None:
    from etf_cockpit.app import state as state_module
    from etf_cockpit.application.sec_bulk_import import BulkCikStatus, BulkImportResult

    warnings = tuple({"code": "malformed_fact", "message": "bad input"} for _ in range(10000))
    result = BulkImportResult("partial", (BulkCikStatus("0000000001", "ONE", "imported", detail="facts and inventory published; checkpoint unavailable", coverage_status="pending", warnings=warnings),), None, None)
    message = state_module._bulk_result_message(result, "SEC bulk import")
    assert len(message) <= 2048
    assert "malformed_fact" in message
    assert "9999 warning entries omitted" in message
    assert "coverage=pending" in message
    assert "checkpoint unavailable" in message
    assert "execution_allowed=false" in message
    assert len(result.per_cik[0].warnings) == 10000


def test_appstate_interrupted_acquisition_reports_retained_partial(tmp_path: Path, monkeypatch) -> None:
    from io import BytesIO
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    _persisted_identity(tmp_path / "identity.parquet")
    monkeypatch.setattr(state_module, "IDENTITY_PATH", tmp_path / "identity.parquet")
    payload = _archive(tmp_path / "source.zip").read_bytes()

    class InterruptedResponse:
        status = 200
        headers = {"ETag": '"stable"', "Content-Length": str(len(payload))}
        offset = 0

        def read(self, size):
            if self.offset:
                raise OSError("interrupted transfer")
            self.offset = 10
            return payload[:10]

        def close(self):
            pass

    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=tmp_path / "cache", transport=lambda *args: InterruptedResponse(), rate_limit_seconds=0, max_retries=0)
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *args, **kwargs: provider)
    facts, inventory = tmp_path / "facts.parquet", tmp_path / "inventory.parquet"
    pd.DataFrame().to_parquet(facts, index=False)
    pd.DataFrame().to_parquet(inventory, index=False)
    before = (facts.read_bytes(), inventory.read_bytes())
    state = _state(state_module)
    result = state.fetch_sec_companyfacts_bulk("1", user_agent=provider.user_agent, cache_dir=tmp_path / "cache")
    assert (tmp_path / "cache" / "sec_edgar_bulk" / "partials" / "companyfacts.part").stat().st_size == 10
    assert (facts.read_bytes(), inventory.read_bytes()) == before
    assert "No data changed" not in result
    assert "Canonical statement stores unchanged" in result
    assert "cache/partials may have changed" in result

    documents = []
    actual_fetch = provider.fetch_companyfacts_bulk

    def capture(**kwargs):
        document = actual_fetch(**kwargs)
        documents.append(document)
        return document

    monkeypatch.setattr(provider, "fetch_companyfacts_bulk", capture)
    stream = BytesIO(payload[10:])

    def resumed_transport(url, headers):
        assert headers["Range"] == "bytes=10-"
        return SimpleNamespace(read=stream.read, close=stream.close, status=206, headers={"ETag": '"stable"', "Content-Range": f"bytes 10-{len(payload)-1}/{len(payload)}"})

    provider.transport = resumed_transport
    resumed = state.fetch_sec_companyfacts_bulk("1", user_agent=provider.user_agent, cache_dir=tmp_path / "cache")
    assert "SEC bulk import complete" in resumed
    assert documents[-1].http_status == 206
    acquired_at = documents[-1].retrieved_at
    provider.transport = lambda *args: (b"", 304, {})
    revalidated = state.fetch_sec_companyfacts_bulk("1", user_agent=provider.user_agent, cache_dir=tmp_path / "cache")
    assert "SEC bulk import complete" in revalidated
    assert documents[-1].http_status == 304
    assert documents[-1].retrieved_at == acquired_at
    assert pd.read_parquet(inventory).iloc[0]["source_authority"] == "official_regulator"
    assert pd.read_parquet(inventory).iloc[0]["ingested_at"] == acquired_at.isoformat()
    assert pd.read_parquet(facts)["instrument_id"].eq("ONE").all()


def test_actual_provider_200_refresh_and_bad_cache_json_fallback(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    _persisted_identity(tmp_path / "identity.parquet")
    payload = _archive(tmp_path / "source.zip").read_bytes()
    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=tmp_path / "cache", transport=lambda *args: (payload, 200, {"ETag": '"initial"'}), rate_limit_seconds=0, max_retries=0)
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *args, **kwargs: provider)
    state = _state(state_module)
    result = state.fetch_sec_companyfacts_bulk("1", user_agent=provider.user_agent, cache_dir=tmp_path / "cache")
    assert "SEC bulk import complete" in result
    assert pd.read_parquet(tmp_path / "inventory.parquet")["document_type"].eq("sec_companyfacts_bulk").all()

    metadata_path = tmp_path / "cache" / "sec_edgar_bulk" / "companyfacts.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["status"] = True
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    requests = []

    def json_transport(url, headers):
        requests.append(url)
        return (_facts(), 200, {})

    provider.transport = json_transport
    fallback = state.fetch_sec_companyfacts("1", user_agent=provider.user_agent, cache_dir=tmp_path / "cache")
    assert "Bulk fallback: validated SEC bulk cache unavailable" in fallback
    assert requests == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"]
    assert "sec_companyfacts" in set(pd.read_parquet(tmp_path / "inventory.parquet")["document_type"])


@pytest.mark.parametrize("field,value", [("status", True), ("raw_path", "../outside.zip"), ("sha256", "0" * 64)])
def test_invalid_bulk_cache_is_read_only_without_network(tmp_path: Path, monkeypatch, field, value) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    _persisted_identity(tmp_path / "identity.parquet")
    payload = _archive(tmp_path / "source.zip").read_bytes()
    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=tmp_path / "cache", transport=lambda *args: (payload, 200, {}), rate_limit_seconds=0)
    provider.fetch_companyfacts_bulk()
    path = tmp_path / "cache" / "sec_edgar_bulk" / "companyfacts.meta.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata[field] = value
    path.write_text(json.dumps(metadata), encoding="utf-8")
    before = path.read_bytes()
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("no user-agent means no fallback network")

    monkeypatch.setattr(state_module, "SecEdgarProvider", forbidden)
    state = _state(state_module)
    state._sec_bulk_provider = provider
    result = state.fetch_sec_companyfacts("1", cache_dir=tmp_path / "cache")
    assert "validated SEC bulk cache unavailable" in result
    assert calls == []
    assert path.read_bytes() == before
    assert not (tmp_path / "facts.parquet").exists()


def test_cache_only_workflow_rejects_linked_namespace(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "cache"
    root.mkdir()
    try:
        (root / "sec_edgar_bulk").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable on this platform")
    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=root)
    document, reason = state_module._cached_sec_bulk_document(root, provider)
    assert document is None
    assert "unavailable" in reason
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("initialized", [False, True])
def test_json_parser_rejection_reports_retained_acquisition(tmp_path: Path, monkeypatch, initialized: bool) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    _persisted_identity(tmp_path / "identity.parquet")
    facts, inventory = tmp_path / "facts.parquet", tmp_path / "inventory.parquet"
    pd.DataFrame().to_parquet(facts, index=False)
    pd.DataFrame().to_parquet(inventory, index=False)
    before = (facts.read_bytes(), inventory.read_bytes())
    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=tmp_path / "cache", transport=lambda *args: (b'{"cik":1,"facts":[]}', 200, {}), rate_limit_seconds=0, max_retries=0)
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *args, **kwargs: provider)
    state = _state(state_module)
    state._sec_bulk_provider = provider
    if initialized:
        import threading

        state._activity_lock = threading.RLock()
        with pytest.raises(state_module.ActivityUnavailableError) as failure:
            state.fetch_sec_companyfacts("1", user_agent=provider.user_agent, cache_dir=tmp_path / "cache")
        result = str(failure.value)
        assert state.last_message == result
    else:
        result = state.fetch_sec_companyfacts("1", user_agent=provider.user_agent, cache_dir=tmp_path / "cache")
    assert "SEC import unavailable" in result
    assert "Raw acquisition cache may have changed" in result
    assert (tmp_path / "cache" / "companyfacts_0000000001.json").exists()
    assert (facts.read_bytes(), inventory.read_bytes()) == before


@pytest.mark.parametrize("entrypoint", ["refresh", "cache_first", "local", "explicit_identity"])
@pytest.mark.parametrize("instrument_id", [" ONE ", "", " ", 1])
def test_builder_rejects_noncanonical_instrument_before_io(tmp_path: Path, monkeypatch, entrypoint, instrument_id) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    _persisted_identity(tmp_path / "identity.parquet")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("noncanonical identity must fail before any acquisition/cache/import")

    monkeypatch.setattr(state_module, "SecEdgarProvider", forbidden)
    monkeypatch.setattr(state_module, "_cached_sec_bulk_document", forbidden)
    monkeypatch.setattr(state_module, "_import_sec_companyfacts_bulk", forbidden)
    state = _state(state_module)
    kwargs = {"instrument_id": instrument_id, "cache_dir": tmp_path / "cache"}
    if entrypoint == "refresh":
        result = state.fetch_sec_companyfacts_bulk("1", user_agent="ETF Research owner@company.eu", **kwargs)
    elif entrypoint == "cache_first":
        result = state.fetch_sec_companyfacts("1", user_agent="ETF Research owner@company.eu", **kwargs)
    else:
        selection = {"identity": _identity()} if entrypoint == "explicit_identity" else {"cik": "1"}
        result = state.import_sec_companyfacts_bulk(tmp_path / "never-open.zip", **selection, **kwargs)
    assert "unavailable" in result
    assert calls == []
    assert not (tmp_path / "cache").exists()
    assert not (tmp_path / "facts.parquet").exists()
    assert not (tmp_path / "inventory.parquet").exists()


@pytest.mark.parametrize("initialized", [False, True])
def test_cached_missing_member_without_agent_reports_retained_raw(tmp_path: Path, monkeypatch, initialized: bool) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    pd.DataFrame([{"cik": "2", "instrument_id": "TWO"}]).to_parquet(tmp_path / "identity.parquet", index=False)
    payload = _archive(tmp_path / "source.zip").read_bytes()
    cache = tmp_path / "cache"
    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=cache, transport=lambda *args: (payload, 200, {}), rate_limit_seconds=0)
    provider.fetch_companyfacts_bulk()
    facts, inventory = tmp_path / "facts.parquet", tmp_path / "inventory.parquet"
    pd.DataFrame().to_parquet(facts, index=False)
    pd.DataFrame().to_parquet(inventory, index=False)
    before = (facts.read_bytes(), inventory.read_bytes())
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *args, **kwargs: pytest.fail("no agent: no network"))
    state = _state(state_module)
    state._sec_bulk_provider = provider
    if initialized:
        import threading

        state._activity_lock = threading.RLock()
        with pytest.raises(state_module.ActivityUnavailableError) as failure:
            state.fetch_sec_companyfacts("2", instrument_id="TWO", cache_dir=cache)
        result = str(failure.value)
        assert state.last_message == result
    else:
        result = state.fetch_sec_companyfacts("2", instrument_id="TWO", cache_dir=cache)
    assert "cached bulk import failed" in result
    assert "Local data was not changed" not in result
    assert "No data changed" not in result
    assert "Raw cache/partials or checkpoints may have changed" in result
    assert (facts.read_bytes(), inventory.read_bytes()) == before
    manifest = cache / "sec_companyfacts_bulk" / "manifests" / "sec-companyfacts-bulk.json"
    assert manifest.exists()


@pytest.mark.parametrize("rows", [
    [{"cik": "1", "instrument_id": "ONE"}, {"cik": "2", "instrument_id": "ONE"}],
    [{"cik": "1", "instrument_id": "ONE"}, {"cik": "1", "instrument_id": "OTHER"}],
    [{"cik": "1", "instrument_id": None}],
    [{"cik": "1", "instrument_id": ""}],
    [{"cik": "1", "instrument_id": " ONE "}],
], ids=["inverse-conflict", "ambiguous", "null", "empty", "noncanonical"])
def test_json_fallback_rejects_invalid_registry_without_explicit_id(tmp_path: Path, monkeypatch, rows) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    pd.DataFrame(rows).to_parquet(tmp_path / "identity.parquet", index=False)
    facts, inventory = tmp_path / "facts.parquet", tmp_path / "inventory.parquet"
    pd.DataFrame().to_parquet(facts, index=False)
    pd.DataFrame().to_parquet(inventory, index=False)
    before = (facts.read_bytes(), inventory.read_bytes())
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("invalid registry must block both acquisition paths")

    monkeypatch.setattr(state_module, "SecEdgarProvider", forbidden)
    monkeypatch.setattr(state_module, "_cached_sec_bulk_document", forbidden)
    monkeypatch.setattr(state_module, "_import_sec_companyfacts_bulk", forbidden)
    state = _state(state_module)
    monkeypatch.setattr(state, "import_sec_companyfacts", forbidden)
    result = state.fetch_sec_companyfacts("1", user_agent="ETF Research owner@company.eu", cache_dir=tmp_path / "cache")
    assert "unavailable" in result
    assert calls == []
    assert (facts.read_bytes(), inventory.read_bytes()) == before
    assert not (tmp_path / "cache").exists()


def test_json_first_run_without_binding_retains_manual_review_fallback(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    requests = []

    def transport(url, headers):
        requests.append(url)
        return (_facts(), 200, {})

    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=tmp_path / "cache", transport=transport, rate_limit_seconds=0)
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *args, **kwargs: provider)
    result = _state(state_module).fetch_sec_companyfacts("1", user_agent=provider.user_agent, cache_dir=tmp_path / "cache")
    assert "SEC import complete" in result
    assert "manual identity review required" in result
    assert requests == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"]
    assert pd.read_parquet(tmp_path / "facts.parquet")["instrument_id"].eq("sec_unresolved_0000000001").all()


def test_cold_appstate_cannot_rehydrate_bulk_session(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module

    _configure_state(state_module, tmp_path, monkeypatch)
    _persisted_identity(tmp_path / "identity.parquet")
    cache = tmp_path / "cache"
    payload = _archive(tmp_path / "source.zip").read_bytes()
    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=cache, transport=lambda *_: (payload, 200, {}), rate_limit_seconds=0)
    provider.fetch_companyfacts_bulk()
    before = {path.relative_to(cache): path.read_bytes() for path in cache.rglob("*") if path.is_file()}
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *_args, **_kwargs: pytest.fail("cold cache must not create a provider"))
    result = _state(state_module).fetch_sec_companyfacts("1", instrument_id="ONE", cache_dir=cache)
    assert "no same-session acquisition proof" in result
    assert not (tmp_path / "facts.parquet").exists()
    assert {path.relative_to(cache): path.read_bytes() for path in cache.rglob("*") if path.is_file()} == before


def test_cancelled_refresh_keeps_same_session_cache_and_official_stores(tmp_path: Path, monkeypatch) -> None:
    from etf_cockpit.app import state as state_module
    from etf_cockpit.core.workflow import WorkflowTransitionError

    _configure_state(state_module, tmp_path, monkeypatch)
    _persisted_identity(tmp_path / "identity.parquet")
    cache = tmp_path / "cache"
    payload = _archive(tmp_path / "source.zip").read_bytes()
    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=cache, transport=lambda *_: (payload, 200, {}), rate_limit_seconds=0)
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *_args, **_kwargs: provider)
    state = _state(state_module)
    assert "complete" in state.fetch_sec_companyfacts_bulk("1", instrument_id="ONE", user_agent=provider.user_agent, cache_dir=cache)
    before = {path: path.read_bytes() for path in (tmp_path / "facts.parquet", tmp_path / "inventory.parquet", cache / "sec_edgar_bulk/companyfacts.meta.json")}
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *_args, **_kwargs: pytest.fail("refresh must reuse its session"))
    provider.transport = lambda *_: pytest.fail("cancelled/cache-only calls must not request network")

    def cancel():
        raise WorkflowTransitionError("cancelled refresh")

    with pytest.raises(WorkflowTransitionError):
        state.fetch_sec_companyfacts_bulk("1", instrument_id="ONE", user_agent=provider.user_agent, cache_dir=cache, publish_guard=cancel)
    assert all(path.read_bytes() == payload for path, payload in before.items())
    assert "SEC cached bulk import complete" in state.fetch_sec_companyfacts("1", instrument_id="ONE", cache_dir=cache)
    assert pd.read_parquet(tmp_path / "inventory.parquet")["source_authority"].eq("official_regulator").all()
    assert state._sec_bulk_provider is provider


def test_clean_first_run_explicit_local_identity_and_bounded_audit_outputs(tmp_path, monkeypatch):
    from etf_cockpit.app import state as state_module
    from etf_cockpit.chatgpt_bridge import export_pack

    _configure_state(state_module, tmp_path, monkeypatch)
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *a, **k: pytest.fail("local must stay offline"))
    state = _state(state_module)
    outputs = []
    def output(step, path):
        outputs.append((step, Path(path)))
        state.last_message = step
    monkeypatch.setattr(state, "_record_activity_output", output)
    message = state.import_sec_companyfacts_bulk(_archive(tmp_path / "companyfacts.zip"), cik="1", instrument_id="ONE", cache_dir=tmp_path / "cache")
    assert "complete" in message and "execution_allowed=false" in message
    assert state.sec_companyfacts_bulk_message == message
    assert len(outputs) == 3
    assert "sha256=" in outputs[-1][0]
    assert outputs[-1][1].is_file()
    assert pd.read_parquet(tmp_path / "inventory.parquet")["source_authority"].eq("manual_review").all()
    evidence = tmp_path / "audit"
    evidence.mkdir()
    manifest = {"included": [], "missing": [], "checksums": {}}
    for path in (tmp_path / "facts.parquet", tmp_path / "inventory.parquet"):
        export_pack._copy_evidence_file(path, evidence, manifest)
    assert manifest["included"]
    assert not list(evidence.rglob("*.zip"))


def test_submissions_bulk_local_and_explicit_session_cache(tmp_path, monkeypatch):
    from etf_cockpit.app import state as state_module
    from etf_cockpit.core.workflow import WorkflowTransitionError

    _configure_state(state_module, tmp_path, monkeypatch)
    archive = tmp_path / "submissions.zip"
    payload = {"cik": "0000000001", "name": "One", "filings": {"recent": {"accessionNumber": ["0000000001-26-000001"], "filingDate": ["2026-01-02"], "reportDate": ["2025-12-31"], "acceptanceDateTime": ["2026-01-02T03:04:05.000Z"], "form": ["10-K"], "primaryDocument": ["annual.htm"]}, "files": []}}
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("CIK0000000001.json", json.dumps(payload))
    state = _state(state_module)
    local = state.import_sec_submissions_bulk(archive, cik="1", instrument_id="ONE", cache_dir=tmp_path / "local")
    assert "partial" in local and "Filing bytes may be missing" in local
    assert state.sec_submissions_result.records
    assert state.sec_submissions_result.manifest_path.is_file()
    assert all(doc.provider_id == "sec_local_import" for doc in state.sec_submissions_result.raw_documents)
    assert "unavailable" in state.fetch_sec_submissions_bulk("1", instrument_id="ONE", cache_dir=tmp_path / "cache", cache_only=True)
    _persisted_identity(tmp_path / "identity.parquet")
    provider = SecEdgarProvider("ETF Research owner@company.eu", cache_dir=tmp_path / "cache", transport=lambda *_: (archive.read_bytes(), 200, {}), rate_limit_seconds=0)
    monkeypatch.setattr(state_module, "SecEdgarProvider", lambda *a, **k: provider)
    assert "partial" in state.fetch_sec_submissions_bulk("1", instrument_id="ONE", user_agent=provider.user_agent, cache_dir=tmp_path / "cache")
    provider.transport = lambda *_: pytest.fail("cache and cancellation must stay offline")
    assert "partial" in state.fetch_sec_submissions_bulk("1", instrument_id="ONE", cache_dir=tmp_path / "cache", cache_only=True)
    before = state.sec_submissions_result.manifest_path.read_bytes()
    def cancel():
        raise WorkflowTransitionError("cancelled")
    with pytest.raises(WorkflowTransitionError):
        state.fetch_sec_submissions_bulk("1", instrument_id="ONE", cache_dir=tmp_path / "cache", cache_only=True, publish_guard=cancel)
    assert state.sec_submissions_result.manifest_path.read_bytes() == before
    cold = _state(state_module)
    assert "no same-session acquisition proof" in cold.fetch_sec_submissions_bulk("1", instrument_id="ONE", cache_dir=tmp_path / "cache", cache_only=True)


def test_bulk_activity_session_evidence_preserves_partial_warning(tmp_path, monkeypatch):
    from etf_cockpit.app import state as state_module
    from etf_cockpit.core import session_log
    from etf_cockpit.core.workflow import WorkflowController

    _configure_state(state_module, tmp_path, monkeypatch)
    monkeypatch.setattr(state_module.AppState, "refresh_runtime_profile", lambda self: None)
    log = tmp_path / "session.jsonl"
    monkeypatch.setattr(state_module, "ACTIVITY_LOG_PATH", log)
    monkeypatch.setattr(session_log, "SESSION_LOG_PATH", log)
    state = state_module.AppState(snapshot=SimpleNamespace(), selected_etf="ETF", workflow_controller=WorkflowController(log_path=log))
    archive = tmp_path / "partial.zip"
    payload = json.loads(_facts())
    payload["facts"]["us-gaap"]["Assets"]["units"]["EUR"] = payload["facts"]["us-gaap"]["Assets"]["units"]["USD"]
    payload["facts"]["us-gaap"]["Revenues"] = {"units": {"USD": [{"val": 2, "end": "2024-12-31", "form": "10-K", "filed": "2025-01-01"}]}}
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("CIK0000000001.json", json.dumps(payload))
    activity = state.begin_activity("Import SEC companyfacts bulk")
    with state.share_activity(activity.action_id):
        result = state.import_sec_companyfacts_bulk(archive, cik="1", instrument_id="ONE", cache_dir=tmp_path / "cache", publish_guard=lambda: state.activity_publication(activity.action_id))
        state.finish_activity(result, expected_action_id=activity.action_id)
    assert "partial" in result
    assert "ambiguous_unit" in result
    assert state.sec_companyfacts_bulk_message == result
    copied = tmp_path / "audit" / "session.jsonl"
    assert session_log.copy_session_log_to(copied)
    evidence = copied.read_text()
    assert "sha256=" in evidence and "partial" in evidence and "ambiguous_unit" in evidence
    assert "execution_allowed=false" in evidence
