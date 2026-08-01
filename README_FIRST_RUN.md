# ETF AI Cockpit - First Run

1. Preferred launcher: double-click `ETF_AI_Cockpit.bat`.
2. `ETF_AI_Cockpit.bat` starts the Python launcher from `.venv` first so live local TimesFM/Toto packages and external model folders are available.
3. Direct exe launcher: double-click `Run_ETF_AI_Cockpit_EXE.bat`, or run `build\flet_dist\ETF_AI_Cockpit\ETF_AI_Cockpit.exe`.
4. If the Python launcher cannot start and the packaged exe exists, `ETF_AI_Cockpit.bat` falls back to the packaged executable.
5. The Python launcher creates or repairs a local `.venv` if needed and installs project dependencies.
6. First launch creates sample data and opens the local dashboard in your browser at `http://127.0.0.1:8550`.
7. Toto and TimesFM are optional. If their model folders or runtime packages
   are missing, the app uses baseline signals only. Availability depends on
   the local installation and external folders under `models\`; it is not a
   package guarantee.

The browser window is intentional. The Flet desktop renderer opened a blank shell on this Windows setup, so the normal launcher uses the local web renderer for reliability.

No broker automation is included. Audit packet export/import is manual and local until you choose to share a packet with an external reviewer yourself. Imported audit responses are commentary only.

## Local checks

For an ordinary change, run the targeted tests for the affected files and one
local application import/startup smoke check, then apply the E/O/H/C classifier
and its exact-base cadence before review and merge. See
`docs/product-completion/DELIVERY_WORKFLOW.md`; do not defer a gate that the
classifier requires.
