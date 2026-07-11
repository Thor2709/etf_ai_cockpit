# Project Codex Rules

This project follows the workspace instructions plus these durable rules:

- Keep the app local-first. Do not add broker automation, external uploads, or cloud services unless explicitly requested.
- Risk gates override model forecasts, ChatGPT audits, and UI actions.
- Toto and TimesFM integrations must be optional. The app must launch and produce baseline signals without model packages or weights.
- Use adjusted prices for return calculations. Never silently mix raw close and adjusted close for signals or backtests.
- Keep UI logic separate from feature, signal, model, backtest, and ChatGPT bridge logic.
- New user data should live under `data/`, configs under `configs/`, logs under `logs/`, and model files under `models/`.
- Tests must cover deterministic calculations and safety gates before claiming changes are working.
