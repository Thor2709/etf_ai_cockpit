from __future__ import annotations

import builtins
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from etf_cockpit.data import sec_filing_documents as sfd
from etf_cockpit.data.document_chunks import index_document, search
from etf_cockpit.plugins.registry import _network_probe

FIXTURES = Path(__file__).parent / "fixtures" / "sec_filing_documents"
RECEIPT = datetime(2026, 7, 30, 20, 15, tzinfo=timezone.utc)
STAMP = "July 30, 2026 at 4:05 p.m. ET"


def _8k(replace: str | None = None) -> bytes:
    text = (FIXTURES / "8k_earnings.txt").read_text(encoding="utf-8")
    return (text if replace is None else text.replace(STAMP, replace)).encode("utf-8")


def test_stored_8k_yields_items_one_table_and_separate_times_with_the_network_blocked() -> None:
    pytest.importorskip("edgar")
    sfd._edgar()  # first import happens outside the socket probe
    with _network_probe() as calls:
        filing = sfd.parse_8k(_8k(), known_at=RECEIPT)
    assert calls == []
    assert filing.items == ("2.02", "9.01") and filing.is_earnings_release
    assert filing.filed_date == "2026-07-30" and filing.sec_receipt_time == RECEIPT
    assert filing.public_announcement_time == "2026-07-30T20:05:00+00:00"  # 4:05 p.m. EDT, ahead of the SEC receipt
    (table,) = filing.tables
    assert table.review_status == "unreviewed" and table.exhibit == "ex991.htm"
    assert dict(table.rows)["Revenue"] == (1200.0, 1000.0) and table.scale == "THOUSANDS"
    labelled = sfd.parse_8k(_8k("July 30, 2026 - Release time: July 30, 2026 at 4:05 p.m. ET"), known_at=RECEIPT)
    assert labelled.public_announcement_time == "2026-07-30T20:05:00+00:00"  # explicitly named as the release time
    with pytest.raises(sfd.SecFilingDocumentUnavailable, match="acceptance"):  # receipt differs from the stored header
        sfd.parse_8k(_8k(), known_at=RECEIPT + timedelta(minutes=1))
    real = _8k().replace(b"20260730161500", b"20261112185820")  # header is Eastern local time: 18:58:20 EST
    assert sfd.parse_8k(real, known_at=datetime(2026, 11, 12, 23, 58, 20, tzinfo=timezone.utc)).sec_receipt_time.hour == 23
    with pytest.raises(sfd.SecFilingDocumentUnavailable, match="acceptance"):  # the header read as UTC is refused
        sfd.parse_8k(real, known_at=datetime(2026, 11, 12, 18, 58, 20, tzinfo=timezone.utc))
    with pytest.raises(sfd.SecFilingDocumentUnavailable, match="acceptance"):  # sub-second drift is not the stored time
        sfd.parse_8k(real, known_at=datetime(2026, 11, 12, 23, 58, 20, 500000, tzinfo=timezone.utc))


@pytest.mark.parametrize("printed, reason", [
    ("July 30, 2026 after the market close", "no_explicit_release_time"),
    ("July 30, 2026. Management will host a conference call at 4:30 p.m. ET", "no_explicit_release_time"),
    ("July 30, 2026 at 5:00 p.m. ET", "release_time_after_sec_receipt"),
    ("July 30, 2026 at 4:05 p.m. EST", "no_explicit_release_time"),  # EST in July contradicts the date
    ("July 30, 2026 - trading was halted on July 30, 2026 at 3:00 p.m. ET", "no_explicit_release_time"),  # not the dateline
    ("November 1, 2026 at 1:30 a.m. ET", "no_explicit_release_time"),  # fall-back hour occurs twice
    ("March 8, 2026 at 2:30 a.m. ET", "no_explicit_release_time"),  # spring-forward hour does not exist
])
def test_announcement_time_is_unavailable_unless_the_release_prints_it_explicitly(printed: str, reason: str) -> None:
    pytest.importorskip("edgar")
    filing = sfd.parse_8k(_8k(printed), known_at=RECEIPT)
    assert filing.public_announcement_time == "unavailable" and filing.announcement_reason == reason
    assert filing.sec_receipt_time == RECEIPT and len(filing.tables) == 1


def test_10k_risk_factor_and_mda_sections_become_chunks_known_only_from_acceptance(tmp_path: Path) -> None:
    pytest.importorskip("edgar")
    source = (FIXTURES / "10k_sections.txt").read_bytes()
    accepted = datetime(2026, 2, 27, 21, 30, tzinfo=timezone.utc)
    chunks = sfd.parse_10k_section_chunks(source, known_at=accepted)
    assert {(c.page, c.source_id.rsplit(":", 1)[1]) for c in chunks} == {(1, "risk_factors"), (2, "mda")}
    store = tmp_path / "chunks.sqlite3"
    index_document(store, chunks)
    hit = search(store, "competition larger vendors", as_of="2026-03-01T00:00:00Z")["hits"][0]
    assert hit["page"] == 1 and hit["char_start"] == 0 and hit["source_id"].endswith(":risk_factors")
    assert search(store, "competition", as_of="2026-02-27T21:00:00Z")["hits"] == []  # before acceptance
    with pytest.raises(sfd.SecFilingDocumentUnavailable, match="acceptance"):
        sfd.parse_10k_section_chunks(source, known_at=accepted + timedelta(seconds=1))


def test_missing_edgartools_and_naive_times_are_explicit_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def without_edgar(name: str, *args: object, **kwargs: object):
        if name == "edgar" or name.startswith("edgar."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", without_edgar)
        with pytest.raises(sfd.SecFilingDocumentUnavailable, match="optional `sec` extra"):
            sfd.parse_8k(b"", known_at=RECEIPT)
    with pytest.raises(sfd.SecFilingDocumentUnavailable, match="timezone-aware"):
        sfd.parse_8k(b"", known_at=datetime(2026, 7, 30))
