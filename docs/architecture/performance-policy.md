# Performance and Caching Policy

This document defines the performance, latency, memory, and cache-invalidation
policy for the ETF AI Cockpit, implementing ISSUE-0039. It establishes versioned
resource budgets, lazy loading rules for optional machine learning models, safe
cache invalidation guarantees, and observability mechanisms for long-running
operations.

## Scope and Non-Goals

The cockpit is a local-first application where `execution_allowed=false` is strictly
enforced. Non-goals include:
- No live broker connections, automated trading, or external order dispatch.
- No network telemetry or external network calls during performance measurement
  or budget evaluation (`network_calls: False` in `src/etf_cockpit/core/performance.py`).

## Performance Budgets

Performance budgets and regression tolerances are declared in
`configs/performance_budgets.yaml` under schema `performance-budgets.v1`.

| metric_id | limit | unit | tolerance |
|---|---:|---|---:|
| `startup_cold` | 5000 | ms | 10% |
| `first_durable_event` | 2000 | ms | 10% |
| `route_render` | 1000 | ms | 10% |
| `common_query` | 500 | ms | 10% |
| `refresh` | 10000 | ms | 10% |
| `algorithm_scores` | 30000 | ms | 10% |
| `screen_100` | 1000 | ms | 10% |
| `screen_1000` | 3000 | ms | 10% |
| `screen_10000` | 10000 | ms | 10% |
| `backtest` | 30000 | ms | 10% |
| `training` | 120000 | ms | 10% |
| `app_peak_memory` | 1024 | MiB | 10% |
| `local_storage` | 10737418240 | bytes | 10% |

### Enforcement and Release Blocking

As implemented in `src/etf_cockpit/core/performance.py`:
- Each budget defines an upper threshold equal to `limit * (1 + tolerance_pct / 100)`.
- If an observed measurement exceeds the threshold, or if observed regression against
  a non-zero baseline exceeds `tolerance_pct`, `evaluate_budget()` marks the metric as `failed`.
- `build_performance_report()` evaluates all metrics; if any budget is exceeded, the metric
  is recorded in `failures` and the overall report status evaluates to `failed`.
- An over-budget result blocks release validation.

## Lazy Heavy Imports

To preserve cold startup latency (`startup_cold` budget limit of 5000 ms), optional
heavy machine learning packages must never be imported at top level. They must be
loaded lazily inside adapter methods only when execution or capability checks require them:
- `src/etf_cockpit/models/timesfm_adapter.py`:
  - `transformers` and `timesfm` are imported dynamically via `__import__` in
    `_backend_available()`, `_load_transformers_model()`, and `_load_timesfm_package_model()`.
  - `torch` is imported lazily inside `_forecast_with_transformers()` and `_torch_cuda_available()`.
  - `accelerate` is probed via `find_spec` rather than direct top-level import.
- `src/etf_cockpit/models/toto_adapter.py`:
  - `toto2` is imported dynamically via `__import__` inside `is_available()` and `load_model()`.
  - `torch` is imported dynamically inside `load_model()` and `_forecast_live()`.

When optional dependencies or local checkpoints are absent, adapters report `unavailable`
or fall back to deterministic baselines without crashing.

## Cache Invalidation

The following caches and invalidation paths are verified in the codebase:
1. **Bulk Source Cache (`src/etf_cockpit/data/bulk_cache.py`, `docs/architecture/bulk-cache.md`)**:
   - Stores immutable, content-addressed files under `data/raw/bulk_cache/objects/sha256/`
     with JSON manifests in `data/raw/bulk_cache/manifests/`.
   - **Invalidation**: When a download or ingest produces a SHA-256 digest differing from
     the previous manifest, an invalidation record is appended to
     `data/raw/bulk_cache/manifests/invalidations.jsonl` with `previous_sha256`, `current_sha256`,
     and `occurred_at`. Downstream parsers write to `staging/` and only reach published
     use through `promote_generation()`.
2. **In-Memory Universe Snapshot (`src/etf_cockpit/app/state.py`)**:
   - In-memory dataframes (`prices`, `holdings`, `features`, `forecasts`, `signals`, `backtest`).
   - **Invalidation**: `apply_universe_config()` filters dataframes to active universe IDs,
     sets `universe_cache_revision`, and clears cached backtest results with `quality_label="stale_universe"`.
3. **Classification Invalidation (`src/etf_cockpit/app/state.py`)**:
   - Scores and signals dependent on instrument classification.
   - **Invalidation**: `invalidate_classification_scores()` strips matching or out-of-date
     signals from `snapshot.signals` and resets `selected_instrument_score`.
4. **Other Caches**:
   - Not documented here.

## Responsiveness and Progress

To prevent long workflows from freezing the UI:
- `AppState` in `src/etf_cockpit/app/state.py` manages lifecycle state via `ActivityEntry`
  and `WorkflowController`, protected by `_activity_lock` (`threading.RLock`) and thread-local
  tracking (`_activity_context`).
- Step-by-step progress is emitted through `update_activity(step, message, completed_units, total_units, output_path)`,
  updating completed versus total work units without blocking user interaction.
- Every workflow step is individually measured via `timed_step()` and logged to `logs/session.jsonl`
  via `activity_update` events.

## Timing Logs and Slow-Step Visibility

Execution durations and cache events are tracked using `src/etf_cockpit/core/timing.py`:
- `timed_step(action_id, step_name, slow_ms=1000)` records elapsed wall time in milliseconds.
- Timing records are appended to `logs/timings.jsonl` with `action_id`, `step`, `duration_ms`,
  and a boolean `slow` flag.
- **Slow Threshold**: Any step taking >= 1000 ms (`slow_ms = 1000`) is flagged as `slow: true`
  and logged as a warning event in the session trace.
- **UI Visibility**:
  - **Diagnostics (`src/etf_cockpit/app/pages/diagnostics.py`)**: The Performance and Recovery
    panel shows parsed timing record counts, duration summaries, total slow step count,
    cache hit/miss/invalidation counts, versioned budget status, and the most recent 6 step
    or cache records.
  - **Data Health (`src/etf_cockpit/app/pages/data_health.py`)**: Displays bulk cache health
    metrics including object count, manifest count, staged files, and promoted generations.

## Enforced by tests

- `tests/test_performance_budgets.py`
- `tests/test_bulk_cache.py`
- `tests/test_performance_policy.py`
