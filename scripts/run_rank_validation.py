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
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "src", ROOT / "app" / "src"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

from etf_cockpit.analysis.decision.rank_validation import (  # noqa: E402 - imports follow the sys.path bootstrap above
    attach_fundamental_evidence,
    forward_comparator_frame,
    load_rank_validation_policy,
    price_momentum_risk_evidence,
    rank_validation_report_dict,
    research_policy,
    run_stored_rank_validation,
    window_decision_times,
)
from etf_cockpit.core.paths import CONFIG_DIR  # noqa: E402 - imports follow the sys.path bootstrap above

_PRICE_RELATIVE = Path("data") / "validated" / "prices" / "prices_daily.parquet"
_DEFAULT_SCOPE = "listing:euronext_oslo:all"


def _read_table(path: Path | None) -> pd.DataFrame:
    if path is None or not path.is_file():
        return pd.DataFrame()
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)


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


def _load_membership(args: argparse.Namespace, root: Path, as_known_at: datetime) -> pd.DataFrame:
    if args.membership is not None:
        return _read_table(args.membership)
    from etf_cockpit.data.universe_membership import membership_frame

    return membership_frame(args.scope, as_known_at, root=root)


def build_report(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    prices = _read_table(args.prices if args.prices is not None else root / _PRICE_RELATIVE)
    costs = _read_table(args.costs)
    cash = _read_table(args.cash)
    fundamentals = _read_table(args.fundamentals)
    base_policy = load_rank_validation_policy()
    report: dict[str, object] = {
        "schema_version": 1,
        "kind": "rank_validation_report",
        "generated_for": "research_only",
        "policy_version": base_policy.version,
        "price_known_at_basis": "session_end_assumed_when_column_absent",
        "inputs": {
            "prices_rows": int(len(prices)),
            "costs_rows": int(len(costs)),
            "cash_rows": int(len(cash)),
            "fundamental_rows": int(len(fundamentals)),
            "benchmark_id": args.benchmark_id,
        },
        "windows": [],
        "promotion_applied": False,
        "rank_authority": False,
        "execution_allowed": False,
    }
    if prices.empty or not {"instrument_id", "date", "adjusted_close"}.issubset(prices.columns):
        report["status"] = "unavailable"
        report["reason"] = "stored adjusted-close history is unavailable"
        return report
    last_session = max(item for item in pd.to_datetime(prices["date"]).dt.date)
    as_known_at = datetime(last_session.year, last_session.month, last_session.day, 23, 59, 59, tzinfo=timezone.utc)
    memberships = _load_membership(args, root, as_known_at)
    report["inputs"]["membership_rows"] = int(len(memberships))  # type: ignore[index]
    first_session = min(item for item in pd.to_datetime(prices["date"]).dt.date)

    for years in args.years:
        times, excluded = window_decision_times(
            prices,
            years,
            step_sessions=base_policy.holding_period_sessions,
            holding_period_sessions=base_policy.holding_period_sessions,
        )
        evidence, skipped = price_momentum_risk_evidence(prices, times)
        benchmark = (
            forward_comparator_frame(prices, args.benchmark_id, times, base_policy.holding_period_sessions)
            if args.benchmark_id
            else pd.DataFrame()
        )
        window: dict[str, object] = {
            "requested_years": years,
            "first_price_date": first_session.isoformat(),
            "last_price_date": last_session.isoformat(),
            "decision_times": len(times),
            "excluded_decision_times": len(excluded),
            "instrument_skips": {key: len(value) for key, value in skipped.items()},
        }
        sections: dict[str, object] = {}
        runs = [("price_factors", research_policy(base_policy, fundamentals=False), evidence)]
        if fundamentals.empty:
            sections["fundamental_factors"] = {
                "status": "unavailable",
                "reason": "no point-in-time fundamentals evidence supplied; not filled",
            }
        else:
            runs.append(
                (
                    "fundamental_factors",
                    research_policy(base_policy, fundamentals=True),
                    attach_fundamental_evidence(evidence, fundamentals),
                )
            )
        for label, policy, run_evidence in runs:
            replay, validation = run_stored_rank_validation(
                run_evidence, memberships, prices, costs, benchmark, cash, times, policy=policy
            )
            sections[label] = rank_validation_report_dict(
                replay,
                validation,
                label=f"{label}_{years}y",
                requested_decision_times=times,
                excluded_decision_times=excluded,
            )
        window["sections"] = sections
        report["windows"].append(window)  # type: ignore[union-attr]
    report["status"] = "reported"
    return report


def _summary(report: dict[str, object]) -> str:
    lines = [f"rank validation ({report.get('status')}); promotion_applied=false rank_authority=false"]
    if report.get("reason"):
        lines.append(f"reason: {report['reason']}")
    for window in report.get("windows", []):  # type: ignore[union-attr]
        lines.append(f"{window['requested_years']}y: {window['decision_times']} decision times, {window['excluded_decision_times']} excluded")
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
        target = args.out.resolve()
        if target.is_relative_to(CONFIG_DIR.resolve()):
            print("refusing to write a report into the configuration directory", file=sys.stderr)
            return 2
    report = build_report(args)
    print(_summary(report))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(_json_safe(report), indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
