"""Build the point-in-time execution-cost-v1 round-trip table for rank validation (C1, owner 2026-11-25).

Usage: python scripts/build_pit_cost_table.py --root PATH --out FILE.parquet

Reads <root>/data/validated/prices/prices_daily.parquet and <root>/data/clean/fx.parquet (read-only), prices one
month-end row per instrument with the cost model (labelled cost_basis=reconstructed_model) and writes FILE.parquet
plus a FILE.json manifest with a sha256 in one atomic group. Pass FILE to run_rank_validation.py --costs.
execution_allowed stays false.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_PRICE_RELATIVE = Path("data") / "validated" / "prices" / "prices_daily.parquet"
_FX_RELATIVE = Path("data") / "clean" / "fx.parquet"


def build(root: Path, out: Path) -> dict[str, object]:
    """Write the table and its manifest; return the manifest."""

    import pandas as pd

    from etf_cockpit.application.score_backfill import research_reference_order_value_eur
    from etf_cockpit.core.atomic_io import AtomicWriteRequest, atomic_write_group
    from etf_cockpit.core.config import load_config
    from etf_cockpit.data.fx_data import load_fx_rates
    from etf_cockpit.data.provenance import sha256_dataframe
    from etf_cockpit.portfolio import cost_table

    prices_path, fx_path = root / _PRICE_RELATIVE, root / _FX_RELATIVE
    prices = pd.read_parquet(  # ids and currencies as categories: the store has ~5M rows
        prices_path, columns=["etf_id", "date", "close", "adjusted_close", "volume", "currency"],
        read_dictionary=["etf_id", "currency"],
    )
    order_value = research_reference_order_value_eur(root)
    table, skipped = cost_table.build_pit_cost_table(prices, load_fx_rates(fx_path), load_config(), order_value_eur=order_value)
    manifest = {
        "source_hash": sha256_dataframe(table), "rows": len(table), "instruments": int(table["instrument_id"].nunique()),
        "first_known_at": table["known_at"].min() if len(table) else None,
        "last_known_at": table["known_at"].max() if len(table) else None,
        "cost_model_id": cost_table.COST_MODEL_ID, "cost_basis": cost_table.COST_BASIS, "cadence": "month_end_session",
        "order_value_eur": order_value, "adv_window_sessions": cost_table.ADV_WINDOW,
        "volatility_window_sessions": cost_table.VOLATILITY_WINDOW, "skipped_month_ends": skipped,
        "prices": str(prices_path), "prices_rows": len(prices), "fx": str(fx_path), "execution_allowed": False,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    table.to_parquet(buffer, index=False)
    atomic_write_group([
        AtomicWriteRequest(out, buffer.getvalue(), lambda path: pd.read_parquet(path)),
        AtomicWriteRequest(out.with_suffix(".json"), json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
                           lambda path: json.loads(path.read_text(encoding="utf-8"))),
    ])
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="data root (defaults to ETF_COCKPIT_ROOT)")
    parser.add_argument("--out", type=Path, required=True, help="table destination (.parquet); the manifest goes beside it")
    args = parser.parse_args(argv)
    if not args.root:
        parser.error("--root (or ETF_COCKPIT_ROOT) is required")
    if args.out.suffix.lower() != ".parquet":
        parser.error("--out must be a .parquet file")
    manifest = build(Path(args.root).resolve(), args.out.resolve())
    print(f"cost table written: {args.out} rows={manifest['rows']} instruments={manifest['instruments']} "
          f"skipped={manifest['skipped_month_ends']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
