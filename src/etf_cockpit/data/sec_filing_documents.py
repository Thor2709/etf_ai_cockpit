"""Shadow 8-K earnings releases and 10-K sections parsed from stored SEC filings with EdgarTools (INT-18).

The input is the stored full-submission text of one filing; nothing here opens a socket (the filing
object is built from that text and every document is read from it). ``edgartools`` is the optional
``sec`` extra, imported lazily: without it every parser raises :class:`SecFilingDocumentUnavailable`.

Two times are never merged. ``sec_receipt_time`` is the acceptance time passed to the parsers; the fetch
callers pass the stored header's ACCEPTANCE-DATETIME, the real acceptance time.
``public_announcement_time`` is the release time printed in the EX-99.1 dateline, accepted only
when it names a full date, a clock time and a US time zone, sits in the dateline (before the first dash)
or is labelled as the release time, resolves to exactly one real instant, is unique, is not a call or
webcast time and is not later than the SEC receipt; otherwise it is ``"unavailable"`` with the reason.
The passed receipt must equal the stored header's ACCEPTANCE-DATETIME (US Eastern local time) or the parse is refused. Earnings
tables are unreviewed candidates and feed nothing. 10-K risk-factor and MD&A text becomes chunks for
the INT-23 store, known from the acceptance time.

``fetch_8k`` and ``fetch_10k_section_chunks`` are the callers: they take a filing already listed by the
EDGAR path (CIK and accession), read its full-submission text through :class:`SecEdgarProvider` (cache
first, then one request under the declared User-Agent and rate limit) and take ``known_at`` from the
stored header's ACCEPTANCE-DATETIME. With the network denied an uncached filing is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import re
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from etf_cockpit.core.values import finite_float_or_none as _number
from etf_cockpit.data.document_chunks import DocumentChunk, chunk_pages
from etf_cockpit.data.sec_edgar_provider import SecEdgarError, SecEdgarProvider, SecEdgarUnavailable
from etf_cockpit.data.sec_ownership import SecOwnershipUnavailable, _aware, prepare_edgar_environment

UNAVAILABLE = "unavailable"
_DATELINE_CHARS = 400
_ZONES = {"E": "America/New_York", "C": "America/Chicago", "M": "America/Denver", "P": "America/Los_Angeles"}
_STAMP = re.compile(
    r"(?i:(?P<month>January|February|March|April|May|June|July|August|September|October|November|December))"
    r"\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})[\s,]+(?i:at\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?i:(?P<ampm>[ap])\.?m\.?)\s+(?P<zone>[ECMP])(?P<dst>[SD])?T\b"
)
_DASH = re.compile(r"\s[-\u2013\u2014]{1,2}\s|[\u2013\u2014]")
_ACCEPTED = re.compile(r"<ACCEPTANCE-DATETIME>[ \t]*(\d{14})[ \t]*(?:\r?\n|$)")
_RELEASE_LABEL = re.compile(r"(?:release[sd]?|announce[sd]?)(?:\s+(?:date|time)(?:\s+and\s+time)?)?\s*(?:[:\-]|on|at)?\s*$", re.IGNORECASE)
_CALL_WORDS = re.compile(r"call|webcast|conference|dial|join", re.IGNORECASE)
_MONTHS = "january february march april may june july august september october november december".split()


SecFilingDocumentUnavailable = SecOwnershipUnavailable  # one "evidence cannot be produced" error for both SEC parsers


@dataclass(frozen=True)
class EarningsTableCandidate:
    exhibit: str
    statement_type: str
    scale: str
    currency: str | None
    columns: tuple[str, ...]
    rows: tuple[tuple[str, tuple[float | None, ...]], ...]  # None: the cell is not a finite number
    review_status: str = "unreviewed"


@dataclass(frozen=True)
class EightKFiling:
    accession: str
    form: str
    issuer_cik: str
    filed_date: str
    sec_receipt_time: datetime
    items: tuple[str, ...]  # e.g. ("2.02", "9.01")
    tables: tuple[EarningsTableCandidate, ...]
    public_announcement_time: str  # ISO instant or "unavailable"
    announcement_reason: str
    source_sha256: str

    @property
    def is_earnings_release(self) -> bool:
        return "2.02" in self.items


def _edgar() -> SimpleNamespace:
    prepare_edgar_environment()
    try:
        from edgar import Filing
        from edgar.company_reports.current_report import CurrentReport
        from edgar.company_reports.ten_k import TenK
        from edgar.earnings import find_earnings_exhibit, get_earnings_tables
    except ImportError as exc:
        raise SecFilingDocumentUnavailable("edgartools is not installed (optional `sec` extra)") from exc
    return SimpleNamespace(Filing=Filing, CurrentReport=CurrentReport, TenK=TenK,
                           find_earnings_exhibit=find_earnings_exhibit, get_earnings_tables=get_earnings_tables)


def _header_instants(digits: str) -> set[datetime]:
    """UTC instants a header stamp (US Eastern local time) can name: one, two in the fall-back hour, none in the gap."""
    try:
        naive = datetime.strptime(digits, "%Y%m%d%H%M%S")
    except ValueError as exc:  # fourteen digits that are not a calendar date and time
        raise SecFilingDocumentUnavailable("filing acceptance time is not a valid date and time") from exc
    zone = ZoneInfo("America/New_York")
    instants = {naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc) for fold in (0, 1)}
    return {i for i in instants if i.astimezone(zone).replace(tzinfo=None) == naive}


def _acceptance_digits(source: bytes) -> str:
    """The 14 digits of the one ACCEPTANCE-DATETIME field of the SEC header (text before the first document)."""
    header = source.decode("utf-8", "replace").split("<DOCUMENT>", 1)[0]
    stamp = _ACCEPTED.search(header)
    if stamp is None or header.count("<ACCEPTANCE-DATETIME>") != 1:
        raise SecFilingDocumentUnavailable("filing header has no single complete ACCEPTANCE-DATETIME")
    return stamp[1]


def _filing(ed: SimpleNamespace, source: bytes, forms: tuple[str, ...], known_at: datetime):
    text = source.decode("utf-8")
    if known_at.astimezone(timezone.utc) not in _header_instants(_acceptance_digits(source)):
        raise SecFilingDocumentUnavailable("known_at does not match the filing's stored acceptance time")
    filing = ed.Filing.from_sgml_text(text)
    if filing.form not in forms:
        raise SecFilingDocumentUnavailable(f"filing form {filing.form} is not {' or '.join(forms)}")
    return filing


def header_known_at(source: bytes) -> datetime:
    """The one UTC instant of the stored header's ACCEPTANCE-DATETIME (US Eastern local time), else unavailable."""
    instants = _header_instants(_acceptance_digits(source))
    if len(instants) != 1:  # the fall-back hour names two instants and the spring-forward gap none
        raise SecFilingDocumentUnavailable("filing acceptance time is not one real instant")
    return next(iter(instants))


def _stored_submission(provider: SecEdgarProvider, cik: str, accession: str) -> tuple[bytes, datetime]:
    try:
        source = provider.fetch_full_submission(cik, accession).path.read_bytes()
    except SecEdgarUnavailable as exc:
        raise SecFilingDocumentUnavailable("full submission is not cached and the SEC is unreachable") from exc
    except (SecEdgarError, ValueError, OSError) as exc:
        raise SecFilingDocumentUnavailable(f"full submission could not be read: {exc}") from exc
    return source, header_known_at(source)


def fetch_8k(provider: SecEdgarProvider, cik: str, accession: str) -> EightKFiling:
    """Fetch (or read the stored) full submission of a listed 8-K and parse it."""
    source, known_at = _stored_submission(provider, cik, accession)
    return parse_8k(source, known_at=known_at)


def fetch_10k_section_chunks(provider: SecEdgarProvider, cik: str, accession: str) -> list[DocumentChunk]:
    """Fetch (or read the stored) full submission of a listed 10-K and chunk its risk-factor and MD&A sections."""
    source, known_at = _stored_submission(provider, cik, accession)
    return parse_10k_section_chunks(source, known_at=known_at)


def parse_8k(source: bytes, *, known_at: datetime) -> EightKFiling:
    """Parse one stored 8-K: its items, earnings-release tables and the explicit release time."""
    known_at = _aware(known_at, "known_at")
    try:
        ed = _edgar()
        filing = _filing(ed, source, ("8-K", "8-K/A"), known_at)
        items = tuple(item.removeprefix("Item ") for item in ed.CurrentReport(filing).items)
        tables: tuple[EarningsTableCandidate, ...] = ()
        announced, reason = UNAVAILABLE, "not_an_earnings_release"
        exhibit = ed.find_earnings_exhibit(filing.attachments) if "2.02" in items else None
        if exhibit is not None:
            tables = tuple(_candidate(exhibit.document, table) for table in ed.get_earnings_tables(filing))
            announced, reason = _announcement(exhibit.text() or "", known_at)
        elif "2.02" in items:
            reason = "no_earnings_exhibit"
        return EightKFiling(
            accession=str(filing.accession_no), form=str(filing.form), issuer_cik=str(filing.cik).zfill(10),
            filed_date=str(filing.filing_date), sec_receipt_time=known_at, items=items, tables=tables,
            public_announcement_time=announced, announcement_reason=reason,
            source_sha256=hashlib.sha256(source).hexdigest(),
        )
    except SecFilingDocumentUnavailable:
        raise
    except Exception as exc:  # third-party parser boundary: any failure is an explicit unavailable
        raise SecFilingDocumentUnavailable(f"8-K could not be parsed: {type(exc).__name__}") from exc


def parse_10k_section_chunks(source: bytes, *, known_at: datetime) -> list[DocumentChunk]:
    """Risk-factor (page 1) and MD&A (page 2) chunks of one stored 10-K; a missing section adds none."""
    known_at = _aware(known_at, "known_at")
    try:
        ed = _edgar()
        filing = _filing(ed, source, ("10-K", "10-K/A"), known_at)
        report = ed.TenK(filing)
        sections = (("risk_factors", report.risk_factors), ("mda", report.management_discussion))
        when = known_at.isoformat()
        chunks = chunk_pages(
            [(text or "").strip() for _, text in sections], document_sha256=hashlib.sha256(source).hexdigest(),
            source_id="", published_at=when, known_at=when,
        )
        chunks = [replace(c, source_id=f"sec:{filing.form}:{filing.accession_no}:{sections[c.page - 1][0]}") for c in chunks]
    except SecFilingDocumentUnavailable:
        raise
    except Exception as exc:  # third-party parser boundary: any failure is an explicit unavailable
        raise SecFilingDocumentUnavailable(f"10-K could not be parsed: {type(exc).__name__}") from exc
    if not chunks:
        raise SecFilingDocumentUnavailable("10-K has no risk-factor or MD&A section")
    return chunks


def _candidate(exhibit: str, table: object) -> EarningsTableCandidate:
    frame = table.dataframe
    return EarningsTableCandidate(
        exhibit=str(exhibit), statement_type=str(table.statement_type.value), scale=str(table.scale.name),
        currency=table.currency, columns=tuple(str(c) for c in frame.columns),
        rows=tuple((str(label), tuple(_number(v) for v in values)) for label, values in zip(frame.index, frame.to_numpy())),
    )


def _announcement(text: str, receipt: datetime) -> tuple[str, str]:
    """(ISO instant, reason) of the one explicit release time in the dateline, else (unavailable, reason)."""
    instants = set()
    head = text[:_DATELINE_CHARS]
    dash = _DASH.search(head)
    dateline_end = dash.start() if dash else 0
    for match in _STAMP.finditer(head):
        if match.end() > dateline_end and not _RELEASE_LABEL.search(head[max(0, match.start() - 40):match.start()]):
            continue  # neither in the dateline nor labelled as the release time
        if _CALL_WORDS.search(text[max(0, match.start() - 120):match.end() + 40]):
            continue
        hour = int(match["hour"])
        if not 1 <= hour <= 12 or int(match["minute"] or 0) > 59:
            continue
        try:
            naive = datetime(int(match["year"]), _MONTHS.index(match["month"].lower()) + 1, int(match["day"]),
                             hour % 12 + (12 if match["ampm"].lower() == "p" else 0), int(match["minute"] or 0))
        except ValueError:  # an impossible calendar date is not an explicit time
            continue
        zone = ZoneInfo(_ZONES[match["zone"]])
        resolved = set()
        for fold in (0, 1):
            local = naive.replace(tzinfo=zone, fold=fold)
            utc = local.astimezone(timezone.utc)
            if utc.astimezone(zone).replace(tzinfo=None) != naive:
                continue  # spring-forward gap: this local time never occurred
            if match["dst"] and (local.dst() != timedelta(0)) != (match["dst"] == "D"):
                continue  # EST printed in summer or EDT in winter: the zone label contradicts the date
            resolved.add(utc)
        if len(resolved) == 1:  # a fall-back hour printed without EDT/EST names two instants: not explicit
            instants |= resolved
    if not instants:
        return UNAVAILABLE, "no_explicit_release_time"
    if len(instants) > 1:
        return UNAVAILABLE, "ambiguous_release_time"
    (instant,) = instants
    if instant > receipt:
        return UNAVAILABLE, "release_time_after_sec_receipt"
    return instant.isoformat(), "explicit_in_release"
