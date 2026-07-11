# Wave 0 Task 1 Final Review - Round 3

## Result

**Task quality: Needs fixes.** Product behaviour, migration scope, actor validation, current RUN_STATE/TESTING/ledger hashes and no-closure state are compliant. The durable PLAN checkpoint remains incomplete and has ambiguous command escaping.

## Important finding - must fix

- Append a current, unambiguous Task 1 correction block to `.ai_worklog/PLAN.md` that contains all exact PowerShell commands and individual exit codes from the actor-validation fix:
  - RED `./.venv/Scripts/python.exe -m pytest tests/operations/test_verification_records.py -q` - exit 1;
  - GREEN `./.venv/Scripts/python.exe -m pytest tests/operations/test_verification_records.py tests/release/test_issue_evidence.py tests/test_closure_matrix.py -q` - exit 0, 18 passed;
  - Ruff `./.venv/Scripts/python.exe -m ruff check src/etf_cockpit/operations/models.py tests/operations/test_verification_records.py` - exit 0;
  - compile `./.venv/Scripts/python.exe -m compileall -q src/etf_cockpit/operations` - exit 0.
- Use the slash-form commands verbatim above to eliminate Markdown/backslash ambiguity. Include the current model checksum `77031736fd073a4c3ad169d2fa9ec9e9c2bfa4b9d745a4adbf7163465d442294`, programme schema 2, historic baseline 41, 42 active records, DATA-05 `still_open`, no issue closure and a truthful fresh-re-review-pending state.
- Correct the matching ambiguous doubled-backslash assertion in `.ai_worklog/task-1-report.md`.

## Minor retained for broad final triage

- Closure-matrix metadata validation accepts unsupported versions and impossible historic baseline counts.

## Evidence limitation

- The reviewer did not rerun pytest because no concrete behavioural doubt arose; retained 18-pass, Ruff and compile evidence remains documentary until the task is fully reviewed.
