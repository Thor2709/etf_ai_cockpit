# ETF AI Cockpit — Open-source integration intake (15 November 2026)

This research handoff contains **28 implementation issue proposals** derived from a complete 210-feature / 79-codebase audit. These proposals have not been admitted to the existing Git-canonical programme. Their `INT-xx` identifiers are **provisional**, not canonical `ISSUE-xxxx` IDs. All requested integration remains `execution_allowed=false`.

## Source and status
- Baseline for source-path and line checks: `1afe17c09fb53299f7c46459254d94ce8323acd1`.
- Validated 82 existing target files; 23 expected new target files; 118 in-scope source-line anchors.
- Original ZIP and supporting trace/report: https://drive.google.com/file/d/1IOeqUWT3NoH5gx14_LSLEEOWz32lp7MT/view?usp=drivesdk
- Full updated plan ZIP: https://drive.google.com/file/d/1uJOlx8PWnfCrpkxtWATESgmxtw0Xd8ye/view?usp=drivesdk

## How to authorise
`AGENTS.md`, `docs/development/CONTROL_PLANE.md` and `docs/product-completion/DELIVERY_WORKFLOW.md` govern the programme. Root must inspect duplicates and current issue/lifecycle state, then use `issues/programme_control_state.json` `canonical_definition`, the reviewed `registry_migration` guard, `scripts/generate_programme.py`, and checksum-reviewed `scripts/sync_github_issues.py`. **Do not edit the generated registry or mark proposed work ready by creating a GitHub issue.**

## Priorities
- P0: INT-01 (approved quant/pypdf only), INT-02.
- P1: INT-03, 04, 05, 06, 07 (data-blocked), 08, 09, 20 (data-blocked).
- P2/P3/P4: later capabilities; see issue manifest.
- Future dependency approvals needed: `sec`, `documents`, `retrieval`, `chronos-forecasting`. These are **not approved** by the existing U1 decision.

## Restrictions
Only observed point-in-time rows can train and validate. Existing canonical score, DCF, optimiser API, and B0-B3 bots remain the authority. No live trading, no third-party network-fetch bypass, no implied commercial data rights.
