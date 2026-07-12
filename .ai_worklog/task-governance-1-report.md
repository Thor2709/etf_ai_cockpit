# Wave 1 Governance Task 1 implementation report

## Boundary and ownership

Task: Wave 1 Governance Task 1 - define and load governance policies fail
closed. Branch: `wave1/governance-task1`. Base: `3922afc48fb21ab22465ad890733caa5e0717afc`.
Implementation commit: `9081909c9c2e5b679fcf11b8f7203560d17e3d51`.
This task establishes policy contracts only. It does not migrate legacy action
types, add the governance routes, create the Decision Journal, change issue
ledgers or close `ISSUE-0008`, `ISSUE-0015`, `ISSUE-0030`, `ISSUE-0043` or
`ISSUE-0047`; those requirements remain open for their later governance tasks
and complete source/UI/package/browser evidence.

The product boundary is preserved: every policy and load result carries
`execution_allowed: false`; no broker, order, credential or external-upload
capability was added.

## RED - observed before policy implementation

Command:

```powershell
& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q
```

Result: exit 1 during collection with four genuine missing-module failures:
`etf_cockpit.governance.models` and `etf_cockpit.governance.product_scope` did
not exist. The tests were not syntactically invalid and did not pass before
the implementation.

## GREEN and refactor evidence

- Focused policy suite after implementation and contract hardening: exit 0,
  18 passed.
- Wider affected regression:
  `tests/test_product_governance.py tests/test_feature_registry.py
  tests/test_strategy_scope.py tests/test_gate_policy.py
  tests/test_closure_matrix.py tests/test_release_hardening.py
  tests/operations/test_verification_records.py`: exit 0, 64 passed.
- Ruff:
  `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m ruff check src/etf_cockpit/governance tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py`
  -> exit 0.
- Compilation:
  `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m compileall -q src/etf_cockpit/governance tests/test_product_governance.py tests/test_feature_registry.py tests/test_strategy_scope.py tests/test_gate_policy.py`
  -> exit 0.
- Dependency check:
  `& 'C:\Users\thor2\Desktop\Trading App\etf_ai_cockpit\.venv\Scripts\python.exe' -m pip check`
  -> `No broken requirements found.`
- Policy provenance validator: five YAML SHA-256 values in
  `evidence/governance/policy_checksums.json` matched their source bytes and
  the manifest authority field is false.

The full authoritative suite was rerun for regression comparison: 323 tests
were collected, 316 passed and the same seven generated-data/identity failures
as the clean baseline remained. They are unrelated to this policy task:
missing generated trade-candidate CSV, absent secondary-tier rows, missing
AURG/MSFT fixture rows and the 16-row identity fixture versus its historical
45-row assertion. No new failure was introduced.

## Delivered contract

- `src/etf_cockpit/governance/models.py` contains frozen, extra-forbidden
  Pydantic policy models, exact lifecycle/authority/severity vocabularies,
  literal-false execution fields, uniqueness/order checks and contradiction
  validators.
- `src/etf_cockpit/governance/product_scope.py` loads all five local policies,
  records source SHA-256 checksums and returns a diagnostic fail-closed result
  for missing, malformed or incomplete files. Explicit positive authority
  requests remain validation errors.
- `configs/product_governance.yaml` is the canonical product statement and
  authority boundary; feature, strategy, gate and glossary registries are
  versioned and include the route/strategy/lifecycle evidence needed by later
  governance tasks.
- `evidence/governance/policy_checksums.json` records the five policy paths,
  SHA-256 values, source checkpoint and `execution_allowed: false` without
  secrets.
- Four focused test modules exercise valid loading, checksums, immutability,
  missing/invalid diagnostic mode, duplicate routes/IDs/orders, lifecycle and
  authority contradictions and production-route coverage.

## Compatibility and limitations

The loader accepts the repository plan's `features`, `strategies`, `gates` and
`glossary` YAML collection keys while normalising them to typed `entries`.
Invalid or absent policies never become supported defaults: they return
`manual_review`/`not_scoreable`, no research promotion and no portfolio review.
Legacy action migration, central authority resolution, Decision Journal
persistence, visible governance pages and package/browser evidence are
explicitly deferred to Governance Tasks 2-5; they were not silently treated as
complete here.

## Source checksums at review handoff

| Path | SHA-256 |
|---|---|
| `src/etf_cockpit/governance/models.py` | `d2558d4afa42a4379acc98c255b53c5526569f09fac624790fdc5009f37912be` |
| `src/etf_cockpit/governance/product_scope.py` | `345f4f7c60c637eb521c592fe9659cf586bf735adeba22afc331b6ee7a886f8c` |
| `tests/test_product_governance.py` | `7b717db7c7902a02a18db76a929cdc6df363ebafdb765ed29b30f17b77fab2d2` |
| `tests/test_feature_registry.py` | `0898a8f9264105945a5eb8f433ba06288c94c1da9e8bfc89d2c3d2d1d31aa732` |
| `tests/test_strategy_scope.py` | `de3af7455a57236189aac7cd7c567f005e9328e48fc1870510555af7477044cc` |
| `tests/test_gate_policy.py` | `002eaa30f22edcff53caa18d0377b6c6cb7f076f8c96140415e8bfa60eb598d7` |

## Review handoff

The branch is ready for a fresh independent review of specification
compliance and code quality. The reviewer must check the exact lifecycle and
authority vocabularies, fail-closed behaviour, policy checksums, route
coverage, no-authority invariant and the stated seven-test baseline.
