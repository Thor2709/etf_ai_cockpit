# Operator runbook and troubleshooting

Release version: `0.1.0rc1`.

For the person running a local installation. The application is local-first and
`execution_allowed=false`; nothing here involves a broker or live orders. Paper
ledger incidents are covered separately in the
[incident runbooks](INCIDENT_RUNBOOKS.md). Task walkthroughs are in the
[tutorials](../user/TUTORIALS.md).

## Where things live

All paths are relative to the installation root (the extracted release folder,
or the repository root for a source checkout).

| Path | Content |
| --- | --- |
| `configs/` | Local YAML/JSON settings, including the universe store. |
| `data/` | Raw, clean, validated, derived, forecast, backtest, portfolio and operations data (paper ledger under `data/operations/paper/`). |
| `models/` | Optional model weights, kept outside the packaged executable. |
| `logs/session.jsonl` | Action trace shown on Diagnostics (keeps the latest 5,000 events). |
| `exports/`, `backups/` | Default destinations for exports and plain backups. |

Keep `data/`, `configs/` and any backup together when you move or restore an
installation.

## Start, stop and check

- Packaged release: run `Run_ETF_AI_Cockpit_EXE.bat`; it selects or reuses a
  local port and opens your browser. Do not run it from inside the ZIP.
- Source checkout: `python scripts/run_app.py`. The default address is
  `http://127.0.0.1:8550`; `ETF_COCKPIT_PORT` (1024-65535) changes the port and
  `ETF_COCKPIT_VIEW=desktop` selects the native renderer, which can show a
  blank window on some Windows systems. The browser mode binds to loopback only.
- Stop the application by ending its process: close its console window, or press Ctrl+C in a source run.
- Quick health check without the UI: `python scripts/run_app.py --smoke`.
  End-to-end route check: `python scripts/smoke_app.py --mode source` (other
  modes: `native`, `portable-native`, `launcher`, `first-run`, `offline`).
- In the application: Diagnostics (runtime, packages, security policy, session
  log), Data Health (store classification), Provider Status (capability, cache,
  failure) and Jobs & Activity (durable jobs).

## Routine procedures

*Daily or before analysis.* Open Data Health and Provider Status. A store
that is stale, missing, corrupt or schema-mismatched is not analysed silently;
fix or re-import it first. Optional provider failures and quota errors are
visible and non-blocking.

*Refresh data.* Use **Renew/import local files** on Simple Scores for local
files, or the optional yfinance refresh when a network is available. Imports are
validated before they replace clean data; **Rollback prices** restores the
previous clean price snapshot.

*Back up.* Create an encrypted backup on Settings and validate it, or a plain
archive on Import & Export; run **Run recovery drill** after changing keys or
storage location. See tutorial 6. Back up before every update.

*Update the application.* Updates are applied locally. Build or obtain the new
package, record its version and SHA-256 checksum, back up `data/` and
`configs/`, install it, run the restore and startup smoke check, and keep the
changelog. Settings shows release metadata and offline update verification;
unsigned, tampered or path-unsafe bundles are rejected before staging.

*Validate an installation (maintainers).* `python scripts/validate_app.py
--offline` runs the offline scope; `--quick`, `--changed`, `--full` and
`--packaged` are the other scopes. `python scripts/issue0014_workflow.py` runs
the complete deterministic offline workflow contract. The protected release
gate is `python scripts/release_gate.py`; see
[release gate](../architecture/release-gate.md).

## Troubleshooting

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| Browser window is blank, or the page does not load | Native renderer selected, port in use or app not running | Open `http://127.0.0.1:8550` in a browser; unset `ETF_COCKPIT_VIEW` or set it to `web`; set another `ETF_COCKPIT_PORT`; rerun `python scripts/run_app.py --smoke` and read the error. |
| `Route unavailable` | Link to an unregistered route | Pick a page from the dock or **Command palette**; see [Workspaces](../user/WORKSPACES.md). |
| Scores show `N/A` or `not scoreable` | Required evidence missing, stale or conflicted | Data Health and Provider Status show which input is missing; import it. `N/A` is not zero. |
| No prices after First-run Setup | Sample bootstrap has no prices; bulk bootstrap only validates the file | Import prices on Simple Scores (**Import prices**). |
| Safety rail shows `Unavailable` | Snapshot has no value for that item | Hover for the reason; refresh or re-import data. |
| Provider failed or quota exceeded | Optional provider, network or key | Provider Status shows the state; continue with local files. No silent retry happens. |
| TimesFM or Toto shows unavailable | Package or weights missing | Expected; the deterministic baseline stays active. Install `requirements-models.txt` and place weights under `models/` only if you want them. |
| Imported file rejected | Missing adjusted-close column, bad mapping or failed validation | Read the preview errors on Import & Export or the dashboard dialog; fix the source file and preview again. Nothing is committed until the preview passes. |
| Restore preview or encrypted-backup validation fails | Corrupt archive, checksum mismatch or wrong recovery key | The operation fails closed and writes nothing. Retry with the correct key or another backup. |
| A job is stuck or failed | Expired lease or failed input | Jobs & Activity: **Recover expired leases**, **Run durable self-check**. A failed or cancelled job is not a result; inspect its inputs before a deliberate retry. |
| Paper order state unknown, ledger or journal integrity error | Disconnect, contradictory event or tampering | Stop paper actions and follow the [incident runbooks](INCIDENT_RUNBOOKS.md). Do not edit ledger files. |
| Action seems to hang | Long-running action | The progress strip shows the current step; **Cancel** stops it. Check `logs/session.jsonl` on Diagnostics. |
| Optional parser features fail (filings, PDF, RSS) | Parser extras not installed | `python -m pip install -e ".[parsers]"`, or use the local files path. |

When reporting a problem, record the visible message, the data as-of date, the
app version (Settings), and the relevant lines from Diagnostics. Keep the
original inputs and logs; Errors & Recovery gives guidance only and takes no
automatic recovery action.

## Privacy and secrets

Standard exports omit private fields, credentials and recovery keys. Private
data lives under `data/private/`; deleting it needs the exact confirmation
phrase shown on Settings. Credentials saved on Settings are never displayed.
Do not paste secrets into notes, imports or issue reports. See
[privacy, backup and recovery](../architecture/privacy-backup-recovery.md) and
the [security policy](../architecture/security-policy.md).
