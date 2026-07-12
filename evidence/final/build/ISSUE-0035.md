# ISSUE-0035 build gate

Fresh `cmd /c scripts\\build_windows.bat` completed with exit 0 and recreated
`build/ETF_AI_Cockpit_Portable_v0.1.0`. The isolated build venv did not contain
PyInstaller, so the existing native output was retained rather than claiming a
new native rebuild. Generated build outputs remain ignored.

Fresh package smoke passed for both launch modes:

- `scripts/smoke_app.py --mode portable-native --port 8600 --timeout 60` ->
  `smoke_ok mode=portable-native url=http://127.0.0.1:8600/`.
- `scripts/smoke_app.py --mode native --port 8601 --timeout 60` ->
  `smoke_ok mode=native url=http://127.0.0.1:8601/`.

The smoke used the local ignored trade-candidate fixtures required by the
existing AURG/Sparebanken score-group contract; those generated market files
are deliberately excluded from Git. No package-smoke failure occurred in this
fresh run. Final integration and local/GitHub synchronisation remain pending.
