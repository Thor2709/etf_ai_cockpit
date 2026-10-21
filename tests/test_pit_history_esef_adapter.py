"""HDP2: ESEF -> stock_fundamentals source, per-date certificate rescore hook, GLEIF ISIN verification."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data import stock_fundamentals as store
from etf_cockpit.data import stock_sources as src

CONFIG = {
    "esef_concepts": {
        "revenue": ["Revenue", "RevenueFromContractsWithCustomers"],
        "gross_profit": ["GrossProfit"],
        "net_income_parent": ["ProfitLossAttributableToOwnersOfParent"],
        "capex": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
        "equity_parent": ["EquityAttributableToOwnersOfParent"],
        "minority_interest": ["NoncontrollingInterests", "Equity[NoncontrollingInterestsMember]"],
        "shares_outstanding": ["NumberOfSharesOutstanding"],
    },
    "esef_rules": {"share_count_agreement": 0.01, "absolute_value_fields": ["capex"]},
}


def _fact(concept: str, value: float, known_at: str, *, start: str | None = "2023-01-01", end: str = "2023-12-31", unit: str = "EUR", dimensions: str = "") -> dict:
    instant = end if start is None else None
    return {
        "instrument_id": "XX", "taxonomy": "ifrs-full", "concept": concept, "unit": unit, "value": value, "start": start, "end": end,
        "instant": instant, "known_at": known_at, "dimensions": dimensions, "consolidation_scope": "consolidated",
    }


FIRST = "2024-03-01T00:00:00.000000+00:00"
LATER = "2025-03-01T00:00:00.000000+00:00"


def _facts() -> pd.DataFrame:
    rows = [
        _fact("Revenue", 100.0, FIRST),
        _fact("Revenue", 110.0, LATER),  # the next report restates the comparative: it must not replace what was known
        _fact("ProfitLossAttributableToOwnersOfParent", 10.0, FIRST),
        _fact("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", -7.0, FIRST),
        _fact("EquityAttributableToOwnersOfParent", 50.0, FIRST, start=None),
        _fact("Equity", 5.0, FIRST, start=None, dimensions=json.dumps({"ifrs-full:ComponentsOfEquityAxis": "ifrs-full:NoncontrollingInterestsMember"})),
        _fact("Revenue", 999.0, FIRST, dimensions=json.dumps({"ifrs-full:SegmentsAxis": "x:SegmentMember"})),  # a segment, not the group
    ]
    return pd.DataFrame(rows)


def test_esef_rows_are_as_originally_reported_without_zero_fill() -> None:
    rows = src.parse_esef_statement_facts(_facts(), CONFIG, source_ref="esef:test")

    assert len(rows) == 1
    row = rows[0]
    assert (row["source"], row["period_type"], row["period_end"], row["reporting_standard"]) == ("esef", "FY", "2023-12-31", "ifrs")
    assert row["revenue"] == 100.0 and row["known_at"] == FIRST  # the earliest filing wins; the restated comparative is ignored
    assert row["capex"] == 7.0  # a payment is stored as the positive outflow
    assert row["equity_parent"] == 50.0 and row["minority_interest"] == 5.0  # NCI from the equity-axis member
    assert "gross_profit" not in row and "shares_outstanding" not in row  # untagged is absent, never 0
    assert json.loads(row["value_status"])["net_income_parent"] == "observed"


def test_conflicting_share_counts_are_conflicted_not_picked() -> None:
    facts = pd.concat([_facts(), pd.DataFrame([
        _fact("NumberOfSharesOutstanding", 567069000.0, FIRST, start=None, unit="shares"),
        _fact("NumberOfSharesOutstanding", 567069.0, LATER, start=None, unit="shares"),  # a later filing reports in thousands
    ])], ignore_index=True)

    row = src.parse_esef_statement_facts(facts, CONFIG, source_ref="esef:test")[0]

    assert "shares_outstanding" not in row
    assert json.loads(row["value_status"])["shares_outstanding"] == "conflicted"


def test_positive_nci_keeps_only_explicitly_parent_attributed_income() -> None:
    def merged(source: str, status: str) -> store.Period:
        frame = pd.DataFrame([{
            "instrument_id": "T", "period_end": "2023-12-31", "period_type": "FY", "source": source, "currency": "EUR",
            "known_at": FIRST, "net_income_parent": 10.0, "minority_interest": 5.0, "revenue": 100.0, "value_status": status,
        }])
        return store.periods_for("T", frame, ["sec_edgar", "esef", "yfinance"])[-1]

    assert merged("esef", json.dumps({"net_income_parent": "observed"})).values["net_income_parent"] == 10.0
    assert "net_income_parent" not in merged("sec_edgar", "").values  # an unverified attribution is still dropped


def test_refresh_reads_the_esef_source_without_network_and_skips_issuers_without_facts(tmp_path: Path) -> None:
    calls: list[str] = []

    def esef_fetch(instrument_id: str, config: dict) -> src.FetchResult:
        calls.append(instrument_id)
        if instrument_id == "NOFACTS":
            return src.FetchResult("esef", status="unavailable", reason="none imported")
        return src.fetch_esef(instrument_id, config, facts=_facts().assign(instrument_id=instrument_id))

    def forbidden(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("a network source was called")

    targets = [store.StockTarget("XX", "X", "XX.PA"), store.StockTarget("NOFACTS", "N", "NF.PA")]
    config = {**CONFIG, "sources": {"chain": ["esef"]}}
    report = store.refresh_stock_fundamentals(
        targets, root=tmp_path, now=datetime(2026, 10, 21, tzinfo=timezone.utc), config=config, environ={},
        yfinance_fetch=forbidden, edgar_fetch=forbidden, esef_fetch=esef_fetch, fx_fetch=forbidden,
    )

    stored = store.read_fundamentals(tmp_path)
    assert calls == ["XX", "NOFACTS"] and report.rows_added == 1
    assert set(stored["source"]) == {"esef"} and set(stored["instrument_id"]) == {"XX"}
    assert report.per_instrument["NOFACTS"] == "ok"  # an issuer without imported ESEF facts is not a reported gap


def test_rescore_hook_uses_the_decision_instant_and_leaves_the_live_summary_alone(tmp_path: Path) -> None:
    from scripts import sparebank_refresh as sr

    seen: list[str] = []
    record = type("R", (), {"instrument_id": "MING", "name": "Ming", "lei": "L", "ticker": "MING", "isin": "", "enabled": True})()

    def rescorer(rec, data_root, universe_root, decision_time):  # noqa: ANN001
        seen.append(decision_time)
        return 7.5, 0.4, "partial"

    original = sr.load_sparebank_records
    sr.load_sparebank_records = lambda root: (record,)
    try:
        rows = sr.rescore_sparebanks_at(tmp_path, date(2024, 6, 28), rescorer=rescorer)
    finally:
        sr.load_sparebank_records = original

    assert seen == ["2024-06-28T23:59:59+00:00"]  # end of the UTC decision day
    assert rows[0]["composite"] == 7.5 and rows[0]["reason"] == ""
    assert not (tmp_path / "evidence" / "norway").exists()  # no summary file, no certificate directory created
    with pytest.raises(ValueError):
        sr.decision_instant(datetime(2024, 6, 28, 12, 0))  # a naive datetime is not a decision time


def test_isin_is_verified_only_when_both_gleif_directions_agree() -> None:
    from scripts import pit_verify_isins as verify

    lei = "635400DPX6WP2KKDOA83"
    record = {"id": lei, "attributes": {"entity": {"legalName": {"name": "Cairn Homes Public Limited Company"}}, "registration": {"status": "ISSUED"}}}

    def fake(isins: list[str]):
        def get(url: str):  # noqa: ANN202
            if "filter%5Bisin%5D" in url:
                return {"data": [record]}
            return {"data": [{"attributes": {"isin": item}} for item in isins], "links": {}}
        return get

    kwargs = {"sleep": lambda _s: None, "now": lambda: datetime(2026, 10, 21, tzinfo=timezone.utc)}
    ok = verify.verify_candidate("CBUK", "Cairn Homes plc", "IE00BWY4ZF18", get=fake(["IE00BWY4ZF18"]), **kwargs)
    assert ok["verified"] is True and ok["lei"] == lei and ok["checked_at"].startswith("2026-10-21")

    not_listed = verify.verify_candidate("CBUK", "Cairn Homes plc", "IE00BWY4ZF18", get=fake(["IE0000000000"]), **kwargs)
    assert not_listed["verified"] is False and not_listed["reason"] == "forward_lookup_does_not_list_the_isin"

    wrong_name = verify.verify_candidate("CBUK", "Some Other Company", "IE00BWY4ZF18", get=fake(["IE00BWY4ZF18"]), **kwargs)
    assert wrong_name["verified"] is False and "name" in str(wrong_name["reason"])

    no_isin = verify.verify_candidate("KMAR", "Kempower Oyj", "", get=lambda url: {"data": []}, **kwargs)
    assert no_isin["verified"] is False and no_isin["reason"].startswith("no_candidate_isin")


def test_replay_dates_inside_the_live_grace_window_are_flagged() -> None:
    from scripts import pit_history_check as check

    days = [date(2026, 9, 28), date(2026, 10, 5)]
    assert check.check_decision_window(days, datetime(2026, 10, 21, tzinfo=timezone.utc))["violations"] == []
    # a run whose "now" is the data end would see the last date as live: its decision time would be now, not the day's end
    flagged = check.check_decision_window(days, datetime(2026, 10, 9, 12, tzinfo=timezone.utc))["violations"]
    assert len(flagged) == 1 and "2026-10-05" in flagged[0]


def test_isin_overrides_fill_only_unverified_isins_and_must_match_the_gleif_lei() -> None:
    from scripts import pit_history_backfill as backfill

    records = {
        "CBUK": {"isin": "NEEDS_VERIFICATION"},
        "HO": {"isin": "FR0000121329"},  # a valid store ISIN is never replaced
    }
    overrides = {
        "CBUK": {"isin": "IE00BWY4ZF18", "lei": "635400DPX6WP2KKDOA83", "verified_at": "2026-10-21T19:26:48+00:00"},
        "HO": {"isin": "DE0006070006", "lei": "529900Y25S8NZIYTT924", "verified_at": "x"},
    }
    merged = backfill.apply_isin_overrides(records, overrides)
    assert merged["CBUK"]["isin"] == "IE00BWY4ZF18" and merged["HO"]["isin"] == "FR0000121329"

    leis = {"CBUK": {"lei": "635400DPX6WP2KKDOA83", "source": "GLEIF"}}
    backfill.check_override_leis(leis, overrides, merged)
    assert "override verified 2026-10-21" in leis["CBUK"]["source"]
    leis = {"CBUK": {"lei": "5493000000000000000X", "source": "GLEIF"}}
    backfill.check_override_leis(leis, overrides, merged)
    assert leis["CBUK"]["lei"] == "" and "differs" in leis["CBUK"]["reason"]
