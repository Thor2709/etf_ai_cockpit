# Changelog

## 0.1.0rc1 - 2026-07-14

First usable Windows release candidate for the local-first ETF AI Evidence
Cockpit. This release includes the evidence, scoring, portfolio, backtest,
universe, provider, audit import/export, backup/restore and diagnostics
workflows implemented through Wave 5 Task 23.

Optional TimesFM/Toto models and internet/API-key-backed providers remain
explicit unavailable states when their external packages, model files or
credentials are absent. Broker execution remains disabled
(`execution_allowed=false`).
