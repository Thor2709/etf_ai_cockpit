from __future__ import annotations

import builtins
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from etf_cockpit.data import sec_filing_documents as sfd
from etf_cockpit.data import sec_ownership as so
from etf_cockpit.data.sec_edgar_provider import SecEdgarProvider
from etf_cockpit.plugins.registry import _network_probe

FIXTURES = Path(__file__).parent / "fixtures"
ACCEPTED = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=timezone.utc)


def test_form4_counts_only_open_market_unplanned_buys_known_by_decision_time() -> None:
    pytest.importorskip("edgar")
    so._edgar()  # first import happens outside the socket probe
    xml = (FIXTURES / "sec_ownership" / "form4_mixed.xml").read_bytes()
    with _network_probe() as calls:
        filing = so.parse_ownership_xml(xml, accession="0000777001-26-000001", known_at=ACCEPTED)
    assert calls == []

    reasons = [(t.code, t.is_derivative, t.exclusion_reason) for t in filing.transactions]
    assert reasons == [
        ("P", False, None), ("A", False, "code_A"), ("S", False, "rule_10b5_1_plan"),
        ("P", False, None), ("P", True, "derivative_row"),
    ]
    assert filing.insider_ciks == ("0000777001",)

    names = ("insider_net_open_market_shares", "insider_cluster_buyers")
    late = so.insider_purchase_features([filing], issuer_cik="12345", decision_time=_utc(2026, 8, 13, 11))
    assert {late[n].status for n in names} == {"unavailable"}  # accepted after the decision time
    seen = so.insider_purchase_features([filing], issuer_cik="12345", decision_time=_utc(2026, 8, 14))
    assert seen[names[0]].value == 1300.0  # the 7000-share grant and the derivative buy are not purchases
    assert seen[names[0]].detail["net_value_usd"] == pytest.approx(1000 * 10.5 + 300 * 10.6)
    assert seen[names[1]].value == 1.0 and seen[names[1]].detail["is_cluster"] is False

    stale = so.insider_purchase_features([replace(filing, known_at=_utc(2025, 1, 1))], issuer_cik="12345", decision_time=_utc(2026, 8, 14))
    assert {stale[n].status for n in names} == {"unavailable"}  # no filing inside the window: not an ok zero
    unsized = replace(filing, transactions=(replace(filing.transactions[0], shares=None), *filing.transactions[1:]))
    gap = so.insider_purchase_features([unsized], issuer_cik="12345", decision_time=_utc(2026, 8, 14))
    assert {gap[n].status for n in names} == {"unavailable"}  # a purchase without shares cannot be netted

    swap = so.parse_ownership_xml(
        xml.replace(b"<transactionCode>P</transactionCode><equitySwapInvolved>0", b"<transactionCode>P</transactionCode><equitySwapInvolved>1", 1),
        accession="a", known_at=ACCEPTED,
    )
    assert swap.transactions[0].exclusion_reason == "equity_swap" and swap.transactions[3].exclusion_reason is None
    remark = so.parse_ownership_xml(
        xml.replace(b"<ownerSignature>", b"<remarks>All sales were made under a Rule 10b5-1 trading plan.</remarks><ownerSignature>"),
        accession="b", known_at=ACCEPTED,
    )
    assert [t.exclusion_reason for t in remark.transactions if t.code in ("P", "S")] == ["rule_10b5_1_plan"] * 3 + ["derivative_row"]


def test_13f_amendment_replaces_only_from_its_own_acceptance_and_is_never_current_exposure() -> None:
    pytest.importorskip("edgar")
    so._edgar()
    directory = FIXTURES / "sec_13f"
    kwargs = {"manager_cik": "900001"}

    def load(primary: str, info: str, accession: str, form: str, known_at: datetime) -> so.Filing13F:
        return so.parse_13f(
            (directory / primary).read_bytes(), (directory / info).read_bytes(),
            accession=accession, form=form, known_at=known_at, **kwargs,
        )

    with _network_probe() as calls:
        original = load("primary_original.xml", "info_original.xml", "0000900001-26-000001", "13F-HR", _utc(2026, 8, 1, 20))
        restated = load("primary_restatement.xml", "info_restatement.xml", "0000900001-26-000002", "13F-HR/A", _utc(2026, 9, 10, 20))
        added = load("primary_new_holdings.xml", "info_new_holdings.xml", "0000900001-26-000003", "13F-HR/A", _utc(2026, 10, 1, 20))
    assert calls == []
    assert original.period_end == date(2026, 6, 30) and original.holdings[0].shares == 1000
    assert (restated.amendment_type, added.amendment_type) == ("RESTATEMENT", "NEW HOLDINGS")
    assert added.incomplete_reasons == ("partial_new_holdings_only",)

    prior = replace(original, accession="0000900001-26-000000", period_end=date(2026, 3, 31), holdings=(replace(original.holdings[0], shares=600),))
    chain = [original, restated, added, prior]

    def view(when: datetime) -> so.ThirteenFView:
        return so.thirteenf_view(chain, manager_cik="900001", period_end=date(2026, 6, 30), decision_time=when)

    assert view(_utc(2026, 7, 1)).status == "unavailable"
    assert [view(_utc(2026, 9, 10, 19, 59)).holdings[0].shares, view(_utc(2026, 9, 10, 20)).holdings[0].shares] == [1000, 1500]
    final = view(_utc(2026, 10, 2))
    assert final.accessions == (restated.accession, added.accession) and final.superseded == (original.accession,)
    assert len(final.holdings) == 2 and final.known_at == added.known_at and not final.incomplete_reasons
    assert final.label == so.POSITIONS_LABEL and "not current exposure" in final.label

    def change(when: datetime) -> so.ShadowFeature:
        return so.holder_share_change(chain, cusip="123456109", period_end=date(2026, 6, 30), prior_period_end=date(2026, 3, 31), decision_time=when)

    assert change(_utc(2026, 9, 1)).value == 400.0 and change(_utc(2026, 9, 11)).value == 900.0
    assert change(_utc(2026, 7, 1)).status == "unavailable"
    chain.append(replace(original, accession="0000900002-26-000001", manager_cik="0000900002", known_at=_utc(2026, 12, 1)))
    assert change(_utc(2026, 9, 11)).detail["skipped_managers"] == 0  # a manager first disclosed later is not skipped

    primary = (directory / "primary_original.xml").read_bytes()
    info = (directory / "info_original.xml").read_bytes()
    bad = {
        "count": (primary.replace(b"<tableEntryTotal>1<", b"<tableEntryTotal>2<"), info),
        "empty": (primary, info[: info.index(b"<infoTable>")] + b"</informationTable>"),
        "quantity": (primary, info.replace(b"<sshPrnamt>1000</sshPrnamt>", b"<sshPrnamt></sshPrnamt>")),
    }
    for case, (p, i) in bad.items():
        with pytest.raises(so.SecOwnershipUnavailable, match="information table"):
            so.parse_13f(p, i, accession="x", form="13F-HR", known_at=_utc(2026, 8, 1), **kwargs)


@pytest.mark.parametrize("parse", [
    lambda known_at: so.parse_ownership_xml(b"<ownershipDocument/>", accession="a", known_at=known_at),
    lambda known_at: so.parse_13f(b"", None, accession="a", form="13F-HR", manager_cik="1", known_at=known_at),
    lambda known_at: sfd.parse_8k(b"", known_at=known_at),
], ids=["form4", "13f", "8k"])
def test_missing_edgartools_and_naive_times_are_explicit_unavailable(parse, monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def without_edgar(name: str, *args: object, **kwargs: object):
        if name == "edgar" or name.startswith("edgar."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", without_edgar)
        with pytest.raises(so.SecOwnershipUnavailable, match="optional `sec` extra"):
            parse(ACCEPTED)
    with pytest.raises(so.SecOwnershipUnavailable, match="timezone-aware"):
        parse(datetime(2026, 1, 1))


def test_filing_documents_are_bounded_fetches(tmp_path: Path) -> None:
    payload = (FIXTURES / "sec_ownership" / "form4_mixed.xml").read_bytes()
    provider = SecEdgarProvider(
        "ETF AI Cockpit tests research@company.org", cache_dir=tmp_path, rate_limit_seconds=0,
        transport=lambda url, _headers: payload if url.endswith("form4.xml") else b"blocked",
    )
    url = "https://www.sec.gov/Archives/edgar/data/777001/000077700126000001/form4.xml"
    document = provider.fetch_filing_document(url)
    assert document.path.read_bytes() == payload and document.document_type == "sec_filing_document"
    assert document.sha256 == so.hashlib.sha256(payload).hexdigest()
    for bad in ("https://data.sec.gov/submissions/CIK0000777001.json", url.replace("form4", "../form4"), url.replace("form4.xml", "other.xml")):
        with pytest.raises(ValueError):
            provider.fetch_filing_document(bad)
