from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import yaml

import pytest
import pandas as pd

from etf_cockpit.data.fixed_income_market_data import (
    BondLiquidityObservation,
    FixedIncomeMarketDataError,
    FixedIncomeMarketDataSchemaError,
    FixedIncomeMarketDataStore,
    FixedIncomeMarketObservation,
    ProviderCoverage,
    read_provider_coverage,
    write_provider_coverage,
)
from etf_cockpit.plugins.builtins import default_plugin_registry
from etf_cockpit.application.api import LocalApplicationApi
from etf_cockpit.application.ui_facade import (
    load_fixed_income_market_data_projection,
)


NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64


def _observation(**changes: object) -> FixedIncomeMarketObservation:
    base: dict[str, object] = {
        "instrument_id": "bond-1",
        "provider_id": "manual_local",
        "observation_type": "price",
        "market": "OTC",
        "currency": "EUR",
        "valid_at": NOW,
        "known_at": NOW + timedelta(hours=1),
        "retrieved_at": NOW + timedelta(hours=2),
        "source_checksum": SHA_A,
        "raw_checksum": SHA_B,
        "values": {"clean_price": "99.25"},
    }
    base.update(changes)
    return FixedIncomeMarketObservation(**base)


def test_point_in_time_cutoff_revision_and_provider_conflict_are_preserved(tmp_path: Path) -> None:
    first = _observation()
    revision = replace(
        first,
        revision=2,
        known_at=NOW + timedelta(days=1),
        retrieved_at=NOW + timedelta(days=1, hours=1),
        values={"clean_price": "100.00"},
    )
    other = replace(
        first,
        provider_id="other",
        source_checksum="c" * 64,
        raw_checksum="d" * 64,
        values={"clean_price": "98.00"},
    )
    with FixedIncomeMarketDataStore(tmp_path) as store:
        store.append((first, revision, other))
        early = store.resolve("bond-1", decision_time=NOW + timedelta(hours=3))
        assert {row["provider_id"] for row in early["observations"]} == {
            "manual_local",
            "other",
        }
        assert early["status"] == "conflicted"
        late = store.resolve("bond-1", decision_time=NOW + timedelta(days=2))
        local = next(
            row for row in late["observations"] if row["provider_id"] == "manual_local"
        )
        assert local["revision"] == 2
        assert len(late["history"]) == 3


def test_retry_is_idempotent_but_identity_content_collision_is_rejected(tmp_path: Path) -> None:
    item = _observation()
    with FixedIncomeMarketDataStore(tmp_path) as store:
        assert store.append((item,)) == store.append((item,))
        with pytest.raises(FixedIncomeMarketDataSchemaError):
            store.append((replace(item, values={"clean_price": "101"}),))
        with pytest.raises(FixedIncomeMarketDataError):
            store.append((replace(item, source_authority="self_asserted"),))
        assert len(store.history("bond-1")) == 1


def test_later_retrieval_is_distinct_and_not_visible_at_earlier_decision(tmp_path: Path) -> None:
    first = _observation()
    later = replace(
        first,
        known_at=first.known_at + timedelta(hours=2),
        retrieved_at=first.retrieved_at + timedelta(hours=2),
    )
    with FixedIncomeMarketDataStore(tmp_path) as store:
        store.append((first, later))
        assert len(store.history("bond-1")) == 2
        early = store.resolve(
            "bond-1", decision_time=first.retrieved_at + timedelta(minutes=1)
        )
    assert len(early["history"]) == 1
    assert early["observations"][0]["retrieved_at"] == first.retrieved_at.isoformat(
        timespec="microseconds"
    )


def test_concurrent_distinct_appends_do_not_lose_records(tmp_path: Path) -> None:
    items = tuple(
        replace(_observation(), instrument_id=f"bond-{index}") for index in range(8)
    )

    def append(item: FixedIncomeMarketObservation) -> None:
        with FixedIncomeMarketDataStore(tmp_path) as store:
            store.append((item,))

    with ThreadPoolExecutor(max_workers=4) as pool:
        tuple(pool.map(append, items))
    with FixedIncomeMarketDataStore(tmp_path) as store:
        assert sum(len(store.history(item.instrument_id)) for item in items) == 8


def test_manual_import_fails_closed_and_manual_local_succeeds(tmp_path: Path) -> None:
    legal_path = Path(__file__).parents[1] / "configs" / "legal_terms_registry.yaml"
    with FixedIncomeMarketDataStore(tmp_path) as store:
        with pytest.raises(FixedIncomeMarketDataError):
            store.import_manual_local((_observation(),))
        curve = replace(
            _observation(),
            instrument_id="curve-eur",
            observation_type="yield_curve",
            values={
                "curve_type": "government",
                "interpolation": "linear",
                "tenors": {"1Y": "0.02"},
            },
        )
        store.import_manual_local((curve,), legal_terms_path=legal_path)
        with pytest.raises(FixedIncomeMarketDataError):
            store.import_manual_local((_observation(),), legal_terms_path=legal_path)
        with pytest.raises(FixedIncomeMarketDataError):
            store.import_manual_local(
                (replace(_observation(), provider_id="ecb"),),
                legal_terms_path=legal_path,
            )


def test_disabled_fixed_income_plugins_are_visible_and_never_invoked() -> None:
    registry = default_plugin_registry()
    for plugin_id in (
        "fixed-income.ecb",
        "fixed-income.esma-firds-fitrs",
        "fixed-income.finra-trace",
    ):
        assert registry.health(plugin_id).status.value == "disabled"
        assert registry.invoke(plugin_id, "fetch").status == "unavailable"


def test_remote_fixed_income_provider_cannot_be_enabled_by_config(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "configs" / "plugin_registry.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    for row in payload["allowlist"]:
        if str(row["plugin_id"]).startswith("fixed-income."):
            row["enabled"] = True
    path = tmp_path / "plugins.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    registry = default_plugin_registry(path)
    for plugin_id in (
        "fixed-income.ecb",
        "fixed-income.esma-firds-fitrs",
        "fixed-income.finra-trace",
    ):
        assert registry.health(plugin_id).status.value == "disabled"
        assert registry.invoke(plugin_id, "fetch").status == "unavailable"


def test_missing_or_evaluated_liquidity_cannot_make_precise_claim(tmp_path: Path) -> None:
    liquidity = BondLiquidityObservation(
        instrument_id="bond-1",
        provider_id="manual_local",
        market="OTC",
        currency="EUR",
        valid_at=NOW,
        known_at=NOW,
        retrieved_at=NOW,
        source_checksum=SHA_A,
        raw_checksum=SHA_B,
        bid="99",
        ask=None,
        tape_available=False,
        quality_label="evaluated",
    )
    with FixedIncomeMarketDataStore(tmp_path) as store:
        store.append((liquidity,))
        result = store.resolve("bond-1")
    assert result["precise_liquidity_available"] is False
    assert result["execution_allowed"] is False
    assert result["observations"][0]["executable_claim_allowed"] is False


def test_types_resolve_independently_and_liquidity_conflicts_are_scoped(tmp_path: Path) -> None:
    price = replace(_observation(), clean_price="99.25")
    liquidity = replace(
        _observation(),
        observation_type="bond_liquidity",
        provider_id="liquidity-a",
        valid_at=NOW - timedelta(days=1),
        bid="99",
        ask="100",
        tape_available=True,
        evidence_label="executable",
    )
    with FixedIncomeMarketDataStore(tmp_path) as store:
        store.append((price, liquidity))
        mixed = store.resolve("bond-1", decision_time=NOW + timedelta(hours=3))
        assert {row["observation_type"] for row in mixed["observations"]} == {
            "price",
            "bond_liquidity",
        }
        assert mixed["status"] == "available"
        assert mixed["precise_liquidity_available"] is True
        store.append(
            (
                replace(
                    liquidity,
                    provider_id="liquidity-b",
                    source_checksum="c" * 64,
                    raw_checksum="d" * 64,
                    bid="98",
                ),
            )
        )
        conflicted = store.resolve("bond-1", decision_time=NOW + timedelta(hours=3))
    assert conflicted["status"] == "conflicted"
    assert conflicted["precise_liquidity_available"] is False


def test_price_only_never_claims_precise_liquidity(tmp_path: Path) -> None:
    with FixedIncomeMarketDataStore(tmp_path) as store:
        store.append((_observation(),))
        result = store.resolve("bond-1", decision_time=NOW + timedelta(hours=3))
    assert result["status"] == "available"
    assert result["precise_liquidity_available"] is False


def test_failed_batch_preserves_prior_and_unrelated_provider(tmp_path: Path) -> None:
    prior = _observation()
    unrelated = replace(prior, provider_id="other", source_checksum="c" * 64)
    with FixedIncomeMarketDataStore(tmp_path) as store:
        store.append((prior, unrelated))
        with pytest.raises(FixedIncomeMarketDataSchemaError):
            store.append(
                (
                    replace(prior, values={"clean_price": "changed"}),
                    replace(prior, instrument_id="bond-new"),
                )
            )
        assert len(store.history("bond-1")) == 2
        assert store.history("bond-new") == ()


def test_coverage_preserves_dimensions_denominators_and_lineage(tmp_path: Path) -> None:
    path = tmp_path / "fixed_income_provider_coverage.parquet"
    write_provider_coverage(
        path,
        (
            ProviderCoverage(
                provider_id="manual_local",
                as_of=NOW,
                source_checksum=SHA_A,
                raw_checksum=SHA_B,
                market_covered=2,
                market_total=4,
            ),
        ),
    )
    row = read_provider_coverage(path)[0]
    assert (row["market_covered"], row["market_total"]) == (2, 4)
    assert row["rating_status"] == "unavailable"
    assert row["source_checksum"] == SHA_A


def test_invalid_coverage_fails_closed_without_affecting_observations(tmp_path: Path) -> None:
    coverage = tmp_path / "data" / "market" / "fixed_income_provider_coverage.parquet"
    write_provider_coverage(
        coverage,
        (
            ProviderCoverage(
                provider_id="manual_local",
                as_of=NOW,
                source_checksum=SHA_A,
                raw_checksum=SHA_B,
                market_covered=1,
                market_total=2,
            ),
        ),
    )
    frame = pd.read_parquet(coverage)
    frame.loc[0, "market_status"] = "unavailable"
    frame.to_parquet(coverage, index=False)
    with FixedIncomeMarketDataStore(tmp_path) as store:
        store.append((_observation(),))
        result = store.resolve("bond-1", decision_time=NOW + timedelta(hours=3))
    assert result["provider_coverage"]["status"] == "unavailable"
    assert len(result["observations"]) == 1


def test_application_api_and_ui_facade_projections_are_identical(tmp_path: Path) -> None:
    with FixedIncomeMarketDataStore(tmp_path) as store:
        store.append((_observation(),))
    cutoff = NOW + timedelta(hours=3)
    api = LocalApplicationApi(lambda: object(), root=tmp_path)
    api_projection = api.get_fixed_income_market_data(
        "bond-1", decision_time=cutoff
    )
    facade_projection = load_fixed_income_market_data_projection(
        "bond-1", storage_root=tmp_path, decision_time=cutoff.isoformat()
    )
    assert api_projection == facade_projection
    assert api_projection["execution_allowed"] is False


def test_selector_and_page_expose_non_executable_market_data(monkeypatch) -> None:
    from etf_cockpit.app.pages import instrument_detail as page_module
    from etf_cockpit.app.selectors import instrument_detail as selector
    from etf_cockpit.services import build_snapshot

    projection = {
        "status": "available",
        "instrument_id": "VWCE",
        "observations": [],
        "provider_coverage": {"status": "unavailable", "rows": []},
        "execution_allowed": False,
    }
    monkeypatch.setattr(
        selector,
        "load_fixed_income_market_data_projection",
        lambda *_args, **_kwargs: projection,
    )
    snapshot = build_snapshot()
    model = selector.build_instrument_detail(snapshot, "VWCE")
    assert model.sections["fixed_income_market_data"] == projection
    monkeypatch.setattr(page_module, "build_instrument_detail", lambda *_args, **_kwargs: model)
    state = type("State", (), {"selected_etf": "VWCE", "snapshot": snapshot})()
    control = page_module.instrument_detail_page(None, state)

    def walk(item: object):
        yield item
        content = getattr(item, "content", None)
        if content is not None:
            yield from walk(content)
        for child in getattr(item, "controls", ()) or ():
            yield from walk(child)

    keyed = {
        getattr(item, "key", None): item
        for item in walk(control)
        if getattr(item, "key", None)
    }
    assert "instrument-detail.fixed-income-market-data" in keyed
    assert model.sections["fixed_income_market_data"]["execution_allowed"] is False
