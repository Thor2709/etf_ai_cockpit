"""PT2: point-in-time and provenance hardening (V8 P2/P3 data items)."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from etf_cockpit.data import forward_evidence_diary as diary_module
from etf_cockpit.data.forward_evidence_diary import (
    ForwardEvidenceDiary,
    ForwardEvidenceObservation,
    ForwardInputManifest,
)
from etf_cockpit.data.fundamentals import latest_fundamental_rows
from etf_cockpit.data.market_adjustments import (
    FXObservation,
    FXObservationStore,
    CorporateAction,
    apply_total_return_adjustments,
    derive_fx_cross,
    reconcile_adjustments,
)
from etf_cockpit.features.feature_store import (
    FeatureDefinition,
    FeatureStoreError,
    LocalFeatureStore,
    TargetDefinition,
)
from scripts.import_official_filing import _resolve_published_at


# --- C.C2.S20.N002 fundamentals: known-time ordering --------------------------------------------


def test_latest_fundamental_row_prefers_latest_available_vintage_for_same_period() -> None:
    frame = pd.DataFrame(
        [
            {"instrument_id": "A", "as_of_date": "2025-06-30", "available_at": "2025-08-01", "evidence_checksum": "zzz", "valuation": 1.0},
            {"instrument_id": "A", "as_of_date": "2025-06-30", "available_at": "2025-09-15", "evidence_checksum": "aaa", "valuation": 2.0},
        ]
    )
    for ordered in (frame, frame.iloc[::-1].reset_index(drop=True)):
        latest = latest_fundamental_rows(ordered)
        assert len(latest) == 1
        assert latest.iloc[0]["valuation"] == 2.0


# --- A.C6.S09.N001 FX: every enumerated path must agree -----------------------------------------


def _fx(observation_id: str, base: str, quote: str, rate: float, *, known_at: str = "2024-01-10T00:00:00Z", revision: int = 1, source_id: str | None = None) -> FXObservation:
    return FXObservation(
        observation_id=observation_id,
        base_currency=base,
        quote_currency=quote,
        rate=Decimal(str(rate)),
        valid_at="2024-01-10T00:00:00Z",
        published_at="2024-01-10T00:00:00Z",
        retrieved_at=known_at,
        known_at=known_at,
        revision=revision,
        source="fixture:ecb-reference",
        source_id=source_id or f"fixture:ecb-reference:{observation_id}",
        source_checksum=f"sha256:{observation_id}:{revision}",
        is_reference=True,
        executable=False,
        authority="official",
    )


def test_fx_cross_rejects_inconsistent_path_longer_than_shortest_plus_one(tmp_path: Path) -> None:
    with FXObservationStore(tmp_path) as store:
        store.append(_fx("EURJPY", "EUR", "JPY", 160.0))
        store.append(_fx("EURUSD", "EUR", "USD", 1.0))
        store.append(_fx("USDJPY", "USD", "JPY", 160.0))
        store.append(_fx("EURGBP", "EUR", "GBP", 1.0))
        store.append(_fx("GBPUSD", "GBP", "USD", 1.5))  # EUR->GBP->USD->JPY = 240 disagrees with 160

        result = derive_fx_cross(store, "EUR", "JPY", as_of="2024-01-10T00:00:00Z")

    assert result.available is False
    assert result.status == "quarantined"
    assert "triangular_inconsistency" in result.discrepancies


# --- A.C3.S10.N001 daily vintages are alternatives, not sequential returns -----------------------


def test_same_day_vintages_are_returns_against_prior_day_not_prior_vintage() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2024-01-09", "2024-01-10", "2024-01-10", "2024-01-11"],
            "close": [100.0, 90.0, 110.0, 110.0],
            "known_at": ["2024-01-09T18:00:00Z", "2024-01-10T18:00:00Z", "2024-01-11T09:00:00Z", "2024-01-11T18:00:00Z"],
        }
    )
    result = apply_total_return_adjustments(prices, ())

    assert result.status == "available"
    frame = result.frame
    returns = frame["local_total_return"].tolist()
    assert returns[1] == pytest.approx(-0.10)
    assert returns[2] == pytest.approx(0.10)  # revision measured against the prior day's close, not the 90 vintage
    assert returns[3] == pytest.approx(0.0)
    assert frame["total_return_index"].iloc[-1] == pytest.approx(110.0)
    assert result.total_return == pytest.approx(0.10)
    assert reconcile_adjustments(result).available


@pytest.mark.parametrize("cash_amount", [0.0, 1.0])
def test_late_prior_close_revision_does_not_leak_into_historical_returns(cash_amount: float) -> None:
    prices = pd.DataFrame({
        "date": ["2024-01-09", "2024-01-09", "2024-01-10", "2024-01-10", "2024-01-11", "2024-01-11"],
        "close": [100.0, 120.0, 110.0, 132.0, 121.0, 145.2],
        "currency": "USD",
        "known_at": [f"2024-01-{day:02}T18:00:00Z" for day in (9, 12, 10, 13, 11, 14)],
    })
    actions = (CorporateAction(
        action_id="DIV-LATE", instrument_id="ETF1", action_type="dividend",
        announced_at="2024-01-01T00:00:00Z", effective_at="2024-01-10T00:00:00Z",
        ex_date="2024-01-10", payable_at="2024-01-31", known_at="2024-01-02T00:00:00Z",
        revision=1, source="provider:a", source_id="provider:a:DIV-LATE",
        source_checksum="sha256:DIV-LATE", amount=cash_amount, currency="USD",
    ),) if cash_amount else ()
    result = apply_total_return_adjustments(prices, actions)
    assert result.status == "available"
    assert result.frame["price_return"].iloc[2:].tolist() == pytest.approx([0.1] * 4)
    assert result.frame["local_total_return"].iloc[2:].tolist() == pytest.approx([
        (110 + cash_amount) / 100 - 1, (132 + cash_amount) / 120 - 1, 0.1, 0.1,
    ])
    assert result.frame["price_return_index"].tolist() == pytest.approx([100, 100, 110, 110, 121, 121])
    assert result.frame["total_return_index"].tolist() == pytest.approx([
        100, 100, 110 + cash_amount, (132 + cash_amount) / 1.2,
        (110 + cash_amount) * 1.1, (132 + cash_amount) / 1.2 * 1.1,
    ])
    assert result.total_return == pytest.approx((132 + cash_amount) / 120 * 1.1 - 1)
    assert reconcile_adjustments(result).reconciled
    # Removing future publications must leave each historically selectable return/index unchanged.
    for cutoff in prices["known_at"]:
        historical = apply_total_return_adjustments(prices.loc[prices["known_at"] <= cutoff], actions)
        selected = result.frame.loc[result.frame["known_at"] <= cutoff]
        for column in (
            "price_return", "local_total_return", "price_return_index", "total_return_index",
            "price_adjusted_close", "adjusted_close",
        ):
            pd.testing.assert_series_equal(selected[column].reset_index(drop=True), historical.frame[column])
    tampered = result.frame.copy()
    tampered.loc[2, "local_total_return"] = 110 / 120 - 1
    assert reconcile_adjustments(tampered).status == "quarantined"
    missing_prior = prices.copy()
    missing_prior.loc[0, "known_at"] = "2024-01-15T18:00:00Z"
    unavailable = apply_total_return_adjustments(missing_prior, actions)
    assert unavailable.status == "unavailable"
    assert "price_vintage_unavailable_at_knowledge_time" in unavailable.warnings
    assert unavailable.frame["total_return_index"].isna().all()


def test_same_day_vintage_dividend_is_not_counted_twice() -> None:
    action = CorporateAction(
        action_id="DIV-1",
        instrument_id="ETF1",
        action_type="dividend",
        announced_at="2023-12-15T00:00:00Z",
        effective_at="2024-01-10T00:00:00Z",
        ex_date="2024-01-10",
        payable_at="2024-01-31",
        known_at="2024-01-02T00:00:00Z",
        revision=1,
        source="provider:a",
        source_id="provider:a:DIV-1",
        source_checksum="sha256:DIV-1",
        amount=1.0,
        currency="USD",
    )
    prices = pd.DataFrame(
        {
            "date": ["2024-01-09", "2024-01-10", "2024-01-10"],
            "close": [100.0, 99.0, 99.0],
            "currency": "USD",
            "known_at": ["2024-01-09T18:00:00Z", "2024-01-10T18:00:00Z", "2024-01-11T09:00:00Z"],
        }
    )
    result = apply_total_return_adjustments(prices, (action,), price_currency="USD")
    assert result.status == "available"
    assert result.income_return == pytest.approx(0.01)


@pytest.mark.parametrize("terminal_close", [119.0, 0.0])
def test_first_day_revision_is_shared_income_and_anchor_origin(terminal_close: float) -> None:
    action = CorporateAction(
        action_id="DIV-ORIGIN", instrument_id="ETF1", action_type="dividend",
        announced_at="2024-01-01T00:00:00Z", effective_at="2024-01-10T00:00:00Z",
        ex_date="2024-01-10", payable_at="2024-01-31", known_at="2024-01-02T00:00:00Z",
        revision=1, source="provider:a", source_id="provider:a:DIV-ORIGIN",
        source_checksum="sha256:DIV-ORIGIN", amount=1.0, currency="USD",
    )
    prices = pd.DataFrame({
        "date": ["2024-01-09", "2024-01-09", "2024-01-10"],
        "close": [100.0, 120.0, terminal_close], "currency": "USD",
        "known_at": ["2024-01-09T18:00:00Z", "2024-01-10T09:00:00Z", "2024-01-10T18:00:00Z"],
    })
    result = apply_total_return_adjustments(prices, (action,), price_currency="USD")
    assert result.status == "available"
    assert result.income_return == pytest.approx(1.0 / 120.0)
    assert result.price_return == pytest.approx(terminal_close / 120.0 - 1.0)
    assert result.total_return == pytest.approx((terminal_close + 1.0) / 120.0 - 1.0)
    assert result.frame["price_adjusted_close"].iloc[1] == pytest.approx(120.0)
    if terminal_close == 0.0:
        assert result.frame["adjusted_close"].iloc[1] == pytest.approx(120.0)
        assert result.frame["adjusted_close"].iloc[-1] == pytest.approx(1.0)
        no_income = apply_total_return_adjustments(prices, (), price_currency="USD")
        assert no_income.frame["adjusted_close"].tolist() == pytest.approx([100.0, 120.0, 0.0])  # row 0 anchors on its own as-known snapshot


# --- A.C4.S06.N002 filing publication date ------------------------------------------------------


def test_explicit_publication_date_beats_unlinked_sidecar_date(tmp_path: Path) -> None:
    source = tmp_path / "package.xbri"
    source.write_bytes(b"x")
    (tmp_path / "unrelated.json").write_text(json.dumps({"data": {"attributes": {"date_added": "2025-02-27"}}}), encoding="utf-8")

    assert _resolve_published_at(source, "https://example.invalid/filing", "2026-03-05") == "2026-03-05"
    # Without an explicit date the sole unlinked sidecar remains the only available evidence.
    assert _resolve_published_at(source, "https://example.invalid/filing", None) == "2025-02-27"


# --- A.C3.S10.N002 FX raw query vs lineage ------------------------------------------------------


def test_derive_fx_cross_collapses_revisions_of_a_raw_query_sequence(tmp_path: Path) -> None:
    original = _fx("EURUSD-REV", "EUR", "USD", 1.20, known_at="2024-01-10T00:00:00Z")
    correction = replace(original, rate=Decimal("1.30"), revision=2, known_at="2024-01-11T00:00:00Z")
    with FXObservationStore(tmp_path) as store:
        store.append(original)
        store.append(correction)
        raw = store.query("EUR", "USD")
        assert len(raw) == 2

        later = derive_fx_cross(raw, "EUR", "USD", as_of="2024-01-10T00:00:00Z", decision_time="2024-01-11T00:00:00Z")
        earlier = derive_fx_cross(raw, "EUR", "USD", as_of="2024-01-10T00:00:00Z", decision_time="2024-01-10T12:00:00Z")

    assert later.available is True and later.rate == pytest.approx(1.30) and later.discrepancies == ()
    assert earlier.available is True and earlier.rate == pytest.approx(1.20)


# --- A.C5.S22 forward-evidence diary lock -------------------------------------------------------


def _diary_observation() -> ForwardEvidenceObservation:
    from datetime import datetime, timezone

    as_of = datetime(2026, 7, 19, tzinfo=timezone.utc)
    return ForwardEvidenceObservation(
        observation_id="observation-1",
        created_at=as_of,
        instrument_ids=("ETF1",),
        manifest=ForwardInputManifest(
            as_of=as_of,
            data_hash="d" * 64,
            formula_hash="e" * 64,
            model_hash="a" * 64,
            portfolio_hash="b" * 64,
            policy_hash="c" * 64,
            proposal_hash="9" * 64,
            source_authority="test-adjusted-price-source",
            source_checksum="f" * 64,
        ),
        proposal_outcome="observation_only",
        proposal_id=None,
        paper_order_ids=(),
        decision="manual_review",
        rationale="Evidence is retained for a later, explicit outcome update.",
    )


def test_write_lock_release_never_removes_a_lock_owned_by_someone_else(tmp_path: Path) -> None:
    diary = ForwardEvidenceDiary()
    lock_path = tmp_path / "forward_evidence_diary" / ".diary-write.lock"
    with diary._write_lock(tmp_path):
        lock_path.write_text("424242:foreign-owner", encoding="ascii")
    assert lock_path.read_text(encoding="ascii") == "424242:foreign-owner"


def test_write_lock_recovers_only_dead_owner_locks_and_fails_closed_otherwise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diary_module, "_LOCK_TIMEOUT_SECONDS", 0.0)
    diary = ForwardEvidenceDiary()
    live = tmp_path / "live"
    lock = live / "forward_evidence_diary" / ".diary-write.lock"
    lock.parent.mkdir(parents=True)
    import os

    lock.write_text(f"{os.getpid()}:live-owner", encoding="ascii")
    with pytest.raises(TimeoutError):
        diary.record_observation(_diary_observation(), root=live)
    assert lock.read_text(encoding="ascii") == f"{os.getpid()}:live-owner"


def test_write_lock_is_not_stolen_twice_by_concurrent_stale_recoveries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two waiters that both see a dead owner must not both end up holding the lock."""

    monkeypatch.setattr(diary_module, "_LOCK_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(diary_module, "_pid_alive", lambda pid: False)
    diary = ForwardEvidenceDiary()
    lock = tmp_path / "forward_evidence_diary" / ".diary-write.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("999999:dead", encoding="ascii")

    holders: list[str] = []
    guard = threading.Lock()
    inside = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def worker(name: str) -> None:
        try:
            with diary._write_lock(tmp_path):
                with guard:
                    holders.append(name)
                    simultaneous = len(holders)
                if simultaneous == 1:
                    inside.set()
                    release.wait(2.0)
                with guard:
                    holders.remove(name)
        except TimeoutError:
            pass
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    first = threading.Thread(target=worker, args=("a",))
    first.start()
    assert inside.wait(5.0)
    second = threading.Thread(target=worker, args=("b",))
    second.start()
    second.join(5.0)
    overlap = len(holders)
    release.set()
    first.join(5.0)
    assert not errors
    assert overlap == 1, "second waiter took over a live lock"


# --- Feature store ------------------------------------------------------------------------------


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), float("-inf")])
def test_event_target_threshold_must_be_finite(threshold: float) -> None:
    with pytest.raises(FeatureStoreError):
        TargetDefinition("evt", 5, kind="event", event_threshold=threshold)


def test_drift_flags_std_and_missing_rate_changes() -> None:
    reference = pd.DataFrame({"f": [9.0, 10.0, 11.0, 10.0], "stable": [9.0, 10.0, 11.0, 10.0]})
    wider = pd.DataFrame({"f": [0.0, 10.0, 20.0, 10.0], "stable": [9.0, 10.0, 11.0, 10.0]})
    gappy = pd.DataFrame({"f": [9.0, None, None, 11.0], "stable": [9.0, 10.0, 11.0, 10.0]})

    wide = LocalFeatureStore.drift(reference, wider)["features"]
    assert wide["f"]["drifted"] is True
    assert wide["stable"]["drifted"] is False
    assert LocalFeatureStore.drift(reference, gappy)["features"]["f"]["drifted"] is True
    assert LocalFeatureStore.drift(reference, reference)["features"]["f"]["drifted"] is False


def test_register_feature_is_atomic_against_concurrent_conflicting_registration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    barrier = threading.Barrier(2)
    original_get = LocalFeatureStore.get

    def slow_get(self: LocalFeatureStore, entity_type: str, entity_id: str):
        result = original_get(self, entity_type, entity_id)
        try:
            barrier.wait(1.0)
        except threading.BrokenBarrierError:
            pass
        return result

    monkeypatch.setattr(LocalFeatureStore, "get", slow_get)
    outcomes: list[str] = []

    def register(lookback: int) -> None:
        store = LocalFeatureStore(tmp_path)
        try:
            store.register_feature(FeatureDefinition("custom_signal", "custom_signal", lookback_days=lookback))
            outcomes.append(f"ok:{lookback}")
        except FeatureStoreError:
            outcomes.append(f"conflict:{lookback}")

    LocalFeatureStore(tmp_path).feature_catalogue()  # initialise storage before the race
    threads = [threading.Thread(target=register, args=(value,)) for value in (3, 7)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20.0)

    assert sorted(item.split(":")[0] for item in outcomes) == ["conflict", "ok"]
    winner = int(next(item for item in outcomes if item.startswith("ok")).split(":")[1])
    monkeypatch.undo()
    stored = next(item for item in LocalFeatureStore(tmp_path).feature_catalogue() if item.feature_id == "custom_signal")
    assert stored.lookback_days == winner


def test_builtin_feature_cannot_be_shadowed_by_registration(tmp_path: Path) -> None:
    store = LocalFeatureStore(tmp_path)
    with pytest.raises(FeatureStoreError):
        store.register_feature(FeatureDefinition("momentum_60d", "other_column", lookback_days=5))


def test_source_vintage_hash_changes_with_available_at_and_definitions(tmp_path: Path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal", units="score"))
    base = pd.DataFrame({"etf_id": ["AAA"], "date": pd.to_datetime(["2026-01-01"]), "signal": [1.0], "available_at": ["2026-01-01T00:00:00Z"]})
    later = base.assign(available_at="2026-01-01T06:00:00Z")
    first = store.materialise(base, ["2026-01-02"], feature_ids=["signal"])
    second = store.materialise(later, ["2026-01-02"], feature_ids=["signal"])
    assert first["source_vintage_hash"].iloc[0] != second["source_vintage_hash"].iloc[0]


def test_dropped_registered_feature_is_visible_in_the_definition_hash_and_explicit_requests_fail(tmp_path: Path) -> None:
    store = LocalFeatureStore(tmp_path)
    store.register_feature(FeatureDefinition("signal", "signal", units="score"))
    store.register_feature(FeatureDefinition("other", "other", units="score"))
    full = pd.DataFrame({"etf_id": ["AAA"], "date": pd.to_datetime(["2026-01-01"]), "signal": [1.0], "other": [2.0]})
    partial = full.drop(columns=["other"])
    full_matrix = store.materialise(full, ["2026-01-02"])
    partial_matrix = store.materialise(partial, ["2026-01-02"])
    assert full_matrix["feature_definition_hash"].iloc[0] != partial_matrix["feature_definition_hash"].iloc[0]
    with pytest.raises(FeatureStoreError):
        store.materialise(partial, ["2026-01-02"], feature_ids=["signal", "other"])


# --- A.C4.S05.N002 SEC date-only filed ----------------------------------------------------------


def test_sec_date_only_filed_is_not_usable_on_the_filing_day() -> None:
    from etf_cockpit.parsers.sec_facts import StatementFact, select_authoritative_facts

    fact = StatementFact(
        instrument_id="X", cik="1", taxonomy="us-gaap", concept="Revenues", unit="USD", value=1.0,
        start="2024-01-01", end="2024-12-31", instant=None, filed="2025-01-20", form="10-K", accession="0001-25-000001",
        fiscal_year=2024, fiscal_period="FY", source_id="sec_edgar:1:Revenues", canonical_metric="revenue", mapping_status="mapped",
        is_custom=False, dimensions="", currency="USD", period_type="duration", mapping_confidence="high",
        manual_review_required=False, restatement_kind="reported", available_at="2025-01-20",
    )
    assert select_authoritative_facts((fact,), (), as_of="2025-01-20") == ()
    assert select_authoritative_facts((fact,), (), as_of="2025-01-21") == (fact,)


# --- A.C2.S18.N001 sample data ------------------------------------------------------------------


def test_generated_sample_data_is_always_labelled_synthetic(tmp_path, monkeypatch) -> None:
    from etf_cockpit.core.config import load_config
    from etf_cockpit.data import sample_data
    from etf_cockpit.data.fx_data import fx_rates_for_prices

    config = load_config()
    prices = sample_data.generate_sample_prices(config, periods=30, end_date=date(2026, 6, 26))
    holdings = sample_data.generate_sample_holdings(config, prices)
    assert set(prices["source"]) == {"synthetic_sample"}
    assert set(holdings["source"]) == {"synthetic_sample"}
    raw = tmp_path / "raw"
    portfolios = tmp_path / "portfolios"
    (raw / "prices").mkdir(parents=True)
    portfolios.mkdir()
    monkeypatch.setattr(sample_data, "RAW_DIR", raw)
    monkeypatch.setattr(sample_data, "PORTFOLIOS_DIR", portfolios)
    monkeypatch.setattr(sample_data, "ensure_project_dirs", lambda: None)
    monkeypatch.setattr(sample_data, "generate_sample_prices", lambda config: prices)
    price_path, holdings_path = sample_data.ensure_sample_files(config, allow_synthetic=True)
    assert set(pd.read_csv(price_path)["source"]) == {"synthetic_sample"}
    assert set(pd.read_csv(holdings_path)["source"]) == {"synthetic_sample"}
    fx = fx_rates_for_prices(prices.assign(currency="USD"))
    assert not fx.empty
    assert set(fx["source"]) == {"synthetic_sample"}
    # The explicit setting survives normal settings saves and is consumed by the loader.
    import yaml
    from etf_cockpit.core.settings_bundle import load_settings_bundle, save_settings

    settings_root = tmp_path / "settings"
    settings_path = settings_root / "configs" / "settings.yaml"
    settings_path.parent.mkdir(parents=True)
    bundle = load_settings_bundle(settings_root)
    document = {
        "schema_version": bundle.schema_version, "semantic_version": bundle.semantic_version,
        "settings_version": 0, "revision": bundle.revision,
        "controls": bundle.controls.model_dump(mode="json"),
        "data": {"allow_synthetic_sample_data": True}, "execution_allowed": False,
    }
    settings_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert load_config(settings_path.parent).data.allow_synthetic_sample_data is True
    bundle = load_settings_bundle(settings_root)
    candidate = bundle.model_copy(update={"controls": bundle.controls.model_copy(update={"horizon": "6M"})})
    saved = save_settings(candidate, expected_revision=bundle.revision, root=settings_root)
    assert saved.saved
    assert load_config(settings_path.parent).data.allow_synthetic_sample_data is True


def test_missing_sample_prices_default_disabled_reports_unavailable_without_writes(tmp_path, monkeypatch) -> None:
    from etf_cockpit.application.data_service import DataService
    from etf_cockpit.core.config import load_config
    from etf_cockpit.data import duckdb_store, sample_data

    config = load_config()
    assert config.data.allow_synthetic_sample_data is False
    monkeypatch.setattr(sample_data, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sample_data, "PORTFOLIOS_DIR", tmp_path / "portfolios")
    monkeypatch.setattr(duckdb_store, "PRICE_PARQUET", tmp_path / "prices.parquet")
    monkeypatch.setattr(duckdb_store, "HOLDINGS_CSV", tmp_path / "portfolios" / "current_holdings.csv")
    monkeypatch.setattr(duckdb_store, "load_config", lambda: config)
    monkeypatch.setattr(sample_data, "ensure_project_dirs", lambda: pytest.fail("generation attempted"))
    price_path, holdings_path = sample_data.ensure_sample_files(config, force=True)
    service = DataService(config)
    service.update_prices(force_sample=True)
    assert not price_path.exists()
    assert not holdings_path.exists()
    assert list(tmp_path.iterdir()) == []
    assert service.last_operation_succeeded is False
    assert service.last_operation_status == "unavailable"
    assert service.last_operation_reason == "no price data; synthetic sample data disabled"
    prices = service.load_prices()
    assert prices.empty
    assert prices.attrs["status"] == "unavailable"
    assert prices.attrs["reason"] == service.last_operation_reason
    assert service.dry_run_update() == "unavailable: no price data; synthetic sample data disabled"
    assert duckdb_store.load_holdings().empty


@pytest.mark.parametrize("source", ["synthetic_sample", "sample_generator"])
def test_persisted_synthetic_prices_are_refused_at_consumption_when_disabled(tmp_path, monkeypatch, source) -> None:
    from etf_cockpit.core.config import load_config
    from etf_cockpit.data import duckdb_store, sample_data

    config = load_config()
    assert config.data.allow_synthetic_sample_data is False
    prices = sample_data.generate_sample_prices(config, periods=30, end_date=date(2026, 6, 26)).assign(source=source)
    raw = tmp_path / "raw"
    (raw / "prices").mkdir(parents=True)
    prices.to_csv(raw / "prices" / "sample_prices.csv", index=False)
    monkeypatch.setattr(sample_data, "RAW_DIR", raw)
    monkeypatch.setattr(sample_data, "PORTFOLIOS_DIR", tmp_path / "portfolios")
    parquet = tmp_path / "validated" / "prices_daily.parquet"
    monkeypatch.setattr(duckdb_store, "PRICE_PARQUET", parquet)
    # Persisted CSV path: an existing synthetic CSV must not be promoted to the canonical store.
    duckdb_store.initialise_store(config)
    assert not parquet.exists()
    csv_view = duckdb_store.load_prices(config=config)
    assert csv_view.empty and csv_view.attrs["status"] == "unavailable"
    assert csv_view.attrs["reason"] == "no price data; synthetic sample data disabled"
    # Persisted parquet path: an existing synthetic canonical file must not be returned as evidence.
    duckdb_store.write_prices(prices, parquet)
    assert parquet.exists()
    view = duckdb_store.load_prices(config=config)
    assert view.empty and view.attrs["status"] == "unavailable"
    assert view.attrs["reason"] == "no price data; synthetic sample data disabled"
    opted_in = config.model_copy(deep=True)
    opted_in.data.allow_synthetic_sample_data = True
    assert not duckdb_store.load_prices(config=opted_in).empty


def test_active_config_blocks_synthetic_fallback_even_when_default_allows_it(tmp_path, monkeypatch) -> None:
    from etf_cockpit.application.data_service import DataService
    from etf_cockpit.core.config import load_config
    from etf_cockpit.data import duckdb_store, sample_data

    config = load_config()
    config.data.allow_synthetic_sample_data = False
    default = config.model_copy(deep=True)
    default.data.allow_synthetic_sample_data = True
    monkeypatch.setattr(duckdb_store, "load_config", lambda: default)
    monkeypatch.setattr(sample_data, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sample_data, "PORTFOLIOS_DIR", tmp_path / "portfolios")
    monkeypatch.setattr(duckdb_store, "PRICE_PARQUET", tmp_path / "prices.parquet")
    monkeypatch.setattr(duckdb_store, "HOLDINGS_CSV", tmp_path / "portfolios" / "current_holdings.csv")
    def generation_attempted(*_args):
        raise RuntimeError("synthetic fallback attempted")

    monkeypatch.setattr(sample_data, "generate_sample_prices", generation_attempted)
    service = DataService(config)
    service.update_prices(force_sample=True)
    assert service.last_operation_status == "unavailable"
    assert service.last_operation_succeeded is False
    assert service.last_operation_reason == "no price data; synthetic sample data disabled"
    assert service.load_prices().attrs["status"] == "unavailable"
    assert service.dry_run_update() == "unavailable: no price data; synthetic sample data disabled"
    assert service.run_yfinance_forecasts() == "No clean yfinance prices are available. Refresh yfinance data first."
    assert duckdb_store.load_prices(config=config).attrs["status"] == "unavailable"
    holdings = duckdb_store.load_holdings(config=config)
    assert holdings.empty and holdings.attrs["status"] == "unavailable"
    # Legacy callers without a config still use the configured default.
    with pytest.raises(RuntimeError, match="synthetic fallback attempted"):
        duckdb_store.load_holdings()
    # Exercise service holdings fallbacks with a real local price file present.
    pd.DataFrame({"etf_id": [config.universe.enabled_ids[0]], "date": ["2024-01-10"], "close": [100.0]}).to_parquet(
        duckdb_store.PRICE_PARQUET, index=False,
    )
    def holdings_read(*_args, **_kwargs):
        raise RuntimeError("holdings read")

    monkeypatch.setattr(service, "validate_prices", holdings_read)
    with pytest.raises(RuntimeError, match="holdings read"):
        service.dry_run_update()
    import etf_cockpit.application.data_service as service_module
    monkeypatch.setattr(service_module, "_benchmark_reference_snapshot_inputs", holdings_read)
    with pytest.raises(RuntimeError, match="holdings read"):
        service.run_yfinance_forecasts()
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "portfolios").exists()
