from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from etf_cockpit.data.legal_terms import (
    LegalTermsError,
    filter_restricted_exports,
    legal_terms_report,
    load_legal_terms,
    terms_change_requires_review,
)


def test_legal_terms_registry_has_no_unresolved_mandatory_entries_and_is_no_network() -> None:
    report = legal_terms_report(Path.cwd())

    assert report["status"] == "passed"
    assert report["network_calls"] is False
    assert report["unresolved_mandatory"] == []
    assert report["professional_review_required"] is True
    assert report["registry_sha256"] == load_legal_terms().checksum


def test_restricted_sources_are_excluded_from_standard_audit_exports() -> None:
    registry = load_legal_terms()
    records = [
        {"provider_id": "yfinance", "value": "restricted"},
        {"provider_id": "issuer_document", "value": "metadata-only"},
        {"provider_id": "sec_edgar", "value": "official", "user_owned": False},
    ]

    exported = filter_restricted_exports(records, registry)

    assert [row["provider_id"] for row in exported] == ["sec_edgar"]
    assert registry.can_export("issuer_document", "audit_export") is False
    assert registry.can_export("yfinance", "redistribution") is False


def test_terms_changes_require_review() -> None:
    registry = load_legal_terms()
    changed = replace(registry, jurisdictions=({"jurisdiction_id": "AU", "disclaimer": "Changed wording."},))

    assert terms_change_requires_review(registry, changed) is True
    assert terms_change_requires_review(registry, registry) is False


def test_official_jurisdiction_sources_have_fail_closed_terms_records() -> None:
    registry = load_legal_terms()
    source_ids = {
        "dk_finanstilsynet_oam",
        "fi_fsa_oam",
        "fr_dila_oam",
        "gb_companies_house",
        "nl_afm_oam",
        "no_finanstilsynet_oam",
        "se_fi_oam",
    }

    entries = [registry.entry(source_id) for source_id in source_ids]
    assert all(entry is not None and not entry.unresolved for entry in entries)
    assert all(entry.audit_export == "metadata_only" for entry in entries if entry is not None)
    assert all(not registry.can_export(source_id, "audit_export") for source_id in source_ids)


def test_unresolved_mandatory_terms_fail_closed(tmp_path: Path) -> None:
    source = Path("configs/legal_terms_registry.yaml").read_text(encoding="utf-8")
    invalid = source.replace("terms_status: user_owned_terms", "terms_status: unresolved", 1)
    path = tmp_path / "legal_terms_registry.yaml"
    path.write_text(invalid, encoding="utf-8")

    with pytest.raises(LegalTermsError, match="unresolved"):
        load_legal_terms(path)
