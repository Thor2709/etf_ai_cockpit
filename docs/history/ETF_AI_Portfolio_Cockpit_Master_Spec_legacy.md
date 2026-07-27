# ETF AI Portfolio Cockpit — Master Build Specification

> **LEGACY — historical ETF-only MVP build specification.** This document is
> preserved for rationale and traceability. It is not the current architecture
> or implementation source of truth. See the
> [current SDD](../architecture/SDD.md), the
> [canonical issue registry](../../issues/issue_registry.json), and the
> [current-status artefact](../product-completion/CURRENT_STATUS.json).

**Purpose of this file:** this Markdown file is the complete implementation specification for an AI coding agent to build a local desktop app for ETF buy/add/hold/trim/sell analysis over a **1-week to 9-month** horizon. It should be treated as the single source of truth for product design, architecture, algorithms, UI, model integration, testing, packaging, and implementation order.

**Important scope note:** this app is not a licensed financial adviser and must not present outputs as guaranteed recommendations. It is a personal analysis and decision-support cockpit. Its default action must be **hold / no trade** unless evidence is strong, data is valid, and risk gates pass.

---

## 0. Executive Summary

Build a **local-first Windows desktop app folder** called **ETF AI Portfolio Cockpit**.

The app will analyse ETFs over **1 week, 1 month, 3 months, 6 months, and 9 months** and produce actions:

- **Buy**
- **Add**
- **Hold**
- **Trim**
- **Sell**
- **No trade**
- **Manual review**

The app should look like a clean personal investment command centre: action-first, explanation-second, risk-third, model details available one click deeper.

The best architecture is:

```text
Data ingestion
→ Data validation
→ Feature engineering
→ Baseline signals
→ Toto/TimesFM forecasts
→ Ensemble scoring
→ Risk gates
→ Rebalancing logic
→ Backtesting validation
→ Dashboard
→ ChatGPT review export/import
→ Manual trade proposal
```

The key product philosophy:

```text
Models forecast.
Rules decide.
Risk gates block.
Backtests validate.
ChatGPT audits and explains.
The user approves.
```

---

## 1. Product Definition

### 1.1 What the app is

A local desktop app for personal ETF portfolio management. It should help decide whether an ETF deserves a higher, lower, or unchanged weight in the portfolio over the next 1 week to 9 months.

Primary use case:

```text
I hold or consider several ETFs.
Each week/month I want the app to tell me:
- what changed,
- which ETFs look better/worse,
- whether I should buy/add/hold/trim/sell,
- whether a position is too large,
- whether the forecast is supported by simple baselines,
- whether the AI models add value,
- and what the main risk is.
```

### 1.2 What the app is not

Do **not** build:

- day-trading app,
- high-frequency trading bot,
- direct ChatGPT buy/sell bot,
- raw future-price predictor,
- fully automatic broker-execution system in the MVP,
- black-box system without reason logging,
- strategy optimiser that searches thousands of parameter combinations without overfitting controls.

### 1.3 Best horizon

The app covers 1 week to 9 months, but weight horizons differently:

| Horizon | Use | Importance |
|---|---|---:|
| 1 week | entry timing, alerts, volatility warnings | medium-low |
| 2–4 weeks | tactical add/trim | high |
| 1–3 months | main decision horizon | highest |
| 3–6 months | medium-term allocation tilt | high |
| 6–9 months | thesis/allocation review | medium |

Primary decision horizon: **1–3 months**.
Secondary decision horizon: **3–6 months**.
1-week horizon is **not** for aggressive trading; it is for alerts and entry timing.

---

## 2. Recommended App Form

### 2.1 Preferred distribution form

Do **not** aim for a single tiny `.exe`. The app includes Python, data files, model weights, logs, and possibly PyTorch/Toto/TimesFM dependencies. A one-file executable is possible in theory but fragile, slow to start, painful to update, and unsuitable for model weights.

Build a **portable Windows app folder**:

```text
ETF_AI_Cockpit_Portable/
  ETF_AI_Cockpit.exe
  app/
  runtime/
  data/
  models/
  configs/
  logs/
  exports/
  README_FIRST_RUN.md
  update_models.bat
  run_diagnostics.bat
```

The user launches:

```text
ETF_AI_Cockpit.exe
```

Internally, the executable starts the Python app, loads local data, runs forecasts, and opens a desktop window.

### 2.2 Recommended UI framework

Use **Flet** first.

Reason:

- Python-first, suitable for vibe coding.
- Desktop app feeling, not a browser tab.
- Built-in packaging via `flet build` / `flet pack`.
- Easier than PySide6 for a dashboard-style app.
- Cleaner for a portable `.exe` folder than Streamlit.

Fallback choices:

| Framework | Use if | Notes |
|---|---|---|
| **Flet** | default | best balance for Python + desktop packaging |
| **PySide6** | you need maximum native control | more code, stronger native desktop feel |
| **NiceGUI native** | you accept browser/webview style | very productive, but feels more web-like |
| **Streamlit** | only for prototype | easiest but not ideal as a normal desktop app |

### 2.3 Recommended backend design

Even if using Flet, keep the app internally modular:

```text
UI layer: Flet pages and controls
Service layer: signal generation, backtesting, model orchestration
Data layer: DuckDB + Parquet
Model layer: Toto, TimesFM, baselines, tabular ML
Audit layer: ChatGPT export/import
```

The UI must never contain model logic directly. It should call services.

---

## 3. External Tools and Programs Required

### 3.1 Required for development

Install on the development machine:

- Windows 11
- Python 3.11 or 3.12
- Git
- Build tools if needed by ML packages
- Flet
- DuckDB
- Polars
- Pandas
- NumPy
- scikit-learn
- Plotly
- PyArrow
- MLflow or lightweight JSON logging initially
- TimesFM package/repo
- Toto package/repo
- PyTorch CPU/GPU compatible version
- Optional: LightGBM/XGBoost
- Optional: Great Expectations for data validation
- Optional: PyInstaller/Nuitka for packaging experiments

### 3.2 Required for the user

For the final portable folder, the user should not need to manually install Python if packaging is successful.

However, the app must handle the first run gracefully:

- check CPU/RAM/GPU availability,
- check model files exist,
- check data folders exist,
- check internet if updating prices,
- check config files,
- show diagnostics rather than crash.

### 3.3 Separate programs for AI

#### ChatGPT 5.5 high

Use the normal ChatGPT app/web interface manually. Do not rely on the OpenAI API unless the user separately configures paid API billing.

Workflow:

1. App exports a **ChatGPT Review Pack**.
2. User uploads it into ChatGPT.
3. ChatGPT returns strict JSON + text audit.
4. User imports JSON back into app.
5. App validates it and displays it as audit commentary.

#### Toto/TimesFM

Run locally inside the Python backend.

They are not chat models and should not be loaded through LM Studio. They must be wrapped as forecasting adapters.

#### Optional local LLM / Qwen

Not needed in MVP. Can later be used for cheap local text summarisation, but the core app should not depend on it.

---

## 4. Evidence-Informed Design Principles

### 4.1 Baselines first

The app must first implement simple strategies:

- buy-and-hold,
- equal-weight ETF basket,
- target-weight rebalancing,
- threshold rebalancing,
- 3-month momentum,
- 6-month momentum,
- 9/12-month trend/momentum,
- price-above-moving-average trend filter,
- volatility targeting.

Toto/TimesFM are allowed to influence decisions only after they are compared with these baselines.

### 4.2 Momentum and trend are the core, not exotic AI

Academic momentum evidence supports intermediate horizons such as 3–12 months. For this app, use momentum and trend as robust baseline signals, then let AI attempt to improve risk/return estimates.

### 4.3 Forecasts are uncertain evidence

Toto/TimesFM outputs are not truth. They are uncertain forecasts that must be converted into risk-adjusted, cost-adjusted features.

### 4.4 Risk gates outrank model scores

If a risk gate blocks a trade, the app must not override it because Toto, TimesFM, or ChatGPT is optimistic.

Priority order:

```text
1. Data validity
2. Hard portfolio/risk constraints
3. Backtest validity
4. Baseline comparison
5. Ensemble score
6. ChatGPT explanation
```

### 4.5 Default action is no trade

Most weeks should produce no action. This is a feature, not a bug.

---

## 5. High-Level Architecture

### 5.1 Module diagram

```text
                   ┌─────────────────────────────┐
                   │          Flet UI             │
                   │ Dashboard / Portfolio / etc. │
                   └──────────────┬──────────────┘
                                  │
                                  ▼
                   ┌─────────────────────────────┐
                   │       App Service Layer      │
                   │ orchestration / state / jobs │
                   └──────────────┬──────────────┘
                                  │
           ┌──────────────────────┼──────────────────────┐
           ▼                      ▼                      ▼
┌──────────────────┐   ┌───────────────────────┐   ┌──────────────────┐
│ Data Service      │   │ Signal/Portfolio      │   │ Model Service     │
│ ingest/validate   │   │ scoring/gates/actions │   │ Toto/TimesFM/ML   │
└────────┬─────────┘   └──────────┬────────────┘   └────────┬─────────┘
         ▼                        ▼                         ▼
┌──────────────────┐   ┌───────────────────────┐   ┌──────────────────┐
│ DuckDB + Parquet  │   │ Backtest Engine        │   │ Forecast Store   │
│ local data lake   │   │ walk-forward/logging   │   │ model outputs    │
└──────────────────┘   └───────────────────────┘   └──────────────────┘
                                  │
                                  ▼
                   ┌─────────────────────────────┐
                   │ ChatGPT Bridge              │
                   │ export pack / import JSON   │
                   └─────────────────────────────┘
```

### 5.2 Data flow

```text
1. User opens app
2. App loads configs
3. App validates local data store
4. Optional: update latest ETF data
5. App computes features
6. App runs baseline models
7. App runs TimesFM/Toto if enabled
8. App standardises model forecasts
9. App computes ensemble scores
10. App applies risk gates
11. App generates action table
12. App writes immutable signal log
13. Dashboard displays decisions
14. User optionally exports ChatGPT Review Pack
15. User imports ChatGPT audit JSON
16. App displays audit and stores it
```

---

## 6. Project Folder Structure

Use this exact folder structure unless there is a strong reason not to:

```text
etf_ai_cockpit/
  README.md
  pyproject.toml
  requirements.txt
  requirements-dev.txt
  .env.example
  .gitignore

  configs/
    universe.yaml
    portfolio_targets.yaml
    costs.yaml
    risk_limits.yaml
    model_settings.yaml
    ui_settings.yaml
    chatgpt_schema.json

  data/
    raw/
      prices/
      broker_exports/
      macro/
      etf_metadata/
    validated/
      prices/
      metadata/
    features/
    forecasts/
    backtests/
    portfolios/
    chatgpt_exports/
    chatgpt_imports/

  models/
    timesfm/
    toto/
    lightgbm/
    cached/

  logs/
    app.log
    data_quality.jsonl
    model_runs.jsonl
    signal_log.jsonl
    trade_proposals.jsonl
    chatgpt_audits.jsonl
    errors.jsonl

  src/
    etf_cockpit/
      __init__.py
      main.py

      app/
        flet_app.py
        theme.py
        state.py
        router.py
        components/
          cards.py
          tables.py
          charts.py
          action_badges.py
          risk_badges.py
        pages/
          dashboard.py
          portfolio.py
          etf_detail.py
          signals.py
          backtests.py
          chatgpt_audit.py
          settings.py
          diagnostics.py

      core/
        config.py
        paths.py
        constants.py
        exceptions.py
        logging.py
        scheduler.py

      data/
        ingest_prices.py
        ingest_broker.py
        ingest_metadata.py
        providers.py
        stooq_provider.py
        eodhd_provider.py
        alphavantage_provider.py
        validation.py
        transforms.py
        duckdb_store.py

      features/
        returns.py
        momentum.py
        trend.py
        volatility.py
        drawdown.py
        liquidity.py
        overlap.py
        macro.py
        feature_pipeline.py

      models/
        base.py
        timesfm_adapter.py
        toto_adapter.py
        baseline_models.py
        tabular_models.py
        ensemble.py
        calibration.py
        registry.py

      signals/
        scoring.py
        gates.py
        actions.py
        explanations.py
        signal_pipeline.py

      portfolio/
        holdings.py
        allocation.py
        rebalancing.py
        risk.py
        costs.py
        proposals.py

      backtest/
        engine.py
        walk_forward.py
        metrics.py
        benchmarks.py
        overfitting.py
        reports.py

      chatgpt_bridge/
        export_pack.py
        import_audit.py
        schemas.py
        prompts.py
        validation.py

      packaging/
        diagnostics.py
        first_run.py

  tests/
    test_returns.py
    test_no_lookahead.py
    test_data_validation.py
    test_signal_gates.py
    test_rebalancing.py
    test_backtest_costs.py
    test_chatgpt_import.py
    test_model_shapes.py

  scripts/
    run_app.py
    update_data.py
    run_backtest.py
    export_chatgpt_pack.py
    import_chatgpt_audit.py
    build_windows.bat
    first_run_setup.bat
```

---

## 7. Config Files

### 7.1 `configs/universe.yaml`

Purpose: defines all ETFs the app knows about.

Example:

```yaml
etfs:
  - id: EXX1
    name: iShares EURO STOXX Banks 30-15 UCITS ETF
    isin: DE0006289309
    ticker: EXX1
    exchange: XETRA
    tradegate_ticker: EXX1
    currency: EUR
    asset_class: equity
    region: Europe
    sector: Banks
    theme: EU financials
    role: satellite
    accumulating: false
    ucits: true
    ter: null
    max_weight: 0.15
    min_history_days: 504
    enabled: true

  - id: WORLD_CORE
    name: World equity core ETF
    isin: null
    ticker: TBD
    exchange: TBD
    currency: EUR
    asset_class: equity
    region: World
    sector: Broad
    theme: Core global equity
    role: core
    max_weight: 0.80
    enabled: true
```

Requirements:

- `id` must be unique.
- `ticker` must map to a data provider symbol.
- `tradegate_ticker` can be optional but useful for user execution.
- `role` must be one of: `core`, `regional`, `sector`, `theme`, `bond`, `cash_proxy`, `commodity`, `hedge`, `watchlist`.

### 7.2 `configs/portfolio_targets.yaml`

```yaml
base_currency: EUR
cash_min_weight: 0.02
cash_target_weight: 0.05

portfolio:
  target_total_equity_weight: 0.95
  target_total_bond_cash_weight: 0.05

positions:
  EXX1:
    target_weight: 0.12
    soft_band: 0.03
    hard_band: 0.06
  SXRJ:
    target_weight: 0.10
    soft_band: 0.03
    hard_band: 0.05
```

### 7.3 `configs/risk_limits.yaml`

```yaml
portfolio_limits:
  max_single_etf_weight: 0.35
  max_sector_weight: 0.35
  max_region_weight: 0.70
  max_theme_weight: 0.25
  max_monthly_turnover: 0.25
  max_trade_fraction_of_portfolio: 0.15
  min_trade_value_eur: 100
  max_expected_drawdown_60d: 0.12
  min_edge_to_cost_ratio: 2.5

signal_limits:
  min_confidence_for_buy: 0.60
  min_confidence_for_trim: 0.55
  default_action: no_trade
  require_two_week_confirmation: true
```

### 7.4 `configs/costs.yaml`

```yaml
base_currency: EUR
broker: manual_degiro

cost_model:
  default_commission_eur: 1.00
  default_spread_bps: 8
  default_slippage_bps: 5
  fx_conversion_bps: 25
  min_edge_multiplier: 2.5

per_etf:
  EXX1:
    spread_bps: 6
    slippage_bps: 4
```

### 7.5 `configs/model_settings.yaml`

```yaml
forecast_horizons_trading_days: [5, 20, 60, 120, 180]

models:
  baseline:
    enabled: true
  timesfm:
    enabled: true
    model_path: models/timesfm/timesfm-2.5-200m-pytorch
    context_length: 2048
    use_quantiles: true
    device: auto
  toto:
    enabled: true
    model_size: 313m
    model_path: models/toto/Toto-2.0-313m
    context_length: 2048
    device: auto
  lightgbm:
    enabled: false

ensemble:
  weights:
    momentum: 0.20
    trend: 0.15
    risk: 0.10
    rebalance: 0.10
    relative_strength: 0.10
    toto: 0.15
    timesfm: 0.10
    baseline_ml: 0.05
    chatgpt_thesis: 0.05
  allow_dynamic_weights: false
```

---

## 8. Data Model and Storage

### 8.1 Use DuckDB + Parquet

Store time-series data as Parquet files and query using DuckDB. DuckDB can read Parquet directly and Parquet is compressed/columnar, making it suitable for local analytics.

### 8.2 Main tables

#### `prices_daily`

Columns:

```text
date: date
etf_id: string
provider_symbol: string
open: float
high: float
low: float
close: float
adjusted_close: float
volume: float
currency: string
source: string
is_adjusted: bool
ingested_at: timestamp
```

Rules:

- Use `adjusted_close` for returns.
- If `adjusted_close` is missing, block total-return backtests unless the ETF is known not to distribute or the provider has adjusted data.
- Never mix raw close and adjusted close silently.

#### `holdings_current`

```text
as_of_date: date
etf_id: string
units: float
market_price: float
market_value_eur: float
current_weight: float
average_cost_eur: float
unrealised_gain_eur: float
unrealised_gain_pct: float
source: string
```

#### `features_daily`

```text
date
etf_id
return_1d_log
return_5d_log
return_20d_log
return_60d_log
momentum_20d
momentum_60d
momentum_120d
momentum_180d
sma_50
sma_100
sma_200
trend_100
trend_200
vol_20d_ann
vol_60d_ann
ewma_vol_ann
drawdown_current
drawdown_60d_max
drawdown_120d_max
relative_strength_60d
relative_strength_120d
liquidity_score
```

#### `forecasts`

```text
run_id: string
created_at: timestamp
forecast_date: date
model_name: string
model_version: string
etf_id: string
horizon_days: int
expected_return: float
expected_excess_return: float
q10_return: float
q50_return: float
q90_return: float
prob_positive_return: float
prob_beat_benchmark: float
forecast_vol: float
forecast_drawdown_prob: float
input_window_start: date
input_window_end: date
status: string
error_message: string|null
```

#### `signals`

```text
run_id
signal_date
etf_id
score_total
score_momentum
score_trend
score_risk
score_rebalance
score_relative_strength
score_toto
score_timesfm
score_chatgpt
action
confidence
blocked_by
reason_short
reason_long
created_at
```

#### `backtest_results`

```text
run_id
strategy_name
universe_id
start_date
end_date
cagr
volatility
sharpe
sortino
max_drawdown
calmar
turnover
cost_drag
win_rate
avg_gain
avg_loss
benchmark_cagr
benchmark_max_drawdown
excess_return
information_ratio
status
```

---

## 9. Core Mathematical Features

### 9.1 Log returns

Use log returns internally:

```text
r_t = ln(P_t / P_{t-1})
```

For horizon h:

```text
R_{t,h} = ln(P_t / P_{t-h})
```

Forward label for backtests:

```text
FwdReturn_{t,h} = ln(P_{t+h} / P_t)
```

### 9.2 Excess return

```text
ExcessReturn_{i,t,h} = Return_{i,t,h} - Return_{benchmark,t,h}
```

Use excess return because the app should compare an ETF against the likely alternative, not merely ask if it rises in a bull market.

### 9.3 Momentum

```text
MOM_20  = ln(P_t / P_{t-20})
MOM_60  = ln(P_t / P_{t-60})
MOM_120 = ln(P_t / P_{t-120})
MOM_180 = ln(P_t / P_{t-180})
```

Starting momentum score:

```text
MomentumScore =
0.15 * z(MOM_20)
+ 0.35 * z(MOM_60)
+ 0.35 * z(MOM_120)
+ 0.15 * z(MOM_180)
```

Use cross-sectional z-scores within the ETF universe, clipped to [-3, +3].

### 9.4 Trend

```text
SMA_N = mean(P_{t-N+1:t})
Trend_100 = 1 if P_t > SMA_100 else 0
Trend_200 = 1 if P_t > SMA_200 else 0
TrendSlope = SMA_100 / SMA_200 - 1
```

Trend score:

```text
TrendScore =
0.35 * Trend_100
+ 0.35 * Trend_200
+ 0.30 * clipped_z(TrendSlope)
```

### 9.5 Volatility

Annualised realised volatility:

```text
Vol_N = std(r_{t-N+1:t}) * sqrt(252)
```

Use N = 20, 60, 120.

### 9.6 EWMA volatility

```text
sigma2_t = lambda * sigma2_{t-1} + (1 - lambda) * r_t^2
sigma_t = sqrt(sigma2_t * 252)
```

Starting lambda:

- 0.94 for short horizon
- 0.97 for slower ETF allocation

### 9.7 Drawdown

```text
Peak_t = max(P_0 ... P_t)
Drawdown_t = P_t / Peak_t - 1
MaxDrawdown_window = min(Drawdown_{t-window:t})
```

### 9.8 Robust z-score

Financial data is heavy-tailed. Use robust z-score where possible:

```text
robust_z = (x - median(x_window)) / (1.4826 * MAD(x_window))
```

Where:

```text
MAD = median(|x - median(x)|)
```

Clip robust z-scores:

```text
z_clipped = min(max(robust_z, -3), 3)
```

### 9.9 Cost-adjusted edge

```text
CostAdjustedEdge =
ExpectedExcessReturn
- TradingCost
- SlippageCost
- FXCost
- UncertaintyPenalty
- TurnoverPenalty
```

Trade only if:

```text
CostAdjustedEdge > 0
AND ExpectedExcessReturn > min_edge_to_cost_ratio * EstimatedCost
```

Default min edge-to-cost ratio: 2.5.

### 9.10 Portfolio drift

```text
Drift_i = CurrentWeight_i - TargetWeight_i
```

Use bands:

```text
If Drift_i > hard_band_i: trim candidate
If Drift_i < -hard_band_i: add candidate
If abs(Drift_i) <= soft_band_i: no rebalance needed
```

### 9.11 Shrunk covariance

Use shrinkage covariance for portfolio risk instead of raw sample covariance:

```text
Sigma_shrunk = delta * F + (1 - delta) * S
```

Where:

- S = sample covariance matrix
- F = structured target, such as diagonal or constant-correlation target
- delta = shrinkage intensity

Implement initially via `sklearn.covariance.LedoitWolf`.

---

## 10. Noise Suppression

Noise suppression is central to this app.

### 10.1 Data-level noise suppression

Block signal generation if:

```text
latest price older than 2 trading days
adjusted close missing
volume is zero or null
one-day return is > 8 robust sigma and not confirmed
ETF has less than required history
currency metadata missing
provider data conflicts with previous stored data beyond tolerance
```

Outlier handling:

- Do not delete outliers automatically.
- Flag outliers.
- Winsorise only for feature/model input, never for raw stored prices.
- Keep an audit trail.

### 10.2 Feature-level noise suppression

Use:

- rolling medians,
- robust z-scores,
- clipping at [-3, +3],
- EWMA volatility,
- minimum-history checks,
- cross-sectional ranks instead of raw values where possible.

### 10.3 Signal-level noise suppression

Use deadbands:

```text
If -0.30 < TotalScore < +0.45 → Hold / No trade
```

Use hysteresis:

```text
Enter Add state if score > +0.60
Remain Add/Hold unless score < +0.20
Enter Trim state if score < -0.45
Enter Sell candidate if score < -0.75 and thesis/risk gates confirm
```

Use confirmation:

```text
Require 2 weekly closes for new buy/add/trim signal unless hard risk gate triggers.
```

### 10.4 Model-level noise suppression

AI forecast affects action only if at least one condition holds:

```text
Toto agrees with simple baseline direction
OR TimesFM agrees with simple baseline direction
OR Toto has proven walk-forward edge for this ETF class
OR signal is used only as informational, not action-driving
```

Compute model disagreement:

```text
Disagreement = std([TotoScore, TimesFMScore, BaselineScore, MomentumScore])
```

If disagreement is high:

```text
Action = Hold / Manual review
```

### 10.5 Portfolio-level noise suppression

Before any add/buy:

- check sector cap,
- check region cap,
- check currency cap,
- check single ETF cap,
- check ETF overlap,
- check cash minimum,
- check projected portfolio volatility,
- check turnover limit.

---

## 11. Forecasting Models

## 11.1 TimesFM 2.5 Adapter

TimesFM is a pretrained time-series foundation model for forecasting. TimesFM 2.5 uses 200M parameters, supports up to 16k context length, and supports quantile forecasts via an optional quantile head.

### Role

Use TimesFM as:

- fast baseline forecaster,
- univariate return forecast,
- volatility forecast helper,
- fallback when multivariate Toto data is incomplete,
- sanity check against Toto.

### Inputs

Preferred input series:

```text
log returns
normalised cumulative total-return index
realised volatility series
```

Do not feed raw unnormalised prices as the primary signal.

### Outputs to standardise

Adapter must output:

```python
ForecastResult(
    model_name="timesfm",
    etf_id=str,
    forecast_date=date,
    horizon_days=int,
    expected_return=float,
    q10_return=float | None,
    q50_return=float | None,
    q90_return=float | None,
    forecast_vol=float | None,
    prob_positive_return=float | None,
    status="ok" | "failed" | "skipped",
    error_message=str | None,
)
```

### Implementation notes

Create `src/etf_cockpit/models/timesfm_adapter.py`.

Required class:

```python
class TimesFMAdapter:
    def __init__(self, config: ModelConfig): ...
    def is_available(self) -> bool: ...
    def load_model(self) -> None: ...
    def forecast_series(self, series: pd.Series, horizons: list[int]) -> list[ForecastResult]: ...
    def unload_model(self) -> None: ...
```

The adapter must fail gracefully if TimesFM is not installed or model files are missing. UI should show: `TimesFM unavailable — using baselines only`.

---

## 11.2 Toto 2.0 Adapter

Toto 2.0 is a family of multivariate time-series forecasting models from 4M to 2.5B parameters.

### Role

Use Toto as the main AI forecaster because ETF movements are multivariate.

### Inputs

For each ETF, prepare a multivariate window:

```text
ETF log return
benchmark/world ETF log return
region ETF log return
sector ETF log return
bond proxy return
FX proxy return
volatility proxy change
volume/liquidity proxy
optional commodity/gold proxy
```

All input channels must be aligned by date. Missing values must be handled before model call.

### Output

Same standard `ForecastResult` schema as TimesFM.

### Recommended sizes

Start:

```text
Toto 2.0 313M
```

Then test:

```text
Toto 2.0 1B
```

Only keep 2.5B if walk-forward results justify runtime.

### Implementation notes

Create `src/etf_cockpit/models/toto_adapter.py`.

Required class:

```python
class TotoAdapter:
    def __init__(self, config: ModelConfig): ...
    def is_available(self) -> bool: ...
    def load_model(self) -> None: ...
    def build_multivariate_input(self, etf_id: str, as_of_date: date) -> ModelInput: ...
    def forecast_etf(self, etf_id: str, as_of_date: date, horizons: list[int]) -> list[ForecastResult]: ...
    def unload_model(self) -> None: ...
```

Toto must be optional. If unavailable, the app works with baseline + TimesFM.

---

## 11.3 Baseline Models

Always implement before AI.

### Baseline A: Naive hold

```text
Forecast return = historical mean or 0
```

### Baseline B: Momentum continuation

```text
ExpectedReturn_h = k * MomentumScore_h
```

### Baseline C: Trend filter

```text
Expected excess return positive if price > SMA_200 and momentum positive
```

### Baseline D: EWMA volatility

Forecast volatility using EWMA.

### Baseline E: LightGBM/elastic net later

Inputs:

- momentum,
- trend,
- volatility,
- drawdown,
- liquidity,
- macro proxies,
- relative strength.

Target:

```text
probability of ETF beating benchmark over next 60 trading days after costs
```

Do not enable LightGBM in MVP unless the baseline/rules are already working.

---

## 12. Ensemble Scoring

### 12.1 Component scores

Each ETF gets these component scores:

```text
MomentumScore
TrendScore
RiskScore
RebalanceScore
RelativeStrengthScore
TotoScore
TimesFMScore
BaselineMLScore
ChatGPTThesisScore
```

All scores must be normalised to approximately [-1, +1].

### 12.2 Total score

Initial formula:

```text
TotalScore =
0.20 * MomentumScore
+ 0.15 * TrendScore
+ 0.10 * RiskScore
+ 0.10 * RebalanceScore
+ 0.10 * RelativeStrengthScore
+ 0.15 * TotoScore
+ 0.10 * TimesFMScore
+ 0.05 * BaselineMLScore
+ 0.05 * ChatGPTThesisScore
- CostPenalty
- TurnoverPenalty
- ConcentrationPenalty
```

If Toto unavailable, redistribute its 0.15 weight:

```text
+0.07 to Momentum
+0.04 to Trend
+0.04 to TimesFM/Baseline
```

If TimesFM unavailable, redistribute its 0.10 weight:

```text
+0.05 to Momentum
+0.05 to Baseline
```

If ChatGPT audit unavailable, set ChatGPTThesisScore = 0, not missing.

### 12.3 AI forecast score

For a model forecast:

```text
ForecastScore = z_cross_section(ExpectedExcessReturn / ForecastVol)
```

If quantiles available:

```text
DownsidePenalty = abs(min(Q10, 0))
UpsidePotential = max(Q90, 0)
ForecastScore = z(ExpectedExcessReturn / ForecastVol) + 0.25*z(UpsidePotential) - 0.35*z(DownsidePenalty)
```

Clip final forecast score to [-1, +1].

### 12.4 Confidence

Confidence should not simply equal score magnitude.

```text
Confidence =
0.25 * DataQualityScore
+ 0.25 * ModelAgreementScore
+ 0.20 * BacktestReliabilityScore
+ 0.15 * SignalPersistenceScore
+ 0.15 * Liquidity/CostQualityScore
```

Scale to 0–1.

If data invalid: confidence = 0.

---

## 13. Action Engine

### 13.1 Action thresholds

Starting thresholds:

```text
Strong Buy/Add: TotalScore >= +0.75 and confidence >= 0.65
Buy/Add:        TotalScore >= +0.50 and confidence >= 0.60
Hold:           -0.30 < TotalScore < +0.50
Trim:           TotalScore <= -0.30 and confidence >= 0.55
Sell candidate: TotalScore <= -0.75 and confidence >= 0.65
No trade:       any weak/conflicted/blocked case
Manual review:  thesis change, data issue, model disagreement, or risk gate conflict
```

### 13.2 Deciding buy vs add

```text
If current_weight == 0 and signal positive → Buy
If current_weight > 0 and signal positive → Add
```

But only if target/risk gates allow.

### 13.3 Deciding trim vs sell

```text
Trim = reduce position because overweight or risk/reward worsened.
Sell = ETF no longer fits portfolio or structural thesis invalidated.
```

Sell should be rare. For ETFs, most negative cases should be trim/underweight rather than full sell.

### 13.4 Risk gates

Before any action:

```text
If data invalid → No signal
If latest data stale → No signal
If expected edge < cost threshold → No trade
If concentration cap breached by action → Block action
If cash minimum breached → Block buy/add
If turnover cap breached → Block trade
If model disagreement high → Manual review
If backtest class failed → AI informational only
```

### 13.5 Action explanation

Every action must have:

```text
action
confidence
primary reason
supporting metrics
blocking risks
horizon
what would change the decision
```

Example:

```text
Action: Add small
Confidence: 0.64
Horizon: 1–3 months
Reason: ETF is 4.2 percentage points below target, 3-month momentum is positive, trend is above SMA-200, and Toto/TimesFM both forecast positive 60-day excess return.
Risks: model agreement is only moderate; spread cost estimate is stale.
Invalidation: if 60-day momentum turns negative or Q10 downside exceeds -8%.
```

---

## 14. Rebalancing and Position Sizing

### 14.1 Target-weight first

The user defines strategic target weights. The app proposes changes around those weights.

### 14.2 Bands

Default bands:

| ETF role | Soft band | Hard band |
|---|---:|---:|
| core | 5 pp | 10 pp |
| regional | 4 pp | 8 pp |
| sector | 3 pp | 6 pp |
| theme | 2 pp | 4 pp |
| bond/cash | 5 pp | 10 pp |

`pp` = percentage points.

### 14.3 Add/trim sizing

Propose trade size as the smallest of:

```text
amount needed to return halfway to target
max_trade_fraction_of_portfolio
cash available after cash_min_weight
risk cap allowance
turnover budget remaining
```

Example:

```text
If target = 12%, current = 7%, and signal positive:
Suggested new weight = 9.5% to 10%, not full jump to 12%.
```

### 14.4 Volatility adjustment

If ETF volatility is high, reduce proposed size:

```text
VolAdjustedTrade = BaseTrade * min(1, TargetVol / ForecastVol)
```

### 14.5 Suggested trade output

```text
Suggested action: Add
Suggested size: +€350 to +€500
Reason: below target and signal positive
Do not exceed final weight: 10%
```

No exact order execution in MVP.

---

## 15. Backtesting Engine

### 15.1 Requirements

Backtesting must use the **same signal code path** as live signals. Do not create a separate backtest-only strategy implementation.

### 15.2 Walk-forward design

Suggested setup:

```text
Training window: 3–5 years
Validation window: 6–12 months
Test window: 1–3 months
Step: monthly
```

For each step:

1. train/calibrate models using only data up to train end,
2. choose thresholds/weights only from training/validation,
3. run next test period,
4. roll forward,
5. record results.

### 15.3 Purging/embargo

If using overlapping forward labels, avoid leakage.

Example:

```text
For 60-day forward return labels, embargo at least 60 trading days between train and test label windows where necessary.
```

### 15.4 Baselines

Backtest every strategy against:

```text
buy-and-hold benchmark ETF
equal-weight ETF basket
monthly target-weight rebalancing
threshold rebalancing
3-month momentum ranking
6-month momentum ranking
12-month momentum ranking
price above SMA-200 trend filter
volatility targeting
no-AI ensemble
```

### 15.5 Metrics

Portfolio metrics:

```text
CAGR
annualised volatility
Sharpe ratio
Sortino ratio
max drawdown
Calmar ratio
turnover
cost drag
win rate
average gain
average loss
profit factor
tracking error
information ratio
worst 1-month return
worst 3-month return
worst 12-month return
maximum time under water
```

Forecast metrics:

```text
MAE
RMSE
MASE
Brier score
CRPS if available
calibration curve
rank correlation between forecast and realised returns
hit rate of positive excess return
```

Signal metrics:

```text
forward 20/60/120-day excess return after signal
average drawdown after buy/add signal
trim success rate
false positive rate
no-trade correctness
model agreement vs outcome
```

### 15.6 Minimum acceptable AI benefit

Toto/TimesFM are allowed to drive action only if they improve at least one of:

```text
higher after-cost CAGR with similar/lower drawdown
lower max drawdown with similar CAGR
better Calmar ratio
better information ratio
lower turnover for same return
better forecast calibration
better ETF ranking correlation
```

If AI only improves in-sample but not walk-forward out-of-sample, mark as informational only.

---

## 16. ChatGPT 5.5 High Manual Integration

### 16.1 Why manual export/import

The user has ChatGPT subscription access, not necessarily API access. Therefore, use a manual structured workflow.

### 16.2 ChatGPT Review Pack

Add button in app:

```text
Export ChatGPT Review Pack
```

Create a folder or zip:

```text
chatgpt_review_YYYY-MM-DD/
  00_prompt.md
  01_portfolio_summary.json
  02_signal_table.csv
  03_etf_detail_metrics.csv
  04_model_forecasts.csv
  05_backtest_summary.json
  06_recent_news_events.md
  07_questions_for_chatgpt.md
  08_response_schema.json
  09_readme.md
```

Also generate a single combined Markdown file:

```text
combined_review_packet.md
```

This helps if uploading multiple files is inconvenient.

### 16.3 What to export

#### `01_portfolio_summary.json`

```json
{
  "as_of_date": "2026-06-26",
  "base_currency": "EUR",
  "portfolio_value": 5000,
  "cash_weight": 0.05,
  "holdings": [
    {
      "etf_id": "EXX1",
      "name": "iShares EURO STOXX Banks 30-15 UCITS ETF",
      "current_weight": 0.14,
      "target_weight": 0.12,
      "drift": 0.02,
      "unrealised_gain_pct": 0.18,
      "role": "sector_satellite"
    }
  ],
  "risk_limits": {
    "max_single_etf_weight": 0.35,
    "max_sector_weight": 0.35
  }
}
```

#### `02_signal_table.csv`

Columns:

```text
etf_id,name,action,confidence,total_score,score_1w,score_1m,score_3m,score_6m,score_9m,blocked_by,reason_short
```

#### `03_etf_detail_metrics.csv`

Columns:

```text
etf_id,date,current_weight,target_weight,momentum_20,momentum_60,momentum_120,momentum_180,trend_100,trend_200,vol_20,vol_60,drawdown_current,drawdown_120,relative_strength_60,liquidity_score,cost_bps
```

#### `04_model_forecasts.csv`

Columns:

```text
model_name,model_version,etf_id,horizon_days,expected_return,expected_excess_return,q10_return,q50_return,q90_return,forecast_vol,prob_positive_return,prob_beat_benchmark,status
```

#### `05_backtest_summary.json`

Must include:

```json
{
  "main_strategy": {},
  "benchmarks": [],
  "ai_added_value": true,
  "warning_flags": [],
  "last_walk_forward_periods": []
}
```

### 16.4 Exact ChatGPT prompt

Save this as `00_prompt.md`:

```text
You are reviewing a local ETF AI Portfolio Cockpit. Do not give personal financial advice. Act as a model-risk auditor, portfolio-risk auditor, and systematic-investing research reviewer.

The app analyses ETFs over 1 week, 1 month, 3 months, 6 months, and 9 months. It uses momentum, trend, rebalancing, volatility/drawdown, Toto 2.0 forecasts, TimesFM 2.5 forecasts, simple baselines, and risk gates.

Files uploaded:
- 01_portfolio_summary.json: holdings, weights, targets, constraints
- 02_signal_table.csv: current actions and scores
- 03_etf_detail_metrics.csv: ETF metrics
- 04_model_forecasts.csv: Toto/TimesFM/baseline outputs
- 05_backtest_summary.json: walk-forward/backtest metrics
- 06_recent_news_events.md: optional thesis/macro notes
- 08_response_schema.json: JSON schema you must follow

Tasks:
1. Identify which app signals are strongest and weakest.
2. Check if each buy/add/trim/sell signal is justified by the data.
3. Flag overfitting risk, stale data, model disagreement, excessive turnover, hidden concentration, and small edge after costs.
4. Compare AI model evidence with simple baselines.
5. Identify which trades should be ignored or downgraded to hold/no trade.
6. Separate short-term alerts from medium-term allocation decisions.
7. Do not invent missing data.
8. If data is missing, mark it explicitly as missing.
9. Do not recommend automatic execution.
10. Default to hold/no trade when evidence is weak.

Output format:
A. Human-readable audit report with headings:
- Executive summary
- Strongest signals
- Signals to ignore or downgrade
- Risk/concentration issues
- Model-risk issues
- Data-quality issues
- Suggested next checks

B. Then output exactly one JSON object matching 08_response_schema.json.
Do not output anything after the JSON.
```

### 16.5 ChatGPT response schema

Save as `configs/chatgpt_schema.json` and include in exports:

```json
{
  "schema_version": "1.0",
  "review_date": "YYYY-MM-DD",
  "overall_view": "risk_on | neutral | risk_off | unclear",
  "portfolio_actions": [
    {
      "etf_id": "string",
      "action": "buy | add | hold | trim | sell | no_trade | manual_review",
      "conviction": 0.0,
      "reason_short": "string",
      "main_supporting_metrics": ["string"],
      "main_risks": ["string"],
      "blocked_by": ["string"],
      "manual_checks": ["string"]
    }
  ],
  "ignored_signals": [
    {
      "etf_id": "string",
      "reason": "string"
    }
  ],
  "risk_flags": [
    {
      "type": "concentration | data_quality | overfitting | model_disagreement | liquidity | cost | thesis_change",
      "severity": "low | medium | high",
      "description": "string"
    }
  ],
  "model_audit": {
    "toto_usefulness": "string",
    "timesfm_usefulness": "string",
    "baseline_comparison": "string",
    "overfitting_concerns": ["string"]
  },
  "dashboard_notes": ["string"]
}
```

### 16.6 Import validation

When importing ChatGPT JSON:

Reject if:

```text
invalid JSON
schema_version missing
unknown ETF id appears
action not in allowed enum
conviction not between 0 and 1
required fields missing
JSON recommends automatic execution
```

Imported ChatGPT audit must be displayed as **audit commentary**, not as the final signal engine.

Decision hierarchy remains:

```text
Risk gates > backtest validation > signal engine > ChatGPT audit
```

---

## 17. UI/UX Specification

### 17.1 Overall feel

Design style:

- calm, dense, professional,
- dark mode default,
- no gimmicky finance neon,
- tables first, charts second,
- action colour badges,
- every action explainable,
- show uncertainty clearly.

Use colour sparingly:

```text
Blue/grey: neutral
Green: buy/add/positive
Amber: warning/hold/manual review
Red: trim/sell/risk blocked
Purple: AI/model/audit notes
```

### 17.2 Navigation

Left sidebar:

```text
Dashboard
Portfolio
Signals
ETF Detail
Backtests
ChatGPT Audit
Data & Models
Settings
Diagnostics
```

### 17.3 Page 1 — Dashboard

Purpose: the page used every week.

Top cards:

```text
Portfolio mode: Risk-on / Neutral / Risk-off / Unclear
Best action today: Add / Trim / Hold / No trade
Data status: Clean / Warning / Blocked
AI status: Toto ok / TimesFM ok / Baseline only
Backtest status: Valid / Warning / Failed
```

Main table:

```text
ETF | Current weight | Target | Drift | Action | Confidence | 1w | 1m | 3m | 6m | 9m | Reason | Blocked by
```

Sorting:

1. action priority,
2. confidence,
3. absolute drift,
4. total score.

Buttons:

```text
Update data
Run signals
Export ChatGPT pack
Open latest audit
Create trade proposal
```

### 17.4 Page 2 — Portfolio

Show:

- current allocation vs target,
- drift bars,
- region exposure,
- sector exposure,
- currency exposure,
- ETF overlap warnings,
- cash level,
- risk limits.

Components:

```text
Allocation bar chart
Current vs target table
Concentration warning cards
Cash and turnover panel
```

### 17.5 Page 3 — Signals

This is the model-comparison page.

Table columns:

```text
ETF
Momentum
Trend
Risk
Rebalance
Relative strength
Toto
TimesFM
Baseline
ChatGPT thesis
Total
Action
```

Clicking a score opens explanation.

### 17.6 Page 4 — ETF Detail

Layout:

Top:

```text
ETF name | ticker | ISIN | exchange | currency | role | TER | last price | current action
```

Left column:

- price chart,
- drawdown chart,
- rolling volatility chart.

Middle column:

- momentum table,
- trend status,
- relative strength,
- forecast quantiles.

Right column:

- action card,
- confidence card,
- risk gates,
- suggested trade size,
- thesis status.

Bottom:

- Toto/TimesFM/baseline comparison,
- last ChatGPT audit note,
- historical signal outcomes.

### 17.7 Page 5 — Backtests

Sections:

1. Strategy selector
2. Date range selector
3. Benchmark selector
4. Results cards
5. Equity curve
6. Drawdown chart
7. Monthly returns heatmap
8. Trade/action log
9. AI added value panel
10. Overfitting warnings

Must show:

```text
With AI vs without AI
After costs vs before costs
Main strategy vs buy-and-hold
Main strategy vs momentum-only
```

### 17.8 Page 6 — ChatGPT Audit

Sections:

```text
Export Review Pack
Import Review JSON
Latest Audit Summary
Risk Flags
Signals ChatGPT Downgraded
Manual Checks
```

The UI must label ChatGPT as:

```text
External audit layer — not final trading authority
```

### 17.9 Page 7 — Data & Models

Show:

- latest data date per ETF,
- missing values,
- provider status,
- model availability,
- model paths,
- latest model run time,
- forecast errors,
- diagnostics.

### 17.10 Page 8 — Settings

Editable configs:

- ETF universe,
- target weights,
- risk limits,
- cost assumptions,
- model enable/disable,
- ChatGPT export settings,
- app theme.

Must validate before save.

### 17.11 Page 9 — Diagnostics

Show:

- Python version,
- OS,
- RAM,
- GPU availability,
- PyTorch availability,
- TimesFM availability,
- Toto availability,
- DuckDB version,
- data folder access,
- model folder access,
- last error logs.

Button:

```text
Run full diagnostic
Export diagnostic report
```

---

## 18. Data Providers

### 18.1 Prototype providers

Start with:

- Stooq for free historical market data where available,
- manual CSV import for broker holdings,
- manually maintained ETF metadata.

### 18.2 Serious providers later

Add optional:

- EODHD for adjusted historical prices and ETF data,
- Alpha Vantage for ETF profile/holdings,
- broker export files,
- IBKR API if later automating.

### 18.3 Data provider interface

Create abstract provider:

```python
class PriceProvider:
    name: str
    def fetch_daily_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...
    def validate_symbol(self, symbol: str) -> bool: ...
```

Provider output must map into `prices_daily` schema.

### 18.4 Manual CSV import

Must support importing CSV with columns:

```text
date, open, high, low, close, adjusted_close, volume
```

Allow mapping column names in UI.

---

## 19. Logging and Audit

### 19.1 Immutable logs

Use JSONL logs for:

```text
data_quality.jsonl
model_runs.jsonl
signal_log.jsonl
trade_proposals.jsonl
chatgpt_audits.jsonl
errors.jsonl
```

Each log entry must include:

```text
timestamp
run_id
app_version
config_hash
data_hash
model_version
event_type
payload
```

### 19.2 Signal log example

```json
{
  "timestamp": "2026-06-26T18:30:00+10:00",
  "run_id": "20260626_183000",
  "etf_id": "EXX1",
  "action": "hold",
  "confidence": 0.71,
  "total_score": 0.38,
  "blocked_by": ["near_target_weight", "edge_below_trade_threshold"],
  "reason_short": "Positive medium-term signal but already near target and edge not large enough after costs.",
  "config_hash": "...",
  "data_hash": "..."
}
```

---

## 20. Packaging Specification

### 20.1 Preferred packaging target

Build a portable Windows folder.

Output:

```text
ETF_AI_Cockpit_Portable_v0.1.0/
  ETF_AI_Cockpit.exe
  _internal/
  configs/
  data/
  models/
  logs/
  exports/
  README_FIRST_RUN.md
```

### 20.2 Build with Flet

Try:

```bash
flet build windows --output build/windows
```

Or use Flet/PyInstaller one-folder mode if needed:

```bash
flet pack src/etf_cockpit/main.py --name ETF_AI_Cockpit --onedir
```

Exact command may need adjustment to current Flet version. The app must include a `scripts/build_windows.bat` that documents the current working command.

### 20.3 Why not one-file

Do not use one-file as default because:

- PyTorch dependencies can be huge,
- model weights should be external/updateable,
- one-file extraction causes slow startup,
- antivirus false positives are more likely,
- debugging is harder,
- data/config/logs must remain writable.

### 20.4 First-run flow

On first launch:

1. create missing folders,
2. copy default configs,
3. ask user to select data provider or import CSV,
4. check models,
5. if models missing, show download/setup instructions,
6. run diagnostics,
7. load dashboard.

### 20.5 Model download strategy

Do not bundle large model weights into the executable.

Use:

```text
models/timesfm/
models/toto/
```

Provide:

```text
update_models.bat
```

This script should download or instruct the user how to download model weights from official sources.

If no model exists, the app still works with baseline signals.

---

## 21. Tests and Acceptance Criteria

### 21.1 Critical tests

The app must include tests for:

```text
returns use adjusted_close
features do not use future data
forecasts only use data up to forecast date
stale data blocks signal
data outliers are flagged
target weights validate
risk gates block invalid trades
transaction costs apply in backtest
backtest and live signals use same pipeline
ChatGPT import rejects invalid JSON
unknown ETF IDs rejected
model adapter failure does not crash app
```

### 21.2 No-lookahead test

Create a test that intentionally hides future data and verifies features remain identical.

Pseudo-test:

```python
def test_features_do_not_change_when_future_rows_removed():
    full = compute_features(prices_until_2026)
    truncated = compute_features(prices_until_2025)
    assert full.loc[:"2025-12-31"].equals(truncated)
```

### 21.3 Acceptance criteria for MVP

MVP is complete when:

- app launches from desktop folder,
- ETF universe loads,
- data loads from CSV/provider,
- feature table computes,
- dashboard shows actions,
- portfolio page shows drift,
- ETF detail page works,
- backtest page compares at least 3 baselines,
- TimesFM/Toto can be unavailable without crash,
- signal log writes JSONL,
- ChatGPT export pack works,
- ChatGPT JSON import validates.

---

## 22. Implementation Phases

### Phase 1 — Skeleton desktop app

Build:

- Flet app shell,
- left navigation,
- config loading,
- placeholder pages,
- logging,
- diagnostics.

### Phase 2 — Data and portfolio

Build:

- ETF universe config,
- price CSV import,
- holdings import,
- DuckDB/Parquet store,
- data validation,
- portfolio allocation page.

### Phase 3 — Features and simple signals

Build:

- returns,
- momentum,
- trend,
- volatility,
- drawdown,
- relative strength,
- basic scoring,
- action engine without AI.

### Phase 4 — Backtesting

Build:

- buy-and-hold baseline,
- equal-weight baseline,
- threshold rebalancing,
- momentum baseline,
- cost model,
- metrics,
- backtest UI.

### Phase 5 — TimesFM adapter

Build:

- availability check,
- model load/unload,
- forecast wrapper,
- output standardisation,
- fallback errors.

### Phase 6 — Toto adapter

Build:

- multivariate input builder,
- model wrapper,
- forecast standardisation,
- model comparison UI.

### Phase 7 — Ensemble and risk gates

Build:

- final total score,
- confidence score,
- risk blocks,
- hysteresis,
- signal persistence,
- suggested trade sizing.

### Phase 8 — ChatGPT bridge

Build:

- export pack,
- prompt generator,
- response schema,
- import validator,
- audit page.

### Phase 9 — Packaging

Build:

- Flet build script,
- portable folder layout,
- first-run setup,
- model path configuration,
- diagnostics export.

### Phase 10 — Polish

Build:

- better charts,
- dark mode,
- report export,
- PDF/HTML report optional,
- strategy comparison views,
- watchlist improvements.

---

## 23. References and Source Notes

Use these references to understand why the design choices exist. The app should not hard-code citations into the UI, but the documentation should preserve them.

### Time-series foundation models

- Google Research TimesFM GitHub: https://github.com/google-research/timesfm
  - TimesFM 2.5 uses 200M parameters, supports up to 16k context, and supports quantile forecasts via optional 30M quantile head.
- Hugging Face TimesFM 2.5 model: https://huggingface.co/google/timesfm-2.5-200m-pytorch
- Datadog Toto GitHub: https://github.com/datadog/toto
  - Toto 2.0 is the current recommended release, with 4M to 2.5B models.
- Datadog Toto 2.0 technical report: https://arxiv.org/abs/2605.20119

### App/UI/packaging

- Flet publishing/build docs: https://flet.dev/docs/publish/
- Flet pack docs: https://flet.dev/docs/cli/flet-pack/
- PyInstaller docs: https://pyinstaller.org/
- PyInstaller one-folder/one-file mode: https://pyinstaller.org/en/stable/operating-mode.html
- PySide6 deployment docs: https://doc.qt.io/qtforpython-6/deployment/
- NiceGUI deployment docs: https://nicegui.io/documentation/section_configuration_deployment

### Data/storage

- DuckDB Parquet docs: https://duckdb.org/docs/current/data/parquet/overview.html
- DuckDB read_parquet docs: https://duckdb.org/docs/current/guides/file_formats/query_parquet.html
- Stooq free historical market data: https://stooq.com/db/h/
- EODHD historical data API: https://eodhd.com/financial-apis/api-for-historical-data-and-volumes
- Alpha Vantage ETF Profile endpoint: https://www.alphavantage.co/documentation/

### Finance/research design

- Jegadeesh and Titman, momentum over 3–12 month horizons: https://www-2.rotman.utoronto.ca/~kan/3032/pdf/PredictabilityOfReturns_IntermediateAndLongHorizon/Jegadeesh_Titman_JF_1993.pdf
- Moskowitz, Ooi and Pedersen, time-series momentum: https://elmwealth.com/wp-content/uploads/2017/06/timeseriesmomentum.pdf
- Ledoit and Wolf covariance shrinkage: https://www.ledoit.net/honey.pdf
- Bailey et al., Probability of Backtest Overfitting: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Carr and López de Prado, determining trading rules without backtesting: https://arxiv.org/abs/1408.1159

### ChatGPT manual integration

- OpenAI File Uploads FAQ: https://help.openai.com/en/articles/8555545-file-uploads-faq
- OpenAI Data Analysis with ChatGPT: https://help.openai.com/en/articles/8437071-data-analysis-with-chatgpt
- OpenAI Projects in ChatGPT: https://help.openai.com/en/articles/10169521-projects-in-chatgpt
- OpenAI API and ChatGPT billing separate: https://help.openai.com/en/articles/8156019-how-can-i-move-my-chatgpt-subscription-to-the-api

### Broker/API later

- Interactive Brokers API docs: https://www.interactivebrokers.com/campus/ibkr-api-page/ibkr-api-home/

---

## 24. Final Build Instruction for the Coding Agent

Build the app in this exact priority order:

```text
1. Create the Flet desktop app shell.
2. Implement config loading and folder initialisation.
3. Implement DuckDB/Parquet storage.
4. Implement ETF universe and portfolio target screens.
5. Implement CSV price import and data validation.
6. Implement features: returns, momentum, trend, volatility, drawdown, relative strength.
7. Implement simple baseline signals and action engine.
8. Implement dashboard, portfolio, signals, and ETF detail pages.
9. Implement backtesting with costs and baselines.
10. Implement TimesFM adapter as optional.
11. Implement Toto adapter as optional.
12. Implement ensemble score and risk gates.
13. Implement ChatGPT export/import audit workflow.
14. Implement logging and diagnostics.
15. Package as a portable Windows app folder.
```

The app should be fully usable with only simple baselines. AI models are optional overlays and must never be required for the app to launch.

The final user-facing mental model must be:

```text
This ETF deserves more, less, or the same weight in the portfolio because of current allocation drift, momentum, trend, risk, forecasts, costs, and thesis quality.
```

Never present the app as:

```text
AI knows the future price.
```


---

## 25. Concrete Python Interfaces

The coding agent should create stable interfaces early. This prevents the UI, models, and backtester from becoming tangled.

### 25.1 Core dataclasses

Create `src/etf_cockpit/core/types.py`.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

Action = Literal["buy", "add", "hold", "trim", "sell", "no_trade", "manual_review"]
SignalStatus = Literal["ok", "blocked", "warning", "failed"]
ModelStatus = Literal["ok", "failed", "skipped", "unavailable"]

@dataclass(frozen=True)
class ETFIdentity:
    etf_id: str
    name: str
    isin: str | None
    ticker: str
    exchange: str | None
    currency: str
    role: str
    region: str | None = None
    sector: str | None = None
    theme: str | None = None

@dataclass(frozen=True)
class ForecastResult:
    run_id: str
    model_name: str
    model_version: str
    etf_id: str
    forecast_date: date
    horizon_days: int
    expected_return: float | None
    expected_excess_return: float | None
    q10_return: float | None = None
    q50_return: float | None = None
    q90_return: float | None = None
    forecast_vol: float | None = None
    prob_positive_return: float | None = None
    prob_beat_benchmark: float | None = None
    forecast_drawdown_prob: float | None = None
    status: ModelStatus = "ok"
    error_message: str | None = None

@dataclass(frozen=True)
class ComponentScores:
    momentum: float
    trend: float
    risk: float
    rebalance: float
    relative_strength: float
    toto: float
    timesfm: float
    baseline_ml: float
    chatgpt_thesis: float
    cost_penalty: float
    turnover_penalty: float
    concentration_penalty: float

@dataclass(frozen=True)
class SignalResult:
    run_id: str
    signal_date: date
    etf_id: str
    action: Action
    confidence: float
    total_score: float
    components: ComponentScores
    blocked_by: list[str]
    warnings: list[str]
    reason_short: str
    reason_long: str
    horizon_primary: str
    suggested_trade_value_eur: float | None = None
    suggested_new_weight: float | None = None
    status: SignalStatus = "ok"
```

### 25.2 Service contracts

Create service classes:

```python
class DataService:
    def update_prices(self) -> None: ...
    def load_prices(self, etf_ids: list[str], start: date, end: date): ...
    def validate_prices(self) -> DataQualityReport: ...

class FeatureService:
    def compute_features(self, as_of_date: date) -> FeatureFrame: ...

class ForecastService:
    def run_forecasts(self, as_of_date: date, etf_ids: list[str]) -> list[ForecastResult]: ...

class SignalService:
    def generate_signals(self, as_of_date: date) -> list[SignalResult]: ...

class BacktestService:
    def run_backtest(self, config: BacktestConfig) -> BacktestReport: ...

class ChatGPTBridge:
    def export_review_pack(self, as_of_date: date) -> Path: ...
    def import_audit_json(self, path: Path) -> ChatGPTAudit: ...
```

The UI must call services, not low-level feature/model code.

---

## 26. Flet UI Implementation Details

### 26.1 App shell

Create `src/etf_cockpit/app/flet_app.py`.

Pseudo-structure:

```python
import flet as ft

PAGES = {
    "/": dashboard_page,
    "/portfolio": portfolio_page,
    "/signals": signals_page,
    "/etf": etf_detail_page,
    "/backtests": backtests_page,
    "/chatgpt": chatgpt_page,
    "/data-models": data_models_page,
    "/settings": settings_page,
    "/diagnostics": diagnostics_page,
}

def main(page: ft.Page):
    page.title = "ETF AI Portfolio Cockpit"
    page.theme_mode = ft.ThemeMode.DARK
    page.window_width = 1400
    page.window_height = 900
    page.window_min_width = 1100
    page.window_min_height = 720
    state = AppState.load()

    def route_change(e):
        page.views.clear()
        page.views.append(build_shell(page, state, page.route))
        page.update()

    page.on_route_change = route_change
    page.go("/")
```

### 26.2 Layout dimensions

Target window: 1400 × 900 px.

Layout:

```text
Left sidebar: 220 px
Top header: 64 px
Main content: remaining width
Status bar bottom: 28 px
```

Dashboard content grid:

```text
Row 1: 5 summary cards, equal width
Row 2: action table, full width
Row 3: risk flags left, model status right
```

### 26.3 UI components

Create reusable components:

```text
ActionBadge(action)
ConfidenceBadge(confidence)
RiskFlagBadge(severity)
MetricCard(title, value, subtitle, status)
DriftBar(current, target, soft_band, hard_band)
ScoreHeatCell(score)
ETFSelector()
RunStatusBanner()
```

### 26.4 Colour mapping

```python
ACTION_COLOURS = {
    "buy": "green",
    "add": "lightgreen",
    "hold": "bluegrey",
    "trim": "orange",
    "sell": "red",
    "no_trade": "grey",
    "manual_review": "purple",
}
```

Severity colours:

```text
low = muted blue/grey
medium = amber
high = red
```

### 26.5 Table behaviour

Action table requirements:

- sortable by columns,
- searchable by ETF name/ticker,
- filter by action,
- filter by role,
- click row opens ETF detail page,
- display reason tooltip,
- display blocked gates as chips.

If Flet DataTable becomes limiting, implement a simple custom table with rows and columns first; do not over-engineer.

---

## 27. Chart Specification

Use Plotly or Flet charts. Plotly is preferred for rich charts if it can be embedded. If embedding is awkward, generate static PNG/SVG or simple Flet charts first.

### 27.1 Required charts

Dashboard:

- portfolio allocation bar,
- top positive/negative score bars,
- risk regime sparkline.

Portfolio page:

- current vs target weights horizontal bar chart,
- sector exposure stacked bar,
- region exposure stacked bar,
- currency exposure stacked bar.

ETF detail:

- adjusted price line,
- drawdown area/line,
- rolling volatility line,
- forecast quantile fan if available,
- score history line.

Backtest:

- equity curve,
- drawdown curve,
- monthly returns heatmap,
- rolling Sharpe/Calmar,
- turnover over time.

### 27.2 Forecast fan chart

For each ETF:

```text
x-axis: forecast horizon dates
line: q50 forecast
band: q10 to q90
baseline: current price/return = 0
```

For return forecasts, show cumulative expected return, not price unless explicitly requested.

---

## 28. Data Validation Rules in Detail

### 28.1 Price validation

For each ETF/date:

```text
open > 0
high >= low
high >= max(open, close)
low <= min(open, close)
close > 0
adjusted_close > 0 if required
volume >= 0 or null allowed for some ETFs
```

Block if:

```text
more than 5 consecutive missing trading days without known exchange holiday
latest date older than 2 expected trading days
adjusted_close missing for total-return calculations
currency missing
```

Warn if:

```text
one-day absolute log return > 8 * rolling robust sigma
volume > 10 * rolling median volume
volume == 0 on active trading day
provider changed historical data beyond tolerance
```

### 28.2 Historical data revision detection

When updating data, compare overlapping last 30 days with stored data.

If adjusted prices changed materially:

```text
If abs(new_adjusted_close / old_adjusted_close - 1) > 0.005 → warning
If > 0.02 → data revision alert
```

Store provider revisions in log.

### 28.3 Minimum history

Feature availability:

| Feature | Minimum trading days |
|---|---:|
| 20-day momentum | 21 |
| 60-day momentum | 61 |
| 120-day momentum | 121 |
| 180-day momentum | 181 |
| SMA-200 | 200 |
| main signal | 252 minimum, 504 preferred |
| backtest inclusion | 756 preferred |

If insufficient history:

```text
Action = manual_review or no_trade
Reason = insufficient history
```

---

## 29. Model Runtime Management

### 29.1 Lazy loading

Do not load Toto/TimesFM at app startup unless necessary.

Flow:

```text
Open app → load dashboard with latest cached forecasts
User clicks Run forecasts → load models → forecast → unload or keep cached
```

### 29.2 Device selection

Device setting:

```text
auto | cpu | cuda
```

Auto logic:

```python
if torch.cuda.is_available() and available_vram_sufficient:
    device = "cuda"
else:
    device = "cpu"
```

But never crash if CUDA fails. Fall back to CPU with warning.

### 29.3 Model cache

Cache forecasts by:

```text
model_name
model_version
etf_id
forecast_date
input_hash
horizon_days
```

If input hash unchanged, reuse forecast.

### 29.4 Timeout handling

Model calls must have timeouts:

```text
TimesFM per ETF timeout: configurable, default 60 s
Toto per ETF timeout: configurable, default 180 s
Batch timeout: configurable
```

If timeout:

```text
status = failed
error_message = timeout
fallback = baselines
```

### 29.5 Memory preflight

Before loading model:

- check RAM free,
- check VRAM free if using GPU,
- check model folder size,
- warn if insufficient.

Diagnostics page must show this.

---

## 30. Strategy Variants to Implement

### 30.1 Baseline strategy: target-weight rebalancing

Rules:

```text
If ETF current weight below target - band: add toward target
If above target + band: trim toward target
Else hold
```

### 30.2 Momentum strategy

Rank ETFs by:

```text
0.4 * 3-month momentum + 0.4 * 6-month momentum + 0.2 * 9-month momentum
```

Allocate more to top-ranked ETFs within allowed roles and caps.

### 30.3 Trend-filter strategy

If ETF below SMA-200:

```text
block new buy/add unless strategic core and rebalancing rule says add slowly
```

If ETF above SMA-200:

```text
allow normal add/buy if other gates pass
```

### 30.4 Volatility-target strategy

Scale risk:

```text
TargetWeight_i = BaseTargetWeight_i * TargetVol / ForecastVol_i
```

Cap changes.

### 30.5 Ensemble strategy

Use full score formula and gates.

This is the main app strategy after MVP.

---

## 31. Error Handling and User Messages

The app must prefer understandable errors.

Examples:

```text
Data blocked: EXX1 latest adjusted close is missing. Signals for EXX1 were not generated.
```

```text
TimesFM unavailable: model folder not found. App is using simple baselines only.
```

```text
Trade blocked: expected edge is 0.42%, estimated cost is 0.31%, below required 2.5× cost buffer.
```

```text
Manual review: Toto and TimesFM disagree strongly, while simple momentum is neutral.
```

Never show only stack traces in the UI. Stack traces go to `logs/errors.jsonl`.

---

## 32. Security, Privacy, and Data Safety

### 32.1 Local-first

All portfolio data remains local unless the user explicitly exports a ChatGPT Review Pack or configures a data provider/API.

### 32.2 Secrets

API keys must be stored in `.env` or OS keyring, never committed to Git.

`.env.example`:

```text
EODHD_API_KEY=
ALPHAVANTAGE_API_KEY=
```

### 32.3 ChatGPT export privacy

Before export, app should show:

```text
This pack may contain your holdings, ETF weights, and model outputs. Upload only if you are comfortable sharing this with ChatGPT.
```

Allow anonymisation option:

```text
Replace exact portfolio value with percentages
Remove average cost
Remove cash amount
Keep ETF IDs and weights
```

### 32.4 Backups

Create automatic backups of:

```text
configs/
logs/
data/portfolios/
```

Before major update, copy to:

```text
backups/YYYY-MM-DD_HHMMSS/
```

---

## 33. Report Export

Add export options:

```text
Export weekly dashboard as HTML
Export signal table as CSV
Export ChatGPT pack as ZIP
Export backtest report as HTML/Markdown
Export diagnostics as JSON
```

The weekly report should contain:

```text
- date
- portfolio mode
- actions
- risk flags
- top 5 positive ETF signals
- top 5 negative ETF signals
- model status
- backtest status
- changes since previous week
```

---

## 34. Broker Integration Later

MVP: no broker API, manual execution.

Later optional:

```text
IBKR API
Saxo OpenAPI
Trading 212 API if available/account-supported
```

Do not integrate DEGIRO automation because it does not officially support automated trades/bots.

Broker integration phases:

1. read-only holdings import,
2. paper-trading order simulation,
3. draft order proposal,
4. manual approval,
5. live order placement only after extensive validation.

Hard safety for broker mode:

```text
No market orders by default
Limit order only
Max trade value cap
Daily trade count cap
Kill switch
Duplicate order detection
Manual confirmation
```

---

## 35. Development Commands

### 35.1 Setup

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 35.2 Run app in development

```bash
python scripts/run_app.py
```

### 35.3 Update data

```bash
python scripts/update_data.py --provider stooq
```

### 35.4 Run signals

```bash
python scripts/run_signals.py --date latest
```

### 35.5 Run backtest

```bash
python scripts/run_backtest.py --config configs/backtest_default.yaml
```

### 35.6 Export ChatGPT pack

```bash
python scripts/export_chatgpt_pack.py --date latest
```

### 35.7 Run tests

```bash
pytest tests -q
```

### 35.8 Build Windows folder

```bash
scripts/build_windows.bat
```

Build script should attempt Flet packaging first. If packaging fails due to ML dependencies, create a portable folder with launcher and embedded environment.

---

## 36. Requirements File Draft

Create `requirements.txt` similar to:

```text
flet
pandas
polars
numpy
pyarrow
duckdb
plotly
scikit-learn
pydantic
pyyaml
python-dotenv
requests
rich
pytest
joblib
```

Optional:

```text
lightgbm
xgboost
mlflow
great_expectations
torch
timesfm
```

Toto dependency may need install from official repository/Hugging Face instructions. Keep model dependencies optional and isolated so the app can launch without them.

---

## 37. Definition of Done by Major File

### `data/validation.py`

Done when:

- validates OHLCV,
- validates adjusted close,
- detects stale data,
- flags outliers,
- returns structured report,
- never crashes on one bad ETF.

### `features/feature_pipeline.py`

Done when:

- computes all features as of date,
- uses only past data,
- handles missing values,
- stores features in Parquet,
- passes no-lookahead tests.

### `models/timesfm_adapter.py`

Done when:

- detects availability,
- loads model on demand,
- forecasts one ETF,
- returns standard schema,
- fails gracefully.

### `models/toto_adapter.py`

Done when:

- builds aligned multivariate input,
- forecasts one ETF,
- handles missing channels,
- returns standard schema,
- fails gracefully.

### `signals/scoring.py`

Done when:

- converts features/forecasts into component scores,
- clips/normalises scores,
- applies ensemble weights,
- returns total score.

### `signals/gates.py`

Done when:

- implements all hard risk gates,
- returns block reasons,
- tests confirm blocked actions.

### `backtest/engine.py`

Done when:

- uses same signal pipeline,
- applies costs,
- logs trades,
- compares against baselines,
- outputs metrics.

### `chatgpt_bridge/export_pack.py`

Done when:

- exports all required files,
- creates combined markdown,
- creates zip,
- includes prompt and schema.

### `chatgpt_bridge/import_audit.py`

Done when:

- validates JSON schema,
- rejects invalid ETF IDs/actions,
- logs import,
- exposes audit to UI.

---

## 38. Final User Experience Scenario

### Weekly workflow

1. User opens app.
2. Dashboard shows latest status.
3. User clicks `Update data`.
4. App validates data.
5. User clicks `Run signals`.
6. App computes features and forecasts.
7. Dashboard shows:

```text
Portfolio mode: Neutral
Best action: No trade
Risk flags: EU banks overweight, AI disagreement medium
```

8. User reviews Signals page.
9. User opens ETF detail for flagged ETFs.
10. User exports ChatGPT Review Pack.
11. User uploads pack to ChatGPT 5.5 high.
12. ChatGPT returns audit JSON.
13. User imports audit.
14. App shows ChatGPT audit panel.
15. If action survives all gates, app creates manual trade proposal.
16. User executes manually in broker if desired.
17. App logs the decision.

### Example dashboard output

```text
EXX1 — Hold
Confidence: 0.71
Reason: positive 3-month trend, but already near target and edge below cost-adjusted add threshold.
Blocked by: near_target_weight, low_edge_after_costs

SXRJ — Add small
Confidence: 0.66
Reason: below target, 3-month momentum positive, broad risk acceptable, Toto and baseline agree.
Warnings: TimesFM neutral, liquidity cost estimate stale.

H4ZZ — Trim candidate
Confidence: 0.62
Reason: overweight versus target and 1–3 month expected excess return is weak.
Warnings: do not full sell; trim only if target drift remains after next review.
```

---

## 39. One-Sentence Product Rule

Every screen and every algorithm should support this question:

```text
Does this ETF deserve more, less, or the same weight in the portfolio over the next 1 week to 9 months, after accounting for risk, costs, uncertainty, allocation drift, alternatives, and thesis quality?
```

If a feature does not help answer that question, do not build it yet.
