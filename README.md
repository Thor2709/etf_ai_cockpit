# ETF AI Cockpit

Private, local-first Windows investment-research and decision-support
application. Verified capabilities include deterministic ETF analysis, local
evidence, screening, backtest and paper-replay foundations; the canonical
programme also covers stocks, ordinary funds, supported fixed income,
selected-currency bulk analysis and separate portfolio capabilities. Programme
scope is not a claim that every capability is certified today.

The app is a decision-support cockpit, not a financial adviser and not an execution bot. Models forecast, deterministic rules decide, risk gates block, backtests validate, and external audit imports are commentary only.

Open `ETF_AI_Cockpit.bat` from the project root. It starts the Python launcher in the local `.venv` first, so the installed TimesFM/Toto runtime packages and external model folders are available. If that path fails and a packaged executable exists, it falls back to `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`. The app runs locally at `http://127.0.0.1:8550` and opens in your browser because the Flet desktop renderer can show a blank shell on some Windows systems.

## Quick Start

```powershell
cd "path\to\etf_ai_cockpit"
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

### ISSUE-0014 workflow contract

Run the complete deterministic, local-only workflow contract from a clean checkout with:

```text
python scripts/issue0014_workflow.py
```

The runner executes separate source, packaged and browser suites with `ETF_COCKPIT_OFFLINE=1`, fixed hash ordering and UTC. Fixtures cover offline local import, optional online failure, migrations, a 250-instrument universe, training, paper-broker simulation, recovery, package parity and loopback browser startup. No live external network or execution authority is used; every journey asserts `execution_allowed=false`. Use `python scripts/issue0014_workflow.py --dry-run` to inspect the exact suite commands.

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

## Architecture

The [current SDD](docs/architecture/SDD.md) describes verified architecture,
runtime flows and gaps. See the [architecture index](docs/architecture/README.md),
[decision records](docs/architecture/decisions/README.md), and
[traceability map](docs/architecture/TRACEABILITY.md). The old root master
specification is a compatibility pointer to preserved legacy history.

## Broker Automation TODO

Broker execution is intentionally not implemented in v0.1. Future phases, after extensive validation, may add read-only broker holdings import, paper-trading order simulation, draft order proposals and manually approved live order placement with strict limits.

<!-- BEGIN GENERATED FINAL RELEASE PROGRAMME -->
## Final-release programme

ETF AI Cockpit is a private, local-first decision-support application. The adopted programme covers core stock, ETF, ordinary-fund and supported fixed-income research; reproducible bulk/top-N analysis; selected-currency outputs; five editable risk-profile projections; and Quick/Medium/High/Full analysis depths. These are programme contracts, not a claim that every capability is certified today.

The canonical registry and current evidence live in `issues/issue_registry.json` and `docs/product-completion/CURRENT_STATUS.json`. Missing providers, keys, optional models, weights or network access must remain explicit unavailable states and must not prevent safe local startup. Returns require adjusted, corporate-action-aware total-return data and point-in-time evidence.

Live execution is not authorised: `execution_allowed=false`. Portfolio, paper, broker-read-only and disabled canary scaffolding have separate certification/activation lanes and cannot gain authority from a model, LLM, UI action or programme status.

Current delivery mechanics are defined in `docs/product-completion/DELIVERY_WORKFLOW.md`. Canonical checks: `python scripts/generate_programme.py --root . --check`, `python scripts/classify_validation.py --root . --base <exact-origin-main> --head <exact-head>`, `python scripts/validate_app.py --changed`, and `python scripts/validate_app.py --offline`. Ordinary changes use focused evidence plus the classifier-derived full-gate cadence. Full/package certification is delegated to the existing protected release gate through `validate_app.py --full` and `--packaged`; authoritative serial Linux/Windows jobs and the terminal `validation-summary` remain the CI interface.
<!-- END GENERATED FINAL RELEASE PROGRAMME -->
