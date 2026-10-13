
import pandas as pd

from etf_cockpit.core.config import load_config
from etf_cockpit.core.types import DataQualityIssue, DataQualityReport
from etf_cockpit.data.validation import validate_holdings
from etf_cockpit.signals.gates import evaluate_risk_gates


def _gates(issues: list[DataQualityIssue], etf_id: str = "A") -> list[str]:
    report = DataQualityReport(as_of_date=pd.Timestamp("2026-10-09").date(), issues=issues)
    config = load_config()
    row = pd.Series({"etf_id": etf_id, "trend_200": 1.0})
    blocked, _ = evaluate_risk_gates(config, row, report, candidate_action="hold", projected_weight=None, cash_weight=1.0)
    return blocked


def test_short_history_blocks_only_its_own_instrument() -> None:
    issues = [DataQualityIssue("B", "block", "insufficient_history", "Only 83 rows")]
    assert "portfolio_validation_block" not in _gates(issues, "A")
    assert "insufficient_history" in _gates(issues, "B")


def test_other_instrument_blocks_still_block_the_portfolio() -> None:
    issues = [DataQualityIssue("B", "block", "invalid_ohlc", "bad rows")]
    assert "portfolio_validation_block" in _gates(issues, "A")


def test_no_holdings_is_watchlist_mode_not_a_block() -> None:
    report = validate_holdings(load_config(), pd.DataFrame())
    assert report.analysis_allowed
    assert [(i.severity, i.code) for i in report.issues] == [("warning", "empty_holdings")]
