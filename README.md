# ETF AI Portfolio Cockpit

Local-first Windows desktop-style ETF analysis app for 1-week to 9-month hold, no-trade, add-candidate, trim-candidate and manual-review signals.

The app is a decision-support cockpit, not a financial adviser and not an execution bot. Models forecast, deterministic rules decide, risk gates block, backtests validate, and external audit imports are commentary only.

Open `ETF_AI_Cockpit.bat` from the project root. It starts the Python launcher in the local `.venv` first, so the installed TimesFM/Toto runtime packages and external model folders are available. If that path fails and a packaged executable exists, it falls back to `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`. The app runs locally at `http://127.0.0.1:8550` and opens in your browser because the Flet desktop renderer can show a blank shell on some Windows systems.

## Quick Start

```powershell
cd "C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit"
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\pip install -r requirements-models.txt
.\.venv\Scripts\python scripts\run_app.py
```

For a command-line smoke test without opening the UI:

```powershell
.\.venv\Scripts\python scripts\run_app.py --smoke
```

The workflow smoke harness accepts `source`, `native`, `portable-native`, `launcher`, `first-run` and `offline` modes. It requires a local HTTP-ready app for each mode and removes only processes it started. `offline` prevents the harness itself from making remote requests; it does not certify that every provider is unavailable without a separate provider fixture test.

Run the finish check with a newline-delimited changed-paths file. It executes mapped automated gates and writes a secret-redacted JSON report. Use `--plan-only` to inspect selected gates without running them.

```powershell
.\.venv\Scripts\python scripts\dev_finish_check.py --issues UPDATEV2-0029 ISSUE-0013 --changed-paths-file evidence\wave2\changed-paths.txt --json-report evidence\wave2\finish-report.json
```

The configured market-data backbone is Yahoo Finance through `yfinance`. The validated clean store under `data/clean` is refreshed from yfinance, then algorithms, backtests and TimesFM/Toto forecasts run from that same yfinance price panel. Sample data remains available only as a fallback/test generator.

## Main Workflows

- `python scripts/run_app.py` - launch the local Flet app in browser mode.
- `python scripts/run_yfinance_analysis.py --years 5` - fetch Yahoo Finance prices/metadata/top holdings, validate and commit them, run algorithms, run TimesFM/Toto/baseline forecasts and write a yfinance audit report.
- `python scripts/update_data.py --sample` - regenerate deterministic sample prices and holdings for fallback/testing only.
- `python scripts/run_signals.py --date latest` - compute latest features and signals.
- `python scripts/run_backtest.py` - run the baseline and signal strategy backtest.
- `python scripts/export_chatgpt_pack.py --date latest` - export a local external-audit packet ZIP.
- `python scripts/import_chatgpt_audit.py --path path\to\audit.json` - validate and import external audit JSON as non-executable commentary.
- `pytest tests -q` - run deterministic safety and calculation tests.

## Pages

- Dashboard - weekly decision view, data/model/backtest status and ranked ETF action table.
- Portfolio - current versus target weights, drift, exposure and warnings.
- ETF Detail - identity, metrics, forecasts, gates and action explanation.
- Signals - component score comparison across momentum, trend, risk, rebalance, AI and final score.
- Backtests - strategy versus buy-and-hold, equal-weight, momentum-only and trend-only baselines.
- Audit - export an audit packet and import strict non-executable external audit commentary.
- Data & Models - data status plus Toto/TimesFM availability.
- Settings - editable config overview and validation status.
- Diagnostics - Python, OS, DuckDB, Flet, model folders and log access checks.

## Data

Yahoo Finance symbols are configured in `configs/data_providers.yaml`. The current universe mapping is explicit because Yahoo suffixes can differ by venue, for example `WORLD_CORE` uses `IWDA.AS` while most Xetra listings use `.DE`.

The app validates yfinance OHLCV data, adjusted close availability, stale prices, outliers, minimum history and suspicious rows before producing signals. Yahoo fund metadata and top holdings are imported where Yahoo exposes them, but those are treated as partial/non-issuer data when source dates or full holdings are not available.

## AI Model Modes

Toto and TimesFM adapters expose a clean forecasting interface and safe disabled/mock/live modes. Missing packages or model weights never block app launch; unavailable models return null forecasts and are excluded from scoring. AI outputs are informational unless model agreement and backtest checks support them.

Current local checkpoint folders:

- `models/timesfm/timesfm-2.5-200m-transformers` - TimesFM 2.5 Transformers checkpoint with local `model.safetensors` and `config.json`.
- `models/toto/Toto-2.0-1B` - active Toto 2.0 checkpoint.
- `models/toto/Toto-2.0-4m` - retained as a small fallback/smoke-test checkpoint.

The current `.venv` has the optional runtime installed. To recreate it, run `.\.venv\Scripts\pip install -r requirements-models.txt`. Large model weights are kept outside the packaged executable and ignored by `.gitignore`; `scripts\build_windows.bat` intentionally does not bundle safetensors into the app package.

Optional local LLM audit commentary is configured in `configs/local_llm.yaml` and defaults to the LM Studio OpenAI-compatible endpoint `http://localhost:1234/v1`. It is only called from the Audit page when you press the local LLM buttons. Its output is schema-validated, saved as commentary under `data/reports/`, and cannot calculate portfolio metrics, override risk gates or authorise trades.

## Packaging

Run:

```powershell
scripts\build_windows.bat
```

The build script first tries Flet one-folder packaging. If that is unavailable, it creates a portable folder with launch scripts, app code, configs, data folders, logs, models and first-run notes. A one-file executable is not the default because model weights and writable data/config/log folders are better kept external.

By default the app uses Flet browser mode on `127.0.0.1:8550`, which avoids the blank Flet desktop shell seen on some Windows GPU/Flutter combinations. To try the native desktop renderer anyway, set `ETF_COCKPIT_VIEW=desktop` before launching.

## Broker Automation TODO

Broker execution is intentionally not implemented in v0.1. Future phases, after extensive validation, may add read-only broker holdings import, paper-trading order simulation, draft order proposals and manually approved live order placement with strict limits.
