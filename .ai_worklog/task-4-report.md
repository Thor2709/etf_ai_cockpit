# Wave 0 Task 4 report - no-execution and rejection boundary

Date: 2026-07-12 (Australia/Sydney)
Branch: `wave0/task4-execution-boundary`
Base: `c5fd053425376508e141f3cef3cc09f72d2fe791`

## Scope and invariants

Task 4 adds a static, context-aware boundary check, a versioned rejection
registry, and three future-only architecture records. It does not add broker
SDKs, order endpoints, credential handling, execution controls, UI scope,
score weights, model authority, issue closure or external uploads. No change to
`src/etf_cockpit/core/types.py` was required. Every report and registry record
keeps `execution_allowed=false` and `executable_authority=false`.

## RED evidence

Required command (PowerShell executes the path with `&` because the workspace
contains a space):

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\scope_boundary\test_execution_boundary.py tests\scope_boundary\test_rejection_registry.py -q
```

Result before implementation: exit code 1, 7 behavioural assertion failures.
The tests collected successfully; failures were the expected missing checker
and registry interfaces (`report is not None` / registry validation), rather
than import or syntax-only errors.

After adding the `OrderRouter`/INI regression, its RED run also failed for the
intended behavioural reason: the report incorrectly returned `pass` for a
camel-case order-router class and an enabled INI authority flag. The fix added
class-name scanning and camel-case normalisation without changing the benign
`sort_order` path.

## Implementation

- `src/etf_cockpit/governance/static_checks.py` defines Pydantic
  `BoundaryViolation` and `ExecutionBoundaryReport`, deterministic relative
  paths/ordering, schema version `1.0`, policy checksum, UTC generation time,
  and explicit false authority fields.
- AST checks reject order-routing symbols (including camel-case class names),
  known broker SDK imports, HTTP calls to order endpoints, credential/endpoint
  names and current UI order-control labels. `sort_order` is not prohibited.
- YAML/JSON/TOML/INI/CFG authority values, dependency manifests and credential
  resources are scanned. `tests/**` and `docs/architecture/future/**` are
  explicit allow-list paths; generated/runtime directories are excluded from
  the production package scan.
- `configs/rejection_registry.yaml` contains three permanent, duplicate-free,
  auditable records (`FUTURE-01`, `FUTURE-03`, `WAVE0-NO-EXECUTION`) with
  decision owners, rationale, timestamps, evidence references and false
  authority fields. `load_rejection_registry` and
  `validate_rejection_registry` enforce the schema.
- Future documents begin with the approved `# Future-only / no-authority`
  banner and contain no credentials or runnable order examples.
- `src/etf_cockpit/governance/__init__.py` makes the new package discoverable by
  setuptools package inventory.

## GREEN and regression evidence

Required GREEN command:

```text
C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe -m pytest tests\scope_boundary tests\test_release_hardening.py -q
```

Result: exit code 0; 40 tests passed (11 scope-boundary tests and 29 release
hardening tests). A run with `-rA` recorded every test as `PASSED`; the only
output warning was the existing pandas `FutureWarning` in
`data/trust_artifacts.py`.

Additional checks:

| Check | Command | Result |
|---|---|---|
| Package inventory | `python -m pytest tests\\scope_boundary\\test_package_inventory.py -q -rA` | 3 passed, exit 0 |
| Release regression | `python -m pytest tests\\release -q` | 2 passed, exit 0 |
| Operations regression | `python -m pytest tests\\operations -q` | passed, exit 0 (one earlier concurrent run was flaky; isolated rerun and clean rerun passed) |
| Scoped Ruff | `ruff check src\\etf_cockpit\\governance tests\\scope_boundary` | All checks passed, exit 0 |
| Compile check | `python -m compileall -q src tests\\scope_boundary` | exit 0 |
| Dependency inventory | `python -m pip check` | No broken requirements found, exit 0 |
| Working-tree whitespace | `git diff --check` | clean |

Current production-tree static report:

```json
{
  "schema_version": "1.0",
  "result": "pass",
  "violations": [],
  "scanned_files": 232,
  "policy_checksum": "e1b6d9198b36cf322b29f7fb2d029e7ee4d6fe2ae418c305b0c0559a3e7e81cc",
  "generated_at": "2026-07-11T14:36:28.356766Z",
  "execution_allowed": false,
  "executable_authority": false
}
```

The injected fixtures fail with the expected codes:
`PROHIBITED_ORDER_SYMBOL`, `PROHIBITED_BROKER_DEPENDENCY`,
`PROHIBITED_ORDER_ENDPOINT`, `PROHIBITED_UI_ORDER_CONTROL`,
`PROHIBITED_CREDENTIAL_RESOURCE` and `EXECUTION_AUTHORITY_ENABLED`.

## SHA-256 manifest

```text
a98a7339e9c53c2d5cec42a604fca269fcc1137912dcbed8697d7468dfa4ab49  src/etf_cockpit/governance/static_checks.py
c0e48dc96377fd172cd28aac4cd28627689db7b575f215dbbcc846900a9974aa  src/etf_cockpit/governance/__init__.py
cb2a14268017efaaf5e155131bbe353a756d5842c07b4528a59d22c4dd3533b1  configs/rejection_registry.yaml
7805473ec1a04c56ce26a9cc028adfc17565bd5ac9533664554e76b18a916816  docs/architecture/future/execution_scope_and_approval.md
4b705a12aef5788e5174800a7c757ff1e7f6f1a800e974ea62014e5e1f767bd5  docs/architecture/future/broker_adapter_contract.md
72be3d5bb3a2d16bc5dcb8dc09ef14922ddecfcc7a7a2dc43e3be2d274e9eb8a  docs/architecture/future/source_of_truth_and_reconciliation.md
26d723e3909335a4eab78c1af5031064c928cef646e5881ee54727fa1ad3ac0f  tests/scope_boundary/test_execution_boundary.py
aa0213a591706a741d15790aff3ae28ffa2addd8a845ed3d43b98b1a6d9b59d8  tests/scope_boundary/test_rejection_registry.py
2827e54e130dc8df3b62e4b9b3c399f92255fa944631f2efc9a443eddcb33db9  tests/scope_boundary/test_package_inventory.py
```

The policy checksum is
`e1b6d9198b36cf322b29f7fb2d029e7ee4d6fe2ae418c305b0c0559a3e7e81cc`; the
registry contains 3 records. No issue status or unrelated tracker record was
modified.

## Final post-fix review boundary

The second focused fix pass added regression coverage for arbitrary dotenv
names, opaque credential-container suffixes, imported order-routing symbols
and indirect order URLs. Its genuine RED and GREEN evidence is recorded in
`.ai_worklog/task-4-fix-pass-2-report.md`. A fresh independent postfix review
is recorded in `.ai_worklog/task-4-review-postfix.md`; it returned
specification-compliance **APPROVED** and code-quality **APPROVED**, with no
Critical, Important or Minor findings. The reviewer verified 53 focused
scope/release tests, release regressions, deterministic production scans,
adversarial fixtures and `execution_allowed=false` / `executable_authority=false`.

The current branch contains the reviewed residual fixes and is ready for its
final commit and integration. Task 4 does not close a local issue; `ISSUE-0040`
and all later issue records remain open. No product authority, broker
capability, credential handling, UI scope or approved coverage changed.
