"""Read-only rank validation runner over stored point-in-time data (DA-005 safe point).

Builds momentum/risk evidence from stored adjusted closes (and, when supplied,
point-in-time quality/value/v3 scores), replays frozen ranks over 1/3/5-year
windows, and prints a report: rank-IC, deciles, Top/Bottom net of cost, with a
terminal holdout fixed from decision dates before any metric is computed.

The runner only reads.  It never changes settings, the cutover flag, a champion
or a promotion record, and it never fills missing history: windows without
sufficient point-in-time data are reported as insufficient.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "app" / "src"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

from etf_cockpit.core.paths import CONFIG_DIR  # noqa: E402 - imports follow the sys.path bootstrap above

_PRICE_RELATIVE = Path("data") / "validated" / "prices" / "prices_daily.parquet"
_DEFAULT_SCOPE = "listing:euronext_oslo:all"
_DESKTOP_TREE = Path("C:/Users/thor2/Desktop/Trading App")
_PROTECTED_PARTS = {".owner-root", "models"}


def output_refusal(target: Path, inputs: Sequence[Path | None]) -> str | None:
    """Reason a report destination is refused, else ``None`` (checked before any build or write).

    Refused: configs/, any ``.owner-root`` or ``models`` directory, the owner
    Desktop tree, a non-``.json`` name, any input table, and any existing file
    that is not a previous rank-validation report (it may hold champion state).
    """

    resolved = target.resolve()
    if resolved.is_relative_to(CONFIG_DIR.resolve()):
        return "refusing to write a report into the configuration directory"
    if resolved.is_relative_to(_DESKTOP_TREE.resolve()):
        return "refusing to write a report into the owner Desktop tree"
    if any(part.casefold() in _PROTECTED_PARTS for part in resolved.parts):
        return "refusing to write a report under a protected .owner-root or models directory"
    if resolved.suffix.lower() != ".json":
        return "the report destination must be a .json file"
    if any(item is not None and item.resolve() == resolved for item in inputs):
        return "refusing to overwrite an input table with the report"
    if resolved.exists():
        try:
            previous = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None
        if not isinstance(previous, dict) or previous.get("kind") != "rank_validation_report":
            return "refusing to overwrite an existing file that is not a rank validation report"
    return None


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_report(args: argparse.Namespace) -> dict[str, object]:
    from etf_cockpit.application.rank_validation_service import build_rank_validation_report

    return build_rank_validation_report(
        root=args.root, years=args.years, scope=args.scope, benchmark_id=args.benchmark_id,
        prices_path=args.prices, membership_path=args.membership, costs_path=args.costs,
        cash_path=args.cash, fundamentals_path=args.fundamentals,
    )


def _summary(report: dict[str, object]) -> str:
    lines = [f"rank validation ({report.get('status')}); promotion_applied=false rank_authority=false"]
    if report.get("reason"):
        lines.append(f"reason: {report['reason']}")
    for window in report.get("windows", []):  # type: ignore[union-attr]
        lines.append(
            f"{window['requested_years']}y: {window.get('status')}, {window['decision_times']} decision times, "
            f"{window['excluded_decision_times']} excluded"
            + (f" - {window['reason']} (covered {window['coverage'].get('covered_years')}y)" if window.get("reason") else "")
        )
        for name, section in window["sections"].items():
            lines.append(f"  {name}: {section.get('status')} - {section.get('reason') or 'ok'}")
            for ranker, metrics in (section.get("holdout") or {}).items():
                lines.append(
                    f"    holdout {ranker}: status={metrics.get('status')} rank_ic={metrics.get('rank_ic_mean')} "
                    f"t={metrics.get('rank_ic_t')} top_net={metrics.get('top_net_return_mean')}"
                )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="project root holding the stored data")
    parser.add_argument("--years", type=int, nargs="+", default=[1, 3, 5], help="window lengths in years (default 1 3 5)")
    parser.add_argument("--prices", type=Path, help="override stored adjusted-close table")
    parser.add_argument("--membership", type=Path, help="override stored PIT membership frame")
    parser.add_argument("--scope", default=_DEFAULT_SCOPE, help="stored membership capture scope")
    parser.add_argument("--costs", type=Path, help="PIT execution-cost-v1 round-trip bps table")
    parser.add_argument("--cash", type=Path, help="cash forward-return table (decision_date, net_return)")
    parser.add_argument("--fundamentals", type=Path, help="PIT quality/value/v3 score table; absent = unavailable")
    parser.add_argument("--benchmark-id", help="stored instrument used as the benchmark comparator")
    parser.add_argument("--out", type=Path, help="write the JSON report here")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if any(item <= 0 for item in args.years):
        print("--years values must be positive", file=sys.stderr)
        return 2
    if args.out is not None:
        stored_prices = args.prices if args.prices is not None else args.root.resolve() / _PRICE_RELATIVE
        refusal = output_refusal(
            args.out, [stored_prices, args.membership, args.costs, args.cash, args.fundamentals]
        )
        if refusal is not None:
            print(refusal, file=sys.stderr)
            return 2
    report = build_report(args)
    print(_summary(report))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(_json_safe(report), indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
