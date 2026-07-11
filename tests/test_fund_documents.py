from __future__ import annotations

from pathlib import Path

import pytest

from etf_cockpit.data.fund_documents import register_document


def test_document_registry_retains_checksum_and_missing_state(tmp_path: Path) -> None:
    path = tmp_path / "kid.pdf"
    path.write_bytes(b"fixture")
    document = register_document(path, "priips_kid", "VWCE", "https://issuer.example/kid.pdf", "issuer")
    assert document.sha256
    assert document.coverage_status == "available"
    with pytest.raises(ValueError):
        register_document(tmp_path / "missing.pdf", "factsheet", "VWCE", "https://issuer.example/factsheet.pdf", "issuer")
