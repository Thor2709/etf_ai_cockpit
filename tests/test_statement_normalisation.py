from __future__ import annotations

import json
import inspect
from pathlib import Path

from etf_cockpit.data.instrument_identity import CanonicalIdentity
from etf_cockpit.data.statement_normalisation import (
    load_statement_evidence,
    normalise_statement_facts,
    reconcile_statement_identities,
    statement_coverage,
    statement_view,
)
from etf_cockpit.parsers.sec_facts import StatementFact, parse_companyfacts


def _fact(
    metric: str,
    value: float,
    *,
    start: str | None = "2024-01-01",
    end: str = "2024-12-31",
    filed: str = "2025-01-20",
    form: str = "10-K",
    fiscal_period: str = "FY",
    source_id: str | None = None,
) -> StatementFact:
    return StatementFact(
        instrument_id="MSFT",
        cik="789019",
        taxonomy="us-gaap",
        concept=metric.title(),
        unit="USD",
        value=value,
        start=start,
        end=end,
        instant=None if start else end,
        filed=filed,
        form=form,
        accession=source_id or f"{metric}-{filed}",
        fiscal_year=2024,
        fiscal_period=fiscal_period,
        source_id=f"sec_edgar:{source_id or metric + filed}",
        canonical_metric=metric,
        mapping_status="mapped",
        is_custom=False,
        currency="USD",
        period_type="duration" if start else "instant",
        mapping_confidence="high",
        manual_review_required=False,
        restatement_kind="amended" if form.endswith("/A") else "reported",
        available_at=filed,
    )


def test_views_keep_reported_facts_and_select_restated_or_as_known_without_leakage() -> None:
    older = _fact("revenue", 100, source_id="older")
    amended = _fact("revenue", 90, filed="2025-03-01", form="10-K/A", source_id="amended")
    reported = statement_view((older, amended), "reported")
    latest = statement_view((older, amended), "latest_restated")
    as_known = statement_view((older, amended), "as_known_at", as_known_at="2025-02-01")

    assert len(reported) == 2
    assert latest.iloc[0]["value"] == 90
    assert latest.iloc[0]["restatement_kind"] == "amended"
    assert as_known.iloc[0]["value"] == 100
    assert "amended" not in set(as_known["restatement_kind"])


def test_coverage_and_identities_report_missing_and_failed_evidence_explicitly() -> None:
    records = [
        _fact("assets", 100),
        _fact("liabilities", 40),
        _fact("equity", 60),
        _fact("revenue", 10),
    ]
    frame = normalise_statement_facts(records)
    coverage = statement_coverage(frame)
    reconciliation = reconcile_statement_identities(frame)

    assert coverage["annual_periods"] == 1
    assert coverage["annual_target_met"] is False
    assert reconciliation["status"] == "passed"
    assert reconciliation["checked"] == 1

    failed = normalise_statement_facts([_fact("assets", 100), _fact("liabilities", 40), _fact("equity", 55)])
    assert reconcile_statement_identities(failed)["status"] == "failed"
    assert reconcile_statement_identities(normalise_statement_facts([_fact("revenue", 10)]))["status"] == "unavailable"


def test_reconciliation_checks_cash_flow_components_with_optional_fx() -> None:
    records = [
        _fact("cash_from_operations", 25),
        _fact("cash_from_investing", -10),
        _fact("cash_from_financing", -5),
        _fact("cash_from_fx", 1),
        _fact("cash_net_change", 11),
    ]

    result = reconcile_statement_identities(normalise_statement_facts(records))

    assert result["status"] == "passed"
    assert result["checked"] == 1


def test_statement_evidence_loads_history_coverage_and_reconciliation(tmp_path: Path) -> None:
    frame = normalise_statement_facts([_fact("revenue", 10), _fact("assets", 100, start=None, fiscal_period="Q1", end="2024-03-31")])
    path = tmp_path / "statement_facts.parquet"
    frame.to_parquet(path, index=False)

    evidence = load_statement_evidence(path, instrument_id="MSFT", as_known_at="2025-12-31")

    assert evidence["status"] == "available"
    assert {row["view"] for row in evidence["statement_history"]} == {"reported", "latest_restated", "as_known_at"}
    assert evidence["coverage"]["as_known_at"] == "2025-12-31"
    assert evidence["execution_allowed"] is False


def test_missing_statement_evidence_reports_an_explicit_unavailable_status(tmp_path: Path) -> None:
    evidence = load_statement_evidence(tmp_path / "missing.parquet", instrument_id="MSFT")

    assert evidence["status"] == "unavailable"
    assert evidence["statement_history"] == []
    assert evidence["coverage"]["total_facts"] == 0
    assert evidence["reconciliation"]["status"] == "unavailable"
    assert evidence["execution_allowed"] is False


def test_sec_parser_retains_unit_dimension_and_mapping_review_metadata(tmp_path: Path) -> None:
    payload = {
        "cik": 789019,
        "facts": {
            "us-gaap": {
                "Revenue": {
                    "units": {
                        "USD": [
                            {
                                "val": 10,
                                "start": "2024-01-01",
                                "end": "2024-03-31",
                                "filed": "2025-01-20",
                                "form": "10-Q/A",
                                "accn": "amended",
                                "fp": "Q1",
                                "dim": {"segment": "cloud"},
                            }
                        ]
                    }
                },
                "UnsupportedConcept": {"units": {"USD": [{"val": 1, "end": "2024-03-31", "filed": "2025-01-20"}]}},
            }
        },
    }
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    identity = CanonicalIdentity("MSFT", "Microsoft", None, "needs_verification", "MSFT", "NASDAQ", "USD", "stock", {}, "high", (), "789019")

    result = parse_companyfacts(path, identity)
    revenue = next(record for record in result.records if record.canonical_metric == "revenue")
    unsupported = next(record for record in result.records if record.concept == "UnsupportedConcept")

    assert revenue.currency == "USD"
    assert revenue.period_type == "duration"
    assert revenue.dimensions == '{"segment":"cloud"}'
    assert revenue.restatement_kind == "amended"
    assert revenue.available_at == "2025-01-20"
    assert revenue.manual_review_required is False
    assert unsupported.manual_review_required is True


def test_fundamentals_surface_exposes_reported_and_restated_statement_history() -> None:
    from etf_cockpit.app.pages.instrument_detail import _render_evidence_section
    from etf_cockpit.app.selectors.instrument_detail import _fundamentals_panel

    assert "statement_history" in inspect.getsource(_fundamentals_panel)
    assert "statement_history" in inspect.getsource(_render_evidence_section)
