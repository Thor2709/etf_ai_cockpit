from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import zipfile

import pandas as pd

from etf_cockpit.application.financial_institution_views import load_financial_institution_projection
from etf_cockpit.application.identity_views import load_identity_projection
from etf_cockpit.parsers.contracts import RawDocument
from scripts.import_official_filing import import_official_filing
from scripts.sparebank_refresh import refresh_sparebanks


FIXTURE = Path(__file__).parent / "fixtures" / "official" / "esef_report_package" / "synthetic-ming-2025.xbri"
PUBLISHED_AT = "2026-03-05"
LEI_ONE = "FAKELEI0000000000001"
LEI_TWO = "FAKELEI0000000000002"


def _universe(root: Path, entries: tuple[tuple[str, str, str, str | None], ...]) -> Path:
    config_dir = root / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    rows = ["etfs:"]
    for index, (instrument_id, name, ticker, lei) in enumerate(entries):
        rows.extend(
            [
                f"  - id: {instrument_id}",
                f"    name: {name}",
                f"    isin: NO{index + 1:010d}",
                f"    ticker: {ticker}",
                f"    instrument_type: equity_certificate",
                "    analysis_tier: sparebanken",
                "    data_policy: yfinance_only",
                "    region: Norway",
                "    sector: Banks",
                "    enabled: true",
            ]
        )
        if lei:
            rows.append(f"    lei: {lei}")
    path = config_dir / "universe.yaml"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _fixture_for_issuer(path: Path, lei: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    replaced = False
    with zipfile.ZipFile(FIXTURE) as source, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename.lower().endswith((".xhtml", ".html")):
                payload, count = payload.replace(b"7V6Z97IO7R1SEAO84Q32", lei.encode("ascii")), payload.count(b"7V6Z97IO7R1SEAO84Q32")
                replaced = replaced or count > 0
            target.writestr(member, payload)
    assert replaced
    return path


def test_synthetic_universe_record_imports_and_scores_without_a_code_edit(tmp_path: Path) -> None:
    _universe(tmp_path, (("SYNTHBANK", "Synthetic Sparebank", "SYNTH.OL", LEI_ONE),))
    package = _fixture_for_issuer(tmp_path / "package.xbri", LEI_ONE)
    source_url = f"https://filings.xbrl.org/{LEI_ONE}/2025-12-31/ESEF/NO/0/synthetic.xbri"

    imported = import_official_filing(
        package,
        jurisdiction="NO",
        instrument_id="SYNTHBANK",
        source_url=source_url,
        expected_period="2025-12-31",
        published_at=PUBLISHED_AT,
        output_dir=tmp_path / "evidence" / "norway" / "SYNTHBANK-2025",
        universe_root=tmp_path,
    )
    projection = load_financial_institution_projection(
        "SYNTHBANK",
        storage_root=tmp_path,
        universe_root=tmp_path,
        effective_at="2025-12-31",
        decision_time="2026-03-06T00:00:00Z",
    )

    identity = json.loads((tmp_path / "evidence" / "norway" / "SYNTHBANK-2025" / "identity.json").read_text(encoding="utf-8"))
    share_identity = projection["share_class_identity"]
    analysis = share_identity["sparebank_analysis"]
    assert imported["instrument_id"] == "SYNTHBANK"
    assert identity["ticker"] == "SYNTH.OL"
    assert identity["lei"] == LEI_ONE
    assert identity["isin"] == "NO0000000001"
    assert identity["instrument_type"] == "equity_certificate"
    assert analysis["routing"]["applies"] is True
    # The imported filing feeds the scorecard: at least one filing-based axis is rated.
    price_axes = {"marketability_implementation", "owner_valuation_expectations"}
    assert any(
        axis.get("rating_10") is not None
        for axis_id, axis in analysis["scorecard"]["axes"].items()
        if axis_id not in price_axes
    )


class _RefreshClient:
    def __init__(self, download_root: Path) -> None:
        self.download_root = download_root
        self.rows = (
            {
                "id": "filing-fail",
                "entity_lei": LEI_TWO,
                "period_end": "2025-12-31",
                "date_added": PUBLISHED_AT,
                "package_url": f"https://filings.xbrl.org/{LEI_TWO}/2025-12-31/ESEF/NO/0/fail.xbri",
            },
            {
                "id": "filing-good",
                "entity_lei": LEI_ONE,
                "period_end": "2025-12-31",
                "date_added": PUBLISHED_AT,
                "package_url": f"https://filings.xbrl.org/{LEI_ONE}/2025-12-31/ESEF/NO/0/good.xbri",
            },
        )

    def filings_for_lei(self, lei):
        return self.rows

    def download(self, filing):
        if filing["id"] == "filing-fail":
            raise OSError("synthetic package download failure")
        path = _fixture_for_issuer(self.download_root / "good.xbri", LEI_ONE)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return RawDocument(
            path,
            str(filing["package_url"]),
            datetime.now(timezone.utc),
            digest,
            "filings_xbrl_org",
            "esef_report_package",
            "application/octet-stream",
            200,
        )


def test_refresh_isolates_download_failure_and_imports_other_banks(tmp_path: Path) -> None:
    _universe(
        tmp_path,
        (
            ("FAILBANK", "Failed Sparebank", "FAIL.OL", LEI_TWO),
            ("GOODBANK", "Working Sparebank", "GOOD.OL", LEI_ONE),
        ),
    )
    rows = refresh_sparebanks(
        tmp_path,
        universe_root=tmp_path,
        client=_RefreshClient(tmp_path / "downloads"),
        decision_time="2026-03-06T00:00:00Z",
        rescorer=lambda *_args: (4.25, 0.08, "partial"),
    )

    by_id = {str(row["id"]): row for row in rows}
    summary = json.loads((tmp_path / "evidence" / "norway" / "sparebank_refresh_summary.json").read_text(encoding="utf-8"))
    assert by_id["FAILBANK"]["reason"] == "refresh_failed: OSError: synthetic package download failure"
    assert by_id["GOODBANK"]["filing_date"] == PUBLISHED_AT
    assert by_id["GOODBANK"]["composite"] == 4.25
    assert (tmp_path / "evidence" / "norway" / "GOODBANK-2025" / "identity.json").is_file()
    assert summary["banks"] == list(rows)


def test_certificate_without_filing_routes_and_scores_from_price_history(tmp_path: Path) -> None:
    _universe(tmp_path, (("PRICEBANK", "Price Sparebank", "PRICE.OL", LEI_ONE),))
    price_path = tmp_path / "data" / "clean" / "prices.parquet"
    price_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {"date": "2025-01-02", "etf_id": "PRICEBANK", "open": 99, "high": 101, "low": 98, "close": 100, "adjusted_close": 100, "volume": 12000, "currency": "NOK", "provider_symbol": "PRICE.OL", "source": "Yahoo Finance", "is_adjusted": True, "dividends": 0.0},
            {"date": "2025-01-03", "etf_id": "PRICEBANK", "open": 99, "high": 101, "low": 98, "close": 101, "adjusted_close": 101, "volume": 16000, "currency": "NOK", "provider_symbol": "PRICE.OL", "source": "Yahoo Finance", "is_adjusted": True, "dividends": 2.0},
        ]
    ).to_parquet(price_path, index=False)
    projection = load_financial_institution_projection(
        "PRICEBANK",
        storage_root=tmp_path,
        universe_root=tmp_path,
    )
    identity_projection = tmp_path / "data" / "clean" / "instrument_identity.parquet"
    pd.DataFrame([{"instrument_id": "PRICEBANK", "display_name": "Price Sparebank", "instrument_type": "ETF"}]).to_parquet(identity_projection, index=False)
    identity = load_identity_projection(
        "PRICEBANK",
        storage_root=tmp_path,
        universe_root=tmp_path,
    )
    analysis = projection["share_class_identity"]["sparebank_analysis"]
    scorecard = analysis["scorecard"]

    assert identity["instrument_type"] == "equity_certificate"
    assert analysis["routing"]["applies"] is True
    # Price-only evidence is below min_coverage_for_composite: no composite, but the reason and coverage are shown.
    assert scorecard["composite_10"] is None
    assert "MINIMUM_COMPOSITE_COVERAGE_NOT_MET" in scorecard["gate_reasons"]
    assert 0.0 < scorecard["composite_coverage"] < 1.0
    assert scorecard["axes"]["marketability_implementation"]["rating_10"] is not None


def test_source_has_no_hardcoded_sparebank_issuer_table() -> None:
    repository = Path(__file__).resolve().parents[1]
    tickers = ("AURG", "NONG", "RING", "SOAG", "SPOL", "MORG", "SPOG", "MING")
    expected_existing_uses = {
        "scripts/smoke_app.py": {"AURG", "NONG"},
        "src/etf_cockpit/analysis/financial_sector_adapters.py": {"MING"},
    }
    matches: dict[str, set[str]] = {}
    for folder in (repository / "scripts", repository / "src"):
        for path in folder.rglob("*"):
            if path.suffix not in {".py", ".json"} or {"configs", "fixtures"}.intersection(path.parts):
                continue
            relative = path.relative_to(repository).as_posix()
            source = path.read_text(encoding="utf-8")
            found = {ticker for ticker in tickers if re.search(rf"\b{ticker}\b", source)}
            if found:
                matches[relative] = found
    assert matches == expected_existing_uses
