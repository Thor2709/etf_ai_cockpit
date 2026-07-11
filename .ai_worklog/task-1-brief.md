### Task 1: Establish typed verification and closure evidence records

**Files:**

- Create: `src/etf_cockpit/operations/__init__.py`, `src/etf_cockpit/operations/models.py`, `tests/operations/test_verification_records.py`, `tests/release/test_issue_evidence.py`
- Modify: `src/etf_cockpit/core/closure.py:1-133`, `configs/closure_matrix.yaml:1-end`, `tests/test_closure_matrix.py:1-end` (migration of the existing exact-41 regression to assert 42 active records while preserving the historic 41-ID baseline)

**Consumes:** existing `ClosureMatrix` parser and the 41-record list.

**Produces:** versioned evidence records which later plans attach to without changing issue state.

- [ ] **Step 1: Write the failing evidence-validation tests**

```python
def test_closure_evidence_rejects_builder_as_required_independent_reviewer() -> None:
    with pytest.raises(ValidationError, match="independent_reviewer"):
        ClosureEvidenceRecord(
            closure_evidence_id="ce-1", issue_id="DATA-05", requirement_version="2026-07-11",
            verification_run_ids=["vr-1"], builder="implementer", independent_reviewer="implementer",
            review_result="approved", evidence_hash="a" * 64,
        )

def test_new_data05_record_does_not_rewrite_the_historic_41_baseline() -> None:
    matrix = load_closure_matrix(path)
    assert matrix.programme_schema_version == 2
    assert matrix.historic_baseline_count == 41
    assert matrix.record_for("DATA-05").status == "still_open"
```

- [ ] **Step 2: Run the focused RED suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py -q`

Expected: FAIL because the `operations` models and DATA-05 closure record do not yet exist.

- [ ] **Step 3: Create the minimal typed models and schema-2 matrix parser**

```python
class ClosureEvidenceRecord(BaseModel):
    closure_evidence_id: str
    issue_id: str
    requirement_version: str
    verification_run_ids: list[str]
    builder: str
    independent_reviewer: str
    review_result: Literal["approved", "rejected"]
    evidence_hash: str

    @model_validator(mode="after")
    def require_independent_reviewer(self) -> Self:
        if self.review_result == "approved" and self.builder == self.independent_reviewer:
            raise ValueError("independent_reviewer must differ from builder")
        return self
```

Set `programme_schema_version: 2`, `historic_baseline_count: 41`, and create a `DATA-05` record with `still_open` status and the source/schema/tests/UI/audit/package/browser gates specified in the approved specification.

- [ ] **Step 4: Run focused GREEN and regression checks**

Run: `.\.venv\Scripts\python.exe -m pytest tests\operations\test_verification_records.py tests\release\test_issue_evidence.py tests\test_closure_matrix.py -q`

Expected: PASS, with the historical 41 count preserved and 42 active records explicitly represented.

- [ ] **Step 5: Record the non-Git checkpoint**

Update the programme ledger, `RUN_STATE.json`, `.ai_worklog/PLAN.md` and `.ai_worklog/TESTING.md` with command, exit code, source checksum and the new matrix schema version. No commit step is permitted because the repository is not Git-backed.

