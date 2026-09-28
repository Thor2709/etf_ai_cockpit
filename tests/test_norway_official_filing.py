from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from scripts.import_official_filing import import_official_filing


FIXTURE = Path(__file__).parent / "fixtures" / "official" / "esef_report_package" / "synthetic-ming-2025.xbri"
URL = "https://newsweb.oslobors.no/message/999999"
# LEI carried by the synthetic fixture; a test value, not an asserted real-world identifier.
FIXTURE_LEI = "7V6Z97IO7R1SEAO84Q32"


def _run(output: Path, **kwargs: object) -> dict[str, object]:
    args = {
        "jurisdiction": "NO",
        "instrument_id": "MING",
        "source_url": URL,
        "expected_period": "2025-12-31",
        "published_at": "2026-03-05",
        "lei": FIXTURE_LEI,
        "output_dir": output,
    }
    args.update(kwargs)
    return import_official_filing(FIXTURE, **args)  # type: ignore[arg-type]


def test_synthetic_ming_import_reaches_normalised_pit_statements(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result["execution_allowed"] is False
    statements = pd.read_parquet(tmp_path / "normalised_statements.parquet")
    assert set(statements["canonical_metric"].dropna()) >= {"net_interest_income", "loans_to_customers", "deposits_from_customers"}
    assert statements["known_at"].eq("2026-03-05").all()
    assert statements["effective_at"].eq("2025-12-31").all()


def test_repeat_import_is_idempotent(tmp_path: Path) -> None:
    _run(tmp_path)
    _run(tmp_path)
    facts = pd.read_parquet(tmp_path / "statement_facts.parquet")
    inventory = pd.read_parquet(tmp_path / "filings_statements.parquet")
    assert len(facts) == facts["source_id"].nunique()
    assert len(inventory) == 1


def test_revised_filing_keeps_prior_revision(tmp_path: Path) -> None:
    revised = tmp_path / "revised.xbri"
    with zipfile.ZipFile(FIXTURE) as source, zipfile.ZipFile(revised, "w", zipfile.ZIP_DEFLATED) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename.endswith(".xhtml"):
                payload = payload.replace(b">600</ix:nonFraction>", b">601</ix:nonFraction>")
            target.writestr(member, payload)
    _run(tmp_path / "evidence")
    import_official_filing(
        revised,
        jurisdiction="NO",
        instrument_id="MING",
        source_url=URL,
        expected_period="2025-12-31",
        published_at="2026-03-06",
        lei=FIXTURE_LEI,
        output_dir=tmp_path / "evidence",
    )
    facts = pd.read_parquet(tmp_path / "evidence" / "statement_facts.parquet")
    assert facts["filing_version"].nunique() == 2


def test_wrong_issuer_and_orgnr_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="LEI"):
        _run(tmp_path / "lei", lei="00000000000000000000")
    with pytest.raises(ValueError, match="organisation number"):
        _run(tmp_path / "org", orgnr="999999999")


def test_non_official_host_and_checksum_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="official HTTPS host"):
        _run(tmp_path / "host", source_url="https://example.com/report.xbri")
    with pytest.raises(ValueError, match="checksum"):
        _run(tmp_path / "sha", expected_sha256="0" * 64)


def test_ec_fact_sheet_preserves_disclosures_and_unavailable_items(tmp_path: Path) -> None:
    sheet = tmp_path / "ec.json"
    sheet.write_text(
        json.dumps({
            "registered_ec_count": {
                "value": 101,
                "source_locator": "annual report 2025 note 4 p.20",
                "unit": "shares",
                "period": "2025-12-31",
            }
        }),
        encoding="utf-8",
    )
    _run(tmp_path / "evidence", fact_sheet=sheet)
    payload = json.loads((tmp_path / "evidence" / "ec_facts.json").read_text(encoding="utf-8"))
    assert payload["facts"]["registered_ec_count"]["available"] is True
    assert payload["facts"]["treasury_ec_count"]["available"] is False
    assert payload["facts"]["treasury_ec_count"]["value"] is None


def test_import_requires_explicit_issuer_lei(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="LEI"):
        _run(tmp_path / "nolei", lei=None)


def test_rejected_import_publishes_nothing(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    for kwargs in ({"expected_sha256": "0" * 64}, {"lei": "00000000000000000000"}, {"expected_period": "2024-12-31"}):
        with pytest.raises(ValueError):
            _run(output, **kwargs)
    assert not output.exists() or not any(p.is_file() for p in output.rglob("*"))
