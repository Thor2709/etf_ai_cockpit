from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import numpy as np
import pandas as pd
import pytest

from etf_cockpit.data.fund_holdings import normalise_holdings, write_holdings_records
from etf_cockpit.data.fund_documents import DOCUMENT_TYPES
from etf_cockpit.app.pages import risk as risk_page_module


def test_full_holdings_are_normalised_and_partial_data_is_explicit() -> None:
    full = normalise_holdings(pd.DataFrame({"security": ["A", "B"], "weight": [0.6, 0.4]}), "VWCE", "2026-07-10", "issuer")
    partial = normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [0.4]}), "VWCE", "2026-07-10", "vendor")
    invalid = normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [-1.0]}), "VWCE", "2026-07-10", "issuer")
    assert full.completeness == "full"
    assert partial.completeness == "partial"
    assert invalid.completeness == "invalid"
    assert full.frame.iloc[0]["instrument_id"] == "VWCE"


@pytest.mark.parametrize("total", [0.99, 1.01])
def test_full_holdings_accept_boundary_tolerance(total: float) -> None:
    result = normalise_holdings(pd.DataFrame({"security": ["A", "B"], "ticker": ["A", "B"], "weight": [total - 0.4, 0.4]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "full"
    assert result.score_eligible is True
    assert result.authority == "issuer"


def test_vendor_top_holdings_remain_partial_even_when_weights_sum_to_one() -> None:
    result = normalise_holdings(pd.DataFrame({"security": ["A", "B"], "weight": [0.6, 0.4]}), "VWCE", "2026-07-10", "yfinance", today="2026-07-11")
    assert result.completeness == "partial"
    assert result.authority == "vendor"
    assert result.score_eligible is False


def test_stale_holdings_are_explicit_and_capped_for_current_exposure() -> None:
    result = normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [1.0]}), "VWCE", "2025-01-01", "issuer", today="2026-07-11")
    assert result.completeness == "full"
    assert result.freshness == "stale"
    assert result.confidence <= 0.25
    assert result.score_eligible is False


@pytest.mark.parametrize("bad_weight", [True, np.bool_(True), float("nan"), float("inf"), 60.0])
def test_canonical_decimal_weights_reject_boolean_non_finite_and_implicit_percentages(bad_weight: object) -> None:
    frame = pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": pd.Series([bad_weight], dtype=object)})
    result = normalise_holdings(frame, "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "invalid"
    assert result.score_eligible is False


def test_source_authority_requires_an_exact_allowlisted_label() -> None:
    result = normalise_holdings(
        pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}),
        "VWCE",
        "2026-07-10",
        "issuer_spoof",
        today="2026-07-11",
    )
    assert result.authority == "unknown"
    assert result.score_eligible is False


def test_source_id_is_order_independent_when_primary_sort_fields_tie() -> None:
    frame = pd.DataFrame(
        {
            "security": ["A", "A"],
            "isin": ["GB0000000001", "GB0000000002"],
            "weight": [0.5, 0.5],
            "sector": ["Technology", "Financials"],
        }
    )
    first = normalise_holdings(frame, "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    second = normalise_holdings(frame.iloc[::-1], "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert first.source_id == second.source_id


def test_future_holdings_are_invalid_and_never_score_eligible() -> None:
    result = normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [1.0]}), "VWCE", "2026-07-12", "issuer", today="2026-07-11")
    assert result.completeness == "invalid"
    assert result.freshness == "invalid"
    assert result.score_eligible is False
    assert result.frame.empty
    assert "future_holdings" in result.warnings


@pytest.mark.parametrize(
    "frame",
    [
        pd.DataFrame({"security": ["A"], "weight": [-0.1]}),
        pd.DataFrame({"security": ["A", "B"], "weight": [0.8, 0.3]}),
        pd.DataFrame({"security": [""], "weight": [1.0]}),
    ],
)
def test_invalid_weights_or_empty_security_block_exposure(frame: pd.DataFrame) -> None:
    result = normalise_holdings(frame, "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "invalid"
    assert result.score_eligible is False


def test_exact_duplicate_rows_do_not_change_source_id_or_weight_sum() -> None:
    frame = pd.DataFrame({"security": ["A", "A", "B"], "ticker": ["A", "A", "B"], "weight": [0.6, 0.6, 0.4]})
    result = normalise_holdings(frame, "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "full"
    assert len(result.frame) == 2
    assert result.warnings == ("exact_duplicate_rows_removed",)


def test_holdings_are_persisted_with_provenance_columns(tmp_path: Path) -> None:
    result = normalise_holdings(pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    destination = tmp_path / "fund_holdings.parquet"
    written = write_holdings_records(result, destination=destination)
    stored = pd.read_parquet(written)
    assert {"source_id", "completeness", "freshness", "confidence", "authority", "score_eligible"} <= set(stored.columns)


def test_risk_adapts_legacy_reference_holdings_without_dropping_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(risk_page_module, "FUND_HOLDINGS_PATH", tmp_path / "missing.parquet")
    monkeypatch.setattr(
        risk_page_module,
        "load_reference_dataset",
        lambda _dataset: pd.DataFrame({
            "etf_id": ["VWCE", "VWCE"],
            "as_of_date": ["2026-07-10", "2026-07-10"],
            "holding_name": ["A", "B"],
            "weight": [0.6, 0.4],
            "source": ["yfinance", "yfinance"],
            "sector": ["Technology", "Healthcare"],
            "region": ["US", "EU"],
            "currency": ["USD", "EUR"],
        }),
    )
    adapted = risk_page_module._load_holdings_evidence()
    assert not adapted.empty
    assert adapted["completeness"].eq("partial").all()
    assert adapted["score_eligible"].eq(False).all()


@pytest.mark.parametrize("missing", ["score_eligible", "authority", "freshness", "completeness"])
def test_risk_exposure_fails_closed_when_holdings_metadata_is_missing(missing: str) -> None:
    frame = pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "security": ["A"],
            "weight": [1.0],
            "score_eligible": [True],
            "authority": ["issuer"],
            "freshness": ["fresh"],
            "completeness": ["full"],
        }
    ).drop(columns=[missing])
    eligible = risk_page_module._exposure_eligible_holdings(frame)
    assert eligible.empty


def test_risk_recomputes_persisted_holdings_freshness_at_consumption_time() -> None:
    from etf_cockpit.app.pages import risk as risk_page_module

    persisted = pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "security": ["Issuer holding"],
            "weight": [1.0],
            "as_of_date": ["2025-01-01"],
            "score_eligible": [True],
            "authority": ["issuer"],
            "freshness": ["fresh"],
            "completeness": ["full"],
        }
    )

    eligible = risk_page_module._exposure_eligible_holdings(persisted)

    assert eligible.empty


def test_missing_security_identity_is_invalid_and_requires_manual_review() -> None:
    result = normalise_holdings(pd.DataFrame({"weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "invalid"
    assert result.score_eligible is False
    assert "missing_security_or_weight" in result.warnings


def test_name_only_holdings_without_isin_or_ticker_are_context_only() -> None:
    result = normalise_holdings(pd.DataFrame({"holding_name": ["A"], "weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "full"
    assert result.score_eligible is False
    assert result.confidence <= 0.55
    assert "missing_isin_or_ticker_manual_review" in result.warnings


@pytest.mark.parametrize("identity_column", ["security", "holding_name", "security_name", "name"])
def test_all_name_only_holdings_identities_are_context_only(identity_column: str) -> None:
    result = normalise_holdings(pd.DataFrame({identity_column: ["A"], "weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    assert result.completeness == "full"
    assert result.score_eligible is False
    assert result.confidence <= 0.55
    assert "missing_isin_or_ticker_manual_review" in result.warnings


@pytest.mark.parametrize("identity_column", ["isin", "ticker", "holding_id", "security_id"])
def test_explicit_holdings_identity_allows_issuer_score_eligibility(identity_column: str) -> None:
    result = normalise_holdings(
        pd.DataFrame({"security": ["A"], identity_column: ["ID-A"], "weight": [1.0]}),
        "VWCE",
        "2026-07-10",
        "issuer",
        today="2026-07-11",
    )
    assert result.score_eligible is True


def test_mixed_name_only_row_keeps_entire_holdings_set_context_only() -> None:
    result = normalise_holdings(
        pd.DataFrame({"security": ["A", "B"], "ticker": ["A", ""], "weight": [0.5, 0.5]}),
        "VWCE",
        "2026-07-10",
        "issuer",
        today="2026-07-11",
    )
    assert result.score_eligible is False
    assert "missing_isin_or_ticker_manual_review" in result.warnings


@pytest.mark.parametrize(
    "result_factory",
    [
        lambda: normalise_holdings(pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [-1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11"),
        lambda: normalise_holdings(pd.DataFrame(), "VWCE", "2026-07-10", "issuer", today="2026-07-11"),
        lambda: normalise_holdings(pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [0.4]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11"),
        lambda: normalise_holdings(pd.DataFrame({"security": ["A"], "weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11"),
    ],
)
def test_write_rejects_invalid_empty_and_ineligible_results_without_replacing_store(tmp_path: Path, result_factory) -> None:
    destination = tmp_path / "fund_holdings.parquet"
    valid = normalise_holdings(pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}), "VWCE", "2026-07-10", "issuer", today="2026-07-11")
    write_holdings_records(valid, destination=destination)
    prior_bytes = destination.read_bytes()
    prior_csv_bytes = destination.with_suffix(".csv").read_bytes()
    prior_data = pd.read_parquet(destination)

    with pytest.raises(ValueError, match="score-eligible"):
        write_holdings_records(result_factory(), destination=destination)

    assert destination.read_bytes() == prior_bytes
    assert destination.with_suffix(".csv").read_bytes() == prior_csv_bytes
    pd.testing.assert_frame_equal(pd.read_parquet(destination), prior_data)


def test_write_rejects_mutated_frame_without_replacing_store(tmp_path: Path) -> None:
    destination = tmp_path / "fund_holdings.parquet"
    result = normalise_holdings(
        pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}),
        "VWCE",
        "2026-07-10",
        "issuer",
        today="2026-07-11",
    )
    write_holdings_records(result, destination=destination)
    prior_bytes = destination.read_bytes()
    prior_csv_bytes = destination.with_suffix(".csv").read_bytes()

    result.frame.loc[0, "weight"] = 0.2

    with pytest.raises(ValueError, match="score-eligible"):
        write_holdings_records(result, destination=destination)

    assert destination.read_bytes() == prior_bytes
    assert destination.with_suffix(".csv").read_bytes() == prior_csv_bytes


def test_write_rejects_mutated_schema_version_without_replacing_store(tmp_path: Path) -> None:
    destination = tmp_path / "fund_holdings.parquet"
    result = normalise_holdings(
        pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}),
        "VWCE",
        "2026-07-10",
        "issuer",
        today="2026-07-11",
    )
    write_holdings_records(result, destination=destination)
    prior_bytes = destination.read_bytes()
    prior_csv_bytes = destination.with_suffix(".csv").read_bytes()

    result.frame["schema_version"] = "corrupt"

    with pytest.raises(ValueError, match="schema_version"):
        write_holdings_records(result, destination=destination)

    assert destination.read_bytes() == prior_bytes
    assert destination.with_suffix(".csv").read_bytes() == prior_csv_bytes


def test_holdings_import_path_normalises_csv_and_persists_records(tmp_path: Path) -> None:
    from etf_cockpit.data.fund_holdings import import_etf_holdings

    source = tmp_path / "holdings.csv"
    pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}).to_csv(source, index=False)
    destination = tmp_path / "fund_holdings.parquet"
    imported = import_etf_holdings(source, "VWCE", "2026-07-10", "issuer", destination=destination)
    assert imported.score_eligible is True
    assert pd.read_parquet(destination).loc[0, "instrument_id"] == "VWCE"


def test_holdings_import_merges_disjoint_identity_schemas_without_changing_provenance(tmp_path: Path) -> None:
    from etf_cockpit.data.fund_holdings import import_etf_holdings

    destination = tmp_path / "fund_holdings.parquet"
    first_source = tmp_path / "vwce.csv"
    second_source = tmp_path / "lyp6.csv"
    pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}).to_csv(first_source, index=False)
    pd.DataFrame({"security": ["B"], "isin": ["IE00TEST0002"], "weight": [1.0]}).to_csv(second_source, index=False)

    first = import_etf_holdings(first_source, "VWCE", "2026-07-10", "issuer", destination=destination, today="2026-07-11")
    import_etf_holdings(second_source, "LYP6", "2026-07-11", "issuer", destination=destination, today="2026-07-11")

    stored = pd.read_parquet(destination)
    assert set(stored["instrument_id"]) == {"VWCE", "LYP6"}
    assert stored.loc[stored["instrument_id"].eq("VWCE"), "source_id"].eq(first.source_id).all()
    assert stored.loc[stored["instrument_id"].eq("VWCE"), "ticker"].eq("A").all()
    assert stored.loc[stored["instrument_id"].eq("LYP6"), "isin"].eq("IE00TEST0002").all()


def test_holdings_import_rejects_malformed_existing_store_without_writes(tmp_path: Path) -> None:
    from etf_cockpit.data.fund_holdings import import_etf_holdings

    destination = tmp_path / "fund_holdings.parquet"
    malformed = pd.DataFrame({"instrument_id": ["OTHER"], "unrelated": ["not holdings"]})
    malformed.to_parquet(
        destination, index=False
    )
    mirror = destination.with_suffix(".csv")
    malformed.to_csv(mirror, index=False)
    prior_bytes = destination.read_bytes()
    prior_mirror_bytes = mirror.read_bytes()
    source = tmp_path / "vwce.csv"
    pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}).to_csv(
        source, index=False
    )

    with pytest.raises(ValueError, match="required|schema|canonical"):
        import_etf_holdings(
            source,
            "VWCE",
            "2026-07-10",
            "issuer",
            destination=destination,
            today="2026-07-11",
        )

    assert destination.read_bytes() == prior_bytes
    assert mirror.read_bytes() == prior_mirror_bytes


def test_holdings_import_rejects_empty_existing_store_without_schema(tmp_path: Path) -> None:
    from etf_cockpit.data.fund_holdings import import_etf_holdings

    destination = tmp_path / "fund_holdings.parquet"
    pd.DataFrame(columns=["instrument_id"]).to_parquet(destination, index=False)
    prior_bytes = destination.read_bytes()
    source = tmp_path / "vwce.csv"
    pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}).to_csv(
        source, index=False
    )

    with pytest.raises(ValueError, match="missing required columns"):
        import_etf_holdings(
            source,
            "VWCE",
            "2026-07-10",
            "issuer",
            destination=destination,
            today="2026-07-11",
        )

    assert destination.read_bytes() == prior_bytes


def test_document_holdings_import_rejects_invalid_post_binding_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import etf_cockpit.data.fund_holdings as fund_holdings

    source = tmp_path / "holdings.csv"
    pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}).to_csv(
        source, index=False
    )
    holdings_destination = tmp_path / "fund_holdings.parquet"
    registry_destination = tmp_path / "fund_documents.parquet"
    real_attach = fund_holdings._attach_document_binding

    def corrupt_binding(frame: pd.DataFrame, document: object) -> pd.DataFrame:
        corrupted = real_attach(frame, document)
        corrupted["source"] = ""
        return corrupted

    monkeypatch.setattr(fund_holdings, "_attach_document_binding", corrupt_binding)

    with pytest.raises(ValueError, match="missing row provenance=source"):
        fund_holdings.import_etf_holdings_with_document(
            source,
            "VWCE",
            "2026-07-10",
            holdings_destination=holdings_destination,
            registry_destination=registry_destination,
            today="2026-07-11",
        )

    for destination in (
        holdings_destination,
        holdings_destination.with_suffix(".csv"),
        registry_destination,
        registry_destination.with_suffix(".csv"),
    ):
        assert not destination.exists()


def test_combined_holdings_import_persists_manual_unverified_context_and_document(tmp_path: Path) -> None:
    import etf_cockpit.data.fund_holdings as fund_holdings
    from etf_cockpit.data.fund_documents import read_document_registry

    source = tmp_path / "holdings.csv"
    source.write_bytes(b"security,ticker,weight,as_of\nManual,MAN,1.0,2026-08-09\n")
    holdings_destination = tmp_path / "fund_holdings.parquet"
    registry_destination = tmp_path / "fund_documents.parquet"

    imported = fund_holdings.import_etf_holdings_with_document(
        source,
        "VWCE",
        "2026-08-09",
        "manual_unverified",
        holdings_destination=holdings_destination,
        registry_destination=registry_destination,
        today="2026-08-10",
    )

    assert imported.source == "manual_unverified"
    assert imported.authority == "unknown"
    assert imported.score_eligible is False
    stored = pd.read_parquet(holdings_destination)
    assert stored["source"].eq("manual_unverified").all()
    assert stored["authority"].eq("unknown").all()
    assert stored["score_eligible"].eq(False).all()
    registry = read_document_registry(path=registry_destination)
    document = registry.loc[registry["document_type"].eq("holdings")].iloc[0]
    assert document["authority"] == "manual_unverified"
    assert stored["document_source_id"].eq(document["source_id"]).all()
    assert stored["document_checksum"].eq(document["sha256"]).all()


def test_concurrent_holdings_imports_preserve_disjoint_identity_schemas(tmp_path: Path) -> None:
    from etf_cockpit.data.fund_holdings import import_etf_holdings

    destination = tmp_path / "fund_holdings.parquet"
    sources = {}
    for instrument, identity_column, identity_value in (
        ("VWCE", "ticker", "A"),
        ("LYP6", "isin", "IE00TEST0002"),
    ):
        source = tmp_path / f"{instrument.lower()}.csv"
        pd.DataFrame({"security": [identity_value], identity_column: [identity_value], "weight": [1.0]}).to_csv(
            source, index=False
        )
        sources[instrument] = source
    start = Barrier(2)

    def import_one(instrument: str) -> tuple[str, str]:
        start.wait(timeout=20)
        result = import_etf_holdings(
            sources[instrument],
            instrument,
            "2026-07-10",
            "issuer",
            destination=destination,
            today="2026-07-11",
        )
        return instrument, result.source_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(import_one, instrument) for instrument in sources]
        expected_source_ids = dict(future.result(timeout=30) for future in futures)

    stored = pd.read_parquet(destination)
    assert set(stored["instrument_id"].astype(str)) == {"VWCE", "LYP6"}
    assert {
        instrument: group["source_id"].iloc[0]
        for instrument, group in stored.groupby("instrument_id")
    } == expected_source_ids


def test_combined_holdings_import_preserves_registry_instrument_omitted_from_configured_ids(tmp_path: Path) -> None:
    import etf_cockpit.data.fund_holdings as fund_holdings
    from etf_cockpit.data.fund_documents import register_document, write_document_registry

    holdings_destination = tmp_path / "fund_holdings.parquet"
    registry_destination = tmp_path / "fund_documents.parquet"
    prior_source = tmp_path / "disabled-factsheet.pdf"
    prior_source.write_bytes(b"disabled instrument document")
    prior = register_document(
        prior_source,
        "factsheet",
        "DISABLED",
        "https://issuer.example/disabled/factsheet.pdf",
        "issuer",
        document_date="2026-07-10",
    )
    write_document_registry([prior], destination=registry_destination)

    import_source = tmp_path / "vwce-holdings.csv"
    pd.DataFrame({"security": ["Imported"], "ticker": ["IMPORTED"], "weight": [1.0]}).to_csv(import_source, index=False)
    fund_holdings.import_etf_holdings_with_document(
        import_source,
        "VWCE",
        "2026-07-11",
        "issuer",
        holdings_destination=holdings_destination,
        registry_destination=registry_destination,
        configured_instrument_ids=["VWCE"],
        today="2026-07-11",
    )

    stored = pd.read_parquet(registry_destination)
    assert set(stored["instrument_id"]) == {"DISABLED", "VWCE"}
    retained = stored.loc[stored["source_id"] == prior.source_id].iloc[0]
    assert retained["coverage_status"] == "available"
    disabled_rows = stored[stored["instrument_id"] == "DISABLED"]
    assert disabled_rows["document_type"].nunique() == len(DOCUMENT_TYPES)
    assert disabled_rows.loc[disabled_rows["document_type"] != "factsheet", "coverage_status"].eq("missing").all()


def test_risk_holdings_loader_keeps_legacy_vendor_context_when_canonical_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from etf_cockpit.data.fund_holdings import import_etf_holdings

    canonical = tmp_path / "fund_holdings.parquet"
    source = tmp_path / "vwce.csv"
    pd.DataFrame({"security": ["A"], "ticker": ["A"], "weight": [1.0]}).to_csv(source, index=False)
    import_etf_holdings(source, "VWCE", "2026-07-10", "issuer", destination=canonical, today="2026-07-11")
    monkeypatch.setattr(risk_page_module, "FUND_HOLDINGS_PATH", canonical)
    monkeypatch.setattr(
        risk_page_module,
        "load_reference_dataset",
        lambda _dataset: pd.DataFrame(
            {
                "etf_id": ["LYP6"],
                "as_of_date": ["2026-07-10"],
                "holding_name": ["Vendor B"],
                "weight": [0.4],
                "source": ["yfinance"],
            }
        ),
    )

    loaded = risk_page_module._load_holdings_evidence()
    assert set(loaded["instrument_id"]) == {"VWCE", "LYP6"}
    vendor = loaded.loc[loaded["instrument_id"] == "LYP6"].iloc[0]
    assert vendor["authority"] == "vendor"
    assert bool(vendor["score_eligible"]) is False


def test_risk_holdings_loader_uses_csv_mirror_when_parquet_engine_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canonical = tmp_path / "fund_holdings.parquet"
    pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "as_of_date": ["2026-07-10"],
            "completeness": ["partial"],
            "freshness": ["fresh"],
            "confidence": [0.55],
            "authority": ["issuer"],
            "score_eligible": [False],
        }
    ).to_csv(canonical.with_suffix(".csv"), index=False)
    canonical.write_bytes(b"placeholder")
    monkeypatch.setattr(risk_page_module, "FUND_HOLDINGS_PATH", canonical)
    monkeypatch.setattr(risk_page_module, "load_reference_dataset", lambda _dataset: pd.DataFrame())
    monkeypatch.setattr(risk_page_module.pd, "read_parquet", lambda *_args, **_kwargs: (_ for _ in ()).throw(ImportError("pyarrow unavailable")))

    loaded = risk_page_module._load_holdings_evidence()

    assert loaded.loc[0, "instrument_id"] == "VWCE"
    assert loaded.loc[0, "completeness"] == "partial"


def test_risk_holdings_loader_resolves_portable_root_when_imported_path_is_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    portable_root = tmp_path / "portable"
    clean = portable_root / "data" / "clean"
    clean.mkdir(parents=True)
    pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "as_of_date": ["2026-07-10"],
            "completeness": ["partial"],
            "freshness": ["fresh"],
            "confidence": [0.55],
            "authority": ["issuer"],
            "score_eligible": [False],
        }
    ).to_csv(clean / "fund_holdings.csv", index=False)
    monkeypatch.setenv("ETF_COCKPIT_ROOT", str(portable_root))
    monkeypatch.setattr(risk_page_module, "FUND_HOLDINGS_PATH", tmp_path / "source-tree" / "data" / "clean" / "fund_holdings.parquet")
    monkeypatch.setattr(risk_page_module, "load_reference_dataset", lambda _dataset: pd.DataFrame())
    monkeypatch.setattr(risk_page_module.pd, "read_parquet", lambda *_args, **_kwargs: (_ for _ in ()).throw(ImportError("pyarrow unavailable")))

    loaded = risk_page_module._load_holdings_evidence()

    assert loaded.loc[0, "instrument_id"] == "VWCE"
    assert loaded.loc[0, "authority"] == "issuer"


def test_risk_holdings_loader_uses_nonempty_csv_when_packaged_parquet_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canonical = tmp_path / "fund_holdings.parquet"
    canonical.write_bytes(b"packaged placeholder")
    pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "as_of_date": ["2026-07-10"],
            "completeness": ["partial"],
            "freshness": ["fresh"],
            "confidence": [0.55],
            "authority": ["issuer"],
            "score_eligible": [False],
        }
    ).to_csv(canonical.with_suffix(".csv"), index=False)
    monkeypatch.setattr(risk_page_module, "FUND_HOLDINGS_PATH", canonical)
    monkeypatch.setattr(risk_page_module, "load_reference_dataset", lambda _dataset: pd.DataFrame())
    monkeypatch.setattr(risk_page_module.pd, "read_parquet", lambda *_args, **_kwargs: pd.DataFrame())

    loaded = risk_page_module._load_holdings_evidence()

    assert loaded.loc[0, "instrument_id"] == "VWCE"


def test_risk_holdings_loader_never_mixes_legacy_when_canonical_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canonical = tmp_path / "fund_holdings.parquet"
    pd.DataFrame(
        {
            "instrument_id": ["VWCE"],
            "as_of_date": ["2026-07-10"],
            "source_id": ["canonical-source"],
            "completeness": ["partial"],
            "freshness": ["fresh"],
            "confidence": [0.55],
            "authority": ["issuer"],
            "score_eligible": [False],
        }
    ).to_parquet(canonical, index=False)
    monkeypatch.setattr(risk_page_module, "_holdings_file_candidates", lambda: (canonical,))
    monkeypatch.setattr(
        risk_page_module,
        "load_reference_dataset",
        lambda _dataset: pd.DataFrame(
            {
                "etf_id": ["VWCE"],
                "as_of_date": ["2026-07-11"],
                "holding_name": ["Newer legacy row"],
                "weight": [1.0],
                "source": ["yfinance"],
            }
        ),
    )

    loaded = risk_page_module._load_holdings_evidence()

    assert loaded["source_id"].tolist() == ["canonical-source"]


@pytest.mark.parametrize("weight", [True, float("inf"), float("nan")])
def test_risk_exposure_eligibility_rejects_untrusted_weights(weight: object) -> None:
    holdings = pd.DataFrame(
        [{
            "instrument_id": "VWCE",
            "as_of": "2026-07-10",
            "weight": weight,
            "source_id": "issuer-source",
            "completeness": "full",
            "freshness": "fresh",
            "confidence": 0.9,
            "authority": "issuer",
            "score_eligible": True,
        }]
    )

    assert risk_page_module._exposure_eligible_holdings(holdings).empty


def test_risk_exposure_eligibility_requires_provenance_and_ages_as_of_only() -> None:
    holdings = pd.DataFrame(
        [{
            "instrument_id": "VWCE",
            "as_of": "2000-01-01",
            "weight": 1.0,
            "source_id": "",
            "completeness": "full",
            "freshness": "fresh",
            "confidence": 0.9,
            "authority": "issuer",
            "score_eligible": True,
        }]
    )

    assert risk_page_module._exposure_eligible_holdings(holdings).empty


def test_risk_exposure_eligibility_fails_closed_on_malformed_persisted_date() -> None:
    holdings = pd.DataFrame(
        [{
            "instrument_id": "VWCE",
            "as_of_date": "not-a-date",
            "completeness": "full",
            "freshness": "fresh",
            "confidence": 0.9,
            "authority": "issuer",
            "score_eligible": True,
        }]
    )

    eligible = risk_page_module._exposure_eligible_holdings(holdings)

    assert eligible.empty


def test_risk_exposure_eligibility_fails_closed_on_out_of_range_persisted_date() -> None:
    holdings = pd.DataFrame(
        [{
            "instrument_id": "VWCE",
            "as_of_date": "2999-01-01",
            "completeness": "full",
            "freshness": "fresh",
            "confidence": 0.9,
            "authority": "issuer",
            "score_eligible": True,
        }]
    )

    eligible = risk_page_module._exposure_eligible_holdings(holdings)

    assert eligible.empty


def test_risk_holdings_quality_marks_malformed_persisted_date_invalid() -> None:
    from etf_cockpit.app.pages.risk import _refresh_holdings_freshness

    refreshed = _refresh_holdings_freshness(
        pd.DataFrame(
            [{
                "instrument_id": "VWCE",
                "as_of_date": "not-a-date",
                "completeness": "full",
                "freshness": "fresh",
                "confidence": 0.9,
                "score_eligible": True,
            }]
        )
    )

    row = refreshed.iloc[0]
    assert row["freshness"] == "invalid"
    assert row["completeness"] == "invalid"
    assert bool(row["score_eligible"]) is False
    assert float(row["confidence"]) == 0.0


def test_combined_holdings_import_leaves_holdings_and_registry_unchanged_when_registry_stage_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import etf_cockpit.data.fund_holdings as fund_holdings
    from etf_cockpit.core import atomic_io
    from etf_cockpit.data.fund_documents import register_document, write_document_registry

    holdings_destination = tmp_path / "fund_holdings.parquet"
    registry_destination = tmp_path / "fund_documents.parquet"
    prior_source = tmp_path / "prior.csv"
    import_source = tmp_path / "import.csv"
    pd.DataFrame({"security": ["Prior"], "ticker": ["PRIOR"], "weight": [1.0]}).to_csv(prior_source, index=False)
    pd.DataFrame({"security": ["Imported"], "ticker": ["IMPORTED"], "weight": [1.0]}).to_csv(import_source, index=False)
    fund_holdings.import_etf_holdings(prior_source, "VWCE", "2026-07-10", "issuer", destination=holdings_destination, today="2026-07-11")
    prior_document = register_document(prior_source, "holdings", "VWCE", "", "issuer_document", document_date="2026-07-10")
    write_document_registry([prior_document], destination=registry_destination)
    prior_holdings_bytes = holdings_destination.read_bytes()
    prior_holdings_csv_bytes = holdings_destination.with_suffix(".csv").read_bytes()
    prior_registry_bytes = registry_destination.read_bytes()
    prior_registry_csv_bytes = registry_destination.with_suffix(".csv").read_bytes()

    real_atomic_write_group = atomic_io.atomic_write_group

    def fail_registry_stage(requests, **kwargs):
        staged_requests = []
        for request in tuple(requests):
            if request.destination.resolve() == registry_destination.resolve():
                staged_requests.append(
                    atomic_io.AtomicWriteRequest(request.destination, request.payload, lambda _path: (_ for _ in ()).throw(OSError("registry validation failed")))
                )
            else:
                staged_requests.append(request)
        return real_atomic_write_group(tuple(staged_requests), **kwargs)

    monkeypatch.setattr(fund_holdings, "atomic_write_group", fail_registry_stage)
    with pytest.raises(OSError, match="registry validation failed"):
        fund_holdings.import_etf_holdings_with_document(
            import_source,
            "LYP6",
            "2026-07-11",
            "issuer",
            holdings_destination=holdings_destination,
            registry_destination=registry_destination,
            configured_instrument_ids=["VWCE", "LYP6"],
            today="2026-07-11",
        )

    assert holdings_destination.read_bytes() == prior_holdings_bytes
    assert holdings_destination.with_suffix(".csv").read_bytes() == prior_holdings_csv_bytes
    assert registry_destination.read_bytes() == prior_registry_bytes
    assert registry_destination.with_suffix(".csv").read_bytes() == prior_registry_csv_bytes
