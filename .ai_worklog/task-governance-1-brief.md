### Task 1: Define and load governance policies fail closed

**Files:**

- Create: `configs/product_governance.yaml`, `configs/feature_registry.yaml`, `configs/strategy_scope.yaml`, `configs/gate_policy.yaml`, `configs/glossary.yaml`, `src/etf_cockpit/governance/models.py`, `src/etf_cockpit/governance/product_scope.py`
- Test: `tests/test_product_governance.py`, `tests/test_feature_registry.py`, `tests/test_strategy_scope.py`, `tests/test_gate_policy.py`

**Consumes:** foundation wave checksum/evidence facilities.

**Produces:** validated, checksum-bearing policy objects and diagnostic fail-closed loading mode.

- [ ] **Step 1: Create failing policy tests**

```python
def test_execution_enabled_governance_configuration_is_rejected(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, {"authority": {"order_transmission": True}})
    with pytest.raises(ValidationError, match="order_transmission"):
        load_product_governance(path)

def test_experimental_strategy_cannot_have_positive_score_authority() -> None:
    with pytest.raises(ValidationError, match="score_authority"):
        StrategyScopeEntry(lifecycle="experimental", score_authority=True)
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q`

Expected: FAIL because governance policy models and files are absent.

- [ ] **Step 3: Implement immutable policy models and checksum loading**

All loaders return a Pydantic object, schema version and SHA-256 checksum. An invalid or absent policy yields `GovernanceLoadResult(diagnostic_mode=True)` with `manual_review`/`not_scoreable`, no research promotion and no portfolio review.

- [ ] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_product_governance.py tests\test_feature_registry.py tests\test_strategy_scope.py tests\test_gate_policy.py -q`

Expected: PASS; every production route and user-visible subsystem has one feature registry entry, and prohibited authority combinations fail validation.

- [ ] **Step 5: Checkpoint policy provenance**

Generate `evidence/governance/policy_checksums.json` with no secret values and attach it to the wave ledger.
