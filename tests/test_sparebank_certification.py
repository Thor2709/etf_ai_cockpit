from __future__ import annotations

import hashlib
import json
from pathlib import Path

import flet as ft
import pandas as pd
import pytest

from etf_cockpit.app.pages.instrument_detail import _render_sparebank_workspace
from etf_cockpit.application.instrument_detail_view import _sparebank_workspace
from etf_cockpit.application.ui_facade import _select_ec_revision, load_financial_institution_projection
from etf_cockpit.analysis.sparebank.events import merger_bridge, merger_ratios
from etf_cockpit.data.classification import ClassificationEvidence, resolve_instrument_context
from etf_cockpit.data.contracts import SourceAuthority
from etf_cockpit.data.market_adjustments import CorporateAction, CorporateActionStore
from etf_cockpit.data.score_history import append_score_run, score_history_frame


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "sparebank"


def _teaching_bank() -> dict[str, object]:
    return json.loads((FIXTURES / "teaching_bank.json").read_text(encoding="utf-8"))


def _production_fixture(tmp_path: Path, *, price_rows: list[dict[str, object]] | None):
    instrument_id = "MING"
    rows = [
        {"instrument_id": instrument_id, "canonical_metric": "net_interest_income", "value": 100.0, "unit": "NOK", "end": "2024-12-31", "known_at": "2025-02-15T00:00:00Z", "effective_at": "2024-12-31", "source_id": "fixture:nim"},
        {"instrument_id": instrument_id, "canonical_metric": "operating_expenses", "value": 40.0, "unit": "NOK", "end": "2024-12-31", "known_at": "2025-02-15T00:00:00Z", "effective_at": "2024-12-31", "source_id": "fixture:opex"},
        {"instrument_id": instrument_id, "canonical_metric": "loans_to_customers", "value": 800.0, "unit": "NOK", "end": "2024-12-31", "known_at": "2025-02-15T00:00:00Z", "effective_at": "2024-12-31", "source_id": "fixture:loans"},
        {"instrument_id": instrument_id, "canonical_metric": "deposits_from_customers", "value": 1000.0, "unit": "NOK", "end": "2024-12-31", "known_at": "2025-02-15T00:00:00Z", "effective_at": "2024-12-31", "source_id": "fixture:deposits"},
        {"instrument_id": instrument_id, "canonical_metric": "cet1_ratio", "value": 0.18, "unit": "ratio", "end": "2024-12-31", "known_at": "2025-02-15T00:00:00Z", "effective_at": "2024-12-31", "source_id": "pillar3:cet1", "taxonomy": "pillar3"},
    ]
    pd.DataFrame(rows).to_parquet(tmp_path / "statement_facts.parquet", index=False)
    ec_payload = _teaching_bank() | {"instrument_id": instrument_id}
    ec_payload["sha256"] = hashlib.sha256((FIXTURES / "teaching_bank.json").read_bytes()).hexdigest()
    ec_payload["bank_economics_evidence"] = {
        "reported_earnings": 100.0,
        "average_common_equity": 1000.0,
        "cet1": 150.0,
        "ppp": 0.0,
        "credit_loss": 0.0,
        "rwa": 1000.0,
        "target_ratio": 0.1,
        "funding": {"lcr": 2.0, "nsfr": 1.2},
    }
    ec_payload["valuation_assumptions"] = {
        "central_owner_value_per_ec": 130.0,
        "cost_of_equity": 0.05,
        "marketability": {"days_to_trade": 21.0},
        "currency": "NOK",
    }
    (tmp_path / "ec_facts.json").write_text(json.dumps(ec_payload), encoding="utf-8")
    if price_rows is not None:
        price_path = tmp_path / "data" / "clean" / "prices.parquet"
        price_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(price_rows).to_parquet(price_path, index=False)
    context = resolve_instrument_context(
        tuple(
            ClassificationEvidence(
                evidence_id=f"{instrument_id}:{field}", instrument_id=instrument_id, field=field, value=value,
                source="fixture", authority=SourceAuthority.OFFICIAL, source_id=f"fixture:{field}", confidence=0.99,
                valid_from="2020-01-01T00:00:00Z", available_at="2020-01-02T00:00:00Z",
            )
            for field, value in {
                "instrument_type": "equity_certificate", "asset_class": "equity", "sector": "financials",
                "operating_country": "NO", "issuer_type": "savings_bank", "business_model_tag": "bank",
            }.items()
        ),
        instrument_id=instrument_id, effective_at="2024-12-31T00:00:00Z", decision_time="2025-03-01T00:00:00Z",
    )
    return instrument_id, context


def _manifest() -> dict[str, object]:
    content = (ROOT / "docs/architecture/sparebank-book-manifest.md").read_text(encoding="utf-8")
    return json.loads(content.split("```json\n", 1)[1].split("\n```", 1)[0])


def _text_values(control: object) -> list[str]:
    result: list[str] = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        result.append(value)
    for name in ("controls", "content", "title", "subtitle"):
        child = getattr(control, name, None)
        if isinstance(child, (list, tuple)):
            for item in child:
                result.extend(_text_values(item))
        elif child is not None and child is not control:
            result.extend(_text_values(child))
    return result


def test_manifest_requirements_have_existing_file_function_and_test_locators() -> None:
    manifest = _manifest()
    equations = manifest["equations"]
    expected = [
        f"BOOK-EQ-{chapter}.{equation}"
        for chapter, maximum in ((1, 7), (2, 4), (3, 5), (4, 3), (5, 10), (6, 4), (7, 5), (8, 3))
        for equation in range(1, maximum + 1)
    ]
    assert [row["id"] for row in equations] == expected
    assert len({row["id"] for row in equations}) == 41
    assert {item["table_reference"] for item in manifest["analytical_tables"]} == {
        "table 2.1", "table 2.2", "table 3.2", "table 4.1", "table 4.2", "table 5.2",
        "table 6.1", "table 6.2", "table 7.1", "table 7.2", "table 8.2", "table 9.2",
    }

    rows = [*equations, *manifest["requirements"], *manifest["analytical_tables"]]
    for row in rows:
        if row["disposition"] == "BACKGROUND_ONLY":
            assert row.get("reason")
            continue
        implementation = row.get("implementation_locator")
        if row.get("status") == "unimplemented":
            assert row.get("reason")
            assert implementation is None
        else:
            assert implementation
            source_path, symbol = implementation.split("::", 1)
            source = ROOT / source_path
            assert source.is_file(), row["id"]
            assert symbol in source.read_text(encoding="utf-8"), row["id"]
        test_locator = row.get("test_locator")
        assert test_locator, row["id"]
        test_path, test_name = test_locator.split("::", 1)
        test_file = ROOT / test_path
        assert test_file.is_file(), row["id"]
        assert test_name in test_file.read_text(encoding="utf-8"), row["id"]


def test_teaching_bank_production_route_exposes_scorecard_and_workspace(tmp_path: Path) -> None:
    instrument_id, context = _production_fixture(
        tmp_path,
        price_rows=[
            {"instrument_id": "MING", "date": "2025-02-27", "close": 98.0, "currency": "NOK"},
            {"instrument_id": "MING", "date": "2025-02-28", "close": 100.0, "currency": "NOK"},
            {"instrument_id": "MING", "date": "2025-03-02", "close": 110.0, "currency": "NOK"},
        ],
    )
    append_score_run(
        pd.DataFrame(
            [
                {
                    "instrument_id": "GENERIC",
                    "final_combined_score_10": 4.25,
                    "formula_version": "generic-formula-v1",
                    "formula_checksum": "generic-formula-checksum",
                    "source_vintage_hash": "generic-source-vintage",
                }
            ]
        ),
        "generic-existing-run",
        "2025-02-28T00:00:00Z",
        root=tmp_path,
    )
    projection = load_financial_institution_projection(
        instrument_id,
        storage_root=tmp_path,
        decision_time="2025-03-01T00:00:00Z",
        context=context,
        tactical_evidence={"status": "available", "components": ({"key": "momentum", "raw_metric": 0.8},)},
    )
    identity = projection["share_class_identity"]
    assert identity["native_suite"] == "sparebank-analysis-suite.v1"
    analysis = identity["sparebank_analysis"]
    assert analysis["scorecard"]["formula_version"] == "sparebank-scorecard-v1.0.0"
    assert analysis["scorecard"]["composite_10"] is not None
    assert analysis["decision_price"] == {
        "status": "available", "price": 100.0, "date": "2025-02-28", "currency": "NOK",
        "valuation_currency": "NOK", "execution_allowed": False,
    }
    assert analysis["history_status"] == {"status": "written", "reason": None}
    history = score_history_frame(root=tmp_path)
    sparebank_history = history.loc[history["instrument_id"].eq(instrument_id)]
    assert len(sparebank_history) == 1
    score_row = sparebank_history.iloc[0]
    assert score_row["formula_version"] == analysis["scorecard"]["formula_version"]
    assert score_row["formula_checksum"] == analysis["scorecard"]["formula_checksum"]
    assert score_row["source_vintage_hash"] == hashlib.sha256((FIXTURES / "teaching_bank.json").read_bytes()).hexdigest()
    assert str(score_row["price_as_of_date"]) == "2025-02-28"
    generic_history = history.loc[history["instrument_id"].eq("GENERIC")]
    assert len(generic_history) == 1
    assert generic_history.iloc[0]["final_combined_score_10"] == 4.25
    assert generic_history.iloc[0]["formula_version"] == "generic-formula-v1"
    assert generic_history.iloc[0]["formula_checksum"] == "generic-formula-checksum"
    assert generic_history.iloc[0]["source_vintage_hash"] == "generic-source-vintage"
    workspace = _sparebank_workspace(projection)
    assert workspace["status"] == "available"
    assert workspace["ownership_passport"]["claim_status"] == "resolved"
    assert workspace["underwriting_horizon"]["label"] == "Underwriting"
    assert workspace["tactical_horizon"]["label"] == "Tactical"

    rendered = _render_sparebank_workspace(workspace)
    assert isinstance(rendered, ft.ExpansionTile)
    text = "\n".join(_text_values(rendered))
    assert "Sparebank EC workspace" in text
    assert "Underwriting horizon" in text
    assert "Tactical horizon" in text
    assert "What this EC owns" in text
    assert "Bank economics" in text
    assert "Structural transition" in text


@pytest.mark.parametrize(
    ("price_rows", "expected_reason"),
    [
        ([{"instrument_id": "MING", "date": "2025-03-02", "close": 100.0, "currency": "NOK"}], "decision_price_unavailable_as_of_decision"),
        (None, "decision_price_store_missing"),
        ([{"instrument_id": "MING", "date": "2025-02-28", "close": 100.0, "currency": "USD"}], "decision_price_currency_mismatch"),
    ],
)
def test_sparebank_score_history_requires_price_at_decision_time(
    tmp_path: Path,
    price_rows: list[dict[str, object]] | None,
    expected_reason: str,
) -> None:
    instrument_id, context = _production_fixture(tmp_path, price_rows=price_rows)
    projection = load_financial_institution_projection(
        instrument_id,
        storage_root=tmp_path,
        decision_time="2025-03-01T00:00:00Z",
        context=context,
    )
    analysis = projection["share_class_identity"]["sparebank_analysis"]
    assert analysis["scorecard"]["composite_10"] is None
    assert analysis["history_status"] == {"status": "not_written", "reason": expected_reason}
    assert score_history_frame(root=tmp_path).empty


def test_point_in_time_selection_ignores_later_filing_facts() -> None:
    facts = _teaching_bank()["facts"]
    changed_facts = dict(facts)
    changed_facts["ec_capital"] = {"available": True, "value": 900.0}
    payload = {
        "revisions": [
            {"instrument_id": "TEACHING-EC", "known_at": "2023-10-25T00:00:00Z", "effective_at": "2023-09-30", "facts": facts},
            {"instrument_id": "TEACHING-EC", "known_at": "2023-10-30T00:00:00Z", "effective_at": "2023-09-30", "facts": changed_facts, "publication_boundary": "Q3 report after 2023-10-26 merger announcement"},
        ]
    }
    selected = _select_ec_revision(payload, "TEACHING-EC", "2023-10-26T00:00:00Z")
    assert selected["known_at"] == "2023-10-25T00:00:00Z"
    assert selected["facts"]["ec_capital"]["value"] == facts["ec_capital"]["value"]
    assert selected["facts"]["ec_capital"]["value"] != changed_facts["ec_capital"]["value"]


def test_successor_ec_and_cash_preserve_merged_instrument_history(tmp_path: Path) -> None:
    action = CorporateAction(
        action_id="TOTG-SPOL",
        instrument_id="TOTG",
        action_type="merger",
        announced_at="2024-10-01T00:00:00Z",
        effective_at="2024-11-01T00:00:00Z",
        ex_date="2024-11-01",
        payable_at="2024-11-01T00:00:00Z",
        known_at="2024-10-01T00:00:00Z",
        revision=1,
        source="fixture:SPBK-799",
        source_id="fixture:SPBK-799:Totens-to-SPOL",
        source_checksum="sha256:SPBK-799-Totens-to-SPOL",
        ratio=1.80,
        amount=7.788,
        currency="NOK",
        terms={"successor_instrument_id": "SPOL", "successor_ec_per_legacy_ec": 1.80, "cash_per_legacy_ec": 7.788},
    )
    with CorporateActionStore(tmp_path / "corporate-actions") as store:
        store.append(action)
        history = store.query("TOTG")
        successor_history = store.query("SPOL")
        historical_analysis = store.replay(
            "TOTG",
            effective_at="2024-11-02T00:00:00Z",
            known_at="2024-11-02T00:00:00Z",
        )
    assert len(history) == 1
    assert history[0].terms["successor_instrument_id"] == "SPOL"
    assert history[0].ratio == pytest.approx(1.80)
    assert history[0].amount == pytest.approx(7.788)
    assert successor_history == ()
    assert history[0].execution_allowed is False
    assert len(historical_analysis) == 1
    assert historical_analysis[0].instrument_id == "TOTG"

    ratios = merger_ratios(target_ec_exchange_ratio=history[0].terms["successor_ec_per_legacy_ec"])
    value_bridge = merger_bridge(100.0, per_ec_increment=0.0)
    successor_price = 51.22888888888889
    successor_value = (
        ratios["target_ec_exchange_ratio"] * successor_price
        + history[0].terms["cash_per_legacy_ec"]
    )
    assert value_bridge["status"] == "resolved"
    assert successor_value == pytest.approx(value_bridge["value_per_legacy_ec"])


def test_roe_decomposition_uses_consistent_averages() -> None:
    from etf_cockpit.analysis.sparebank.bank_economics import roe_decomposition

    result = roe_decomposition(net_income=99.0, average_assets=1000.0, average_common_equity=1000.0)
    assert result["roe"] == pytest.approx(result["roa"] * result["leverage"])
