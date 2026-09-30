from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from etf_cockpit.data import sec_edgar_bulk
from etf_cockpit.data.fund_adapters import (
    parse_sec_ncen_archive,
    parse_sec_nport_archive,
    resolve_fund_evidence,
    run_sec_fund_adapters,
)
from etf_cockpit.data.sec_edgar_bulk import SecEdgarBulkUnavailable
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider


FIXTURES = Path(__file__).parent / "fixtures" / "sec_nport"
FUNDS = {("1", "S000000001"): "SYNTHETF"}
ACCEPTED_AT = {"0000000000-00-000001": "2025-02-15T20:12:00+00:00"}


class Response:
    def __init__(self, payload: bytes, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.payload = payload
        self.status = status
        self.headers = headers or {}
        self.offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.payload)
        size = min(size, 7)
        result = self.payload[self.offset : self.offset + size]
        self.offset += len(result)
        return result

    def close(self) -> None:
        return None


def _archive_bytes(form: str = "nport") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for table in (FIXTURES / form).glob("*.tsv"):
            archive.writestr(table.name, table.read_bytes())
    return output.getvalue()


def _write_archive(tmp_path: Path, form: str = "nport") -> Path:
    path = tmp_path / f"synthetic_{form}.zip"
    path.write_bytes(_archive_bytes(form))
    return path


def test_interrupted_nport_bulk_acquisition_resumes_and_hash_matches(tmp_path: Path) -> None:
    payload = _archive_bytes()

    class Interrupted(Response):
        def read(self, size: int = -1) -> bytes:
            if self.offset >= len(self.payload) // 2:
                raise OSError("synthetic interruption")
            return super().read(size)

    provider = SecEdgarProvider(
        "ETF Research owner@company.eu",
        cache_dir=tmp_path,
        transport=lambda _url, _headers: Interrupted(
            payload,
            headers={"ETag": '"synthetic-stable"', "Content-Length": str(len(payload))},
        ),
        rate_limit_seconds=0,
        max_retries=0,
    )
    with pytest.raises(SecEdgarBulkUnavailable):
        sec_edgar_bulk.fetch_bulk(provider, "nport_2025q1")

    def resume(_url: str, headers: dict[str, str]) -> Response:
        offset = int(headers["Range"].split("=", 1)[1].rstrip("-"))
        return Response(
            payload[offset:],
            206,
            {
                "ETag": '"synthetic-stable"',
                "Content-Range": f"bytes {offset}-{len(payload) - 1}/{len(payload)}",
            },
        )

    provider.transport = resume
    document = sec_edgar_bulk.fetch_bulk(provider, "nport_2025q1")

    assert document.path.read_bytes() == payload
    assert document.sha256 == hashlib.sha256(payload).hexdigest()
    assert document.source_url.endswith("/form-n-port-data-sets/2025q1_nport.zip")


def test_holdings_conservation_keeps_unknown_amount_visible(tmp_path: Path) -> None:
    results, _nav, coverage = parse_sec_nport_archive(
        _write_archive(tmp_path),
        FUNDS,
        accepted_at_by_accession=ACCEPTED_AT,
        today="2025-03-01",
    )

    assert len(results) == 1
    assert results[0].authority == "issuer"
    assert results[0].frame["weight"].sum() == pytest.approx(0.70)
    assert coverage["mapped_pct"].sum() + coverage["unknown_pct"].sum() == pytest.approx(100.0)
    assert coverage["mapped_pct"].sum() == pytest.approx(70.0)
    assert coverage["unknown_pct"].sum() == pytest.approx(30.0)
    assert (coverage["unknown_pct"] > 0).any()


def test_official_sec_evidence_outranks_convenience_and_records_conflict() -> None:
    resolved, conflicts = resolve_fund_evidence(
        [
            {
                "instrument_id": "SYNTHETF",
                "metric": "net_assets",
                "as_of": "2024-12-31",
                "value": "1000",
                "source": "sec_nport",
                "authority": "official",
            },
            {
                "instrument_id": "SYNTHETF",
                "metric": "net_assets",
                "as_of": "2024-12-31",
                "value": "900",
                "source": "convenience_feed",
                "authority": "convenience",
            },
        ]
    )

    assert resolved[0]["selected"]["source"] == "sec_nport"
    assert resolved[0]["authority"] == "official"
    assert len(conflicts) == 1
    assert conflicts[0]["conflicting_source"] == "convenience_feed"


def test_nav_filing_lag_uses_filing_date_and_not_retrieval_time(tmp_path: Path) -> None:
    results, nav, _coverage = parse_sec_nport_archive(
        _write_archive(tmp_path),
        FUNDS,
        accepted_at_by_accession=ACCEPTED_AT,
        retrieved_at="2099-01-01T00:00:00+00:00",
    )

    assert results[0].frame["known_at"].iloc[0] == ACCEPTED_AT["0000000000-00-000001"]
    assert nav[0]["as_of"] == "2024-12-31"
    assert nav[0]["filing_date"] == "2025-02-15"
    assert nav[0]["filing_lag_days"] == 46
    assert nav[0]["retrieved_at"] == "2099-01-01T00:00:00+00:00"
    assert nav[0]["dealing_eligibility"] is None
    assert nav[0]["dealing_eligibility_reason"] == "not_reported_by_n_port_bulk_dataset"


def test_one_failing_region_preserves_other_region_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = _write_archive(tmp_path)
    original_bytes = archive.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    document = SimpleNamespace(
        path=archive,
        sha256=original_hash,
        retrieved_at=datetime(2099, 1, 1),
    )

    def fetch(_provider: object, dataset: str, *, cache_only: bool = False):
        if dataset.startswith("nport_"):
            return document
        raise RuntimeError("synthetic N-CEN region failure")

    monkeypatch.setattr("etf_cockpit.data.fund_adapters.fetch_bulk", fetch)
    run = run_sec_fund_adapters(
        object(),
        "2025q1",
        FUNDS,
        network_enabled=True,
        accepted_at_by_accession=ACCEPTED_AT,
    )

    assert "nport" in run.documents
    assert "nport" not in run.failures
    assert "ncen" in run.failures
    assert len(run.holdings) == 1
    assert archive.read_bytes() == original_bytes
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == original_hash


def test_run_reports_coverage_denominators_by_market_asset_and_evidence_type(tmp_path: Path) -> None:
    _holdings, _nav, coverage = parse_sec_nport_archive(_write_archive(tmp_path), FUNDS)

    assert {"market", "asset_type", "evidence_type", "denominator_pct", "mapped_pct", "unknown_pct"} <= set(coverage.columns)
    assert set(coverage["market"]) >= {"US", "GB", "UNKNOWN"}
    assert set(coverage["asset_type"]) >= {"EC", "DBT", "UNKNOWN"}
    assert set(coverage["evidence_type"]) == {"sec_official"}
    assert coverage["denominator_pct"].sum() == pytest.approx(100.0)


def test_ncen_identity_has_no_inferred_nav_or_dealing_eligibility(tmp_path: Path) -> None:
    records = parse_sec_ncen_archive(
        _write_archive(tmp_path, "ncen"),
        FUNDS,
        accepted_at_by_accession={"0000000000-00-000002": "2025-03-01T14:00:00+00:00"},
    )

    assert records[0]["instrument_id"] == "SYNTHETF"
    assert records[0]["as_of"] == "2024-12-31"
    assert records[0]["nav_per_share"] is None
    assert records[0]["dealing_eligibility"] is None


def test_network_is_disabled_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def cache_only_fetch(_provider: object, _dataset: str, *, cache_only: bool = False):
        seen.append(cache_only)
        raise RuntimeError("synthetic cache miss")

    monkeypatch.setattr("etf_cockpit.data.fund_adapters.fetch_bulk", cache_only_fetch)
    run = run_sec_fund_adapters(object(), "2025q1", FUNDS)

    assert seen == [True, True]
    assert set(run.failures) == {"nport", "ncen"}
    assert run.coverage_denominators["unknown_pct"].sum() == pytest.approx(100.0)
