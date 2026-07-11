# Implementation Notes

## Stack

The implementation follows the master spec stack:

- Python package under `src/etf_cockpit`.
- Flet desktop UI.
- Pandas/NumPy for deterministic calculations.
- DuckDB plus Parquet for local storage.
- Pydantic and YAML for config and ChatGPT audit validation.
- Pytest for calculation, risk-gate, data-quality, no-lookahead, backtest and import tests.

## AI Models

Toto and TimesFM are implemented as optional adapters with disabled/mock modes. The app does not import model packages at startup. Missing packages, missing model paths or runtime failures return structured unavailable/failed forecast results and the signal engine redistributes score weights to deterministic baselines.

This is intentional: the cockpit must remain useful with baseline momentum, trend, risk and rebalancing signals before large local forecasting models are installed.

## Packaging

The default package target is a portable Windows folder, not a single-file executable. A single file is fragile for PyTorch-scale model stacks, slow to extract, awkward for writable data/config/log folders and difficult to update. The build script documents both the Flet packaging attempt and the portable fallback folder.

## Data Source

The configured market-data source is Yahoo Finance through `yfinance`. Prices, available Yahoo fund metadata and available top-holdings are fetched, validated and committed before algorithms, backtests and TimesFM/Toto forecasts run. Yahoo fund data is not treated as issuer-grade factsheet data when Yahoo does not expose source dates or full holdings; the UI and reports mark those limitations.

The deterministic sample-data generator is retained for fallback/testing and for fresh environments before a yfinance refresh has populated the clean store.

## Scope Boundaries

The app does not execute trades, automate a broker, make day-trading signals or present forecasts as future price certainty. Every action includes supporting metrics, blocked gates, confidence, horizon and explanation.
