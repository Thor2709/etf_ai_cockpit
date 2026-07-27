# Implementation Notes

The [current SDD](docs/architecture/SDD.md) is the architecture authority.

## Stack

The Python 3.11+ package uses layered presentation, typed in-process
application contracts, deterministic domain/calculation services and
provider/persistence infrastructure:

- Python package under `src/etf_cockpit`.
- Flet loopback browser UI (with optional native renderer).
- Pandas/NumPy for deterministic calculations.
- Immutable Parquet/DuckDB analytical generations plus SQLite, JSONL and
  atomic-file transactional state.
- Pydantic and YAML for config and ChatGPT audit validation.
- Pytest for calculation, risk-gate, data-quality, no-lookahead, backtest and import tests.

## AI Models

Toto and TimesFM are implemented as optional adapters with disabled/mock modes. The app does not import model packages at startup. Missing packages, missing model paths or runtime failures return structured unavailable/failed forecast results and the signal engine redistributes score weights to deterministic baselines.

This is intentional: the cockpit must remain useful with baseline momentum, trend, risk and rebalancing signals before large local forecasting models are installed.

## Packaging

The default package target is a portable Windows folder, not a single-file executable. A single file is fragile for PyTorch-scale model stacks, slow to extract, awkward for writable data/config/log folders and difficult to update. The build script documents both the Flet packaging attempt and the portable fallback folder.

## Providers and data

Providers are policy-labelled and optional. Yahoo Finance remains a configured
convenience source; official/public adapters, imports and cached evidence have
explicit provenance, chronology and conflict rules. Data is validated and
canonicalised before calculations. Yahoo fund data is not issuer-grade when
source dates or full holdings are absent.

The deterministic sample-data generator is retained for fallback/testing and for fresh environments before a yfinance refresh has populated the clean store.

## Scope Boundaries

The app does not execute trades, automate a broker, make day-trading signals or present forecasts as future price certainty. Every action includes supporting metrics, blocked gates, confidence, horizon and explanation.

Packaging targets a writable Windows folder and local browser runtime; external
model weights stay outside the immutable payload. Current certification is
narrower than the canonical multi-asset programme.
