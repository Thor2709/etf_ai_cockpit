from __future__ import annotations

import builtins
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from urllib.error import URLError

import pytest

from etf_cockpit.data import sec_filing_documents as sfd
from etf_cockpit.data.document_chunks import index_document, search
from etf_cockpit.data.sec_edgar_provider import SecEdgarError, SecEdgarProvider
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


AGENT = "ETF AI Cockpit tests research@company.org"
ACC_8K, ACC_10K = "0000777001-26-000010", "0000777001-26-000004"


def _provider(tmp_path: Path, transport, sleeps: list[float] | None = None) -> SecEdgarProvider:
    now = [0.0]  # a frozen clock of its own, so the shared rate-limit state of other tests is untouched
    return SecEdgarProvider(AGENT, cache_dir=tmp_path, transport=transport, rate_limit_seconds=0.1,
                            monotonic=lambda: now[0], sleep=(sleeps if sleeps is not None else []).append)


def test_full_submission_request_declares_the_user_agent_respects_the_rate_limit_and_is_cached(tmp_path: Path) -> None:
    bodies = {ACC_8K: _8k(), ACC_10K: (FIXTURES / "10k_sections.txt").read_bytes()}
    seen: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers: dict[str, str]) -> bytes:
        seen.append((url, headers))
        return bodies[url.rsplit("/", 1)[1].removesuffix(".txt")]

    sleeps: list[float] = []
    provider = _provider(tmp_path, transport, sleeps)
    first = provider.fetch_full_submission("0000777001", ACC_8K)
    provider.fetch_full_submission("777001", ACC_10K)
    assert seen[0][0] == f"https://www.sec.gov/Archives/edgar/data/777001/{ACC_8K}.txt"
    assert all(headers["User-Agent"] == AGENT for _, headers in seen)
    assert sleeps == [0.1]  # the second request waited out the rate limit on the frozen clock
    assert first.path.read_bytes() == bodies[ACC_8K] and first.document_type == "sec_full_submission"
    assert provider.fetch_full_submission("777001", ACC_8K).path == first.path and len(seen) == 2  # stored: no request
    with pytest.raises(ValueError, match="accession"):  # a body that is another filing is refused and not stored
        _provider(tmp_path / "other", lambda *_: bodies[ACC_10K]).fetch_full_submission("777001", ACC_8K)
    assert not (tmp_path / "other").exists()


def test_live_requests_keep_the_sec_minimum_interval_even_when_a_faster_limit_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status, headers = 200, {}

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self) -> bytes:
            return _8k()

    monkeypatch.setattr("etf_cockpit.data.sec_edgar_provider.urlopen", lambda *_a, **_k: Response())
    now, sleeps = [0.0], []
    live = SecEdgarProvider(AGENT, cache_dir=tmp_path, rate_limit_seconds=0, monotonic=lambda: now[0], sleep=sleeps.append)
    live.fetch_full_submission("777001", ACC_8K)
    live._get_document("https://www.sec.gov/Archives/edgar/data/777001/x.txt", "text/plain")
    assert sleeps == [0.1]  # a stubbed transport may use 0 (the tests above); a real request never goes below 100 ms


def test_header_known_at_is_the_eastern_acceptance_instant_and_refuses_ambiguous_hours() -> None:
    assert sfd.header_known_at(_8k()) == RECEIPT
    with pytest.raises(sfd.SecFilingDocumentUnavailable, match="ACCEPTANCE-DATETIME"):
        sfd.header_known_at(b"<SEC-HEADER>")
    with pytest.raises(sfd.SecFilingDocumentUnavailable, match="one real instant"):  # 01:30 occurs twice on 2026-11-01
        sfd.header_known_at(_8k().replace(b"20260730161500", b"20261101013000"))
    with pytest.raises(sfd.SecFilingDocumentUnavailable, match="valid date"):  # 14 digits, not a calendar date
        sfd.header_known_at(_8k().replace(b"20260730161500", b"20261399161500"))
    field = re.search(rb"<ACCEPTANCE-DATETIME>\d{14}\r?\n", _8k())[0]
    body_only = re.sub(rb"(<DOCUMENT>)", lambda m: m[1] + b"\n" + field, _8k().replace(field, b""), count=1)
    twice = _8k().replace(b"<SEC-HEADER>", b"<SEC-HEADER>" + field, 1)
    for source in (body_only, twice):  # a timestamp in the filing body is never the acceptance time; two fields are ambiguous
        with pytest.raises(sfd.SecFilingDocumentUnavailable, match="single complete ACCEPTANCE-DATETIME"):
            sfd.header_known_at(source)
        with pytest.raises(sfd.SecFilingDocumentUnavailable):  # the parse path reads the same header block
            sfd.parse_8k(source, known_at=RECEIPT)


def test_uncached_filing_is_unavailable_when_the_network_is_denied(tmp_path: Path) -> None:
    def denied(_url: str, _headers: dict[str, str]) -> bytes:
        raise URLError("network denied")

    provider = _provider(tmp_path, denied)
    with pytest.raises(sfd.SecFilingDocumentUnavailable, match="not cached"):
        sfd.fetch_8k(provider, "777001", ACC_8K)
    forbidden = _provider(tmp_path, lambda *_: (b"", 403, {}))  # any other SEC refusal is unavailable too, cause kept
    with pytest.raises(sfd.SecFilingDocumentUnavailable) as refused:
        sfd.fetch_8k(forbidden, "777001", ACC_8K)
    assert isinstance(refused.value.__cause__, SecEdgarError)
    with pytest.raises(sfd.SecFilingDocumentUnavailable, match="not cached"):
        sfd.fetch_10k_section_chunks(provider, "777001", ACC_10K)


def test_fetched_and_then_stored_submissions_parse_with_known_at_from_the_header(tmp_path: Path) -> None:
    pytest.importorskip("edgar")
    sfd._edgar()
    bodies = {ACC_8K: _8k(), ACC_10K: (FIXTURES / "10k_sections.txt").read_bytes()}
    live = _provider(tmp_path, lambda url, _h: bodies[url.rsplit("/", 1)[1].removesuffix(".txt")])
    filing = sfd.fetch_8k(live, "777001", ACC_8K)
    assert filing.sec_receipt_time == RECEIPT and filing.items == ("2.02", "9.01")
    assert filing.public_announcement_time == "2026-07-30T20:05:00+00:00"
    chunks = sfd.fetch_10k_section_chunks(live, "777001", ACC_10K)
    assert {datetime.fromisoformat(c.known_at) for c in chunks} == {datetime(2026, 2, 27, 21, 30, tzinfo=timezone.utc)}

    def denied(_url: str, _headers: dict[str, str]) -> bytes:
        raise URLError("network denied")

    offline = _provider(tmp_path, denied)  # same cache, no network: the stored submissions still parse
    assert sfd.fetch_8k(offline, "777001", ACC_8K) == filing
    assert [c.source_id for c in sfd.fetch_10k_section_chunks(offline, "777001", ACC_10K)] == [c.source_id for c in chunks]
