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

<!-- BEGIN GENERATED FINAL RELEASE CONTROL PLANE -->
## 2026-07-21 — Final-release control-plane intake

- Adopted the versioned final-release specification and provisional collision-free `ISSUE-0153`–`ISSUE-0176` contracts without implementing their downstream product features.
- Added typed, status-independent dependency-edge readiness, separate activation readiness, dynamic registry/phase/count validation, and deterministic source-derived programme projections.
- Preserved `execution_allowed=false`; no GitHub apply, live order, deployment, publication or release action is part of this change.
<!-- END GENERATED FINAL RELEASE CONTROL PLANE -->
