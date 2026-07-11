from __future__ import annotations

from pathlib import Path

from etf_cockpit.backtest.engine import BacktestReport


def write_backtest_markdown(report: BacktestReport, path: Path) -> Path:
    lines = ["# Backtest Report", "", "```csv", report.results.to_csv(index=False), "```"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
