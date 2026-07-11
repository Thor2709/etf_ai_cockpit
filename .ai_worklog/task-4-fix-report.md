# Wave 0 Task 4 focused fix pass

Date: 2026-07-12 (Australia/Sydney)
Branch: `wave0/task4-execution-boundary`
Base implementation: `a4f2956` (`feat: enforce wave0 execution boundary`)

## Review findings addressed

This pass addresses every Important finding and the Minor coverage finding in
`task-4-review-1.md` without changing issue status, UI scope, execution
authority or later tasks.

- Production `src/etf_cockpit/data` and `src/etf_cockpit/models` are scanned;
  only intended top-level runtime roots and cache directories are excluded.
- `.pem`, `.key`, `.p12` and `.pfx` resources are included in the text/resource
  inventory and credential checks.
- `.env` and `.env.local` assignments are parsed, and INI/CFG `[DEFAULT]`
  values are inspected for enabled authority flags.
- Registry validation now requires top-level `registry_id`, `policy_version`,
  `last_reviewed`, both false authority literals and a non-empty record list;
  records require scope/review timestamps, false authority literals and
  non-empty string evidence references. File-backed validation rejects absolute,
  escaping or missing evidence paths (retaining optional `#anchor` support).
- The future allow-list covers Markdown documents only (`.md`/`.markdown`);
  executable/configuration files under that directory are scanned. Test
  fixtures remain explicitly allow-listed.
- UI short labels (`Buy`, `Submit`, `Cancel`, `Replace`) are rejected when
  assigned to control/label targets or used by button/control constructors;
  benign `sort_order` and unrelated strings such as `errors='replace'` remain
  clean. Scalar configuration URL values are checked for order endpoints.
- Dynamic `importlib.import_module(...)` broker SDK loads and variant
  `requirements*.txt`/`.in` manifests are checked.

## RED evidence

Behavioural adversarial tests were added before the implementation changes.
The focused RED command initially collected 16 tests and failed 8 expected
behavioural assertions (all failures were bypasses from the independent
review, not import or syntax errors):

```text
python -m pytest tests\scope_boundary\test_execution_boundary.py tests\scope_boundary\test_rejection_registry.py -q
8 failed, 8 passed
```

The regressions cover package-subtree scanning, private-key suffixes, env and
INI defaults, future executable/config bypasses, short UI labels and scalar
URLs, dynamic imports, dependency manifest variants, top-level registry
authority/schema fields, evidence-reference types and missing evidence paths.

## GREEN and regression evidence

Required focused/release command:

```text
python -m pytest tests\scope_boundary tests\test_release_hardening.py -q
51 passed, exit 0
```

Additional checks:

| Check | Command | Result |
|---|---|---|
| Release regression | `python -m pytest tests\\release -q` | 2 passed, exit 0 |
| Operations regression | `python -m pytest tests\\operations -q` | 73 passed, exit 0 |
| Scoped Ruff | `ruff check src\\etf_cockpit\\governance tests\\scope_boundary` | All checks passed, exit 0 |
| Compile check | `python -m compileall -q src tests\\scope_boundary` | exit 0 |
| Dependency inventory | `python -m pip check` | No broken requirements found, exit 0 |
| Working-tree whitespace | `git diff --check` | clean, exit 0 |

The operations suite had one known concurrent-run flake during an earlier
parallel validation; the required isolated rerun above passed cleanly.

## Production static report

The current production-tree scan is deterministic and non-executable:

```json
{
  "schema_version": "1.0",
  "result": "pass",
  "violations": [],
  "scanned_files": 353,
  "policy_checksum": "2962d01d93f9be08c4ec9e9475a54a58c047c5f18c775f5cc49a159d98be6df0",
  "generated_at": "2026-07-11T15:12:43.762427Z",
  "execution_allowed": false,
  "executable_authority": false
}
```

The focused adversarial tests provide fresh evidence that each reviewed
bypass now produces the expected violation code while benign sort/UI strings
and exact future Markdown/test fixture paths retain their intended behaviour.

## Scope manifest

Changed only Task 4 governance source and scope-boundary tests, plus this
fix-pass report. No issue tracker record, production authority field, UI
scope, broker integration, endpoint, credential value or later-task artefact
was changed.
