# ISSUE-0035 build gate

`cmd /c scripts\\build_windows.bat` ran with the worktree `.venv` junctioned
temporarily to the repository Python 3.13 environment. PyInstaller/Flet native
build completed successfully and produced
`build/flet_dist/ETF_AI_Cockpit/ETF_AI_Cockpit.exe`; the portable output folder
was also created.

The optional `ETF_COCKPIT_BUILD_SMOKE=1` step failed in the existing
fixture-dependent score-group smoke with:

`RuntimeError: Sparebanken group did not preserve AURG needs_verification ISIN.`

This is unrelated to Data Health and is recorded as a closure blocker. Direct
packaged-native launcher verification succeeded on port 8565:

`started mode=portable-native ... ready url=http://127.0.0.1:8565/`

`Invoke-WebRequest http://127.0.0.1:8565/` returned HTTP 200. The temporary
`.venv` junction was removed after the build and generated build outputs remain
ignored.
