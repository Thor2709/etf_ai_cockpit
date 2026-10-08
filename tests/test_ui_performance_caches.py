"""Performance caches keep results identical and parse each distinct input only once."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import flet as ft
import numpy as np
import pandas as pd
import pytest
import yaml

from etf_cockpit.analysis.decision import domains, etf, opportunity, rank_validation, stock
from etf_cockpit.app.components.kit import data as kit_data
from etf_cockpit.app.components.kit.data import DataTable, TableColumn
from etf_cockpit.core import settings_bundle
from etf_cockpit.features import crowding

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "configs" / "decision_domains_v1.yaml"


@pytest.fixture
def parse_counter(monkeypatch):
    calls = {"n": 0}
    real = yaml.safe_load

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(yaml, "safe_load", counting)
    return calls


def test_domain_registry_parses_once_per_content_and_equals_a_fresh_parse(parse_counter) -> None:
    domains._domain_registry_for_content.cache_clear()
    first = domains.load_domain_registry(REGISTRY)
    again = domains.load_domain_registry(REGISTRY)
    assert parse_counter["n"] == 1
    assert first is again
    assert first == domains._domain_registry_for_content.__wrapped__(REGISTRY.read_bytes())


def test_domain_registry_cache_follows_file_content_and_never_caches_failures(tmp_path) -> None:
    domains._domain_registry_for_content.cache_clear()
    path = tmp_path / "registry.yaml"
    path.write_bytes(REGISTRY.read_bytes())
    original = domains.load_domain_registry(path)
    path.write_text("not: a registry\n", encoding="utf-8")
    for _ in range(2):  # the failure is raised every time, not cached as a value
        with pytest.raises(ValueError):
            domains.load_domain_registry(path)
    path.write_bytes(REGISTRY.read_bytes() + b"\n# comment\n")
    edited = domains.load_domain_registry(path)
    assert edited.metrics == original.metrics
    assert edited.checksum != original.checksum  # new content -> new parse, nothing stale


def test_other_decision_loaders_parse_once_per_content(parse_counter) -> None:
    stock._stock_decision_map_for_content.cache_clear()
    etf._etf_registries_for_content.cache_clear()
    opportunity._opportunity_policy_for_content.cache_clear()
    first_stock = stock.load_stock_decision_map(REGISTRY)
    first_etf = etf._load_etf_registries(REGISTRY)
    first_policy = opportunity.load_opportunity_policy()
    parsed = parse_counter["n"]
    assert parsed == 3
    for _ in range(3):
        assert stock.load_stock_decision_map(REGISTRY) is first_stock
        assert etf._load_etf_registries(REGISTRY) is first_etf
        assert opportunity.load_opportunity_policy() is first_policy
    assert parse_counter["n"] == parsed
    assert first_stock == stock._stock_decision_map_for_content.__wrapped__(REGISTRY.read_bytes())


def test_rank_cutover_is_unchanged_parses_once_and_returns_private_record(parse_counter) -> None:
    rank_validation._rank_validation_policy_for_content.cache_clear()
    rank_validation._parsed_rank_cutover.cache_clear()
    first = rank_validation.resolve_rank_cutover()
    parsed = parse_counter["n"]
    assert parsed == 2  # policy + domain config
    assert rank_validation.resolve_rank_cutover() == first
    assert parse_counter["n"] == parsed
    text = REGISTRY.read_text(encoding="utf-8")
    assert first.enabled is yaml.safe_load(text)["rank_cutover"]["enabled"]
    _enabled, record = rank_validation._configured_rank_cutover(text)
    if isinstance(record, dict):
        record["tampered"] = True
        assert "tampered" not in rank_validation._configured_rank_cutover(text)[1]


def test_rank_cutover_missing_config_still_fails_closed_to_v3(tmp_path) -> None:
    result = rank_validation.resolve_rank_cutover(domain_config_path=tmp_path / "missing.yaml")
    assert (result.enabled, result.active, result.ranker, result.reason) == (
        False,
        False,
        "v3",
        "cutover_config_unavailable",
    )


def test_settings_yaml_reads_are_cached_by_text_and_copied(tmp_path, parse_counter) -> None:
    settings_bundle._parse_yaml_text.cache_clear()
    path = tmp_path / "s.yaml"
    path.write_text("a: 1\nb: [1, 2]\n", encoding="utf-8")
    first = settings_bundle._read_yaml(path)
    first["b"].append(3)  # a caller mutating its copy must not leak into the cache
    second = settings_bundle._read_yaml(path)
    assert second == {"a": 1, "b": [1, 2]}
    assert parse_counter["n"] == 1
    path.write_text("a: 2\n", encoding="utf-8")
    assert settings_bundle._read_yaml(path) == {"a": 2}


def _prices_with_gaps(columns: int = 7, rows: int = 130, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.01, (rows, columns)), axis=0)),
        index=pd.bdate_range("2024-01-01", periods=rows),
        columns=[f"I{i}" for i in range(columns)],
    )
    return frame.mask(rng.random(frame.shape) < 0.1)


def test_pair_counts_match_the_per_pair_dropna_definition() -> None:
    returns = _prices_with_gaps().pct_change(fill_method=None)
    counts = crowding._pair_observation_counts(returns)
    assert counts is not None
    for left in returns.columns:
        for right in returns.columns:
            if left != right:
                assert counts.loc[left, right] == returns[[left, right]].dropna().shape[0]


def test_pair_counts_fall_back_when_column_labels_repeat() -> None:
    returns = pd.DataFrame([[1.0, 2.0], [None, 3.0]], columns=["A", "A"])
    assert crowding._pair_observation_counts(returns) is None


def test_correlation_clusters_do_not_slice_a_frame_per_pair(monkeypatch) -> None:
    prices = _prices_with_gaps(columns=9)
    report = crowding.build_correlation_clusters(prices, window=120)
    assert report.status == "available"
    calls = {"n": 0}
    real = pd.DataFrame.dropna

    def counting(self, *args, **kwargs):
        calls["n"] += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "dropna", counting)
    assert crowding.build_correlation_clusters(prices, window=120) == report
    assert calls["n"] <= 3  # frame clean-up only, not one dropna per instrument pair


def _table(count: int, **kwargs) -> ft.Control:
    columns = [TableColumn("name", "Name"), TableColumn("value", "Value", numeric=True)]
    rows = [{"name": f"row-{index}", "value": index} for index in range(count)]
    return DataTable(columns, rows, **kwargs)


def _body(table: ft.Control) -> ft.ListView:
    scroller = table.controls[1]
    return scroller.controls[0] if isinstance(scroller, ft.Stack) else scroller


def test_small_tables_are_unchanged_and_large_tables_materialise_a_window() -> None:
    assert len(_body(_table(12)).controls) == 12
    large = _table(kit_data.INITIAL_ROWS * 5)
    assert large.data["rows"] == kit_data.INITIAL_ROWS * 5
    assert len(_body(large).controls) == kit_data.INITIAL_ROWS


def test_scrolling_to_the_end_appends_the_next_chunk_in_order() -> None:
    total = kit_data.INITIAL_ROWS + kit_data.ROW_CHUNK + 37
    body = _body(_table(total))
    top = SimpleNamespace(pixels=0.0, max_scroll_extent=10_000.0)
    end = SimpleNamespace(pixels=9_999.0, max_scroll_extent=10_000.0)
    body.on_scroll(top)
    assert len(body.controls) == kit_data.INITIAL_ROWS  # nothing loads far from the end
    body.on_scroll(end)
    assert len(body.controls) == kit_data.INITIAL_ROWS + kit_data.ROW_CHUNK
    body.on_scroll(end)
    body.on_scroll(end)  # idempotent once everything is loaded
    assert [row.data["index"] for row in body.controls] == list(range(total))
    eager = DataTable([TableColumn("name", "Name")], [{"name": f"row-{i}"} for i in range(total)])
    assert eager.data["rows"] == total


def test_appended_rows_have_the_same_content_as_the_first_window() -> None:
    body = _body(_table(kit_data.INITIAL_ROWS * 2))
    body.on_scroll(SimpleNamespace(pixels=1.0, max_scroll_extent=1.0))
    texts = [
        [text.value for text in _walk_text(row)]
        for row in body.controls
    ]
    assert texts[0] == ["row-0", "0"]
    assert texts[kit_data.INITIAL_ROWS + 5] == [f"row-{kit_data.INITIAL_ROWS + 5}", str(kit_data.INITIAL_ROWS + 5)]


def _walk_text(control: ft.Control):
    if isinstance(control, ft.Text):
        yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk_text(content)
    for child in getattr(control, "controls", ()) or ():
        yield from _walk_text(child)


def test_selected_row_beyond_the_initial_window_is_materialised() -> None:
    table = _table(kit_data.INITIAL_ROWS * 3, selected_index=kit_data.INITIAL_ROWS + 50)
    body = _body(table)
    assert len(body.controls) == kit_data.INITIAL_ROWS + 51
    assert body.controls[kit_data.INITIAL_ROWS + 50].data["selected"] is True


def _reference_instrument_rows(frame: pd.DataFrame, instrument_id: str) -> pd.DataFrame:
    """The pre-optimisation row-wise definition, kept as the oracle."""

    from etf_cockpit.application import instrument_detail_view as view

    source = frame.copy()
    available = [column for column in view._CANONICAL_ID_COLUMNS if column in source.columns]
    target = view._normalise_identifier(instrument_id)
    identifiers = pd.DataFrame(
        {column: source[column].map(view._normalise_identifier) for column in available}, index=source.index
    )
    matches = identifiers.eq(target).any(axis=1)
    contradictory = identifiers.apply(
        lambda row: any(not view._is_missing_scalar(value) and value != target for value in row), axis=1
    )
    return source.loc[matches & ~contradictory].copy()


def _messy_identifier_frame() -> pd.DataFrame:
    values = ["VWCE", " VWCE ", "SXR8", None, np.nan, "", "  ", 7, "vwce", "EUNL"]
    rng = np.random.default_rng(11)
    count = 400
    return pd.DataFrame(
        {
            "instrument_id": [values[i] for i in rng.integers(0, len(values), count)],
            "etf_id": [values[i] for i in rng.integers(0, len(values), count)],
            "display_id": [values[i] for i in rng.integers(0, len(values), count)],
            "payload": np.arange(count),
        },
        index=pd.RangeIndex(1000, 1000 + count),
    )


@pytest.mark.parametrize("instrument_id", ["VWCE", "SXR8", "EUNL", "7", "unknown", "vwce"])
def test_instrument_rows_match_the_row_wise_definition(instrument_id) -> None:
    from etf_cockpit.application import instrument_detail_view as view

    frame = _messy_identifier_frame()
    fast = view._instrument_rows(frame, instrument_id)
    assert fast.equals(_reference_instrument_rows(frame, instrument_id))
    assert fast.index.equals(_reference_instrument_rows(frame, instrument_id).index)


def test_instrument_rows_normalise_identifier_columns_once_and_follow_content(monkeypatch) -> None:
    from etf_cockpit.application import instrument_detail_view as view

    view._IDENTIFIER_CACHE.clear()
    frame = _messy_identifier_frame()
    calls = {"n": 0}
    real = view._normalise_identifier

    def counting(value):
        calls["n"] += 1
        return real(value)

    monkeypatch.setattr(view, "_normalise_identifier", counting)
    view._instrument_rows(frame, "VWCE")
    after_first = calls["n"]
    for instrument_id in ("SXR8", "EUNL", "VWCE"):
        view._instrument_rows(frame, instrument_id)
    assert calls["n"] == after_first + 3  # only the target is normalised again, not 3 x 400 cells
    changed = frame.copy()
    changed.loc[changed.index[:5], "instrument_id"] = "VWCE"
    expected = _reference_instrument_rows(changed, "VWCE")
    monkeypatch.setattr(view, "_normalise_identifier", real)
    assert view._instrument_rows(changed, "VWCE").equals(expected)  # edited content is never served stale
    assert view._instrument_rows(frame, "VWCE").equals(_reference_instrument_rows(frame, "VWCE"))


def test_opportunity_artifact_is_parsed_once_across_instruments_and_results_are_private(tmp_path, monkeypatch) -> None:
    import json

    from etf_cockpit.application import decision_views

    decision_views._parsed_artifact.cache_clear()
    artifact = {
        "schema_version": 1,
        "artifact_version": "decision-opportunity-shadow-v1",
        "run_id": "run-1",
        "decision_time": "2024-01-01T23:59:59Z",
        "config_hashes": {"decision_domains_v1": "frozen"},
        "execution_allowed": False,
        "results": [
            {"instrument": name, "execution_allowed": False, "benchmark_rankers": [{"ranker": "v3", "score": 0.3}]}
            for name in ("AAA", "BBB", "CCC")
        ],
    }
    path = tmp_path / "decision_opportunity_run-1.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    calls = {"n": 0}
    real = json.loads

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(decision_views.json, "loads", counting)
    first = decision_views.load_opportunity_assessment("AAA", artifact_directory=tmp_path)
    for name in ("BBB", "CCC", "AAA"):
        assert decision_views.load_opportunity_assessment(name, artifact_directory=tmp_path)["instrument"] == name
    assert calls["n"] == 1
    assert first["v3_replay_score"] == 0.3 and first["run_id"] == "run-1"
    first["benchmark_rankers"][0]["score"] = 99  # mutating a result must not corrupt the shared parse
    assert decision_views.load_opportunity_assessment("AAA", artifact_directory=tmp_path)["v3_replay_score"] == 0.3
    artifact["run_id"] = "run-2"  # an edited artifact is re-read, never served stale
    path.write_text(json.dumps(artifact), encoding="utf-8")
    assert decision_views.load_opportunity_assessment("AAA", artifact_directory=tmp_path)["run_id"] == "run-2"


def _report_with_rows(rows: list) -> object:
    from etf_cockpit.backtest.engine import BacktestReport

    empty = pd.DataFrame()
    return BacktestReport(empty, empty, empty, empty, False, metadata={"operational_evidence_rows": rows})


def test_operational_evidence_frame_is_built_once_per_rows_list_and_copied() -> None:
    from collections.abc import Mapping

    reads = {"n": 0}

    class CountingRow(Mapping):
        def __init__(self, **values: object) -> None:
            self._values = values

        def __getitem__(self, key: str) -> object:
            return self._values[key]

        def __iter__(self):
            reads["n"] += 1
            return iter(self._values)

        def __len__(self) -> int:
            return len(self._values)

    rows = [CountingRow(instrument_id="AAA", execution_delay_sessions=1), CountingRow(instrument_id="BBB", execution_delay_sessions=None)]
    report = _report_with_rows(rows)
    first = report.operational_evidence
    built_reads = reads["n"]
    assert built_reads > 0
    assert first["instrument_id"].tolist() == ["AAA", "BBB"]
    assert first["execution_delay_sessions"].dtype == object
    assert first["execution_delay_sessions"].tolist() == [1, None]
    first.loc[0, "instrument_id"] = "tampered"  # a caller edit must not leak into later reads
    second = report.operational_evidence
    third = report.operational_evidence
    assert reads["n"] == built_reads  # rows were not re-read: the cached frame served both calls
    assert second["instrument_id"].tolist() == third["instrument_id"].tolist() == ["AAA", "BBB"]
    assert second is not third


def test_operational_evidence_follows_a_changed_rows_list() -> None:
    rows = [{"instrument_id": "AAA"}]
    report = _report_with_rows(rows)
    assert report.operational_evidence["instrument_id"].tolist() == ["AAA"]
    rows.append({"instrument_id": "BBB"})  # grown in place -> never stale
    assert report.operational_evidence["instrument_id"].tolist() == ["AAA", "BBB"]
    report.metadata["operational_evidence_rows"] = [{"instrument_id": "ZZZ"}]
    assert report.operational_evidence["instrument_id"].tolist() == ["ZZZ"]
    report.metadata["operational_evidence_rows"] = ["not-a-mapping"]
    assert report.operational_evidence.empty


def test_empty_statement_frame_is_a_fresh_copy_with_the_same_schema() -> None:
    from etf_cockpit.data import statement_normalisation as normalisation

    first = normalisation._empty_frame()
    schema = normalisation._build_empty_frame()
    assert list(first.columns) == list(schema.columns)
    assert first.dtypes.equals(schema.dtypes) and first.empty
    first["extra"] = []  # mutating one result must not change what the next caller gets
    first.loc[0, "instrument_id"] = "AAA"
    second = normalisation._empty_frame()
    assert second.empty and "extra" not in second.columns
    assert normalisation.normalise_statement_facts(pd.DataFrame()).equals(schema)


@pytest.mark.parametrize(
    "sources",
    [
        ["sample", "Sample data", "SAMPLE_GENERATOR"],
        ["sample", "yfinance"],
        ["yfinance", "yfinance"],
        ["sample", None],
        [None, np.nan],
        ["sample"],
    ],
)
def test_shell_sample_data_flag_matches_the_row_wise_definition(sources) -> None:
    from etf_cockpit.app.components.shell.status import _uses_sample

    prices = pd.DataFrame({"source": sources * 50, "adjusted_close": 1.0})
    expected = bool(prices["source"].astype(str).str.contains("sample", case=False).all())
    assert _uses_sample(SimpleNamespace(prices=prices)) is expected
    assert _uses_sample(SimpleNamespace(prices=prices.iloc[0:0])) is False
    assert _uses_sample(SimpleNamespace(prices=prices.drop(columns="source"))) is False


def _price_frame() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=30).strftime("%Y-%m-%d")
    rows = [
        {"date": day, "etf_id": etf, "adjusted_close": 100.0 + index + offset}
        for etf, offset in (("AAA", 0.0), ("BBB", 5.0))
        for index, day in enumerate(dates)
    ]
    return pd.DataFrame(rows)


_WINDOW = {"start_date": "2024-01-01", "end_date": "2024-02-09", "decision_time": "2024-02-09T21:00:00Z"}


def test_price_binding_is_memoised_on_content_and_equals_the_uncached_value(monkeypatch) -> None:
    from etf_cockpit.portfolio import benchmark_reference as reference

    reference._BINDING_CACHE.clear()
    prices = _price_frame()
    expected = reference._adjusted_price_snapshot_binding(prices, dict(_WINDOW))
    assert expected is not None
    clips = {"n": 0}
    real = reference.clip_to_decision_window

    def counting(*args, **kwargs):
        clips["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(reference, "clip_to_decision_window", counting)
    first = reference.adjusted_price_snapshot_binding(prices, calculation_window=_WINDOW)
    second = reference.adjusted_price_snapshot_binding(prices.copy(), calculation_window=_WINDOW)
    assert first == second == expected
    assert clips["n"] == 1  # the second (equal-content) call came from the memo
    second["calculation_window"]["end_date"] = "tampered"  # results are private copies
    assert reference.adjusted_price_snapshot_binding(prices, calculation_window=_WINDOW) == expected


def test_price_binding_follows_content_window_and_unavailable_results() -> None:
    from etf_cockpit.portfolio import benchmark_reference as reference

    reference._BINDING_CACHE.clear()
    prices = _price_frame()
    base = reference.adjusted_price_snapshot_binding(prices, calculation_window=_WINDOW)
    edited = prices.copy()
    edited.loc[3, "adjusted_close"] += 1.0
    changed = reference.adjusted_price_snapshot_binding(edited, calculation_window=_WINDOW)
    assert changed["price_snapshot_checksum"] != base["price_snapshot_checksum"]
    assert reference.adjusted_price_snapshot_binding(prices, calculation_window=_WINDOW) == base
    narrower = {**_WINDOW, "end_date": "2024-01-31", "decision_time": "2024-01-31T21:00:00Z"}
    assert reference.adjusted_price_snapshot_binding(prices, calculation_window=narrower)["price_snapshot_checksum"] != base["price_snapshot_checksum"]
    bad = prices.copy()
    bad.loc[0, "adjusted_close"] = -1.0
    for _ in range(2):  # unavailable stays unavailable (fail closed), cached or not
        assert reference.adjusted_price_snapshot_binding(bad, calculation_window=_WINDOW) is None
    assert reference.adjusted_price_snapshot_binding(prices.drop(columns="etf_id"), calculation_window=_WINDOW) is None


def test_price_binding_with_mixed_date_types_is_not_memoised() -> None:
    from etf_cockpit.portfolio import benchmark_reference as reference

    reference._BINDING_CACHE.clear()
    prices = _price_frame().astype({"date": object})
    prices.loc[0, "date"] = pd.Timestamp("2024-01-01")
    reference.adjusted_price_snapshot_binding(prices, calculation_window=_WINDOW)
    assert not reference._BINDING_CACHE
