# Handoff - 2026-07-09 Launcher, Sparebanken, Reliability Execution

## Current State

The approved plan at `docs/superpowers/plans/2026-07-09-launcher-sparebanken-reliability-plan.md` has been executed for the narrow launcher/build/start/browser workflow and Sparebanken grouping scope.

Key results:

- Full pytest suite passes: 129 tests.
- Windows build passes.
- Root BAT launcher reaches readiness and opens the browser.
- Native packaged executable reaches readiness.
- Portable generated runner reaches readiness and opens the browser from the alternate portable output folder.
- Main Simple Scores page renders five grouped sections:
  - Primary tier - ETFs
  - Primary tier - stocks/equity certificates
  - Secondary tier - ETFs
  - Secondary tier - stocks/equity certificates
  - Sparebanken - Norwegian savings-bank equity-certificate issuers
- Sparebanken unknown ISIN values are preserved as `needs_verification`.

## Evidence Files

- `RUN_LOG.md`
- `.ai_worklog/WORKLOG.md`
- `.ai_worklog/CHANGES.md`
- `.ai_worklog/TESTING.md`
- `.ai_worklog/ERRORS_AND_FINDINGS.md`
- `.ai_worklog/DECISIONS.md`
- `browser-main-top.png`
- `browser-mcp-main-sparebanken-groups.png`
- `browser-main-tall.png`
- `browser-main-very-tall.png`
- `browser-row-expand-attempt.png`
- `browser-direct-providers.png`
- `browser-direct-diagnostics.png`

## Post-Review Completion - 2026-07-10

- Corrected `Launch_Latest_ETF_AI_Cockpit.bat` to consume `build\portable_outdir.txt` instead of assuming the fixed portable folder.
- Corrected native staging lock handling, including delayed batch expansion and a durable `build\native_outdir.txt` manifest.
- Final locked-folder stress build selected timestamped native and portable folders, launched the selected packaged executable, returned HTTP 200 and rendered successfully in the in-app browser.
- Fresh verification: 51 focused tests passed, all 131 collected tests passed, compileall passed and source snapshot smoke passed.
- Browser evidence: `browser-final-launch-latest-locked-folders.png`.
- All verification app processes were stopped and test ports were released.

## Git Status

The app root `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit` is still not a Git repository. No commit was created and `git init` was not run.

## Still Open

Keep open:

- all broad product issues selected as the non-previous-21 set unless their full product scope is later implemented;
- all semantic locator/accessibility work beyond current screenshot-based Flet verification;
- SEC EDGAR, ESEF/iXBRL, PRIIPs KID, ETF/index methodology and provider-backed parser workflows until they have real fixtures, tests, UI workflow, export/audit proof and browser smoke evidence.

## Resume Prompt

Continue from `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit`. Read `HANDOFF.md`, `RUN_LOG.md`, `.ai_worklog/WORKLOG.md`, `.ai_worklog/TESTING.md`, `issues/open.md` and `issues/closed.md`. Do not initialise Git. Continue with the next highest-value open issue from `issues/open.md`, preserving the strict close rules for parser/provider workflows and recording fresh command, build and browser evidence before closing anything.

## Final 2026-07-11 Checkpoint

- The final source fixes were rebuilt into `build\ETF_AI_Cockpit_Portable_v0.1.0`; the native executable is under `build\ETF_AI_Cockpit_Portable_v0.1.0\native\ETF_AI_Cockpit\ETF_AI_Cockpit.exe` and the selected root native output is under `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`.
- Fresh smoke passed for source/native/portable modes. Root launcher start/reuse passed on port 8633. Corrected portable launcher verification ran from the package directory and passed start on 8634, non-HTTP busy-port fallback to 8635, and reuse on 8634.
- Fresh Chrome evidence is in `evidence\wave4\browser`; route matrix is `evidence\wave4\browser\followup-route-smoke.txt`. Screenshots cover the main groups, ETF/stock subdivisions, Sparebanken rows and `needs_verification` ISIN states, row expansion, workflow controls, Diagnostics, Evidence Ledger and Audit Notes/export.
- Audit validation is in `evidence\wave4\final-audit-validation-followup.txt`: valid archive, no checksum errors, no secret findings, candle/conflict markers handled, 16 unique holdings with required fields and model advisory provenance present.
- Closure evaluator evidence is `evidence\final\closure-report.json` after the final command below. Honest state: 4 of 41 ready, 37 still open. `ISSUE-0069`, `UPDATEV2-0022` and `UPDATEV2-0028` are now closed alongside the already-closed `ISSUE-0035`. No strict SEC EDGAR, ESEF/iXBRL, PRIIPs KID, index-methodology or provider-backed workflow was paper-closed.
- Computer Use did not pass because Windows URL-confidence policy stopped the attempt. Chrome and HTTP fallback evidence is recorded; any Computer-Use-required issue remains open.
- No Git repository exists. No commit was created and `git init` was not run.

## Exact Resume Prompt

Continue from `C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit`. Read `HANDOFF.md`, `RUN_STATE.json`, `issues/open.md`, `issues/closed.md` and `docs\superpowers\plans\2026-07-10-all-41-issues-closure-plan.md`. Keep the no-Git constraint. Start with the next highest-value open issue, implement it with test-first coverage, run source/native/portable and Chrome/computer-use verification where possible, update the evidence dossier and closure evaluator, and close it only when every required gate is fresh. Keep SEC EDGAR, ESEF/iXBRL, PRIIPs KID, index-methodology and provider-backed workflows open unless real fixtures, parser tests, UI workflow, export/audit proof, rebuild and browser smoke all pass.

## Active All-41 Closure Train - 2026-07-11

- Source of truth: `docs\superpowers\plans\2026-07-10-all-41-issues-closure-plan.md`.
- Tasks 1-3 are complete; the current task is the Wave 8 trust-policy review-fix rebuild and evidence refresh.
- Durable state and exact next command are in `RUN_STATE.json`.
- Current verified baseline is 259 passing tests after the trust-policy fixes, passing compileall and passing scoped Ruff.
- Current honest closure state is 1/41 ready (`ISSUE-0035`); no issue is closed before its final dossier and package/browser gates pass.
- Task 2's source/dependency/fixture tests pass; native parser packaging proof remains pending until the Wave 1 Windows build gate.

## 2026-07-11 Resume Checkpoint

- Latest focused trust-policy tests pass, including session/audit redaction, explicit unavailable markers, source/status/model score eligibility and conflict/full-holdings audit export.
- Full pytest pass is recorded in `evidence\\wave4\\full-pytest-trust-fix.txt`; compileall and scoped Ruff pass. The repository-wide Ruff baseline remains non-zero in unrelated scripts.
- Next exact command: `.\\scripts\\build_windows.bat`.
- After the build, rerun source/native/portable smoke, root and portable BAT launcher checks, fresh Chrome screenshots for grouped rows/expansion/diagnostics/audit export, validate the fresh ZIP, then decide closure only for issues whose strict gates are complete.
