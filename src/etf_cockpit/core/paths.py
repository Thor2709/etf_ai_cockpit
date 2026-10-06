from __future__ import annotations

import os
from pathlib import Path


def _has_project_config(path: Path) -> bool:
    return (path / "configs" / "universe.yaml").exists()


def project_root(
    start: Path | None = None,
    cwd: Path | None = None,
    env_root: str | None = None,
) -> Path:
    env_value = os.getenv("ETF_COCKPIT_ROOT") if env_root is None else env_root
    if env_value:
        candidate = Path(env_value).expanduser().resolve()
        if _has_project_config(candidate):
            return candidate

    cwd_candidate = (cwd or Path.cwd()).resolve()
    if _has_project_config(cwd_candidate):
        return cwd_candidate

    current = (start or Path(__file__)).resolve()
    for parent in current.parents:
        if _has_project_config(parent):
            return parent
    return current.parents[3] if len(current.parents) > 3 else cwd_candidate


ROOT = project_root()
CONFIG_DIR = ROOT / "configs"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
ETF_QUOTES_DIR = RAW_DIR / "etf_quotes"
ETF_QUOTES_PATH = ETF_QUOTES_DIR / "quotes.csv"
CLEAN_DIR = DATA_DIR / "clean"
ETF_ECONOMICS_PATH = CLEAN_DIR / "etf_economics.parquet"
ETF_FUND_TOTAL_RETURN_PATH = CLEAN_DIR / "etf_fund_total_return.parquet"
ETF_BENCHMARK_TOTAL_RETURN_PATH = CLEAN_DIR / "etf_benchmark_total_return.parquet"
ETF_CLOSURE_POLICY_PATH = CLEAN_DIR / "etf_closure_policy.json"
STATEMENT_FACTS_PATH = CLEAN_DIR / "statement_facts.parquet"
FILINGS_STATEMENTS_PATH = CLEAN_DIR / "filings_statements.parquet"
DERIVED_DIR = DATA_DIR / "derived"
VALIDATED_DIR = DATA_DIR / "validated"
FEATURES_DIR = DATA_DIR / "features"
FORECASTS_DIR = DATA_DIR / "forecasts"
BACKTESTS_DIR = DATA_DIR / "backtests"
PORTFOLIOS_DIR = DATA_DIR / "portfolios"
WORKSPACES_DIR = DATA_DIR / "workspaces"
OPERATIONS_DIR = DATA_DIR / "operations"
CHATGPT_EXPORTS_DIR = DATA_DIR / "chatgpt_exports"
CHATGPT_IMPORTS_DIR = DATA_DIR / "chatgpt_imports"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
AUDIT_PACKETS_DIR = DATA_DIR / "audit_packets"
REPORTS_DIR = DATA_DIR / "reports"
MODEL_DIR = ROOT / "models"
LOG_DIR = ROOT / "logs"
EXPORTS_DIR = ROOT / "exports"
BACKUPS_DIR = ROOT / "backups"

REQUIRED_DIRS = [
    CONFIG_DIR,
    RAW_DIR / "broker",
    RAW_DIR / "prices",
    RAW_DIR / "broker_exports",
    RAW_DIR / "fx",
    RAW_DIR / "etf_factsheets",
    RAW_DIR / "etf_holdings",
    RAW_DIR / "manual_news",
    RAW_DIR / "macro",
    RAW_DIR / "etf_metadata",
    RAW_DIR / "filings",
    RAW_DIR / "sec_edgar",
    RAW_DIR / "esef",
    RAW_DIR / "priips_kids",
    RAW_DIR / "etf_reports",
    ETF_QUOTES_DIR,
    RAW_DIR / "index_methodology",
    RAW_DIR / "rss",
    RAW_DIR / "stock_research",
    CLEAN_DIR,
    DERIVED_DIR,
    SNAPSHOTS_DIR,
    AUDIT_PACKETS_DIR,
    REPORTS_DIR,
    VALIDATED_DIR / "prices",
    VALIDATED_DIR / "metadata",
    FEATURES_DIR,
    FORECASTS_DIR,
    BACKTESTS_DIR,
    PORTFOLIOS_DIR,
    WORKSPACES_DIR,
    OPERATIONS_DIR,
    CHATGPT_EXPORTS_DIR,
    CHATGPT_IMPORTS_DIR,
    MODEL_DIR / "timesfm",
    MODEL_DIR / "toto",
    MODEL_DIR / "lightgbm",
    MODEL_DIR / "cached",
    LOG_DIR,
    EXPORTS_DIR,
    BACKUPS_DIR,
]


def ensure_project_dirs() -> None:
    for path in REQUIRED_DIRS:
        path.mkdir(parents=True, exist_ok=True)
