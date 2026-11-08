from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

from etf_cockpit.data import universe_store, yfinance_provider
from etf_cockpit.data.universe_store import UniverseRecord, load_universe, save_universe
from scripts import resolve_universe_currency as resolver


class FakeLimiter:
    def __init__(self) -> None:
        self.calls = 0

    def acquire(self) -> None:
        self.calls += 1


def _record(instrument_id: str, ticker: str, *, currency: str = "EUR", enabled: bool = True) -> UniverseRecord:
    return UniverseRecord(
        instrument_id,
        instrument_id,
        isin_status="needs_verification",
        ticker=ticker,
        asset_type="stock",
        tier="secondary",
        enabled=enabled,
        data_policy="daily",
        currency=currency,
    )


def _seed(root: Path, *records: UniverseRecord):
    root.mkdir(parents=True, exist_ok=True)
    return save_universe(records, expected_revision="", root=root)


def _install_symbols(monkeypatch, mapping: Mapping[str, str]) -> None:
    monkeypatch.setattr(yfinance_provider, "yfinance_symbol_map_from_config", lambda _config: dict(mapping))


def _factory(responses: Mapping[str, object], calls: list[str] | None = None):
    seen = calls if calls is not None else []

    def make_ticker(symbol: str):
        seen.append(symbol)
        response = responses[symbol]

        class FakeTicker:
            @property
            def fast_info(self):
                if isinstance(response, BaseException):
                    raise response
                return response

        return FakeTicker()

    return make_ticker, seen


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _summary(capsys) -> dict[str, object]:
    output = capsys.readouterr().out.strip().splitlines()
    assert len(output) == 1
    return json.loads(output[-1])


def test_usd_symbol_stored_as_eur_resolves_to_edit(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "root"
    _seed(root, _record("USD1", "USD1"), _record("SKIP", "SKIP"))
    _install_symbols(monkeypatch, {"USD1": "USD1", "SKIP": "SKIP"})
    ticker_factory, calls = _factory({"USD1": {"currency": "USD"}, "SKIP": {"currency": "EUR"}})
    limiter = FakeLimiter()
    out = tmp_path / "currencies.csv"

    result = resolver.main(
        ["--root", str(root), "--out", str(out), "--ids", "USD1"],
        ticker_factory=ticker_factory,
        limiter=limiter,
    )

    assert result == 0
    row = _csv(out)[0]
    assert tuple(row) == resolver.CSV_FIELDS
    assert (row["action"], row["resolved_currency"]) == ("edit", "USD")
    assert calls == ["USD1"]
    assert limiter.calls == 1
    assert _summary(capsys)["actions"]["edit"] == 1


def test_minor_units_normalize_and_matching_currency_is_kept(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    root = tmp_path / "root"
    _seed(
        root,
        _record("GB", "GB"),
        _record("GBX", "GBX"),
        _record("IL", "IL"),
        _record("ZA", "ZA"),
        _record("SAME", "SAME", currency="USD"),
    )
    _install_symbols(monkeypatch, {"GB": "GB", "GBX": "GBX", "IL": "IL", "ZA": "ZA", "SAME": "SAME"})
    ticker_factory, _ = _factory({
        "GB": {"currency": "GBp"},
        "GBX": {"currency": "GBX"},
        "IL": {"currency": "ILA"},
        "ZA": {"currency": "ZAc"},
        "SAME": {"currency": "USD"},
    })
    out = tmp_path / "currencies.csv"

    assert resolver.main(["--root", str(root), "--out", str(out)], ticker_factory=ticker_factory, limiter=FakeLimiter()) == 0

    rows = {row["instrument_id"]: row for row in _csv(out)}
    assert (rows["GB"]["yahoo_currency_raw"], rows["GB"]["resolved_currency"]) == ("GBp", "GBP")
    assert rows["GBX"]["resolved_currency"] == "GBP"
    assert rows["IL"]["resolved_currency"] == "ILS"
    assert (rows["ZA"]["yahoo_currency_raw"], rows["ZA"]["resolved_currency"]) == ("ZAc", "ZAR")
    assert rows["SAME"]["action"] == "keep"
    assert rows["SAME"]["resolved_currency"] == "USD"
    assert _summary(capsys)["resolved_currencies"] == {"GBP": 2, "ILS": 1, "USD": 1, "ZAR": 1}


def test_missing_currency_and_not_found_are_disabled(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "root"
    _seed(root, _record("EMPTY", "EMPTY"), _record("GONE", "GONE"))
    _install_symbols(monkeypatch, {"EMPTY": "EMPTY", "GONE": "GONE"})
    ticker_factory, _ = _factory({
        "EMPTY": {},
        "GONE": RuntimeError("404 not found"),
    })
    out = tmp_path / "currencies.csv"

    assert resolver.main(["--root", str(root), "--out", str(out)], ticker_factory=ticker_factory, limiter=FakeLimiter()) == 0

    rows = {row["instrument_id"]: row for row in _csv(out)}
    assert rows["EMPTY"]["action"] == "disable"
    assert rows["EMPTY"]["reason"] == "currency_unavailable"
    assert rows["GONE"]["action"] == "disable"
    assert rows["GONE"]["reason"] == "not_found"
    assert _summary(capsys)["actions"]["disable"] == 2


def test_transient_errors_and_missing_symbol_retry_without_changes_on_commit(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    root = tmp_path / "root"
    initial = _seed(root, _record("THROTTLED", "THROTTLED"), _record("TIMEOUT", "TIMEOUT"), _record("NO_SYMBOL", "NO_SYMBOL"))
    _install_symbols(monkeypatch, {"THROTTLED": "THROTTLED", "TIMEOUT": "TIMEOUT"})
    ticker_factory, calls = _factory({
        "THROTTLED": RuntimeError("429 Too Many Requests"),
        "TIMEOUT": TimeoutError("request timed out"),
    })
    store_path = root / "configs" / "universe_store.json"
    before = store_path.read_bytes()
    out = tmp_path / "currencies.csv"

    result = resolver.main(
        ["--root", str(root), "--out", str(out), "--commit"],
        ticker_factory=ticker_factory,
        limiter=FakeLimiter(),
    )

    assert result == 3
    rows = {row["instrument_id"]: row for row in _csv(out)}
    assert {key: row["action"] for key, row in rows.items()} == {
        "THROTTLED": "retry",
        "TIMEOUT": "retry",
        "NO_SYMBOL": "retry",
    }
    assert rows["NO_SYMBOL"]["reason"] == "no_symbol"
    assert calls == ["THROTTLED", "TIMEOUT"]
    assert store_path.read_bytes() == before
    assert load_universe(root).revision == initial.revision
    assert _summary(capsys)["actions"]["retry"] == 3


def test_fast_info_key_error_retries_without_changes_on_commit(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    root = tmp_path / "root"
    initial = _seed(root, _record("BROKEN", "BROKEN"))
    _install_symbols(monkeypatch, {"BROKEN": "BROKEN"})
    ticker_factory, _ = _factory({"BROKEN": KeyError("currentTradingPeriod")})
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    out = tmp_path / "currencies.csv"

    result = resolver.main(
        ["--root", str(root), "--out", str(out), "--commit"],
        ticker_factory=ticker_factory,
        limiter=FakeLimiter(),
    )

    assert result == 3
    row = _csv(out)[0]
    assert (row["action"], row["reason"]) == ("retry", "error")
    assert load_universe(root).revision == initial.revision
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    summary = _summary(capsys)
    assert summary["actions"]["retry"] == 1
    assert summary["backup_path"] is None


def test_fast_info_without_currency_is_disabled_on_commit(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    root = tmp_path / "root"
    _seed(root, _record("EMPTY", "EMPTY"))
    _install_symbols(monkeypatch, {"EMPTY": "EMPTY"})
    ticker_factory, _ = _factory({"EMPTY": {}})
    out = tmp_path / "currencies.csv"

    result = resolver.main(
        ["--root", str(root), "--out", str(out), "--commit"],
        ticker_factory=ticker_factory,
        limiter=FakeLimiter(),
    )

    assert result == 0
    row = _csv(out)[0]
    assert (row["action"], row["reason"]) == ("disable", "currency_unavailable")
    saved = load_universe(root).records[0]
    assert saved.enabled is False
    assert saved.currency == "EUR"
    assert _summary(capsys)["actions"]["disable"] == 1


def test_commit_saves_once_with_start_revision_and_backup(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    root = tmp_path / "root"
    initial = _seed(root, _record("USD", "USD"), _record("EMPTY", "EMPTY"), _record("SAME", "SAME"))
    _install_symbols(monkeypatch, {"USD": "USD", "EMPTY": "EMPTY", "SAME": "SAME"})
    ticker_factory, _ = _factory({
        "USD": {"currency": "USD"},
        "EMPTY": {},
        "SAME": {"currency": "EUR"},
    })
    original_save = universe_store.save_universe
    calls: list[str] = []

    def save_spy(records, expected_revision, **kwargs):
        calls.append(expected_revision)
        return original_save(records, expected_revision, **kwargs)

    monkeypatch.setattr(universe_store, "save_universe", save_spy)
    out = tmp_path / "currencies.csv"

    result = resolver.main(
        ["--root", str(root), "--out", str(out), "--commit"],
        ticker_factory=ticker_factory,
        limiter=FakeLimiter(),
    )

    assert result == 0
    assert calls == [initial.revision]
    saved = load_universe(root)
    records = {record.instrument_id: record for record in saved.records}
    assert records["USD"].currency == "USD"
    assert records["EMPTY"].enabled is False
    assert records["SAME"].currency == "EUR"
    summary = _summary(capsys)
    assert summary["new_revision"] == saved.revision
    assert Path(summary["backup_path"]).exists()


def test_concurrent_universe_change_refuses_commit_without_partial_writes(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    root = tmp_path / "root"
    initial = _seed(root, _record("RACE", "RACE"))
    _install_symbols(monkeypatch, {"RACE": "RACE"})
    raced_bytes: list[bytes] = []
    original_save = universe_store.save_universe

    def racing_factory(symbol: str):
        current = load_universe(root)
        concurrent = universe_store.edit_record(current.records, "RACE", name="Concurrent update")
        original_save(concurrent, current.revision, root=root)
        raced_bytes.append((root / "configs" / "universe_store.json").read_bytes())

        class FakeTicker:
            fast_info = {"currency": "USD"}

        return FakeTicker()

    out = tmp_path / "currencies.csv"
    result = resolver.main(
        ["--root", str(root), "--out", str(out), "--commit"],
        ticker_factory=racing_factory,
        limiter=FakeLimiter(),
    )

    assert result == 2
    assert raced_bytes
    assert (root / "configs" / "universe_store.json").read_bytes() == raced_bytes[-1]
    current = load_universe(root)
    assert current.revision != initial.revision
    assert current.records[0].name == "Concurrent update"
    assert current.records[0].currency == "EUR"
    assert _summary(capsys)["save_error"].startswith("UniverseRevisionConflict:")


def test_noop_commit_refuses_changed_revision_without_writes(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    root = tmp_path / "root"
    initial = _seed(root, _record("RACE", "RACE"))
    _install_symbols(monkeypatch, {"RACE": "RACE"})
    concurrent_files: dict[Path, bytes] = {}
    original_save = universe_store.save_universe
    save_calls: list[str] = []

    def save_spy(records, expected_revision, **kwargs):
        save_calls.append(expected_revision)
        return original_save(records, expected_revision, **kwargs)

    monkeypatch.setattr(universe_store, "save_universe", save_spy)

    def racing_factory(symbol: str):
        current = load_universe(root)
        concurrent = universe_store.edit_record(current.records, "RACE", name="Concurrent update")
        original_save(concurrent, current.revision, root=root)
        concurrent_files.update(
            {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
        )
        return SimpleNamespace(fast_info={"currency": "EUR"})

    out = tmp_path / "currencies.csv"
    result = resolver.main(
        ["--root", str(root), "--out", str(out), "--commit"],
        ticker_factory=racing_factory,
        limiter=FakeLimiter(),
    )

    assert result == 2
    assert _csv(out)[0]["action"] == "keep"
    assert save_calls == []
    assert concurrent_files
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == concurrent_files
    current = load_universe(root)
    assert current.revision != initial.revision
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["save_error"].startswith("UniverseRevisionConflict:")
    assert initial.revision in captured.err
    assert current.revision in captured.err
    assert "universe save refused" in captured.err


def test_invalid_universe_validation_refuses_commit(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "root"
    _seed(root, _record("INVALID", "INVALID"))
    _install_symbols(monkeypatch, {"INVALID": "INVALID"})
    ticker_factory, _ = _factory({"INVALID": {"currency": "USD"}})
    store_path = root / "configs" / "universe_store.json"
    before = store_path.read_bytes()
    original_save = universe_store.save_universe
    save_calls: list[str] = []

    def prepare_invalid_commit(symbol: str):
        monkeypatch.setattr(universe_store, "edit_record", lambda records, *_args, **_kwargs: tuple(records))
        monkeypatch.setattr(
            universe_store,
            "validate_universe",
            lambda *_args, **_kwargs: SimpleNamespace(valid=False, errors=("currency rejected",)),
        )

        def save_spy(records, expected_revision, **kwargs):
            save_calls.append(expected_revision)
            return original_save(records, expected_revision, **kwargs)

        monkeypatch.setattr(universe_store, "save_universe", save_spy)

        class FakeTicker:
            fast_info = {"currency": "USD"}

        return FakeTicker()

    out = tmp_path / "currencies.csv"
    result = resolver.main(
        ["--root", str(root), "--out", str(out), "--commit"],
        ticker_factory=prepare_invalid_commit,
        limiter=FakeLimiter(),
    )

    assert result == 2
    assert save_calls == []
    assert store_path.read_bytes() == before
    assert _summary(capsys)["save_error"].endswith("currency rejected")


def test_without_commit_writes_only_csv(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    _seed(root, _record("USD", "USD"))
    _install_symbols(monkeypatch, {"USD": "USD"})
    ticker_factory, _ = _factory({"USD": {"currency": "USD"}})
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    out = tmp_path / "currencies.csv"

    assert resolver.main(["--root", str(root), "--out", str(out)], ticker_factory=ticker_factory, limiter=FakeLimiter()) == 0

    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert after == before
    assert out.exists()


def test_yaml_universe_records_can_be_corrected_through_canonical_save(
    tmp_path: Path, monkeypatch,
) -> None:
    root = tmp_path / "root"
    configs = root / "configs"
    configs.mkdir(parents=True)
    (configs / "universe.yaml").write_text(
        "schema_version: 1\netfs:\n"
        "  - id: LEGACY\n    name: Legacy\n    ticker: LEGACY\n"
        "    isin: needs_verification\n    analysis_tier: secondary\n"
        "    enabled: true\n    instrument_type: stock\n    data_policy: daily\n"
        "    currency: EUR\n",
        encoding="utf-8",
    )
    _install_symbols(monkeypatch, {"LEGACY": "LEGACY"})
    ticker_factory, _ = _factory({"LEGACY": {"currency": "USD"}})
    out = tmp_path / "currencies.csv"

    assert resolver.main(
        ["--root", str(root), "--out", str(out), "--commit"],
        ticker_factory=ticker_factory,
        limiter=FakeLimiter(),
    ) == 0

    saved = load_universe(root)
    assert len(saved.records) == 1
    assert saved.records[0].currency == "USD"
