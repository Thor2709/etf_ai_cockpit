# Wave 0 Task 4 focused fix pass 2

Date: 2026-07-12 (Australia/Sydney)
Branch: `wave0/task4-execution-boundary`
Base reviewed implementation: `c7372d3`

## Review findings addressed

- Arbitrary dotenv filenames such as `config.env` are now parsed for both authority flags.
- Opaque production `.pem`, `.key`, `.p12` and `.pfx` resources are rejected as credential resources; future Markdown and test fixtures retain their explicit allow-lists.
- `from helper import place_order` and `from helper import OrderRouter` are rejected as imported order-routing symbols.
- Indirect endpoint calls such as `url = 'https://broker.example/orders'; requests.post(url)` are rejected using deterministic string-binding analysis.

## RED

Tests were added before the production changes. The focused command:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\scope_boundary\test_execution_boundary.py::test_arbitrary_env_and_opaque_credential_resources_are_rejected tests\scope_boundary\test_execution_boundary.py::test_imported_order_symbols_and_indirect_order_url_are_rejected -q --tb=short
```

Exited 1 with two behavioural failures: both temporary trees returned `pass` instead of the required failure report. Collection and imports succeeded; this was not syntax-only RED evidence.

## GREEN and regression evidence

Targeted fix tests passed: 2 passed.

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\scope_boundary tests\test_release_hardening.py -q --tb=short
```

Exit 0. The focused scope/release bundle passed 53 tests after the added regressions.

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\release tests\operations -q --tb=short
```

Exit 0 for release and operations regressions. Scoped Ruff, compileall and pip check all exited 0; `pip check` reported no broken requirements. `git diff --check` is clean.

## Production report

The production-tree static scan returned `pass` with 354 scanned files, zero violations, `execution_allowed=false`, `executable_authority=false` and policy checksum `2962d01d93f9be08c4ec9e9475a54a58c047c5f18c775f5cc49a159d98be6df0`.

No issue status, UI scope, broker capability, credentials or later task artefact changed.
