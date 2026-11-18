"""Shadow SEC insider (Form 3/4/5) and 13F evidence parsed with EdgarTools.

The Cockpit fetches the XML (``SecEdgarProvider.fetch_filing_document``) and the parsers here run
on those bytes only. ``edgartools`` is the optional ``sec`` extra and is imported lazily: without it
every parser raises :class:`SecOwnershipUnavailable` and the base install is unaffected.

``known_at`` is the filing acceptance time taken from the submissions record (``available_at``);
nothing is read from a clock. A filing accepted after the decision time is never used. These are
shadow features only: nothing here feeds a score or a decision. ``Ownership.from_xml`` is not used
because it resolves each reporting owner through a network lookup; the table parsers it is built
from are used directly instead.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import math
import os
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
from typing import Any

POSITIONS_LABEL = "positions at period_end as reported by known_at; not current exposure"
_SIGNAL_CODES = {"P": "purchase", "S": "sale"}
_THIRTEENF_PARTIAL_REPORTS = ("NOTICE", "COMBINATION")


class SecOwnershipUnavailable(RuntimeError):
    """The evidence cannot be produced; the message is the explicit reason."""


def _edgar() -> SimpleNamespace:
    # edgartools creates its HTTP cache folder at import; keep that out of the user profile.
    os.environ.setdefault("EDGAR_LOCAL_DATA_DIR", str(Path(tempfile.gettempdir()) / "etf_cockpit_edgartools"))
    try:
        from edgar.ownership.core import detect_10b5_1_plan
        from edgar.ownership.models import Footnotes
        from edgar.ownership.table_containers import DerivativeTable, NonDerivativeTable
        from edgar.thirteenf.parsers.infotable_xml import parse_infotable_xml
        from edgar.thirteenf.parsers.primary_xml import parse_primary_document_xml
        from edgar.xmltools import child_text, find_all_elements, find_element, local_name, parse_xml, parse_xml_boolean
    except ImportError as exc:
        raise SecOwnershipUnavailable("edgartools is not installed (optional `sec` extra)") from exc
    return SimpleNamespace(
        detect_10b5_1_plan=detect_10b5_1_plan, Footnotes=Footnotes, DerivativeTable=DerivativeTable,
        NonDerivativeTable=NonDerivativeTable, parse_infotable_xml=parse_infotable_xml,
        parse_primary_document_xml=parse_primary_document_xml, child_text=child_text,
        find_all_elements=find_all_elements, find_element=find_element, local_name=local_name,
        parse_xml=parse_xml, parse_xml_boolean=parse_xml_boolean,
    )


def _aware(value: object, what: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SecOwnershipUnavailable(f"{what} must be a timezone-aware datetime")
    return value


def _cik(value: object) -> str:
    text = str(value or "").strip()
    if not text.isdigit() or int(text) <= 0 or len(text) > 10:
        raise SecOwnershipUnavailable("filing identity CIK is missing or invalid")
    return text.zfill(10)


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass(frozen=True)
class InsiderTransaction:
    code: str
    acquired_disposed: str
    shares: float | None
    price: float | None
    security_title: str
    is_derivative: bool
    transaction_date: date | None
    is_10b5_1: bool
    exclusion_reason: str | None  # None means the row counts for signals

    @property
    def signal(self) -> str | None:
        return None if self.exclusion_reason else _SIGNAL_CODES.get(self.code)


@dataclass(frozen=True)
class InsiderFiling:
    accession: str
    form: str
    issuer_cik: str
    issuer_ticker: str
    known_at: datetime
    source_sha256: str
    insider_ciks: tuple[str, ...]  # reporting owners that are officers or directors
    transactions: tuple[InsiderTransaction, ...]


def parse_ownership_xml(xml: bytes, *, accession: str, known_at: datetime) -> InsiderFiling:
    """Parse one Form 3/4/5 document. Form 3 holds no transactions; Form 4/A rows never count."""
    known_at = _aware(known_at, "known_at")
    ed = _edgar()
    try:
        root = ed.parse_xml(xml.decode("utf-8"))
        if ed.local_name(root) != "ownershipDocument":
            raise ValueError("not an ownershipDocument")
        form = ed.child_text(root, "documentType") or ""
        issuer = ed.find_element(root, "issuer")
        issuer_cik = _cik(ed.child_text(issuer, "issuerCik"))
        # Filing-level remarks cannot be tied to single rows, so a plan disclosed there covers every row.
        document_plan = ed.parse_xml_boolean(ed.child_text(root, "aff10b5One")) is True or ed.detect_10b5_1_plan(ed.child_text(root, "remarks")) is True
        footnotes = ed.Footnotes.extract(root)
        insiders = []
        for owner in ed.find_all_elements(root, "reportingOwner"):
            relationship = ed.find_element(owner, "reportingOwnerRelationship")
            if any(ed.parse_xml_boolean(ed.child_text(relationship, tag)) for tag in ("isOfficer", "isDirector")):
                insiders.append(_cik(ed.child_text(ed.find_element(owner, "reportingOwnerId"), "rptOwnerCik")))
        transactions: list[InsiderTransaction] = []
        for derivative, tag, table_type in ((False, "nonDerivativeTable", ed.NonDerivativeTable), (True, "derivativeTable", ed.DerivativeTable)):
            element = ed.find_element(root, tag)
            table = table_type.extract(element, form=form) if element is not None else None
            if table is None or not table.has_transactions:
                continue
            for row in table.transactions.data.to_dict("records"):
                ids = re.split(r"[\s,]+", str(row.get("footnotes") or "").strip())
                text = " ".join(footnotes.get(i, "") for i in ids if i)
                planned = document_plan or ed.detect_10b5_1_plan(text) is True
                when = _date(row.get("Date"))
                code = str(row.get("Code") or "")
                transactions.append(InsiderTransaction(
                    code=code, acquired_disposed=str(row.get("AcquiredDisposed") or ""),
                    shares=_number(row.get("Shares")), price=_number(row.get("Price")),
                    security_title=str(row.get("Security") or ""), is_derivative=derivative,
                    transaction_date=when, is_10b5_1=planned,
                    exclusion_reason=_exclusion(code, derivative, planned, when, form, row.get("EquitySwap") in (True,)),
                ))
    except SecOwnershipUnavailable:
        raise
    except Exception as exc:  # third-party parser boundary: any failure is an explicit unavailable
        raise SecOwnershipUnavailable(f"ownership document could not be parsed: {type(exc).__name__}") from exc
    return InsiderFiling(
        accession=accession, form=form, issuer_cik=issuer_cik,
        issuer_ticker=ed.child_text(issuer, "issuerTradingSymbol") or "", known_at=known_at,
        source_sha256=hashlib.sha256(xml).hexdigest(), insider_ciks=tuple(sorted(set(insiders))),
        transactions=tuple(transactions),
    )


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _exclusion(code: str, derivative: bool, planned: bool, when: date | None, form: str, swap: bool) -> str | None:
    if derivative:
        return "derivative_row"
    if form.upper().endswith("/A"):
        return "amendment_not_reconciled"
    if code not in _SIGNAL_CODES:
        return f"code_{code or 'missing'}"  # A grant, M exercise, F tax withholding, G gift, ...
    if planned:
        return "rule_10b5_1_plan"
    if swap:
        return "equity_swap"
    return None if when is not None else "transaction_date_missing"


@dataclass(frozen=True)
class ShadowFeature:
    name: str
    status: str  # "ok" | "unavailable"
    value: float | None
    reason: str | None
    detail: Mapping[str, Any]


def _unavailable(name: str, reason: str) -> ShadowFeature:
    return ShadowFeature(name, "unavailable", None, reason, {})


def insider_purchase_features(
    filings: Iterable[InsiderFiling], *, issuer_cik: str, decision_time: datetime,
    window_days: int = 90, cluster_min_buyers: int = 3,
) -> dict[str, ShadowFeature]:
    """Net open-market shares bought by officers and directors, and the cluster-buy count."""
    names = ("insider_net_open_market_shares", "insider_cluster_buyers")
    decision_time = _aware(decision_time, "decision_time")
    issuer = _cik(issuer_cik)
    visible = [f for f in filings if f.issuer_cik == issuer and f.known_at <= decision_time]
    if not visible:
        return {name: _unavailable(name, "no_insider_filing_known_by_decision_time") for name in names}
    start = decision_time.date() - timedelta(days=window_days)
    net_shares, net_value, unpriced = 0.0, 0.0, 0
    buyers: set[str] = set()
    covered = unsized_any = unsized_buy = False
    for filing in visible:
        if not filing.insider_ciks:
            continue
        covered = covered or start < filing.known_at.date()  # a filing inside the window shows the window was observed
        for row in filing.transactions:
            if row.signal is None or not start < (row.transaction_date or start) <= decision_time.date():
                continue
            if row.shares is None:
                unsized_any, unsized_buy = True, unsized_buy or row.signal == "purchase"
                continue
            sign = 1 if row.signal == "purchase" else -1
            net_shares += sign * row.shares
            if row.price is None:
                unpriced += 1
            else:
                net_value += sign * row.shares * row.price
            if sign > 0:
                buyers.update(filing.insider_ciks)
    if not covered:
        return {name: _unavailable(name, "no_insider_filing_in_window") for name in names}
    detail = {"window_days": window_days, "net_value_usd": None if unpriced else net_value, "unpriced_rows": unpriced}
    return {
        names[0]: _unavailable(names[0], "signal_row_shares_missing") if unsized_any else ShadowFeature(names[0], "ok", net_shares, None, detail),
        names[1]: _unavailable(names[1], "purchase_row_shares_missing") if unsized_buy else ShadowFeature(names[1], "ok", float(len(buyers)), None, {**detail, "is_cluster": len(buyers) >= cluster_min_buyers, "cluster_min_buyers": cluster_min_buyers}),
    }


@dataclass(frozen=True)
class Holding13F:
    cusip: str
    issuer: str
    title_of_class: str
    shares: int
    shares_type: str  # "Shares" or "Principal"
    put_call: str


@dataclass(frozen=True)
class Filing13F:
    accession: str
    form: str
    manager_cik: str
    period_end: date
    known_at: datetime
    report_type: str
    amendment_type: str | None  # "RESTATEMENT" replaces; "NEW HOLDINGS" adds previously confidential rows
    amendment_number: int | None
    incomplete_reasons: tuple[str, ...]
    source_sha256: str
    holdings: tuple[Holding13F, ...]

    @property
    def is_amendment(self) -> bool:
        return self.form.upper().endswith("/A")


def parse_13f(
    primary_xml: bytes, infotable_xml: bytes | None, *, accession: str, form: str, manager_cik: str, known_at: datetime,
) -> Filing13F:
    """Parse a 13F primary document and its information table (``None`` for a notice report)."""
    known_at = _aware(known_at, "known_at")
    manager = _cik(manager_cik)
    ed = _edgar()
    try:
        primary = ed.parse_primary_document_xml(primary_xml.decode("utf-8"))
        cover = primary.cover_page
        report_type = str(cover.report_type or "")
        info = cover.amendment_info
        amendment_type = (info.amendment_type or "").strip().upper() or None if info is not None else None
        reasons = [f"report_type_{key.lower()}" for key in _THIRTEENF_PARTIAL_REPORTS if key in report_type.upper()]
        if amendment_type == "NEW HOLDINGS":
            reasons.append("partial_new_holdings_only")
        holdings: tuple[Holding13F, ...] = ()
        if infotable_xml is not None:
            text = infotable_xml.decode("utf-8")
            table = ed.parse_infotable_xml(text)
            entries = ed.find_all_elements(ed.parse_xml(text), "infoTable")
            declared = primary.summary_page.total_holdings
            if not entries or not len(entries) == len(table) == declared:
                raise SecOwnershipUnavailable(f"13F information table has {len(table)} of {len(entries)} entries parsed, {declared} declared")
            if any(_number(ed.child_text(e, "sshPrnamt")) is None for e in entries):
                raise SecOwnershipUnavailable("13F information table entry without a share quantity")
            holdings = tuple(
                Holding13F(str(r["Cusip"]), str(r["Issuer"]), str(r["Class"]), int(r["SharesPrnAmount"]), str(r["Type"]), str(r["PutCall"]))
                for r in table.to_dict("records")
            )
        elif not reasons:
            raise ValueError("information table is missing")
    except SecOwnershipUnavailable:
        raise
    except Exception as exc:  # third-party parser boundary: any failure is an explicit unavailable
        raise SecOwnershipUnavailable(f"13F document could not be parsed: {type(exc).__name__}") from exc
    return Filing13F(
        accession=accession, form=form, manager_cik=manager, period_end=primary.report_period.date(), known_at=known_at,
        report_type=report_type, amendment_type=amendment_type, amendment_number=cover.amendment_number,
        incomplete_reasons=tuple(reasons), source_sha256=hashlib.sha256(primary_xml + b"\0" + (infotable_xml or b"")).hexdigest(),
        holdings=holdings,
    )


@dataclass(frozen=True)
class ThirteenFView:
    status: str  # "ok" | "unavailable"
    reason: str | None
    manager_cik: str
    period_end: date
    known_at: datetime | None
    accessions: tuple[str, ...]
    superseded: tuple[str, ...]  # replaced by a later accepted amendment; the filings themselves are kept
    incomplete_reasons: tuple[str, ...]
    holdings: tuple[Holding13F, ...]
    label: str = POSITIONS_LABEL


def thirteenf_view(
    filings: Iterable[Filing13F], *, manager_cik: str, period_end: date, decision_time: datetime,
) -> ThirteenFView:
    """The holdings for one manager and quarter as known at ``decision_time``.

    A restatement replaces the original only from its own acceptance time; a NEW HOLDINGS amendment is
    added to the filing it follows; an amendment of unknown type is never applied and is reported.
    """
    decision_time = _aware(decision_time, "decision_time")
    manager = _cik(manager_cik)
    group = sorted(
        (f for f in filings if f.manager_cik == manager and f.period_end == period_end and f.known_at <= decision_time),
        key=lambda f: (f.known_at, f.accession),
    )
    full = [f for f in group if not f.is_amendment or f.amendment_type == "RESTATEMENT"]
    if not full:
        reason = "no_13f_known_by_decision_time" if not group else "no_complete_13f_known_by_decision_time"
        return ThirteenFView("unavailable", reason, manager, period_end, None, (), (), (), ())
    base = full[-1]
    later = group[group.index(base) + 1:]
    used = [base] + [f for f in later if f.amendment_type == "NEW HOLDINGS"]
    reasons = list(base.incomplete_reasons) + [f"amendment_type_unknown:{f.accession}" for f in later if f.amendment_type not in ("NEW HOLDINGS", "RESTATEMENT")]
    return ThirteenFView(
        "ok", None, manager, period_end, used[-1].known_at, tuple(f.accession for f in used),
        tuple(f.accession for f in full[:-1]), tuple(reasons), tuple(h for f in used for h in f.holdings),
    )


def holder_share_change(
    filings: Iterable[Filing13F], *, cusip: str, period_end: date, prior_period_end: date, decision_time: datetime,
) -> ShadowFeature:
    """Quarter-on-quarter share change in one CUSIP over managers with a complete report for both quarters."""
    name = "13f_share_change_qoq"
    decision_time = _aware(decision_time, "decision_time")
    filings = [f for f in filings if f.known_at <= decision_time]
    now_held = prior_held = 0
    holders_now = holders_prior = matched = skipped = 0
    for manager in sorted({f.manager_cik for f in filings}):
        views = [thirteenf_view(filings, manager_cik=manager, period_end=p, decision_time=decision_time) for p in (period_end, prior_period_end)]
        if any(v.status != "ok" or v.incomplete_reasons for v in views):
            skipped += 1
            continue
        matched += 1
        current, prior = (sum(h.shares for h in v.holdings if h.cusip == cusip and h.shares_type == "Shares" and not h.put_call) for v in views)
        now_held, prior_held = now_held + current, prior_held + prior
        holders_now, holders_prior = holders_now + (current > 0), holders_prior + (prior > 0)
    if not matched:
        return _unavailable(name, "no_manager_with_complete_13f_for_both_quarters_known_by_decision_time")
    detail = {
        "label": POSITIONS_LABEL, "period_end": period_end.isoformat(), "prior_period_end": prior_period_end.isoformat(),
        "matched_managers": matched, "skipped_managers": skipped, "holders_now": holders_now, "holders_prior": holders_prior,
    }
    return ShadowFeature(name, "ok", float(now_held - prior_held), None, detail)
