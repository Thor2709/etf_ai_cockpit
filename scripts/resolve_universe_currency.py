"""Resolve enabled universe quote currencies from Yahoo and optionally save corrections."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping, Sequence


CSV_FIELDS = (
    "instrument_id",
    "symbol",
    "stored_currency",
    "yahoo_currency_raw",
    "resolved_currency",
    "action",
    "reason",
)
ACTION_NAMES = ("keep", "edit", "disable", "retry")
MINOR_UNIT_CURRENCY_CODES = {
    "GBp": "GBP",
    "GBX": "GBP",
    "ILA": "ILS",
    "ZAc": "ZAR",
}


def normalize_currency(currency: object) -> str | None:
    if currency is None:
        return None
    value = str(currency).strip()
    if not value:
        return None
    return MINOR_UNIT_CURRENCY_CODES.get(value, value.upper())


def lookup_yahoo_currency(
    symbol: str,
    *,
    ticker_factory: Callable[[str], Any],
    limiter: Any,
    classify_error: Callable[[Any], str],
) -> tuple[object | None, str | None]:
    """Read one Yahoo quote currency through an injected ticker and limiter."""

    try:
        limiter.acquire()
        ticker = ticker_factory(symbol)
        fast_info = ticker.fast_info
    except Exception as error:
        return None, classify_error(error)
    try:
        return fast_info["currency"], None
    except KeyError:
        return None, None
    except Exception as error:
        return None, classify_error(error)


def resolve_records(
    records: Iterable[Any],
    symbol_map: Mapping[str, str],
    *,
    ticker_factory: Callable[[str], Any],
    limiter: Any,
    classify_error: Callable[[Any], str],
    selected_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in records:
        instrument_id = str(record.instrument_id)
        if selected_ids is None and not record.enabled:
            continue
        if selected_ids is not None and instrument_id not in selected_ids:
            continue

        symbol = str(symbol_map.get(instrument_id) or "").strip()
        stored_currency = str(record.currency or "")
        row = {
            "instrument_id": instrument_id,
            "symbol": symbol,
            "stored_currency": stored_currency,
            "yahoo_currency_raw": "",
            "resolved_currency": "",
            "action": "retry",
            "reason": "no_symbol",
        }
        if not symbol:
            rows.append(row)
            continue

        raw_currency, error_class = lookup_yahoo_currency(
            symbol,
            ticker_factory=ticker_factory,
            limiter=limiter,
            classify_error=classify_error,
        )
        if error_class:
            if error_class == "not_found":
                row["action"] = "disable"
                row["reason"] = "not_found"
            else:
                row["action"] = "retry"
                row["reason"] = error_class if error_class in {"throttled", "timeout", "error"} else "error"
            rows.append(row)
            continue

        row["yahoo_currency_raw"] = "" if raw_currency is None else str(raw_currency)
        resolved_currency = normalize_currency(raw_currency) if raw_currency is not None else None
        if not resolved_currency:
            row["action"] = "disable"
            row["reason"] = "currency_unavailable"
        else:
            row["resolved_currency"] = resolved_currency
            if resolved_currency == stored_currency:
                row["action"] = "keep"
                row["reason"] = "currency_matches"
            else:
                row["action"] = "edit"
                row["reason"] = "currency_differs"
        rows.append(row)
    return rows


def _load_runtime(root: Path) -> dict[str, Any]:
    os.environ["ETF_COCKPIT_ROOT"] = str(root)
    source_root = Path(__file__).resolve().parents[1] / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

    from etf_cockpit.core.config import load_config
    from etf_cockpit.data import universe_store
    from etf_cockpit.data.retrieval_batch import provider_rate_limiter
    from etf_cockpit.data.yfinance_provider import (
        classify_provider_error,
        yfinance_symbol_map_from_config,
    )

    config = load_config(root / "configs")
    snapshot = universe_store.load_universe(root)
    if snapshot.integrity_errors:
        raise ValueError("universe integrity errors block currency resolution: " + "; ".join(snapshot.integrity_errors))
    records = snapshot.records
    legacy_path = root / "configs" / "universe.yaml"
    if not snapshot.path.exists() and legacy_path.is_file():
        records = universe_store.import_legacy_universe(legacy_path).records

    return {
        "snapshot": snapshot,
        "records": records,
        "symbol_map": yfinance_symbol_map_from_config(config),
        "allow_cross_tier_duplicates": (
            snapshot.allow_cross_tier_duplicates
            if snapshot.path.exists()
            else config.universe.allow_cross_tier_duplicates
        ),
        "store": universe_store,
        "classify_error": classify_provider_error,
        "limiter": provider_rate_limiter(
            "yfinance", max_calls_per_window=60, window_seconds=60.0
        ),
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _summary(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    counts = Counter(row["action"] for row in rows)
    currencies = Counter(row["resolved_currency"] for row in rows if row["resolved_currency"])
    return {
        "actions": {action: counts[action] for action in ACTION_NAMES},
        "resolved_currencies": dict(sorted(currencies.items())),
    }


def _commit_rows(
    rows: Sequence[Mapping[str, str]],
    records: Iterable[Any],
    *,
    root: Path,
    snapshot: Any,
    allow_cross_tier_duplicates: bool,
    store: Any,
) -> tuple[str, Path | None]:
    original = tuple(records)
    updated = original
    for row in rows:
        if row["action"] == "edit":
            updated = store.edit_record(
                updated,
                row["instrument_id"],
                currency=row["resolved_currency"],
                allow_cross_tier_duplicates=allow_cross_tier_duplicates,
            )
        elif row["action"] == "disable":
            updated = store.disable_record(
                updated,
                row["instrument_id"],
                allow_cross_tier_duplicates=allow_cross_tier_duplicates,
            )

    report = store.validate_universe(
        updated,
        allow_cross_tier_duplicates=allow_cross_tier_duplicates,
    )
    if not report.valid:
        raise ValueError("universe validation failed: " + "; ".join(report.errors))
    if updated == original:
        current_revision = store.load_universe(root).revision
        if current_revision != snapshot.revision:
            raise store.UniverseRevisionConflict(
                f"Expected revision {snapshot.revision or '<empty>'}, found {current_revision or '<empty>'}"
            )
        return snapshot.revision, None

    result = store.save_universe(
        updated,
        expected_revision=snapshot.revision,
        root=root,
        allow_cross_tier_duplicates=allow_cross_tier_duplicates,
        policy_profiles=snapshot.policy_profiles,
    )
    return result.revision, result.backup_path


def main(
    argv: Sequence[str] | None = None,
    *,
    ticker_factory: Callable[[str], Any] | None = None,
    limiter: Any | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ids", default="", help="comma separated instrument IDs")
    parser.add_argument("--commit", action="store_true", help="save currency corrections through the canonical universe store")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        previous_root = os.environ.get("ETF_COCKPIT_ROOT")
        previous_bytecode = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            runtime = _load_runtime(root)
            if ticker_factory is None:
                import yfinance as yf

                ticker_factory = yf.Ticker
        finally:
            sys.dont_write_bytecode = previous_bytecode
            if previous_root is None:
                os.environ.pop("ETF_COCKPIT_ROOT", None)
            else:
                os.environ["ETF_COCKPIT_ROOT"] = previous_root
        selected_ids = {item.strip() for item in args.ids.split(",") if item.strip()} or None
        rows = resolve_records(
            runtime["records"],
            runtime["symbol_map"],
            ticker_factory=ticker_factory,
            limiter=limiter if limiter is not None else runtime["limiter"],
            classify_error=runtime["classify_error"],
            selected_ids=selected_ids,
        )
        _write_csv(args.out, rows)
        summary = _summary(rows)
        if args.commit:
            try:
                revision, backup_path = _commit_rows(
                    rows,
                    runtime["records"],
                    root=root,
                    snapshot=runtime["snapshot"],
                    allow_cross_tier_duplicates=runtime["allow_cross_tier_duplicates"],
                    store=runtime["store"],
                )
                summary["new_revision"] = revision
                summary["backup_path"] = str(backup_path) if backup_path is not None else None
            except Exception as error:
                summary["save_error"] = f"{type(error).__name__}: {error}"
                print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
                print(f"universe save refused: {error}", file=sys.stderr)
                return 2
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 3 if summary["actions"]["retry"] else 0
    except Exception as error:
        print(f"currency resolution failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
