"""Audit of normal-stock coverage: score, coverage, missing components and every fundamental with its source.

Usage:
    ETF_COCKPIT_ROOT=<data root> python scripts/stock_coverage_audit.py --state before|after [--out docs/development/stock-coverage-2026-10.md]

``before`` documents the state with no fundamentals loader (every fundamental is reported with that
reason); ``after`` reads the canonical fundamentals store. Each state replaces only its own block in the
output file, so both stay in one document.
"""

from __future__ import annotations

import argparse
import re
import sys
import warnings
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))

BEFORE_REASON = (
    "no fundamentals source was wired: configured stocks used the placeholder "
    "`_configured_stock_fundamental_components` and no fundamentals store existed"
)
ROWS = (
    ("revenue", "Revenue"),
    ("net_income", "Net income (parent)"),
    ("ebit_margin", "EBIT margin"),
    ("net_margin", "Net margin"),
    ("roe", "ROE"),
    ("roic", "ROIC"),
    ("net_debt", "Net debt"),
    ("debt_to_equity", "Debt / equity"),
    ("fcf", "Free cash flow"),
    ("pe", "P/E"),
    ("ev_ebit", "EV / EBIT"),
    ("pb", "P/B"),
    ("dividend_yield", "Dividend yield"),
    ("revenue_cagr", "Revenue CAGR"),
)


def _fmt(metric) -> str:
    from etf_cockpit.analysis import stock_text as tx

    if metric.value is None:
        return "—"
    if metric.unit == "ratio":
        return tx.pct(metric.value)
    if metric.unit == "multiple":
        return tx.times(metric.value)
    return tx.money(metric.value, metric.currency)


def build(state: str) -> str:
    warnings.filterwarnings("ignore")
    from etf_cockpit.application.score_views import snapshot_scores
    from etf_cockpit.application.snapshot_builder import build_snapshot
    from etf_cockpit.application.stock_service import snapshot_stock_evidence, stock_universe_records

    snapshot = build_snapshot()
    scores = {s.display_id: s for s in snapshot_scores(snapshot, penalise_missing=False) if str(s.instrument_key).startswith("configured:")}
    records = stock_universe_records(snapshot.config)
    evidence = snapshot_stock_evidence(snapshot).evidence if state == "after" else {}
    lines = [f"### State: {state.upper()} (decision time {snapshot.benchmark_reference_decision_time})", ""]
    lines += ["| Stock | Score | Coverage | Components used (incl. the zero-weight data-quality check) | Missing components (reason) |", "|---|---|---|---|---|"]
    for record in records:
        score = scores.get(record.instrument_id)
        if score is None:
            lines.append(f"| {record.instrument_id} | no score | — | — | not in the score list: no configured score row for this instrument |")
            continue
        missing = [f"{c.label}: {c.why.split(chr(10))[0][:80]}" for c in score.components if not c.score_eligible and c.key in {"stock_value", "stock_quality", "analyst_revision", "relative_strength", "timesfm", "toto", "baseline", "momentum", "trend", "risk", "liquidity_cost"}]
        value = "no score" if score.final_score_10 is None else f"{score.final_score_10:.1f}"
        lines.append(f"| {record.instrument_id} | {value} | {score.score_coverage:.0%} | {score.valid_component_count} of {score.total_component_count} | {'; '.join(missing) or 'none'} |")
    lines.append("")
    for record in records:
        lines += [f"#### {record.instrument_id} — {record.name} ({record.symbol})", "", "| Fundamental | Value | Basis / as-of | Source | Reason when unavailable |", "|---|---|---|---|---|"]
        item = evidence.get(record.instrument_id)
        for key, label in ROWS:
            if state == "before" or item is None:
                lines.append(f"| {label} | — | — | — | {BEFORE_REASON} |")
                continue
            metric = item.metrics[key]
            basis = " ".join(part for part in (metric.basis, metric.as_of) if part) or "—"
            reason = "" if metric.value is not None else (metric.reason or metric.status)
            lines.append(f"| {label} | {_fmt(metric)} | {basis} | {metric.source or '—'} | {reason} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", choices=("before", "after"), required=True)
    parser.add_argument("--out", default=str(ROOT_DIR / "docs" / "development" / "stock-coverage-2026-10.md"))
    args = parser.parse_args()
    block = build(args.state)
    out = Path(args.out)
    text = out.read_text(encoding="utf-8") if out.exists() else ""
    marker = args.state.upper()
    wrapped = f"<!-- {marker} -->\n{block}\n<!-- /{marker} -->"
    pattern = re.compile(rf"<!-- {marker} -->.*?<!-- /{marker} -->", re.S)
    if pattern.search(text):
        text = pattern.sub(lambda _m: wrapped, text)
    else:
        text = text.rstrip("\n") + "\n\n" + wrapped + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
