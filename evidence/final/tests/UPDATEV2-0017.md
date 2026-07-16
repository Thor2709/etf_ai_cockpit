# UPDATEV2-0017 test evidence

Focused parser, persistence, registry, score and file-picker regressions passed after the final source changes; the behavioural coverage is in `tests/test_priips_kid_parser.py`, `tests/test_parsed_disclosures.py` and `tests/test_task15_file_picker.py`. The exact verifier gates also passed: `tests/task15-source-exact-raw.txt` (compileall, SHA-256 `cc258d839e50d5e0cf220528399d5c29a6bcc5c3a9ee2616a915627e0363d91`), `tests/task15-ui-exact-raw.txt` (13 tests, SHA-256 `0a2023c23c5db1bfb80abbe4a8445a398190d2e8c69647081fc47848d964e748`), and the authoritative full suite `tests/task15-full-ui-root-fixes-raw.txt` (SHA-256 `c3316a11ed907503aee27cdb9dd5ec62efad2b2ca355638493c34e098f8d41ef`). Ruff and compileall checks passed; known deprecation warnings are unchanged and non-failing.

RED/GREEN evidence for latest UI registry selection and durable import progress is recorded in `.ai_worklog/task-15-closure-report.md` and `tests/test_task15_file_picker.py`.
