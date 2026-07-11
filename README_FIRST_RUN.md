# ETF AI Cockpit - First Run

1. Preferred launcher: double-click `ETF_AI_Cockpit.bat`.
2. `ETF_AI_Cockpit.bat` starts the Python launcher from `.venv` first so live local TimesFM/Toto packages and external model folders are available.
3. Direct exe launcher: double-click `Run_ETF_AI_Cockpit_EXE.bat`, or run `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`.
4. If the Python launcher cannot start and the packaged exe exists, `ETF_AI_Cockpit.bat` falls back to the packaged executable.
5. The Python launcher creates or repairs a local `.venv` if needed and installs project dependencies.
6. First launch creates sample data and opens the local dashboard in your browser at `http://127.0.0.1:8550`.
7. Toto and TimesFM are optional. If their model folders or runtime packages are missing, the app uses baseline signals only. The current project has TimesFM 2.5 and Toto 2.0 1B active, with Toto 2.0 4M retained as a small fallback checkpoint under `models\`.

The browser window is intentional. The Flet desktop renderer opened a blank shell on this Windows setup, so the normal launcher uses the local web renderer for reliability.

No broker automation is included. Audit packet export/import is manual and local until you choose to share a packet with an external reviewer yourself. Imported audit responses are commentary only.

## Local verification

Evidence checks are local and read-only. From PowerShell, run the fixed finish
plan and then verify its manifest for a specific issue:

```powershell
python scripts\dev_finish_check.py --changed-paths-file .ai_worklog\changed-paths.txt --json-report evidence\finish-report.json
python scripts\verify_issue.py DATA-05 --evidence-root evidence
```

For an isolated dependency check, use the fail-closed clean-environment
script. It creates an explicit verification virtual environment and can install
the declared requirements when requested:

```powershell
.\scripts\verify_clean_environment.ps1 -EvidenceRoot evidence\clean-environment
.\scripts\verify_clean_environment.ps1 -EvidenceRoot evidence\clean-environment -InstallRequirements
```

Verification returns `pass`, `fail` or `blocked`. Missing tools, stale or
mismatched source/environment hashes, skipped tests, live informational runs,
bad checksums, missing package/browser evidence and incomplete independent
review are `blocked`; they are never treated as a pass. A blocked result keeps
the issue open for a fresh evidence run.

These commands never edit local issue ledgers, change closure status, call a
remote tracker or close an issue automatically. A separate reviewer must
approve a fresh manifest before any issue-status decision is considered.
